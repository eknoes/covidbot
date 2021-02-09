import logging
from typing import List, Union

from telegram import ParseMode
from telegram.ext import Updater

from covidbot.messenger_interface import MessengerInterface
from covidbot.user_manager import UserManager


class FeedbackForwarder(MessengerInterface):
    log = logging.getLogger(__name__)

    def __init__(self, api_key: str, dev_chat_id: int, user_manager: UserManager):
        self.dev_chat_id = dev_chat_id
        self.user_manager = user_manager
        self.updater = Updater(api_key)

    async def sendDailyReports(self) -> None:
        # This method is not used for daily reports, but to forward feedback to the developers
        for feedback_id, message in self.user_manager.get_not_forwarded_feedback():
            sent = self.updater.bot.send_message(chat_id=self.dev_chat_id, text=message, parse_mode=ParseMode.HTML)
            if sent:
                self.user_manager.confirm_feedback_forwarded(feedback_id)
            else:
                self.log.error(f"Could not forward feedback {feedback_id}")

    async def sendMessageTo(self, message: str, users: List[Union[str, int]], append_report=False):
        raise NotImplementedError("This is just an interface to forward feedback from users to developers")

    def run(self) -> None:
        pass
