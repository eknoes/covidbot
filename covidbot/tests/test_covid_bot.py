import os
from datetime import datetime
from unittest import TestCase

from covidbot.bot import Bot
from covidbot.covid_data import CovidData
from covidbot.subscription_manager import SubscriptionManager


class CovidBotTest(TestCase):
    def test_main(self):
        if os.path.isfile("covidbot/tests/testuser_empty.json"):
            os.remove("covidbot/tests/testuser_empty.json")
        man = SubscriptionManager("covidbot/tests/testuser_empty.json")
        bot = Bot(CovidData(db_user="covidbot", db_password="covidbot", db_name="covid_db"), man)
        self.assertEqual([], bot.update(), "Empty subscribers should generate empty update list")
        bot.subscribe("testuser", "Berlin")
        bot.subscribe("testuser2", "Hannover")
        self.assertEqual([], bot.update(), "Without new data no reports should be generated")
        man.set_last_update(datetime(year=2019, month=12, day=1))
        self.assertEqual(2, len(bot.update()), "New data should trigger 2 updates")
        self.assertEqual([], bot.update(), "Without new data no reports should be generated")
        del bot

        # Test persistence
        bot = Bot(CovidData(db_user="covidbot", db_password="covidbot", db_name="covid_db"),
                  SubscriptionManager("covidbot/tests/testuser_empty.json"))
        self.assertEqual([], bot.update(), "After recreation no update should be triggerd")
