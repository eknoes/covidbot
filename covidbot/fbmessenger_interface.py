import logging
import os
import signal
import traceback
from typing import List, Union

import prometheus_async
from fbmessenger import Messenger
from fbmessenger.models import Message

from covidbot.bot import Bot, UserHintService
from covidbot.messenger_interface import MessengerInterface
from covidbot.metrics import RECV_MESSAGE_COUNT, SENT_MESSAGE_COUNT, BOT_RESPONSE_TIME
from covidbot.text_interface import SimpleTextInterface
from covidbot.utils import adapt_text, BotResponse


class FBMessengerInterface(SimpleTextInterface, MessengerInterface):
    bot: Bot
    fb_messenger: Messenger
    port: int

    def __init__(self, bot: Bot, access_token: str, verify_token: str, port: int, web_dir: str, public_url: str):
        super().__init__(bot)
        self.fb_messenger = Messenger(access_token, verify_token, self.handle_messenger_msg, web_dir, public_url)
        self.port = port

    def run(self):
        logging.info("Run Facebook Messenger Interface")
        self.fb_messenger.start_receiving(port=self.port)

    @prometheus_async.aio.time(BOT_RESPONSE_TIME)
    async def handle_messenger_msg(self, message: Message):
        RECV_MESSAGE_COUNT.inc()
        try:
            responses = self.handle_input(message.text, message.sender_id)
            for response in responses:
                await self.send_bot_response(message.sender_id, response)
        except Exception as e:
            self.log.exception("An error happened while handling a FB Messenger message", exc_info=e)
            self.log.exception(f"Message from {message.sender_id}: {message.text}")
            self.log.exception("Exiting!")
            await self.fb_messenger.reply(message, adapt_text(self.bot.get_error_message()[0], threema_format=True))

            try:
                tb_list = traceback.format_exception(None, e, e.__traceback__)
                tb_string = ''.join(tb_list)

                await self.sendMessageToDev(f"An exception occurred: {tb_string}\n"
                                            f"Message from {message.sender_id}: {message.text}")
            except Exception:
                self.log.error(f"Could not send message to developers")

            # Just exit on exception
            os.kill(os.getpid(), signal.SIGINT)

    async def send_bot_response(self, user: str, response: BotResponse):
        if response.message:
            image = None
            if response.images:
                for image in response.images[:-1]:
                    await self.fb_messenger.send_message(user, "", image)
                image = response.images[-1]

            await self.fb_messenger.send_message(user, response.message, image)
            SENT_MESSAGE_COUNT.inc()

    async def send_unconfirmed_reports(self) -> None:
        unconfirmed_reports = self.bot.get_unconfirmed_daily_reports()
        if not unconfirmed_reports:
            return
        for userid, message in unconfirmed_reports:
            for elem in message:
                await self.send_bot_response(userid, elem)
            self.bot.confirm_daily_report_send(userid)
            self.log.warning(f"Sent report to {userid}")

    async def send_message_to_users(self, message: str, users: List[Union[str, int]], append_report=False):
        if not users:
            users = map(lambda x: x.platform_id, self.bot.get_all_user())

        message = UserHintService.format_commands(message, self.bot.format_command)

        for user in users:
            await self.fb_messenger.send_message(user, adapt_text(message, threema_format=True))

            if append_report:
                report = self.reportHandler("", user)
                for elem in report:
                    await self.send_bot_response(user, elem)
            self.log.warning(f"Sent message to {user}")

    async def sendMessageToDev(self, message: str):
        self.log.error(f"Not yet implemented, send following to dev: {message}")
