import os
import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv
from aiohttp import web

# ---- aiogram v3 ----
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

# ---- SQLAlchemy async ----
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import BigInteger, String, Text, ForeignKey, DateTime

# ----------------- базовая настройка -----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
DB_URL = os.getenv("DATABASE_URL")  # Render даст postgres://...  или postgresql://...

if not TOKEN:
    raise RuntimeError("No Telegram token found! Set BOT_TOKEN or TELEGRAM_TOKEN")

if not DB_URL:
    logging.warning("DATABASE_URL not set — using in-memory SQLite (for local dev)")
    DB_URL = "sqlite+aiosqlite:///:memory:"

# Преобразуем URL в async-формат для SQLAlchemy
def to_async_url(url: str) -> str:
    # Render часто выдает postgres:// — нужно заменить на postgresql+asyncpg://
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url  # уже aiosqlite или корректный async URL

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

# ----------------- aiogram -----------------
bot = Bot(TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def on_start(message: Message):
    # upsert пользователя
    async with Session() as s:
        u = await s.scalar(
            # ищем по tg_id
            s.sync_session.query(User).filter(User.tg_id == message.from_user.id)
        )  # type: ignore
        if not u:
            u = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
            s.add(u)
            await s.commit()
    await message.answer("Привет! Я Алина 🥰 Я работаю на Render и записываю сообщения в базу.")

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

    # Парсим: контакт — до первого пробела; всё остальное — как note
    parts = payload.split(maxsplit=1)
    contact = parts[0]
    note = parts[1] if len(parts) > 1 else None

    async with Session() as s:
        # гарантируем, что есть пользователь
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
        lead = Lead(user_id=u.id, contact=contact, note=note)
        s.add(lead)
        await s.commit()
    await message.answer("Заявка принята ✅ Мы свяжемся с тобой по указанному контакту.")

@dp.message(F.text)
async def log_and_echo(message: Message):
    # логируем любое входящее сообщение
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
    await message.answer(f"Принял: «{message.text}»")

# ----------------- healthcheck -----------------
async def health(_):
    return web.Response(text="ok")

async def start_web():
    app = web.Application()
    app.router.add_get("/healthz", health)
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    logging.info(f"Healthcheck on :{PORT}/healthz")
    await asyncio.Event().wait()

# ----------------- точка входа -----------------
async def main():
    await init_db()
    # снимаем webhook перед polling
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