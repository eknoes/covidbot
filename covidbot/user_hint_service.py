import csv
import datetime
import os
import re
from typing import Callable, Optional


class UserHintService:
    FILE = "resources/user-tips.csv"
    current_hint: Optional[str] = None
    current_date: datetime.date = datetime.date.today()
    command_fmt: Callable[[str], str]
    command_regex = re.compile("{([\w\s]*)}")

    def __init__(self, command_formatter: Callable[[str], str]):
        self.command_fmt = command_formatter

    def get_hint_of_today(self) -> str:
        if self.current_hint and self.current_date == datetime.date.today():
            return self.current_hint

        if os.path.isfile(self.FILE):
            with open(self.FILE, "r") as f:
                reader = csv.DictReader(f, delimiter=";")
                today = datetime.date.today()
                for row in reader:
                    if row['date'] == today.isoformat():
                        self.current_hint = self.format_commands(row['message'], self.command_fmt)
                        self.current_date = today
                        return self.current_hint

    @staticmethod
    def format_commands(message: str, formatter: Callable[[str], str]) -> str:
        return UserHintService.command_regex.sub(lambda x: formatter(x.group(1)), message)
