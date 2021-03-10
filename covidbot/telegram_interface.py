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
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, PhotoSize, ChatAction, \
    MessageEntity, InputMediaPhoto
from telegram.error import BadRequest, TelegramError, Unauthorized
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters, CallbackQueryHandler
from telegram.ext.dispatcher import DEFAULT_GROUP

from covidbot.bot import Bot, UserDistrictActions
from covidbot.covid_data.visualization import Visualization
from covidbot.messenger_interface import MessengerInterface
from covidbot.metrics import SENT_IMAGES_COUNT, SENT_MESSAGE_COUNT, BOT_COMMAND_COUNT, RECV_MESSAGE_COUNT, \
    BOT_RESPONSE_TIME

'''
Telegram Aktionen:
hilfe - Infos zur Benutzung
info - Erläuterung der Zahlen
daten - Aktuelle Zahlen für den Ort
abo - Abonniere Ort
beende - Widerrufe Abonnement
bericht - Aktueller Bericht
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

    def __init__(self, bot: Bot, api_key: str, dev_chat_id: int, data_visualization: Visualization):
        self.dev_chat_id = dev_chat_id
        self._bot = bot
        self._viz = data_visualization
        self.updater = Updater(api_key)

    def get_input_media_photo(self, filename: str) -> Union[InputMediaPhoto]:
        if filename in self.cache.keys():
            return InputMediaPhoto(self.cache[filename])

        with open(filename, "rb") as f:
            return InputMediaPhoto(f, filename=filename)

    def set_file_id(self, filename: str, file_id: str):
        self.cache[filename] = file_id

    def run(self):
        self.updater.dispatcher.add_handler(MessageHandler(Filters.update, callback=self.countRecvMessagesHandler), group=DEFAULT_GROUP + 1)
        self.updater.dispatcher.add_handler(MessageHandler(Filters.update.edited_message, self.editedMessageHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.update.channel_posts, self.channelPostHandler))
        self.updater.dispatcher.add_handler(CommandHandler('hilfe', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('info', self.infoHandler))
        self.updater.dispatcher.add_handler(CommandHandler('loeschmich', self.deleteHandler))
        self.updater.dispatcher.add_handler(CommandHandler('stop', self.deleteHandler))
        self.updater.dispatcher.add_handler(CommandHandler('datenschutz', self.privacyHandler))
        self.updater.dispatcher.add_handler(CommandHandler('start', self.startHandler))
        self.updater.dispatcher.add_handler(CommandHandler('bericht', self.reportHandler))
        self.updater.dispatcher.add_handler(CommandHandler('daten', self.currentHandler))
        self.updater.dispatcher.add_handler(CommandHandler('ort', self.currentHandler))
        self.updater.dispatcher.add_handler(CommandHandler('impfungen', self.vaccHandler))
        self.updater.dispatcher.add_handler(CommandHandler('abo', self.subscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('beende', self.unsubscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('statistik', self.statHandler))
        self.updater.dispatcher.add_handler(CommandHandler('sprache', self.languageHandler))
        self.updater.dispatcher.add_handler(CommandHandler('debug', self.debugHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.command, self.unknownHandler))
        self.updater.dispatcher.add_handler(CallbackQueryHandler(self.callbackHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.text, self.directMessageHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.location, self.directMessageHandler))
        self.updater.dispatcher.add_error_handler(self.error_callback)

        self.send_message_to_dev("I just started successfully!")
        self.updater.start_polling()
        self.updater.idle()

    def answer_update(self, update: Update, message: str, photos: Optional[List[str]] = None,
                      disable_web_page_preview=False, reply_markup=None) -> bool:
        return self.send_telegram_message(update.effective_chat.id, message, photos, disable_web_page_preview,
                                          reply_markup)

    def send_telegram_message(self, chat_id: int, message: str, photos: Optional[List[str]] = None,
                              disable_web_page_preview=False, reply_markup=None) -> bool:
        if photos:
            self.updater.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            if len(photos) == 1:
                photo = photos[0]
                caption = None
                if len(message) <= 1024:
                    caption = message

                message_obj = self.updater.bot.send_photo(chat_id, self.get_input_media_photo(photo).media,
                                                          caption=caption, parse_mode=ParseMode.HTML)
                SENT_IMAGES_COUNT.inc(len(photos))

                if message_obj.photo[0]:
                    self.set_file_id(photo, message_obj.photo[0].file_id)

                if caption:
                    if message_obj:
                        return True
                    return False
            else:
                files = []
                for photo in photos:
                    files.append(self.get_input_media_photo(photo))

                sent_messages = self.updater.bot.send_media_group(chat_id, files)
                if sent_messages:
                    for i in range(0, len(sent_messages)):
                        if sent_messages[i].photo:
                            self.set_file_id(photos[i], sent_messages[i].photo[0].file_id)
                SENT_IMAGES_COUNT.inc(len(photos))

        if self.updater.bot.send_message(chat_id, message, parse_mode=ParseMode.HTML,
                                         disable_web_page_preview=disable_web_page_preview,
                                         reply_markup=reply_markup):
            SENT_MESSAGE_COUNT.inc()
            return True
        return False

    @staticmethod
    def countRecvMessagesHandler(update: Update, context: CallbackContext):
        RECV_MESSAGE_COUNT.inc()

    @BOT_RESPONSE_TIME.time()
    def startHandler(self, update: Update, context: CallbackContext):
        BOT_COMMAND_COUNT.labels('start').inc()
        name = ""
        if update.effective_user:
            name = update.effective_user.first_name
        self.answer_update(update, self._bot.start_message(update.effective_chat.id, name))
        if update.effective_user and update.effective_user.language_code:
            self._bot.set_language(update.effective_chat.id, update.effective_user.language_code)

    @BOT_RESPONSE_TIME.time()
    def helpHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('help').inc()
        self.answer_update(update, self._bot.help_message(update.effective_chat.id), disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def infoHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('info').inc()
        self.answer_update(update, self._bot.explain_message(), disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def privacyHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('privacy').inc()
        self.answer_update(update, self._bot.get_privacy_msg())

    @BOT_RESPONSE_TIME.time()
    def languageHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('set_language').inc()
        self.answer_update(update, self._bot.set_language(update.effective_chat.id, " ".join(context.args)))

    @BOT_RESPONSE_TIME.time()
    def debugHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('debug').inc()
        self.answer_update(update, self._bot.get_debug_report(update.effective_chat.id))

    @BOT_RESPONSE_TIME.time()
    def currentHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('district_data').inc()
        query = " ".join(context.args)
        msg, districts = self._bot.find_district_id(query)
        if not districts:
            self.answer_update(update, msg)
        elif len(districts) > 1:
            markup = self.gen_multi_district_answer(districts, TelegramCallbacks.REPORT)
            self.answer_update(update, msg, reply_markup=markup)
        else:
            district_id = districts[0][0]
            message = self._bot.get_district_report(district_id)
            self.answer_update(update, message, [self._viz.infections_graph(district_id),
                                                 self._viz.incidence_graph(district_id)], disable_web_page_preview=True)

    @BOT_RESPONSE_TIME.time()
    def deleteHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('delete_me').inc()
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Ja, alle meine Daten löschen",
                                                             callback_data=TelegramCallbacks.DELETE_ME.name)],
                                       [InlineKeyboardButton("Nein", callback_data=TelegramCallbacks.DISCARD.name)]])
        self.answer_update(update, "Sollen alle deine Abonnements und Daten gelöscht werden?", reply_markup=markup)

    @BOT_RESPONSE_TIME.time()
    def subscribeHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('subscribe').inc()
        if not context.args:
            msg, districts = self._bot.get_overview(update.effective_chat.id)
        else:
            query = " ".join(context.args)
            msg, districts = self._bot.find_district_id(query)

        if not districts:
            self.answer_update(update, msg)
        elif len(districts) > 1 or not context.args:
            if not context.args:
                markup = self.gen_multi_district_answer(districts, TelegramCallbacks.CHOOSE_ACTION)
            else:
                markup = self.gen_multi_district_answer(districts, TelegramCallbacks.SUBSCRIBE)
            self.answer_update(update, msg, reply_markup=markup)
        else:
            self.answer_update(update, self._bot.subscribe(update.effective_chat.id, districts[0][0]))

    @BOT_RESPONSE_TIME.time()
    def unsubscribeHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('unsubscribe').inc()
        query = " ".join(context.args)
        msg, districts = self._bot.find_district_id(query)
        if not districts:
            self.answer_update(update, msg)
        elif len(districts) > 1:
            markup = self.gen_multi_district_answer(districts, TelegramCallbacks.UNSUBSCRIBE)
            self.answer_update(update, msg, reply_markup=markup)
        else:
            self.answer_update(update, self._bot.unsubscribe(update.effective_chat.id, districts[0][0]))

    @BOT_RESPONSE_TIME.time()
    def reportHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('report').inc()
        self.sendReport(update.effective_chat.id)

    @BOT_RESPONSE_TIME.time()
    def unknownHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('unknown').inc()
        self.answer_update(update, self._bot.unknown_action())
        self.log.info("Someone called an unknown action: " + update.message.text)

    @BOT_RESPONSE_TIME.time()
    def editedMessageHandler(self, update: Update, context: CallbackContext) -> None:
        update.message = update.edited_message
        update.edited_message = None
        self.updater.dispatcher.process_update(update)

    @BOT_RESPONSE_TIME.time()
    def channelPostHandler(self, update: Update, context: CallbackContext) -> None:
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
    def callbackHandler(self, update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        if query.message.message_id in self.deleted_callbacks:
            return

        query.answer()
        # Subscribe Callback
        if query.data.startswith(TelegramCallbacks.SUBSCRIBE.name):
            BOT_COMMAND_COUNT.labels('subscribe').inc()
            district_id = int(query.data[len(TelegramCallbacks.SUBSCRIBE.name):])
            query.edit_message_text(self._bot.subscribe(update.effective_chat.id, district_id),
                                    parse_mode=telegram.ParseMode.HTML)

        # Unsubscribe Callback
        elif query.data.startswith(TelegramCallbacks.UNSUBSCRIBE.name):
            BOT_COMMAND_COUNT.labels('unsubscribe').inc()
            district_id = int(query.data[len(TelegramCallbacks.UNSUBSCRIBE.name):])
            query.edit_message_text(self._bot.unsubscribe(update.effective_chat.id, district_id),
                                    parse_mode=telegram.ParseMode.HTML)

        # Choose Action Callback
        elif query.data.startswith(TelegramCallbacks.CHOOSE_ACTION.name):
            BOT_COMMAND_COUNT.labels('choose_action').inc()
            district_id = int(query.data[len(TelegramCallbacks.CHOOSE_ACTION.name):])
            text, markup = self.chooseActionBtnGenerator(district_id, update.effective_chat.id)
            if markup is not None:
                query.edit_message_text(text, reply_markup=markup, parse_mode=telegram.ParseMode.HTML)
            else:
                query.edit_message_text(text, parse_mode=telegram.ParseMode.HTML)

        # Send Report Callback
        elif query.data.startswith(TelegramCallbacks.REPORT.name):
            BOT_COMMAND_COUNT.labels('report').inc()
            district_id = int(query.data[len(TelegramCallbacks.REPORT.name):])
            message = self._bot.get_district_report(district_id)
            self.answer_update(update, message,
                               [self._viz.infections_graph(district_id), self._viz.incidence_graph(district_id)],
                               disable_web_page_preview=True)

            query.delete_message()
            self.deleted_callbacks.append(query.message.message_id)

        # DeleteMe Callback
        elif query.data.startswith(TelegramCallbacks.DELETE_ME.name):
            BOT_COMMAND_COUNT.labels('delete_me').inc()
            query.edit_message_text(self._bot.delete_user(update.effective_chat.id), parse_mode=telegram.ParseMode.HTML)

        # Discard Callback
        elif query.data.startswith(TelegramCallbacks.DISCARD.name):
            BOT_COMMAND_COUNT.labels('discard_callback').inc()
            query.delete_message()
            self.deleted_callbacks.append(query.message.message_id)

        # ConfirmFeedback Callback
        elif query.data.startswith(TelegramCallbacks.CONFIRM_FEEDBACK.name):
            BOT_COMMAND_COUNT.labels('send_feedback').inc()
            if update.effective_chat.id not in self.feedback_cache:
                query.edit_message_text(self._bot.get_error_message(), parse_mode=telegram.ParseMode.HTML)
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
            query.edit_message_text(self._bot.get_error_message(), parse_mode=telegram.ParseMode.HTML)

    @BOT_RESPONSE_TIME.time()
    def directMessageHandler(self, update: Update, context: CallbackContext) -> None:
        if update.message.location:
            msg, districts = self._bot.find_district_id_from_geolocation(update.message.location.longitude,
                                                                         update.message.location.latitude)
        else:
            # Make Commands without / available
            # See #82: https://github.com/eknoes/covid-bot/issues/82
            cmd_with_args = update.message.text.split()
            if cmd_with_args[0].lower() in ["hilfe", "info", "loeschmich", "datenschutz", "start", "bericht", "ort",
                                            "abo", "beende", "statistik", "sprache", "debug", "impfungen", "daten"]:
                update.message.text = f"/{update.message.text}"
                update.message.entities = [
                    MessageEntity(MessageEntity.BOT_COMMAND, offset=0, length=len(cmd_with_args[0]) + 1)]
                return self.updater.dispatcher.process_update(update)

            msg, districts = self._bot.find_district_id(update.message.text)

        if not districts:
            self.answer_update(update, msg)

            self.feedback_cache[update.effective_chat.id] = update.message.text
            if update.effective_user:
                self.feedback_cache[update.effective_chat.id] += "\n— {name}" \
                    .format(name=update.effective_user.first_name)
            feedback_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Ja", callback_data=TelegramCallbacks.CONFIRM_FEEDBACK.name)],
                 [InlineKeyboardButton("Abbrechen",
                                       callback_data=TelegramCallbacks.DISCARD.name)]])

            self.answer_update(update, "Hast du gar keinen Ort gesucht, sondern möchtest uns deine Nachricht als "
                                       "Feedback zusenden?", reply_markup=feedback_markup)
        else:
            if len(districts) > 1:
                markup = self.gen_multi_district_answer(districts, TelegramCallbacks.CHOOSE_ACTION)
            else:
                msg, markup = self.chooseActionBtnGenerator(districts[0][0], update.effective_chat.id)
            self.answer_update(update, msg, reply_markup=markup)

    @staticmethod
    def gen_multi_district_answer(districts: List[Tuple[int, str]],
                                  callback: TelegramCallbacks) -> InlineKeyboardMarkup:
        buttons = []
        for district_id, name in districts:
            buttons.append([InlineKeyboardButton(name, callback_data=callback.name + str(district_id))])
        return InlineKeyboardMarkup(buttons)

    def chooseActionBtnGenerator(self, district_id: int, user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
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
            buttons.append([InlineKeyboardButton(action_name, callback_data=callback)])

        markup = InlineKeyboardMarkup(buttons)
        return message, markup

    async def send_daily_reports(self) -> None:
        self.log.debug("Check for new daily reports update")
        messages = self._bot.get_unconfirmed_daily_reports()
        if not messages:
            return

        # Empty file cache as there seems to be new content
        self.graph_cache = {}

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
                sent_msg = self.sendReport(userid, message)
                if sent_msg:
                    self._bot.confirm_daily_report_send(userid)
                    # Add to flood window, on message > 1024 characters, 2 messages are sent
                    sliding_flood_window.append(time.perf_counter())
                    if len(message) > 1024:
                        sliding_flood_window.append(time.perf_counter())

                self.log.warning(f"Sent report to {userid}!")
            except Unauthorized:
                self._bot.delete_user(userid)
                logging.warning(f"Deleted user {userid} as he blocked us")

    def sendReport(self, userid: int, message=None):
        if not message:
            message = self._bot.get_report(userid)

        graph = self._viz.infections_graph(0)
        sent_msg = self.send_telegram_message(userid, message, [graph], disable_web_page_preview=True)

        if sent_msg:
            return True
        return False

    @BOT_RESPONSE_TIME.time()
    def statHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('statistic').inc()
        self.answer_update(update, self._bot.get_statistic(), [self._viz.bot_user_graph()])

    @BOT_RESPONSE_TIME.time()
    def vaccHandler(self, update: Update, context: CallbackContext) -> None:
        BOT_COMMAND_COUNT.labels('vaccinations').inc()
        self.answer_update(update, self._bot.get_vaccination_overview(0), [self._viz.vaccination_graph(0)],
                           disable_web_page_preview=True)

    async def send_message(self, message: str, users: List[Union[str, int]], append_report=False):
        if not users:
            users = map(lambda x: x.platform_id, self._bot.get_all_user())
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
                    self.sendReport(uid)
                    # As 2 messages are sent
                    sliding_flood_window.append(time.perf_counter())

                sliding_flood_window.append(time.perf_counter())
                self.log.warning(f"Sent message to {str(uid)}")
            except BadRequest as error:
                self.log.warning(f"Could not send message to {str(uid)}: {str(error)}")
            except Unauthorized:
                self._bot.delete_user(uid)
                self.log.warning(f"Could not send message to {str(uid)} as he blocked us")

    def error_callback(self, update: Update, context: CallbackContext):
        # Send all errors to maintainers
        # Try to send non Telegram Exceptions to maintainer
        try:
            tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
            tb_string = ''.join(tb_list)

            message = [f'<b>An exception was raised while handling an update!</b>\n']
            if update:
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
                if not self.send_message_to_dev(line):
                    self.log.warning("Can't send message to developers!")

            # Inform user that an error happened
            if update.effective_chat.id:
                context.bot.send_message(chat_id=update.effective_chat.id,
                                         text="Entschuldige, leider ist ein Fehler aufgetreten. Bitte versuche "
                                              "es später erneut!")
        except Exception as e:
            self.log.error("Can't send error to developers", exc_info=e)

        # noinspection PyBroadException
        if isinstance(context.error, Unauthorized):
            user_id = 0
            if update and update.effective_chat:
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

    def send_message_to_dev(self, message: str):
        if self.send_telegram_message(self.dev_chat_id, message):
            return True
        return False
