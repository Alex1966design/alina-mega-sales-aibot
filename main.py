import os
import asyncio
import logging

from dotenv import load_dotenv
from aiohttp import web
from aiogram import Bot, Dispatcher, types

# Загружаем переменные окружения
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "10000"))  # Render передаёт порт сюда

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

logging.basicConfig(level=logging.INFO)

# --- Бот ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.reply("Привет! 🚀 Я Алина — нейро-чемпион по продажам!")

# --- Healthcheck ---
async def health(request):
    return web.Response(text="OK")

async def start_web():
    app = web.Application()
    app.router.add_get("/healthz", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# --- Запуск ---
def run_bot_blocking():
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)

async def main():
    web_task = asyncio.create_task(start_web())
    bot_task = asyncio.to_thread(run_bot_blocking)
    await asyncio.gather(web_task, bot_task)

if __name__ == "__main__":
    asyncio.run(main())
