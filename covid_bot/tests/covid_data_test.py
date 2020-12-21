from unittest import TestCase

from covid_bot.covid_data import CovidData


class CovidDataTest(TestCase):
    def test_find_ags(self):
        data = CovidData("../../data.csv")#
        self.assertEqual(2, len(data.find_rs("Kassel")), "2 Entities should be found for Kassel")
        self.assertEqual(12, len(data.find_rs("Berlin")), "Berlin should appear 12 times")