from datetime import datetime, timedelta
from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import CovidData, RKIUpdater, VaccinationGermanyStatesImpfdashboardUpdater, RValueGermanyUpdater, \
    Visualization, DistrictData
from covidbot.bot import Bot
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
            cursor.execute("DROP TABLE IF EXISTS county_alt_names;")
            cursor.execute("DROP TABLE IF EXISTS counties;")

        # Update Data
        RKIUpdater(cls.conn).update()
        VaccinationGermanyStatesImpfdashboardUpdater(cls.conn).update()
        RValueGermanyUpdater(cls.conn).update()

        cls.user_manager = UserManager("unittest", cls.conn, activated_default=True)
        cls.data = CovidData(connection=cls.conn)
        cls.interface = Bot(cls.user_manager, cls.data,
                            Visualization(cls.conn, ".", disable_cache=True), lambda x: x)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    # noinspection SqlWithoutWhere
    def setUp(self) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute('TRUNCATE subscriptions')
            cursor.execute('TRUNCATE report_subscriptions')
            cursor.execute('TRUNCATE bot_user_settings')
            cursor.execute('TRUNCATE bot_user_sent_reports')
            cursor.execute('TRUNCATE user_feedback')
            cursor.execute('DELETE FROM bot_user')

    def test_update_with_subscribers(self):
        hessen_id = self.interface.find_district_id("Hessen")[1][0].id
        bayern_id = self.interface.find_district_id("Bayern")[1][0].id

        platform_id1 = "uid1"
        platform_id2 = "uid2"

        uid1 = self.user_manager.get_user_id(platform_id1)
        uid2 = self.user_manager.get_user_id(platform_id2)

        self.user_manager.add_subscription(uid1, hessen_id)
        self.user_manager.add_subscription(uid2, bayern_id)

        with self.conn.cursor() as cursor:
            for uid in [uid1, uid2]:
                cursor.execute('UPDATE bot_user SET created=%s WHERE user_id=%s',
                               [datetime.now() - timedelta(days=2), uid])

        update = self.interface.get_available_user_messages()
        i = 0
        for report, uid, reports in update:
            if uid == platform_id1:
                self.assertRegex(reports[0].message, "Hessen", "A subscribed district must be part of the daily report")
                self.assertEqual(self.interface.reportHandler("", uid1), reports,
                                 "The daily report should be equal to the manual report")
            if uid == platform_id2:
                self.assertRegex(reports[0].message, "Bayern", "A subscribed district must be part of the daily report")
                self.assertEqual(self.interface.reportHandler("", uid2), reports,
                                 "The daily report should be equal to the manual report")
            self.interface.confirm_message_send(report, uid)

            i += 1

        self.assertEqual(2, i, "New data should trigger 2 updates")
        self.assertEqual([], [1 for _ in self.interface.get_available_user_messages()],
                         "If both users already have current report, "
                         "it should not be sent again")

    def test_update_no_subscribers(self):
        self.assertEqual([], [1 for _ in self.interface.get_available_user_messages()],
                         "Empty subscribers should generate empty "
                         "update list")

    def test_no_update_new_subscriber(self):
        user1 = self.user_manager.get_user_id("uid1")
        self.user_manager.add_subscription(user1, 0)
        self.assertEqual([], [1 for _ in self.interface.get_available_user_messages()],
                         "New subscriber should get his first report on next day")

    def test_sort_districts(self):
        districts = [DistrictData(incidence=0, name="A", id=1), DistrictData(incidence=0, name="C", id=3),
                     DistrictData(incidence=0, name="B", id=2)]
        actual_names = list(map(lambda d: d.name, self.interface.sort_districts(districts)))

        self.assertEqual("A", actual_names[0], "Districts should be sorted alphabetically")
        self.assertEqual("B", actual_names[1], "Districts should be sorted alphabetically")
        self.assertEqual("C", actual_names[2], "Districts should be sorted alphabetically")

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
        self.assertIsNotNone(self.interface.handle_input("Ja", uid))
