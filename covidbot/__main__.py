import argparse
import asyncio
import configparser
import locale
import logging
import os
import sys
from typing import List

from mysql.connector import connect, MySQLConnection

from covidbot.bot import Bot
from covidbot.covid_data import CovidData, VaccinationGermanyUpdater, VaccinationGermanyImpfdashboardUpdater, \
    RValueGermanyUpdater, RKIUpdater
from covidbot.covid_data.visualization import Visualization
from covidbot.feedback_forwarder import FeedbackForwarder
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

    def __init__(self, name: str, config_dict, loglvl=logging.INFO, setup_logs=True):
        if setup_logs:
            # Setup Logging
            logging.basicConfig(format=logging_format, level=loglvl, filename=f"{name}-bot.log")

            # Log also to stdout
            stream_log_handler = logging.StreamHandler()
            stream_log_handler.setFormatter(logging.Formatter(logging_format))
            logging.getLogger().addHandler(stream_log_handler)

        if name != "signal" and name != "threema" and name != "telegram" and name != "interactive" and name != "feedback":
            raise ValueError(f"Invalid messenger interface was requested: {name}")

        self.name = name
        self.config = config_dict

    def __enter__(self) -> MessengerInterface:
        # Do not activate user on Threema automatically
        users_activated = True
        location_feature = True
        if self.name == "threema":
            location_feature = False
            # users_activated = False

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
        bot = Bot(data, user_manager, command_format=command_format, location_feature=location_feature)

        # Return specific interface
        if self.name == "threema":
            return ThreemaInterface(self.config['THREEMA'].get('ID'), self.config['THREEMA'].get('SECRET'),
                                    self.config['THREEMA'].get('PRIVATE_KEY'), bot,
                                    dev_chat=self.config['THREEMA'].get('DEV_CHAT'))

        if self.name == "signal":
            return SignalInterface(self.config['SIGNAL'].get('PHONE_NUMBER'),
                                   self.config['SIGNAL'].get('SIGNALD_SOCKET'), bot,
                                   dev_chat=self.config['SIGNAL'].get('DEV_CHAT'))

        if self.name == "telegram":
            return TelegramInterface(bot, api_key=self.config['TELEGRAM'].get('API_KEY'),
                                     dev_chat_id=self.config['TELEGRAM'].getint("DEV_CHAT"))
        if self.name == "feedback":
            return FeedbackForwarder(api_key=self.config['TELEGRAM'].get('API_KEY'),
                                     dev_chat_id=self.config['TELEGRAM'].getint("DEV_CHAT"), user_manager=user_manager)

        if self.name == "interactive":
            return InteractiveInterface(bot)

    def __exit__(self, exc_type, exc_val, exc_tb):
        for db_conn in self.connections:
            db_conn.close()


async def sendUpdates(messenger_iface: str):
    try:
        with MessengerBotSetup(messenger_iface, config, setup_logs=False) as iface:
            await iface.send_daily_reports()
            logging.info(f"Checked for daily reports on {messenger_iface}")
    except Exception as e:
        logging.error(f"Got exception while sending daily reports for {messenger_iface}: {e}", exc_info=e)


async def send_all(message: str, recipients: List[str], config_dict, messenger_interface=None):
    if not messenger_interface and recipients:
        print("You have to specify a messenger if you want to send a message to certain users!")
        return

    if messenger_interface and messenger_interface not in ["signal", "threema", "telegram"]:
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

    if messenger_interface:
        print(f"On {messenger_interface}")
    else:
        print(f"On all messengers")

    if input("PLEASE CONFIRM SENDING! (y/N)").lower() != "y":
        print("Aborting...")
        return

    if messenger_interface:
        with MessengerBotSetup(messenger_interface, config_dict, setup_logs=False) as iface:
            await iface.send_message(message, recipients, with_report)

    else:
        for messenger_interface in ["telegram", "threema", "signal"]:
            try:
                with MessengerBotSetup(messenger_interface, config_dict, setup_logs=False) as iface:
                    await iface.send_message(message, recipients, with_report)
            except Exception as e:
                logging.error(f"Got exception while sending message on {messenger_interface}: ", exc_info=e)


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
    parser.add_argument('--verbose', '-v', action='count', default=0)
    parser.add_argument('--config', '-c', action='store', default='config.ini', metavar='CONFIG_FILE')

    parser.add_argument('--platform', choices=['threema', 'telegram', 'signal', 'shell'], nargs=1,
                        help='Platform that should be used', type=str, action='store')
    parser.add_argument('--check-updates', help='Run platform independent jobs, such as checking for new data',
                        action='store_true')
    parser.add_argument('--daily-report', help='Send daily reports if available, requires --platform',
                        action='store_true')
    parser.add_argument('--message-user', help='Send a message to users', action='store_true')
    parser.add_argument('--file', help='Message, requires --message-user', metavar='MESSAGE_FILE', action='store')
    parser.add_argument('--all', help='Intended receivers, requires --platform', action='store_true')
    parser.add_argument('--specific', help='Intended receivers, requires --platform', metavar='USER',
                        action='store', nargs="+", type=str)

    # Just for testing
    parser.add_argument('--graphic-test', help='Generate graphic for testing', action='store_true')
    args = parser.parse_args()
    if args.platform:
        args.platform = args.platform[0]
    if not args.verbose:
        logging_level = logging.WARNING
    elif args.verbose > 1:
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO

    if not args.platform and not (args.check_updates or args.message_user or args.graphic_test):
        print("Exactly one platform has to be set, e.g. --platform telegram")
        sys.exit(1)

    if args.check_updates and (args.platform or args.message_user):
        print("--check-updates can't be combined with other flags")
        sys.exit(1)

    if args.message_user and not (args.specific or args.all):
        print("--message-user has to be combined with either --specific USER1 USER2 ... or --all")
        sys.exit(1)

    if args.all and args.specific:
        print("You can't send a message to --all and --specific")
        sys.exit(1)

    if args.specific and not args.platform:
        print("--Platform required for --specific USER1 USER2 ...")
        sys.exit(1)

    # Read Config
    config = parse_config(args.config)

    if args.check_updates:
        # Setup Logging
        logging.basicConfig(format=logging_format, level=logging_level, filename="updater.log")

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(logging_format))
        if not args.verbose:
            stream_handler.setLevel(logging.ERROR)
        logging.getLogger().addHandler(stream_handler)

        logging.info("### Start Data Update ###")
        with get_connection(config, autocommit=False) as conn:
            for updater in [VaccinationGermanyImpfdashboardUpdater(conn), RKIUpdater(conn),
                            VaccinationGermanyUpdater(conn)]:  # TODO: RValueGermanyUpdater(conn)]:
                try:
                    if updater.update():
                        logging.warning(f"Got new data from {updater.__class__.__name__}")
                        with MessengerBotSetup("telegram", config, setup_logs=False) as telegram:
                            asyncio.run(telegram.send_message(f"Got new data from {updater.__class__.__name__}",
                                                              [config["TELEGRAM"].get("DEV_CHAT")]))
                except ValueError as error:
                    # Data did not make it through plausibility check
                    print(f"Exception happened on Data Update with {updater.__class__.__name__}: {error}")
                    with MessengerBotSetup("telegram", config, setup_logs=False) as telegram:
                        asyncio.run(telegram.send_message(f"Exception happened on Data Update with "
                                                          f"{updater.__class__.__name__}: {error}",
                                                          [config["TELEGRAM"].get("DEV_CHAT")]))

        # Forward Feedback
        with MessengerBotSetup("feedback", config, setup_logs=False) as iface:
            asyncio.run(iface.send_daily_reports())

    elif args.daily_report:
        # Setup Logging
        logging.basicConfig(format=logging_format, level=logging_level, filename=f"reports-{args.platform}.log")

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(logging_format))
        if not args.verbose:
            stream_handler.setLevel(logging.ERROR)
        logging.getLogger().addHandler(stream_handler)

        asyncio.run(sendUpdates(args.platform))

    elif args.message_user:
        # Setup Logging
        logging.basicConfig(format=logging_format, level=logging_level, filename="message-users.log")

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(logging_format))
        logging.getLogger().addHandler(stream_handler)

        message_input = None
        if args.file:
            with open(args.file, "r") as f:
                message_input = f.read()

        recipients_input = []
        if args.specific:
            recipients_input = args.specific

        messenger = args.platform
        asyncio.run(send_all(message_input, recipients_input, config, messenger))
    elif args.platform == "shell":
        with MessengerBotSetup("interactive", config, logging_level) as interface:
            logging.info("### Start Interactive Bot ###")
            interface.run()
    elif args.platform == "signal":
        with MessengerBotSetup("signal", config, logging_level) as interface:
            logging.info("### Start Signal Bot ###")
            interface.run()
    elif args.platform == "threema":
        with MessengerBotSetup("threema", config, logging_level) as interface:
            logging.info("### Start Threema Bot ###")
            interface.run()
    elif args.platform == "telegram":
        with MessengerBotSetup("telegram", config, logging_level) as interface:
            logging.info("### Start Telegram Bot ###")
            interface.run()
    elif args.graphic_test:
        vis = Visualization(get_connection(config), os.path.abspath("tmp/"))
        vis.incidence_graph(0)
