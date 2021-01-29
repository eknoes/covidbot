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
                response_msg = TextMessage(self.connection, text=self.adapt_text(response.message),
                                           to_id=message.from_id)
                await response_msg.send()

    def adapt_text(self, text: str) -> str:
        # Replace bold with Unicode bold
        bold_pattern = re.compile("<b>(.*?)</b>")
        matches = bold_pattern.finditer(text)
        if matches:
            for match in matches:
                text = text.replace(match.group(0), self.replace_bold(match.group(1)))

        bold_pattern = re.compile("<i>(.*?)</i>")
        matches = bold_pattern.finditer(text)
        if matches:
            for match in matches:
                text = text.replace(match.group(0), self.replace_italic(match.group(1)))

        # Strip non bold or italic
        pattern = re.compile("<[^<]+?>")
        return pattern.sub("", text)

    def replace_bold(self, text: str) -> str:
        bold_str = [
            *"𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵𝗮̈𝘂̈𝗼̈𝗔̈𝗨̈𝗢̈ß"]
        normal_str = [*(string.ascii_letters + string.digits + "äüöÄÜÖß")]

        replace_list = list(zip(normal_str, bold_str))

        for i in range(len(replace_list)):
            text = text.replace(replace_list[i][0], replace_list[i][1])
        return text

    def replace_italic(self, text: str) -> str:
        italic_str = [
            *"𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡0123456789𝘢̈𝘶̈𝘰̈𝘈̈𝘜̈𝘖̈ß"]
        normal_str = [*(string.ascii_letters + string.digits + "äüöÄÜÖß")]

        replace_list = list(zip(normal_str, italic_str))

        for i in range(len(replace_list)):
            text = text.replace(replace_list[i][0], replace_list[i][1])
        return text

    def sendDailyReports(self) -> None:
        # TODO: Implement daily reports
        pass

