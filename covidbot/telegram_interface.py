import logging
import time
from enum import Enum

import telegram
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest, TelegramError, Unauthorized, TimedOut, NetworkError, ChatMigrated
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters, CallbackQueryHandler

from covidbot.bot import Bot

'''
Telegram Aktionen:
hilfe - Infos zur Benutzung
ort - Aktuelle Zahlen für den Ort
abo - Abonniere Ort
beende - Widerrufe Abonnement
bericht - Aktueller Bericht
statistik - Nutzungsstatistik
'''


class TelegramInterface(object):
    _bot: Bot
    log = logging.getLogger(__name__)

    CALLBACK_CMD_SUBSCRIBE = "subscribe"
    CALLBACK_CMD_UNSUBSCRIBE = "unsubscribe"
    CALLBACK_CMD_CHOOSE_ACTION = "choose"
    CALLBACK_CMD_REPORT = "report"

    def __init__(self, bot: Bot, api_key: str):
        self._bot = bot

        self.updater = Updater(api_key)

        self.updater.dispatcher.add_handler(CommandHandler('hilfe', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('start', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('bericht', self.reportHandler))
        self.updater.dispatcher.add_handler(CommandHandler('ort', self.currentHandler))
        self.updater.dispatcher.add_handler(CommandHandler('abo', self.subscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('beende', self.unsubscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('statistik', self.statHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.command, self.unknownHandler))
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
                                  f'Diesen Hilfetext erhältst du über /hilfe.')
        self.log.debug("Someone called /hilfe")

    def currentHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        message = self._bot.get_current(entity)
        update.message.reply_html(message)
        self.log.debug("Someone called /ort")

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

    def directMessageHandler(self, update: Update, context: CallbackContext) -> None:
        text, markup = self.genButtonMessage(update.message.text, update.effective_chat.id)
        if markup is None:
            update.message.reply_html(text)
        else:
            update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

    def genButtonMessage(self, county: str, user_id: int) -> (str, InlineKeyboardMarkup):
        locations = self._bot.data.find_rs(county)
        if locations is None or len(locations) == 0:
            return (f"Die Ortsangabe {county} konnte leider nicht zugeordnet werden! "
                    "Hilfe zur Benutzung des Bots gibts über <code>/hilfe</code>", None)
        elif len(locations) == 1:
            buttons = [[InlineKeyboardButton("Bericht", callback_data=self.CALLBACK_CMD_REPORT + locations[0][1])]]
            if locations[0][0] in self._bot.manager.get_subscriptions(user_id):
                buttons.append([InlineKeyboardButton("Beende Abo",
                                                     callback_data=self.CALLBACK_CMD_UNSUBSCRIBE + locations[0][
                                                         1])])
                verb = "beenden"
            else:
                buttons.append([InlineKeyboardButton("Starte Abo",
                                                     callback_data=self.CALLBACK_CMD_SUBSCRIBE + locations[0][1])])
                verb = "starten"
            markup = InlineKeyboardMarkup(buttons)
            return (f"Möchtest du dein Abo von {locations[0][1]} {verb} oder nur den aktuellen Bericht erhalten?",
                    markup)
        else:
            buttons = []
            for rs, county in locations:
                buttons.append([InlineKeyboardButton(county, callback_data=self.CALLBACK_CMD_CHOOSE_ACTION + county)])
            markup = InlineKeyboardMarkup(buttons)
            return "Bitte wähle einen Ort:", markup

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
        try:
            raise context.error
        except Unauthorized:
            logging.warning(f"TelegramError: Unauthorized chat_id {update.message.chat_id}")
            self._bot.manager.delete_user(update.message.chat_id)
        except BadRequest as e:
            logging.warning(f"TelegramError: BadRequest: {update.message.text}: {e}")
        except TimedOut as e:
            logging.warning(f"TelegramError: TimedOut sending {update.message.text}: {e}")
        except NetworkError as e:
            logging.warning(f"TelegramError: NetworkError while sending {update.message.text}: {e}")
        except TelegramError as e:
            logging.warning(f"TelegramError: {e}")
