from unittest import TestCase

from covidbot.covid_data import CovidData


class CovidDataTest(TestCase):
    def setUp(self) -> None:
        self.data = CovidData(db_user="covid_bot", db_password="covid_bot", db_name="covid_test_db")

    def test_find_ags(self):
        self.assertEqual(2, len(self.data.find_rs("Kassel")), "2 Entities should be found for Kassel")
        self.assertEqual(1, len(self.data.find_rs("Berlin")), "Exact match should be chosen")

    def test_self_update(self):
        self.assertIsNotNone(self.data.get_last_update(), "Covid Data should fetch data")

    def test_no_update_current_data(self):
        self.assertFalse(self.data.fetch_current_data(), "Do not update if data has not changed")

    def test_brd(self):
        self.assertIsNotNone(self.data.get_country_data())

    def test_clean_district_name(self):
        expected = [("Region Hannover", "Hannover"), ("LK Kassel", "Kassel"),
                    ("LK Dillingen a.d.Donau", "Dillingen a.d.Donau"),
                    ("LK Bad Tölz-Wolfratshausen", "Bad Tölz-Wolfratshausen"), ("Berlin", "Berlin")]
        for item in expected:
            self.assertEqual(item[1], self.data.clean_district_name(item[0]),
                             "Clean name of " + item[0] + " should be " + item[1])
