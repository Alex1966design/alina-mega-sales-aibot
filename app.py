import os
import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, Text, DateTime

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
DB_URL = os.getenv("DATABASE_URL")
if not TOKEN:
    raise RuntimeError("No Telegram token found! Set BOT_TOKEN or TELEGRAM_TOKEN")
if not DB_URL:
    raise RuntimeError("DATABASE_URL is not set")

def to_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url

ASYNC_DB_URL = to_async_url(DB_URL)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "tg_users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MessageLog(Base):
    __tablename__ = "tg_messages"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

engine = create_async_engine(ASYNC_DB_URL, echo=False, pool_pre_ping=True)
Session: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("DB ready ✓")

bot = Bot(TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def handle_start(message: Message):
    async with Session() as s:
        user = await s.scalar(s.sync_session.query(User).filter(User.tg_id == message.from_user.id))  # type: ignore
        if not user:
            user = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
            s.add(user)
            await s.commit()
    await message.answer("Привет! Я Алина 🤖. Пишу события в базу.")

@dp.message(Command("lead"))
async def handle_lead(message: Message):
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Использование: /lead <контакт> [примечание]")
    payload = args[1]
    parts = payload.split(maxsplit=1)
    contact = parts[0]
    note = parts[1] if len(parts) > 1 else None

    txt = f"LEAD | contact: {contact}" + (f" | note: {note}" if note else "")
    async with Session() as s:
        s.add(MessageLog(tg_id=message.from_user.id, text=txt))
        await s.commit()
    await message.answer("Заявка записана ✅")

@dp.message(F.text)
async def log_text(message: Message):
    async with Session() as s:
        s.add(MessageLog(tg_id=message.from_user.id, text=message.text or ""))
        await s.commit()
    await message.answer(f"Принято: «{message.text}»")

async def health(_):
    return web.Response(text="ok")

async def start_web():
    app = web.Application()
    app.router.add_get("/healthz", health)
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Healthcheck on :{PORT}/healthz")
    await asyncio.Event().wait()

async def main():
    await init_db()
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
