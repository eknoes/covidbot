import logging
import os
import signal
import traceback
from typing import List, Union

import prometheus_async
import threema.gateway as threema
from aiohttp import web
from threema.gateway.e2e import create_application, add_callback_route, TextMessage, Message, ImageMessage, \
    DeliveryReceipt

from covidbot.interfaces.messenger_interface import MessengerInterface
from covidbot.metrics import RECV_MESSAGE_COUNT, SENT_MESSAGE_COUNT, SENT_IMAGES_COUNT, BOT_RESPONSE_TIME
from covidbot.bot import Bot
from covidbot.user_hint_service import UserHintService
from covidbot.utils import adapt_text, split_message
from covidbot.interfaces.bot_response import BotResponse


class ThreemaInterface(MessengerInterface):
    threema_id: str
    secret: str
    private_key: str
    bot: Bot
    connection: threema.Connection
    dev_chat: str
    log = logging.getLogger(__name__)

    def __init__(self, threema_id: str, threema_secret: str, threema_key: str, bot: Bot, dev_chat: str):
        self.bot = bot
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
                responses = self.bot.handle_input(message.text, message.from_id)
                for response in responses:
                    await self.send_bot_response(message.from_id, response)
            except Exception as e:
                self.log.exception("An error happened while handling a Threema message", exc_info=e)
                self.log.exception(f"Message from {message.from_id}: {message.text}")
                self.log.exception("Exiting!")

                try:
                    response_msg = TextMessage(self.connection,
                                               text=adapt_text(self.bot.get_error_message().message, True),
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
        elif type(message) == DeliveryReceipt:
            pass
        else:
            self.log.warning(f"Received unknown message type {type(message)}: {message}")

    async def send_bot_response(self, user: str, response: BotResponse):
        if response.images:
            for image in response.images:
                response_img = ImageMessage(self.connection, image_path=image, to_id=user)
                await response_img.send()
                SENT_IMAGES_COUNT.inc()

        if response.message:
            message_parts = split_message(adapt_text(str(response), threema_format=True), max_bytes=3500)
            for m in message_parts:
                response_msg = TextMessage(self.connection, text=m, to_id=user)
                await response_msg.send()
                SENT_MESSAGE_COUNT.inc()

    async def send_unconfirmed_reports(self) -> None:
        if not self.bot.user_messages_available():
            await self.connection.close()
            return

        for report_type, userid, message in self.bot.get_available_user_messages():
            try:
                for elem in message:
                    await self.send_bot_response(userid, elem)
                self.log.warning(f"Sent report to {userid}")
                self.bot.confirm_message_send(report_type, userid)
            except threema.KeyServerError as error:
                self.log.error(f"Got KeyServer Error {error.status}: {error.status_description[error.status]} ",
                               exc_info=error)
                if error.status == 404:
                    self.bot.delete_user(userid)
        await self.connection.close()

    async def send_message_to_users(self, message: str, users: List[Union[str, int]]):
        if not users:
            users = map(lambda x: x.platform_id, self.bot.get_all_users())

        message = UserHintService.format_commands(message, self.bot.command_formatter)

        for user in users:
            await TextMessage(self.connection, text=adapt_text(message, True), to_id=user).send()
            self.log.warning(f"Sent message to {user}")

    async def sendMessageToDev(self, message: str):
        await TextMessage(self.connection, text=adapt_text(message, True), to_id=self.dev_chat).send()
