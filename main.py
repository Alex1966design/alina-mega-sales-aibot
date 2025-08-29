import os
from telegram.ext import Application, CommandHandler
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

async def start(update, context):
    await update.message.reply_text("Привет! Я Алина — нейро-чемпион по продажам 💬")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()
