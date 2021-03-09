from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import RKIUpdater, VaccinationGermanyUpdater, RValueGermanyUpdater, \
    VaccinationGermanyImpfdashboardUpdater
from covidbot.covid_data.updater import clean_district_name, ICUGermanyUpdater


class TestVaccinationGermanyUpdater(TestCase):
    conn: MySQLConnection

    @classmethod
    def setUpClass(cls) -> None:
        cfg = parse_config("resources/config.unittest.ini")
        cls.conn = get_connection(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_update(self):
        rki = RKIUpdater(self.conn)
        rki.update()
        updater = VaccinationGermanyUpdater(self.conn)
        updater.update()
        updater = RValueGermanyUpdater(self.conn)
        updater.update()
        updater = VaccinationGermanyImpfdashboardUpdater(self.conn)
        updater.update()
        updater = ICUGermanyUpdater(self.conn)
        updater.update()

    def test_clean_district_name(self):
        expected = [("Region Hannover", "Hannover"), ("LK Kassel", "Kassel"),
                    ("LK Dillingen a.d.Donau", "Dillingen a.d.Donau"),
                    ("LK Bad Tölz-Wolfratshausen", "Bad Tölz-Wolfratshausen"), ("Berlin", "Berlin")]
        for item in expected:
            self.assertEqual(item[1], clean_district_name(item[0]),
                             "Clean name of " + item[0] + " should be " + item[1])
