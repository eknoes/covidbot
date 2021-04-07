import logging
import os
import signal
import traceback
from typing import List, Union

import prometheus_async
import threema.gateway as threema
from aiohttp import web
from threema.gateway.e2e import create_application, add_callback_route, TextMessage, Message, ImageMessage

from covidbot.bot import Bot, UserHintService
from covidbot.messenger_interface import MessengerInterface
from covidbot.metrics import RECV_MESSAGE_COUNT, SENT_MESSAGE_COUNT, SENT_IMAGES_COUNT, BOT_RESPONSE_TIME
from covidbot.text_interface import SimpleTextInterface
from covidbot.utils import adapt_text, str_bytelen, BotResponse


class ThreemaInterface(SimpleTextInterface, MessengerInterface):
    threema_id: str
    secret: str
    private_key: str
    bot: Bot
    connection: threema.Connection
    dev_chat: str

    def __init__(self, threema_id: str, threema_secret: str, threema_key: str, bot: Bot, dev_chat: str):
        super().__init__(bot)
        self.threema_id = threema_id
        self.threema_secret = threema_secret
        self.threema_key = threema_key
        self.connection = threema.Connection(
            identity=self.threema_id,
            secret=self.threema_secret,
            key=self.threema_key
        )
        self.dev_chat = dev_chat

    def run(self):
        logging.info("Run Threema Interface")
        # Create the application and register the handler for incoming messages
        application = create_application(self.connection)
        add_callback_route(self.connection, application, self.handle_threema_msg, path='/gateway_callback')
        web.run_app(application, port=9000, access_log=logging.getLogger('threema_api'))

    @prometheus_async.aio.time(BOT_RESPONSE_TIME)
    async def handle_threema_msg(self, message: Message):
        if type(message) == TextMessage:
            RECV_MESSAGE_COUNT.inc()
            message: TextMessage
            try:
                responses = self.handle_input(message.text, message.from_id)
                for response in responses:
                    await self.send_bot_response(message.from_id, response)
            except Exception as e:
                self.log.exception("An error happened while handling a Threema message", exc_info=e)
                self.log.exception(f"Message from {message.from_id}: {message.text}")
                self.log.exception("Exiting!")

                try:
                    response_msg = TextMessage(self.connection, text=adapt_text(self.bot.get_error_message()[0], True),
                                               to_id=message.from_id)
                    await response_msg.send()
                except Exception:
                    self.log.error(f"Could not send message to {message.from_id}")

                try:
                    tb_list = traceback.format_exception(None, e, e.__traceback__)
                    tb_string = ''.join(tb_list)

                    await self.sendMessageToDev(f"An exception occurred: {tb_string}\n"
                                                f"Message from {message.from_id}: {message.text}")
                except Exception:
                    self.log.error(f"Could not send message to developers")

                # Just exit on exception
                os.kill(os.getpid(), signal.SIGINT)
        else:
            self.log.warning(f"Received unknown message type {type(message)}: {message}")

    async def send_bot_response(self, user: str, response: BotResponse):
        if response.images:
            for image in response.images:
                response_img = ImageMessage(self.connection, image_path=image, to_id=user)
                await response_img.send()
                SENT_IMAGES_COUNT.inc()

        if response.message:
            message_parts = self.split_messages(response.message)
            for m in message_parts:
                response_msg = TextMessage(self.connection, text=m, to_id=user)
                await response_msg.send()
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

    @staticmethod
    def split_messages(message: str) -> List[str]:
        # Max len of 3500 bytes
        current_part = ""
        message = adapt_text(message, True)
        split_message = []
        for part in message.split('\n'):
            if str_bytelen(part) + str_bytelen(current_part) + str_bytelen('\n') < 3500:
                current_part += part + '\n'
            else:
                current_part.strip('\n')
                split_message.append(current_part)
                current_part = part
        if current_part:
            split_message.append(current_part.strip('\n'))
        return split_message

    async def send_message_to_users(self, message: str, users: List[Union[str, int]], append_report=False):
        if not users:
            users = map(lambda x: x.platform_id, self.bot.get_all_user())

        message = UserHintService.format_commands(message, self.bot.format_command)

        for user in users:
            await TextMessage(self.connection, text=adapt_text(message, True), to_id=user).send()

            if append_report:
                report = self.reportHandler("", user)
                for elem in report:
                    await self.send_bot_response(user, elem)
            self.log.warning(f"Sent message to {user}")

    async def sendMessageToDev(self, message: str):
        await TextMessage(self.connection, text=adapt_text(message, True), to_id=self.dev_chat).send()
