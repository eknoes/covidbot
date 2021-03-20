import csv
import datetime
import logging
import re
import os.path
from enum import Enum
from functools import reduce
from typing import Optional, Tuple, List, Dict, Union, Callable

from covidbot.covid_data import CovidData, DistrictData
from covidbot.location_service import LocationService
from covidbot.user_manager import UserManager, BotUser
from covidbot.utils import format_data_trend, format_int, format_float, format_noun, FormattableNoun


class UserDistrictActions(Enum):
    SUBSCRIBE = 0
    UNSUBSCRIBE = 1
    REPORT = 2
    RULES = 3


class UserHintService:
    FILE = "resources/user-tips.csv"
    current_hint: Optional[str] = None
    current_date: datetime.date = datetime.date.today()
    command_fmt: Callable[[str], str]
    command_regex = re.compile("{([\w\s]*)}")

    def __init__(self, command_formatter: Callable[[str], str]):
        self.command_fmt = command_formatter

    def get_hint_of_today(self) -> str:
        if self.current_hint and self.current_date == datetime.date.today():
            return self.current_hint

        if os.path.isfile(self.FILE):
            with open(self.FILE, "r") as f:
                reader = csv.DictReader(f, delimiter=";")
                today = datetime.date.today()
                for row in reader:
                    if row['date'] == today.isoformat():
                        self.current_hint = self.format_commands(row['message'], self.command_fmt)
                        self.current_date = today
                        return self.current_hint

    @staticmethod
    def format_commands(message: str, formatter: Callable[[str], str]) -> str:
        return UserHintService.command_regex.sub(lambda x: formatter(x.group(1)), message)


class Bot(object):
    _data: CovidData
    _manager: UserManager
    _location_service: LocationService
    DEFAULT_LANG = "de"
    command_format: str
    location_feature: bool = False
    query_regex = re.compile("^[\w,()\-. ]*$")
    user_hints: UserHintService

    def __init__(self, covid_data: CovidData, subscription_manager: UserManager, command_format="<code>/{command}</code>",
                 location_feature=False):
        self.log = logging.getLogger(__name__)
        self._data = covid_data
        self._manager = subscription_manager
        self._location_service = LocationService('resources/germany_rs.geojson')
        self.command_format = command_format
        self.location_feature = location_feature
        self.user_hints = UserHintService(self.format_command)

    def is_user_activated(self, user_identification: Union[int, str]) -> bool:
        user_id = self._manager.get_user_id(user_identification)
        if user_id:
            return self._manager.get_user(user_id).activated
        return False

    def enable_user(self, user_identification: Union[int, str]):
        user_id = self._manager.get_user_id(user_identification)
        if user_id:
            self._manager.set_user_activated(user_id)

    def disable_user(self, user_identification: Union[int, str]):
        user_id = self._manager.get_user_id(user_identification)
        if user_id:
            self._manager.set_user_activated(user_id, activated=False)

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

        # If e.g. emojis or ?! are part of query, we do not have to query online
        if not possible_district and self.query_regex.match(district_query):
            online_match = True
            osm_results = self._location_service.find_location(district_query)
            possible_district = []
            for district_id in osm_results:
                district = self._data.get_district(district_id)
                possible_district.append((district_id, district.name))

        if not possible_district:
            message = 'Leider konnte kein Ort gefunden werden. Bitte beachte, ' \
                      'dass Daten nur für Orte innerhalb Deutschlands verfügbar sind. Mit {help_cmd} erhältst du ' \
                      'einen Überblick über die Funktionsweise des Bots.' \
                .format(location=district_query, help_cmd=self.format_command("hilfe"))
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
        if not district_id:
            return ('Leider konnte kein Ort in den RKI Corona Daten zu {location} gefunden werden. Bitte beachte, '
                    'dass Daten nur für Orte innerhalb Deutschlands verfügbar sind.'.format(location="deinem Standort"),
                    None)
        else:
            district = self._data.get_district(district_id)
            results = [(district_id, district.name)]

            message = None
            if district.parent:
                message = "Die Daten für die folgenden Orte und Regionen sind für deinen Standort verfügbar"
                results.append((district.parent, self._data.get_district(district.parent).name))
            return message, results

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
            actions.append(("Regeln anzeigen", UserDistrictActions.RULES))
            message = "Möchtest du dein Abo von {name} {verb}, die aktuellen Daten oder geltende Regeln erhalten?" \
                .format(name=district.name, verb=verb)
        else:
            message = "Möchtest du die aktuellen Daten von {name} erhalten?".format(name=district.name)
        return message, actions

    def get_rules(self, district_id: int) -> str:
        current_data = self._data.get_district_data(district_id)
        rules, district_name = None, None
        if current_data.rules:
            rules = current_data.rules
            district_name = current_data.name

        if not rules and current_data.parent:
            parent = self._data.get_district_data(current_data.parent)
            if parent.rules:
                rules = parent.rules
                district_name = parent.name

        if rules:
            message = f"<b>👆 Regeln für {district_name}</b>\n" \
                      f"<i>Wir beziehen den folgenden Überblick vom Kompetenzzentrum Tourismus des Bundes. Für die Richtigkeit der Angaben können wir " \
                      f"keine Gewähr übernehmen. Für weitere Informationen siehe unten.</i>\n" \
                      f"{rules.text}\n\nDetails zu den aktuellen Regeln sowie Links zu den FAQs und den Verordnungen deines Bundeslandes findest du " \
                      f"<a href='{rules.link}'>hier</a>.\n\n"
            message += (f'Regeln vom {rules.date.strftime("%d.%m.%Y")}. Daten vom '
                        f'<a href="https://tourismus-wegweiser.de">Tourismus-Wegweisers</a> des Kompetenzzentrum Tourismus des Bundes, sind lizenziert unter'
                        f' CC BY 4.0.')
        else:
            message = f"Regeln sind für {current_data.name} leider nicht verfügbar. Momentan können Regeln nur für " \
                      f"Bundesländer abgerufen werden."
        return message

    def get_vaccination_overview(self, district_id: int) -> str:
        parent_data = self._data.get_district_data(district_id)
        if not parent_data.vaccinations:
            return f"Leider kann für {parent_data.name} keine Impfübersicht generiert werden, da keine Daten vorliegen."

        children_data = self._data.get_children_data(district_id)
        message = f"<b>💉 Impfdaten ({parent_data.name})</b>\n"
        message += "{rate_partial}% der Bevölkerung haben mindestens eine Impfung erhalten, {rate_full}% sind " \
                   " - Stand {vacc_date} - vollständig geimpft. " \
                   "Bei dem Impftempo der letzten 7 Tage werden {vacc_speed} Dosen pro Tag verabreicht und in " \
                   "{vacc_days_to_finish} Tagen wäre die gesamte Bevölkerung vollständig geschützt.\n\n" \
                   "Verabreichte Erstimpfdosen: {vacc_partial}\n" \
                   "Verabreichte Zweitimpfdosen: {vacc_full}\n\n" \
            .format(rate_partial=format_float(parent_data.vaccinations.partial_rate * 100),
                    rate_full=format_float(parent_data.vaccinations.full_rate * 100),
                    vacc_partial=format_int(parent_data.vaccinations.vaccinated_partial),
                    vacc_full=format_int(parent_data.vaccinations.vaccinated_full),
                    vacc_date=parent_data.vaccinations.date.strftime("%d.%m.%Y"),
                    vacc_speed=format_int(parent_data.vaccinations.avg_speed),
                    vacc_days_to_finish=format_int(parent_data.vaccinations.avg_days_to_finish))

        earliest_data = reduce(
            lambda x, y: x if x.vaccinations.date < y.vaccinations.date else y,
            children_data)
        message += "<b>💉 Impfdaten der Länder</b>\n" \
                   "Angegeben ist der Anteil der Bevölkerung, die mindestens eine Impfung erhalten hat, sowie der " \
                   "Anteil der Bevölkerung, der einen vollen Impfschutz hat.\n\n"
        children_data.sort(key=lambda x: x.name)
        for child in children_data:
            message += "• {rate_partial}% / {rate_full}% ({district})\n" \
                .format(district=child.name,
                        rate_partial=format_float(child.vaccinations.partial_rate * 100),
                        rate_full=format_float(child.vaccinations.full_rate * 100))

        message += '\n\n' \
                   '<i>Stand: {earliest_vacc_date}. Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://impfdashboard.de/">Impfdashboard</a>. ' \
                   'Sende {info_command} um eine Erläuterung der Daten zu erhalten.</i>' \
            .format(info_command=self.format_command("Info"),
                    earliest_vacc_date=earliest_data.vaccinations.date.strftime("%d.%m.%Y"))
        return message

    def get_district_report(self, district_id: int) -> str:
        current_data = self._data.get_district_data(district_id)
        sources = [f'Infektionsdaten vom {current_data.date.strftime("%d.%m.%Y")}. '
                   f'Infektionsdaten und R-Wert vom Robert Koch-Institut (RKI), '
                   'Lizenz: dl-de/by-2-0. '
                   'Weitere Informationen findest Du im <a href="https://corona.rki.de/">Dashboard des RKI</a>.']

        message = "<b>{district_name}</b>\n\n"

        message += "<b>🦠 Infektionsdaten</b>\n"
        if current_data.incidence:
            message += "Die 7-Tage-Inzidenz liegt bei {incidence} {incidence_trend}."
            if current_data.incidence_interval_since:
                interval_length = current_data.date - current_data.incidence_interval_since
                message += " Die Inzidenz ist damit seit {interval_length} unter {interval}." \
                    .format(interval_length=format_noun(interval_length.days, FormattableNoun.DAYS),
                            interval=current_data.incidence_interval_upper_value)

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

        if current_data.icu_data:
            message += f"<b>🏥️ Intensivbetten</b>\n" \
                       f"{format_float(current_data.icu_data.percent_occupied())}% " \
                       f"({format_noun(current_data.icu_data.occupied_beds, FormattableNoun.BEDS)}) der " \
                       f"Intensivbetten sind aktuell belegt. " \
                       f"In {format_noun(current_data.icu_data.occupied_covid, FormattableNoun.BEDS)} " \
                       f"({format_float(current_data.icu_data.percent_covid())}%) liegen Patienten" \
                       f" mit COVID-19, davon müssen {format_int(current_data.icu_data.covid_ventilated)} beatmet werden. " \
                       f"Insgesamt gibt es {format_noun(current_data.icu_data.total_beds(), FormattableNoun.BEDS)}.\n\n"
            sources.append(f'Intensivbettenauslastung vom {current_data.icu_data.date.strftime("%d.%m.%Y")}. '
                           f'Daten vom <a href="https://intensivregister.de">DIVI-Intensivregister</a>.')

        related_vaccinations = None
        if current_data.vaccinations:
            related_vaccinations = current_data.vaccinations
            message += "<b>💉 Impfdaten</b>\n"
        else:
            if current_data.parent:
                parent_district = self._data.get_district_data(current_data.parent)
                related_vaccinations = parent_district.vaccinations
                message += f"<b>💉 Impfdaten für {parent_district.name}</b>\n"

        if related_vaccinations:
            message += "{rate_partial}% der Bevölkerung haben mindestens eine Impfung erhalten, {rate_full}% sind " \
                       " - Stand {vacc_date} - vollständig geimpft.\n\n" \
                       "Verabreichte Erstimpfdosen: {vacc_partial}\n" \
                       "Verabreichte Zweitimpfdosen: {vacc_full}\n\n" \
                .format(rate_partial=format_float(related_vaccinations.partial_rate * 100),
                        rate_full=format_float(related_vaccinations.full_rate * 100),
                        vacc_partial=format_int(related_vaccinations.vaccinated_partial),
                        vacc_full=format_int(related_vaccinations.vaccinated_full),
                        vacc_date=related_vaccinations.date.strftime("%d.%m.%Y"))
            sources.append(f'Impfdaten vom {related_vaccinations.date.strftime("%d.%m.%Y")}. '
                           f'Daten vom Bundesministerium für Gesundheit, mehr Informationen im '
                           f'<a href="https://impfdashboard.de/">Impfdashboard</a>.')

        if current_data.rules:
            message += "<b>👆 Regeln</b>\n" \
                       f"{current_data.rules.text}\n\nDetails zu den aktuellen Regeln und Öffnungen findest du " \
                       f"<a href='{current_data.rules.link}'>hier</a>.\n\n"
            sources.append(f'Regeln vom {current_data.rules.date.strftime("%d.%m.%Y")}. Daten vom '
                           f'<a href="https://tourismus-wegweiser.de">Tourismus-Wegweisers</a>, sind lizenziert unter'
                           f' CC BY 4.0.')
        elif current_data.parent:
            parent_district = self._data.get_district_data(current_data.parent)
            if parent_district and parent_district.rules:
                message += f"<b>👆 Regeln</b>\nDie wichtigsten Regeln für {parent_district.name} erhältst du mit dem " \
                           f"Befehl {self.format_command('Daten ' + parent_district.name)}.\n\n"
        message += "<b>Quellen & Datenstand</b>\n"
        message += "\n\n".join(sources)
        message += '\nSende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten.' \
            .format(info_command=self.format_command("Info"), date=current_data.date.strftime("%d.%m.%Y"))

        return message

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
        message += "<b>🦠 Infektionszahlen</b>\n" \
                   "Insgesamt wurden bundesweit {new_cases} {new_cases_trend} und " \
                   "{new_deaths} {new_deaths_trend} gemeldet. Die 7-Tage-Inzidenz liegt bei {incidence} " \
                   "{incidence_trend}."
        if country.r_value:
            message += " Der zuletzt gemeldete 7-Tage-R-Wert beträgt {r_value} {r_trend}." \
                .format(r_value=format_float(country.r_value.r_value_7day),
                        r_trend=format_data_trend(country.r_value.r_trend))
        message += "\n\n"
        message = message.format(date=self._data.get_last_update().strftime("%d.%m.%Y"),
                                 new_cases=format_noun(country.new_cases, FormattableNoun.INFECTIONS),
                                 new_cases_trend=format_data_trend(country.cases_trend),
                                 new_deaths=format_noun(country.new_deaths, FormattableNoun.DEATHS),
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

        if country.vaccinations:
            message += "<b>💉  Impfdaten</b>\n" \
                       "{vacc_partial} ({rate_partial}%) Personen in Deutschland haben mindestens eine Impfdosis " \
                       "erhalten, {vacc_full} ({rate_full}%) Menschen sind bereits - Stand {date} - vollständig geimpft.\n\n" \
                .format(rate_full=format_float(country.vaccinations.full_rate * 100),
                        rate_partial=format_float(country.vaccinations.partial_rate * 100),
                        vacc_partial=format_int(country.vaccinations.vaccinated_partial),
                        vacc_full=format_int(country.vaccinations.vaccinated_full),
                        date=country.vaccinations.date.strftime("%d.%m.%Y"))

        if country.icu_data:
            message += f"<b>🏥 Intensivbetten</b>\n" \
                       f"{format_float(country.icu_data.percent_occupied())}% " \
                       f"({format_noun(country.icu_data.occupied_beds, FormattableNoun.BEDS)}) der " \
                       f"Intensivbetten sind aktuell belegt. " \
                       f"In {format_noun(country.icu_data.occupied_covid, FormattableNoun.BEDS)} " \
                       f"({format_float(country.icu_data.percent_covid())}%) liegen Patienten" \
                       f" mit COVID-19, davon müssen {country.icu_data.covid_ventilated} beatmet werden. " \
                       f"Insgesamt gibt es {format_noun(country.icu_data.total_beds(), FormattableNoun.BEDS)}.\n\n"

        user_hint = self.user_hints.get_hint_of_today()
        if user_hint:
            message += f"{user_hint}\n\n"

        message += '<i>Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://corona.rki.de/">Dashboard des RKI</a> und dem ' \
                   '<a href="https://impfdashboard.de/">Impfdashboard</a>. ' \
                   'Intensivbettendaten vom <a href="https://intensivregister.de">DIVI-Intensivregister</a>.' \
                   '\n\nSende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten. Ein Service von <a href="https://d-64.org">D64 - Zentrum für Digitalen ' \
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
        return "{name}: {incidence} {incidence_trend} ({new_cases}, {new_deaths})" \
            .format(name=district.name,
                    incidence=format_float(district.incidence),
                    incidence_trend=format_data_trend(district.incidence_trend),
                    new_cases=format_noun(district.new_cases, FormattableNoun.INFECTIONS),
                    new_deaths=format_noun(district.new_deaths, FormattableNoun.DEATHS))

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
            message = "Du hast aktuell {abo_count} abonniert." \
                .format(abo_count=format_noun(len(user.subscriptions), FormattableNoun.DISTRICT))

        return message, counties

    @staticmethod
    def handle_no_input() -> str:
        return 'Diese Aktion benötigt eine Ortsangabe.'

    def unknown_action(self) -> str:
        return ("Dieser Befehl wurde nicht verstanden. Sende <code>{help_command}</code> um einen Überblick über die "
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
                    'Wählst du "Daten" aus, erhältst Du einmalig Informationen über diesen Ort. Diese '
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
                    '<b>👋 Abmelden</b>\n'
                    'Wenn du von unserem Bot keine Nachrichten mehr empfangen möchtest, kannst du alle deine Daten '
                    'bei uns löschen indem du {deleteme_command} sendest.\n\n'
                    '<b>🤓 Statistik</b>\n'
                    'Wenn du {stat_command} sendest, erhältst du ein Beliebtheitsranking der Orte und ein '
                    'paar andere Daten zu den aktuellen Nutzungszahlen des Bots.\n\n'
                    '<b>Weiteres</b>\n'
                    '• Sende {vacc_command} für eine Übersicht der Impfsituation\n'
                    '• Sende {report_command} für deinen Tagesbericht\n'
                    '• Sende {abo_command} um deine abonnierten Orte einzusehen\n'
                    '• Sende {privacy_command} erhältst du mehr Informationen zum Datenschutz und die '
                    'Möglichkeit, alle deine Daten bei uns zu löschen\n'
                    '• Unter https://github.com/eknoes/covid-bot findest du den Quelltext des Bots\n'
                    '\n\n'
                    'Auf https://covidbot.d-64.org/ gibt es mehr Informationen zum Bot und die Links für alle '
                    'anderen verfügbaren Messenger. Diesen Hilfetext erhältst du über {help_command}') \
            .format(stat_command=self.format_command('Statistik'), report_command=self.format_command('Bericht'),
                    abo_command=self.format_command('Abo'), privacy_command=self.format_command('Datenschutz'),
                    help_command=self.format_command('Hilfe'), info_command=self.format_command('Info'),
                    vacc_command=self.format_command('Impfungen'), deleteme_command=self.format_command('Loeschmich'))
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
