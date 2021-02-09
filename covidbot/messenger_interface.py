from abc import ABC, abstractmethod
from typing import Union, List


class MessengerInterface(ABC):

    @abstractmethod
    async def sendDailyReports(self) -> None:
        pass

    @abstractmethod
    async def sendMessageTo(self, message: str, users: List[Union[str, int]], append_report=False):
        pass

    @abstractmethod
    def run(self) -> None:
        pass
