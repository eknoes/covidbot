import argparse
import configparser
import locale
import logging

from mysql.connector import connect, MySQLConnection
from mysql.connector.conversion import MySQLConverter

from covidbot.bot import Bot
from covidbot.covid_data import CovidData
from covidbot.user_manager import UserManager
from covidbot.telegram_interface import TelegramInterface


def parse_config(config_file: str):
    cfg = configparser.ConfigParser()
    cfg.read(config_file)
    return cfg


def get_connection(cfg) -> MySQLConnection:
    return connect(database=cfg['DATABASE'].get('DATABASE'),
                   user=cfg['DATABASE'].get('USER'),
                   password=cfg['DATABASE'].get('PASSWORD'),
                   port=cfg['DATABASE'].get('PORT'),
                   host=cfg['DATABASE'].get('HOST', 'localhost'))


def send_correction_report(bot: TelegramInterface):
    if input("Do you want to send a message to all users? (y/N)").upper() != "Y":
        exit(0)

    append_report = False
    if input("Do you want to append the current report? (y/N)").upper() == "Y":
        append_report = True

    line = input("Please write the message you want to send."
                 "You can review it before sending, basic HTML is allowed):\n")
    lines = []
    while True:
        if line:
            lines.append(line)
        else:
            break
        line = input()
    msg = '\n'.join(lines)

    print(f"\n{msg}\nAppend current report: {append_report}")
    if input("Press Y to send this message: ") == "Y":
        bot.message_all_users(msg, append_report)


# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO, filename="bot.log")
# Also write to stderr
logging.getLogger().addHandler(logging.StreamHandler())

if __name__ == "__main__":
    # Set locale
    try:
        locale.setlocale(locale.LC_ALL, 'de_DE.utf8')
    except Exception:
        logging.error("Can't set locale!")

    # Parse Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--message', help='Do not start the bot but send a message to all users',
                        action='store_true')
    args = parser.parse_args()
    config = parse_config("config.ini")
    api_key = config['TELEGRAM'].get('API_KEY')

    with get_connection(config) as conn:
        if args and args.message:
            data = CovidData(conn, disable_autoupdate=True)
        else:
            data = CovidData(conn)
        user_manager = UserManager(conn)
        bot = Bot(data, user_manager)
        telegram_bot = TelegramInterface(bot, api_key=api_key, dev_chat_id=config['TELEGRAM'].getint("DEV_CHAT"))

        if args and args.message:
            send_correction_report(telegram_bot)
        else:
            telegram_bot.run()
