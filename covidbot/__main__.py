import argparse
import asyncio
import configparser
import locale
import logging
import os
from os.path import abspath
from sys import exit
from typing import List

import prometheus_client
from mysql.connector import connect, MySQLConnection
from prometheus_client import Info

from covidbot.covid_data import CovidData, Visualization, RKIHistoryUpdater
from covidbot.interfaces.facebook_interface import FacebookInterface
from covidbot.interfaces.messenger_interface import MessengerInterface
from covidbot.metrics import USER_COUNT, AVERAGE_SUBSCRIPTION_COUNT
from covidbot.bot import Bot
from covidbot.user_manager import UserManager

LOGGING_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def parse_config(config_file: str):
    cfg = configparser.ConfigParser()
    cfg.read(config_file)
    return cfg


def get_connection(cfg, autocommit=False) -> MySQLConnection:
    connection = connect(database=cfg['DATABASE'].get('DATABASE'),
                         user=cfg['DATABASE'].get('USER'),
                         password=cfg['DATABASE'].get('PASSWORD'),
                         port=cfg['DATABASE'].get('PORT'),
                         host=cfg['DATABASE'].get('HOST', 'localhost'), autocommit=autocommit)
    return connection


class MessengerBotSetup:
    connections: List[MySQLConnection] = []
    name: str
    config: configparser.ConfigParser

    def __init__(self, name: str, config_dict, loglvl=logging.INFO, setup_logs=True, monitoring=True):
        if setup_logs:
            # Setup Logging
            logs_dir = config_dict["GENERAL"].get("LOGS_DIR", fallback="")

            logging.basicConfig(format=LOGGING_FORMAT, level=loglvl, filename=os.path.join(logs_dir, f"{name}-bot.log"))

            # Log also to stdout
            stream_log_handler = logging.StreamHandler()
            stream_log_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
            logging.getLogger().addHandler(stream_log_handler)

        if name not in ["signal", "threema", "telegram", "interactive", "twitter", "mastodon", "instagram",
                        "messenger", "facebook", "feedback"]:
            raise ValueError(f"Invalid messenger interface was requested: {name}")

        self.name = name
        self.config = config_dict

        monitor_port = self.config.getint(name.upper(), "PROMETHEUS_PORT", fallback=0)
        if monitoring and monitor_port > 0:
            try:
                prometheus_client.start_http_server(monitor_port, '0.0.0.0')
            except OSError as e:
                logging.error("Error while starting Prometheus Endpoint", exc_info=e)
            i = Info('platform', 'Bot Platform')
            i.info({'platform': self.name})

    def __enter__(self) -> MessengerInterface:
        # Do not activate user on Threema automatically
        users_activated = True
        location_feature = True
        if self.name == "threema" or self.name == "messenger":
            location_feature = False

        if self.name == "telegram":
            def telegram_format(command: str) -> str:
                if len(command.split()) == 1:
                    return f"/{command}"
                return f"<code>/{command}</code>"

            command_format = telegram_format
        else:
            command_format = lambda command: f'"{command}"'

        # Setup CovidData, Bot and UserManager
        data_conn = get_connection(self.config, autocommit=True)
        user_conn = get_connection(self.config, autocommit=True)
        user_monitor_conn = get_connection(self.config, autocommit=True)

        self.connections.append(data_conn)
        self.connections.append(user_conn)
        self.connections.append(user_monitor_conn)

        data = CovidData(data_conn)
        visualization = Visualization(data_conn, self.config['GENERAL'].get('CACHE_DIR', 'graphics'))
        user_manager = UserManager(self.name, user_conn, activated_default=users_activated)
        bot = Bot(user_manager, data, visualization, command_formatter=command_format,
                  has_location_feature=location_feature)

        # Setup database monitoring
        user_monitor = UserManager("monitor", user_monitor_conn)
        USER_COUNT.labels(platform="threema").set_function(lambda: user_monitor.get_user_number("threema"))
        USER_COUNT.labels(platform="telegram").set_function(lambda: user_monitor.get_user_number("telegram"))
        USER_COUNT.labels(platform="signal").set_function(lambda: user_monitor.get_user_number("signal"))
        USER_COUNT.labels(platform="messenger").set_function(lambda: user_monitor.get_user_number("messenger"))
        USER_COUNT.labels(platform="facebook").set_function(
            lambda: user_monitor.get_social_network_user_number("facebook"))
        USER_COUNT.labels(platform="instagram").set_function(
            lambda: user_monitor.get_social_network_user_number("instagram"))
        USER_COUNT.labels(platform="twitter").set_function(
            lambda: user_monitor.get_social_network_user_number("twitter"))
        USER_COUNT.labels(platform="mastodon").set_function(
            lambda: user_monitor.get_social_network_user_number("mastodon"))

        AVERAGE_SUBSCRIPTION_COUNT.set_function(lambda: user_monitor.get_mean_subscriptions())

        # Return specific interface
        if self.name == "threema":
            if not self.config.has_section("THREEMA"):
                raise ValueError("THREEMA is not configured")
            from covidbot.interfaces.threema_interface import ThreemaInterface
            return ThreemaInterface(self.config['THREEMA'].get('ID'), self.config['THREEMA'].get('SECRET'),
                                    self.config['THREEMA'].get('PRIVATE_KEY'),
                                    self.config['THREEMA'].get('CALLBACK_PATH'),
                                    bot, dev_chat=self.config['THREEMA'].get('DEV_CHAT'))

        if self.name == "messenger":
            if not self.config.has_section("MESSENGER"):
                raise ValueError("MESSENGER is not configured")
            from covidbot.interfaces.fbmessenger_interface import FBMessengerInterface
            return FBMessengerInterface(bot, self.config['MESSENGER'].get('PAGE_ACCESS_TOKEN'),
                                        self.config['MESSENGER'].get('VERIFY'),
                                        self.config['MESSENGER'].getint('PORT', fallback=8080),
                                        self.config['INSTAGRAM'].get('WEB_DIR'),
                                        self.config['INSTAGRAM'].get('PUBLIC_URL'))

        if self.name == "signal":
            if not self.config.has_section("SIGNAL"):
                raise ValueError("SIGNAL is not configured")
            from covidbot.interfaces.signal_interface import SignalInterface
            return SignalInterface(bot, self.config['SIGNAL'].get('PHONE_NUMBER'),
                                   self.config['SIGNAL'].get('SIGNALD_SOCKET'),
                                   dev_chat=self.config['SIGNAL'].get('DEV_CHAT'))

        if self.name == "telegram":
            if not self.config.has_section("TELEGRAM"):
                raise ValueError("TELEGRAM is not configured")
            from covidbot.interfaces.telegram_interface import TelegramInterface
            return TelegramInterface(bot, api_key=self.config['TELEGRAM'].get('API_KEY'),
                                     dev_chat_id=self.config['TELEGRAM'].getint("DEV_CHAT"))

        if self.name == "interactive":
            from covidbot.bot import InteractiveInterface
            return InteractiveInterface(bot)

        if self.name == "feedback":
            from covidbot.feedback_notifier import FeedbackNotifier
            return FeedbackNotifier(api_key=self.config['TELEGRAM'].get('API_KEY'),
                                    dev_chat_id=self.config['TELEGRAM'].getint("DEV_CHAT"),
                                    user_manager=user_manager)

        if self.name == "twitter":
            if not self.config.has_section("TWITTER"):
                raise ValueError("TWITTER is not configured")
            from covidbot.interfaces.twitter_interface import TwitterInterface
            return TwitterInterface(self.config['TWITTER'].get('API_KEY'), self.config['TWITTER'].get('API_SECRET'),
                                    self.config['TWITTER'].get('ACCESS_TOKEN'),
                                    self.config['TWITTER'].get('ACCESS_SECRET'),
                                    user_manager, data, visualization,
                                    no_write=self.config['TWITTER'].getboolean('DEBUG',
                                                                               fallback=False))

        if self.name == "mastodon":
            if not self.config.has_section("MASTODON"):
                raise ValueError("MASTODON is not configured")
            from covidbot.interfaces.mastodon_interface import MastodonInterface
            return MastodonInterface(self.config['MASTODON'].get('ACCESS_TOKEN'),
                                     self.config['MASTODON'].get('INSTANCE_URL'),
                                     user_manager, data, visualization,
                                     no_write=self.config['MASTODON'].getboolean('DEBUG',
                                                                                 fallback=False))

        if self.name == "instagram":
            if not self.config.has_section("INSTAGRAM"):
                raise ValueError("INSTAGRAM is not configured")
            from covidbot.interfaces.instagram_interface import InstagramInterface
            return InstagramInterface(self.config['INSTAGRAM'].get('ACCOUNT_ID'),
                                      self.config['INSTAGRAM'].get('ACCESS_TOKEN'),
                                      self.config['INSTAGRAM'].get('WEB_DIR'),
                                      self.config['INSTAGRAM'].get('PUBLIC_URL'),
                                      user_manager, data, visualization,
                                      no_write=self.config['INSTAGRAM'].getboolean('DEBUG',
                                                                                   fallback=False))

        if self.name == "facebook":
            if not self.config.has_section("FACEBOOK"):
                raise ValueError("FACEBOOK is not configured")
            from covidbot.interfaces.instagram_interface import InstagramInterface
            return FacebookInterface(self.config['FACEBOOK'].get('PAGE_ID'),
                                     self.config['FACEBOOK'].get('PAGE_ACCESS_TOKEN'),
                                     self.config['FACEBOOK'].get('WEB_DIR'),
                                     self.config['FACEBOOK'].get('PUBLIC_URL'),
                                     user_manager, data, visualization,
                                     no_write=self.config['FACEBOOK'].getboolean('DEBUG',
                                                                                 fallback=False))

    def __exit__(self, exc_type, exc_val, exc_tb):
        for db_conn in self.connections:
            db_conn.close()


async def sendUpdates(messenger_iface: str, config: configparser):
    try:
        with MessengerBotSetup(messenger_iface, config, setup_logs=False, monitoring=False) as iface:
            await iface.send_unconfirmed_reports()
            logging.info(f"Checked for daily reports on {messenger_iface}")
    except Exception as e:
        logging.error(f"Got exception while sending daily reports for {messenger_iface}:\n{e}", exc_info=e)
        with MessengerBotSetup("telegram", config, setup_logs=False, monitoring=False) as telegram:
            asyncio.run(telegram.send_message_to_users(f"Exception happened while sending reports via {messenger_iface}:"
                                                       f"{e}", [config["TELEGRAM"].get("DEV_CHAT")]))


async def send_all(message: str, recipients: List[int], config_dict):
    if not message:
        message = ""
        line = input("Please type a message:\n> ")
        while line != "":
            message += f"{line}\n"
            line = input("> ")

    print("\n\n++ Please confirm ++")
    print(f"Message:\n{message}")
    if recipients:
        print(f"To: {recipients}")
    else:
        print("To all users")

    if input("PLEASE CONFIRM SENDING! (y/N)").lower() != "y":
        print("Aborting...")
        return

    user_manager = UserManager("message-sender", get_connection(config_dict))
    if not recipients:
        recipients = map(lambda x: x.id, filter(lambda x: x.activated == 1 , user_manager.get_all_user(all_platforms=True)))

    for r in recipients:
        user_manager.add_user_message(r, message)


def main():
    # Set locale
    try:
        locale.setlocale(locale.LC_ALL, 'de_DE.utf8')
    except Exception:
        logging.error("Can't set locale!")

    # Parse Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action='count', default=0)
    parser.add_argument('--config', '-c', action='store', default='config.ini', metavar='CONFIG_FILE')

    parser.add_argument('--platform', choices=['threema', 'telegram', 'signal', 'interactive', 'twitter', 'mastodon',
                                               'messenger'],
                        nargs=1,
                        help='Platform that should be used', type=str, action='store')
    parser.add_argument('--check-updates', help='Run platform independent jobs, such as checking for new data',
                        action='store_true')
    parser.add_argument('--daily-report', help='Send daily reports if available, requires --platform',
                        action='store_true')
    parser.add_argument('--message-user', help='Send a message to users', action='store_true')
    parser.add_argument('--file', help='Message, requires --message-user', metavar='MESSAGE_FILE', action='store')
    parser.add_argument('--all', help='Send to all users, mutually exclusive with --specific', action='store_true')
    parser.add_argument('--specific', help='Send to a list of users, mutually exclusive with --all', metavar='USER',
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
        exit(1)

    if args.check_updates and (args.platform or args.message_user):
        print("--check-updates can't be combined with other flags")
        exit(1)

    if args.message_user and not (args.specific or args.all):
        print("--message-user has to be combined with either --specific USER1 USER2 ... or --all")
        exit(1)

    if args.all and args.specific:
        print("You can't send a message to --all and --specific")
        exit(1)

    # Read Config
    config = parse_config(args.config)

    logs_dir = config["GENERAL"].get("LOGS_DIR", fallback="")

    if args.check_updates:
        # Setup Logging
        logging.basicConfig(format=LOGGING_FORMAT, level=logging_level, filename=os.path.join(logs_dir, "updater.log"))

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
        if not args.verbose:
            stream_handler.setLevel(logging.ERROR)
        logging.getLogger().addHandler(stream_handler)

        logging.info("### Start Data Update ###")
        with get_connection(config, autocommit=False) as conn:
            from covidbot.covid_data import CovidData, VaccinationGermanyImpfdashboardUpdater, RValueGermanyUpdater, \
                RKIUpdater, ICUGermanyUpdater, \
                RulesGermanyUpdater, ICUGermanyHistoryUpdater, VaccinationGermanyStatesImpfdashboardUpdater, HospitalisationRKIUpdater
            for updater in [VaccinationGermanyStatesImpfdashboardUpdater(conn), RKIUpdater(conn), ICUGermanyHistoryUpdater(conn),
                            VaccinationGermanyImpfdashboardUpdater(conn), RulesGermanyUpdater(conn),
                            RValueGermanyUpdater(conn), ICUGermanyUpdater(conn), HospitalisationRKIUpdater(conn)]:
                try:
                    if updater.update():
                        logging.warning(f"Got new data from {updater.__class__.__name__}")
                        with MessengerBotSetup("telegram", config, setup_logs=False, monitoring=False) as telegram:
                            asyncio.run(
                                telegram.send_message_to_users(f"Got new data from {updater.__class__.__name__}",
                                                               [config["TELEGRAM"].get("DEV_CHAT")]))
                except Exception as error:
                    # Data did not make it through plausibility check
                    logging.exception(f"Exception happened on Data Update with {updater.__class__.__name__}: {error}",
                                      exc_info=error)
                    with MessengerBotSetup("telegram", config, setup_logs=False, monitoring=False) as telegram:
                        asyncio.run(telegram.send_message_to_users(f"Exception happened on Data Update with "
                                                                   f"{updater.__class__.__name__}: {error}",
                                                                   [config["TELEGRAM"].get("DEV_CHAT")]))

        # Check Tweets & Co
        platforms = ["feedback"]
        if config.has_section("TWITTER"):
            platforms.append("twitter")
        if config.has_section("MASTODON"):
            platforms.append("mastodon")
        if config.has_section("INSTAGRAM"):
            platforms.append("instagram")
        if config.has_section("FACEBOOK"):
            platforms.append("facebook")

        for platform in platforms:
            with MessengerBotSetup(platform, config, setup_logs=False, monitoring=False) as iface:
                asyncio.run(iface.send_unconfirmed_reports())

    elif args.daily_report:
        # Setup Logging
        logging.basicConfig(format=LOGGING_FORMAT, level=logging_level,
                            filename=os.path.join(logs_dir, f"reports-{args.platform}.log"))

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
        if not args.verbose:
            stream_handler.setLevel(logging.ERROR)
        logging.getLogger().addHandler(stream_handler)

        asyncio.run(sendUpdates(args.platform, config))

    elif args.message_user:
        # Setup Logging
        logging.basicConfig(format=LOGGING_FORMAT, level=logging_level,
                            filename=os.path.join(logs_dir, "message-users.log"))

        # Log also to stdout
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
        logging.getLogger().addHandler(stream_handler)

        message_input = None
        if args.file:
            with open(args.file, "r") as f:
                message_input = f.read()

        recipients_input = []
        if args.specific:
            recipients_input = args.specific

        asyncio.run(send_all(message_input, recipients_input, config))
    elif args.platform:
        with MessengerBotSetup(args.platform, config, logging_level) as interface:
            logging.info(f"### Start {args.platform} Bot ###")
            try:
                interface.run()
            except Exception as e:
                logging.exception(f"Exception while running {args.platform} client", exc_info=e)
                with MessengerBotSetup("telegram", config, setup_logs=False, monitoring=False) as telegram:
                    asyncio.run(telegram.send_message_to_users(f"Exception happened while running {args.platform} bot:"
                                                               f"{e}", [config["TELEGRAM"].get("DEV_CHAT")]))
                raise e
    elif args.graphic_test:
        vis = Visualization(get_connection(config), abspath("graphics/"), disable_cache=True)
        vis.hospitalization_incidence_graph(0)


if __name__ == "__main__":
    main()
