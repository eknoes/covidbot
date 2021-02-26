import asyncio
import os
import random
import re
import signal
import time
import traceback
from io import BytesIO
from math import ceil
from typing import Dict, List, Optional

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
    profile_name: Optional[str] = None  # = "Covid Update"
    profile_picture: Optional[str] = None  # = os.path.abspath("resources/logo.png")
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
            platform_id = ctx.message.source
            # Currently, we disable user that produce errors on sending the daily report
            # If they would query our bot, we'd like to have them activated before we process their query
            # This is a hacky workaround for https://github.com/eknoes/covidbot/issues/103
            if not self.bot.is_user_activated(platform_id):
                self.bot.enable_user(platform_id)
            reply = self.handle_input(text, platform_id)
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

        # This way, if we are blocked from a single user or such, we should reach all other users
        random.shuffle(unconfirmed_reports)

        async with semaphore.Bot(self.phone_number, socket_path=self.socket, profile_name=self.profile_name,
                                 profile_picture=self.profile_picture) as bot:
            backoff_time = random.uniform(0.5, 2)
            message_counter = 0
            for userid, message in unconfirmed_reports:
                self.log.info(f"Try to send report {message_counter}")

                success = await bot.send_message(userid, adapt_text(message), attachments=[attachment])
                if success:
                    self.bot.confirm_daily_report_send(userid)
                    self.log.warning(f"({message_counter}/{len(unconfirmed_reports)}) Sent daily report to {userid}")
                    if backoff_time > 1:
                        backoff_time = 0.7 * backoff_time
                else:
                    self.log.error(
                        f"({message_counter}/{len(unconfirmed_reports)}) Error sending daily report to {userid}")
                    backoff_time = 2 ^ ceil(backoff_time)
                    # Disable user, hacky workaround for https://github.com/eknoes/covidbot/issues/103
                    self.bot.disable_user(userid)

                sleep_seconds = backoff_time
                self.log.info(f"Sleeping {sleep_seconds}s to avoid server limitations")
                time.sleep(sleep_seconds)
                message_counter += 1

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
            backoff_time = random.uniform(0.5, 2)
            message_counter = 0
            for user in users:
                success = await bot.send_message(user, adapt_text(message))
                if success:
                    self.log.warning(f"Sent message to {user}")
                    if backoff_time > 1:
                        backoff_time = 0.7 * backoff_time
                else:
                    self.log.error(f"Error sending message to {user}")
                    backoff_time = 2 ^ ceil(backoff_time)
                    # Disable user, hacky workaround for https://github.com/eknoes/covidbot/issues/103
                    self.bot.disable_user(user)

                sleep_seconds = backoff_time
                self.log.info(f"Sleeping {sleep_seconds}s to avoid server limitations")
                time.sleep(sleep_seconds)
                message_counter += 1

                if append_report:
                    response = self.reportHandler("", user)
                    attachments = []
                    if response.image:
                        attachments.append(self.get_attachment(response.image))
                    success = await bot.send_message(user, adapt_text(response.message), attachments)

                    if success:
                        self.log.warning(f"Sent message to {user}")
                        if backoff_time > 1:
                            backoff_time = 0.7 * backoff_time
                    else:
                        self.log.error(f"Error sending message to {user}")
                        backoff_time = 2 ^ ceil(backoff_time)
                        # Disable user, hacky workaround for https://github.com/eknoes/covidbot/issues/103
                        self.bot.disable_user(user)

                    sleep_seconds = backoff_time
                    self.log.info(f"Sleeping {sleep_seconds}s to avoid server limitations")
                    time.sleep(sleep_seconds)
                    message_counter += 1

        await self.restart_service()

    async def sendMessageToDev(self, message: str, bot: semaphore.Bot):
        await bot.send_message(self.dev_chat, adapt_text(message))
