import asyncio
import logging
import os
import queue
import random
import re
import signal
import time
import traceback
from dataclasses import dataclass
from math import ceil
from typing import Dict, List, Optional

import prometheus_async.aio
import semaphore
from semaphore import ChatContext
from semaphore.exceptions import SignaldError, InternalError, InvalidRequestError, \
    RateLimitError, NoSuchAccountError, NoSendPermissionError, UnknownGroupError, \
    InvalidRecipientError, UnknownError

from covidbot.interfaces.messenger_interface import MessengerInterface
from covidbot.metrics import RECV_MESSAGE_COUNT, SENT_IMAGES_COUNT, SENT_MESSAGE_COUNT, \
    BOT_RESPONSE_TIME, \
    FAILED_MESSAGE_COUNT
from covidbot.bot import Bot
from covidbot.settings import BotUserSettings
from covidbot.user_hint_service import UserHintService
from covidbot.utils import adapt_text
from covidbot.interfaces.bot_response import BotResponse


@dataclass
class SignalSendElem:
    context: Optional[ChatContext]
    messages: List[BotResponse]


def format_response(bot_response: BotResponse, just_strip: bool):
    bot_response.message = adapt_text(str(bot_response), just_strip=just_strip)
    return bot_response


class SignalInterface(MessengerInterface):
    phone_number: str
    socket: str
    profile_name: Optional[str] = None  # = "Covid Update"
    profile_picture: Optional[str] = None  # = os.path.abspath("resources/logo.png")
    dev_chat: str = None
    bot: Bot
    log = logging.getLogger(__name__)
    message_queue: asyncio.Queue

    def __init__(self, bot: Bot, phone_number: str, socket: str, dev_chat: str):
        self.bot = bot
        self.phone_number = phone_number
        self.socket = socket
        self.dev_chat = dev_chat

    def run(self):
        asyncio.run(self.run_async())

    async def run_async(self):
        self.message_queue = asyncio.Queue()
        await asyncio.gather(asyncio.create_task(self.run_bot()),
                             asyncio.create_task(self.message_sender()))

    async def message_sender(self):
        self.log.debug("Initializing Sender")
        backoff_time = 1

        while await asyncio.sleep(0.1) is None:
            if not self.message_queue.empty():
                message = self.message_queue.get_nowait()
                self.log.debug(f"Got item for {message.context.message.source.uuid} from queue")
                try:
                    await message.context.message.typing_started()
                    for m in message.messages:
                        await self.send_reply(message.context, m)
                    await message.context.message.typing_stopped()
                except RateLimitError as e:
                    self.log.warning(f"Got rate limited, current backoff: {backoff_time} seconds")
                    rate_limited = True
                else:
                    rate_limited = False
                    self.message_queue.task_done()

                backoff_time = self.backoff_timer(backoff_time, rate_limited)
                await asyncio.sleep(backoff_time)

    async def run_bot(self):
        self.log.debug("Initializing Bot")
        async with semaphore.Bot(self.phone_number, socket_path=self.socket,
                                 profile_name=self.profile_name,
                                 profile_picture=self.profile_picture,
                                 raise_errors=True) as bot:
            # We do not really use the underlying bot framework, but just use our own Pure-Text Handler
            bot.register_handler(re.compile(""), self.message_handler)
            bot.set_exception_handler(self.exception_callback)
            self.log.debug("Starting Semaphore")
            await bot.start()

    async def exception_callback(self, exception: Exception, ctx: ChatContext):
        self.log.exception("An exception occurred, exiting...", exc_info=exception)
        tb_list = traceback.format_exception(None, exception, exception.__traceback__)
        tb_string = ''.join(tb_list)

        await self.send_to_dev(
            f"Exception occurred: {tb_string}\n\nGot message {ctx.message}", ctx.bot)
        # Just exit on exception
        os.kill(os.getpid(), signal.SIGINT)

    @prometheus_async.aio.time(BOT_RESPONSE_TIME)
    async def message_handler(self, ctx: ChatContext):
        """
        Handles a text message received by the bot
        """
        RECV_MESSAGE_COUNT.inc()
        text = ctx.message.get_body()
        self.log.debug(f"Got message {text}")
        if text:
            if text.find('https://maps.google.com/maps?q='):
                # This is a location
                text = re.sub('\nhttps://maps.google.com/maps\?q=.*', '', text)
                # Strip URL so it is searched for the contained address
            platform_id = ctx.message.source.uuid

            replies = self.bot.handle_input(text, platform_id)
            disable_unicode = not self.bot.get_user_setting(platform_id,
                                                            BotUserSettings.FORMATTING)

            item = SignalSendElem(context=ctx,
                                  messages=list(map(lambda x: format_response(x, disable_unicode), replies)))
            await self.message_queue.put(item)
            self.log.debug(f"Added item for {ctx.message.source.uuid} to queue")

    async def send_reply(self, ctx: ChatContext, reply: BotResponse):
        """
        Answers a signal message with the given :class:`covidbot.BotResponse`
        """
        attachment = []
        if reply.images:
            for image in reply.images:
                attachment.append(self.get_attachment(image))
                SENT_IMAGES_COUNT.inc()

        if await ctx.message.reply(body=reply.message, attachments=attachment):
            SENT_MESSAGE_COUNT.inc()
        else:
            self.log.error(
                f"Could not send message to {ctx.message.username}:\n{reply.message}")
            FAILED_MESSAGE_COUNT.inc()

    @staticmethod
    def get_attachment(filename: str) -> Dict:
        """
        Returns an attachement dict to send an image with signald, containing a file path to the graphic
        """
        return {"filename": filename, "width": "1600", "height": "1000"}

    async def send_unconfirmed_reports(self) -> None:
        """
        Send unconfirmed daily reports to the specific users
        """
        if not self.bot.user_messages_available():
            return

        async with semaphore.Bot(self.phone_number, socket_path=self.socket,
                                 profile_name=self.profile_name,
                                 profile_picture=self.profile_picture,
                                 raise_errors=True) as bot:
            backoff_time = random.uniform(2, 6)
            message_counter = 0
            for report_type, userid, message in self.bot.get_available_user_messages():
                self.log.info(f"Try to send report {message_counter}")
                disable_unicode = not self.bot.get_user_setting(userid,
                                                                BotUserSettings.FORMATTING)
                for elem in message:
                    success = False
                    rate_limited = False
                    try:
                        success = await bot.send_message(userid, adapt_text(elem.message,
                                                                            just_strip=disable_unicode),
                                                         attachments=elem.images)
                    except InternalError as e:
                        if "org.whispersystems.signalservice.api.push.exceptions.RateLimitException" in e.exceptions:
                            rate_limited = True
                            break
                        elif "org.whispersystems.signalservice.api.push.exceptions.UnregisteredUserException" in e.exceptions \
                                or "org.whispersystems.signalservice.api.push.exceptions.NotFoundException" in e.exceptions:
                            self.log.warning(
                                f"Account does not exist anymore, delete it: {userid}")
                            self.bot.delete_user(userid)
                            break
                        else:
                            raise e
                    except RateLimitError as e:
                        self.log.error(f"Invalid Send Request: {e.message}")
                        rate_limited = True
                        break
                    except NoSuchAccountError as e:
                        self.log.warning(
                            f"Account does not exist anymore, delete it: {e.account}")
                        self.bot.delete_user(userid)
                        break
                    except UnknownGroupError:
                        self.log.warning(
                            f"Group does not exist anymore, delete it: {userid}")
                        self.bot.delete_user(userid)
                        break
                    except (NoSendPermissionError, InvalidRecipientError) as e:
                        self.log.warning(
                            f"We cant send to {userid}, disabling user: {e.message}")
                        self.bot.disable_user(userid)
                        break
                    except UnknownError as e:
                        self.log.error(f"Unknown Signald Error {e.error_type}: {e.error}")
                        raise e
                    except SignaldError as e:
                        self.log.error(f"Unknown Signald Error {e}")
                        raise e

                if success:
                    self.log.warning(f"({message_counter}) Sent daily report to {userid}")
                    self.bot.confirm_message_send(report_type, userid)
                else:
                    self.log.error(
                        f"({message_counter}) Error sending daily report to {userid}")

                backoff_time = self.backoff_timer(backoff_time, rate_limited)
                message_counter += 1

    async def send_message_to_users(self, message: str, users: List[str]) -> None:
        """
        Send a message to specific or all users
        Args:
            message: Message to send
            users: List of user ids or None for all signal users
        """
        if not users:
            users = map(lambda x: x.platform_id, self.bot.get_all_users())

        message = UserHintService.format_commands(message, self.bot.command_formatter)

        async with semaphore.Bot(self.phone_number, socket_path=self.socket,
                                 profile_name=self.profile_name,
                                 profile_picture=self.profile_picture,
                                 raise_errors=True) as bot:
            for user in users:
                disable_unicode = not self.bot.get_user_setting(user,
                                                                BotUserSettings.FORMATTING)
                await bot.send_message(user, adapt_text(str(message),
                                                        just_strip=disable_unicode))

    def backoff_timer(self, current_backoff: float, failed: bool) -> float:
        """
        Sleeps and calculates the new backoff time, depending whether sending the message failed or not
        Args:
            current_backoff: current backoff time in seconds
            failed: True if we ran into a rate limit

        Returns:
            float: new backoff time
        """
        if not failed:
            # Minimum 0.2s sleep
            if current_backoff > 0.25:
                new_backoff = 0.8 * current_backoff
            else:
                new_backoff = current_backoff
        else:
            new_backoff = 3 * current_backoff
            self.log.warning(f"New backoff time: {new_backoff}s")

        self.log.info(f"Sleeping {new_backoff}s to avoid server limitations")
        time.sleep(new_backoff)
        return new_backoff

    async def send_to_dev(self, message: str, bot: semaphore.Bot):
        await bot.send_message(self.dev_chat, adapt_text(message))
