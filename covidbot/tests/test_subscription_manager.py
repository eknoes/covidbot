from datetime import datetime
from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.subscription_manager import SubscriptionManager


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
        self.manager = SubscriptionManager(self.conn)
        with self.conn.cursor(dictionary=True) as cursor:
            cursor.execute("TRUNCATE subscriptions")
            # noinspection SqlWithoutWhere
            cursor.execute("DELETE FROM bot_user")

    def tearDown(self) -> None:
        del self.manager

    def test_add_subscription(self):
        self.assertTrue(self.manager.add_subscription(1, 1), "Adding a non-existing subscription should return true")
        self.assertFalse(self.manager.add_subscription(1, 1), "Adding an existing subscription should return false")

    def test_rm_subscription(self):
        self.manager.add_subscription(1, 1)
        self.assertTrue(self.manager.rm_subscription(1, 1), "Removing a non-existing subscription should return true")
        self.assertFalse(self.manager.rm_subscription(1, 1), "Removing an existing subscription should return false")

    def test_get_subscriptions(self):
        self.manager.add_subscription(1, 1)
        self.manager.add_subscription(1, 2)
        self.manager.add_subscription(2, 1)

        self.assertCountEqual([1, 2], self.manager.get_subscriptions(1))
        self.assertListEqual([1], self.manager.get_subscriptions(2))
        self.assertListEqual([], self.manager.get_subscriptions(3), "A non existing user should not have subscriptions")

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

        self.assertCountEqual([1, 2], self.manager.get_all_user(), "All users with subscriptions should be returned")

        self.manager.rm_subscription(2, 1)
        self.assertListEqual([1], self.manager.get_all_user(), "Users with removed subscriptions should not exist")

        self.manager.delete_user(1)
        self.assertListEqual([], self.manager.get_all_user(), "If no subscribers exist, list of user should be empty")

    def test_last_update(self):
        self.manager.add_subscription(1, 1)
        self.assertIsNone(self.manager.get_last_update(1), "Before an update, last_update should be None")
        expected = datetime.now()
        self.manager.set_last_update(1, expected)
        self.assertEqual(expected, self.manager.get_last_update(1))
        self.manager.delete_user(1)
        self.assertIsNone(self.manager.get_last_update(1), "last_update of an deleted user should be None")

    def test_statistic(self):
        self.assertEqual(self.manager.get_total_user(), 0, "get_total_user should return 0 if no users are present")

        self.manager.add_subscription(1, 1)
        self.manager.add_subscription(1, 2)
        self.manager.add_subscription(2, 1)
        self.manager.add_subscription(3, 1)

        with self.conn.cursor() as cursor:
            cursor.execute("DELETE FROM covid_data")
            cursor.execute("DELETE FROM counties WHERE parent IS NOT NULL")
            cursor.execute("DELETE FROM counties")
            cursor.executemany("INSERT INTO counties (rs, county_name) VALUES (%s, %s)", [(1, "Test1"), (2, "Test2")])
        self.assertEqual(self.manager.get_total_user(), 3, "get_total_user should return the number of users")
        self.assertEqual(len(self.manager.get_ranked_subscriptions()), 2, "len(get_ranked_subscriptions) should return "
                                                                          "the number of subscribed counties")
        self.assertCountEqual(self.manager.get_ranked_subscriptions(), [(3, "Test1"), (1, "Test2")],
                              "get_ranked_subscriptions should return a ranking of subscriptions")
        self.assertEqual(self.manager.get_ranked_subscriptions()[0], (3, "Test1"),
                         "get_ranked_subscriptions result should be sorted")
