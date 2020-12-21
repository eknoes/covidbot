from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters

from covid_data import CovidData

'''
Telegram Aktionen:
info - Infos zur Benutzung
ort - Aktuelle Zahlen für den Ort
abonniere - Abonniere Ort
kündige - Widerrufe Abonemment 
'''


class TelegramBot(object):

    def __init__(self, data: CovidData):
        self.data = data

        # Initialize Telegram
        with open(".api_key", "r") as f:
            key = f.readline()

        self.updater = Updater(key)

        self.updater.dispatcher.add_handler(CommandHandler('info', self.infoHandler))
        self.updater.dispatcher.add_handler(CommandHandler('start', self.infoHandler))
        self.updater.dispatcher.add_handler(CommandHandler('ort', self.currentHandler))
        self.updater.dispatcher.add_handler(CommandHandler('abo', self.subscribeHandler))
        self.updater.dispatcher.add_handler(CommandHandler('beende', self.unsubscribeHandler))
        self.updater.dispatcher.add_handler(MessageHandler(Filters.command, self.unknownHandler))

    @staticmethod
    def infoHandler(update: Update, context: CallbackContext) -> None:
        update.message.reply_text(f'Hallo {update.effective_user.first_name},\n'
                                  f'über diesen Bot kannst du die vom RKI bereitgestellten Covid-Daten abonnieren.\n\n'
                                  f'Mit der /abo Aktion kannst du die Zahlen für einen Ort '
                                  f'abonnieren. Probiere bspw. /abo Heidelberg aus.'
                                  f'Mit der /beende Aktion kannst du dieses Abonemment widerrufen.'
                                  f'Aktuelle Zahlen bekommst du mit der /ort Aktion, bspw. /ort Heidelberg.'
                                  f'\n\n'
                                  f'Du bekommst dann täglich deinen persönlichen RKI Tagesbericht, direkt nach '
                                  f'Veröffentlichung neuer Zahlen.\n\n'
                                  f'Diesen Hilfetext erhälst du über /info.')

    def currentHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        if context.args is not []:
            possible_ags = data.find_ags(entity)
            if not possible_ags:
                message = "Es wurde keine Kommune mit dem Namen " + entity + " gefunden!"
            elif len(possible_ags) > 1 and len(possible_ags) <= 10:
                message = "Es wurden mehrere Kommunen mit diesem oder einem Ähnlichen Namen gefunden:\n"
                message += ", ".join(list(map(lambda t: t[1], possible_ags)))
            elif len(possible_ags) > 10:
                message = "Mit deinem Suchbegriff wurden mehr als 10 Kommunen gefunden, bitte versuche spezifischer zu sein."
            else:
                ags, county = possible_ags[0]
                message = "Die Inzidenz der letzten 7 Tage / 100.000 Einwohner beträgt:\n"
                message += county + ": " + self.data.get_7day_incidence(ags)

            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=message)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text='Bitte gib einen Ort an!')

    def subscribeHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_text(f'Diese Funktion ist noch nicht implementiert.')

    def unsubscribeHandler(self, update: Update, context: CallbackContext) -> None:
        update.message.reply_text(f'Diese Funktion ist noch nicht implementiert.')

    @staticmethod
    def unknownHandler(update: Update, context: CallbackContext) -> None:
        update.message.reply_text(
            "Dieser Befehl wurde nicht verstanden. Nutze /info um einen Überblick über die Funktionen"
            "zu bekommen!")

    def run(self):
        self.updater.start_polling()
        self.updater.idle()


if __name__ == "__main__":
    # Initialize Data
    data = CovidData("data.csv")
    bot = TelegramBot(data)
    bot.run()
