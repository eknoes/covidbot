from unittest import TestCase

from covid_bot.covid_data import CovidData


class CovidDataTest(TestCase):
    def test_find_ags(self):
        data = CovidData("../../data.csv")#
        self.assertEqual(len(data.find_ags("Kassel")), 2, "2 Entities should be found for Kassel")