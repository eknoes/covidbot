from datetime import datetime, timedelta, date
from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.bot import Bot, UserDistrictActions, UserHintService
from covidbot.covid_data import CovidData, DistrictData, RKIUpdater, VaccinationGermanyUpdater, RValueGermanyUpdater, \
    Visualization
from covidbot.text_interface import SimpleTextInterface
from covidbot.user_manager import UserManager


class TestBot(TestCase):
    conn: MySQLConnection

    @classmethod
    def setUpClass(cls) -> None:
        cfg = parse_config("resources/config.unittest.ini")
        cls.conn = get_connection(cfg)

        with cls.conn.cursor(dictionary=True) as cursor:
            cursor.execute("DROP TABLE IF EXISTS covid_data;")
            cursor.execute("DROP TABLE IF EXISTS covid_vaccinations;")
            cursor.execute("DROP TABLE IF EXISTS covid_r_value;")
            cursor.execute("DROP TABLE IF EXISTS icu_beds;")
            cursor.execute("DROP TABLE IF EXISTS district_rules;")
            cursor.execute("DROP TABLE IF EXISTS counties;")

        # Update Data
        RKIUpdater(cls.conn).update()
        VaccinationGermanyUpdater(cls.conn).update()
        RValueGermanyUpdater(cls.conn).update()

        bot = Bot(CovidData(connection=cls.conn), UserManager("unittest", cls.conn),
                  Visualization(cls.conn, ".", disable_cache=True))
        cls.interface = SimpleTextInterface(bot)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def sample_session(self):
        # Sample Session, should be improved a lot
        uid = "1"
        self.assertIsNotNone(self.interface.handle_input("Start", uid))
        self.assertIsNotNone(self.interface.handle_input("Darmstadt", uid))
        self.assertIsNotNone(self.interface.handle_input("Stadt Darmstadt", uid))
        self.assertIsNotNone(self.interface.handle_input("Abo", uid))
        self.assertIsNotNone(self.interface.handle_input("Impfungen", uid))
        self.assertIsNotNone(self.interface.handle_input("Abo Dresden", uid))
        self.assertIsNotNone(self.interface.handle_input("Bericht", uid))
        self.assertIsNotNone(self.interface.handle_input("Statistik", uid))
        self.assertIsNotNone(self.interface.handle_input("Regeln Berlin", uid))
        self.assertIsNotNone(self.interface.handle_input("Loeschmich", uid))
