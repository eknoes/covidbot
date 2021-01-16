import html
import json
import logging
import time
import traceback
from typing import Tuple, Optional

import telegram
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest, TelegramError, Unauthorized, TimedOut, NetworkError
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters, CallbackQueryHandler

from covidbot.bot import Bot
from covidbot.location_service import LocationService

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


class TelegramInterface(object):
    _bot: Bot
    _location_service: LocationService
    log = logging.getLogger(__name__)
    dev_chat_id: int

    CALLBACK_CMD_SUBSCRIBE = "subscribe"
    CALLBACK_CMD_DELETEME = "deleteme"
    CALLBACK_CMD_NODELETE = "donotdelete"
    CALLBACK_CMD_UNSUBSCRIBE = "unsubscribe"
    CALLBACK_CMD_CHOOSE_ACTION = "choose"
    CALLBACK_CMD_REPORT = "report"

    def __init__(self, bot: Bot, api_key: str, dev_chat_id: int):
        self.dev_chat_id = dev_chat_id
        self._bot = bot
        self._location_service = LocationService('resources/germany_rs.geojson')
        self.updater = Updater(api_key)

        self.updater.dispatcher.add_handler(MessageHandler(Filters.update.edited_message, self.editedMessageHandler))
        self.updater.dispatcher.add_handler(CommandHandler('hilfe', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('loeschmich', self.deleteHandler))
        self.updater.dispatcher.add_handler(CommandHandler('datenschutz', self.privacyHandler))
        self.updater.dispatcher.add_handler(CommandHandler('start', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('bericht', self.reportHandler))
        self.updater.dispatcher.add_handler(CommandHandler('ort', self.currentHandler))
        self.updater.dispatcher.add_handler(CommandHandler('abo', self.subscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('beende', self.unsubscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('statistik', self.statHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.command, self.unknownHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.location, self.locationHandler))
        self.updater.dispatcher.add_handler(CallbackQueryHandler(self.callbackHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.text, self.directMessageHandler))
        self.updater.dispatcher.add_error_handler(self.error_callback)
        self.updater.job_queue.run_repeating(self.updateHandler, interval=1300, first=10)

    def helpHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_html(f'Hallo {update.effective_user.first_name},\n'
                                  f'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                                  f'COVID19-Daten anzeigen lassen und sie dauerhaft abonnieren.\n\n'
                                  f'Schicke einfach eine Nachricht mit dem Ort, für den Du Informationen erhalten '
                                  f'möchtest. Der Ort kann entweder ein Bundesland oder ein Stadt-/ Landkreis sein. '
                                  f'Du kannst auch einen Standort senden. '
                                  f'Wenn Du auf "Starte Abo" klickst, erhältst du '
                                  f'jeden Morgen deinen persönlichen Tagesbericht mit den von dir '
                                  f'abonnierten Orten. Wählst du "Bericht" aus, '
                                  f'erhältst Du die Informationen über den Ort nur einmalig. '
                                  f'\n\n'
                                  f'Möchtest Du ein Abonnement beenden, schicke eine Nachricht mit dem '
                                  f'entsprechenden Ort und wähle dann "Beende Abo" aus.'
                                  f'\n\n'
                                  f'Außerdem kannst du mit dem Befehl /bericht deinen Tagesbericht und mit /abo eine '
                                  f'Übersicht über deine aktuellen Abonnements einsehen.\n'
                                  f'Über den /statistik Befehl erhältst du eine kurze Nutzungsstatistik über diesen '
                                  f'Bot.\n\n'
                                  f'Mehr Informationen zu diesem Bot findest du hier: '
                                  f'https://github.com/eknoes/covid-bot\n\n'
                                  f'Diesen Hilfetext erhältst du über /hilfe, Datenschutzinformationen über '
                                  f'/datenschutz.')
        self.log.debug("Someone called /hilfe")

    @staticmethod
    def privacyHandler(update: Update, context: CallbackContext) -> None:
        update.message.reply_html("Unsere Datenschutzerklärung findest du hier: "
                                  "https://github.com/eknoes/covid-bot/wiki/Datenschutz\n\n"
                                  "Außerdem kannst du mit dem Befehl /loeschmich alle deine bei uns gespeicherten "
                                  "Daten löschen.")

    def currentHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        message = self._bot.get_current(entity)
        update.message.reply_html(message)
        self.log.debug("Someone called /ort")

    def deleteHandler(self, update: Update, context: CallbackContext) -> None:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Ja, alle meine Daten löschen",
                                                             callback_data=self.CALLBACK_CMD_DELETEME)],
                                       [InlineKeyboardButton("Nein", callback_data=self.CALLBACK_CMD_NODELETE)]])
        update.message.reply_html("Sollen alle deine Abonnements und Daten gelöscht werden?", reply_markup=markup)

    def subscribeHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        update.message.reply_html(self._bot.subscribe(update.effective_chat.id, entity))
        self.log.debug("Someone called /abo" + entity)

    def unsubscribeHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        update.message.reply_html(self._bot.unsubscribe(str(update.effective_chat.id), entity))
        self.log.debug("Someone called /beende" + entity)

    def reportHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_html(self._bot.get_report(update.effective_chat.id))
        self.log.debug("Someone called /bericht")

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
        if query.data.startswith(self.CALLBACK_CMD_SUBSCRIBE):
            district = query.data[len(self.CALLBACK_CMD_SUBSCRIBE):]
            query.edit_message_text(self._bot.subscribe(update.effective_chat.id, district),
                                    parse_mode=telegram.ParseMode.HTML)
        elif query.data.startswith(self.CALLBACK_CMD_UNSUBSCRIBE):
            district = query.data[len(self.CALLBACK_CMD_UNSUBSCRIBE):]
            query.edit_message_text(self._bot.unsubscribe(update.effective_chat.id, district),
                                    parse_mode=telegram.ParseMode.HTML)
        elif query.data.startswith(self.CALLBACK_CMD_CHOOSE_ACTION):
            district = query.data[len(self.CALLBACK_CMD_CHOOSE_ACTION):]
            text, markup = self.genButtonMessage(district, update.effective_chat.id)
            if markup is not None:
                query.edit_message_text(text, reply_markup=markup)
            else:
                query.edit_message_text(text)
        elif query.data.startswith(self.CALLBACK_CMD_REPORT):
            district = query.data[len(self.CALLBACK_CMD_REPORT):]
            query.edit_message_text(self._bot.get_current(district), parse_mode=telegram.ParseMode.HTML)
        elif query.data.startswith(self.CALLBACK_CMD_DELETEME):
            query.edit_message_text(self._bot.delete_user(update.effective_chat.id), parse_mode=telegram.ParseMode.HTML)
        elif query.data.startswith(self.CALLBACK_CMD_NODELETE):
            query.delete_message()

    def directMessageHandler(self, update: Update, context: CallbackContext) -> None:
        text, markup = self.genButtonMessage(update.message.text, update.effective_chat.id)
        if markup is None:
            update.message.reply_html(text)
        else:
            update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

    def genButtonMessage(self, county: str, user_id: int) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
        locations = self._bot.data.find_rs(county)
        if locations is None or len(locations) == 0:
            return (f"Die Ortsangabe {county} konnte leider nicht zugeordnet werden! "
                    "Hilfe zur Benutzung des Bots gibts über <code>/hilfe</code>", None)
        elif len(locations) == 1:
            return self.genSingleBtn(locations[0][0], user_id)
        else:
            buttons = []
            for rs, county in locations:
                buttons.append([InlineKeyboardButton(county, callback_data=self.CALLBACK_CMD_CHOOSE_ACTION + county)])
            markup = InlineKeyboardMarkup(buttons)
            return "Bitte wähle einen Ort:", markup

    def genSingleBtn(self, rs: int, user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
        name = self._bot.data.get_rs_name(rs)
        buttons = [[InlineKeyboardButton("Bericht", callback_data=self.CALLBACK_CMD_REPORT + name)]]
        if rs in self._bot.manager.get_subscriptions(user_id):
            buttons.append([InlineKeyboardButton("Beende Abo",
                                                 callback_data=self.CALLBACK_CMD_UNSUBSCRIBE + name)])
            verb = "beenden"
        else:
            buttons.append([InlineKeyboardButton("Starte Abo",
                                                 callback_data=self.CALLBACK_CMD_SUBSCRIBE + name)])
            verb = "starten"
        markup = InlineKeyboardMarkup(buttons)
        return (f"Möchtest du dein Abo von {name} {verb} oder nur den aktuellen Bericht erhalten?",
                markup)

    def locationHandler(self, update: Update, context: CallbackContext) -> None:
        if update.message.location is None:
            return

        rs = self._location_service.find_rs(update.message.location.longitude, update.message.location.latitude)
        if rs is None:
            update.message.reply_html(f"Leider konnte kein Ort in den RKI Corona Daten zu deinem Standort gefunden "
                                      f"werden. Bitte beachte, dass Daten nur für Orte innerhalb Deutschlands "
                                      f"verfügbar sind.")
        else:
            text, markup = self.genSingleBtn(rs, update.effective_chat.id)
            if markup is None:
                update.message.reply_html(text)
            else:
                update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

    def updateHandler(self, context: CallbackContext) -> None:
        self.log.info("Check for data update")
        messages = self._bot.update()
        if not messages:
            return

        # Avoid flood limits of 30 messages / second
        messages_sent = 0
        for userid, message in messages:
            if messages_sent > 0 and messages_sent % 25 == 0:
                self.log.info("Sleep for one second to avoid flood limits")
                time.sleep(1.0)
            context.bot.send_message(chat_id=userid, text=message, parse_mode=ParseMode.HTML)
            self.log.info(f"Sent report to {userid}")
            messages_sent += 1

    def statHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_html(self._bot.get_statistic())

    def run(self):
        self.updater.start_polling()
        self.updater.idle()

    def send_correction_message(self, msg):
        for subscriber in self._bot.manager.get_all_user():
            try:
                self.updater.bot.send_message(subscriber, msg, parse_mode=telegram.ParseMode.HTML)
                self.updater.bot.send_message(subscriber, self._bot.get_report(subscriber),
                                              parse_mode=telegram.ParseMode.HTML)
                logging.info(f"Sent correction message to {str(subscriber)}")
            except BadRequest as error:
                logging.warning(f"Could not send message to {str(subscriber)}: {str(error)}")

    def error_callback(self, update: Update, context: CallbackContext):
        # noinspection PyBroadException
        if context.error is Unauthorized:
            logging.warning(f"TelegramError: Unauthorized chat_id {update.message.chat_id}", exc_info=context.error)
            self._bot.manager.delete_user(update.message.chat_id)
        elif context.error is BadRequest:
            logging.warning(f"TelegramError: BadRequest: {update.message.text}", exc_info=context.error)
        elif context.error is TimedOut:
            logging.warning(f"TelegramError: TimedOut sending {update.message.text}", exc_info=context.error)
        elif context.error is NetworkError:
            logging.warning(f"TelegramError: NetworkError while sending {update.message.text}", exc_info=context.error)
        elif context.error is TelegramError:
            logging.warning(f"TelegramError", exc_info=context.error)
        else:
            # Stop on all other exceptions
            logging.error(f"Non-Telegram Exception. Exiting!", exc_info=context.error)

            # Try to send non Telegram Exceptions to maintainer
            try:
                tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
                tb_string = ''.join(tb_list)

                message = [
                    f'An exception was raised while handling an update!\n',
                    f'<pre>update = {html.escape(json.dumps(update.to_dict(), indent=2, ensure_ascii=False))}'
                    f'</pre>\n\n',
                    f'<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n',
                    f'<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n',
                    f'<pre>{html.escape(tb_string)}</pre>'
                ]

                # Finally, send the message
                self.log.info("Send error message to developers")
                for line in message:
                    if not context.bot.send_message(chat_id=self.dev_chat_id, text=line, parse_mode=ParseMode.HTML):
                        self.log.warning("Can't send message to developers!")
            except Exception as e:
                self.log.error("Can't send error to developers", exc_info=e)

            self.updater.stop()