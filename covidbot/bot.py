import csv
import datetime
import logging
import os.path
import re
from enum import Enum
from functools import reduce
from typing import Optional, Tuple, List, Dict, Union, Callable, Generator

from covidbot.covid_data import CovidData, DistrictData, Visualization
from covidbot.covid_data.models import District
from covidbot.location_service import LocationService
from covidbot.user_manager import UserManager, BotUser
from covidbot.utils import format_data_trend, format_int, format_float, format_noun, FormattableNoun, BotResponse


class UserDistrictActions(Enum):
    SUBSCRIBE = 0
    UNSUBSCRIBE = 1
    REPORT = 2
    RULES = 3


class BotUserSettings:
    BETA = "beta"
    REPORT_GRAPHICS = "report_graphics"
    REPORT_INCLUDE_ICU = "report_include_icu"
    REPORT_INCLUDE_VACCINATION = "report_include_vaccination"
    REPORT_EXTENSIVE_GRAPHICS = "report_extensive_graphics"
    REPORT_SEND_EACH_DISTRICT = "report_send_each_district"
    DISABLE_FAKE_FORMAT = "disable_fake_format"


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
    data_visualization: Visualization
    DEFAULT_LANG = "de"
    command_format: str
    location_feature: bool = False
    query_regex = re.compile("^[\w,()\-. ]*$")
    user_hints: UserHintService

    def __init__(self, covid_data: CovidData, subscription_manager: UserManager, visualization: Visualization,
                 command_format="<code>/{command}</code>",
                 location_feature=False):
        self.log = logging.getLogger(__name__)
        self._data = covid_data
        self._manager = subscription_manager
        self._location_service = LocationService('resources/germany_rs.geojson')
        self.command_format = command_format
        self.location_feature = location_feature
        self.user_hints = UserHintService(self.format_command)
        self.data_visualization = visualization

    # User management functions
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

    def get_user_setting(self, user_identification: Union[int, str], setting: str, default: bool) -> bool:
        user_id = self._manager.get_user_id(user_identification, create_if_not_exists=False)
        return self._manager.get_user_setting(user_id, setting, default)

    def set_user_setting(self, user_identification: Union[int, str], setting: str, value: bool):
        user_id = self._manager.get_user_id(user_identification, create_if_not_exists=True)
        return self._manager.set_user_setting(user_id, setting, value)

    def set_language(self, user_identification: Union[int, str], language: Optional[str]) -> List[BotResponse]:
        user_id = self._manager.get_user_id(user_identification)
        if not language:
            user = self._manager.get_user(user_id)
            if user and user.language:
                language = user.language
            else:
                language = self.DEFAULT_LANG
            return [BotResponse("Deine aktuelle Spracheinstellung ist {language}".format(language=language))]
        if self._manager.set_language(user_id, language):
            return [BotResponse("Deine bevorzugte Sprache wurde auf {language} gesetzt.".format(language=language))]
        return [
            BotResponse("Leider konnte deine Sprache nicht auf {language} gesetzt werde.".format(language=language))]

    def resolve_geolocation(self, lon, lat) -> Optional[List[District]]:
        district_id = self._location_service.find_rs(lon, lat)
        if not district_id:
            return None

        results = [self._data.get_district(district_id)]
        parent = results[0].parent
        if parent:
            results.append(self._data.get_district(parent))

        return results

    def find_district_id(self, district_query: str) -> Tuple[Optional[BotResponse], Optional[List[District]]]:
        if not district_query:
            return BotResponse('Dieser Befehl benötigt eine Ortsangabe'), None

        possible_district = self._data.search_district_by_name(district_query)
        online_match = False

        # If e.g. emojis or ?! are part of query, we do not have to query online
        if not possible_district and self.query_regex.match(district_query):
            online_match = True
            osm_results = self._location_service.find_location(district_query)
            possible_district = []
            for district_id in osm_results:
                possible_district.append(self._data.get_district(district_id))

        if not possible_district:
            message = 'Leider konnte kein Ort gefunden werden. Bitte beachte, ' \
                      'dass Daten nur für Orte innerhalb Deutschlands verfügbar sind. Mit {help_cmd} erhältst du ' \
                      'einen Überblick über die Funktionsweise des Bots.' \
                .format(location=district_query, help_cmd=self.format_command("hilfe"))
            return BotResponse(message), None
        elif len(possible_district) == 1:
            return None, possible_district
        elif 1 < len(possible_district) <= 15:
            if online_match:
                message = "Für {district} stellt das RKI leider keine spezifischen Daten zur Verfügung. " \
                          "Du kannst stattdessen die Zahlen des dazugehörigen Landkreises abrufen" \
                    .format(district=district_query)
            else:
                message = "Es wurden mehrere Orte mit diesem oder ähnlichen Namen gefunden"
            return BotResponse(message), possible_district
        else:
            message = "Mit deinem Suchbegriff wurden mehr als 15 Orte gefunden, bitte versuche spezifischer zu sein."
            return BotResponse(message), None

    def get_possible_actions(self, user_identification: Union[int, str], district_id: int) -> Tuple[
        str, List[Tuple[str, UserDistrictActions]]]:
        actions = [("Daten anzeigen", UserDistrictActions.REPORT)]
        district = self._data.get_district(district_id)
        user_id = self._manager.get_user_id(user_identification)

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
        return message, actions

    def get_rules(self, district_id: int) -> List[BotResponse]:
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
            message = f"<b>👆 Regeln für {district_name}</b>\n\n" \
                      f"<i>Wir beziehen den folgenden Überblick vom Kompetenzzentrum Tourismus des Bundes. Für die Richtigkeit der Angaben können wir " \
                      f"keine Gewähr übernehmen. Für weitere Informationen siehe unten.</i>\n\n" \
                      f"{rules.text}\n\nDetails zu den aktuellen Regeln sowie Links zu den FAQs und den Verordnungen deines Bundeslandes findest du " \
                      f"<a href='{rules.link}'>hier</a>.\n\n"
            message += (f'Regeln vom {rules.date.strftime("%d.%m.%Y")}. Informationen vom '
                        f'<a href="https://tourismus-wegweiser.de">Tourismus-Wegweiser</a> des Kompetenzzentrum Tourismus des Bundes, lizenziert unter'
                        f' CC BY 4.0.')
        else:
            message = f"Regeln sind für {current_data.name} leider nicht verfügbar. Momentan können Regeln nur für " \
                      f"Bundesländer abgerufen werden."
        return [BotResponse(message)]

    def get_vaccination_overview(self, district_id: int) -> List[BotResponse]:
        parent_data = self._data.get_district_data(district_id)
        if not parent_data.vaccinations:
            return [BotResponse(
                f"Leider kann für {parent_data.name} keine Impfübersicht generiert werden, da keine Daten vorliegen.")]

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
        return [BotResponse(message, [self.data_visualization.vaccination_graph(district_id),
                                      self.data_visualization.vaccination_speed_graph(district_id)])]

    def get_district_report(self, district_id: int) -> List[BotResponse]:
        graphics = [self.data_visualization.infections_graph(district_id),
                    self.data_visualization.incidence_graph(district_id)]
        current_data = self._data.get_district_data(district_id)
        sources = [f'Infektionsdaten vom {current_data.date.strftime("%d.%m.%Y")}. '
                   f'Infektionsdaten und R-Wert vom Robert Koch-Institut (RKI), '
                   'Lizenz: dl-de/by-2-0. '
                   'Weitere Informationen findest Du im <a href="https://corona.rki.de/">Dashboard des RKI</a>.']

        message = "<b>{district_name}</b>\n\n"

        message += "<b>🦠 Infektionsdaten</b>\n"
        if current_data.incidence:
            message += "Die 7-Tage-Inzidenz liegt bei {incidence}{incidence_trend}."
            if current_data.incidence_interval_since is not None:
                days = format_noun((current_data.date - current_data.incidence_interval_since).days,
                                   FormattableNoun.DAYS)
                interval = current_data.incidence_interval_threshold

                if current_data.incidence < current_data.incidence_interval_threshold:
                    word = "unter"
                else:
                    word = "über"

                message += " Die Inzidenz ist damit seit {interval_length} {word} {interval}." \
                    .format(interval_length=days, interval=interval, word=word)

        if current_data.r_value:
            message += " Der 7-Tage-R-Wert liegt bei {r_value}{r_trend}." \
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
                       f"({format_float(current_data.icu_data.percent_covid())}%) liegen Patient:innen" \
                       f" mit COVID-19, davon müssen {format_noun(current_data.icu_data.covid_ventilated, FormattableNoun.PERSONS)}" \
                       f" ({format_float(current_data.icu_data.percent_ventilated())}%) invasiv beatmet werden. " \
                       f"Insgesamt gibt es {format_noun(current_data.icu_data.total_beds(), FormattableNoun.BEDS)}.\n\n"
            sources.append(f'Intensivbettenauslastung vom {current_data.icu_data.date.strftime("%d.%m.%Y")}. '
                           f'Daten vom <a href="https://intensivregister.de">DIVI-Intensivregister</a>.')
            graphics.append(self.data_visualization.icu_graph(district_id))

        related_vaccinations = None
        if current_data.vaccinations:
            related_vaccinations = current_data.vaccinations
            message += "<b>💉 Impfdaten</b>\n"
            # TODO: Daten fehlen
            # graphics.append(self.data_visualization.vaccination_graph(district_id))
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
                           f"Befehl {self.format_command('Regeln ' + parent_district.name)}.\n\n"
        message += "<b>Quellen & Datenstand</b>\n"
        message += "\n\n".join(sources)
        message += '\nSende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten.' \
            .format(info_command=self.format_command("Info"), date=current_data.date.strftime("%d.%m.%Y"))

        return [BotResponse(message, graphics)]

    def subscribe(self, user_identification: Union[int, str], district_id: Optional[int]) -> List[BotResponse]:
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
        return [BotResponse(message.format(name=self._data.get_district(district_id).name))] + self.get_district_report(
            district_id)

    def unsubscribe(self, user_identification: Union[int, str], district_id: int) -> List[BotResponse]:
        user_id = self._manager.get_user_id(user_identification)
        if self._manager.rm_subscription(user_id, district_id):
            message = "Dein Abonnement für {name} wurde beendet."
        else:
            message = "Du hast {name} nicht abonniert."
        return [BotResponse(message.format(name=self._data.get_district(district_id).name))]

    def get_report(self, user_identification: Union[int, str]) -> List[BotResponse]:
        user_id = self._manager.get_user_id(user_identification)
        user = self._manager.get_user(user_id, with_subscriptions=True)
        if not user:
            return self._get_report([])

        if self._manager.get_user_setting(user_id, BotUserSettings.BETA, False):
            return self._get_new_report(user.subscriptions, user_id)
        return self._get_report(user.subscriptions, user.id)

    def _get_new_report(self, subscriptions: List[int], user_id: Optional[int] = None) -> List[BotResponse]:
        # Visualization
        graphs = []
        if self._manager.get_user_setting(user_id, BotUserSettings.REPORT_GRAPHICS, True):
            graphs.append(self.data_visualization.infections_graph(0))

        country = self._data.get_country_data()
        message = "<b>Corona-Bericht vom {date}</b>\n\n"
        message += "<b>🦠 Infektionszahlen</b>\n" \
                   "Insgesamt wurden bundesweit {new_cases}{new_cases_trend} und " \
                   "{new_deaths}{new_deaths_trend} gemeldet. Die 7-Tage-Inzidenz liegt bei {incidence}" \
                   "{incidence_trend}."
        if country.r_value:
            message += " Der zuletzt gemeldete 7-Tage-R-Wert beträgt {r_value}{r_trend}." \
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
            message += "In deinen abonnierten Orten ist die Lage wie folgt:"

            # Split Bundeslaender from other
            districts = list(map(lambda rs: self._data.get_district_data(rs), subscriptions))
            states = list(filter(lambda d: d.type == "Bundesland", districts))
            cities = list(filter(lambda d: d.type != "Bundesland" and d.type != "Staat", districts))
            districts = self.sort_districts(states) + self.sort_districts(cities)
            if len(districts) > 0:
                for district in districts:
                    threshold_info = ""
                    if district.incidence_interval_since is not None:
                        date_interval = district.date - district.incidence_interval_since
                        days = format_noun(date_interval.days, FormattableNoun.DAYS)

                        if district.incidence < district.incidence_interval_threshold:
                            word = "unter"
                        else:
                            word = "über"

                        threshold_info = "Seit {interval_length} {word} {interval}" \
                            .format(interval_length=days, interval=district.incidence_interval_threshold, word=word)

                    message += "\n\n<b>{name}</b>: {incidence}{incidence_trend}\n" \
                               "• {threshold_info}\n" \
                               "• {new_cases}, {new_deaths}" \
                        .format(name=district.name,
                                incidence=format_float(district.incidence),
                                incidence_trend=format_data_trend(district.incidence_trend),
                                new_cases=format_noun(district.new_cases, FormattableNoun.INFECTIONS),
                                new_deaths=format_noun(district.new_deaths, FormattableNoun.DEATHS),
                                threshold_info=threshold_info)
                    if district.icu_data:
                        message += "\n• {percent_occupied}% ({beds_occupied}) belegt, davon {beds_covid} ({percent_covid}%) mit Covid19" \
                            .format(beds_occupied=format_noun(district.icu_data.occupied_beds, FormattableNoun.BEDS),
                                    percent_occupied=format_float(district.icu_data.percent_occupied()),
                                    beds_covid=format_noun(district.icu_data.occupied_covid, FormattableNoun.BEDS),
                                    percent_covid=format_float(district.icu_data.percent_covid()))
                message += "\n\n"
            if self._manager.get_user_setting(user_id, BotUserSettings.REPORT_GRAPHICS, True):
                # Generate multi-incidence graph for up to 8 districts
                districts = subscriptions[-8:]
                if 0 in subscriptions and 0 not in districts:
                    districts[0] = 0
                graphs.append(self.data_visualization.multi_incidence_graph(districts))

        user_hint = self.user_hints.get_hint_of_today()
        if user_hint:
            message += f"{user_hint}\n\n"

        message += '<i>Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://corona.rki.de/">Dashboard des RKI</a> und dem ' \
                   '<a href="https://impfdashboard.de/">Impfdashboard</a>. ' \
                   'Intensivbettendaten vom <a href="https://intensivregister.de">DIVI-Intensivregister</a>.</i>' \
                   '\n\n' \
                   '<i>Sende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten. Ein Service von <a href="https://d-64.org">D64 - Zentrum für Digitalen ' \
                   'Fortschritt</a>.</i>'.format(info_command=self.format_command("Info"))

        message += "\n\n<b>Dies ist ein Entwurf für einen verbesserten Bericht. Wir würden uns sehr über Feedback " \
                   "freuen, sende uns einfach eine Nachricht und bestätige dann, dass diese an uns weitergeleitet " \
                   "werden darf. Danke 🙏</b>"

        reports = [BotResponse(message, graphs)]
        return reports

    def _get_report(self, subscriptions: List[int], user_id: Optional[int] = None) -> List[BotResponse]:
        # Visualization
        graphs = []
        if self._manager.get_user_setting(user_id, BotUserSettings.REPORT_GRAPHICS, True):
            graphs.append(self.data_visualization.infections_graph(0))

        country = self._data.get_country_data()
        message = "<b>Corona-Bericht vom {date}</b>\n\n"
        message += "<b>🦠 Infektionszahlen</b>\n" \
                   "Insgesamt wurden bundesweit {new_cases}{new_cases_trend} und " \
                   "{new_deaths}{new_deaths_trend} gemeldet. Die 7-Tage-Inzidenz liegt bei {incidence}" \
                   "{incidence_trend}."
        if country.r_value:
            message += " Der zuletzt gemeldete 7-Tage-R-Wert beträgt {r_value}{r_trend}." \
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
            subscribed_cities = list(filter(lambda d: d.type != "Bundesland" and d.type != "Staat", subscription_data))
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

            if self._manager.get_user_setting(user_id, BotUserSettings.REPORT_GRAPHICS, True):
                # Generate multi-incidence graph for up to 8 districts
                districts = subscriptions[-8:]
                if 0 in subscriptions and 0 not in districts:
                    districts[0] = 0
                graphs.append(self.data_visualization.multi_incidence_graph(districts))

        if country.vaccinations and self._manager.get_user_setting(user_id, BotUserSettings.REPORT_INCLUDE_VACCINATION,
                                                                   True):
            message += "<b>💉 Impfdaten</b>\n" \
                       "Am {date} wurden {doses} Dosen verimpft. So haben {vacc_partial} ({rate_partial}%) Personen in Deutschland mindestens eine Impfdosis " \
                       "erhalten, {vacc_full} ({rate_full}%) Menschen sind bereits vollständig geimpft.\n\n" \
                .format(rate_full=format_float(country.vaccinations.full_rate * 100),
                        rate_partial=format_float(country.vaccinations.partial_rate * 100),
                        vacc_partial=format_int(country.vaccinations.vaccinated_partial),
                        vacc_full=format_int(country.vaccinations.vaccinated_full),
                        date=country.vaccinations.date.strftime("%d.%m.%Y"),
                        doses=format_int(country.vaccinations.doses_diff))
            if self._manager.get_user_setting(user_id, BotUserSettings.REPORT_EXTENSIVE_GRAPHICS, False):
                graphs.append(self.data_visualization.vaccination_graph(country.id))
                graphs.append(self.data_visualization.vaccination_speed_graph(country.id))

        if country.icu_data and self._manager.get_user_setting(user_id, BotUserSettings.REPORT_INCLUDE_ICU, True):
            message += f"<b>🏥 Intensivbetten</b>\n" \
                       f"{format_float(country.icu_data.percent_occupied())}% " \
                       f"({format_noun(country.icu_data.occupied_beds, FormattableNoun.BEDS)}) der " \
                       f"Intensivbetten sind aktuell belegt. " \
                       f"In {format_noun(country.icu_data.occupied_covid, FormattableNoun.BEDS)} " \
                       f"({format_float(country.icu_data.percent_covid())}%) liegen Patient:innen" \
                       f" mit COVID-19, davon müssen {format_noun(country.icu_data.covid_ventilated, FormattableNoun.PERSONS)}" \
                       f" ({format_float(country.icu_data.percent_ventilated())}%) invasiv beatmet werden. " \
                       f"Insgesamt gibt es {format_noun(country.icu_data.total_beds(), FormattableNoun.BEDS)}.\n\n"

        user_hint = self.user_hints.get_hint_of_today()
        if user_hint:
            message += f"{user_hint}\n\n"

        message += '<i>Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://corona.rki.de/">Dashboard des RKI</a> und dem ' \
                   '<a href="https://impfdashboard.de/">Impfdashboard</a>. ' \
                   'Intensivbettendaten vom <a href="https://intensivregister.de">DIVI-Intensivregister</a>.</i>' \
                   '\n\n' \
                   '<i>Sende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten. Ein Service von <a href="https://d-64.org">D64 - Zentrum für Digitalen ' \
                   'Fortschritt</a>.</i>'.format(info_command=self.format_command("Info"))

        reports = [BotResponse(message, graphs)]

        if user_id and self._manager.get_user_setting(user_id, BotUserSettings.REPORT_SEND_EACH_DISTRICT, False):
            for subscription in subscriptions:
                reports += self.get_district_report(subscription)
        return reports

    def delete_user(self, user_identification: Union[int, str]) -> List[BotResponse]:
        user_id = self._manager.get_user_id(user_identification, create_if_not_exists=False)
        if user_id:
            if self._manager.delete_user(user_id):
                return [BotResponse("Deine Daten wurden erfolgreich gelöscht.")]
        return [BotResponse("Zu deinem Account sind keine Daten vorhanden.")]

    def change_platform_id(self, old_id: str, new_id: str) -> bool:
        return self._manager.change_platform_id(old_id, new_id)

    @staticmethod
    def format_district_data(district: DistrictData) -> str:
        return "{name}: {incidence}{incidence_trend} ({new_cases}, {new_deaths})" \
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

    def get_overview(self, user_identification: Union[int, str]) -> Tuple[BotResponse, Optional[List[District]]]:
        user_id = self._manager.get_user_id(user_identification)
        user = self._manager.get_user(user_id, with_subscriptions=True)
        if not user or not user.subscriptions:
            message = "Du hast aktuell <b>keine</b> Orte abonniert. Mit <code>{subscribe_command}</code> kannst du " \
                      "Orte abonnieren, bspw. <code>{subscribe_command} Dresden</code> " \
                .format(subscribe_command=self.format_command("abo"))
            districts = None
        else:
            districts = list(map(self._data.get_district, user.subscriptions))
            message = "Du hast aktuell {abo_count} abonniert." \
                .format(abo_count=format_noun(len(user.subscriptions), FormattableNoun.DISTRICT))

        return BotResponse(message), districts

    @staticmethod
    def handle_no_input() -> str:
        return 'Diese Aktion benötigt eine Ortsangabe.'

    def unknown_action(self) -> List[BotResponse]:
        return [BotResponse(
            ("Dieser Befehl wurde nicht verstanden. Sende <code>{help_command}</code> um einen Überblick über die "
             "Funktionen zu bekommen!").format(help_command=self.format_command("hilfe")))]

    def get_unconfirmed_daily_reports(self) -> Generator[Tuple[Union[int, str], List[BotResponse]], None, None]:
        """
        Needs to be called once in a while to check for new data. Returns a list of messages to be sent, if new data
        arrived
        :rtype: Optional[list[Tuple[str, str]]]
        :return: List of (userid, message)
        """
        users = []
        data_update = self._data.get_last_update()
        for user in self._manager.get_all_user(with_subscriptions=True):
            if not user.activated or not user.subscriptions:
                continue

            if user.last_update is None or user.last_update.date() < data_update:
                users.append(user)

        for user in users:
            yield user.platform_id, self._get_report(user.subscriptions, user.id)

    def unconfirmed_daily_reports_available(self) -> bool:
        """
        Needs to be called once in a while to check for new data. Returns a list of messages to be sent, if new data
        arrived
        :rtype: Optional[list[Tuple[str, str]]]
        :return: List of (userid, message)
        """
        data_update = self._data.get_last_update()
        for user in self._manager.get_all_user(with_subscriptions=True):
            if not user.activated or not user.subscriptions:
                continue

            if user.last_update is None or user.last_update.date() < data_update:
                return True

        return False

    def confirm_daily_report_send(self, user_identification: Union[int, str]):
        updated = self._data.get_last_update()
        user_id = self._manager.get_user_id(user_identification)
        self._manager.set_last_update(user_id, updated)

    def get_statistic(self) -> List[BotResponse]:
        message = "Aktuell nutzen {total_user} Personen diesen Bot, davon "
        platforms = self._manager.get_users_per_messenger()
        platforms.sort(key=lambda p: p[1], reverse=True)
        messenger_strings = [f"{c} über {m}" for m, c in platforms]
        message += ", ".join(messenger_strings[:-1])
        if messenger_strings[-1:]:
            message += f" und {messenger_strings[-1:][0]}. "
        else:
            message += '. '

        platforms = self._manager.get_users_per_network()
        platforms.sort(key=lambda p: p[1], reverse=True)
        messenger_strings = [f"{c} Follower auf {m}" for m, c in platforms]
        message += "Außerdem sind "
        message += ", ".join(messenger_strings[:-1])
        if messenger_strings[-1:]:
            message += f" und {messenger_strings[-1:][0]}."
        else:
            message += '.'

        message += "\n\nDie Top 10 der beliebtesten Orte sind:\n"

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
        return [BotResponse(message, [self.data_visualization.bot_user_graph()])]

    def get_debug_report(self, user_identification: Union[int, str]) -> List[BotResponse]:
        uid = self._manager.get_user_id(user_identification, False)
        if not uid:
            return [BotResponse("Für dich sind aktuell keine Debug informationen verfügbar.")]

        user = self._manager.get_user(uid, with_subscriptions=True)

        return [BotResponse(f"<b>Debug Informationen</b>\n"
                            f"platform_id: {user.platform_id}\n"
                            f"user_id: {user.id}\n"
                            f"lang: {user.language}\n"
                            f"last_update: {user.last_update}\n"
                            f"subscriptions: {user.subscriptions}")]

    def get_all_user(self) -> List[BotUser]:
        return self._manager.get_all_user()

    def add_user_feedback(self, user_identification: Union[int, str], feedback: str) -> Optional[int]:
        user_id = self._manager.get_user_id(user_identification)
        return self._manager.add_feedback(user_id, feedback)

    def get_privacy_msg(self) -> List[BotResponse]:
        return [BotResponse("Unsere Datenschutzerklärung findest du hier: "
                            "https://github.com/eknoes/covid-bot/wiki/Datenschutz\n\n"
                            f"Außerdem kannst du mit dem Befehl {self.format_command('loeschmich')} alle deine bei uns gespeicherten "
                            "Daten löschen.")]

    @staticmethod
    def get_error_message() -> List[BotResponse]:
        return [BotResponse("Leider ist ein unvorhergesehener Fehler aufgetreten. Bitte versuche es erneut.")]

    @staticmethod
    def no_delete_user() -> List[BotResponse]:
        return [BotResponse("Deine Daten werden nicht gelöscht.")]

    def start_message(self, user_identification: Union[str, int], username="") -> List[BotResponse]:
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

        # Add subscription for Germany on start
        self._manager.add_subscription(self._manager.get_user_id(user_identification, create_if_not_exists=True), 0)
        return [BotResponse(message)]

    def help_message(self, user_identification: Union[str, int], username="") -> List[BotResponse]:
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
                    'Du kannst beliebig viele Orte abonnieren! Wenn du "Regeln" auswählst, erhältst du die aktuell '
                    'gütligen Regeln für dein Bundesland. '
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
        return [BotResponse(message)]

    @staticmethod
    def explain_message() -> List[BotResponse]:
        return [BotResponse("<b>Was bedeuten die Infektionszahlen?</b>\n"
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
                            "dem R-Wert. Die Daten über die Intensivbetten kommen DIVI-Intensivregister, die aktuellen Regeln "
                            "werden vom Kompetenzzentrum Tourismus des Bundes bezogen.\n"
                            "Diese laden wir automatisiert an den folgenden Stellen herunter:\n"
                            "• <a href='https://opendata.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0.csv'>Neuinfektionen</a>\n"
                            "• <a href='https://services.arcgis.com/OLiydejKCZTGhvWg/ArcGIS/rest/services/Impftabelle_mit_Zweitimpfungen/FeatureServer/0'>Impfdaten für Deutschland und die Bundesländer</a>\n"
                            "• <a href='https://impfdashboard.de'>Impfdaten für Deutschland</a>\n"
                            "• <a href='https://www.rki.de/DE/Content/InfAZ/N/Neuartiges_Coronavirus/Projekte_RKI/Nowcasting_Zahlen_csv.csv'>R-Wert</a>\n"
                            "• <a href='https://www.intensivregister.de/#/aktuelle-lage/reports'>Intensivregister</a>\n"
                            "• <a href='https://tourismus-wegweiser.de'>Tourismus-Wegweiser</a>")]

    def format_command(self, command: str):
        if command:
            return self.command_format.format(command=command)
