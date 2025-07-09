
python
from telegram.ext import Application, CommandHandler

TELEGRAM_TOKEN = "7598269211:AAH5zTrpyfQ5R1fGUS6M8rSi_vD-GgE_DOI"

async def start(update, context):
    await update.message.reply_text("Привет! Я Алина — нейро-чемпион по продажам 💬")

def main():
    print(f"TELEGRAM_TOKEN: {repr(TELEGRAM_TOKEN)}")  # Выведет токен в лог
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()
