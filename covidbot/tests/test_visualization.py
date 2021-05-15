from unittest import TestCase

from covidbot.covid_data import Visualization


class TestVisualization(TestCase):
    def test_tick_formatter_german_numbers(self):
        self.assertEqual("1,1 Mio.", Visualization.tick_formatter_german_numbers(1100000, 0))
        self.assertEqual("900.000", Visualization.tick_formatter_german_numbers(900000, 0))
