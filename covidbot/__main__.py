import argparse
import configparser
import locale
import logging
import re
import sys
from functools import reduce
from typing import Optional

from mysql.connector import connect, MySQLConnection

from covidbot.bot import Bot
from covidbot.covid_data import CovidData
from covidbot.messenger_interface import MessengerInterface
from covidbot.signal_interface import SignalInterface
from covidbot.telegram_interface import TelegramInterface
from covidbot.text_interface import InteractiveInterface
from covidbot.threema_interface import ThreemaInterface
from covidbot.user_manager import UserManager


def parse_config(config_file: str):
    cfg = configparser.ConfigParser()
    cfg.read(config_file)
    return cfg


def get_connection(cfg, autocommit=False) -> MySQLConnection:
    return connect(database=cfg['DATABASE'].get('DATABASE'),
                   user=cfg['DATABASE'].get('USER'),
                   password=cfg['DATABASE'].get('PASSWORD'),
                   port=cfg['DATABASE'].get('PORT'),
                   host=cfg['DATABASE'].get('HOST', 'localhost'), autocommit=autocommit)


def strip_html(text: str) -> str:
    # Simple replace, as it is just used for interfaces that do not support scripting in any way
    return re.sub('<[^<]+?>', "", text)


def get_messenger_interface(name: str, config, loglvl=logging.INFO) -> Optional[MessengerInterface]:
    # Setup Logging
    logging.basicConfig(format=logging_format, level=loglvl, filename="signal-bot.log")

    # Log also to stdout
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(logging_format))
    logging.getLogger().addHandler(stream_handler)

    if name != "signal" and name != "threema" and name != "telegram" and name != "interactive":
        logging.error(f"Invalid messenger interface was requested: {name}")
        return None

    # Do not activate user on Threema automatically
    users_activated = True
    if name == "threema":
        users_activated = False

    # Setup CovidData, Bot and UserManager
    data = CovidData(get_connection(config))
    user_manager = UserManager(name, get_connection(config, True), activated_default=users_activated)
    bot = Bot(data, user_manager)

    # Return specific interface
    if name == "threema":
        return ThreemaInterface(config['THREEMA'].get('ID'), config['THREEMA'].get('SECRET'),
                                config['THREEMA'].get('PRIVATE_KEY'), bot)

    if name == "signal":
        return SignalInterface(config['SIGNAL'].get('PHONE_NUMBER'),
                               config['SIGNAL'].get('SIGNALD_SOCKET'), bot)

    if name == "telegram":
        return TelegramInterface(bot, api_key=config['TELEGRAM'].get('API_KEY'),
                                 dev_chat_id=config['TELEGRAM'].getint("DEV_CHAT"))

    if name == "interactive":
        return InteractiveInterface(bot)


if __name__ == "__main__":
    logging_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging_level = logging.INFO

    # Set locale
    try:
        locale.setlocale(locale.LC_ALL, 'de_DE.utf8')
    except Exception:
        logging.error("Can't set locale!")

    # Parse Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--interactive', help='Chat with Textbot', action='store_true')
    parser.add_argument('--threema', help='Use Threema', action='store_true')
    parser.add_argument('--telegram', help='Use Telegram', action='store_true')
    parser.add_argument('--signal', help='Use Signal', action='store_true')
    parser.add_argument('--verbose', '-v', action='count', default=0)

    args = parser.parse_args()

    if args.verbose and args.verbose > 0:
        logging_level = logging.DEBUG

    if reduce(lambda x, y: int(x) + int(y), [args.signal, args.telegram, args.interactive, args.threema]) != 1:
        print("Exactly one interface-flag has to be set, e.g. --telegram")
        sys.exit(1)

    # Read Config
    config = parse_config("config.ini")

    if args.interactive:
        logging.info("### Start Interactive Bot ###")
        get_messenger_interface("interactive", config, logging_level).run()
    elif args.signal:
        logging.info("### Start Signal Bot ###")
        get_messenger_interface("signal", config, logging_level).run()
    elif args.threema:
        logging.info("### Start Threema Bot ###")
        get_messenger_interface("threema", config, logging_level).run()
    elif args.telegram:
        logging.info("### Start Telegram Bot ###")
        get_messenger_interface("telegram", config, logging_level).run()
