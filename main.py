from dotenv import load_dotenv
load_dotenv()

import logging
import openai
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# 🔐 Получаем ключи из .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise ValueError("TELEGRAM_BOT_TOKEN или OPENAI_API_KEY не заданы в .env файле.")

logging.basicConfig(level=logging.INFO)

# 🧠 Простая база состояний пользователей
user_states = {}

# 👋 Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я Алина, нейро-чемпион по продажам 🤖\nНапиши, что ты хочешь продавать.")

# 💬 Основной сценарий общения
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_states:
        user_states[user_id] = {"stage": "ask_product"}
        await update.message.reply_text("Алина на связи 🤖 Что ты хочешь продать?")
        return

    state = user_states[user_id]

    # Стадия 1 — получаем продукт
    if state["stage"] == "ask_product":
        product = text
        user_states[user_id]["product"] = product
        user_states[user_id]["stage"] = "generated_usp"

        prompt = (
            f"Ты — опытный нейропродавец. Напиши короткое и цепляющее УТП в дружелюбном стиле "
            f"для продукта: {product}. УТП должно быть максимум в 2 предложениях."
        )

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            usp = response.choices[0].message.content
            await update.message.reply_text(f"Вот что я придумала:\n\n💡 *{usp}*", parse_mode="Markdown")
            await update.message.reply_text("Хочешь, помогу с обработкой возражений или составлю структуру скрипта?")
        except Exception as e:
            await update.message.reply_text("Произошла ошибка при обращении к OpenAI 😥")
            logging.error(e)

        return

    # Стадия 2 — пользователь отвечает "Да"
    if text.lower() == "да" and state["stage"] == "generated_usp":
        product = state["product"]
        user_states[user_id]["stage"] = "done"

        prompt = (
            f"Ты — нейропродавец с дружелюбным стилем общения. Напиши скрипт продаж для продукта: {product}.\n"
            f"Структура: 1) Приветствие, 2) Выявление потребности, 3) Предложение (оффер), 4) Закрытие на действие.\n"
            f"Затем напиши 3 дружелюбных ответа на типичные возражения."
        )

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            script = response.choices[0].message.content
            await update.message.reply_text(f"📋 Вот твой скрипт продаж:\n\n{script}")
        except Exception as e:
            await update.message.reply_text("Не получилось сгенерировать скрипт 😢 Попробуй ещё раз позже.")
            logging.error(e)

        return

    # Ответ по умолчанию
    await update.message.reply_text("Напиши \"Да\", если хочешь, чтобы я составила скрипт продаж 💬")

# 🚀 Запуск бота
app = Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()
