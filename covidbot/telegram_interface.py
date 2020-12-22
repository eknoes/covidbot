import logging

from telegram import Update
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
        self.updater.job_queue.run_repeating(self.updateHandler, interval=1300, first=10)

    @staticmethod
    def helpHandler(update: Update, context: CallbackContext) -> None:
        update.message.reply_markdown_v2(f'Hallo {update.effective_user.first_name},\n'
                                         f'über diesen Bot kannst du die vom RKI bereitgestellten Covid-Daten abonnieren.\n\n'
                                         f'Mit der `/abo` Aktion kannst du die Zahlen für einen Ort '
                                         f'abonnieren. Probiere bspw. `/abo Berlin` aus. '
                                         f'Mit der `/beende` Aktion kannst du dieses Abonnement widerrufen. '
                                         f'Du bekommst dann täglich deinen persönlichen Tagesbericht direkt nach '
                                         f'Veröffentlichung neuer Zahlen. Möchtest du den aktuellen Bericht abrufen, '
                                         f'ist dies mit `/bericht` möglich.\n\n '
                                         f'\n\n'
                                         f'Aktuelle Zahlen bekommst du mit `/ort`, bspw. `/ort Berlin`.'
                                         f'\n\n'
                                         f'Mehr Informationen zu diesem Bot findest du hier: '
                                         f'https://github.com/eknoes/covid-bot\n\n'
                                         f'Diesen Hilfetext erhältst du über `/hilfe`.')

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

    def updateHandler(self, context: CallbackContext) -> None:
        messages = self._bot.update()
        if not messages:
            return

        for userid, message in messages:
            context.bot.send_message(chat_id=userid, text=message)
            logging.info("Sent report to " + userid)

    def run(self):
        self.updater.start_polling()
        self.updater.idle()
