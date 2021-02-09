from unittest import TestCase

from mysql.connector import MySQLConnection

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import VaccinationGermanyUpdater, RKIUpdater, RValueGermanyUpdater, \
    VaccinationGermanyImpfdashboardUpdater


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
