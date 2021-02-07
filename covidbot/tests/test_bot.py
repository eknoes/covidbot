from datetime import datetime, timedelta, date
from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.bot import Bot, UserDistrictActions
from covidbot.covid_data import CovidData, DistrictData, TrendValue, RKIUpdater, VaccinationGermanyUpdater, RValueGermanyUpdater
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
            cursor.execute("DROP TABLE covid_r_value;")
            cursor.execute("DROP TABLE IF EXISTS counties;")

        # Update Data
        RKIUpdater(cls.conn).update()
        VaccinationGermanyUpdater(cls.conn).update()
        RValueGermanyUpdater(cls.conn).update()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def setUp(self) -> None:
        with self.conn.cursor(dictionary=True) as cursor:
            cursor.execute("DROP TABLE IF EXISTS subscriptions;")
            cursor.execute("DROP TABLE IF EXISTS user_feedback;")
            cursor.execute("DROP TABLE IF EXISTS bot_user;")

        self.man = UserManager("unittest", self.conn, activated_default=True)
        self.bot = Bot(CovidData(self.conn),
                       self.man)

    def tearDown(self) -> None:
        del self.bot
        del self.man

    def test_update_with_subscribers(self):
        hessen_id = self.bot.find_district_id("Hessen")[1][0][0]
        bayern_id = self.bot.find_district_id("Bayern")[1][0][0]

        user1 = "uid1"
        user2 = "uid2"

        self.bot.subscribe(user1, hessen_id)
        self.bot.subscribe(user2, bayern_id)

        uid1 = self.man.get_user_id(user1)
        uid2 = self.man.get_user_id(user2)

        self.man.set_last_update(uid1, datetime.now() - timedelta(days=2))
        self.man.set_last_update(uid2, datetime.now() - timedelta(days=2))

        update = self.bot.get_unconfirmed_daily_reports()
        self.assertEqual(2, len(update), "New data should trigger 2 updates")
        for u in update:
            if u[0] == 1:
                self.assertRegex(u[1], "Hessen", "A subscribed district must be part of the daily report")
                self.assertEqual(self.bot.get_report(user1), u[1],
                                 "The daily report should be equal to the manual report")
            if u[0] == 2:
                self.assertRegex(u[1], "Bayern", "A subscribed district must be part of the daily report")
                self.assertEqual(self.bot.get_report(user2), u[1],
                                 "The daily report should be equal to the manual report")

        self.assertEqual(2, len(self.bot.get_unconfirmed_daily_reports()),
                         "Without setting last_updated, new reports should be generated")
        self.bot.confirm_daily_report_send(user1)
        self.assertEqual(1, len(self.bot.get_unconfirmed_daily_reports()),
                         "Without setting last_updated, new report should be generated")
        self.bot.confirm_daily_report_send(user2)
        self.assertEqual([], self.bot.get_unconfirmed_daily_reports(), "If both users already have current report, "
                                                                       "it should not be sent again")

    def test_update_no_subscribers(self):
        self.assertEqual([], self.bot.get_unconfirmed_daily_reports(), "Empty subscribers should generate empty "
                                                                       "update list")

    def test_no_update_new_subscriber(self):
        self.bot.subscribe("user1", 0)
        self.assertEqual([], self.bot.get_unconfirmed_daily_reports(), "New subscriber should get his first report on "
                                                                       "next day")

    def test_no_user(self):
        uid1 = "uid1"
        self.assertIsNotNone(self.bot.get_overview(uid1), "A not yet existing user should get an overview over their "
                                                          "subscriptions")
        self.assertIsNotNone(self.bot.get_district_report(1), "A not yet existing user should get a district report")
        self.assertIsNotNone(self.bot.find_district_id("Berlin"), "A not yet existing user should be able to query for "
                                                                  "a location")
        self.assertIsNotNone(self.bot.get_report(uid1), "A not yet existing user should be able to query for a report")
        self.assertIsNotNone(self.bot.get_possible_actions(uid1, 2),
                             "A not yet existing user should be able to query for "
                             "possible actions")

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

        self.assertCountEqual(actual[0], [districts[0], districts[1]], "District should be grouped in <= 35")
        self.assertCountEqual(actual[35], [districts[2]], "District should be grouped in 35 < district <= 50")
        self.assertCountEqual(actual[50], [districts[3]], "District should be grouped in 50 < district <= 100")
        self.assertCountEqual(actual[100], [districts[4]], "District with should be grouped in 100 < district <= 200")
        self.assertCountEqual(actual[200], [districts[5]], "District with should be grouped in 200 < district")
        self.assertIn(0, actual.keys(), "Group for > 0 should exist")
        self.assertIn(35, actual.keys(), "Group for > 35 should exist")
        self.assertIn(50, actual.keys(), "Group for > 50 should exist")
        self.assertIn(100, actual.keys(), "Group for > 100 should exist")
        self.assertIn(200, actual.keys(), "Group for > 200 should exist")

        # Bug
        districts = [
            DistrictData(name='Göttingen (Landkreis)', type='Landkreis', date=date(2021, 1, 21), incidence=81.5848),
            DistrictData(name='Lüneburg (Landkreis)', type='Landkreis', date=date(2021, 1, 21), incidence=30.9549)]
        actual = self.bot.group_districts(districts)

        self.assertCountEqual([districts[0]], actual[50])
        self.assertCountEqual([districts[1]], actual[0])

    def test_group_districts_empty(self):
        self.assertIsInstance(self.bot.group_districts([]), dict)

    def test_sort_districts(self):
        districts = [DistrictData(incidence=0, name="A"), DistrictData(incidence=0, name="C"),
                     DistrictData(incidence=0, name="B")]
        actual_names = list(map(lambda d: d.name, self.bot.sort_districts(districts)))

        self.assertEqual("A", actual_names[0], "Districts should be sorted alphabetically")
        self.assertEqual("B", actual_names[1], "Districts should be sorted alphabetically")
        self.assertEqual("C", actual_names[2], "Districts should be sorted alphabetically")

    def test_get_possible_actions(self):
        uid1 = "uid1"
        expected = [UserDistrictActions.SUBSCRIBE, UserDistrictActions.REPORT]
        actual = map(lambda x: x[1], self.bot.get_possible_actions(uid1, 1)[1])
        self.assertCountEqual(expected, actual, "A user without a subscription should get SUBSCRIBE and REPORT action")

        self.bot.subscribe(uid1, 1)
        expected = [UserDistrictActions.SUBSCRIBE, UserDistrictActions.REPORT]
        actual = map(lambda x: x[1], self.bot.get_possible_actions(uid1, 2)[1])
        self.assertCountEqual(expected, actual, "A user without subscription should get SUBSCRIBE and REPORT action")

        expected = [UserDistrictActions.UNSUBSCRIBE, UserDistrictActions.REPORT]
        actual = map(lambda x: x[1], self.bot.get_possible_actions(uid1, 1)[1])
        self.assertCountEqual(expected, actual, "A user with subscription should get UNSUBSCRIBE and REPORT action")
