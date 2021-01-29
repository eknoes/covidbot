import asyncio
import logging
import os
import re
import string
from io import BytesIO
from typing import Dict, List

import threema.gateway as threema
from aiohttp import web
from threema.gateway.e2e import create_application, add_callback_route, TextMessage, Message, ImageMessage

from covidbot.bot import Bot
from covidbot.messenger_interface import MessengerInterface
from covidbot.text_interface import SimpleTextInterface
from covidbot.utils import adapt_text


class ThreemaInterface(SimpleTextInterface, MessengerInterface):
    threema_id: str
    secret: str
    private_key: str
    bot: Bot
    connection: threema.Connection

    def __init__(self, threema_id: str, threema_secret: str, threema_key: str, bot: Bot):
        super().__init__(bot)
        self.threema_id = threema_id
        self.threema_secret = threema_secret
        self.threema_key = threema_key
        self.connection = threema.Connection(
            identity=self.threema_id,
            secret=self.threema_secret,
            key=self.threema_key
        )
        self.graphics_tmp_path = os.path.abspath("tmp-threema/")
        if not os.path.isdir(self.graphics_tmp_path):
            os.makedirs(self.graphics_tmp_path)

    def run(self):
        logging.info("Run Threema Interface")
        # Create the application and register the handler for incoming messages
        application = create_application(self.connection)
        add_callback_route(self.connection, application, self.handle_threema_msg, path='/gateway_callback')
        web.run_app(application, port=9000)

    def get_attachment(self, image: BytesIO) -> Dict:
        filename = self.graphics_tmp_path + "/graphic.jpg"
        with open(filename, "wb") as f:
            image.seek(0)
            f.write(image.getbuffer())
        return {"filename": filename, "width": "900", "height": "600"}

    async def handle_threema_msg(self, message: Message):
        if type(message) == TextMessage:
            message: TextMessage
            response = self.handle_input(message.text, message.from_id)
            if response.image:
                response_img = ImageMessage(self.connection, image_path=self.get_attachment(response.image)['filename'],
                                            to_id=message.from_id)
                await response_img.send()

            if response.message:
                response_msg = TextMessage(self.connection, text=adapt_text(response.message),
                                           to_id=message.from_id)
                await response_msg.send()

    def sendDailyReports(self) -> None:
        unconfirmed_reports = self.bot.get_unconfirmed_daily_reports()

        for userid, message in unconfirmed_reports:
            report = TextMessage(self.connection, text=adapt_text(message), to_id=userid)
            asyncio.get_event_loop().run_until_complete(report.send())
            self.bot.confirm_daily_report_send(userid)
            self.log.info(f"Sent report to {userid}")