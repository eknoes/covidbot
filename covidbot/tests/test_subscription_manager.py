from unittest import TestCase

import psycopg2
from psycopg2.extras import DictCursor
from psycopg2._psycopg import connection

from covidbot.subscription_manager import SubscriptionManager


class TestSubscriptionManager(TestCase):
    conn: connection

    def setUp(self) -> None:
        self.conn = psycopg2.connect(dbname="covid_test_db", user="covid_bot", password="covid_bot", port=5432,
                                            host='localhost', cursor_factory=DictCursor)
        self.manager = SubscriptionManager(self.conn)
        with self.conn as conn:
            with conn.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE subscriptions;")


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

        self.assertListEqual([1, 2], self.manager.get_subscriptions(1))
        self.assertListEqual([1], self.manager.get_subscriptions(2))
        self.assertListEqual([], self.manager.get_subscriptions(3), "A non existing user should not have subscriptions")

    def test_delete_user(self):
        self.fail()

    def test_get_all_user(self):
        self.fail()
