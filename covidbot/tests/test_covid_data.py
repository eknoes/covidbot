from datetime import date
from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import CovidData, DistrictData, TrendValue, RKIUpdater


class CovidDataTest(TestCase):
    conn: MySQLConnection

    @classmethod
    def setUpClass(cls) -> None:
        cfg = parse_config("resources/config.unittest.ini")
        cls.conn = get_connection(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def setUp(self) -> None:
        self.data = CovidData(self.conn)

        with self.conn.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE covid_data;")
            # noinspection SqlWithoutWhere
            cursor.execute("DELETE FROM counties ORDER BY parent DESC;")
            with open("resources/2021-01-16-testdata-counties.sql", "r") as f:
                for stmt in f.readlines():
                    cursor.execute(stmt)

            with open("resources/2021-01-16-testdata-covid_data.sql", "r") as f:
                for stmt in f.readlines():
                    cursor.execute(stmt)

            updater = RKIUpdater(self.conn)
            updater.calculate_aggregated_values(date.fromisoformat("2021-01-16"))

    def tearDown(self) -> None:
        del self.data

    def test_find_ags(self):
        self.assertEqual(2, len(self.data.search_district_by_name("Kassel")), "2 Entities should be found for Kassel")
        self.assertEqual(1, len(self.data.search_district_by_name("Berlin")), "Exact match should be chosen")
        self.assertEqual(1, len(self.data.search_district_by_name("Kassel Stadt")),
                         "Kassel Stadt should match SK Kassel")
        self.assertEqual(1, len(self.data.search_district_by_name("Stadt Kassel")),
                         "Stadt Kassel should match SK Kassel")
        self.assertEqual(1, len(self.data.search_district_by_name("Göttingen")),
                         "Göttingen should match")
        self.assertEqual(1, len(self.data.search_district_by_name("Kassel Land")), "Kassel Land should match LK Kassel")
        self.assertEqual(1, len(self.data.search_district_by_name("Bundesland Hessen")), "Exact match should be chosen")

    def test_clean_district_name(self):
        expected = [("Region Hannover", "Hannover"), ("LK Kassel", "Kassel"),
                    ("LK Dillingen a.d.Donau", "Dillingen a.d.Donau"),
                    ("LK Bad Tölz-Wolfratshausen", "Bad Tölz-Wolfratshausen"), ("Berlin", "Berlin")]
        for item in expected:
            self.assertEqual(item[1], self.data.clean_district_name(item[0]),
                             "Clean name of " + item[0] + " should be " + item[1])

    def test_get_district_data(self):
        data = self.data.get_district_data(3151)

        self.assertIsNotNone(data, "Data for District#11 must be available")
        self.assertIsNotNone(data.new_cases, "New Cases for today must be available")
        self.assertIsNotNone(data.new_deaths, "New Deaths for today must be available")
        self.assertIsNotNone(data.incidence, "Incidence for today must be available")
        self.assertIsNotNone(data.cases_trend, "Trend for today must be available")
        self.assertIsNotNone(data.deaths_trend, "Trend for today must be available")
        self.assertIsNotNone(data.incidence_trend, "Trend for today must be available")

        yesterday = self.data.get_district_data(11, subtract_days=1)
        self.assertIsNotNone(yesterday, "Data for District#11 from yesterday must be available")

        long_time_ago = self.data.get_district_data(11, subtract_days=9999)
        self.assertIsNone(long_time_ago, "get_district_data should return None for non-existing data")

        non_existent = self.data.get_district_data(9999999999999)
        self.assertIsNone(non_existent, "get_district_data should return None for non-existing data")

        history = self.data.get_district_data(1, include_past_days=13)
        self.assertEqual(14, len(history), "GetCovidDataHistory should return 14 DistrictData items")

        history = self.data.get_district_data(3151, include_past_days=14)
        self.assertEqual(15, len(history), "GetCovidDataHistory should return 15 DistrictData items")

    def test_fill_trend(self):
        today = DistrictData("Test1", new_cases=5, new_deaths=5, incidence=5)
        last_week = DistrictData("Test1", new_cases=5, new_deaths=6, incidence=4)

        trend_d1 = self.data.fill_trend(today, last_week)
        self.assertEqual(TrendValue.UP, trend_d1.incidence_trend)
        self.assertEqual(TrendValue.SAME, trend_d1.cases_trend)
        self.assertEqual(TrendValue.DOWN, trend_d1.deaths_trend)

    def test_country_data(self):
        # Test if number calculation is correct
        data = self.data.get_country_data()

        self.assertIsNotNone(self.data.get_country_data())
        self.assertEqual(18678, data.new_cases, "New Cases on 16.01.2020 should be 18,678 for Germany")
        self.assertEqual(980, data.new_deaths, "New Deaths on 16.01.2020 should be 980 for Germany")
        self.assertEqual(139.24, data.incidence, "Incidence on 16.01.2020 should be 139.2 for Germany")


class TestRKIUpdater(TestCase):
    conn: MySQLConnection

    @classmethod
    def setUpClass(cls) -> None:
        cfg = parse_config("resources/config.unittest.ini")
        cls.conn = get_connection(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_update(self):
        with self.conn.cursor() as cursor:
            cursor.execute("TRUNCATE covid_data")

        updater = RKIUpdater(self.conn)
        self.assertIsNone(updater.fetch_current_data(), "Update should not lead to any exception")
