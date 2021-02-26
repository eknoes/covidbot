import logging
import os
import signal
import traceback
from io import BytesIO
from typing import Dict, List, Union

import threema.gateway as threema
from aiohttp import web
from threema.gateway.e2e import create_application, add_callback_route, TextMessage, Message, ImageMessage

from covidbot.bot import Bot
from covidbot.messenger_interface import MessengerInterface
from covidbot.text_interface import SimpleTextInterface, BotResponse
from covidbot.utils import adapt_text, str_bytelen


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
        self.graphics_tmp_path = os.path.abspath("tmp-threema/")
        if not os.path.isdir(self.graphics_tmp_path):
            os.makedirs(self.graphics_tmp_path)

    def run(self):
        logging.info("Run Threema Interface")
        # Create the application and register the handler for incoming messages
        application = create_application(self.connection)
        add_callback_route(self.connection, application, self.handle_threema_msg, path='/gateway_callback')
        web.run_app(application, port=9000, access_log=logging.getLogger('threema_api'))

    def get_attachment(self, image: BytesIO, district_id=99) -> Dict:
        filename = self.graphics_tmp_path + f"/graphic{district_id}.jpg"
        with open(filename, "wb") as f:
            image.seek(0)
            f.write(image.getbuffer())
        return {"filename": filename, "width": "900", "height": "600"}

    async def handle_threema_msg(self, message: Message):
        if type(message) == TextMessage:
            message: TextMessage
            try:
                response = self.handle_input(message.text, message.from_id)
                await self.send_bot_response(message.from_id, response)
            except Exception as e:
                self.log.exception("An error happened while handling a Threema message", exc_info=e)
                self.log.exception(f"Message from {message.from_id}: {message.text}")
                self.log.exception("Exiting!")

                try:
                    response_msg = TextMessage(self.connection, text=adapt_text(self.bot.get_error_message(), True),
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
            self.log.debug(f"Received unknown message type {type(message)}: {message}")

    async def send_bot_response(self, user: str, response: BotResponse):
        if response.image:
            response_img = ImageMessage(self.connection, image_path=self.get_attachment(response.image)['filename'],
                                        to_id=user)
            await response_img.send()

        if response.message:
            message_parts = self.split_messages(response.message)
            for m in message_parts:
                response_msg = TextMessage(self.connection, text=m, to_id=user)
                await response_msg.send()

    async def sendDailyReports(self) -> None:
        unconfirmed_reports = self.bot.get_unconfirmed_daily_reports()
        if not unconfirmed_reports:
            return
        daily_graph = self.bot.get_graphical_report(0)
        attachment = self.get_attachment(daily_graph, 0)
        for userid, message in unconfirmed_reports:
            if attachment:
                response_img = ImageMessage(self.connection, image_path=attachment['filename'],
                                            to_id=userid)
                await response_img.send()

            message_parts = self.split_messages(message)
            for m in message_parts:
                report = TextMessage(self.connection, text=m, to_id=userid)
                await report.send()
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
                current_part = ""
        if current_part:
            split_message.append(current_part.strip('\n'))
        return split_message

    async def sendMessageTo(self, message: str, users: List[Union[str, int]], append_report=False):
        if not users:
            users = map(lambda x: x.platform_id, self.bot.get_all_user())

        for user in users:
            await TextMessage(self.connection, text=adapt_text(message, True), to_id=user).send()

            if append_report:
                report = self.reportHandler("", user)
                await self.send_bot_response(user, report)
            self.log.warning(f"Sent message to {user}")

    async def sendMessageToDev(self, message: str):
        await TextMessage(self.connection, text=adapt_text(message, True), to_id=self.dev_chat).send()
