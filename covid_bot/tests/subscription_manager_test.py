import os
from unittest import TestCase

from covid_bot.subscription_manager import SubscriptionManager


class SubscriptionManagerTest(TestCase):
    def test_all(self):
        if os.path.isfile("testuser_empty.json"):
            os.remove("testuser_empty.json")

        manager = SubscriptionManager("testuser_empty.json")#
        self.assertEqual([], manager.get_subscribers(), "Subscribers of new list should be empty")
        
        manager.add_subscription(1, "test")
        self.assertIn("test", manager.get_subscriptions(1), "Subscribers should have a subscription")
        manager.rm_subscription(1, "test")
        self.assertEqual(None, manager.get_subscriptions(1))
        self.assertIsNone(manager.get_last_update(), "last_update should be None if initialized empty")
        manager.set_last_update("Today")
        self.assertEqual("Today", manager.get_last_update(), "last_update should be changed after set_last_update")
    
    def test_persistence(self):
        if os.path.isfile("testuser_empty.json"):
            os.remove("testuser_empty.json")

        manager = SubscriptionManager("testuser_empty.json")
        manager.add_subscription(1, "test1")
        manager.add_subscription(3, "test1")
        manager.add_subscription(2, "test2")
        manager.add_subscription(4, "removed")
        manager.rm_subscription(4, "removed")
        manager.set_last_update("Today")
        del manager

        manager = SubscriptionManager("testuser_empty.json")
        self.assertEqual({"test1"}, manager.get_subscriptions(1), "Should save persistently")
        self.assertEqual({"test1"}, manager.get_subscriptions(3), "Should save persistently")
        self.assertEqual({"test2"}, manager.get_subscriptions(2), "Should save persistently")
        self.assertIsNone(manager.get_subscriptions(4), "Should remove persistently")
