import shutil
from unittest import TestCase

from covidbot.covid_data import CovidData


class CovidDataTest(TestCase):
    def test_find_ags(self):
        shutil.copy2("covidbot/tests/testdata.csv", "covidbot/tests/current_test.csv")
        data = CovidData(db_user="covid_bot", db_password="covid_bot", db_name="covid_test_db")
        data.add_data("covidbot/tests/current_test.csv")
        self.assertEqual(2, len(data.find_rs("Kassel")), "2 Entities should be found for Kassel")
        self.assertEqual(1, len(data.find_rs("Berlin")), "Exact match should be chosen")

    def test_self_update(self):
        data = CovidData(db_user="covid_bot", db_password="covid_bot", db_name="covid_test_db")
        self.assertIsNotNone(data.get_last_update(), "Covid Data should fetch data")

    def test_no_update_current_data(self):
        data = CovidData(db_user="covid_bot", db_password="covid_bot", db_name="covid_test_db")
        self.assertFalse(data.fetch_current_data(), "Do not update if data has not changed")

    def test_brd(self):
        data = CovidData(db_user="covid_bot", db_password="covid_bot", db_name="covid_test_db")
        self.assertIsNotNone(data.get_country_data())
