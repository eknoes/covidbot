from unittest import TestCase

import psycopg2
from psycopg2.extras import DictCursor

from covidbot.bot import Bot
from covidbot.covid_data import CovidData, DistrictData
from covidbot.file_based_subscription_manager import FileBasedSubscriptionManager
from covidbot.subscription_manager import SubscriptionManager


class SubscriptionManagerNoFile(FileBasedSubscriptionManager):
    """
    Mock class of a memory-based subscription manager
    """

    # noinspection PyMissingConstructor
    def __init__(self):
        pass

    def _save(self):
        pass


class TestBot(TestCase):

    def setUp(self) -> None:
        self.conn = psycopg2.connect(dbname="covid_test_db", user="covid_bot", password="covid_bot", port=5432,
                                     host='localhost', cursor_factory=DictCursor)
        self.man = SubscriptionManager(self.conn)
        self.bot = Bot(CovidData(db_user="covid_bot", db_password="covid_bot", db_name="covid_test_db"),
                       self.man)
        with self.conn as conn:
            with conn.cursor() as cursor:
                cursor.execute("TRUNCATE bot_user CASCADE")

    def tearDown(self) -> None:
        del self.bot
        del self.man
        self.conn.close()

    def test_update_with_subscribers(self):
        self.bot.subscribe(1, "Berlin")
        self.bot.subscribe(2, "Hessen")
        self.assertEqual(2, len(self.bot.update()), "New data should trigger 2 updates")
        self.assertEqual([], self.bot.update(), "Without new data no reports should be generated")

    def test_update_no_subscribers(self):
        self.assertEqual([], self.bot.update(), "Empty subscribers should generate empty update list")

    def test_format_int(self):
        expected = "1.121"
        actual = self.bot.format_int(1121)
        self.assertEqual(expected, actual, "Ints should be formatted for German localization")

    def test_format_incidence(self):
        expected = "1,21"
        actual = self.bot.format_incidence(1.21)
        self.assertEqual(expected, actual, "Incidence should be formatted for German localization")

    def test_group_districts(self):
        districts = [DistrictData(incidence=0, name="0Incidence"), DistrictData(incidence=35, name="35Incidence"),
                     DistrictData(incidence=36, name="36Incidence"), DistrictData(incidence=51, name="51Incidence"),
                     DistrictData(incidence=101, name="101Incidence"), DistrictData(incidence=201, name="201Incidence")]
        actual = self.bot.group_districts(districts)

        in_group_0 = list(map(lambda x: x.name, actual[0]))
        self.assertIn("0Incidence", in_group_0, "District should be grouped in district <= 35")
        self.assertIn("35Incidence", in_group_0, "District should be grouped in district <= 35")
        self.assertEqual(actual[35][0].name, "36Incidence", "District should be grouped in 35 < district <= 50")
        self.assertEqual(actual[50][0].name, "51Incidence", "District should be grouped in 50 < district <= 100")
        self.assertEqual(actual[100][0].name, "101Incidence",
                         "District with should be grouped in 100 < district <= 200")
        self.assertEqual(actual[200][0].name, "201Incidence", "District with should be grouped in 200 < district")
        self.assertIn(0, actual.keys(), "Group for > 0 should exist")
        self.assertIn(35, actual.keys(), "Group for > 35 should exist")
        self.assertIn(50, actual.keys(), "Group for > 50 should exist")
        self.assertIn(100, actual.keys(), "Group for > 100 should exist")
        self.assertIn(200, actual.keys(), "Group for > 200 should exist")

    def test_group_districts_empty(self):
        self.assertIsInstance(self.bot.group_districts([]), dict)

    def test_sort_districts(self):
        districts = [DistrictData(incidence=0, name="A"), DistrictData(incidence=0, name="C"),
                     DistrictData(incidence=0, name="B")]
        actual_names = list(map(lambda d: d.name, self.bot.sort_districts(districts)))

        self.assertEqual("A", actual_names[0], "Districts should be sorted alphabetically")
        self.assertEqual("B", actual_names[1], "Districts should be sorted alphabetically")
        self.assertEqual("C", actual_names[2], "Districts should be sorted alphabetically")
