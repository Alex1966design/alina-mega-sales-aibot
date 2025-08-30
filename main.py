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

# ----------------- Р±Р°Р·РѕРiР°cЏ РЅР°cЃc‚cЂРѕР№РєР° -----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
DB_URL = os.getenv("DATABASE_URL")  # Render РґР°cЃc‚ postgres://...  РёР»Рё postgresql://...

if not TOKEN:
    raise RuntimeError("No Telegram token found! Set BOT_TOKEN or TELEGRAM_TOKEN")

if not DB_URL:
    logging.warning("DATABASE_URL not set вЂ” using in-memory SQLite (for local dev)")
    DB_URL = "sqlite+aiosqlite:///:memory:"

# РџcЂРµРѕР±cЂР°Р·cѓРµРј URL Рi async-c„РѕcЂРјР°c‚ РґР»cЏ SQLAlchemy
def to_async_url(url: str) -> str:
    # Render c‡Р°cЃc‚Рѕ Рic‹РґР°c‘c‚ postgres:// вЂ” РЅcѓР¶РЅРѕ Р·Р°РјРµРЅРёc‚cЊ РЅР° postgresql+asyncpg://
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url  # cѓР¶Рµ aiosqlite РёР»Рё РєРѕcЂcЂРµРєc‚РЅc‹Р№ async URL

ASYNC_DB_URL = to_async_url(DB_URL)

# --------- SQLAlchemy РјРѕРґРµР»Рё ---------
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
    contact: Mapped[str] = mapped_column(String(256))   # c‚РµР»Рµc„РѕРЅ/РїРѕc‡c‚Р°/c‚РµР»РµРicЂР°Рј
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="leads")

# --------- РґРiРёР¶РѕРє Рё cЃРµcЃcЃРёРё ---------
engine = create_async_engine(ASYNC_DB_URL, echo=False, pool_pre_ping=True)
Session: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("DB ready вњ”")

# ----------------- aiogram -----------------
bot = Bot(TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def on_start(message: Message):
    # upsert РїРѕР»cЊР·РѕРiР°c‚РµР»cЏ
    async with Session() as s:
        u = await s.scalar(
            # Рёc‰РµРј РїРѕ tg_id
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
    await message.answer("РџcЂРёРiРµc‚! РЇ РђР»РёРЅР° рџ¤– РЇ cЂР°Р±Рѕc‚Р°cЋ РЅР° Render Рё Р·Р°РїРёcЃc‹РiР°cЋ cЃРѕРѕР±c‰РµРЅРёcЏ Рi Р±Р°Р·cѓ.")

@dp.message(Command("lead"))
async def create_lead(message: Message):
    """
    /lead <РєРѕРЅc‚Р°Рєc‚> [РїcЂРёРјРµc‡Р°РЅРёРµ]
    РџcЂРёРјРµcЂ: /lead +34 600 123 456 РЅcѓР¶РµРЅ cЂР°cЃc‡c‘c‚ РїРѕ c‚Р°cЂРёc„Р°Рј
    """
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("РџcЂРёc€Р»Рё РєРѕРЅc‚Р°Рєc‚ РїРѕcЃР»Рµ РєРѕРјР°РЅРґc‹:\n/lead <РєРѕРЅc‚Р°Рєc‚> [РїcЂРёРјРµc‡Р°РЅРёРµ]")
    payload = args[1]

    # РџР°cЂcЃРёРј: РєРѕРЅc‚Р°Рєc‚ вЂ” РґРѕ РїРµcЂРiРѕРiРѕ РїcЂРѕР±РµР»Р°; РicЃc‘ РѕcЃc‚Р°Р»cЊРЅРѕРµ вЂ” РєР°Рє note
    parts = payload.split(maxsplit=1)
    contact = parts[0]
    note = parts[1] if len(parts) > 1 else None

    async with Session() as s:
        # РiР°cЂР°РЅc‚РёcЂcѓРµРј, c‡c‚Рѕ РµcЃc‚cЊ РїРѕР»cЊР·РѕРiР°c‚РµР»cЊ
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
    await message.answer("Р—Р°cЏРiРєР° РїcЂРёРЅcЏc‚Р° вњ…. Рњc‹ cЃРicЏР¶РµРјcЃcЏ cЃ c‚РѕР±РѕР№ РїРѕ cѓРєР°Р·Р°РЅРЅРѕРјcѓ РєРѕРЅc‚Р°Рєc‚cѓ.")

@dp.message(F.text)
async def log_and_echo(message: Message):
    # Р»РѕРiРёcЂcѓРµРј Р»cЋР±РѕРµ Рic…РѕРґcЏc‰РµРµ cЃРѕРѕР±c‰РµРЅРёРµ
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
    await message.answer(f"РџcЂРёРЅcЏР»: В«{message.text}В»")

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

# ----------------- c‚Рѕc‡РєР° Рic…РѕРґР° -----------------
async def main():
    await init_db()
    # cЃРЅРёРјР°РµРј webhook РїРµcЂРµРґ polling
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

