import os
from datetime import datetime
from unittest import TestCase

from covidbot.subscription_manager import SubscriptionManager


class SubscriptionManagerTest(TestCase):
    def test_all(self):
        if os.path.isfile("covidbot/tests/testuser_empty.json"):
            os.remove("covidbot/tests/testuser_empty.json")

        manager = SubscriptionManager("covidbot/tests/testuser_empty.json")  #
        self.assertEqual([], manager.get_subscribers(), "Subscribers of new list should be empty")

        manager.add_subscription(str(1), "test")
        self.assertIn("test", manager.get_subscriptions(str(1)), "Subscribers should have a subscription")
        manager.rm_subscription(str(1), "test")
        self.assertEqual(None, manager.get_subscriptions(str(1)))
        self.assertIsNone(manager.get_last_update(), "last_update should be None if initialized empty")
        manager.set_last_update(datetime(year=2020, month=1, day=1))
        self.assertEqual(datetime(year=2020, month=1, day=1), manager.get_last_update(),
                         "last_update should be changed "
                         "after set_last_update")

    def test_persistence(self):
        if os.path.isfile("covidbot/tests/testuser_empty.json"):
            os.remove("covidbot/tests/testuser_empty.json")

        manager = SubscriptionManager("covidbot/tests/testuser_empty.json")
        manager.add_subscription(str(1), "test1")
        manager.add_subscription(str(3), "test1")
        manager.add_subscription(str(2), "test2")
        manager.add_subscription(str(4), "removed")
        manager.rm_subscription(str(4), "removed")
        manager.set_last_update(datetime(year=2020, month=1, day=1))
        del manager

        manager = SubscriptionManager("covidbot/tests/testuser_empty.json")
        self.assertEqual({"test1"}, manager.get_subscriptions(str(1)), "Should save persistently")
        self.assertEqual({"test1"}, manager.get_subscriptions(str(3)), "Should save persistently")
        self.assertEqual({"test2"}, manager.get_subscriptions(str(2)), "Should save persistently")
        self.assertEqual(datetime(year=2020, month=1, day=1), manager.get_last_update(), "Should save persistently")
        self.assertIsNone(manager.get_subscriptions(str(4)), "Should remove persistently")
