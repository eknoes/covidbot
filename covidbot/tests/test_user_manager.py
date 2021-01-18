from datetime import datetime
from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import CovidData
from covidbot.user_manager import UserManager


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
            cursor.execute("DROP TABLE IF EXISTS bot_user;")

        self.manager = UserManager(self.conn)

    def tearDown(self) -> None:
        del self.manager

    def test_add_subscription(self):
        self.assertTrue(self.manager.add_subscription(1, 1), "Adding a non-existing subscription should return true")
        self.assertFalse(self.manager.add_subscription(1, 1), "Adding an existing subscription should return false")

    def test_rm_subscription(self):
        self.manager.add_subscription(1, 1)
        self.assertTrue(self.manager.rm_subscription(1, 1), "Removing a non-existing subscription should return true")
        self.assertFalse(self.manager.rm_subscription(1, 1), "Removing an existing subscription should return false")

    def test_get_user(self):
        self.manager.add_subscription(1, 1)
        self.manager.add_subscription(1, 2)
        self.manager.add_subscription(2, 1)

        user1 = self.manager.get_user(1, with_subscriptions=True)
        user2 = self.manager.get_user(2, with_subscriptions=True)

        self.assertCountEqual([1, 2], user1.subscriptions)
        self.assertListEqual([1], user2.subscriptions)
        self.assertIsNone(self.manager.get_user(3), "Return None for a non existing user")

        self.assertEqual(datetime.today().date(), user1.last_update.date(),
                         "After user creation, last_update should be the current day")

        expected_update = datetime.now()
        expected_language = "en"
        self.manager.set_last_update(1, expected_update)
        self.manager.set_language(1, "en")

        current_user1 = self.manager.get_user(1, with_subscriptions=False)
        self.assertEqual(expected_update, current_user1.last_update)
        self.assertEqual(expected_language, current_user1.language)
        self.assertIsNone(current_user1.subscriptions, "with_subscriptions=False should not return any subscriptions")

        self.manager.delete_user(1)
        self.assertIsNone(self.manager.get_user(1), "Return None for a non existing user")

    def test_new_user(self):
        self.manager.set_language(1, "de")
        
        expected_date = datetime.today()
        self.manager.set_last_update(2, expected_date)

        self.assertEqual(self.manager.get_user(1).language, "de", "Setting language of a new user should create the "
                                                                  "user")
        self.assertEqual(self.manager.get_user(2).last_update, expected_date,
                         "Setting last_update of a new user should create the user")

        self.manager.create_user(3)
        self.assertEqual(self.manager.get_user(3, with_subscriptions=True).subscriptions, [],
                         "New user should have no subscriptions")

    def test_create_user(self):
        self.assertTrue(self.manager.create_user(1), "Creating a non-existing user should return True")
        self.assertFalse(self.manager.create_user(1), "Creating an existing user should return False")

    def test_delete_user(self):
        self.assertFalse(self.manager.delete_user(1), "Deleting an non-existing user should return false")
        self.manager.add_subscription(1, 1)
        self.manager.add_subscription(1, 2)
        self.manager.add_subscription(2, 1)
        self.assertTrue(self.manager.delete_user(1), "Deleting an existing user should return true")
        self.assertFalse(self.manager.delete_user(1), "Deleting an non-existing user should return false")
        self.assertTrue(self.manager.delete_user(2), "Deleting an existing user should return true")

    def test_get_all_user(self):
        self.manager.add_subscription(1, 1)
        self.manager.add_subscription(1, 2)
        self.manager.add_subscription(2, 1)

        self.assertCountEqual([1, 2], map(lambda u: u.id, self.manager.get_all_user()),
                              "All users with subscriptions should be returned")

        self.manager.rm_subscription(2, 1)
        self.assertEqual(2, len(self.manager.get_all_user()), "Users with removed subscriptions should still exist")

        self.manager.delete_user(1)
        self.manager.delete_user(2)
        self.assertListEqual([], self.manager.get_all_user(), "If no subscribers exist, list of user should be empty")

    def test_statistic(self):
        self.assertEqual(self.manager.get_total_user_number(), 0,
                         "get_total_user should return 0 if no users are present")

        self.manager.add_subscription(1, 1)
        self.manager.add_subscription(1, 2)
        self.manager.add_subscription(2, 1)
        self.manager.add_subscription(3, 1)

        # Make sure table exists
        CovidData(self.conn)
    
        with self.conn.cursor() as cursor:
            cursor.execute("DELETE FROM covid_data")
            cursor.execute("DELETE FROM counties ORDER BY parent DESC")
            cursor.executemany("INSERT INTO counties (rs, county_name) VALUES (%s, %s)", [(1, "Test1"), (2, "Test2")])
        self.assertEqual(self.manager.get_total_user_number(), 3, "get_total_user should return the number of users")
        self.assertEqual(len(self.manager.get_ranked_subscriptions()), 2, "len(get_ranked_subscriptions) should return "
                                                                          "the number of subscribed counties")
        self.assertCountEqual(self.manager.get_ranked_subscriptions(), [(3, "Test1"), (1, "Test2")],
                              "get_ranked_subscriptions should return a ranking of subscriptions")
        self.assertEqual(self.manager.get_ranked_subscriptions()[0], (3, "Test1"),
                         "get_ranked_subscriptions result should be sorted")
