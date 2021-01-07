from datetime import datetime
from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.subscription_manager import SubscriptionManager
from covidbot.tests.test_file_subscription_manager import SubscriptionManagerTest


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

    def test_migrate(self):
        old_manager_test = SubscriptionManagerTest()
        old_manager_test.setUp()
        old_manager = old_manager_test.manager

        old_manager.add_subscription(1, 1)
        old_manager.add_subscription(1, 2)
        old_manager.add_subscription(2, 1)

        last_update = datetime.now()
        old_manager.set_last_update(last_update)

        self.manager.migrate_from(old_manager)

        self.assertCountEqual([1, 2], self.manager.get_all_user(), "All users should be migrated")
        self.assertCountEqual([1, 2], self.manager.get_subscriptions(1), "All users should be migrated")
        self.assertCountEqual([1], self.manager.get_subscriptions(2), "All users should be migrated")
        self.assertEqual(last_update, self.manager.get_last_update(1), "last_update should be migrated")
        self.assertEqual(last_update, self.manager.get_last_update(2), "last_update should be migrated")

    def test_last_update(self):
        self.manager.add_subscription(1, 1)
        self.assertIsNone(self.manager.get_last_update(1), "Before an update, last_update should be None")
        expected = datetime.now()
        self.manager.set_last_update(1, expected)
        self.assertEqual(expected, self.manager.get_last_update(1))
        self.manager.delete_user(1)
        self.assertIsNone(self.manager.get_last_update(1), "last_update of an deleted user should be None")
