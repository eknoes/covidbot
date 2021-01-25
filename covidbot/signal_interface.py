import os
import re

import semaphore
from semaphore import ChatContext

from covidbot.bot import Bot
from covidbot.text_interface import SimpleTextInterface, BotRespone


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
            reply = self.handle_input(text, ctx.message.username)
            await self.reply_message(ctx, reply)
            await ctx.message.typing_stopped()

    async def reply_message(self, ctx: ChatContext, reply: BotRespone):
        reply.message = self.strip_html(reply.message)

        attachment = []
        if reply.image:
            filename = self.graphics_tmp_path + "/graphic.jpg"
            with open(filename, "wb") as f:
                f.write(reply.image.getbuffer())
            attachment.append({"filename": filename, "width": "900", "height": "600"})

        await ctx.message.reply(body=reply.message, attachments=attachment)

    def strip_html(self, text: str) -> str:
        pattern = re.compile("<[^<]+?>")
        return pattern.sub("", text)