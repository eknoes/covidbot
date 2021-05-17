import datetime
from unittest import TestCase

from covidbot.covid_data.WorkingDayChecker import WorkingDayChecker


class TestWorkingDayChecker(TestCase):
    def test_check_holiday(self):
        checker = WorkingDayChecker()

        # Holidays
        self.assertTrue(checker.check_holiday(datetime.date(year=2021, month=12, day=25)))
        self.assertTrue(checker.check_holiday(datetime.date(year=2021, month=1, day=1)))

        self.assertTrue(checker.check_holiday(datetime.date(year=2021, month=5, day=16)), "Sundays are not working "
                                                                                          "days!")
        self.assertFalse(checker.check_holiday(datetime.date(year=2021, month=5, day=15)), "Saturdays are working "
                                                                                           "days!")
