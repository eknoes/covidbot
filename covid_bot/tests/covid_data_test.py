import shutil
from unittest import TestCase

from covid_bot.covid_data import CovidData


class CovidDataTest(TestCase):
    def test_find_ags(self):
        data = CovidData("../../data.csv")#
        self.assertEqual(2, len(data.find_rs("Kassel")), "2 Entities should be found for Kassel")
        self.assertEqual(1, len(data.find_rs("Berlin")), "Exact match should be chosen")
        
    def test_self_update(self):
        shutil.copy2("testdata.csv", "current_test.csv")
        data = CovidData("current_test.csv")
        self.assertEqual("21.12.2020, 00:00 Uhr", data.get_last_update())
        data.check_for_update()
        self.assertNotEqual("21.12.2020, 00:00 Uhr", data.get_last_update(), "CovidData should update itself")
        
    def test_init_online(self):
        data = CovidData()
        self.assertTrue(data.get_last_update(), "First Update should be true")