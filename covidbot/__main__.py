import logging

from covidbot.bot import Bot
from covidbot.covid_data import CovidData
from covidbot.subscription_manager import SubscriptionManager
from covidbot.telegram_interface import TelegramInterface

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO, filename="bot.log")
# Also write to stderr
logging.getLogger().addHandler(logging.StreamHandler())

# Initialize Data
with open(".api_key", "r") as f:
    key = f.readline()

bot = TelegramInterface(Bot(CovidData(), SubscriptionManager("user.json")), api_key=key)
bot.run()
