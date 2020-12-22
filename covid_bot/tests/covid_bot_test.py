from unittest import TestCase

from covid_bot.covid_bot import CovidBot
from covid_bot.covid_data import CovidData
from covid_bot.subscription_manager import SubscriptionManager


class CovidBotTest(TestCase):
    def test_main(self):
        man = SubscriptionManager("test")
        bot = CovidBot(CovidData(), man)
        self.assertEqual([], bot.update(), "Empty subscribers should generate empty update list")
        bot.subscribe("testuser", "Berlin")
        bot.subscribe("testuser2", "Hannover")
        self.assertEqual([], bot.update(), "Without new data no reports should be generated")
        man.set_last_update("yesterday")
        self.assertEqual(2, len(bot.update()), "New data should trigger 2 updates")
        self.assertEqual([], bot.update(), "Without new data no reports should be generated")
