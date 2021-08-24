import datetime
import json
from typing import Optional

import requests


class WorkingDayChecker:

    def __init__(self):
        header = {"User-Agent": "CovidBot (https://github.com/eknoes/covid-bot | https://covidbot.d-64.org)"}
        response = requests.get(f'https://feiertage-api.de/api/?jahr={datetime.date.today().year}', headers=header)

        if not response or response.status_code < 200 or response.status_code >= 300:
            raise ConnectionError(f"Can't connect to feiertage-api.de: {response}")

        self.holidays = json.loads(response.text)

    def is_valid_state(self, state: str) -> bool:
        return state.upper() in self.holidays

    def check_holiday(self, for_day: datetime.date, state: Optional[str] = "NATIONAL") -> bool:
        if not state or state == "BUND":
            state = "NATIONAL"
        state = state.upper()

        if state not in self.holidays:
            raise ValueError(f"{state} not a valid name to check for holidays")

        if for_day.weekday() == 6:
            return True

        for_day = for_day.isoformat()
        for _, info in self.holidays[state].items():
            if for_day == info['datum']:
                return True

        return False

