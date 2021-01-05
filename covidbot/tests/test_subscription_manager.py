from datetime import datetime
from unittest import TestCase

import psycopg2
from psycopg2.extras import DictCursor
from psycopg2._psycopg import connection

from covidbot.subscription_manager import SubscriptionManager
from covidbot.tests.test_file_subscription_manager import SubscriptionManagerTest


class TestSubscriptionManager(TestCase):
    conn: connection

    def setUp(self) -> None:
        self.conn = psycopg2.connect(dbname="covid_test_db", user="covid_bot", password="covid_bot", port=5432,
                                     host='localhost', cursor_factory=DictCursor)
        self.manager = SubscriptionManager(self.conn)
        with self.conn as conn:
            with conn.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE subscriptions;")
                cursor.execute("TRUNCATE TABLE bot_user;")

    def tearDown(self) -> None:
        del self.manager
        self.conn.close()

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

        self.manager.migrate_from(old_manager)

        self.assertCountEqual([1, 2], self.manager.get_all_user(), "All users should be migrated")
        self.assertCountEqual([1, 2], self.manager.get_subscriptions(1), "All users should be migrated")
        self.assertCountEqual([1], self.manager.get_subscriptions(2), "All users should be migrated")

    def test_last_update(self):
        self.manager.add_subscription(1, 1)
        self.assertIsNone(self.manager.get_last_update(1), "Before an update, last_update should be None")
        expected = datetime.now()
        self.manager.set_last_update(1, expected)
        self.assertEqual(expected, self.manager.get_last_update(1))
        self.manager.delete_user(1)
        self.assertIsNone(self.manager.get_last_update(1), "last_update of an deleted user should be None")
