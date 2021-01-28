import logging
import os
from io import BytesIO
from typing import Dict

import threema.gateway as threema
from aiohttp import web
from threema.gateway.e2e import create_application, add_callback_route, TextMessage, Message, ImageMessage

from covidbot.bot import Bot
from covidbot.text_interface import SimpleTextInterface


class ThreemaInterface(SimpleTextInterface):
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
                response_img = ImageMessage(self.connection, image=self.get_attachment(response.image)['filename'])
                await response_img.send()

            response_msg = TextMessage(self.connection, text=response.message, to_id=message.from_id)
            await response_msg.send()