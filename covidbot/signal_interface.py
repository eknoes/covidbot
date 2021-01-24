import re

import semaphore
from semaphore import ChatContext

from covidbot.bot import Bot
from covidbot.text_interface import SimpleTextInterface


class SignalInterface(SimpleTextInterface):
    phone_number: str

    def __init__(self, phone_number: str, bot: Bot):
        super().__init__(bot)
        self.phone_number = phone_number
    
    async def run(self):
        async with semaphore.Bot(self.phone_number) as bot:
            bot.register_handler(re.compile(""), self.text_handler)
            await bot.start()
        
    def text_handler(self, ctx: ChatContext):
        pass