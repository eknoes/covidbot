import logging

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters

from subscription_manager import SubscriptionManager
from covid_data import CovidData


class CovidBot(object):
    data: CovidData
    manager: SubscriptionManager

    def __init__(self, covid_data: CovidData, subscription_manager: SubscriptionManager):
        self.data = covid_data
        self.manager = subscription_manager

    @staticmethod
    def get_help(name: str) -> str:
        return (f'Hallo {name},\n'
                f'über diesen Bot kannst du die vom RKI bereitgestellten Covid-Daten abonnieren.\n\n'
                f'Mit der /abo Aktion kannst du die Zahlen für einen Ort '
                f'abonnieren. Probiere bspw. /abo Heidelberg aus. '
                f'Mit der /beende Aktion kannst du dieses Abonnement widerrufen. '
                f'Du bekommst dann täglich deinen persönlichen Tagesbericht direkt nach '
                f'Veröffentlichung neuer Zahlen. Möchtest du den aktuellen Bericht abrufen, '
                f'ist dies mit /bericht möglich.\n\n '
                f'\n\n'
                f'Aktuelle Zahlen bekommst du mit der /ort Aktion, bspw. /ort Heidelberg.'
                f'\n\n'
                f'Mehr Informationen zu diesem Bot findest du hier: '
                f'https://github.com/eknoes/covid-bot\n\n'
                f'Diesen Hilfetext erhältst du über /hilfe.')

    def get_current(self, county_key: str) -> str:
        if county_key != "":
            possible_rs = self.data.find_rs(county_key)
            if len(possible_rs) == 1:
                rs, county = possible_rs[0]
                message = "Die Inzidenz der letzten 7 Tage / 100.000 Einwohner beträgt:\n"
                message += county + ": " + self.data.get_7day_incidence(rs)
                return message
            else:
                return self._handle_wrong_county_key(county_key)
        else:
            return self._handle_no_input()

    def subscribe(self, userid: str, county_key: str) -> str:
        if county_key != "":
            possible_rs = self.data.find_rs(county_key)
            if len(possible_rs) == 1:
                rs, county = possible_rs[0]
                if self.manager.add_subscription(userid, rs):
                    message = "Dein Abonnement für " + county + " wurde erstellt."
                else:
                    message = "Du hast " + county + " bereits abonniert."

                return message
            else:
                return self._handle_wrong_county_key(county_key)

        else:
            return self.get_overview(userid)

    def unsubscribe(self, userid: str, county_key: str) -> str:
        if county_key != "":
            possible_rs = self.data.find_rs(county_key)
            if len(possible_rs) == 1:
                rs, county = possible_rs[0]
                if self.manager.rm_subscription(userid, rs):
                    message = "Dein Abonnement für " + county + " wurde beendet."
                else:
                    message = "Du hast " + county + " nicht abonniert."

                return message
            else:
                return self._handle_wrong_county_key(county_key)

        else:
            self._handle_no_input()

    def get_report(self, userid: str) -> str:
        subscriptions = self.manager.get_subscriptions(userid)
        if len(subscriptions) > 0:
            data = map(lambda x: self.data.get_rs_name(x) + ": " + self.data.get_7day_incidence(x), subscriptions)
            message = "Die 7 Tage Inzidenz / 100.000 Einwohner beträgt:\n\n" + "\n".join(data) + "\n\n" \
                                                                                                 "Daten vom Robert Koch-Institut (RKI), dl-de/by-2-0 vom " + self.data.get_last_update()
        else:
            message = "Du hast aktuell keine Abonemments!"
        return message

    def get_overview(self, userid: str) -> str:
        subscriptions = self.manager.get_subscriptions(userid)
        if subscriptions is None or len(subscriptions) == 0:
            message = "Du hast aktuell keine Orte abonniert. Mit /abo kannst du Orte abonnieren, bspw. /abo Dresden"
        else:
            counties = map(self.data.get_rs_name, subscriptions)
            message = "Du hast aktuell " + str(len(subscriptions)) + " Orte abonniert: \n" + ", ".join(counties)
        return message

    def _handle_wrong_county_key(self, location: str) -> str:
        """
        Return Identifier or clarification message for certain location string. :param location: Location that should
        be identified :return: (bool, str): Boolean shows whether identifier was found, str is then identifier.
        Otherwise it is a message that should be sent to the user
        """
        possible_rs = self.data.find_rs(location)
        if not possible_rs:
            message = "Es wurde keine Ort mit dem Namen " + location + " gefunden!"
        elif 1 < len(possible_rs) <= 15:
            message = "Es wurden mehrere Orte mit diesem oder ähnlichen Namen gefunden:\n"
            message += ", ".join(list(map(lambda t: t[1], possible_rs)))
        else:
            message = "Mit deinem Suchbegriff wurden mehr als 15 Orte gefunden, bitte versuche spezifischer zu sein."

        return message

    @staticmethod
    def _handle_no_input() -> str:
        return f'Diese Aktion benötigt eine Ortsangabe.'

    @staticmethod
    def unknown_action() -> str:
        return (
            "Dieser Befehl wurde nicht verstanden. Nutze /hilfe um einen Überblick über die Funktionen"
            "zu bekommen!")
