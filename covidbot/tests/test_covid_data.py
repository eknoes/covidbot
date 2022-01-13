from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import CovidData, RKIKeyDataUpdater, RKIHistoryUpdater


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
            cursor.execute("TRUNCATE TABLE covid_vaccinations;")
            cursor.execute("TRUNCATE TABLE covid_r_value;")
            cursor.execute("TRUNCATE TABLE hospitalisation;")
            cursor.execute("TRUNCATE TABLE icu_beds;")
            cursor.execute("TRUNCATE TABLE district_rules;")
            cursor.execute("TRUNCATE TABLE county_alt_names;")
            # noinspection SqlWithoutWhere
            cursor.execute("DELETE FROM counties ORDER BY parent DESC;")
        RKIKeyDataUpdater(self.conn).update()
        history = RKIHistoryUpdater(self.conn)
        history.max_delta = 0
        history.min_delta = 10
        history.update()
        self.conn.commit()

    def tearDown(self) -> None:
        del self.data

    def test_unicode(self):
        self.assertIsNotNone(self.data.search_district_by_name("den neuen Bericht finde ich super! 👍🏽"))

    def test_find_ags(self):
        self.assertEqual(2, len(self.data.search_district_by_name("Kassel")), "2 Entities should be found for Kassel")
        self.assertEqual(1, len(self.data.search_district_by_name("Essen")), "Exact match should be chosen")
        self.assertEqual(1, len(self.data.search_district_by_name("Berlin")), "Exact match should be chosen")
        self.assertEqual(1, len(self.data.search_district_by_name("Kassel Stadt")),
                         "Kassel Stadt should match SK Kassel")
        self.assertEqual(1, len(self.data.search_district_by_name("Stadt Kassel")),
                         "Stadt Kassel should match SK Kassel")
        self.assertEqual(1, len(self.data.search_district_by_name("Göttingen")), "Göttingen should match")
        self.assertEqual(1, len(self.data.search_district_by_name("Kassel Land")), "Kassel Land should match LK Kassel")
        self.assertEqual(1, len(self.data.search_district_by_name("Bundesland Hessen")), "Exact match should be chosen")

    def test_find_abbr(self):
        self.assertEqual(1, len(self.data.search_district_by_name("SH")))
        self.assertEqual(1, len(self.data.search_district_by_name("NRW")), "NRW should match")

    def test_get_district_data(self):
        data = self.data.get_district_data(3151)

        self.assertIsNotNone(data, "Data for District#11 must be available")
        self.assertIsNotNone(data.new_cases, "New Cases for today must be available")
        self.assertIsNotNone(data.new_deaths, "New Deaths for today must be available")
        self.assertIsNotNone(data.incidence, "Incidence for today must be available")
        self.assertIsNotNone(data.cases_trend, "Trend for today must be available")
        self.assertIsNotNone(data.deaths_trend, "Trend for today must be available")
        self.assertIsNotNone(data.incidence_trend, "Trend for today must be available")

        non_existent = self.data.get_district_data(9999999999999)
        self.assertIsNone(non_existent, "get_district_data should return None for non-existing data")