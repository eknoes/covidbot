import shutil
from datetime import datetime
from unittest import TestCase

from covidbot.covid_data import CovidData


class CovidDataTest(TestCase):
    def test_find_ags(self):
        shutil.copy2("covidbot/tests/testdata.csv", "covidbot/tests/current_test.csv")
        data = CovidData("covidbot/tests/current_test.csv")
        self.assertEqual(2, len(data.find_rs("Kassel")), "2 Entities should be found for Kassel")
        self.assertEqual(1, len(data.find_rs("Berlin")), "Exact match should be chosen")

    def test_self_update(self):
        shutil.copy2("covidbot/tests/testdata.csv", "covidbot/tests/current_test.csv")
        data = CovidData("covidbot/tests/current_test.csv")
        self.assertEqual(datetime(year=2020, month=12, day=21), data.get_last_update())
        data.fetch_current_data()
        self.assertNotEqual(datetime(year=2020, month=12, day=21), data.get_last_update(),
                            "CovidData should update itself")

    def test_no_update_current_data(self):
        data = CovidData()
        self.assertFalse(data.fetch_current_data(), "Do not update if data has not changed")
