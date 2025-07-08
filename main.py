import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я — Алина, нейро-чемпион по продажам. Напиши, что хочешь продать 🚀")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text

    prompt = (
        f"Ты — дружелюбный и убедительный эксперт по продажам. "
        f"Сейчас клиент написал: \"{user_input}\". "
        f"Сначала оцени, готов ли он сказать «Да». "
        f"Если да — предложи сценарий завершения сделки. "
        f"Если есть возражения — приведи мягкий шаблон отработки. "
        f"Обязательно говори простыми словами и поддерживай клиента."
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=500
        )

        bot_reply = response.choices[0].message.content
        await update.message.reply_text(bot_reply)

    except Exception as e:
        logging.error(f"OpenAI Error: {e}")
        await update.message.reply_text("Произошла ошибка при генерации ответа. Попробуйте снова.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()
