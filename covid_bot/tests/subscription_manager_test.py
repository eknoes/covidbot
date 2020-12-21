import os
from unittest import TestCase

from covid_bot.covid_data import CovidData
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
        self.assertEqual(set(), manager.get_subscriptions(1))