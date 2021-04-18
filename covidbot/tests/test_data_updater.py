from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import RKIUpdater, VaccinationGermanyUpdater, RValueGermanyUpdater, \
    VaccinationGermanyImpfdashboardUpdater
from covidbot.covid_data import clean_district_name, ICUGermanyUpdater, RulesGermanyUpdater


class TestUpdater(TestCase):
    conn: MySQLConnection

    @classmethod
    def setUpClass(cls) -> None:
        cfg = parse_config("resources/config.unittest.ini")
        cls.conn = get_connection(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_update(self):
        with self.conn.cursor() as c:
            c.execute("DROP TABLE covid_data")
            c.execute("DROP TABLE covid_vaccinations")
            c.execute("DROP TABLE covid_r_value")
            c.execute("DROP TABLE district_rules")
            c.execute("DROP TABLE icu_beds")

        rki = RKIUpdater(self.conn)
        rki.update()
        updater = VaccinationGermanyImpfdashboardUpdater(self.conn)
        self.assertTrue(updater.update(), "VaccinationGermanyImpfdashboardUpdater should update")
        updater = VaccinationGermanyUpdater(self.conn)
        self.assertTrue(updater.update(), "VaccinationGermanyUpdater should update")
        updater = RValueGermanyUpdater(self.conn)
        self.assertTrue(updater.update(), "RValueGermanyUpdater should update")
        updater = ICUGermanyUpdater(self.conn)
        self.assertTrue(updater.update(), "ICUGermanyUpdater should update")
        updater = RulesGermanyUpdater(self.conn)
        self.assertTrue(updater.update(), "RulesGermanyUpdater should update")

    def test_clean_district_name(self):
        expected = [("Region Hannover", "Hannover"), ("LK Kassel", "Kassel"),
                    ("LK Dillingen a.d.Donau", "Dillingen a.d.Donau"),
                    ("LK Bad Tölz-Wolfratshausen", "Bad Tölz-Wolfratshausen"), ("Berlin", "Berlin")]
        for item in expected:
            self.assertEqual(item[1], clean_district_name(item[0]),
                             "Clean name of " + item[0] + " should be " + item[1])
