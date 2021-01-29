import asyncio
import os
import re
from io import BytesIO
from typing import Dict

import semaphore
from semaphore import ChatContext

from covidbot.bot import Bot
from covidbot.messenger_interface import MessengerInterface
from covidbot.text_interface import SimpleTextInterface, BotResponse
from covidbot.utils import adapt_text


class SignalInterface(SimpleTextInterface, MessengerInterface):
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

    def run(self):
        asyncio.run(self._run())

    async def _run(self):
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
        reply.message = adapt_text(reply.message)

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

    def sendDailyReports(self) -> None:
        unconfirmed_reports = self.bot.get_unconfirmed_daily_reports()
        asyncio.run(self.sendDailyReportsAsync(unconfirmed_reports, self.bot.get_graphical_report(0)))

    async def sendDailyReportsAsync(self, unconfirmed_reports, graph) -> None:
        attachment = self.get_attachment(graph)
        async with semaphore.Bot(self.phone_number, socket_path=self.socket) as bot:
            for userid, message in unconfirmed_reports:
                await bot.send_message(userid, message, attachments=[attachment])
                self.bot.confirm_daily_report_send(userid)
                self.log.info(f"Sent daily report to {userid}")

