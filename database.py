import aiosqlite
import json
from config import DATABASE_FILE, MAINTENANCE_FILE

async def init_db():
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                phone TEXT UNIQUE,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица товаров
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                price REAL NOT NULL,
                discount_price REAL DEFAULT NULL,
                description TEXT,
                category TEXT NOT NULL,
                drop_collection TEXT,
                measurements_photo TEXT,
                is_hidden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица вариаций товаров по цветам, размерам и фото
        await db.execute("""
            CREATE TABLE IF NOT EXISTS product_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                color TEXT NOT NULL,
                sizes_stock TEXT NOT NULL, -- Хранится в JSON: {"S": 10, "M": 5, "L": 0}
                photo_front TEXT,
                photo_back TEXT,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)

        # Таблица заказов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_phone TEXT NOT NULL,
                telegram_username TEXT,
                full_name TEXT NOT NULL,
                city TEXT NOT NULL,
                post_office TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                product_title TEXT NOT NULL,
                color TEXT NOT NULL,
                size TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                total_price REAL NOT NULL,
                comment TEXT,
                status TEXT DEFAULT 'pending', -- pending, confirmed, ttn_created, packed, shipped, cancelled
                ttn TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """)

        # Таблица бегущей строки (настройки)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        await db.commit()

# Функции работы с сайтом и техперерывом
def is_maintenance_mode() -> bool:
    try:
        with open(MAINTENANCE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() == "closed"
    except FileNotFoundError:
        return False

def set_maintenance_mode(closed: bool):
    with open(MAINTENANCE_FILE, "w", encoding="utf-8") as f:
        f.write("closed" if closed else "open")

async def set_running_line(text: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('running_line', ?)",
            (text,)
        )
        await db.commit()

async def get_running_line() -> str:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'running_line'") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else ""

async def delete_running_line():
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("DELETE FROM settings WHERE key = 'running_line'")
        await db.commit()