import re

import semaphore
from semaphore import ChatContext

from covidbot.bot import Bot
from covidbot.text_interface import SimpleTextInterface


class SignalInterface(SimpleTextInterface):
    phone_number: str
    socket: str

    def __init__(self, phone_number: str, socket: str, bot: Bot):
        super().__init__(bot)
        self.phone_number = phone_number
        self.socket = socket
    
    async def run(self):
        async with semaphore.Bot(self.phone_number, socket_path=self.socket) as bot:
            bot.register_handler(re.compile(""), self.text_handler)
            await bot.start()
        
    async def text_handler(self, ctx: ChatContext):
        text = ctx.message.get_body()
        if text:
            reply = self.handle_input(text, ctx.message.username)
            await ctx.message.reply(self.strip_html(reply))

    def strip_html(self, text: str) -> str:
        pattern = re.compile("<[^<]+?>")
        return pattern.sub("", text)