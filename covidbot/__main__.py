import argparse
import asyncio
import configparser
import locale
import logging
import re
import sys
from typing import List, Optional

from mysql.connector import connect, MySQLConnection

from covidbot.bot import Bot
from covidbot.covid_data import CovidData
from covidbot.signal_interface import SignalInterface
from covidbot.telegram_interface import TelegramInterface
from covidbot.text_interface import SimpleTextInterface
from covidbot.threema_interface import ThreemaInterface
from covidbot.user_manager import UserManager


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


def strip_html(text: str) -> str:
    # Simple replace, as it is just used for interfaces that do not support scripting in any way
    return re.sub('<[^<]+?>', "", text)


def send_newsletter(telegram: TelegramInterface, message: str, specific_users: Optional[List[int]]):
    print(message)

    ident = "all"
    if specific_users:
        ident = "specific"

    if input(f"Do you want to send this message to {ident} users? (y/N)").upper() != "Y":
        exit(0)

    append_report = False
    if input("Do you want to append the current report? (y/N)").upper() == "Y":
        append_report = True

    if input("Please confirm sending the message (Y): ") == "Y":
        telegram.message_users(message, append_report, specific_users)


if __name__ == "__main__":
    logging_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(logging_format))
    logging_level = logging.INFO

    # Set locale
    try:
        locale.setlocale(locale.LC_ALL, 'de_DE.utf8')
    except Exception:
        logging.error("Can't set locale!")

    # Parse Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--message-file', help='Send the message from <FILE> to users',
                        metavar='FILE', action='store')
    parser.add_argument('--message', help='Send a message to users', action='store_true')
    parser.add_argument('--specific', help='Just send the message to specific user_ids',
                        metavar='USERS', action='store', nargs="+", type=int)
    parser.add_argument('--interactive', help='Chat with Textbot', action='store_true')
    parser.add_argument('--threema', help='Use Threema', action='store_true')
    parser.add_argument('--telegram', help='Use Telegram', action='store_true')
    parser.add_argument('--signal', help='Use Signal', action='store_true')
    parser.add_argument('--verbose', '-v', action='count', default=0)

    args = parser.parse_args()
    config = parse_config("config.ini")
    api_key = config['TELEGRAM'].get('API_KEY')

    if args.verbose and args.verbose > 0:
        logging_level = logging.DEBUG

    if args.signal and args.telegram and args.threema:
        sys.exit(1)

    if not args.signal and not args.telegram and not args.interactive and not args.threema:
        print("You have to specify the used messenger")
        sys.exit(1)

    if args.specific and not (args.message or args.message_file):
        print("You can use --specific only with --message or --message-file")
        sys.exit(1)

    if args.interactive:
        logging.basicConfig(format=logging_format, level=logging_level, filename="interactive-bot.log")
        # Also write to stderr
        logging.getLogger().addHandler(stream_handler)
        logging.info("### Start Interactive Bot ###")

        data = CovidData(get_connection(config))
        user_manager = UserManager("interactive", get_connection(config))

        bot = SimpleTextInterface(Bot(data, user_manager))
        user_input = input("Please enter input:\n> ")
        while user_input != "":
            print(f"{strip_html(bot.handle_input(user_input, '1').message)}")
            user_input = input("> ")
        sys.exit(0)
    elif args.signal:
        logging.basicConfig(format=logging_format, level=logging_level, filename="signal-bot.log")
        logging.getLogger().addHandler(stream_handler)

        logging.info("### Start Signal Bot ###")
        data = CovidData(get_connection(config))
        user_manager = UserManager("signal", get_connection(config))
        bot = Bot(data, user_manager)
        signal_interface = SignalInterface(config['SIGNAL'].get('PHONE_NUMBER'),
                                           config['SIGNAL'].get('SIGNALD_SOCKET'), bot)
        asyncio.run(signal_interface.run())
    elif args.threema:
        logging.basicConfig(format=logging_format, level=logging_level, filename="threema-bot.log")
        logging.getLogger().addHandler(logging.StreamHandler())
        logging.info("Start Threema Bot")
        data = CovidData(get_connection(config))
        user_manager = UserManager("threema", get_connection(config))
        bot = Bot(data, user_manager)
        threema_iface = ThreemaInterface(config['THREEMA'].get('ID'), config['THREEMA'].get('SECRET'),
                                         config['THREEMA'].get('PRIVATE_KEY'), bot)
        threema_iface.run()
    elif args.telegram:
        logging.basicConfig(format=logging_format, level=logging_level, filename="telegram-bot.log")
        logging.getLogger().addHandler(stream_handler)
        logging.info("### Start Telegram Bot ###")

        if args.message or args.message_file:
            data = CovidData(get_connection(config), disable_autoupdate=True)
        else:
            data = CovidData(get_connection(config))
        user_manager = UserManager("telegram", get_connection(config))
        bot = Bot(data, user_manager)

        telegram_bot = TelegramInterface(bot, api_key=api_key, dev_chat_id=config['TELEGRAM'].getint("DEV_CHAT"))

        if args and (args.message or args.message_file):
            if args.message_file:
                try:
                    with open(args.message_file, "r") as file:
                        message = file.read()
                except FileNotFoundError as e:
                    print("Can't read that file - sorry...")
                    sys.exit(1)
            else:
                lines = []
                line = input("Please write a message: ")
                while line != "":
                    lines.append(line)
                    line = input()

                message = "\n".join(lines)

            send_newsletter(telegram_bot, message, args.specific)
        else:
            telegram_bot.run()
