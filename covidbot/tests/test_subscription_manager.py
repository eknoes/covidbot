from datetime import datetime
from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import CovidData
from covidbot.user_manager import UserManager
from covidbot.utils import MessageType


class TestSubscriptionManager(TestCase):
    conn: MySQLConnection

    @classmethod
    def setUpClass(cls) -> None:
        cfg = parse_config("resources/config.unittest.ini")
        cls.conn = get_connection(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def setUp(self) -> None:
        with self.conn.cursor(dictionary=True) as cursor:
            cursor.execute("DROP TABLE IF EXISTS subscriptions;")
            cursor.execute("DROP TABLE IF EXISTS bot_user_settings;")
            cursor.execute("DROP TABLE IF EXISTS user_feedback;")
            cursor.execute("DROP TABLE IF EXISTS bot_user_sent_reports;")
            cursor.execute("DROP TABLE IF EXISTS report_subscriptions;")
            cursor.execute("DROP TABLE IF EXISTS hospitalisation;")
            cursor.execute("DROP TABLE IF EXISTS user_responses;")
            cursor.execute("DROP TABLE IF EXISTS user_ticket_tag;")
            cursor.execute("DROP TABLE IF EXISTS bot_user;")

        self.test_manager = UserManager("unittest", self.conn)

    def tearDown(self) -> None:
        del self.test_manager

    def test_add_subscription(self):
        user_id = self.test_manager.get_user_id("testuser")
        self.assertTrue(self.test_manager.add_subscription(user_id, 1),
                        "Adding a non-existing subscription should return true")
        self.assertFalse(self.test_manager.add_subscription(user_id, 1),
                         "Adding an existing subscription should return false")

    def test_rm_subscription(self):
        user_id = self.test_manager.get_user_id("testuser")
        self.test_manager.add_subscription(user_id, 1)
        self.assertTrue(self.test_manager.rm_subscription(user_id, 1),
                        "Removing a non-existing subscription should return true")
        self.assertFalse(self.test_manager.rm_subscription(user_id, 1),
                         "Removing an existing subscription should return false")

    def test_activated(self):
        user_id = self.test_manager.get_user_id("testuser")
        self.assertTrue(self.test_manager.get_user(user_id).activated)

        test_manager = UserManager("unittest2", self.conn, activated_default=False)
        user_id = test_manager.get_user_id("testuser")
        self.assertFalse(test_manager.get_user(user_id).activated)

    def test_get_user(self):
        uid1 = self.test_manager.get_user_id("testuser1")
        uid2 = self.test_manager.get_user_id("testuser2")

        self.test_manager.add_subscription(uid1, 1)
        self.test_manager.add_subscription(uid1, 2)
        self.test_manager.add_subscription(uid2, 1)

        user1 = self.test_manager.get_user(uid1, with_subscriptions=True)
        user2 = self.test_manager.get_user(uid2, with_subscriptions=True)

        self.assertCountEqual([1, 2], user1.subscriptions)
        self.assertListEqual([1], user2.subscriptions)
        self.assertIsNone(self.test_manager.get_user(3), "Return None for a non existing user")

        current_user1 = self.test_manager.get_user(uid1, with_subscriptions=False)
        self.assertIsNone(current_user1.subscriptions, "with_subscriptions=False should not return any subscriptions")

        self.test_manager.delete_user(uid1)
        self.assertIsNone(self.test_manager.get_user(uid1), "Return None for a non existing user")

    def test_new_user(self):
        uid1 = self.test_manager.get_user_id("testuser1")
        self.assertIsNotNone(self.test_manager.get_user(uid1), "Getting a user_id should create the user if not "
                                                               "already existing")

        uid2 = self.test_manager.create_user("testuser2")
        self.assertEqual(self.test_manager.get_user(uid2, with_subscriptions=True).subscriptions, [],
                         "New user should have no subscriptions")

        self.assertCountEqual([MessageType.CASES_GERMANY],
                              self.test_manager.get_user(uid2, with_subscriptions=True).subscribed_reports,
                              f"New user should be subscribed to {MessageType.CASES_GERMANY}")

    def test_create_user(self):
        self.assertTrue(self.test_manager.create_user("1"), "Creating a non-existing user should return True")
        self.assertFalse(self.test_manager.create_user("1"), "Creating an existing user should return False")

    def test_delete_user(self):
        uid1 = self.test_manager.get_user_id("testuser1")
        uid2 = self.test_manager.get_user_id("testuser2")
        self.test_manager.add_subscription(uid1, 1)
        self.test_manager.add_subscription(uid1, 2)
        self.test_manager.add_subscription(uid2, 1)
        self.assertTrue(self.test_manager.delete_user(uid1),
                        "Deleting an existing user with subscriptions should return true")
        self.assertFalse(self.test_manager.delete_user(uid1), "Deleting an non-existing user should return false")

        self.test_manager.add_feedback(uid2, "Testfeedback")
        self.assertTrue(self.test_manager.delete_user(uid2),
                        "Deleting an existing user with feedback should return true")

    def test_get_all_user(self):
        uid1 = self.test_manager.get_user_id("testuser1")
        uid2 = self.test_manager.get_user_id("testuser2")

        self.test_manager.add_subscription(uid1, 1)
        self.test_manager.add_subscription(uid1, 2)
        self.test_manager.add_subscription(uid2, 1)

        self.assertCountEqual([1, 2], map(lambda u: u.id, self.test_manager.get_all_user()),
                              "All users with subscriptions should be returned")

        self.test_manager.rm_subscription(uid2, 1)
        self.assertEqual(uid2, len(self.test_manager.get_all_user()),
                         "Users with removed subscriptions should still exist")

        self.test_manager.delete_user(uid1)
        self.test_manager.delete_user(uid2)
        self.assertListEqual([], self.test_manager.get_all_user(),
                             "If no subscribers exist, list of user should be empty")

    def test_statistic(self):
        self.assertEqual(self.test_manager.get_messenger_user_number(), 0,
                         "get_total_user should return 0 if no users are present")

        uid1 = self.test_manager.get_user_id("testuser1")
        uid2 = self.test_manager.get_user_id("testuser2")
        uid3 = self.test_manager.get_user_id("testuser3")

        self.test_manager.add_subscription(uid1, 1)
        self.test_manager.add_subscription(uid1, 2)
        self.test_manager.add_subscription(uid2, 1)
        self.test_manager.add_subscription(uid3, 1)

        # Make sure table exists
        CovidData(self.conn)

        with self.conn.cursor() as cursor:
            # noinspection SqlWithoutWhere
            cursor.execute("DELETE FROM covid_data")
            cursor.execute("TRUNCATE TABLE covid_vaccinations;")
            cursor.execute("TRUNCATE TABLE covid_r_value;")
            cursor.execute("TRUNCATE TABLE icu_beds;")
            cursor.execute("TRUNCATE TABLE district_rules;")
            cursor.execute("TRUNCATE TABLE hospitalisation;")
            # noinspection SqlWithoutWhere
            cursor.execute("DELETE FROM county_alt_names")
            # noinspection SqlWithoutWhere
            cursor.execute("DELETE FROM counties ORDER BY parent DESC")
            cursor.executemany("INSERT INTO counties (rs, county_name) VALUES (%s, %s)", [(1, "Test1"), (2, "Test2")])
        self.assertEqual(self.test_manager.get_messenger_user_number(), 3,
                         "get_total_user should return the number of users")
        self.assertEqual(len(self.test_manager.get_ranked_subscriptions()), 2,
                         "len(get_ranked_subscriptions) should return "
                         "the number of subscribed counties")
        self.assertCountEqual(self.test_manager.get_ranked_subscriptions(), [(3, "Test1"), (1, "Test2")],
                              "get_ranked_subscriptions should return a ranking of subscriptions")
        self.assertEqual(self.test_manager.get_ranked_subscriptions()[0], (3, "Test1"),
                         "get_ranked_subscriptions result should be sorted")

    def test_feedback(self):
        user_id = self.test_manager.get_user_id("testuser1")
        feedback = "I quite like it!"

        self.assertIsNotNone(self.test_manager.add_feedback(user_id, feedback), "Feedback should be added successfully")
        self.assertIsNotNone(self.test_manager.add_feedback(user_id, feedback),
                             "Same Feedback should be added successfully")
        self.assertIsNone(self.test_manager.add_feedback(user_id, ""), "Null Feedback should not be added successfully")

    def test_get_most_subscriptions(self):
        self.assertEqual(0, self.test_manager.get_most_subscriptions(), "Without users 0 should be the number of most "
                                                                        "subscriptions")

        uid1 = self.test_manager.get_user_id("testuser1")
        uid2 = self.test_manager.get_user_id("testuser2")
        self.assertEqual(0, self.test_manager.get_most_subscriptions(),
                         "Without subscriptions 0 should be the number of most "
                         "subscriptions")

        self.test_manager.add_subscription(uid1, 1)
        self.test_manager.add_subscription(uid1, 2)
        self.test_manager.add_subscription(uid1, 3)
        self.assertEqual(3, self.test_manager.get_most_subscriptions())

        self.test_manager.add_subscription(uid2, 1)
        self.assertEqual(3, self.test_manager.get_most_subscriptions())

        self.test_manager.add_subscription(uid2, 2)
        self.test_manager.add_subscription(uid2, 3)
        self.test_manager.add_subscription(uid2, 4)
        self.assertEqual(4, self.test_manager.get_most_subscriptions())
