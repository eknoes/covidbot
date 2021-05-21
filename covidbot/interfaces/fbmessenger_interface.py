import asyncio
import logging
import os
import signal
import traceback
from typing import List, Union

import prometheus_async
from fbmessenger import Messenger
from fbmessenger.errors import MessengerError
from fbmessenger.models import Message, PostbackButton

from covidbot.interfaces.messenger_interface import MessengerInterface
from covidbot.metrics import RECV_MESSAGE_COUNT, SENT_MESSAGE_COUNT, BOT_RESPONSE_TIME
from covidbot.bot import Bot
from covidbot.settings import BotUserSettings
from covidbot.user_hint_service import UserHintService
from covidbot.utils import adapt_text, split_message
from covidbot.interfaces.bot_response import BotResponse


class FBMessengerInterface(MessengerInterface):
    bot: Bot
    fb_messenger: Messenger
    port: int
    log = logging.getLogger(__name__)

    def __init__(self, bot: Bot, access_token: str, verify_token: str, port: int, web_dir: str,
                 public_url: str):
        self.bot = bot
        self.fb_messenger = Messenger(access_token, verify_token, self.handle_messenger_msg, web_dir, public_url)
        self.port = port

    def run(self):
        logging.info("Run Facebook Messenger Interface")
        # Set Get Started and Greeting Text
        asyncio.ensure_future(
            self.fb_messenger.set_greeting_text('Hallo {{user_first_name}}, zu Deinen Diensten: Ich versorge Dich '
                                                'mit den aktuellen Infektions-, Todes- und Impfzahlen '
                                                'der von Dir ausgewählten Orte aus offiziellen Quellen.'))
        asyncio.ensure_future(self.fb_messenger.set_get_started_payload('/start'))
        self.fb_messenger.start_receiving(port=self.port)

    @prometheus_async.aio.time(BOT_RESPONSE_TIME)
    async def handle_messenger_msg(self, message: Message):
        RECV_MESSAGE_COUNT.inc()
        try:
            user_input = message.text
            if message.payload:
                user_input = message.payload
            responses = self.bot.handle_input(user_input, message.sender_id)
            for response in responses:
                await self.send_bot_response(message.sender_id, response)
        except Exception as e:
            self.log.exception("An error happened while handling a FB Messenger message", exc_info=e)
            self.log.exception(f"Message from {message.sender_id}: {message.text}")
            self.log.exception("Exiting!")
            await self.fb_messenger.send_reply(message, adapt_text(self.bot.get_error_message().message))

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
            images = response.images
            disable_unicode = not self.bot.get_user_setting(user, BotUserSettings.FORMATTING)
            max_chars = 2000
            if response.choices:
                max_chars = 640
            messages = split_message(adapt_text(str(response), just_strip=disable_unicode), max_chars=max_chars)
            for i in range(0, len(messages)):
                buttons = None
                if response.choices and i == len(messages) - 1:
                    buttons = []
                    if len(response.choices) > 3:
                        response.choices = response.choices[:3]
                    for choice in response.choices:
                        buttons.append(PostbackButton(choice.label, choice.callback_data))
                await self.fb_messenger.send_message(user, messages[i], images=images, buttons=buttons)
                images = None
                SENT_MESSAGE_COUNT.inc()

    async def send_unconfirmed_reports(self) -> None:
        unconfirmed_reports = self.bot.get_available_user_messages()

        for report, userid, message in unconfirmed_reports:
            try:
                for elem in message:
                    await self.send_bot_response(userid, elem)
                self.bot.confirm_message_send(report, userid)
                self.log.warning(f"Sent report to {userid}")
            except MessengerError as e:
                self.log.exception(f"Can't send report: {e.code} {e.subcode} {e.message}", exc_info=e)
                self.bot.disable_user(userid)

    async def send_message_to_users(self, message: str, users: List[Union[str, int]]):
        if not users:
            users = map(lambda x: x.platform_id, self.bot.get_all_users())

        message = UserHintService.format_commands(message, self.bot.command_formatter)

        for user in users:
            disable_unicode = not self.bot.get_user_setting(user, BotUserSettings.FORMATTING)
            await self.fb_messenger.send_message(user, adapt_text(message, just_strip=disable_unicode))
            self.log.warning(f"Sent message to {user}")

    async def sendMessageToDev(self, message: str):
        self.log.error(f"Not yet implemented, send following to dev: {message}")
