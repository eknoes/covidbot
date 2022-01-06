import datetime
import json
from typing import Optional

import requests


class WorkingDayChecker:

    def __init__(self):
        self.holidays = dict()

    def _data(self, year):
        if not year in self.holidays:
            header = {
                "User-Agent": "CovidBot (https://github.com/eknoes/covid-bot | https://covidbot.d-64.org)"}
            response = requests.get(
                f'https://feiertage-api.de/api/?jahr={year}',
                headers=header)

            if not response or response.status_code < 200 or response.status_code >= 300:
                raise ConnectionError(f"Can't connect to feiertage-api.de: {response}")
            self.holidays[year] = json.loads(response.text)

        return self.holidays[year]

    def is_valid_state(self, state: str) -> bool:
        return state.upper() in self._data(datetime.date.today().year)

    def check_holiday(self, for_day: datetime.date, state: Optional[str] = "NATIONAL") -> bool:
        if not state or state == "BUND":
            state = "NATIONAL"
        state = state.upper()

        if not self.is_valid_state(state):
            raise ValueError(f"{state} not a valid name to check for holidays")

        if for_day.weekday() == 6:
            return True

        for_day_iso = for_day.isoformat()
        for _, info in self._data(for_day.year)[state].items():
            if for_day_iso == info['datum']:
                return True

        return False

