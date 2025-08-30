import os
import asyncio
import logging

from dotenv import load_dotenv
from aiohttp import web
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# ---------- базовая настройка ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "10000"))  # Render передает порт в переменной PORT

# ---------- хендлеры бота ----------
async def start_cmd(update, context):
    await update.message.reply_text("Привет! Я Алина 🤖 Работаю на Render.")

async def echo_text(update, context):
    await update.message.reply_text(f"Ты написал: {update.message.text}")

# ---------- healthcheck для Render ----------
async def health(_request):
    return web.Response(text="ok")

async def start_web():
    app = web.Application()
    app.router.add_get("/healthz", health)
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    logging.info(f"Healthcheck running on :{PORT}/healthz")
    # держим процесс живым
    await asyncio.Event().wait()

# ---------- запуск бота (в отдельном потоке) ----------
def run_bot_blocking():
    if not TOKEN:
        raise RuntimeError("No Telegram token found! Set BOT_TOKEN or TELEGRAM_TOKEN")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_text))

    # run_polling — блокирующий; снимем webhook перед стартом
    async def _pre():
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logging.warning(f"delete_webhook failed: {e}")

    app.run_polling(
        initialize=_pre,  # выполнится перед запуском
        close_loop=False
    )

# ---------- точка входа ----------
async def main():
    web_task = asyncio.create_task(start_web())
    bot_task = asyncio.to_thread(run_bot_blocking)  # запускаем PTB в отдельном потоке
    await asyncio.gather(web_task, bot_task)

if __name__ == "__main__":
    asyncio.run(main())
