import logging

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters

from covid_bot import CovidBot
from subscription_manager import SubscriptionManager
from covid_data import CovidData

'''
Telegram Aktionen:
hilfe - Infos zur Benutzung
ort - Aktuelle Zahlen für den Ort
abo - Abonniere Ort
beende - Widerrufe Abonnement 
bericht - Aktueller Bericht
'''

class TelegramBot(object):
    _bot: CovidBot

    def __init__(self, bot: CovidBot):
        self._bot = bot

        # Initialize Telegram
        with open(".api_key", "r") as f:
            key = f.readline()

        self.updater = Updater(key)

        self.updater.dispatcher.add_handler(CommandHandler('hilfe', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('start', self.helpHandler))
        self.updater.dispatcher.add_handler(CommandHandler('bericht', self.reportHandler))
        self.updater.dispatcher.add_handler(CommandHandler('ort', self.currentHandler))
        self.updater.dispatcher.add_handler(CommandHandler('abo', self.subscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('beende', self.unsubscribeHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.command, self.unknownHandler))

    def helpHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_text(self._bot.get_help(update.effective_user.first_name))

    def currentHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        update.message.reply_text(self._bot.get_current(entity))

    def subscribeHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        update.message.reply_text(self._bot.subscribe(str(update.effective_chat.id), entity))

    def unsubscribeHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        update.message.reply_text(self._bot.unsubscribe(str(update.effective_chat.id), entity))

    def reportHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_text(self._bot.get_report(str(update.effective_chat.id)))

    def overviewHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_text(self._bot.get_overview(str(update.effective_chat.id)))

    def unknownHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_text(self._bot.unknown_action())

    def run(self):
        self.updater.start_polling()
        self.updater.idle()


if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO, filename="bot.log")
    # Initialize Data
    bot = TelegramBot(CovidBot(CovidData("data.csv"), SubscriptionManager("user.json")))
    bot.run()
