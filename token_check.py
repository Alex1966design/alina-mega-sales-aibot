from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

bot = TeleBot(token='7964619241:AAFoFWilFMBrK9ep5QfD-wlGBupG2K3WoBw')

try:
    bot_info = bot.get_me()
except ApiTelegramException:
    print("Ошибка токена, проверьте его на правильность")
else:
    print("Токен валиден, бот авторизован")
