from abc import ABC, abstractmethod


class MessengerInterface(ABC):

    @abstractmethod
    async def sendDailyReports(self) -> None:
        pass

    @abstractmethod
    def run(self) -> None:
        pass