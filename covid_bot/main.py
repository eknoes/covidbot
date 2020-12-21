import logging

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters

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
    data: CovidData
    manager: SubscriptionManager

    def __init__(self, covid_data: CovidData, subscription_manager: SubscriptionManager):
        self.data = covid_data
        self.manager = subscription_manager

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

    @staticmethod
    def helpHandler(update: Update, context: CallbackContext) -> None:
        update.message.reply_text(f'Hallo {update.effective_user.first_name},\n'
                                  f'über diesen Bot kannst du die vom RKI bereitgestellten Covid-Daten abonnieren.\n\n'
                                  f'Mit der /abo Aktion kannst du die Zahlen für einen Ort '
                                  f'abonnieren. Probiere bspw. /abo Heidelberg aus. '
                                  f'Mit der /beende Aktion kannst du dieses Abonemment widerrufen. '
                                  f'Du bekommst dann täglich deinen persönlichen Tagesbericht direkt nach '
                                  f'Veröffentlichung neuer Zahlen. Möchtest du den aktuellen Bericht abrufen, '
                                  f'ist dies mit /bericht möglich.\n\n '
                                  f'\n\n'
                                  f'Aktuelle Zahlen bekommst du mit der /ort Aktion, bspw. /ort Heidelberg.'
                                  f'\n\n'
                                  f'Mehr Informationen zu diesem Bot findest du hier: '
                                  f'https://github.com/eknoes/covid-bot\n\n'
                                  f'Diesen Hilfetext erhälst du über /hilfe.')

    def currentHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        if entity != "":
            possible_rs = self.data.find_rs(entity)
            if len(possible_rs) == 1:
                rs, county = possible_rs[0]
                message = "Die Inzidenz der letzten 7 Tage / 100.000 Einwohner beträgt:\n"
                message += county + ": " + self.data.get_7day_incidence(rs)
                context.bot.send_message(chat_id=update.effective_chat.id,
                                         text=message)
            else:
                self.handleInaccurateLocation(entity, update, context)
        else:
            self.handleNoInput(update)

    def subscribeHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        if entity != "":
            possible_rs = self.data.find_rs(entity)
            if len(possible_rs) == 1:
                rs, county = possible_rs[0]
                if self.manager.add_subscription(update.effective_chat.id, rs):
                    message = "Dein Abonnement für " + county + " wurde erstellt."
                else:
                    message = "Du hast " + county + " bereits abonniert."

                context.bot.send_message(chat_id=update.effective_chat.id, text=message)
            else:
                self.handleInaccurateLocation(entity, update, context)

        else:
            self.overviewHandler(update, context)

    def unsubscribeHandler(self, update: Update, context: CallbackContext) -> None:
        entity = " ".join(context.args)
        if entity != "":
            possible_rs = self.data.find_rs(entity)
            if len(possible_rs) == 1:
                rs, county = possible_rs[0]
                if self.manager.rm_subscription(update.effective_chat.id, rs):
                    message = "Dein Abonnement für " + county + " wurde beendet."
                else:
                    message = "Du hast " + county + " nicht abonniert."

                context.bot.send_message(chat_id=update.effective_chat.id, text=message)
            else:
                self.handleInaccurateLocation(entity, update, context)

        else:
            self.handleNoInput(update)

    def reportHandler(self, update: Update, context: CallbackContext) -> None:
        subscriptions = self.manager.get_subscriptions(update.effective_chat.id)
        if len(subscriptions) > 0:
            data = map(lambda x: self.data.get_rs_name(x) + ": " + self.data.get_7day_incidence(x), subscriptions)
            message = "Die 7 Tage Inzidenz / 100.000 Einwohner beträgt:\n\n" + "\n".join(data) + "\n\n" \
                      "Daten vom Robert Koch-Institut (RKI), dl-de/by-2-0 vom " + self.data.get_last_update()
        else:
            message = "Du hast aktuell keine Abonemments!"
        context.bot.send_message(chat_id=update.effective_chat.id, text=message)

    def overviewHandler(self, update: Update, context: CallbackContext) -> None:
        subscriptions = self.manager.get_subscriptions(update.effective_chat.id)
        if subscriptions is None or len(subscriptions) == 0:
            message = "Du hast aktuell keine Orte abonniert. Mit /abo kannst du Orte abonnieren, bspw. /abo Dresden"
        else:
            counties = map(self.data.get_rs_name, subscriptions)
            message = "Du hast aktuell " + str(len(subscriptions)) + " Orte abonniert: \n" + ", ".join(counties)
        context.bot.send_message(chat_id=update.effective_chat.id, text=message)

    def handleInaccurateLocation(self, location: str, update: Update, context: CallbackContext) -> None:
        """
        Return Identifier or clarification message for certain location string. :param location: Location that should
        be identified :return: (bool, str): Boolean shows whether identifier was found, str is then identifier.
        Otherwise it is a message that should be sent to the user
        """
        possible_rs = self.data.find_rs(location)
        if not possible_rs:
            message = "Es wurde keine Ort mit dem Namen " + location + " gefunden!"
        elif 1 < len(possible_rs) <= 10:
            message = "Es wurden mehrere Orte mit diesem oder ähnlichen Namen gefunden:\n"
            message += ", ".join(list(map(lambda t: t[1], possible_rs)))
        else:
            message = "Mit deinem Suchbegriff wurden mehr als 10 Orte gefunden, bitte versuche spezifischer zu sein."

        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=message)

    @staticmethod
    def handleNoInput(update: Update):
        update.message.reply_text(f'Diese Aktion benötigt eine Ortsangabe.')

    @staticmethod
    def unknownHandler(update: Update, context: CallbackContext) -> None:
        update.message.reply_text(
            "Dieser Befehl wurde nicht verstanden. Nutze /hilfe um einen Überblick über die Funktionen"
            "zu bekommen!")

    def run(self):
        self.updater.start_polling()
        self.updater.idle()


if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO, filename="bot.log")
    # Initialize Data
    data = CovidData("data.csv")
    manager = SubscriptionManager("user.json")
    bot = TelegramBot(data, manager)
    bot.run()
