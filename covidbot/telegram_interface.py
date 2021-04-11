import html
import logging
import os
import signal
import time
import traceback
from enum import Enum
from typing import Tuple, List, Dict, Union, Optional

import telegram
import ujson as json
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, ChatAction, \
    MessageEntity, InputMediaPhoto
from telegram.error import BadRequest, TelegramError, Unauthorized, ChatMigrated
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters, CallbackQueryHandler
from telegram.ext.dispatcher import DEFAULT_GROUP

from covidbot.bot import Bot, UserDistrictActions, UserHintService
from covidbot.covid_data.models import District
from covidbot.covid_data.visualization import Visualization
from covidbot.messenger_interface import MessengerInterface
from covidbot.metrics import SENT_IMAGES_COUNT, SENT_MESSAGE_COUNT, BOT_COMMAND_COUNT, RECV_MESSAGE_COUNT, \
    BOT_RESPONSE_TIME
from covidbot.utils import str_bytelen, BotResponse, split_message

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
    _bot: Bot
    _viz: Visualization
    cache: Dict[str, str] = {}
    log = logging.getLogger(__name__)
    dev_chat_id: int
    feedback_cache: Dict[int, str] = {}
    deleted_callbacks: List[int] = []

    def __init__(self, bot: Bot, api_key: str, dev_chat_id: int):
        self.dev_chat_id = dev_chat_id
        self._bot = bot
        self.updater = Updater(api_key)

    def run(self):
        self.updater.dispatcher.add_handler(MessageHandler(Filters.update, callback=self.update_metrics_handler),
                                            group=DEFAULT_GROUP + 1)
        self.updater.dispatcher.add_handler(MessageHandler(Filters.update.edited_message, self.adapt_edited_message))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.update.channel_posts, self.adapt_channel_post))
        self.updater.dispatcher.add_handler(CommandHandler('hilfe', self.help_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('info', self.info_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('loeschmich', self.delete_user_handler))
        self.updater.dispatcher.add_handler(CommandHandler('stop', self.delete_user_handler))
        self.updater.dispatcher.add_handler(CommandHandler('datenschutz', self.privacy_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('start', self.start_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('bericht', self.report_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('daten', self.current_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('regeln', self.rules_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('impfungen', self.vaccinations_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('abo', self.subscribe_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('beende', self.unsubscribe_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('statistik', self.statistic_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('sprache', self.set_language_command_handler))
        self.updater.dispatcher.add_handler(CommandHandler('debug', self.debug_command_handler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.command, self.unknown_command_handler))
        self.updater.dispatcher.add_handler(CallbackQueryHandler(self.callback_query_handler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.text, self.raw_message_handler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.location, self.raw_message_handler))
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
        if len(response) == 1 and response[0].images:
            if not response[0].images:
                return query.edit_message_text(response[0].message, disable_web_page_preview=disable_web_page_preview)

        query.delete_message()
        self.deleted_callbacks.append(query.message.message_id)
        self.send_message(update.effective_chat.id, response,
                          disable_web_page_preview=disable_web_page_preview)

    def answer_update(self, update: Update, response: List[BotResponse],
                      disable_web_page_preview=False, reply_markup=None) -> bool:
        """
        Send :py:class:BotResponse as answer to an :py:class:telegram.Update
        Args:
            update:
            response:
            disable_web_page_preview:
            reply_markup:

        Returns:

        """
        return self.send_message(update.effective_chat.id, response,
                                 disable_web_page_preview,
                                 reply_markup)

    def send_message(self, chat_id: int, responses: List[BotResponse],
                     disable_web_page_preview=False, reply_markup=None) -> bool:
        """
        Send list of :py:class:BotResponse to a certain chat
        Args:
            chat_id:
            responses:
            disable_web_page_preview:
            reply_markup:

        Returns:

        """
        success = True
        for response in responses:
            if response.images:
                self.updater.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                if len(response.images) == 1:
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
            for m in messages:
                if self.updater.bot.send_message(chat_id, m, parse_mode=ParseMode.HTML,
                                                 disable_web_page_preview=disable_web_page_preview,
                                                 reply_markup=reply_markup):
                    SENT_MESSAGE_COUNT.inc()
                else:
                    success = False

        return success

    @staticmethod
    def update_metrics_handler(update: Update, context: CallbackContext):
        """
        Stub method used for prometheus metrics to count number of received messages
        Args:
            update:
            context:
        """
        RECV_MESSAGE_COUNT.inc()

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

    # Handlers for different commands and messages
    @BOT_RESPONSE_TIME.time()
    def start_command_handler(self, update: Update, context: CallbackContext):
        BOT_COMMAND_COUNT.labels('start').inc()
        name = ""
        if update.effective_user:
            name = update.effective_user.first_name
        self.answer_update(update, self._bot.start_message(update.effective_chat.id, name))
        if update.effective_user and update.effective_user.language_code:
            self._bot.set_language(update.effective_chat.id, update.effective_user.language_code)

    @BOT_RESPONSE_TIME.time()
    def help_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('help').inc()
        self.answer_update(update, self._bot.help_message(update.effective_chat.id), disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def info_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('info').inc()
        self.answer_update(update, self._bot.explain_message(), disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def privacy_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('privacy').inc()
        self.answer_update(update, self._bot.get_privacy_msg())

    @BOT_RESPONSE_TIME.time()
    def set_language_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('set_language').inc()
        self.answer_update(update, self._bot.set_language(update.effective_chat.id, " ".join(context.args)))

    @BOT_RESPONSE_TIME.time()
    def debug_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('debug').inc()
        self.answer_update(update, self._bot.get_debug_report(update.effective_chat.id))

    @BOT_RESPONSE_TIME.time()
    def current_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('district_data').inc()
        query = " ".join(context.args)
        response, districts = self._bot.find_district_id(query)
        if not districts:
            self.answer_update(update, [response])
        elif len(districts) > 1:
            markup = self.generate_multiple_districts_markup(districts, TelegramCallbacks.REPORT)
            self.answer_update(update, [response], reply_markup=markup)
        else:
            district_id = districts[0].id
            message = self._bot.get_district_report(district_id)
            self.answer_update(update, message, disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def rules_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('rules').inc()
        query = " ".join(context.args)
        response, districts = self._bot.find_district_id(query)
        if not districts:
            self.answer_update(update, [response])
        elif len(districts) > 1:
            markup = self.generate_multiple_districts_markup(districts, TelegramCallbacks.RULES)
            self.answer_update(update, [response], reply_markup=markup)
        else:
            district_id = districts[0].id
            message = self._bot.get_rules(district_id)
            self.answer_update(update, message, disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def delete_user_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('delete_me').inc()
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Ja, alle meine Daten löschen",
                                                             callback_data=TelegramCallbacks.DELETE_ME.name)],
                                       [InlineKeyboardButton("Nein", callback_data=TelegramCallbacks.DISCARD.name)]])
        self.answer_update(update, [BotResponse("Sollen alle deine Abonnements und Daten gelöscht werden?")],
                           reply_markup=markup)

    @BOT_RESPONSE_TIME.time()
    def subscribe_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('subscribe').inc()
        if not context.args:
            response, districts = self._bot.get_overview(update.effective_chat.id)
        else:
            query = " ".join(context.args)
            response, districts = self._bot.find_district_id(query)

        if not districts:
            self.answer_update(update, [response])
        elif len(districts) > 1 or not context.args:
            if not context.args:
                markup = self.generate_multiple_districts_markup(districts, TelegramCallbacks.CHOOSE_ACTION)
            else:
                markup = self.generate_multiple_districts_markup(districts, TelegramCallbacks.SUBSCRIBE)
            self.answer_update(update, [response], reply_markup=markup)
        else:
            self.answer_update(update, self._bot.subscribe(update.effective_chat.id, districts[0].id),
                               disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def unsubscribe_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('unsubscribe').inc()
        query = " ".join(context.args)
        response, districts = self._bot.find_district_id(query)
        if not districts:
            self.answer_update(update, [response])
        elif len(districts) > 1:
            markup = self.generate_multiple_districts_markup(districts, TelegramCallbacks.UNSUBSCRIBE)
            self.answer_update(update, [response], reply_markup=markup)
        else:
            self.answer_update(update, self._bot.unsubscribe(update.effective_chat.id, districts[0].id))

    @BOT_RESPONSE_TIME.time()
    def report_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('report').inc()
        self.send_message(update.effective_chat.id, self._bot.get_report(update.effective_chat.id),
                          disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def unknown_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('unknown').inc()
        self.answer_update(update, self._bot.unknown_action())
        self.log.info("Someone called an unknown action: " + update.message.text)

    @BOT_RESPONSE_TIME.time()
    def statistic_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('statistic').inc()
        self.answer_update(update, self._bot.get_statistic())

    @BOT_RESPONSE_TIME.time()
    def vaccinations_command_handler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('vaccinations').inc()
        self.answer_update(update, self._bot.get_vaccination_overview(0),
                           disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def callback_query_handler(self, update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        if query.message.message_id in self.deleted_callbacks:
            return

        query.answer()
        # Subscribe Callback
        if query.data.startswith(TelegramCallbacks.SUBSCRIBE.name):
            BOT_COMMAND_COUNT.labels('subscribe').inc()
            district_id = int(query.data[len(TelegramCallbacks.SUBSCRIBE.name):])
            self.answer_callback_query(update, self._bot.subscribe(update.effective_chat.id, district_id),
                                       disable_web_page_preview=True)

        # Unsubscribe Callback
        elif query.data.startswith(TelegramCallbacks.UNSUBSCRIBE.name):
            BOT_COMMAND_COUNT.labels('unsubscribe').inc()
            district_id = int(query.data[len(TelegramCallbacks.UNSUBSCRIBE.name):])
            self.answer_callback_query(update, self._bot.unsubscribe(update.effective_chat.id, district_id))

        # Rules Callback
        elif query.data.startswith(TelegramCallbacks.RULES.name):
            BOT_COMMAND_COUNT.labels('rules').inc()
            district_id = int(query.data[len(TelegramCallbacks.RULES.name):])
            self.answer_callback_query(update, self._bot.get_rules(district_id))

        # Choose Action Callback
        elif query.data.startswith(TelegramCallbacks.CHOOSE_ACTION.name):
            BOT_COMMAND_COUNT.labels('choose_action').inc()
            district_id = int(query.data[len(TelegramCallbacks.CHOOSE_ACTION.name):])
            text, markup = self.generate_possible_actions_markup(district_id, update.effective_chat.id)
            if markup is not None:
                query.edit_message_text(text, reply_markup=markup, parse_mode=telegram.ParseMode.HTML)
            else:
                self.answer_callback_query(update, [BotResponse(text)])

        # Send Report Callback
        elif query.data.startswith(TelegramCallbacks.REPORT.name):
            BOT_COMMAND_COUNT.labels('report').inc()
            district_id = int(query.data[len(TelegramCallbacks.REPORT.name):])
            self.answer_callback_query(update, self._bot.get_district_report(district_id),
                                       disable_web_page_preview=True)

        # DeleteMe Callback
        elif query.data.startswith(TelegramCallbacks.DELETE_ME.name):
            BOT_COMMAND_COUNT.labels('delete_me').inc()
            self.answer_callback_query(update, self._bot.delete_user(update.effective_chat.id))

        # Discard Callback
        elif query.data.startswith(TelegramCallbacks.DISCARD.name):
            BOT_COMMAND_COUNT.labels('discard_callback').inc()
            query.delete_message()
            self.deleted_callbacks.append(query.message.message_id)

        # ConfirmFeedback Callback
        elif query.data.startswith(TelegramCallbacks.CONFIRM_FEEDBACK.name):
            BOT_COMMAND_COUNT.labels('send_feedback').inc()
            if update.effective_chat.id not in self.feedback_cache:
                self.answer_callback_query(update, self._bot.get_error_message())
            else:
                feedback = self.feedback_cache[update.effective_chat.id]
                self._bot.add_user_feedback(update.effective_chat.id, feedback)
                if update.effective_user:
                    query.edit_message_text("Danke für dein wertvolles Feedback, {name}!"
                                            .format(name=update.effective_user.first_name))
                else:
                    query.edit_message_text("Danke für dein wertvolles Feedback!")

                del self.feedback_cache[update.effective_chat.id]
        else:
            BOT_COMMAND_COUNT.labels('unknown_callback').inc()
            self.answer_callback_query(update, self._bot.get_error_message())

    @BOT_RESPONSE_TIME.time()
    def raw_message_handler(self, update: Update, context: CallbackContext) -> None:
        if update.message.location:
            response, districts = self._bot.find_district_id_from_geolocation(update.message.location.longitude,
                                                                              update.message.location.latitude)
        else:
            # Make Commands without / available
            # See #82: https://github.com/eknoes/covid-bot/issues/82
            cmd_with_args = update.message.text.split()
            if cmd_with_args[0].lower() in ["hilfe", "info", "loeschmich", "datenschutz", "start", "bericht", "ort",
                                            "abo", "beende", "statistik", "sprache", "debug", "impfungen", "daten",
                                            "regeln"]:
                update.message.text = f"/{update.message.text}"
                update.message.entities = [
                    MessageEntity(MessageEntity.BOT_COMMAND, offset=0, length=len(cmd_with_args[0]) + 1)]
                return self.updater.dispatcher.process_update(update)

            response, districts = self._bot.find_district_id(update.message.text)

        if not districts:
            self.answer_update(update, [response])

            if update.message.text:
                self.feedback_cache[update.effective_chat.id] = update.message.text
                if update.effective_user:
                    self.feedback_cache[update.effective_chat.id] += "\n— {name}" \
                        .format(name=update.effective_user.first_name)
                feedback_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Ja", callback_data=TelegramCallbacks.CONFIRM_FEEDBACK.name)],
                     [InlineKeyboardButton("Abbrechen",
                                           callback_data=TelegramCallbacks.DISCARD.name)]])

                self.answer_update(update, [BotResponse("Hast du gar keinen Ort gesucht, sondern möchtest uns deine "
                                                        "Nachricht als Feedback zusenden?")], reply_markup=feedback_markup)
        else:
            if len(districts) > 1:
                markup = self.generate_multiple_districts_markup(districts, TelegramCallbacks.CHOOSE_ACTION)
            else:
                message, markup = self.generate_possible_actions_markup(districts[0].id, update.effective_chat.id)
                response = BotResponse(message)
            self.answer_update(update, [response], reply_markup=markup)

    # Util methods
    @staticmethod
    def generate_multiple_districts_markup(districts: List[District],
                                           callback: TelegramCallbacks) -> InlineKeyboardMarkup:
        """
        Generates :py:class:telegram.InlineKeyboardMarkup from a list of districts for a certain callback
        Args:
            districts:
            callback:

        Returns:

        """
        buttons = []
        for district in districts:
            buttons.append([InlineKeyboardButton(district.name, callback_data=callback.name + str(district.id))])
        return InlineKeyboardMarkup(buttons)

    def generate_possible_actions_markup(self, district_id: int, user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
        """
        Generates :py:class:telegram.InlineKeyboardMarkup from a district_id, containing
        possible actions
        Args:
            district_id:
            user_id:

        Returns:

        """
        message, actions = self._bot.get_possible_actions(user_id, district_id)
        buttons = []

        for action_name, action in actions:
            callback = ""
            if action == UserDistrictActions.REPORT:
                callback = TelegramCallbacks.REPORT.name + str(district_id)
            elif action == UserDistrictActions.SUBSCRIBE:
                callback = TelegramCallbacks.SUBSCRIBE.name + str(district_id)
            elif action == UserDistrictActions.UNSUBSCRIBE:
                callback = TelegramCallbacks.UNSUBSCRIBE.name + str(district_id)
            elif action == UserDistrictActions.RULES:
                callback = TelegramCallbacks.RULES.name + str(district_id)

            if callback:
                buttons.append([InlineKeyboardButton(action_name, callback_data=callback)])

        markup = InlineKeyboardMarkup(buttons)
        return message, markup

    async def send_unconfirmed_reports(self) -> None:
        self.log.debug("Check for new daily reports update")
        messages = self._bot.get_unconfirmed_daily_reports()
        if not messages:
            return

        # Avoid flood limits of 30 messages / second
        sliding_flood_window = []
        for userid, message in messages:
            if len(sliding_flood_window) >= 25:
                # We want to send 25 messages per second max
                flood_window_diff = time.perf_counter() - sliding_flood_window.pop(0)
                if flood_window_diff < 1.05:  # safety margin
                    self.log.info(f"Sleep for {1.05 - flood_window_diff}s")
                    time.sleep(1.05 - flood_window_diff)

            try:
                sent_msg = self.send_message(userid, message, disable_web_page_preview=True)
                if sent_msg:
                    self._bot.confirm_daily_report_send(userid)
                    sliding_flood_window.append(time.perf_counter())

                self.log.warning(f"Sent report to {userid}!")
            except Unauthorized:
                self._bot.delete_user(userid)
                logging.warning(f"Deleted user {userid} as he blocked us")
            except BadRequest as e:
                self.log.error(f"Bad Request while sending report to {userid}: {e.message}", exc_info=e)
            except ChatMigrated as e:
                if self._bot.change_platform_id(userid, str(e.new_chat_id)):
                    self.log.info(f"Migrated Chat {userid} to {e.new_chat_id}")
                else:
                    self.log.warning(f"Could not migrate {userid} to {e.new_chat_id}")
                    self._bot.disable_user(userid)

    async def send_message_to_users(self, message: str, users: List[Union[str, int]], append_report=False):
        if not users:
            users = map(lambda x: x.platform_id, self._bot.get_all_user())

        message = UserHintService.format_commands(message, self._bot.format_command)
        sliding_flood_window = []
        for uid in users:
            try:
                if len(sliding_flood_window) >= 5:
                    # We want to send 25 messages per second max (might be even more due to append_report)
                    flood_window_diff = time.perf_counter() - sliding_flood_window.pop(0)
                    if flood_window_diff < 1.05:  # safety margin
                        self.log.info(f"Sleep for {1.05 - flood_window_diff}s")
                        time.sleep(1.05 - flood_window_diff)

                self.updater.bot.send_message(uid, message, parse_mode=telegram.ParseMode.HTML)
                if append_report:
                    self.send_message(uid, self._bot.get_report(uid))
                    # As 2 messages are sent
                    sliding_flood_window.append(time.perf_counter())

                sliding_flood_window.append(time.perf_counter())
                self.log.warning(f"Sent message to {str(uid)}")
            except BadRequest as error:
                self.log.warning(f"Could not send message to {str(uid)}: {str(error)}")
            except Unauthorized:
                self._bot.delete_user(uid)
                self.log.warning(f"Could not send message to {str(uid)} as he blocked us")

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
            if update and type(update) == Update and update.effective_chat.id:
                self.send_message(update.effective_chat.id, self._bot.get_error_message())
        except Exception as e:
            self.log.error("Can't send error to developers", exc_info=e)

        # noinspection PyBroadException
        if isinstance(context.error, Unauthorized):
            user_id = 0
            if update and type(update) == Update and update.effective_chat:
                user_id = update.effective_chat.id

            logging.warning(f"TelegramError: Unauthorized chat_id {user_id}", exc_info=context.error)
            if user_id and self._bot.delete_user(user_id):
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
