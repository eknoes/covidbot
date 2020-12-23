import logging
from typing import Optional, Tuple, List

from covidbot.subscription_manager import SubscriptionManager
from covidbot.covid_data import CovidData


class Bot(object):
    data: CovidData
    manager: SubscriptionManager

    def __init__(self, covid_data: CovidData, subscription_manager: SubscriptionManager):
        self.log = logging.getLogger(__name__)
        self.data = covid_data
        self.manager = subscription_manager

    def get_current(self, county_key: str) -> str:
        if county_key != "":
            possible_rs = self.data.find_rs(county_key)
            if len(possible_rs) == 1:
                rs, county = possible_rs[0]
                message = "Die 7-Tage-Inzidenz (Anzahl der Infektionen je 100.000 Einwohner:innen) beträgt:\n"
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
            return self._handle_no_input()

    def get_report(self, userid: str) -> str:
        subscriptions = self.manager.get_subscriptions(userid)
        if len(subscriptions) > 0:
            message = "Es sind neue Inzidenzwerte verfügbar!\n\n"
            data = map(lambda x: "• " + self.data.get_rs_name(x) + ": " + self.data.get_7day_incidence(x),
                       subscriptions)
            message += "Die 7-Tage-Inzidenz (Anzahl der Infektionen je 100.000 Einwohner:innen) beträgt:\n\n" + "\n".join(data) + "\n\n" \
                       "<i>Daten vom Robert Koch-Institut (RKI), dl-de/by-2-0 vom "\
                       + self.data.get_last_update().strftime("%d.%m.%Y, %H:%M Uhr") + "</i>"
        else:
            message = "Du hast aktuell keine Abonnements!"
        return message

    def get_overview(self, userid: str) -> str:
        subscriptions = self.manager.get_subscriptions(userid)
        if subscriptions is None or len(subscriptions) == 0:
            message = "Du hast aktuell <b>keine</b> Orte abonniert. Mit <code>/abo</code> kannst du Orte abonnieren, " \
                      "bspw. <code>/abo Dresden</code> "
        else:
            counties = map(self.data.get_rs_name, subscriptions)
            message = "Du hast aktuell <b>" + str(len(subscriptions)) + "</b> Orte abonniert: \n" + ", ".join(counties)
        return message

    def _handle_wrong_county_key(self, location: str) -> str:
        """
        Return Identifier or clarification message for certain location string. :param location: Location that should
        be identified :return: (bool, str): Boolean shows whether identifier was found, str is then identifier.
        Otherwise it is a message that should be sent to the user
        """
        possible_rs = self.data.find_rs(location)
        if not possible_rs:
            message = "Es wurde <b>keine<b> Ort mit dem Namen " + location + " gefunden!"
        elif 1 < len(possible_rs) <= 15:
            message = "Es wurden mehrere Orte mit diesem oder ähnlichen Namen gefunden:\n"
            message += "\n".join(list(map(lambda t: "• " + t[1], possible_rs)))
        else:
            message = "Mit deinem Suchbegriff wurden mehr als 15 Orte gefunden, bitte versuche spezifischer zu sein."

        return message

    @staticmethod
    def _handle_no_input() -> str:
        return 'Diese Aktion benötigt eine Ortsangabe.'

    @staticmethod
    def unknown_action() -> str:
        return ("Dieser Befehl wurde nicht verstanden. Nutze <code>/hilfe</code> um einen Überblick über die Funktionen"
                "zu bekommen!")

    def update(self) -> Optional[List[Tuple[str, str]]]:
        """
        Needs to be called once in a while to check for new data. Returns a list of messages to be sent, if new data
        arrived
        :rtype: Optional[list[Tuple[str, str]]]
        :return: List of (userid, message)
        """
        self.log.debug("Checking for new data")
        if self.manager.get_last_update() is None or self.data.get_last_update() > self.manager.get_last_update():
            self.log.info("New COVID19 data available from " + self.data.get_last_update().isoformat())
            result = []
            for subscriber in self.manager.get_subscribers():
                result.append((subscriber, self.get_report(subscriber)))
            self.manager.set_last_update(self.data.get_last_update())
            return result

        if self.data.fetch_current_data():
            return self.update()
        return []
