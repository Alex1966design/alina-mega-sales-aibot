from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

bot = TeleBot(token='7598269211:AAH5zTrpyfQ5R1fGUS6M8rSi_vD-GgE_DOI')

try:
    bot_info = bot.get_me()
except ApiTelegramException:
    print("Ошибка токена, проверьте его на правильность")
else:
    print("Токен валиден, бот авторизован")