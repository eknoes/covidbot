import logging
import argparse

import psycopg2
from psycopg2.extras import DictCursor

from covidbot.bot import Bot
from covidbot.covid_data import CovidData
from covidbot.file_based_subscription_manager import FileBasedSubscriptionManager
from covidbot.subscription_manager import SubscriptionManager
from covidbot.telegram_interface import TelegramInterface

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO, filename="bot.log")
# Also write to stderr
logging.getLogger().addHandler(logging.StreamHandler())

# Add arguments

parser = argparse.ArgumentParser()
parser.add_argument('--message', help='Do not start the bot but send a message to all users', action='store_true')
parser.add_argument('--migrate', help='Do not start the bot but migrate users from file-based manager to database',
                    action='store_true')
args = parser.parse_args()

# Initialize Data
with open(".api_key", "r") as f:
    key = f.readline().rstrip("\n")

with open(".db_password", "r") as f:
    password = f.readline().rstrip("\n")

conn = psycopg2.connect(dbname="covid_bot_db", user="covid_bot", password=password, port=5432,
                        host='localhost', cursor_factory=DictCursor)

data = CovidData(db_user="covid_bot", db_password=password, db_name="covid_bot_db")
user_manager = SubscriptionManager(conn)
bot = TelegramInterface(Bot(data, user_manager), api_key=key)

if args.message:
    print()
    if input("If you want to sent a correction message with the current report to all users, press Y: ") != "Y":
        exit(0)

    line = input("Message (Basic HTML allowed):\n")
    lines = []
    while True:
        if line:
            lines.append(line)
        else:
            break
        line = input()
    msg = '\n'.join(lines)

    print(f"\n\n{msg}\n\n")
    if input("Press Y to send this message: ") == "Y":
        bot.send_correction_message(msg)
elif args.migrate:
    file_manager = FileBasedSubscriptionManager("user.json")
    user_manager.migrate_from(file_manager)
else:
    bot.run()
