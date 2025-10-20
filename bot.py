# -*- coding: utf-8 -*-
import os
import asyncio
from aiogram import Bot

# --- Проверка токена ---
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("❌ Ошибка: не найден TELEGRAM_TOKEN или BOT_TOKEN в переменных окружения!")

# Проверка токена только при запуске (один раз)
async def check_token_validity():
    bot = Bot(token=TOKEN)
    try:
        me = await bot.get_me()
        print(f"✅ Токен активен! Бот авторизован как @{me.username}")
    except Exception as e:
        print(f"❌ Ошибка авторизации токена: {e}")
        raise
    finally:
        await bot.session.close()

# Запускаем проверку (однократно)
asyncio.run(check_token_validity())

import asyncio
asyncio.run(check_token_validity())
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from aiohttp import web
# ---- aiogram v3 ----
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, Update

# ---- SQLAlchemy async ----
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import BigInteger, String, Text, ForeignKey, DateTime

# ---- OpenAI (async) ----
from openai import AsyncOpenAI

# ----------------- базовая настройка -----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Режим работы: 'polling' (локально) или 'webhook' (Railway)
MODE = os.getenv("MODE", "polling").lower()

PORT = int(os.getenv("PORT", "10000"))
DB_URL = os.getenv("DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # пример: https://<app>.up.railway.app
WEBHOOK_PATH = f"/webhook/{(TOKEN or '')[:10]}"

if not TOKEN:
    raise RuntimeError("No Telegram token found! Set BOT_TOKEN or TELEGRAM_TOKEN")

if not DB_URL:
    logging.warning("DATABASE_URL not set — using in-memory SQLite (for local dev)")
    DB_URL = "sqlite+aiosqlite:///:memory:"

# Преобразуем URL в async-формат для SQLAlchemy
def to_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url

ASYNC_DB_URL = to_async_url(DB_URL)

# --------- SQLAlchemy модели ---------
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "tg_users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[list["MessageLog"]] = relationship(back_populates="user", cascade="all,delete-orphan")
    leads: Mapped[list["Lead"]] = relationship(back_populates="user", cascade="all,delete-orphan")

class MessageLog(Base):
    __tablename__ = "tg_messages"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tg_users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="messages")

class Lead(Base):
    __tablename__ = "tg_leads"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tg_users.id", ondelete="CASCADE"), index=True)
    contact: Mapped[str] = mapped_column(String(256))   # телефон/почта/телеграм
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="leads")

# --------- движок и сессии ---------
engine = create_async_engine(ASYNC_DB_URL, echo=False, pool_pre_ping=True)
Session: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("DB ready ✅")

# ----------------- OpenAI -----------------
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", """
Ты — Алина, нейро-продавец. Отвечай дружелюбно и по делу.
Цель: быстро квалифицировать запрос и предложить следующий шаг.
Всегда уточняй: задачу, сроки, бюджет и контакт. Предлагай оставить контакт через /lead <контакт> [комментарий].
""".strip())

async def generate_reply(user_text: str, username: str | None = None) -> str:
    if not client:
        return f"Принял: «{user_text}»"
    try:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text if not username else f"Пользователь @{username}: {user_text}"}
            ],
            temperature=0.4,
            max_tokens=350,
            timeout=30,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logging.exception(f"OpenAI error: {e}")
        return "Сервис ИИ временно недоступен. Я записала запрос и отвечу позже."

# ----------------- aiogram -----------------
bot = Bot(TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def on_start(message: Message):
    # upsert пользователя
    async with Session() as s:
        u = await s.scalar(s.sync_session.query(User).filter(User.tg_id == message.from_user.id))  # type: ignore
        if not u:
            u = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
            s.add(u)
            await s.commit()
    await message.answer("Привет! Я Алина 🤖 Помогу с автоматизацией продаж. Чем могу быть полезна?")

@dp.message(Command("lead"))
async def create_lead(message: Message):
    """
    /lead <контакт> [примечание]
    Пример: /lead +34 600 123 456 нужен расчет по тарифам
    """
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пришли контакт после команды:\n/lead <контакт> [примечание]")
    payload = args[1]
    parts = payload.split(maxsplit=1)
    contact = parts[0]
    note = parts[1] if len(parts) > 1 else None

    async with Session() as s:
        u = await s.scalar(s.sync_session.query(User).filter(User.tg_id == message.from_user.id))  # type: ignore
        if not u:
            u = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
            s.add(u)
            await s.flush()
        s.add(Lead(user_id=u.id, contact=contact, note=note))
        await s.commit()
    await message.answer("Заявка принята ✅ Мы свяжемся по указанному контакту.")

@dp.message(F.text)
async def log_and_respond(message: Message):
    # логируем
    async with Session() as s:
        u = await s.scalar(s.sync_session.query(User).filter(User.tg_id == message.from_user.id))  # type: ignore
        if not u:
            u = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
            s.add(u)
            await s.flush()
        s.add(MessageLog(user_id=u.id, text=message.text or ""))
        await s.commit()

    # «печатает…» пока ждём LLM
    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    reply = await generate_reply(message.text or "", message.from_user.username)
    await message.answer(reply)

# ----------------- healthcheck & webhook -----------------
async def health(_):
    return web.Response(text="ok")

async def webhook(request: web.Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def start_web():
    app = web.Application()
    app.router.add_get("/healthz", health)
    app.router.add_get("/", health)
    app.router.add_post(WEBHOOK_PATH, webhook)  # для webhook-режима
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    logging.info(f"Healthcheck on :{PORT}/healthz")
    logging.info(f"Webhook path mounted at {WEBHOOK_PATH}")
    await asyncio.Event().wait()

# ----------------- точка входа -----------------
async def main():
    await init_db()

    if MODE == "webhook":
        if not WEBHOOK_URL:
            raise RuntimeError("WEBHOOK_URL not set (e.g., https://<project>.up.railway.app)")
        # ставим вебхук
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}", drop_pending_updates=True)
        logging.info(f"Webhook set to {WEBHOOK_URL}{WEBHOOK_PATH}")
        await start_web()  # только веб-сервер
    else:
        # локальная разработка — polling + healthcheck
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logging.warning(f"delete_webhook failed: {e}")

        await asyncio.gather(
            dp.start_polling(bot),
            start_web()
        )

if __name__ == "__main__":
    asyncio.run(main())
# updated manually for redeploy
