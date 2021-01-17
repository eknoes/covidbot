from unittest import TestCase

from freezegun import freeze_time
from mysql.connector import MySQLConnection
from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import CovidData


class CovidDataTest(TestCase):
    conn: MySQLConnection

    @classmethod
    def setUpClass(cls) -> None:
        cfg = parse_config("resources/config.unittest.ini")
        cls.conn = get_connection(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    @freeze_time("2021-01-16 12:00:00")
    def setUp(self) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute("TRUNCATE covid_data;")
            cursor.execute("DELETE FROM counties WHERE parent IS NOT NULL;")
            cursor.execute("DELETE FROM counties WHERE parent IS NULL;")
            with open("resources/2021-01-16-testdata-counties.sql", "r") as f:
                for stmt in f.readlines():
                    cursor.execute(stmt)

            with open("resources/2021-01-16-testdata-covid_data.sql", "r") as f:
                for stmt in f.readlines():
                    cursor.execute(stmt)

        self.data = CovidData(self.conn)

    def tearDown(self) -> None:
        del self.data

    def test_find_ags(self):
        self.assertEqual(2, len(self.data.find_rs("Kassel")), "2 Entities should be found for Kassel")
        self.assertEqual(1, len(self.data.find_rs("Berlin")), "Exact match should be chosen")
        self.assertEqual(1, len(self.data.find_rs("Kassel Stadt")), "Kassel Stadt should match SK Kassel")
        self.assertEqual(1, len(self.data.find_rs("Stadt Kassel")), "Stadt Kassel should match SK Kassel")
        self.assertEqual(1, len(self.data.find_rs("Kassel Land")), "Kassel Land should match LK Kassel")
        self.assertEqual(1, len(self.data.find_rs("Bundesland Hessen")), "Exact match should be chosen")

    def test_update(self):
        with self.conn.cursor() as cursor:
            cursor.execute("TRUNCATE covid_data")
        self.assertTrue(self.data.fetch_current_data(), "Do update if newer data is available")
        self.assertFalse(self.data.fetch_current_data(), "Do not update if data has not changed")

    def test_clean_district_name(self):
        expected = [("Region Hannover", "Hannover"), ("LK Kassel", "Kassel"),
                    ("LK Dillingen a.d.Donau", "Dillingen a.d.Donau"),
                    ("LK Bad Tölz-Wolfratshausen", "Bad Tölz-Wolfratshausen"), ("Berlin", "Berlin")]
        for item in expected:
            self.assertEqual(item[1], self.data.clean_district_name(item[0]),
                             "Clean name of " + item[0] + " should be " + item[1])

    def test_country_data(self):
        # Test if number calculation is correct
        data = self.data.get_country_data()
        
        self.assertIsNotNone(self.data.get_country_data())
        self.assertEqual(18678, data.new_cases, "New Cases on 16.01.2020 should be 18,678 for Germany")
        self.assertEqual(980, data.new_deaths, "New Deaths on 16.01.2020 should be 980 for Germany")
    
    def test_get_covid_data_history(self):
        history = self.data.get_covid_data_history(1, 14)

        self.assertEqual(14, len(history), "GetCovidDataHistory should return 14 DistrictData")