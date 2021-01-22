import html
import json
import logging
import os
import signal
import time
import traceback
from enum import Enum
from io import BytesIO
from typing import Tuple, List, Dict, Union

import telegram
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, PhotoSize, ChatAction
from telegram.error import BadRequest, TelegramError, Unauthorized, TimedOut, NetworkError
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters, CallbackQueryHandler

from covidbot.bot import Bot, UserDistrictActions

'''
Telegram Aktionen:
hilfe - Infos zur Benutzung
ort - Aktuelle Zahlen für den Ort
abo - Abonniere Ort
beende - Widerrufe Abonnement
bericht - Aktueller Bericht
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


class TelegramInterface(object):
    _bot: Bot
    log = logging.getLogger(__name__)
    dev_chat_id: int
    graph_cache: Dict[int, PhotoSize] = {}
    feedback_cache: Dict[int, str] = {}

    def __init__(self, bot: Bot, api_key: str, dev_chat_id: int):
        self.dev_chat_id = dev_chat_id
        self._bot = bot
        self.updater = Updater(api_key)

        self.updater.dispatcher.add_handler(MessageHandler(Filters.update.edited_message, self.editedMessageHandler))
        self.updater.dispatcher.add_handler(CommandHandler('hilfe', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('loeschmich', self.deleteHandler))
        self.updater.dispatcher.add_handler(CommandHandler('datenschutz', self.privacyHandler))
        self.updater.dispatcher.add_handler(CommandHandler('start', self.startHandler))
        self.updater.dispatcher.add_handler(CommandHandler('bericht', self.reportHandler))
        self.updater.dispatcher.add_handler(CommandHandler('ort', self.currentHandler))
        self.updater.dispatcher.add_handler(CommandHandler('abo', self.subscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('beende', self.unsubscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('statistik', self.statHandler))
        self.updater.dispatcher.add_handler(CommandHandler('sprache', self.languageHandler))
        self.updater.dispatcher.add_handler(CommandHandler('feedback', self.feedbackHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.command, self.unknownHandler))
        self.updater.dispatcher.add_handler(CallbackQueryHandler(self.callbackHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.text, self.directMessageHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.location, self.directMessageHandler))
        self.updater.dispatcher.add_error_handler(self.error_callback)
        self.updater.job_queue.run_repeating(self.updateHandler, interval=1300, first=10)
        self.updater.bot.send_message(self.dev_chat_id, "I just started successfully!")

    def getGraph(self, district_id: int) -> Union[PhotoSize, BytesIO]:
        if district_id in self.graph_cache.keys():
            return self.graph_cache.get(district_id)

        return self._bot.get_graphical_report(district_id)

    def addToFileCache(self, district_id: int, file: PhotoSize):
        self.graph_cache[district_id] = file

    def startHandler(self, update: Update, context: CallbackContext):
        update.message.reply_html(f'Hallo {update.effective_user.first_name},\n'
                                  f'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                                  f'COVID19-Daten anzeigen lassen und sie dauerhaft kostenlos abonnieren. '
                                  f'Einen Überblick über alle Befehle erhältst du über /hilfe.\n\n'
                                  f'Schicke einfach eine Nachricht mit dem Ort, für den Du Informationen erhalten '
                                  f'möchtest. Der Ort kann entweder ein Bundesland oder ein Stadt-/ Landkreis sein. '
                                  f'Du kannst auch einen Standort senden! Wenn die Daten des Ortes nur gesammelt für '
                                  f'eine übergeordneten Landkreis oder eine Region vorliegen, werden dir diese '
                                  f'vorgeschlagen. Du kannst beliebig viele Orte abonnieren und unabhängig von diesen '
                                  f' auch die aktuellen Zahlen für andere Orte ansehen.')
        if update.effective_user and update.effective_user.language_code:
            self._bot.set_language(update.effective_chat.id, update.effective_user.language_code)

    def helpHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_html(f'Hallo {update.effective_user.first_name},\n'
                                  f'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                                  f'COVID19-Daten anzeigen lassen und sie dauerhaft abonnieren.\n\n'
                                  f'<b>Informationen erhalten</b>\n'
                                  f'Schicke einfach eine Nachricht mit dem Ort, für den Du Informationen erhalten '
                                  f'möchtest. Der Ort kann entweder ein Bundesland oder ein Stadt-/ Landkreis sein. '
                                  f'Du kannst auch einen Standort senden. '
                                  f'Wenn Du auf "Starte Abo" klickst, erhältst du '
                                  f'jeden Morgen deinen persönlichen Tagesbericht mit den von dir '
                                  f'abonnierten Orten. Wählst du "Bericht" aus, '
                                  f'erhältst Du die Informationen über den Ort nur einmalig.'
                                  f'\n\n'
                                  f'<b>Kostenloses Abo beenden</b>\n'
                                  f'Möchtest Du ein Abonnement beenden, schicke eine Nachricht mit dem '
                                  f'entsprechenden Ort und wähle dann "Beende Abo" aus. '
                                  f'Wenn du alle Daten die wir über dich gespeichert haben löschen möchtest, '
                                  f'sende /loeschmich.'
                                  f'\n\n'
                                  f'<b>Feedback</b>\n'
                                  f'Wir freuen uns über deine Anregungen, Lob & Kritik! Sende dem Bot einfach eine '
                                  f'Nachricht, du wirst dann gefragt ob diese an uns weitergeleitet werden darf! '
                                  f'Alternativ kannst du auch es auch mit <code>/feedback DEINE NACHRICHT</code> '
                                  f'senden.\n\n'
                                  f'<b>Weiteres</b>\n'
                                  f'Außerdem kannst du mit dem Befehl /bericht deinen Tagesbericht und mit /abo eine '
                                  f'Übersicht über deine aktuellen Abonnements einsehen.\n'
                                  f'Über den /statistik Befehl erhältst du eine kurze Nutzungsstatistik über diesen '
                                  f'Bot.\n\n'
                                  f'Mehr Informationen zu diesem Bot findest du hier: '
                                  f'https://github.com/eknoes/covid-bot\n\n'
                                  f'Diesen Hilfetext erhältst du über /hilfe, Datenschutzinformationen über '
                                  f'/datenschutz.')

    def privacyHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_html(self._bot.get_privacy_msg())

    def languageHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_html(self._bot.set_language(update.effective_chat.id, " ".join(context.args)))

    def currentHandler(self, update: Update, context: CallbackContext) -> None:
        query = " ".join(context.args)
        msg, districts = self._bot.find_district_id(query)
        if not districts:
            update.message.reply_html(msg)
        elif len(districts) > 1:
            markup = self.gen_multi_district_answer(districts, TelegramCallbacks.REPORT)
            update.message.reply_html(msg, reply_markup=markup)
        else:
            district_id = districts[0][0]
            context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=ChatAction.UPLOAD_PHOTO)
            graph = self.getGraph(district_id)
            message = self._bot.get_district_report(district_id)
            if graph:
                message = update.message.reply_photo(graph, caption=message,
                                                     parse_mode=telegram.constants.PARSEMODE_HTML)
                if message.photo:
                    self.addToFileCache(district_id, message.photo[-1])
            else:
                update.message.reply_html(message)
        self.log.debug("Someone called /ort")

    @staticmethod
    def deleteHandler(update: Update, context: CallbackContext) -> None:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Ja, alle meine Daten löschen",
                                                             callback_data=TelegramCallbacks.DELETE_ME.name)],
                                       [InlineKeyboardButton("Nein", callback_data=TelegramCallbacks.DISCARD.name)]])
        update.message.reply_html("Sollen alle deine Abonnements und Daten gelöscht werden?", reply_markup=markup)

    def subscribeHandler(self, update: Update, context: CallbackContext) -> None:
        if not context.args:
            msg, districts = self._bot.get_overview(update.effective_chat.id)
        else:
            query = " ".join(context.args)
            msg, districts = self._bot.find_district_id(query)

        if not districts:
            update.message.reply_html(msg)
        elif len(districts) > 1 or not context.args:
            if not context.args:
                markup = self.gen_multi_district_answer(districts, TelegramCallbacks.CHOOSE_ACTION)
            else:
                markup = self.gen_multi_district_answer(districts, TelegramCallbacks.SUBSCRIBE)
            update.message.reply_html(msg, reply_markup=markup)
        else:
            update.message.reply_html(self._bot.subscribe(update.effective_chat.id, districts[0][0]))

    def unsubscribeHandler(self, update: Update, context: CallbackContext) -> None:
        query = " ".join(context.args)
        msg, districts = self._bot.find_district_id(query)
        if not districts:
            update.message.reply_html(msg)
        elif len(districts) > 1:
            markup = self.gen_multi_district_answer(districts, TelegramCallbacks.UNSUBSCRIBE)
            update.message.reply_html(msg, reply_markup=markup)
        else:
            update.message.reply_html(self._bot.unsubscribe(update.effective_chat.id, districts[0][0]))

    def reportHandler(self, update: Update, context: CallbackContext) -> None:
        graph = self.getGraph(0)
        message = self._bot.get_report(update.effective_chat.id)
        if graph:
            message = update.message.reply_photo(photo=graph, caption=message,
                                                 parse_mode=telegram.constants.PARSEMODE_HTML)
            if message.photo:
                self.addToFileCache(0, message.photo[-1])
        else:
            update.message.reply_html(self._bot.get_report(update.effective_chat.id))

    def unknownHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_html(self._bot.unknown_action())
        self.log.info("Someone called an unknown action: " + update.message.text)

    def editedMessageHandler(self, update: Update, context: CallbackContext) -> None:
        update.message = update.edited_message
        update.edited_message = None
        self.updater.dispatcher.process_update(update)

    def callbackHandler(self, update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        query.answer()
        # Subscribe Callback
        if query.data.startswith(TelegramCallbacks.SUBSCRIBE.name):
            district_id = int(query.data[len(TelegramCallbacks.SUBSCRIBE.name):])
            query.edit_message_text(self._bot.subscribe(update.effective_chat.id, district_id),
                                    parse_mode=telegram.ParseMode.HTML)

        # Unsubscribe Callback
        elif query.data.startswith(TelegramCallbacks.UNSUBSCRIBE.name):
            district_id = int(query.data[len(TelegramCallbacks.UNSUBSCRIBE.name):])
            query.edit_message_text(self._bot.unsubscribe(update.effective_chat.id, district_id),
                                    parse_mode=telegram.ParseMode.HTML)

        # Choose Action Callback
        elif query.data.startswith(TelegramCallbacks.CHOOSE_ACTION.name):
            district_id = int(query.data[len(TelegramCallbacks.CHOOSE_ACTION.name):])
            text, markup = self.chooseActionBtnGenerator(district_id, update.effective_chat.id)
            if markup is not None:
                query.edit_message_text(text, reply_markup=markup, parse_mode=telegram.ParseMode.HTML)
            else:
                query.edit_message_text(text, parse_mode=telegram.ParseMode.HTML)

        # Send Report Callback
        elif query.data.startswith(TelegramCallbacks.REPORT.name):
            district_id = int(query.data[len(TelegramCallbacks.REPORT.name):])
            context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=ChatAction.UPLOAD_PHOTO)
            graph = self.getGraph(district_id)
            message = self._bot.get_district_report(district_id)
            if graph:
                message = context.bot.send_photo(chat_id=update.effective_chat.id, photo=graph, caption=message,
                                                 parse_mode=telegram.constants.PARSEMODE_HTML)
                if message.photo:
                    self.addToFileCache(district_id, message.photo[-1])
                query.delete_message()
            else:
                query.edit_message_text(message, parse_mode=telegram.ParseMode.HTML)

        # DeleteMe Callback
        elif query.data.startswith(TelegramCallbacks.DELETE_ME.name):
            query.edit_message_text(self._bot.delete_user(update.effective_chat.id), parse_mode=telegram.ParseMode.HTML)

        # Discard Callback
        elif query.data.startswith(TelegramCallbacks.DISCARD.name):
            query.delete_message()

        # ConfirmFeedback Callback
        elif query.data.startswith(TelegramCallbacks.CONFIRM_FEEDBACK.name):
            if update.effective_chat.id not in self.feedback_cache:
                query.edit_message_text(self._bot.get_error_message(), parse_mode=telegram.ParseMode.HTML)
            else:
                feedback = self.feedback_cache[update.effective_chat.id]
                self._bot.add_user_feedback(update.effective_chat.id, feedback)
                query.edit_message_text("Danke für dein wertvolles Feedback!")

                # Send to Devs
                context.bot.send_message(chat_id=self.dev_chat_id, text=f"<b>Neues Feedback!</b>\n{feedback}",
                                         parse_mode=ParseMode.HTML)

                del self.feedback_cache[update.effective_chat.id]
        else:
            query.edit_message_text(self._bot.get_error_message(), parse_mode=telegram.ParseMode.HTML)

    def directMessageHandler(self, update: Update, context: CallbackContext) -> None:
        if update.message.location:
            msg, districts = self._bot.find_district_id_from_geolocation(update.message.location.longitude,
                                                                         update.message.location.latitude)
        else:
            msg, districts = self._bot.find_district_id(update.message.text)

        if not districts:
            update.message.reply_html(msg)

            self.feedback_cache[update.effective_chat.id] = update.message.text
            feedback_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Ja", callback_data=TelegramCallbacks.CONFIRM_FEEDBACK.name)],
                 [InlineKeyboardButton("Abbrechen",
                                       callback_data=TelegramCallbacks.DISCARD.name)]])

            update.message.reply_html("Hast du gar keinen Ort gesucht, sondern möchtest uns deine Nachricht als "
                                      "Feedback zusenden?", reply_markup=feedback_markup)
        else:
            if len(districts) > 1:
                markup = self.gen_multi_district_answer(districts, TelegramCallbacks.CHOOSE_ACTION)
            else:
                msg, markup = self.chooseActionBtnGenerator(districts[0][0], update.effective_chat.id)
            update.message.reply_html(msg, reply_markup=markup)

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

    def updateHandler(self, context: CallbackContext) -> None:
        self.log.info("Check for data update")
        messages = self._bot.update()
        if not messages:
            return
        # Empty file cache as there seems to be new content
        self.graph_cache = {}

        # Generate graph for country

        # Avoid flood limits of 30 messages / second
        messages_sent = 0
        for userid, message in messages:
            if messages_sent > 0 and messages_sent % 25 == 0:
                self.log.info("Sleep for one second to avoid flood limits")
                time.sleep(1.0)

            graph = self.getGraph(0)
            if graph:
                try:
                    sent_msg = context.bot.send_photo(chat_id=userid, photo=graph, caption=message,
                                                      parse_mode=telegram.constants.PARSEMODE_HTML)
                except BadRequest as e:
                    self.log.warning(f"Can't send report attached to graphic for {userid}: {e.message}", exc_info=e)

                    sent_msg = context.bot.send_photo(chat_id=userid, photo=graph,
                                                      parse_mode=telegram.constants.PARSEMODE_HTML)
                    context.bot.send_message(chat_id=userid, text=message, parse_mode=ParseMode.HTML)

                if sent_msg.photo:
                    self.addToFileCache(0, sent_msg.photo[-1])
            else:
                self.log.warning("No graph available in report!")
                sent_msg = context.bot.send_message(chat_id=userid, text=message, parse_mode=ParseMode.HTML)

            if sent_msg:
                self._bot.confirm_daily_report_send(userid)

            self.log.info(f"Sent report to {userid}!")
            messages_sent += 1

    def statHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_html(self._bot.get_statistic())

    def feedbackHandler(self, update: Update, context: CallbackContext) -> None:
        feedback = " ".join(context.args)

        if not feedback:
            update.message.reply_html("Als Feedback kann leider nur Text angenommen werden!"
                                      "Bitte versuche es erneut mit einem Text: <code>/feedback DEIN TEXT</code>")
            return

        context.bot.send_message(chat_id=self.dev_chat_id, text=f"<b>Neues Feedback!</b>\n{feedback}",
                                 parse_mode=ParseMode.HTML)
        self._bot.add_user_feedback(update.effective_chat.id, feedback)

        update.message.reply_html("Danke für dein wertvolles Feedback!")

    def run(self):
        self.updater.start_polling()
        self.updater.idle()

    def message_all_users(self, report: str, with_report=False):
        no_flood_counter = 0
        for user in self._bot.get_all_user():
            try:
                if no_flood_counter % 25 == 0:
                    time.sleep(1)

                self.updater.bot.send_message(user.id, report, parse_mode=telegram.ParseMode.HTML)
                if with_report:
                    no_flood_counter += 1  # Additional message
                    graph = self.getGraph(0)
                    report = self._bot.get_report(user.id)
                    if graph:
                        report = self.updater.bot.send_photo(chat_id=user.id, photo=graph, caption=report,
                                                             parse_mode=telegram.constants.PARSEMODE_HTML)
                        if report.photo:
                            self.addToFileCache(0, report.photo[-1])
                    else:
                        self.log.warning("No graph available in report!")
                        self.updater.bot.send_message(chat_id=user.id, text=report, parse_mode=ParseMode.HTML)

                no_flood_counter += 1
                logging.info(f"Sent message to {str(user)}")
            except BadRequest as error:
                logging.warning(f"Could not send message to {str(user)}: {str(error)}")

    def error_callback(self, update: Update, context: CallbackContext):
        # Send all errors to maintainers
        # Try to send non Telegram Exceptions to maintainer
        try:
            tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
            tb_string = ''.join(tb_list)

            message = [f'<b>An exception was raised while handling an update!</b>\n']
            if update:
                message.append(f'<pre>update = {html.escape(json.dumps(update.to_dict(), indent=2, ensure_ascii=False))}'
                               f'</pre>\n\n',)
            if context and context.chat_data:
                message.append(f'<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n')

            if context and context.user_data:
                message.append(f'<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n',)
                
            message.append(f'<pre>{html.escape(tb_string)}</pre>')

            # Finally, send the message
            self.log.info("Send error message to developers")
            for line in message:
                if not context.bot.send_message(chat_id=self.dev_chat_id, text=line, parse_mode=ParseMode.HTML):
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
            logging.warning(f"TelegramError: Unauthorized chat_id {update.message.chat_id}", exc_info=context.error)
            self._bot.delete_user(update.message.chat_id)
        elif isinstance(context.error, BadRequest):
            logging.warning(f"TelegramError: BadRequest: {str(context.chat_data)}", exc_info=context.error)
        elif isinstance(context.error, TimedOut):
            logging.warning(f"TelegramError: TimedOut sending {str(context.chat_data)}", exc_info=context.error)
        elif isinstance(context.error, NetworkError):
            logging.warning(f"TelegramError: NetworkError while sending {str(context.chat_data)}",
                            exc_info=context.error)
        elif isinstance(context.error, TelegramError):
            logging.warning(f"TelegramError: While sending {context.chat_data}", exc_info=context.error)
        else:
            # Stop on all other exceptions
            logging.error(f"Non-Telegram Exception. Exiting!", exc_info=context.error)
            # Stop bot
            os.kill(os.getpid(), signal.SIGINT)
