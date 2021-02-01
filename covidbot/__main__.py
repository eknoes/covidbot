import argparse
import asyncio
import configparser
import locale
import logging
import sys
from functools import reduce
from typing import List

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


class MessengerBotSetup:
    connections: List[MySQLConnection] = []
    name: str
    config: configparser.ConfigParser

    def __init__(self, name: str, config, loglvl=logging.INFO, setup_logs=True):
        if setup_logs:
            # Setup Logging
            logging.basicConfig(format=logging_format, level=loglvl, filename=f"{name}-bot.log")

            # Log also to stdout
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(logging.Formatter(logging_format))
            logging.getLogger().addHandler(stream_handler)

        if name != "signal" and name != "threema" and name != "telegram" and name != "interactive":
            raise ValueError(f"Invalid messenger interface was requested: {name}")

        self.name = name
        self.config = config

    def __enter__(self) -> MessengerInterface:
        # Do not activate user on Threema automatically
        users_activated = True
        if self.name == "threema":
            pass
            #users_activated = False

        if self.name == "telegram":
            command_format = "/{command}"
        else:
            command_format = '"{command}"'

        # Setup CovidData, Bot and UserManager
        data_conn = get_connection(config, autocommit=True)
        user_conn = get_connection(config, autocommit=True)

        self.connections.append(data_conn)
        self.connections.append(user_conn)

        data = CovidData(data_conn)
        user_manager = UserManager(self.name, user_conn, activated_default=users_activated)
        bot = Bot(data, user_manager, command_format=command_format)

        # Return specific interface
        if self.name == "threema":
            return ThreemaInterface(self.config['THREEMA'].get('ID'), self.config['THREEMA'].get('SECRET'),
                                    self.config['THREEMA'].get('PRIVATE_KEY'), bot)

        if self.name == "signal":
            return SignalInterface(self.config['SIGNAL'].get('PHONE_NUMBER'),
                                   self.config['SIGNAL'].get('SIGNALD_SOCKET'), bot)

        if self.name == "telegram":
            return TelegramInterface(bot, api_key=self.config['TELEGRAM'].get('API_KEY'),
                                     dev_chat_id=self.config['TELEGRAM'].getint("DEV_CHAT"))

        if self.name == "interactive":
            return InteractiveInterface(bot)

    def __exit__(self, exc_type, exc_val, exc_tb):
        for conn in self.connections:
            conn.close()


async def sendUpdates():
    for messenger in ["threema", "signal", "telegram"]:
        try:
            with MessengerBotSetup(messenger, config, setup_logs=False) as interface:
                await interface.sendDailyReports()
                logging.info(f"Checked for daily reports on {messenger}")
        except Exception as e:
            logging.error(f"Got exception while sending daily reports for {messenger}: {e}", exc_info=e)


async def send_all(message: str, recipients: List[str], config, messenger=None):
    if not messenger and recipients:
        print("You have to specify a messenger if you want to send a message to certain users!")
        return

    if messenger and messenger not in ["signal", "threema", "telegram"]:
        print("Your messenger name is invalid.")
        return

    if not message:
        message = ""
        line = input("Please type a message:\n> ")
        while line != "":
            message += f"{line}\n"
            line = input("> ")

    with_report = False
    if input("Do you want to append the current report? (y/N): ").lower() == "y":
        with_report = True

    print("\n\n++ Please confirm ++")
    print(f"Append Report? {with_report}")
    print(f"Message:\n{message}")
    if recipients:
        print(f"To: {recipients}")
    else:
        print("To all users")

    if messenger:
        print(f"On {messenger}")
    else:
        print(f"On all messengers")

    if input("PLEASE CONFIRM SENDING! (y/N)").lower() != "y":
        print("Aborting...")
        return

    if messenger:
        with MessengerBotSetup(messenger, config, setup_logs=False) as interface:
            await interface.sendMessageTo(message, recipients, with_report)

    else:
        for messenger in ["telegram", "signal", "threema"]:
            try:
                with MessengerBotSetup(messenger, config, setup_logs=False) as interface:
                    await interface.sendMessageTo(message, recipients, with_report)
                    logging.info(f"Sent message on {messenger}")
            except Exception as e:
                logging.error(f"Got exception while sending message on {messenger}: ", exc_info=e)


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

    parser.add_argument('--message-file', help='Send the message from <FILE> to users',
                        metavar='FILE', action='store')
    parser.add_argument('--message', help='Send a message to users', action='store_true')
    parser.add_argument('--specific', help='Just send the message to specific user_ids',
                        metavar='USERS', action='store', nargs="+", type=str)
    args = parser.parse_args()

    if args.verbose and args.verbose > 0:
        logging_level = logging.DEBUG

    if reduce(lambda x, y: int(x) + int(y), [args.signal, args.telegram, args.interactive, args.threema]) != 1 \
            and not (args.update or args.message or args.message_file):
        print("Exactly one interface-flag has to be set, e.g. --telegram")
        sys.exit(1)

    # Read Config
    config = parse_config("config.ini")

    if args.update:
        if not args.verbose:
            logging_level = logging.WARNING
        elif args.verbose > 1:
            logging_level = logging.DEBUG
        else:
            logging_level = logging.INFO

        # Setup Logging
        logging.basicConfig(format=logging_format, level=logging_level, filename="updater.log")

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(logging_format))
        logging.getLogger().addHandler(stream_handler)

        logging.info("### Start Data Update ###")
        with get_connection(config, autocommit=False) as conn:
            updater = RKIUpdater(conn)
            try:
                updater.fetch_current_data()
            except ValueError as error:
                # Data did not make it through plausibility check
                print(f"Data looks weird, not updating: {error}")
                with MessengerBotSetup("telegram", config, setup_logs=False) as telegram:
                    asyncio.run(telegram.sendMessageTo(f"I did not update the RKI data as it is looking strange: {error}",
                                           [config["TELEGRAM"].get("DEV_CHAT")]))
            else:
                asyncio.run(sendUpdates())
    elif args.message or args.message_file:
        # Setup Logging
        logging.basicConfig(format=logging_format, level=logging_level, filename="message-users.log")

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(logging_format))
        logging.getLogger().addHandler(stream_handler)

        message = None
        if args.message_file:
            with open(args.message_file, "r") as f:
                message = f.read()

        recipients = []
        if args.specific:
            recipients = args.specific

        messenger = None
        if args.telegram:
            messenger = "telegram"
        elif args.threema:
            messenger = "threema"
        elif args.signal:
            messenger = "signal"
        asyncio.run(send_all(message, recipients, config, messenger))
    elif args.interactive:
        with MessengerBotSetup("interactive", config, logging_level) as interface:
            logging.info("### Start Interactive Bot ###")
            interface.run()
    elif args.signal:
        with MessengerBotSetup("signal", config, logging_level) as interface:
            logging.info("### Start Signal Bot ###")
            interface.run()
    elif args.threema:
        with MessengerBotSetup("threema", config, logging_level) as interface:
            logging.info("### Start Threema Bot ###")
            interface.run()
    elif args.telegram:
        with MessengerBotSetup("telegram", config, logging_level) as interface:
            logging.info("### Start Telegram Bot ###")
            interface.run()
