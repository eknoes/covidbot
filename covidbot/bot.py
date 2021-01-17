from io import BytesIO
import itertools
import logging
import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Optional, Tuple, List, Dict

from covidbot.covid_data import CovidData, DistrictData, TrendValue
from covidbot.subscription_manager import SubscriptionManager


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
                message = "<b>{district_name}</b>\n\n" \
                          "7-Tage-Inzidenz (Anzahl der Infektionen je 100.000 Einwohner:innen):" \
                          " {incidence} {incidence_trend}\n\n" \
                          "Neuinfektionen (seit gestern): {new_cases} {new_cases_trend}\n" \
                          "Infektionen seit Ausbruch der Pandemie: {total_cases}\n\n" \
                          "Neue Todesfälle (seit gestern): {new_deaths} {new_deaths_trend}\n" \
                          "Todesfälle seit Ausbruch der Pandemie: {total_deaths}\n\n" \
                          "<i>Stand: {date}</i>\n" \
                          "<i>Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen " \
                          "findest Du im <a href='https://corona.rki.de/'>Dashboard des RKI</a></i>\n"
                message = message.format(
                    district_name=current_data.name,
                    incidence=self.format_incidence(current_data.incidence),
                    incidence_trend=self.format_data_trend(current_data.incidence_trend),
                    new_cases=self.format_int(current_data.new_cases),
                    new_cases_trend=self.format_data_trend(current_data.cases_trend),
                    total_cases=self.format_int(current_data.total_cases),
                    new_deaths=self.format_int(current_data.new_deaths),
                    new_deaths_trend=self.format_data_trend(current_data.deaths_trend),
                    total_deaths=self.format_int(current_data.total_deaths),
                    date=current_data.date.strftime("%d.%m.%Y"))
                return message
            else:
                return self._handle_wrong_county_key(county_key)
        else:
            return self._handle_no_input()
            
    def get_new_infection_graph(self, county_key: str) -> Optional[BytesIO]:
        if county_key != "":
            possible_rs = self.data.find_rs(county_key)
            if len(possible_rs) == 1:
                rs, county = possible_rs[0]
                history_data = self.data.get_covid_data_history(rs, 14)
                y = []
                for day_data in history_data:
                    y.append(day_data.new_cases)
                x = [datetime.datetime.now() - datetime.timedelta(days=i) for i in range(len(y))]
                fig,ax1 = plt.subplots()
                ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d %B'))
                plt.xticks(x)
                plt.plot(x,y)
                plt.gcf().autofmt_xdate()
                plt.title("Neuinfektionen der letzten " + str(len(y)) + " Tage")
                buf = BytesIO()
                plt.savefig(buf, format='JPEG')
                buf.seek(0)
                plt.clf()
                return buf
            else:
                return None
        else:
            return None

    def subscribe(self, userid: int, county_key: str) -> str:
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
                if self.manager.rm_subscription(int(userid), rs):
                    message = "Dein Abonnement für " + county + " wurde beendet."
                else:
                    message = "Du hast " + county + " nicht abonniert."

                return message
            else:
                return self._handle_wrong_county_key(county_key)

        else:
            return self._handle_no_input()

    def get_report(self, userid: int) -> str:
        subscriptions = self.manager.get_subscriptions(userid)
        country = self.data.get_country_data()
        message = "<b>Corona-Bericht vom {date}</b>\n\n" \
                  "Insgesamt wurden bundesweit {new_cases} Neuinfektionen {new_cases_trend} und " \
                  "{new_deaths} Todesfälle {new_deaths_trend} gemeldet.\n\n"
        message = message.format(date=self.data.get_last_update().strftime("%d.%m.%Y"),
                                 new_cases=self.format_int(country.new_cases),
                                 new_cases_trend=self.format_data_trend(country.cases_trend),
                                 new_deaths=self.format_int(country.new_deaths),
                                 new_deaths_trend=self.format_data_trend(country.deaths_trend))
        if len(subscriptions) > 0:
            message += "Die 7-Tage-Inzidenz (Anzahl der Infektionen je 100.000 Einwohner:innen in den vergangenen 7 " \
                       "Tagen) sowie die Neuinfektionen und Todesfälle seit gestern fallen für die von dir abonnierten " \
                       "Orte wie folgt aus:\n\n"
            # Split Bundeslaender from other
            subscription_data = list(map(lambda rs: self.data.get_covid_data(rs), subscriptions))
            subscribed_bls = list(filter(lambda d: d.type == "Bundesland", subscription_data))
            subscribed_cities = list(filter(lambda d: d.type != "Bundesland", subscription_data))
            if len(subscribed_bls) > 0:
                message += "<b>Bundesländer</b>\n"
                data = map(lambda district: "• " + self.format_district_data(district),
                           self.sort_districts(subscribed_bls))
                message += "\n".join(data) + "\n\n"

            grouped_districts = self.group_districts(subscribed_cities)
            for key in grouped_districts:
                message += "<b>Städte und Landkreise mit Inzidenz >" + str(key) + ":</b>\n"
                data = map(lambda district: "• " + self.format_district_data(district),
                           self.sort_districts(grouped_districts[key]))
                message += "\n".join(data) + "\n\n"
        message += '<i>Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://corona.rki.de/">Dashboard des RKI</a></i>'

        return message

    def delete_user(self, user_id: int) -> str:
        if self.manager.delete_user(user_id):
            return "Deine Daten wurden erfolgreich gelöscht."
        return "Zu deinem Account sind keine Daten vorhanden."

    def format_district_data(self, district: DistrictData) -> str:
        return "{name}: {incidence} {incidence_trend} ({new_cases} Neuinfektionen, {new_deaths} Todesfälle)" \
                .format(name=district.name,
                        incidence=self.format_incidence(district.incidence),
                        incidence_trend=self.format_data_trend(district.incidence_trend),
                        new_cases=self.format_int(district.new_cases),
                        new_deaths=self.format_int(district.new_deaths))

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

    def get_overview(self, userid: int) -> str:
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
            message = "Es wurde <b>keine</b> Ort mit dem Namen " + location + " gefunden!"
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

    def update(self) -> Optional[List[Tuple[int, str]]]:
        """
        Needs to be called once in a while to check for new data. Returns a list of messages to be sent, if new data
        arrived
        :rtype: Optional[list[Tuple[str, str]]]
        :return: List of (userid, message)
        """
        self.log.debug("Checking for new data")
        self.log.info("Current COVID19 data from " + str(self.data.get_last_update()))
        result = []
        data_update = self.data.get_last_update()
        for subscriber in self.manager.get_all_user():
            user_last_update = self.manager.get_last_update(subscriber)
            if user_last_update is None or user_last_update < data_update:
                result.append((subscriber, self.get_report(subscriber)))
                self.manager.set_last_update(subscriber, data_update)
        if len(result) > 0:
            return result

        if self.data.fetch_current_data():
            return self.update()
        return result

    def get_statistic(self) -> str:
        message = f"Aktuell nutzen {self.manager.get_total_user()} Personen diesen Bot.\n\n" \
                  f"Die fünf beliebtesten Orte sind:\n"
        for county in self.manager.get_ranked_subscriptions()[:5]:
            message += f"• {county[0]} Abonnements: {county[1]}\n"
        return message

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

    @staticmethod
    def format_data_trend(value: TrendValue) -> str:
        if value == TrendValue.UP:
            return "↗"
        elif value == TrendValue.SAME:
            return "➡"
        elif value == TrendValue.DOWN:
            return "↘"
        else:
            return ""
