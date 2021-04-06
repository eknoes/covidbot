import asyncio
import os
import random
import re
import signal
import time
import traceback
import prometheus_async.aio
from math import ceil
from typing import Dict, List, Optional

import semaphore
from semaphore import ChatContext

from covidbot.bot import Bot, UserHintService
from covidbot.covid_data.visualization import Visualization
from covidbot.messenger_interface import MessengerInterface
from covidbot.metrics import RECV_MESSAGE_COUNT, SENT_IMAGES_COUNT, SENT_MESSAGE_COUNT, BOT_RESPONSE_TIME, \
    FAILED_MESSAGE_COUNT
from covidbot.text_interface import SimpleTextInterface
from covidbot.utils import adapt_text, BotResponse


class SignalInterface(SimpleTextInterface, MessengerInterface):
    phone_number: str
    socket: str
    profile_name: Optional[str] = None  # = "Covid Update"
    profile_picture: Optional[str] = None  # = os.path.abspath("resources/logo.png")
    dev_chat: str = None

    def __init__(self, phone_number: str, socket: str, bot: Bot, dev_chat: str):
        super().__init__(bot)
        self.phone_number = phone_number
        self.socket = socket
        self.dev_chat = dev_chat

    def run(self):
        asyncio.run(self.run_async())

    async def run_async(self):
        async with semaphore.Bot(self.phone_number, socket_path=self.socket, profile_name=self.profile_name,
                                 profile_picture=self.profile_picture) as bot:
            # We do not really use the underlying bot framework, but just use our own Pure-Text Handler
            bot.register_handler(re.compile(""), self.message_handler)
            bot.set_exception_handler(self.exception_callback)
            await bot.start()

    async def exception_callback(self, exception: Exception, ctx: ChatContext):
        self.log.exception("An exception occurred, exiting...", exc_info=exception)
        tb_list = traceback.format_exception(None, exception, exception.__traceback__)
        tb_string = ''.join(tb_list)

        await self.send_to_dev(f"Exception occurred: {tb_string}\n\nGot message {ctx.message}", ctx.bot)
        # Just exit on exception
        os.kill(os.getpid(), signal.SIGINT)

    @prometheus_async.aio.time(BOT_RESPONSE_TIME)
    async def message_handler(self, ctx: ChatContext):
        """
        Handles a text message received by the bot
        """
        RECV_MESSAGE_COUNT.inc()
        text = ctx.message.get_body()
        if text:
            await ctx.message.typing_started()
            if text.find('https://maps.google.com/maps?q='):
                # This is a location
                text = re.sub('\nhttps://maps.google.com/maps\?q=.*', '', text)
                # Strip URL so it is searched for the contained address
            platform_id = ctx.message.source.uuid
            # Currently, we disable user that produce errors on sending the daily report
            # If they would query our bot, we'd like to have them activated before we process their query
            # This is a hacky workaround for https://github.com/eknoes/covidbot/issues/103
            if not self.bot.is_user_activated(platform_id):
                self.bot.enable_user(platform_id)
            replies = self.handle_input(text, platform_id)
            for reply in replies:
                await self.send_reply(ctx, reply)
            await ctx.message.typing_stopped()

    async def send_reply(self, ctx: ChatContext, reply: BotResponse):
        """
        Answers a signal message with the given :class:`covidbot.BotResponse`
        """
        reply.message = adapt_text(reply.message)

        attachment = []
        if reply.images:
            for image in reply.images:
                attachment.append(self.get_attachment(image))
                SENT_IMAGES_COUNT.inc()

        if await ctx.message.reply(body=reply.message, attachments=attachment):
            SENT_MESSAGE_COUNT.inc()
        else:
            self.log.error(f"Could not send message to {ctx.message.username}:\n{reply.message}")
            FAILED_MESSAGE_COUNT.inc()

    @staticmethod
    def get_attachment(filename: str) -> Dict:
        """
        Returns an attachement dict to send an image with signald, containing a file path to the graphic
        """
        return {"filename": filename, "width": "1600", "height": "1000"}

    async def send_daily_reports(self) -> None:
        """
        Send unconfirmed daily reports to the specific users
        """
        # Get reports
        unconfirmed_reports = self.bot.get_unconfirmed_daily_reports()
        if not unconfirmed_reports:
            return

        # Get the current graph as attachement dict
        self.log.warning(f"{len(unconfirmed_reports)} to send!")

        async with semaphore.Bot(self.phone_number, socket_path=self.socket, profile_name=self.profile_name,
                                 profile_picture=self.profile_picture) as bot:
            backoff_time = random.uniform(0.5, 2)
            message_counter = 0
            for userid, message in unconfirmed_reports:
                self.log.info(f"Try to send report {message_counter}")
                success = await bot.send_message(userid, adapt_text(message.message), attachments=message.images)
                if success:
                    self.bot.confirm_daily_report_send(userid)
                    self.log.warning(f"({message_counter}/{len(unconfirmed_reports)}) Sent daily report to {userid}")
                else:
                    self.log.error(
                        f"({message_counter}/{len(unconfirmed_reports)}) Error sending daily report to {userid}")

                backoff_time = self.backoff_timer(backoff_time, not success, userid)
                message_counter += 1

        await self.restart_service()

    async def send_message(self, message: str, users: List[str], append_report=False) -> None:
        """
        Send a message to specific or all users
        Args:
            message: Message to send
            users: List of user ids or None for all signal users
            append_report: True if a current report should be appended
        """
        if not users:
            users = map(lambda x: x.platform_id, self.bot.get_all_user())

        message = UserHintService.format_commands(message, self.bot.format_command)

        async with semaphore.Bot(self.phone_number, socket_path=self.socket, profile_name=self.profile_name,
                                 profile_picture=self.profile_picture) as bot:
            backoff_time = random.uniform(0.5, 2)
            for user in users:
                success = await bot.send_message(user, adapt_text(message))
                backoff_time = self.backoff_timer(backoff_time, not success, user)

                if append_report:
                    response = self.reportHandler("", user)
                    attachments = []
                    if response.images:
                        for image in response.images:
                            attachments.append(self.get_attachment(image))
                    success = await bot.send_message(user, adapt_text(response.message), attachments)
                    backoff_time = self.backoff_timer(backoff_time, not success, user)

        await self.restart_service()

    def backoff_timer(self, current_backoff: float, failed: bool, user_id: str) -> float:
        """
        Sleeps and calculates the new backoff time, depending whether sending the message failed or not
        Args:
            current_backoff: current backoff time in seconds
            failed: True if sending the message led to an error
            user_id: ID of the receiver

        Returns:
            float: new backoff time
        """
        if not failed:
            self.log.info(f"Sent message to {user_id}")
            if current_backoff > 1:
                new_backoff = 0.7 * current_backoff
            else:
                new_backoff = current_backoff
        else:
            self.log.error(f"Error sending message to {user_id}")
            # Disable user, hacky workaround for https://github.com/eknoes/covidbot/issues/103
            self.bot.disable_user(user_id)
            new_backoff = 2 ^ ceil(current_backoff)
        self.log.info(f"Sleeping {new_backoff}s to avoid server limitations")
        time.sleep(new_backoff)
        return new_backoff

    async def send_to_dev(self, message: str, bot: semaphore.Bot):
        await bot.send_message(self.dev_chat, adapt_text(message))

    async def restart_service(self) -> None:
        """
        Restarts the signald and signalbot service
        """
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
