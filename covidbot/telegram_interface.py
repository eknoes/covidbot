import logging
import time

import telegram
from telegram import Update, ParseMode
from telegram.error import BadRequest, TelegramError, Unauthorized, TimedOut, NetworkError, ChatMigrated
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters

from covidbot.bot import Bot

'''
Telegram Aktionen:
hilfe - Infos zur Benutzung
ort - Aktuelle Zahlen für den Ort
abo - Abonniere Ort
beende - Widerrufe Abonnement
bericht - Aktueller Bericht
'''


class TelegramInterface(object):
    _bot: Bot
    log = logging.getLogger(__name__)

    def __init__(self, bot: Bot, api_key: str):
        self._bot = bot

        self.updater = Updater(api_key)

        self.updater.dispatcher.add_handler(CommandHandler('hilfe', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('start', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('bericht', self.reportHandler))
        self.updater.dispatcher.add_handler(CommandHandler('ort', self.currentHandler))
        self.updater.dispatcher.add_handler(CommandHandler('abo', self.subscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('beende', self.unsubscribeHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.command, self.unknownHandler))
        self.updater.dispatcher.add_error_handler(self.error_callback)
        self.updater.job_queue.run_repeating(self.updateHandler, interval=1300, first=10)

    def helpHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_html(f'Hallo {update.effective_user.first_name},\n'
                                  f'über diesen Bot kannst du die vom RKI bereitgestellten COVID19-Daten '
                                  f'abonnieren.\n\n '
                                  f'Mit der <code>/abo</code> Aktion kannst du die Zahlen für einen Ort '
                                  f'abonnieren. Probiere bspw. <code>/abo Berlin</code> aus. '
                                  f'Mit der <code>/beende</code> Aktion kannst du dieses Abonnement widerrufen. '
                                  f'Du bekommst dann täglich deinen persönlichen Tagesbericht direkt nach '
                                  f'Veröffentlichung neuer Zahlen. Möchtest du den aktuellen Bericht abrufen, '
                                  f'ist dies mit <code>/bericht</code> möglich.\n\n '
                                  f'\n\n'
                                  f'Aktuelle Zahlen bekommst du mit <code>/ort</code>, bspw. <code>/ort '
                                  f'Berlin</code>. '
                                  f'\n\n'
                                  f'Mehr Informationen zu diesem Bot findest du hier: '
                                  f'https://github.com/eknoes/covid-bot\n\n'
                                  f'Diesen Hilfetext erhältst du über <code>/hilfe</code>.')
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
        except BadRequest:
            logging.warning(f"TelegramError: BadRequest: {update.message.text}")
        except TimedOut:
            logging.warning(f"TelegramError: TimedOut sending {update.message.text}")
        except NetworkError:
            logging.warning(f"TelegramError: NetworkError while sending {update.message.text}")
        except TelegramError as e:
            logging.warning(f"TelegramError: {e}")
