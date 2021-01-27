import logging

import threema.gateway as threema
from aiohttp import web
from threema.gateway.e2e import create_application, add_callback_route

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

    def run(self):
        logging.info("Run Threema Interface")
        # Create the application and register the handler for incoming messages
        application = create_application(self.connection)
        add_callback_route(self.connection, application, self.handle_threema_msg, path='/gateway_callback')
        web.run_app(application, port=9000)

    async def handle_threema_msg(self, message: str):
        print('Got message ({}): {}'.format(repr(message), message))