import logging

from covidbot.bot import Bot
from covidbot.covid_data import CovidData
from covidbot.file_based_subscription_manager import FileBasedSubscriptionManager
from covidbot.telegram_interface import TelegramInterface

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO, filename="bot.log")
# Also write to stderr
logging.getLogger().addHandler(logging.StreamHandler())

# Initialize Data
with open(".api_key", "r") as f:
    key = f.readline().rstrip("\n")

with open(".db_password", "r") as f:
    password = f.readline().rstrip("\n")
data = CovidData(db_user="covid_bot", db_password=password, db_name="covid_bot_db")
bot = TelegramInterface(Bot(data, FileBasedSubscriptionManager("user.json")), api_key=key)
bot.run()
