# -*- coding: utf-8 -*-
import os
import asyncio
import logging
from datetime import datetime
from typing import Callable, Awaitable, Any, Optional

from dotenv import load_dotenv
from aiohttp import web

# aiogram v3
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, Update
from aiogram.enums import ChatAction

# SQLAlchemy async
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import BigInteger, String, Text, ForeignKey, DateTime, select

# OpenAI (async, v1.x preferred)
from openai import AsyncOpenAI


# ----------------- CONFIG -----------------
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("root")

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# В Railway оставляем MODE=polling (рекомендуется). Webhook включаем только явно.
MODE = os.getenv("MODE", "polling").strip().lower()  # polling | webhook
PORT = int(os.getenv("PORT", "8080"))

DB_URL = os.getenv("DATABASE_URL")  # можно не задавать → будет SQLite
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # только для MODE=webhook, напр. https://<app>.up.railway.app
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")  # рекомендовано: случайная строка

if not TOKEN:
    raise RuntimeError("BOT_TOKEN / TELEGRAM_TOKEN is not set")

# Диагностика (без вывода токена)
log.info(
    "Env check -> TELEGRAM_TOKEN: %s, BOT_TOKEN: %s, MODE: %s, OPENAI: %s",
    "set" if os.getenv("TELEGRAM_TOKEN") else "missing",
    "set" if os.getenv("BOT_TOKEN") else "missing",
    MODE,
    "set" if OPENAI_API_KEY else "missing",
)


# ----------------- DB -----------------
def to_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url

if not DB_URL:
    log.warning("DATABASE_URL not set — using SQLite (./local.db)")
    DB_URL = "sqlite+aiosqlite:///./local.db"

ASYNC_DB_URL = to_async_url(DB_URL)

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
    contact: Mapped[str] = mapped_column(String(256))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="leads")

engine = create_async_engine(ASYNC_DB_URL, echo=False, pool_pre_ping=True)
Session: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("DB ready ✅")


async def get_or_create_user(message: Message) -> User:
    async with Session() as s:
        res = await s.execute(select(User).where(User.tg_id == message.from_user.id))
        u = res.scalar_one_or_none()
        if not u:
            u = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
            s.add(u)
            await s.commit()
        return u


async def log_user_message(tg_id: int, text: str) -> None:
    async with Session() as s:
        res = await s.execute(select(User).where(User.tg_id == tg_id))
        u = res.scalar_one_or_none()
        if not u:
            # крайне редко, но безопасно
            u = User(tg_id=tg_id)
            s.add(u)
            await s.flush()
        s.add(MessageLog(user_id=u.id, text=text))
        await s.commit()


async def get_recent_user_messages(tg_id: int, limit: int = 4) -> list[str]:
    """
    Минимальная память: последние сообщения пользователя (user-only) из БД.
    Без миграций и без хранения ассистента.
    """
    async with Session() as s:
        res = await s.execute(
            select(MessageLog.text)
            .join(User, User.id == MessageLog.user_id)
            .where(User.tg_id == tg_id)
            .order_by(MessageLog.created_at.desc())
            .limit(limit)
        )
        rows = res.all()
    # rows: newest->oldest -> reverse to chronological
    return [r[0] for r in reversed(rows)]


# ----------------- OpenAI -----------------
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    """
Ты — «Алина», AI Support/Sales Assistant для автоматизации на базе n8n и CRM (например GHL).
Твоя задача: быстро собрать требования пользователя и подготовить структурированный контекст для запуска workflow.

Правила:
- Действуй коротко и по делу. 1–3 вопроса за раз.
- Не веди бесконечный диалог: максимум 2 итерации уточнений, затем резюме.
- Всегда завершай ответ блоком:
  (1) РЕЗЮМЕ (bullet points)
  (2) STRUCTURED BRIEF (валидный JSON)
  (3) Вопрос: "Подтверждаете? (да/нет)"
- Если пользователь отвечает "да": ответь "Принято. Запускаю следующий шаг." и НЕ задавай новых вопросов.
- Если "нет": спроси, что исправить, и повтори резюме+JSON.

Минимум, который нужно собрать:
- задача/цель
- источники/каналы (Telegram/сайт/CRM/источники данных)
- период/частота
- формат результата
- ограничения (язык/тон/объём)
- контакт (если уместно)

Выходной JSON (структура фиксирована):
{
  "intent": "content_workflow|lead_capture|support|other",
  "summary": "1-2 предложения",
  "requirements": {
    "topic": "",
    "sources": [],
    "time_range": "",
    "frequency": "",
    "output_format": "",
    "channels": [],
    "language": "",
    "constraints": []
  },
  "next_step": "handoff_to_n8n|schedule_call|need_more_info",
  "questions_remaining": []
}

Всегда печатай JSON под заголовком: STRUCTURED BRIEF
""".strip(),
)

def _normalize_yes_no(text: str) -> Optional[str]:
    t = (text or "").strip().lower()
    yes = {"да", "ok", "ок", "yes", "y", "ага", "угу"}
    no = {"нет", "no", "n", "неа"}
    if t in yes:
        return "yes"
    if t in no:
        return "no"
    return None

async def generate_reply(
    user_text: str,
    username: str | None = None,
    history: Optional[list[str]] = None,
    req_id: str = "",
) -> str:
    if not client:
        return (
            f"Приняла: «{user_text}». Уточните задачу, сроки и бюджет.\n"
            f"Контакт можно оставить: /lead <контакт> [комментарий]"
        )

    user_prefix = "" if not username else f"Пользователь @{username}: "
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # добавляем историю (user-only), чтобы модель не теряла контекст
    if history:
        for h in history:
            # защитимся от слишком длинных сообщений
            hh = (h or "").strip()
            if not hh:
                continue
            if len(hh) > 800:
                hh = hh[:800] + "…"
            messages.append({"role": "user", "content": user_prefix + hh})

    # текущий ввод (в конце)
    current = user_text if not username else f"Пользователь @{username}: {user_text}"
    messages.append({"role": "user", "content": current})

    log.info("req_id=%s | OpenAI call | model=%s | hist=%s", req_id, OPENAI_MODEL, len(history or []))

    # 1 retry на transient ошибки
    for attempt in (1, 2):
        try:
            resp = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.35,
                max_tokens=450,
                timeout=30,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            log.warning("req_id=%s | OpenAI attempt %s failed: %s", req_id, attempt, e)
            if attempt == 2:
                log.exception("req_id=%s | OpenAI error final: %s", req_id, e)
                return "Сервис ИИ временно недоступен. Уточните задачу, сроки, формат результата. Контакт: /lead <контакт> [комментарий]"
            await asyncio.sleep(0.8)

    return "Сервис ИИ временно недоступен. Попробуйте ещё раз позже."


# ----------------- aiogram -----------------
bot = Bot(token=TOKEN)
dp = Dispatcher()

class ErrorMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict], Awaitable[Any]],
        event: Any,
        data: dict
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as e:
            log.exception("Handler error: %s", e)
            if isinstance(event, Message):
                try:
                    await event.answer("Техническая ошибка. Я уже зафиксировала проблему, попробуйте ещё раз через минуту.")
                except Exception:
                    pass
            return None

# Централизованный error handling для message handlers
dp.message.middleware(ErrorMiddleware())


@dp.message(CommandStart())
async def on_start(message: Message):
    await get_or_create_user(message)
    await message.answer("Привет! Я Алина. Помогу с продажами/автоматизацией. Что нужно сделать?")


@dp.message(Command("lead"))
async def create_lead(message: Message):
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пришлите контакт после команды:\n/lead <контакт> [примечание]")

    payload = args[1]
    parts = payload.split(maxsplit=1)
    contact = parts[0]
    note = parts[1] if len(parts) > 1 else None

    async with Session() as s:
        res = await s.execute(select(User).where(User.tg_id == message.from_user.id))
        u = res.scalar_one_or_none()
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

    await message.answer("Заявка принята ✅")


@dp.message(F.text)
async def log_and_respond(message: Message):
    text = (message.text or "").strip()
    if not text:
        return

    req_id = f"{message.chat.id}-{message.message_id}"
    log.info("req_id=%s | incoming: %r", req_id, text[:200])

    # Логируем сообщение пользователя
    await log_user_message(message.from_user.id, text)

    # Guardrail: подтверждение handoff (да/нет)
    yn = _normalize_yes_no(text)
    if yn == "yes":
        log.info("req_id=%s | handoff confirmed", req_id)
        return await message.answer("Принято. Запускаю следующий шаг.")
    # если "нет" — пусть модель уточнит, что исправить (идём дальше)

    try:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception:
        pass

    # История последних сообщений (user-only)
    history = await get_recent_user_messages(message.from_user.id, limit=4)

    reply = await generate_reply(
        user_text=text,
        username=message.from_user.username,
        history=history,
        req_id=req_id,
    )

    await message.answer(reply)


# ----------------- HTTP (health + optional webhook) -----------------
async def health(_request: web.Request):
    return web.Response(text="ok")

async def webhook_handler(request: web.Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def start_http_server(with_webhook: bool):
    app = web.Application()
    app.router.add_get("/healthz", health)
    app.router.add_get("/", health)

    if with_webhook:
        # Секретный путь (лучше, чем id или кусок токена)
        secret = WEBHOOK_SECRET or (TOKEN[:12])
        path = f"/webhook/{secret}"
        app.router.add_post(path, webhook_handler)
        log.info("Webhook path mounted at %s", path)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    log.info("Healthcheck on :%s/healthz", PORT)
    await asyncio.Event().wait()


# ----------------- MAIN -----------------
async def main():
    await init_db()

    if MODE == "webhook":
        if not WEBHOOK_URL:
            raise RuntimeError("MODE=webhook but WEBHOOK_URL is not set (e.g. https://<app>.up.railway.app)")

        secret = WEBHOOK_SECRET or (TOKEN[:12])
        webhook_path = f"/webhook/{secret}"
        webhook_full = f"{WEBHOOK_URL}{webhook_path}"

        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(webhook_full, drop_pending_updates=True)
        log.info("Webhook set to %s", webhook_full)

        await asyncio.gather(
            start_http_server(with_webhook=True),
        )
    else:
        # polling (рекомендовано для демо и Railway)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            log.warning("delete_webhook failed: %s", e)

        log.info("Starting polling...")
        await asyncio.gather(
            dp.start_polling(bot),
            start_http_server(with_webhook=False),  # только healthz
        )


if __name__ == "__main__":
    asyncio.run(main())
