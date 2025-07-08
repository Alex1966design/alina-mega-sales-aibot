from dotenv import load_dotenv
load_dotenv()

import logging
import os
import openai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# 🔐 Ключи из .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_KEY

if not TELEGRAM_TOKEN or not OPENAI_KEY:
    raise ValueError("TELEGRAM_BOT_TOKEN или OPENAI_API_KEY не заданы в .env файле.")

logging.basicConfig(level=logging.INFO)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я Алина 🤖, нейро-чемпион по продажам 💬\n"
        "Напиши, что ты хочешь, чтобы я составила скрипт продаж 🧠"
    )

# Генерация скрипта продаж
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()

    # Формируем prompt для OpenAI
    prompt = (
        "Ты — дружелюбный, эффективный нейропродавец. "
        "Составь скрипт продаж, начиная с вопроса 'Да?', включи шаблоны по работе с возражениями, "
        "в разговорном стиле. Используй эмодзи, если уместно. Вот продукт или ситуация:\n\n"
        f"{user_message}"
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        script = response.choices[0].message.content
        await update.message.reply_text(f"Вот твой скрипт продаж:\n\n{script}")
    except Exception as e:
        logging.error(f"Ошибка OpenAI: {e}")
        await update.message.reply_text("⚠️ Не удалось сгенерировать скрипт. Попробуй ещё раз позже.")

# Инициализация и запуск бота
app = Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()
