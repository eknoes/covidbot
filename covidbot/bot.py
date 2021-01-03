import itertools
import logging
from typing import Optional, Tuple, List, Dict

from covidbot.subscription_manager import SubscriptionManager
from covidbot.covid_data import CovidData, DistrictData


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
                current_data = self.data.get_covid_data(rs)
                message = "<b>" + current_data.name + "</b>\n\n"
                message += "7-Tage-Inzidenz (Anzahl der Infektionen je 100.000 Einwohner:innen): " \
                           + self.format_incidence(current_data.incidence) + "\n\n"
                message += "Neuinfektionen (seit gestern): " + self.format_int(current_data.new_cases) + "\n"
                message += "Infektionen seit Ausbruch der Pandemie: " + self.format_int(
                    current_data.total_cases) + "\n\n"
                message += "Neue Todesfälle (seit gestern): " + self.format_int(current_data.new_deaths) + "\n"
                message += "Todesfälle seit Ausbruch der Pandemie: " + self.format_int(
                    current_data.total_deaths) + "\n\n"
                message += '<i>Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen ' \
                           'findest Du im <a href="https://corona.rki.de/">Dashboard des RKI</a></i>\n'
                message += "<i>Stand: " \
                           + self.data.get_last_update().strftime("%d.%m.%Y, %H:%M Uhr") + "</i>"
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
        country = self.data.get_country_data()
        message = "<b>Corona-Bericht vom " \
                  + self.data.get_last_update().strftime("%d.%m.%Y") + "</b>\n\n"
        message += "Insgesamt wurden bundesweit " + self.format_int(country.new_cases) \
                   + " Neuinfektionen und " + self.format_int(country.new_deaths) + " Todesfälle gemeldet.\n\n"
        if len(subscriptions) > 0:
            message += "7-Tage-Inzidenz (Anzahl der Infektionen je 100.000 Einwohner:innen):\n\n"
            grouped_districts = self.group_districts(list(map(lambda rs: self.data.get_covid_data(rs), subscriptions)))
            for key in grouped_districts:
                message += "<b>Inzidenz >" + str(key) + ":</b>\n"
                data = map(lambda district: "• " + district.name + ": " + self.format_incidence(district.incidence)
                                            + " (" + self.format_int(district.new_cases) + " Neuinfektionen, " +
                                            self.format_int(district.new_deaths) + " Todesfälle)",
                           self.sort_districts(grouped_districts[key]))
                message += "\n".join(data) + "\n\n"
        message += '<i>Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://corona.rki.de/">Dashboard des RKI</a></i>'

        return message

    @staticmethod
    def sort_districts(districts: List[DistrictData]) -> List[DistrictData]:
        districts.sort(key=lambda d: d.name)
        return districts

    @staticmethod
    def group_districts(districts: List[DistrictData]) -> Dict[int, List[DistrictData]]:
        """
        Groups a list of districts according to incidence thresholds
        :param districts: List of Districts
        :rtype: Dict[int, List[DistrictData]]: Districts grouped by thresholds, e.g. {0: [], 35: [], 50: [], 100: [], 200: []
        """
        result = dict()
        groups = [200, 100, 50, 35, 0]
        already_sorted = []
        for group in groups:
            for district in districts:
                already_sorted = list(itertools.chain.from_iterable(result.values()))

                if district not in already_sorted and district.incidence > group:
                    if group not in result:
                        result[group] = []

                    result[group].append(district)

        # Add remaining to 0-group
        if len(districts) != len(already_sorted):
            if 0 not in result:
                result[0] = []

            for d in districts:
                if d not in already_sorted:
                    result[0].append(d)

        return result

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
            self.log.info("New COVID19 data available from " + str(self.data.get_last_update()))
            result = []
            for subscriber in self.manager.get_subscribers():
                result.append((subscriber, self.get_report(subscriber)))
            self.manager.set_last_update(self.data.get_last_update())
            return result

        if self.data.fetch_current_data():
            return self.update()
        return []

    @staticmethod
    def format_incidence(incidence: float) -> str:
        if incidence is not None:
            return "{0:.2f}".format(float(incidence)).replace(".", ",")
        return "Keine Daten"

    @staticmethod
    def format_int(number: int) -> str:
        if number is not None:
            return "{:,}".format(number).replace(",", ".")
        return "Keine Daten"
