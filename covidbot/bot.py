import datetime
import logging
import re
from enum import Enum
from io import BytesIO
from typing import Optional, Tuple, List, Dict, Union

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from covidbot.covid_data import CovidData, DistrictData
from covidbot.location_service import LocationService
from covidbot.user_manager import UserManager, BotUser
from covidbot.utils import format_data_trend, format_int, format_float


class UserDistrictActions(Enum):
    SUBSCRIBE = 0
    UNSUBSCRIBE = 1
    REPORT = 2


class Bot(object):
    _data: CovidData
    _manager: UserManager
    _location_service: LocationService
    DEFAULT_LANG = "de"
    command_format: str
    location_feature: bool = False

    def __init__(self, covid_data: CovidData, subscription_manager: UserManager, command_format="/{command}",
                 location_feature=False):
        self.log = logging.getLogger(__name__)
        self._data = covid_data
        self._manager = subscription_manager
        self._location_service = LocationService('resources/germany_rs.geojson')
        self.command_format = command_format
        self.location_feature = location_feature

    def is_user_activated(self, user_identification: Union[int, str]) -> bool:
        user_id = self._manager.get_user_id(user_identification)
        if user_id:
            return self._manager.get_user(user_id).activated
        return False

    def set_language(self, user_identification: Union[int, str], language: Optional[str]) -> str:
        user_id = self._manager.get_user_id(user_identification)
        if not language:
            user = self._manager.get_user(user_id)
            if user and user.language:
                language = user.language
            else:
                language = self.DEFAULT_LANG
            return "Deine aktuelle Spracheinstellung ist {language}".format(language=language)
        if self._manager.set_language(user_id, language):
            return "Deine bevorzugte Sprache wurde auf {language} gesetzt.".format(language=language)
        return "Leider konnte deine Sprache nicht auf {language} gesetzt werde.".format(language=language)

    def find_district_id(self, district_query: str) -> Tuple[Optional[str], Optional[List[Tuple[int, str]]]]:
        if not district_query:
            return 'Dieser Befehl benötigt eine Ortsangabe', None

        possible_district = self._data.search_district_by_name(district_query)
        online_match = False

        query_regex = re.compile("^[\w,()\- ]*$")
        # If e.g. emojis or ?!. are part of query, we do not have to query online
        if not possible_district and query_regex.match(district_query):
            online_match = True
            osm_results = self._location_service.find_location(district_query)
            possible_district = []
            for d in osm_results:
                possible_district.append((d, self._data.get_district(d).name))

        if not possible_district:
            message = 'Leider konnte kein Ort gefunden werden. Bitte beachte, ' \
                      'dass Daten nur für Orte innerhalb Deutschlands verfügbar sind.'.format(location=district_query)
            return message, None
        elif len(possible_district) == 1:
            return None, possible_district
        elif 1 < len(possible_district) <= 15:
            if online_match:
                message = "Für {district} stellt das RKI leider keine spezifischen Daten zur Verfügung. " \
                          "Du kannst stattdessen die Zahlen des dazugehörigen Landkreises abrufen" \
                    .format(district=district_query)
            else:
                message = "Es wurden mehrere Orte mit diesem oder ähnlichen Namen gefunden"
            return message, possible_district
        else:
            message = "Mit deinem Suchbegriff wurden mehr als 15 Orte gefunden, bitte versuche spezifischer zu sein."
            return message, None

    def find_district_id_from_geolocation(self, lon, lat) -> Tuple[Optional[str], Optional[List[Tuple[int, str]]]]:
        district_id = self._location_service.find_rs(lon, lat)
        # ToDo: Also return parent locations
        if not district_id:
            return ('Leider konnte kein Ort in den RKI Corona Daten zu {location} gefunden werden. Bitte beachte, '
                    'dass Daten nur für Orte innerhalb Deutschlands verfügbar sind.'.format(location="deinem Standort"),
                    None)
        else:
            name = self._data.get_district(district_id).name
            return None, [(district_id, name)]

    def get_possible_actions(self, user_identification: Union[int, str], district_id: int) -> Tuple[
        str, List[Tuple[str, UserDistrictActions]]]:
        actions = [("Daten anzeigen", UserDistrictActions.REPORT)]
        district = self._data.get_district(district_id)
        user_id = self._manager.get_user_id(user_identification)

        if district.type != "Staat":
            user = self._manager.get_user(user_id, with_subscriptions=True)
            if user and district_id in user.subscriptions:
                actions.append(("Beende Abo", UserDistrictActions.UNSUBSCRIBE))
                verb = "beenden"
            else:
                actions.append(("Starte Abo", UserDistrictActions.SUBSCRIBE))
                verb = "starten"

            message = "Möchtest du dein Abo von {name} {verb} oder die aktuellen Daten erhalten?" \
                .format(name=district.name, verb=verb)
        else:
            message = "Möchtest du die aktuellen Daten von {name} erhalten?".format(name=district.name)
        return message, actions

    def get_district_report(self, district_id: int) -> str:
        current_data = self._data.get_district_data(district_id)
        message = "<b>{district_name}</b>\n\n"

        message += "<b>🏥 Infektionsdaten</b>\n"
        if current_data.incidence:
            message += "Die 7-Tage-Inzidenz (Anzahl der Infektionen je 100.000 Einwohner:innen) liegt bei {incidence}" \
                       " {incidence_trend}."

        if current_data.r_value:
            message += " Der 7-Tage-R-Wert liegt bei {r_value} {r_trend}." \
                .format(r_value=format_float(current_data.r_value.r_value_7day),
                        r_trend=format_data_trend(current_data.r_value.r_trend))
        message += "\n\n"
        message += "Neuinfektionen (seit gestern): {new_cases} {new_cases_trend}\n" \
                   "Infektionen seit Ausbruch der Pandemie: {total_cases}\n\n" \
                   "Neue Todesfälle (seit gestern): {new_deaths} {new_deaths_trend}\n" \
                   "Todesfälle seit Ausbruch der Pandemie: {total_deaths}\n\n"

        message = message.format(district_name=current_data.name,
                                 incidence=format_float(current_data.incidence),
                                 incidence_trend=format_data_trend(current_data.incidence_trend),
                                 new_cases=format_int(current_data.new_cases),
                                 new_cases_trend=format_data_trend(current_data.cases_trend),
                                 total_cases=format_int(current_data.total_cases),
                                 new_deaths=format_int(current_data.new_deaths),
                                 new_deaths_trend=format_data_trend(current_data.deaths_trend),
                                 total_deaths=format_int(current_data.total_deaths))

        if current_data.vaccinations:
            vacc = current_data.vaccinations
            message += "<b>💉 Impfdaten</b>\n" \
                       "{rate_partial}% der Bevölkerung haben mindestens eine Impfung erhalten, {rate_full}% sind " \
                       "vollständig geimpft.\n\n" \
                       "Verabreichte Erstimpfdosen: {vacc_partial}\n" \
                       "Verabreichte Zweitimpfdosen: {vacc_full}\n" \
                       "Impfdaten vom {vacc_date}\n\n" \
                .format(rate_partial=format_float(vacc.partial_rate * 100),
                        rate_full=format_float(vacc.full_rate * 100),
                        vacc_partial=format_int(vacc.vaccinated_partial),
                        vacc_full=format_int(vacc.vaccinated_full),
                        vacc_date=current_data.vaccinations.date.strftime("%d.%m.%Y"))

        message += '<i>Infektionsdaten vom {date}</i>\n' \
                   '<i>Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://corona.rki.de/">Dashboard des RKI</a> und dem ' \
                   '<a href="https://impfdashboard.de/">Impfdashboard</a>. Sende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten.</i>' \
            .format(info_command=self.format_command("Info"), date=current_data.date.strftime("%d.%m.%Y"))

        return message

    def get_graphical_report(self, district_id: int, subtract_days=0) -> Optional[BytesIO]:
        history_data = self._data.get_district_data(district_id, include_past_days=21, subtract_days=0)
        if not history_data:
            return None

        y = []
        current_date = None
        for day_data in history_data:
            if not current_date or day_data.date > current_date:
                current_date = day_data.date

            if day_data.new_cases is not None:
                y.append(day_data.new_cases)
            else:
                continue
        if not y:
            return None

        x = [current_date - datetime.timedelta(days=i) for i in range(len(y))]

        px = 1 / plt.rcParams['figure.dpi']
        fig, ax1 = plt.subplots(figsize=(900 * px, 600 * px))

        plt.xticks(x)
        plt.bar(x, y, color="#003f5c", width=0.95, zorder=3)

        # Styling
        plt.title("Neuinfektionen seit " + str(len(y) - 1) + " Tagen in {location}"
                  .format(location=history_data[0].name))
        plt.ylabel("Neuinfektionen")
        plt.figtext(0.8, 0.01, "Stand: {date}\nDaten vom Robert Koch-Institut (RKI)"
                    .format(date=current_date.strftime("%d.%m.%Y")), horizontalalignment='left', fontsize=8,
                    verticalalignment="baseline")
        plt.figtext(0.05, 0.01, "Erhalte kostenlos die tagesaktuellen Daten auf Telegram, Signal oder Threema für deine Orte!\n"
                                "https://covidbot.d-64.org/", horizontalalignment='left', fontsize=8,
                    verticalalignment="baseline")

        for direction in ["left", "right", "bottom", "top"]:
            ax1.spines[direction].set_visible(False)
        plt.grid(axis="y", zorder=0)

        # One tick every 7 days for easier comparison
        formatter = mdates.DateFormatter("%a, %d %b")
        ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=current_date.weekday()))
        ax1.xaxis.set_major_formatter(formatter)

        # Save to buffer
        buf = BytesIO()
        plt.savefig(buf, format='JPEG')
        buf.seek(0)
        plt.clf()
        return buf

    def subscribe(self, user_identification: Union[int, str], district_id: int) -> str:
        user_id = self._manager.get_user_id(user_identification)
        if self._manager.add_subscription(user_id, district_id):
            message = "Dein Abonnement für {name} wurde erstellt."
            # Send more on first subscription
            user = self._manager.get_user(user_id, True)
            if len(user.subscriptions) == 1:
                message += " "
                message += (
                    f"Du kannst beliebig viele weitere Orte abonnieren oder Daten einsehen, sende dafür einfach "
                    f"einen weiteren Ort!\n\n"
                    f"Wie du uns Feedback zusenden kannst, Statistiken einsehen oder weitere Aktionen ausführst "
                    f"erfährst du über den {self.format_command('hilfe')} Befehl. "
                    f"Danke, dass du unseren Bot benutzt!")
        else:
            message = "Du hast {name} bereits abonniert."
        return message.format(name=self._data.get_district(district_id).name)

    def unsubscribe(self, user_identification: Union[int, str], district_id: int) -> str:
        user_id = self._manager.get_user_id(user_identification)
        if self._manager.rm_subscription(user_id, district_id):
            message = "Dein Abonnement für {name} wurde beendet."
        else:
            message = "Du hast {name} nicht abonniert."
        return message.format(name=self._data.get_district(district_id).name)

    def get_report(self, user_identification: Union[int, str]) -> str:
        user_id = self._manager.get_user_id(user_identification)
        user = self._manager.get_user(user_id, with_subscriptions=True)
        if not user:
            return self._get_report([])
        return self._get_report(user.subscriptions)

    def _get_report(self, subscriptions: List[int]) -> str:
        country = self._data.get_country_data()
        message = "<b>Corona-Bericht vom {date}</b>\n\n"
        if country.vaccinations:
            message += "<b>💉  Impfdaten</b>\n" \
                       "{vacc_partial} ({rate_partial}%) Personen in Deutschland haben mindestens eine Impfdosis " \
                       "erhalten, {vacc_full} ({rate_full}%) Menschen sind bereits - Stand {date} - vollständig geimpft.\n\n" \
                .format(rate_full=format_float(country.vaccinations.full_rate * 100),
                        rate_partial=format_float(country.vaccinations.partial_rate * 100),
                        vacc_partial=format_int(country.vaccinations.vaccinated_partial),
                        vacc_full=format_int(country.vaccinations.vaccinated_full),
                        date=country.vaccinations.date.strftime("%d.%m.%Y"))

        message += "<b>🦠 Infektionszahlen</b>\n" \
                   "Insgesamt wurden bundesweit {new_cases} Neuinfektionen {new_cases_trend} und " \
                   "{new_deaths} Todesfälle {new_deaths_trend} gemeldet. Die 7-Tage-Inzidenz liegt bei {incidence} " \
                   "{incidence_trend}."
        if country.r_value:
            message += " Der zuletzt gemeldete 7-Tage-R-Wert beträgt {r_value} {r_trend}." \
                .format(r_value=format_float(country.r_value.r_value_7day),
                        r_trend=format_data_trend(country.r_value.r_trend))
        message += "\n\n"
        message = message.format(date=self._data.get_last_update().strftime("%d.%m.%Y"),
                                 new_cases=format_int(country.new_cases),
                                 new_cases_trend=format_data_trend(country.cases_trend),
                                 new_deaths=format_int(country.new_deaths),
                                 new_deaths_trend=format_data_trend(country.deaths_trend),
                                 incidence=format_float(country.incidence),
                                 incidence_trend=format_data_trend(country.incidence_trend))
        if subscriptions and len(subscriptions) > 0:
            message += "Die 7-Tage-Inzidenz sowie die Neuinfektionen und Todesfälle seit gestern fallen für die von " \
                       "dir abonnierten Orte wie folgt aus:\n\n"

            # Split Bundeslaender from other
            subscription_data = list(map(lambda rs: self._data.get_district_data(rs), subscriptions))
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
                   ' im <a href="https://corona.rki.de/">Dashboard des RKI</a> und dem ' \
                   '<a href="https://impfdashboard.de/">Impfdashboard</a>. Sende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten. Ein Service von <a href="d-64.org/">D64 - Zentrum für Digitalen ' \
                   'Fortschritt</a>.</i>'.format(info_command=self.format_command("Info"))

        return message

    def delete_user(self, user_identification: Union[int, str]) -> str:
        user_id = self._manager.get_user_id(user_identification, create_if_not_exists=False)
        if user_id:
            if self._manager.delete_user(user_id):
                return "Deine Daten wurden erfolgreich gelöscht."
        return "Zu deinem Account sind keine Daten vorhanden."

    @staticmethod
    def format_district_data(district: DistrictData) -> str:
        return "{name}: {incidence} {incidence_trend} ({new_cases} Neuinfektionen, {new_deaths} Todesfälle)" \
            .format(name=district.name,
                    incidence=format_float(district.incidence),
                    incidence_trend=format_data_trend(district.incidence_trend),
                    new_cases=format_int(district.new_cases),
                    new_deaths=format_int(district.new_deaths))

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
                if district not in already_sorted and district.incidence > group:
                    if group not in result:
                        result[group] = []

                    result[group].append(district)
                    already_sorted.append(district)

        # Add remaining to 0-group
        if len(districts) != len(already_sorted):
            if 0 not in result:
                result[0] = []

            for d in districts:
                if d not in already_sorted:
                    result[0].append(d)

        return result

    def get_overview(self, user_identification: Union[int, str]) -> Tuple[str, Optional[List[Tuple[int, str]]]]:
        user_id = self._manager.get_user_id(user_identification)
        user = self._manager.get_user(user_id, with_subscriptions=True)
        if not user or not user.subscriptions:
            message = "Du hast aktuell <b>keine</b> Orte abonniert. Mit <code>{subscribe_command}</code> kannst du " \
                      "Orte abonnieren, bspw. <code>{subscribe_command} Dresden</code> " \
                .format(subscribe_command=self.format_command("abo"))
            counties = None
        else:
            counties = list(map(lambda s: (s, self._data.get_district(s).name), user.subscriptions))
            message = "Du hast aktuell <b>{abo_count}</b> Orte abonniert.".format(abo_count=len(user.subscriptions))

        return message, counties

    @staticmethod
    def handle_no_input() -> str:
        return 'Diese Aktion benötigt eine Ortsangabe.'

    def unknown_action(self) -> str:
        return ("Dieser Befehl wurde nicht verstanden. Nutze <code>{help_command}</code> um einen Überblick über die "
                "Funktionen zu bekommen!").format(help_command=self.format_command("hilfe"))

    def get_unconfirmed_daily_reports(self) -> Optional[List[Tuple[Union[int, str], str]]]:
        """
        Needs to be called once in a while to check for new data. Returns a list of messages to be sent, if new data
        arrived
        :rtype: Optional[list[Tuple[str, str]]]
        :return: List of (userid, message)
        """
        result = []
        data_update = self._data.get_last_update()
        for user in self._manager.get_all_user(with_subscriptions=True):
            if not user.activated:
                continue

            if user.last_update is None or user.last_update.date() < data_update:
                result.append((user.platform_id, self._get_report(user.subscriptions)))
        return result

    def confirm_daily_report_send(self, user_identification: Union[int, str]):
        updated = self._data.get_last_update()
        user_id = self._manager.get_user_id(user_identification)
        self._manager.set_last_update(user_id, updated)

    def get_statistic(self) -> str:
        message = "Aktuell nutzen {total_user} Personen diesen Bot, davon "
        messenger_strings = [f"{c} über {m}" for m, c in self._manager.get_users_per_platform()]
        message += ", ".join(messenger_strings[:-1])
        message += f" und {messenger_strings[-1:][0]}.\n\n"

        message += "Die Top 10 der beliebtesten Orte sind:\n"

        i = 1
        for county in self._manager.get_ranked_subscriptions()[:10]:
            if county[0] == 1:
                message += f"{i}. {county[1]} ({county[0]} Abo)\n"
            else:
                message += f"{i}. {county[1]} ({county[0]} Abos)\n"
            i += 1
        message += "\nIm Durchschnitt hat ein:e Nutzer:in {mean} Orte abonniert, " \
                   "die höchste Anzahl an Abos liegt bei {most_subs}."
        message = message.format(total_user=self._manager.get_total_user_number(),
                       mean=format_float(self._manager.get_mean_subscriptions()),
                       most_subs=self._manager.get_most_subscriptions())

        message += "\n\nInformationen zur Nutzung des Bots auf anderen Plattformen findest du unter " \
                   "https://covidbot.d-64.org!"
        return message

    def get_debug_report(self, user_identification: Union[int, str]) -> str:
        uid = self._manager.get_user_id(user_identification, False)
        if not uid:
            return "Für dich sind aktuell keine Debug informationen verfügbar."

        user = self._manager.get_user(uid, with_subscriptions=True)

        return f"<b>Debug Informationen</b>\n" \
               f"platform_id: {user.platform_id}\n" \
               f"user_id: {user.id}\n" \
               f"lang: {user.language}\n" \
               f"last_update: {user.last_update}\n" \
               f"subscriptions: {user.subscriptions}"

    def get_all_user(self) -> List[BotUser]:
        return self._manager.get_all_user()

    def add_user_feedback(self, user_identification: Union[int, str], feedback: str) -> Optional[int]:
        user_id = self._manager.get_user_id(user_identification)
        return self._manager.add_feedback(user_id, feedback)

    def get_privacy_msg(self):
        return ("Unsere Datenschutzerklärung findest du hier: "
                "https://github.com/eknoes/covid-bot/wiki/Datenschutz\n\n"
                f"Außerdem kannst du mit dem Befehl {self.format_command('loeschmich')} alle deine bei uns gespeicherten "
                "Daten löschen.")

    @staticmethod
    def get_error_message():
        return "Leider ist ein unvorhergesehener Fehler aufgetreten. Bitte versuche es erneut."

    @staticmethod
    def no_delete_user():
        return "Deine Daten werden nicht gelöscht."

    def start_message(self, user_identification: Union[str, int], username=""):
        if username:
            username = " " + username
        message = (f'Hallo{username},\n'
                   f'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                   f'COVID19-Daten anzeigen lassen und sie dauerhaft kostenlos abonnieren. '
                   f'Einen Überblick über alle Befehle erhältst du über {self.format_command("Hilfe")}.\n\n'
                   f'Schicke einfach eine Nachricht mit dem Ort, für den Du Informationen erhalten '
                   f'möchtest. Der Ort kann entweder ein Bundesland oder ein Stadt-/ Landkreis sein. ')
        if self.location_feature:
            message += f'Du kannst auch einen Standort senden! '

        message += (
            f'Wenn die Daten des Ortes nur gesammelt für eine übergeordneten Landkreis oder eine Region vorliegen, werden dir diese '
            f'vorgeschlagen. Du kannst beliebig viele Orte abonnieren und unabhängig von diesen '
            f' auch die aktuellen Zahlen für andere Orte ansehen.')
        return message

    def help_message(self, user_identification: Union[str, int], username="") -> str:
        if username:
            username = " " + username

        message = (f'Hallo{username},\n'
                   'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                   'COVID19-Daten anzeigen lassen und sie dauerhaft abonnieren.\n\n'
                   '<b>🔎 Orte finden</b>\n'
                   'Schicke einfach eine Nachricht mit dem Ort, für den Du Informationen erhalten '
                   'möchtest. So kannst du nach einer Stadt, Adresse oder auch dem Namen deiner '
                   'Lieblingskneipe suchen.')
        if self.location_feature:
            message += ' Du kannst auch einen Standort senden.'

        message += ('\n\n'
                    '<b>📈 Informationen erhalten</b>\n'
                    'Wählst du "Bericht" aus, erhältst Du einmalig Informationen über diesen Ort. Diese '
                    'enthalten eine Grafik die für diesen Ort generiert wurde.\n'
                    'Wählst du "Starte Abo" aus, wird dieser Ort in deinem '
                    'morgendlichen Tagesbericht aufgeführt. Hast du den Ort bereits abonniert, wird dir '
                    'stattdessen angeboten, das Abo wieder zu beenden. '
                    'Du kannst beliebig viele Orte abonnieren! '
                    'Sende {info_command} um die Erläuterung zu den verschiedenen Daten und Quellen mit weiteren '
                    'Informationen zu erhalten.'
                    '\n\n'
                    '<b>💬 Feedback</b>\n'
                    'Wir freuen uns über deine Anregungen, Lob & Kritik! Sende dem Bot einfach eine '
                    'Nachricht, du wirst dann gefragt ob diese an uns weitergeleitet werden darf!\n\n'
                    '<b>🤓 Statistik</b>\n'
                    'Wenn du {stat_command} sendest, erhältst du ein Beliebtheitsranking der Orte und ein '
                    'paar andere Daten zu den aktuellen Nutzungszahlen des Bots.\n\n'
                    '<b>Weiteres</b>\n'
                    '• Sende {report_command} um deinen Tagesbericht erneut zu erhalten\n'
                    '• Sende {abo_command} um deine abonnierten Orte einzusehen\n'
                    '• Sende {privacy_command} erhältst du mehr Informationen zum Datenschutz und die '
                    'Möglichkeit, alle deine Daten bei uns zu löschen\n'
                    '• Unter https://covidbot.d-64.org/ findest du Informationen zum Bot und die Links um ihn auf Telegram und Signal zu benutzen'
                    '\n\n'
                    'Mehr Informationen zu diesem Bot findest du hier: '
                    'https://github.com/eknoes/covid-bot\n\n'
                    'Diesen Hilfetext erhältst du über {help_command}') \
            .format(stat_command=self.format_command('Statistik'), report_command=self.format_command('Bericht'),
                    abo_command=self.format_command('Abo'), privacy_command=self.format_command('Datenschutz'),
                    help_command=self.format_command('Hilfe'), info_command=self.format_command('Info'))
        return message

    @staticmethod
    def explain_message() -> str:
        return ("<b>Was bedeuten die Infektionszahlen?</b>\n"
                "Die 7-Tage Inzidenz ist die Anzahl der Covid19-Infektionen in den vergangenen 7 Tagen je 100.000 Einwohner:innen. "
                "Im Gegensatz zu den Neuinfektionszahlen und Todesfällen lässt sich dieser Wert gut täglich vergleichen. "
                "Das liegt daran, dass es ein Wert ist, der sich auf die letzten 7 Tage bezieht und so nicht den tagesabhängigen Schwankungen unterliegt. "
                "Die Neuinfektionszahlen und die Todesfälle lassen sich dahingegen am besten mit den Zahlen von vor einer Woche vergleichen, da diese auf Grund des "
                "Meldeverzugs tagesabhängigen Schwankungen unterliegen. So werden bspw. am Wochenende weniger Zahlen gemeldet."
                "\n\nMehr Informationen zur Bedeutung der Infektionszahlen findest du im <a href='https://www.rki.de/SharedDocs/FAQ/NCOV2019/gesamt.html'>Informationsportal des RKI</a>.\n"
                "\n\n<b>Was bedeuten die Impfzahlen?</b>\n"
                "Bei den aktuell verfügbaren Impfstoffen werden zwei Impfdosen benötigt um einen vollen Schutz zu genießen. "
                "Aus diesem Grund unterscheiden wir zwischen Erst- und Zweitimpfungen. Die Anzahl der Erstimpfungen beinhaltet also auch die Menschen, die bereits eine zweite Impfdosis erhalten haben."
                "\n\nMehr Informationen zu den Impfungen findest du im <a href='https://www.zusammengegencorona.de/impfen/'>Informationsportal der Bundesregierung</a>.\n"
                "\n\n<b>Was bedeutet der R-Wert?</b>\n"
                "Wir verwenden den 7-Tage-R-Wert des RKI. Dieser beschreibt die Anzahl an Menschen, die von einer infizierten Person angesteckt werden. "
                "Dieser Wert ist eine Schätzung und wird aus den geschätzten Infektionszahlen der letzten Tage berechnet."
                "\n\nMehr Informationen zum R-Wert stellt bspw. die <a href='https://www.tagesschau.de/faktenfinder/r-wert-101.html'>Tagesschau</a> zur Verfügung.\n"
                "\n\n<b>Woher kommen die Daten?</b>\n"
                "Unsere Quellen sind die maschinenlesbaren Daten des RKI zu den Impfungen, Neuinfektionen und "
                "dem R-Wert. "
                "Diese laden wir automatisiert an den folgenden Stellen herunter:\n"
                "• <a href='https://opendata.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0.csv'>Neuinfektionen</a>\n"
                "• <a href='https://services.arcgis.com/OLiydejKCZTGhvWg/ArcGIS/rest/services/Impftabelle_mit_Zweitimpfungen/FeatureServer/0'>Impfdaten für Deutschland und die Bundesländer</a>\n"
                "• <a href='https://impfdashboard.de'>Impfdaten für Deutschland</a>\n"
                "• <a href='https://www.rki.de/DE/Content/InfAZ/N/Neuartiges_Coronavirus/Projekte_RKI/Nowcasting_Zahlen_csv.csv'>R-Wert</a>")

    def format_command(self, command: str):
        if command:
            return self.command_format.format(command=command)
