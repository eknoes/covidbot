import asyncio
import os
import random
import re
import signal
import time
import traceback
from io import BytesIO
from typing import Dict, List

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
    profile_name: str = "Covid Update"
    profile_picture: str = os.path.abspath("resources/logo.png")
    dev_chat: str = None

    def __init__(self, phone_number: str, socket: str, bot: Bot, dev_chat: str):
        super().__init__(bot)
        self.phone_number = phone_number
        self.socket = socket
        self.dev_chat = dev_chat

        self.graphics_tmp_path = os.path.abspath("tmp/")
        if not os.path.isdir(self.graphics_tmp_path):
            os.makedirs(self.graphics_tmp_path)

    def run(self):
        asyncio.run(self._run())

    async def _run(self):
        async with semaphore.Bot(self.phone_number, socket_path=self.socket, profile_name=self.profile_name,
                                 profile_picture=self.profile_picture) as bot:
            bot.register_handler(re.compile(""), self.text_handler)
            bot.set_exception_handler(self.exception_handler)
            await bot.start()

    async def exception_handler(self, exception: Exception, ctx: ChatContext):
        self.log.exception("An exception occurred, exiting...", exc_info=exception)
        tb_list = traceback.format_exception(None, exception, exception.__traceback__)
        tb_string = ''.join(tb_list)

        await self.sendMessageToDev(f"Exception occurred: {tb_string}\n\n"
                                    f"Got message {ctx.message}", ctx.bot)
        # Just exit on exception
        os.kill(os.getpid(), signal.SIGINT)

    async def text_handler(self, ctx: ChatContext):
        text = ctx.message.get_body()
        if text:
            await ctx.message.typing_started()
            if text.find('https://maps.google.com/maps?q='):
                # This is a location
                text = re.sub('\nhttps://maps.google.com/maps\?q=.*', '', text)
                # Strip URL so it is searched for the contained address
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

    def get_attachment(self, image: BytesIO, district_id=99) -> Dict:
        filename = self.graphics_tmp_path + f"/graphic{district_id}.jpg"
        with open(filename, "wb") as f:
            image.seek(0)
            f.write(image.getbuffer())
        return {"filename": filename, "width": "900", "height": "600"}

    async def sendDailyReports(self) -> None:
        unconfirmed_reports = self.bot.get_unconfirmed_daily_reports()
        if not unconfirmed_reports:
            return
        self.log.warning(f"{len(unconfirmed_reports)} to send!")
        attachment = self.get_attachment(self.bot.get_graphical_report(0), 0)

        # Flooding - just send 20 in a batch
        unconfirmed_reports = unconfirmed_reports[:20]
        self.log.warning(f"Just send {len(unconfirmed_reports)} this batch")
        async with semaphore.Bot(self.phone_number, socket_path=self.socket, profile_name=self.profile_name,
                                 profile_picture=self.profile_picture) as bot:
            flood_count = 0
            for userid, message in unconfirmed_reports:
                self.log.info(f"Try to send report {flood_count}")

                #  We do not receive a confirmation, if report was successful
                #  See https://github.com/lwesterhof/semaphore/issues/28
                await bot.send_message(userid, adapt_text(message), attachments=[attachment])
                self.bot.confirm_daily_report_send(userid)
                self.log.warning(f"({flood_count}/{len(unconfirmed_reports)}) Sent daily report to {userid}")

                #  TODO: Find out more about Signals Flood limits -> this is very conservative, but also very slow
                #  See #84 https://github.com/eknoes/covid-bot/issues/84
                #  See #67 https://github.com/eknoes/covid-bot/issues/67
                sleep_seconds = random.uniform(1, 3)
                self.log.info(f"Sleeping {sleep_seconds}s to avoid server limitations")
                time.sleep(sleep_seconds)
                flood_count += 1

            # Currently semaphore is not waiting for signald's response, whether a message was successful.
            # Closing the socket immediately after sending leads to an exception on signald, as it sends a SendResponse
            # but the socket is already closed
            self.log.warning("Sleep 15s to avoid signald damage")
            time.sleep(15)
        await self.restart_service()

    async def restart_service(self):
        self.log.warning("Try to restart signald and signalbot")
        cmd = "supervisorctl restart signald signalbot"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL)

        await proc.wait()
        if proc.returncode:
            print(f'{cmd} exited with {proc.returncode}')
            self.log.error(f'{cmd!r} exited with {proc.returncode}')
            return
        self.log.warning("Restarted signalbot service")

    async def sendMessageTo(self, message: str, users: List[str], append_report=False):
        if not users:
            users = map(lambda x: x.platform_id, self.bot.get_all_user())

        async with semaphore.Bot(self.phone_number, socket_path=self.socket, profile_name=self.profile_name,
                                 profile_picture=self.profile_picture) as bot:
            flood_count = 0
            for user in users:
                # TODO: Find out more about Signals Flood limits -> this is very conservative, but also very slow
                if flood_count % 1 == 0:
                    sleep_seconds = random.uniform(0.3, 2)
                    self.log.info(f"Sleeping {sleep_seconds}s to avoid server limitations")
                    time.sleep(sleep_seconds)
                    flood_count += 1

                self.log.info(f"Try to send message to user {user}")
                await bot.send_message(user, adapt_text(message))
                if append_report:
                    response = self.reportHandler("", user)
                    attachments = []
                    if response.image:
                        attachments.append(self.get_attachment(response.image))
                    await bot.send_message(user, adapt_text(response.message), attachments)
                self.log.warning(f"Sent message to {user}")

            # Currently semaphore is not waiting for signald's response, whether a message was successful.
            # Closing the socket immediately after sending leads to an exception on signald, as it sends a SendResponse
            # but the socket is already closed
            time.sleep(10)
        await self.restart_service()

    async def sendMessageToDev(self, message: str, bot: semaphore.Bot):
        await bot.send_message(self.dev_chat, adapt_text(message))
