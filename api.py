import os
import httpx
import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import json
from fastapi.responses import HTMLResponse, RedirectResponse

from config import DATABASE_FILE, BOT_TOKEN, ADMIN_ID
from database import is_maintenance_mode, get_running_line

# Создаем приложение FastAPI
app = FastAPI(title="API Три кота")

# Разрешаем CORS, чтобы фронтенд мог без проблем стучаться к API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# PYDANTIC МОДЕЛИ ДЛЯ ЗАКАЗА
# ==========================================
class OrderItem(BaseModel):
    product_title: str
    color: str
    size: str
    quantity: int
    price: float

class OrderRequest(BaseModel):
    full_name: str
    phone: str
    telegram_username: Optional[str] = ""
    city: str
    post_office: str
    comment: Optional[str] = ""
    items: List[OrderItem]

# ==========================================
# ENDPOINTS (АПИ)
# ==========================================

@app.get("/api/state")
async def get_site_state():
    """Отдает статус сайта (тех. работы) и текст бегущей строки"""
    maintenance = await is_maintenance_mode()
    running_line = await get_running_line()
    return {
        "maintenance": maintenance,
        "running_line": running_line
    }

@app.get("/api/image-proxy")
async def image_proxy(file_id: str):
    """Превращает Telegram file_id в рабочую временную ссылку на скачивание фото"""
    async with httpx.AsyncClient() as client:
        try:
            # 1. Запрашиваем путь к файлу у Telegram API
            r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}")
            data = r.json()
            if data.get("ok"):
                file_path = data["result"]["file_path"]
                # 2. Формируем прямую ссылку на файл на серверах Telegram
                download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                # 3. Перенаправляем браузер на эту картинку
                return RedirectResponse(url=download_url)
        except Exception as e:
            print(f"Ошибка проксирования картинки: {e}")
            
    raise HTTPException(status_code=404, detail="Image not found")

@app.get("/api/products")
async def get_products():
    """Отдает все активные товары вместе с их цветами, размерами и фотографиями из базы данных"""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'") as cursor:
                if not await cursor.fetchone():
                    return {"products": []}

            async with db.execute("""
                SELECT id, title, description, price, discount_price, category 
                FROM products 
                WHERE is_hidden = 0 OR is_hidden IS NULL
            """) as cursor:
                products_data = await cursor.fetchall()
                
            products = []
            for p in products_data:
                p_id, title, desc, price, discount_price, category = p
                
                variants = []
                media_list = []
                
                try:
                    async with db.execute("""
                        SELECT color, sizes_stock, photo_front, photo_back 
                        FROM product_variants 
                        WHERE product_id = ?
                    """, (p_id,)) as v_cursor:
                        variants_data = await v_cursor.fetchall()
                        
                    for v in variants_data:
                        color, sizes_json, photo_front, photo_back = v
                        
                        sizes = []
                        if sizes_json:
                            try:
                                stock_dict = json.loads(sizes_json)
                                if isinstance(stock_dict, dict):
                                    sizes = [size for size, qty in stock_dict.items() if qty > 0]
                                elif isinstance(stock_dict, list):
                                    sizes = stock_dict
                            except Exception:
                                sizes = [str(sizes_json)]

                        variants.append({
                            "color": color,
                            "sizes": sizes
                        })
                        
                        HOST = "http://127.0.0.1:8000"
                        
                        # Если это Telegram file_id (начинается с AgAC или похоже на него) или просто относительный путь
                        for photo in [photo_front, photo_back]:
                            if photo:
                                if photo.startswith("http"):
                                    img_url = photo
                                elif len(photo) > 20 and not "/" in photo and not "\\" in photo:
                                    # Это Telegram file_id, заворачиваем через наш прокси-эндпоинт
                                    img_url = f"{HOST}/api/image-proxy?file_id={photo}"
                                elif photo.startswith("/"):
                                    img_url = HOST + photo
                                else:
                                    img_url = HOST + "/" + photo
                                    
                                if img_url not in media_list:
                                    media_list.append(img_url)
                                    
                except Exception as e:
                    print(f"Ошибка при загрузке вариантов для товара {p_id}: {e}")
                    
                products.append({
                    "id": p_id,
                    "title": title,
                    "description": desc,
                    "price": discount_price if discount_price else price,
                    "media_urls": media_list,
                    "variants": variants
                })
                
        return {"products": products}
    except Exception as e:
        print(f"Помилка при отриманні товарів: {e}")
        return {"products": []}

@app.post("/api/checkout")
async def process_checkout(order: OrderRequest):
    phone = order.phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone

    tg_user = order.telegram_username.replace("@", "") if order.telegram_username else ""

    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            INSERT INTO users (phone, telegram_username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET 
                telegram_username=excluded.telegram_username,
                full_name=excluded.full_name
        """, (phone, tg_user, order.full_name))
        
        created_order_ids = []
        total_order_sum = 0
        
        for item in order.items:
            total_price = item.price * item.quantity
            total_order_sum += total_price
            
            cursor = await db.execute("""
                INSERT INTO orders (user_phone, telegram_username, full_name, city, post_office, 
                                    product_title, color, size, quantity, total_price, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (phone, tg_user, order.full_name, order.city, order.post_office, 
                  item.product_title, item.color, item.size, item.quantity, total_price, order.comment))
            
            created_order_ids.append(cursor.lastrowid)
            
        await db.commit()

    items_text = ""
    for item in order.items:
        items_text += f"▫️ {item.product_title} | {item.color} | {item.size} | {item.quantity} шт. | {item.price * item.quantity} UAH\n"

    tg_link = f"@{tg_user}" if tg_user else "не вказано"
    
    admin_msg = (
        f"🚨 <b>НОВЫЙ ЗАКАЗ С САЙТА!</b>\n\n"
        f"<b>Покупатель:</b> {order.full_name}\n"
        f"<b>Телефон:</b> <code>{phone}</code>\n"
        f"<b>Telegram:</b> {tg_link}\n"
        f"<b>Город:</b> {order.city}\n"
        f"<b>Отделение:</b> {order.post_office}\n"
        f"<b>Комментарий:</b> {order.comment or '-'}\n\n"
        f"<b>Товары:</b>\n{items_text}\n"
        f"<b>Общая сумма:</b> <b>{total_order_sum} UAH</b>\n\n"
        f"👉 <i>Перейдите в бота /admin для управления заказом.</i>"
    )

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_ID,
                    "text": admin_msg,
                    "parse_mode": "HTML"
                }
            )
        except Exception as e:
            print(f"Ошибка отправки уведомления админу: {e}")

    return {"status": "success", "message": "Замовлення успішно створено", "order_ids": created_order_ids}

@app.get("/", response_class=HTMLResponse)
@app.get("/catalog", response_class=HTMLResponse)
async def serve_catalog():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()