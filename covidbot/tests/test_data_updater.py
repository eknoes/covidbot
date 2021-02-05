from unittest import TestCase

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import VaccinationGermanyUpdater


class TestVaccinationGermanyUpdater(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cfg = parse_config("resources/config.unittest.ini")
        cls.conn = get_connection(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_update(self):
        updater = VaccinationGermanyUpdater(self.conn)
        updater.update()
