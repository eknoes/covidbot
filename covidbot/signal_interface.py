import os
import re
import string
from io import BytesIO
from typing import Dict

import semaphore
from semaphore import ChatContext

from covidbot.bot import Bot
from covidbot.text_interface import SimpleTextInterface, BotResponse


class SignalInterface(SimpleTextInterface):
    phone_number: str
    socket: str
    graphics_tmp_path: str

    def __init__(self, phone_number: str, socket: str, bot: Bot):
        super().__init__(bot)
        self.phone_number = phone_number
        self.socket = socket

        self.graphics_tmp_path = os.path.abspath("tmp/")
        if not os.path.isdir(self.graphics_tmp_path):
            os.makedirs(self.graphics_tmp_path)

    async def run(self):
        async with semaphore.Bot(self.phone_number, socket_path=self.socket) as bot:
            bot.register_handler(re.compile(""), self.text_handler)
            await bot.start()

    async def text_handler(self, ctx: ChatContext):
        text = ctx.message.get_body()
        if text:
            await ctx.message.typing_started()
            reply = self.handle_input(text, ctx.message.source)
            if reply:
                await self.reply_message(ctx, reply)
            await ctx.message.typing_stopped()

    async def reply_message(self, ctx: ChatContext, reply: BotResponse):
        reply.message = self.adapt_text(reply.message)

        attachment = []
        if reply.image:
            attachment.append(self.get_attachment(reply.image))

        await ctx.message.reply(body=reply.message, attachments=attachment)

    def get_attachment(self, image: BytesIO) -> Dict:
        filename = self.graphics_tmp_path + "/graphic.jpg"
        with open(filename, "wb") as f:
            image.seek(0)
            f.write(image.getbuffer())
        return {"filename": filename, "width": "900", "height": "600"}

    # TODO: Implement daily updates
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
