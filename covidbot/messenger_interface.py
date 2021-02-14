from abc import ABC, abstractmethod
from typing import Union, List


class MessengerInterface(ABC):
    """Interface to implement the bot on a certain platform"""

    @abstractmethod
    async def sendDailyReports(self) -> None:
        """Checks :py:meth:`covidbot.Bot.get_unconfirmed_daily_reports` for new reports and sends them to the users of
        the implemented platform.
        """
        pass

    @abstractmethod
    async def sendMessageTo(self, message: str, users: List[Union[str, int]], append_report=False):
        """Sends a message to a set of users

        Args:
            message: Message to sent, may contain HTML
            users: List of platform_id, if empty send to all users
            append_report: Flag if the current report of a certain user should be appended
        """
        pass

    @abstractmethod
    def run(self):
        """Runs the Bot on the implemented platform

        """
        pass
