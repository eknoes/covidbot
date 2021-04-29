import html
import logging
import os
import signal
import time
import traceback
from enum import Enum
from typing import List, Dict, Union

import telegram
import ujson as json
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, ChatAction, \
    InputMediaPhoto
from telegram.error import BadRequest, TelegramError, Unauthorized, ChatMigrated
from telegram.ext import Updater, CallbackContext, MessageHandler, Filters, CallbackQueryHandler

from covidbot.interfaces.messenger_interface import MessengerInterface
from covidbot.metrics import SENT_IMAGES_COUNT, SENT_MESSAGE_COUNT, BOT_RESPONSE_TIME, RECV_MESSAGE_COUNT, \
    BOT_SEND_MESSAGE_ERRORS
from covidbot.bot import Bot
from covidbot.user_hint_service import UserHintService
from covidbot.utils import split_message
from covidbot.interfaces.bot_response import BotResponse

'''
Telegram Aktionen:
hilfe - Infos zur Benutzung
info - Erläuterung der Zahlen
daten - Aktuelle Zahlen für den Ort
abo - Abonniere Ort
beende - Widerrufe Abonnement
bericht - Aktueller Bericht
regeln - Regeln für Ort
impfungen - Zeige Impfbericht
statistik - Nutzungsstatistik
datenschutz - Datenschutzerklärung
loeschmich - Lösche alle Daten
'''


class TelegramCallbacks(Enum):
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    DELETE_ME = "delete_me"
    CHOOSE_ACTION = "choose_action"
    REPORT = "report"
    RULES = "rules"
    CONFIRM_FEEDBACK = "feedback"
    DISCARD = "discard"


class TelegramInterface(MessengerInterface):
    bot: Bot
    cache: Dict[str, str] = {}
    log = logging.getLogger(__name__)
    dev_chat_id: int
    deleted_callbacks: List[int] = []

    def __init__(self, bot: Bot, api_key: str, dev_chat_id: int):
        self.dev_chat_id = dev_chat_id
        self.bot = bot
        self.updater = Updater(api_key)

    def run(self):
        # Adapt messages for text-handling
        self.updater.dispatcher.add_handler(MessageHandler(Filters.update.edited_message, self.adapt_edited_message))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.update.channel_posts, self.adapt_channel_post))

        # Handle messages
        self.updater.dispatcher.add_handler(CallbackQueryHandler(self.handle_callback_query))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.command, self.handle_text))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.text, self.handle_text))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.location, self.handle_location))

        self.updater.dispatcher.add_error_handler(self.error_callback)
        self.message_developer("I just started successfully!")
        self.updater.start_polling()
        self.updater.idle()

    # Methods to send messages
    def answer_callback_query(self, update: Update, response: List[BotResponse], disable_web_page_preview=False):
        """
        Send :py:class:BotResponse as answer to an :py:class:telegram.Update containing a :py:class:telegram.CallbackQuery
        Args:
            update:
            response:
            disable_web_page_preview:

        Returns:

        """
        query = update.callback_query
        if len(response) == 1 and response[0].images and not response[0].choices:
            if not response[0].images:
                return query.edit_message_text(response[0].message, disable_web_page_preview=disable_web_page_preview)
        query.delete_message()
        self.deleted_callbacks.append(query.message.message_id)

        self.send_message(update.effective_chat.id, response,
                          disable_web_page_preview=disable_web_page_preview)

    def answer_update(self, update: Update, response: List[BotResponse],
                      disable_web_page_preview=False) -> bool:
        """
        Send :py:class:BotResponse as answer to an :py:class:telegram.Update
        Args:
            update:
            response:
            disable_web_page_preview:

        Returns:

        """
        return self.send_message(update.effective_chat.id, response,
                                 disable_web_page_preview)

    def send_message(self, chat_id: int, responses: List[BotResponse],
                     disable_web_page_preview=False) -> bool:
        """
        Send list of :py:class:BotResponse to a certain chat
        Args:
            chat_id:
            responses:
            disable_web_page_preview:

        Returns:

        """
        success = True
        try:
            for response in responses:
                if response.images:
                    self.updater.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                    if len(response.images) == 1 and not response.choices:
                        photo = response.images[0]
                        caption = None
                        if len(response.message) <= 1024:
                            caption = response.message

                        message_obj = self.updater.bot.send_photo(chat_id, self.get_input_media_photo(photo).media,
                                                                  caption=caption, parse_mode=ParseMode.HTML)
                        SENT_IMAGES_COUNT.inc(len(response.images))

                        if message_obj.photo[0]:
                            self.set_file_id(photo, message_obj.photo[0].file_id)

                        if caption:
                            if not message_obj:
                                success = False
                            continue
                    else:
                        files = []
                        for photo in response.images:
                            files.append(self.get_input_media_photo(photo))

                        sent_messages = self.updater.bot.send_media_group(chat_id, files)
                        if sent_messages:
                            for i in range(0, len(sent_messages)):
                                if sent_messages[i].photo:
                                    self.set_file_id(response.images[i], sent_messages[i].photo[0].file_id)
                        SENT_IMAGES_COUNT.inc(len(response.images))

                messages = split_message(response.message, max_bytes=4096)
                reply_markup = None
                for i in range(0, len(messages)):
                    if response.choices and i == len(messages) - 1:
                        buttons = []
                        for choice in response.choices:
                            buttons.append([InlineKeyboardButton(choice.label, callback_data=choice.callback_data)])
                        reply_markup = InlineKeyboardMarkup(buttons)

                    if self.updater.bot.send_message(chat_id, messages[i], parse_mode=ParseMode.HTML,
                                                     disable_web_page_preview=disable_web_page_preview,
                                                     reply_markup=reply_markup):
                        SENT_MESSAGE_COUNT.inc()
                    else:
                        success = False
        except BadRequest as e:
            self.log.warning(f"Bad Request on sending Telegram message to {chat_id}: {e.message}", exc_info=e)
            success = False
            BOT_SEND_MESSAGE_ERRORS.labels(platform='telegram', error='bad-request').inc()
        except Unauthorized:
            self.bot.delete_user(chat_id)
            logging.warning(f"Deleted user {chat_id} as he blocked us")
            BOT_SEND_MESSAGE_ERRORS.labels(platform='telegram', error='unauthorized').inc()
        except ChatMigrated as e:
            if self.bot.change_platform_id(str(chat_id), str(e.new_chat_id)):
                self.log.info(f"Migrated Chat {chat_id} to {e.new_chat_id}")
                return self.send_message(e.new_chat_id, responses, disable_web_page_preview)
            else:
                self.log.warning(f"Could not migrate {chat_id} to {e.new_chat_id}")
                self.bot.disable_user(chat_id)
        return success

    @BOT_RESPONSE_TIME.time()
    def adapt_edited_message(self, update: Update, context: CallbackContext) -> None:
        """
        Method to modify :py:class:telegram.Update containing edited message,
        so that it can be handled a a normal received message. Dispatches modified update again.
        Args:
            update:
            context:
        """
        update.message = update.edited_message
        update.edited_message = None
        self.updater.dispatcher.process_update(update)

    @BOT_RESPONSE_TIME.time()
    def adapt_channel_post(self, update: Update, context: CallbackContext) -> None:
        """
        Method to modify :py:class:telegram.Update containing channel message,
        so that it can be handled a a normal received message. Dispatches modified update again.
        Args:
            update:
            context:

        Returns:

        """
        if update.channel_post:
            update.message = update.channel_post
            update.channel_post = None
        elif update.edited_channel_post:
            update.message = update.edited_channel_post
            update.edited_channel_post = None

        entities = update.message.parse_entities()
        for entity in entities:
            if entity.type == entity.MENTION and context.bot.username == entities[entity][1:]:
                # Strip mention from message
                update.message.text = (update.message.text[0:entity.offset] + update.message.text[
                                                                              entity.offset + entity.length:]).strip()
                self.updater.dispatcher.process_update(update)
                return

    @BOT_RESPONSE_TIME.time()
    def handle_callback_query(self, update: Update, context: CallbackContext) -> None:
        RECV_MESSAGE_COUNT.inc()
        query = update.callback_query
        if query.message.message_id in self.deleted_callbacks:
            return

        try:
            query.answer()
        except BadRequest as e:
            # Avoid exception on too old callback queries
            self.log.exception("Error while answering callback query", exc_info=e)

        self.answer_callback_query(update, self.bot.handle_input(query.data, update.effective_chat.id),
                                   disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def handle_text(self, update: Update, context: CallbackContext):
        RECV_MESSAGE_COUNT.inc()
        message = update.message.text

        # Strip own mentions
        mention_pos = message.find('@' + context.bot.username)
        if mention_pos != -1:
            message = message[:mention_pos] + message[mention_pos + len('@' + context.bot.username):]

        responses = self.bot.handle_input(message, update.effective_chat.id)
        self.answer_update(update, responses, disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def handle_location(self, update: Update, context: CallbackContext):
        RECV_MESSAGE_COUNT.inc()
        responses = self.bot.handle_geolocation(update.message.location.longitude, update.message.location.latitude,
                                                update.effective_chat.id)
        self.answer_update(update, responses, disable_web_page_preview=True)

    async def send_unconfirmed_reports(self) -> None:
        self.log.debug("Check for new daily reports update")
        if not self.bot.user_messages_available():
            return

        # Avoid flood limits of 30 messages / second
        sliding_flood_window = []
        for report_type, userid, message in self.bot.get_available_user_messages():
            if len(sliding_flood_window) >= 25:
                # We want to send 25 messages per second max
                flood_window_diff = time.perf_counter() - sliding_flood_window.pop(0)
                if flood_window_diff < 1.05:  # safety margin
                    self.log.info(f"Sleep for {1.05 - flood_window_diff}s")
                    time.sleep(1.05 - flood_window_diff)

            sent_msg = self.send_message(userid, message, disable_web_page_preview=True)
            if sent_msg:
                self.bot.confirm_message_send(report_type, userid)
                sliding_flood_window.append(time.perf_counter())

            self.log.warning(f"Sent report to {userid}!")

    async def send_message_to_users(self, message: str, users: List[Union[str, int]]):
        if not users:
            users = map(lambda x: x.platform_id, self.bot.get_all_users())

        message = UserHintService.format_commands(message, self.bot.command_formatter)
        sliding_flood_window = []
        for uid in users:
            if len(sliding_flood_window) >= 5:
                # We want to send 25 messages per second max (might be even more due to append_report)
                flood_window_diff = time.perf_counter() - sliding_flood_window.pop(0)
                if flood_window_diff < 1.05:  # safety margin
                    self.log.info(f"Sleep for {1.05 - flood_window_diff}s")
                    time.sleep(1.05 - flood_window_diff)

            self.updater.bot.send_message(uid, message, parse_mode=telegram.ParseMode.HTML)
            sliding_flood_window.append(time.perf_counter())
            self.log.warning(f"Sent message to {str(uid)}")

    def error_callback(self, update: object, context: CallbackContext):
        # Send all errors to maintainers
        # Try to send non Telegram Exceptions to maintainer
        try:
            tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
            tb_string = ''.join(tb_list)

            message = [f'<b>An exception was raised while handling an update!</b>\n']
            if update and type(update) == Update:
                message.append(
                    f'<pre>update = {html.escape(json.dumps(update.to_dict(), indent=2, ensure_ascii=False))}'
                    f'</pre>\n\n', )
            if context and context.chat_data:
                message.append(f'<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n')

            if context and context.user_data:
                message.append(f'<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n', )

            message.append(f'<pre>{html.escape(tb_string)}</pre>')

            # Finally, send the message
            self.log.info("Send error message to developers")
            for line in message:
                if not self.message_developer(line):
                    self.log.warning("Can't send message to developers!")

            # Inform user that an error happened
            if update:
                if type(update) == Update:
                    if update.effective_chat.id:
                        self.send_message(update.effective_chat.id, [self.bot.get_error_message()])
        except Exception as e:
            self.log.error("Can't send error to developers", exc_info=e)

        # noinspection PyBroadException
        if isinstance(context.error, Unauthorized):
            user_id = 0
            if update and type(update) == Update and update.effective_chat:
                user_id = update.effective_chat.id

            logging.warning(f"TelegramError: Unauthorized chat_id {user_id}", exc_info=context.error)
            if user_id and self.bot.delete_user(user_id):
                logging.info(f"Removed {user_id} from users")
        elif isinstance(context.error, TelegramError):
            logging.warning(f"TelegramError: While sending {context.chat_data}", exc_info=context.error)
        else:
            # Stop on all other exceptions
            logging.error(f"Non-Telegram Exception. Exiting!", exc_info=context.error)
            # Stop bot
            os.kill(os.getpid(), signal.SIGINT)

    def message_developer(self, message: str):
        if self.send_message(self.dev_chat_id, [BotResponse(message)]):
            return True
        return False

    # Telegram file cache
    def get_input_media_photo(self, filename: str) -> Union[InputMediaPhoto]:
        if filename in self.cache.keys():
            return InputMediaPhoto(self.cache[filename])

        with open(filename, "rb") as f:
            return InputMediaPhoto(f, filename=filename)

    def set_file_id(self, filename: str, file_id: str):
        self.cache[filename] = file_id
