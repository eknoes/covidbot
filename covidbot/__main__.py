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
from covidbot.covid_data import CovidData, RKIUpdater
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


def get_messenger_interface(name: str, config, loglvl=logging.INFO, setup_logs=True) -> Optional[MessengerInterface]:
    if setup_logs:
        # Setup Logging
        logging.basicConfig(format=logging_format, level=loglvl, filename="signal-bot.log")

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(logging_format))
        logging.getLogger().addHandler(stream_handler)

    if name != "signal" and name != "threema" and name != "telegram" and name != "interactive":
        raise ValueError(f"Invalid messenger interface was requested: {name}")

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
    parser.add_argument('--update', help='Check for data updates and new daily reports', action='store_true')
    parser.add_argument('--interactive', help='Chat with Textbot', action='store_true')
    parser.add_argument('--threema', help='Use Threema', action='store_true')
    parser.add_argument('--telegram', help='Use Telegram', action='store_true')
    parser.add_argument('--signal', help='Use Signal', action='store_true')
    parser.add_argument('--verbose', '-v', action='count', default=0)

    args = parser.parse_args()

    if args.verbose and args.verbose > 0:
        logging_level = logging.DEBUG

    if reduce(lambda x, y: int(x) + int(y), [args.signal, args.telegram, args.interactive, args.threema]) != 1 \
            and not args.update:
        print("Exactly one interface-flag has to be set, e.g. --telegram")
        sys.exit(1)

    # Read Config
    config = parse_config("config.ini")

    if args.update:
        if not args.verbose:
            logging_level = logging.WARNING

        # Setup Logging
        logging.basicConfig(format=logging_format, level=logging_level, filename="updater.log")

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(logging_format))
        logging.getLogger().addHandler(stream_handler)

        logging.info("### Start Data Update ###")

        updater = RKIUpdater(get_connection(config, autocommit=False))
        updater.fetch_current_data()
        del updater

        for messenger in ["threema", "signal", "telegram"]:
            try:
                interface = get_messenger_interface(messenger, config, setup_logs=False)
                interface.sendDailyReports()
                logging.info(f"Sent daily reports for {messenger}")
            except Exception as e:
                logging.error(f"Got exception while sending daily reports for {messenger}: {e}", exc_info=e)
    elif args.interactive:
        interface = get_messenger_interface("interactive", config, logging_level)
        logging.info("### Start Interactive Bot ###")
        interface.run()
    elif args.signal:
        interface = get_messenger_interface("signal", config, logging_level)
        logging.info("### Start Signal Bot ###")
    elif args.threema:
        interface = get_messenger_interface("threema", config, logging_level)
        logging.info("### Start Threema Bot ###")
        interface.run()
    elif args.telegram:
        interface = get_messenger_interface("telegram", config, logging_level)
        logging.info("### Start Telegram Bot ###")
        interface.run()
