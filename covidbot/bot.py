import logging
import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from functools import reduce
from typing import Callable, Dict, List, Union, Optional, Tuple, Generator

from covidbot.covid_data import CovidData, Visualization
from covidbot.covid_data.models import District, DistrictData
from covidbot.location_service import LocationService
from covidbot.interfaces.messenger_interface import MessengerInterface
from covidbot.metrics import BOT_COMMAND_COUNT
from covidbot.user_hint_service import UserHintService
from covidbot.user_manager import UserManager, BotUser
from covidbot.settings import BotUserSettings
from covidbot.utils import adapt_text, format_float, format_int, format_noun, FormattableNoun, \
    format_data_trend, ReportType
from covidbot.interfaces.bot_response import UserChoice, BotResponse


class UserDistrictActions(Enum):
    SUBSCRIBE = 0
    UNSUBSCRIBE = 1
    REPORT = 2
    RULES = 3


@dataclass
class Handler:
    command: str
    method: Callable[[str, int], Optional[Union[BotResponse, List[BotResponse]]]]
    has_args: bool


class ChatBotState(Enum):
    WAITING_FOR_COMMAND = 1
    WAITING_FOR_IS_FEEDBACK = 3
    WAITING_FOR_DELETE_ME = 4
    NOT_ACTIVATED = 5


class Bot(object):
    user_manager: UserManager
    covid_data: CovidData
    visualization: Visualization
    user_hints: UserHintService
    has_location_feature: bool
    location_service: LocationService = LocationService('resources/germany_rs.geojson')
    command_formatter: Callable[[str], str]
    handler_list: List[Handler] = []
    chat_states: Dict[int, Tuple[ChatBotState, Optional[str]]] = {}
    log = logging.getLogger(__name__)

    def __init__(self, user_manager: UserManager, covid_data: CovidData, visualization: Visualization,
                 command_formatter: Callable[[str], str], has_location_feature: bool = False):
        self.user_manager = user_manager
        self.covid_data = covid_data
        self.visualization = visualization
        self.has_location_feature = has_location_feature
        self.command_formatter = command_formatter
        self.user_hints = UserHintService(self.command_formatter)
        self.handler_list.append(Handler("start", self.startHandler, False))
        self.handler_list.append(Handler("hilfe", self.helpHandler, False))
        self.handler_list.append(Handler("info", self.infoHandler, False))
        self.handler_list.append(Handler("impfungen", self.vaccHandler, False))
        self.handler_list.append(Handler("abo", self.subscribeHandler, True))
        self.handler_list.append(Handler("regeln", self.rulesHandler, True))
        self.handler_list.append(Handler("beende", self.unsubscribeHandler, True))
        self.handler_list.append(Handler("lösche", self.unsubscribeHandler, True))
        self.handler_list.append(Handler("datenschutz", self.privacyHandler, False))
        self.handler_list.append(Handler("daten", self.currentDataHandler, True))
        self.handler_list.append(Handler("bericht", self.reportHandler, False))
        self.handler_list.append(Handler("statistik", self.statHandler, False))
        self.handler_list.append(Handler("loeschmich", self.deleteMeHandler, False))
        self.handler_list.append(Handler("löschmich", self.deleteMeHandler, False))
        self.handler_list.append(Handler("stop", self.deleteMeHandler, False))
        self.handler_list.append(Handler("debug", self.debugHandler, False))
        self.handler_list.append(Handler("einstellungen", self.settingsHandler, True))
        self.handler_list.append(Handler("einstellung", self.settingsHandler, True))
        self.handler_list.append(Handler("grafik", self.graphicSettingsHandler, True))
        self.handler_list.append(Handler("beta", self.betaSettingsHandler, True))
        self.handler_list.append(Handler("noop", lambda x, y: None, False))
        self.handler_list.append(Handler("", self.directHandler, True))

    def delete_user(self, platform_id: Union[int, str]) -> List[BotResponse]:
        user_id = self.user_manager.get_user_id(platform_id, create_if_not_exists=False)
        if user_id:
            if self.user_manager.delete_user(user_id):
                return [BotResponse("Deine Daten wurden erfolgreich gelöscht.")]
        return [BotResponse("Zu deinem Account sind keine Daten vorhanden.")]

    def change_platform_id(self, old_platform_id: str, new_platform_id: str) -> bool:
        return self.user_manager.change_platform_id(old_platform_id, new_platform_id)

    def get_user_setting(self, user_identification: Union[int, str], setting: BotUserSettings) -> bool:
        user_id = self.user_manager.get_user_id(user_identification, create_if_not_exists=False)
        return self.user_manager.get_user_setting(user_id, setting)

    def disable_user(self, user_identification: Union[int, str]):
        user_id = self.user_manager.get_user_id(user_identification)
        if user_id:
            self.user_manager.set_user_activated(user_id, activated=False)

    def get_all_users(self) -> List[BotUser]:
        return self.user_manager.get_all_user()

    def handle_input(self, user_input: str, platform_id: str) -> List[BotResponse]:
        user_id = self.user_manager.get_user_id(platform_id, create_if_not_exists=True)
        # Strip / on /command
        if user_input[0] == "/":
            user_input = user_input[1:]

        if user_id and user_id in self.chat_states.keys():
            state = self.chat_states[user_id]
            if state[0] == ChatBotState.WAITING_FOR_COMMAND:
                if user_input.strip().lower() in ["abo", "daten", "beende", "lösche", "regeln"]:
                    user_input += " " + str(state[1])
                del self.chat_states[user_id]
            elif state[0] == ChatBotState.WAITING_FOR_IS_FEEDBACK:
                if user_input.lower().strip() == "ja":
                    self.user_manager.add_feedback(user_id, state[1].replace("<", "&lt;").replace(">", "&gt;"))
                    del self.chat_states[user_id]
                    BOT_COMMAND_COUNT.labels('send_feedback').inc()
                    return [BotResponse("Danke für dein wertvolles Feedback!")]
                else:
                    del self.chat_states[user_id]

                    if user_input.strip().lower()[:4] == "nein":
                        return [BotResponse("Alles klar, deine Nachricht wird nicht weitergeleitet.")]
            elif state[0] == ChatBotState.NOT_ACTIVATED:
                if self.user_manager.get_user(user_id) and self.user_manager.get_user(user_id).activated:
                    del self.chat_states[user_id]
                else:
                    return []
            elif state[0] == ChatBotState.WAITING_FOR_DELETE_ME:
                del self.chat_states[user_id]
                if user_input.strip().lower() == "ja":
                    BOT_COMMAND_COUNT.labels('delete_me').inc()
                    if self.user_manager.delete_user(user_id):
                        return [BotResponse("Deine Daten wurden erfolgreich gelöscht.")]
                    return [BotResponse("Zu deinem Account sind keine Daten vorhanden.")]
                else:
                    return [BotResponse("Deine Daten werden nicht gelöscht.")]

        # Check whether user has to be activated
        if user_id and not self.user_manager.get_user(user_id).activated:
            self.user_manager.set_user_activated(user_id, True)
            # self.chat_states[user_id] = (ChatBotState.NOT_ACTIVATED, None)
            # return [
            #    BotResponse("Dein Account wurde noch nicht aktiviert, bitte wende dich an die Entwickler. Bis diese "
            #                "deinen Account aktivieren, kannst du den Bot leider noch nicht nutzen.")]

        for handler in self.handler_list:
            if handler.command == user_input[:len(handler.command)].lower():
                # If no args should be given, check if input has no args. Otherwise it might be handled by
                # the direct message handler
                if not handler.has_args and not len(user_input.strip()) == len(handler.command):
                    continue

                text_in = user_input[len(handler.command):].strip()
                responses = handler.method(text_in, user_id)
                if type(responses) is BotResponse:
                    return [responses]

                if responses is None:
                    responses = []

                return responses

    def handle_geolocation(self, lon, lat, user_id) -> List[BotResponse]:
        district_id = self.location_service.find_rs(lon, lat)
        if not district_id:
            return [BotResponse(
                'Leider konnte kein Ort in den Corona Daten des RKI zu deinem Standort gefunden werden. Bitte beachte, '
                'dass Daten nur für Orte innerhalb Deutschlands verfügbar sind.')]
        districts = [self.covid_data.get_district(district_id)]
        parent = districts[0].parent
        if parent:
            districts.append(self.covid_data.get_district(parent))

        if len(districts) > 1:
            choices = self.generate_districts_choices(districts)
            return [BotResponse("Die Daten für die folgenden Orte und Regionen sind für deinen Standort verfügbar",
                                choices=choices)]
        return self.handle_input(str(districts[0].id), user_id)

    def startHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('start').inc()
        message = (f'Hallo,\n'
                   f'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                   f'COVID19-Daten anzeigen lassen und sie dauerhaft kostenlos abonnieren. '
                   f'Einen Überblick über alle Befehle erhältst du über {self.command_formatter("Hilfe")}.\n\n'
                   f'Schicke einfach eine Nachricht mit dem Ort, für den Du Informationen erhalten '
                   f'möchtest. Der Ort kann entweder ein Bundesland oder ein Stadt-/ Landkreis sein. ')
        if self.has_location_feature:
            message += f'Du kannst auch einen Standort senden! '

        message += (
            f'Wenn die Daten des Ortes nur gesammelt für eine übergeordneten Landkreis oder eine Region vorliegen, werden dir diese '
            f'vorgeschlagen. Du kannst beliebig viele Orte abonnieren und unabhängig von diesen '
            f' auch die aktuellen Zahlen für andere Orte ansehen.')

        # Add subscription for Germany on start
        self.user_manager.add_subscription(user_id, 0)
        return [BotResponse(message)]

    def helpHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('help').inc()
        message = ('Hallo,\n'
                   'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                   'COVID19-Daten anzeigen lassen und sie dauerhaft abonnieren.\n\n'
                   '<b>🔎 Orte finden</b>\n'
                   'Schicke einfach eine Nachricht mit dem Ort, für den Du Informationen erhalten '
                   'möchtest. So kannst du nach einer Stadt, Adresse oder auch dem Namen deiner '
                   'Lieblingskneipe suchen.')
        if self.has_location_feature:
            message += ' Du kannst auch einen Standort senden.'

        message += ('\n\n'
                    '<b>🔔 Täglicher Bericht</b>\n'
                    'Sendest du "Starte Abo", wird der von gewählte Ort in deinem '
                    'morgendlichen Tagesbericht aufgeführt. Hast du den Ort bereits abonniert, wird dir '
                    'stattdessen angeboten, das Abo wieder zu beenden. Alternativ kannst du auch {abo_example} oder '
                    '{beende_example} senden.\n'
                    'Du kannst beliebig viele Orte abonnieren!\n\n'
                    '<b>📈 Einmalig Informationen erhalten</b>\n'
                    'Sendest du "Daten", erhältst Du einmalig Informationen über den zuvor gewählten Ort. Diese '
                    'enthalten eine Grafik die für diesen Ort generiert wurde.\n'
                    'Wenn du "Regeln" sendest, erhältst du die aktuell gültigen Regeln für dein Bundesland. '
                    'Sende {info_command} um die Erläuterung zu den verschiedenen Daten und Quellen mit weiteren '
                    'Informationen zu erhalten.\n\n'
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
            .format(stat_command=self.command_formatter('Statistik'), report_command=self.command_formatter('Bericht'),
                    abo_command=self.command_formatter('Abo'), privacy_command=self.command_formatter('Datenschutz'),
                    help_command=self.command_formatter('Hilfe'), info_command=self.command_formatter('Info'),
                    vacc_command=self.command_formatter('Impfungen'),
                    deleteme_command=self.command_formatter('Loeschmich'),
                    abo_example=self.command_formatter('Abo ORT'), beende_example=self.command_formatter('Beende ORT'))
        return [BotResponse(message)]

    @staticmethod
    def infoHandler(user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('info').inc()
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

    def vaccHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('vaccinations').inc()
        district_id = 0  # TODO: Use arguments
        parent_data = self.covid_data.get_district_data(district_id)
        if not parent_data.vaccinations:
            return [BotResponse(
                f"Leider kann für {parent_data.name} keine Impfübersicht generiert werden, da keine Daten vorliegen.")]

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

        children_data = self.covid_data.get_children_data(district_id)
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
            .format(info_command=self.command_formatter("Info"),
                    earliest_vacc_date=earliest_data.vaccinations.date.strftime("%d.%m.%Y"))
        return [BotResponse(message, [self.visualization.vaccination_graph(district_id),
                                      self.visualization.vaccination_speed_graph(district_id)])]

    def subscribeHandler(self, user_input: str, user_id: int) -> Union[BotResponse, List[BotResponse]]:
        BOT_COMMAND_COUNT.labels('subscribe').inc()

        # Show overview if no arguments given
        if not user_input:
            user = self.user_manager.get_user(user_id, with_subscriptions=True)
            if not user or not user.subscriptions:
                message = "Du hast aktuell <b>keine</b> Orte abonniert. Mit <code>{subscribe_command}</code> kannst du " \
                          "Orte abonnieren, bspw. <code>{subscribe_command} Dresden</code> " \
                    .format(subscribe_command=self.command_formatter("abo"))
                districts = None
            else:
                districts = list(map(self.covid_data.get_district, user.subscriptions))
                message = "Du hast aktuell {abo_count} abonniert." \
                    .format(abo_count=format_noun(len(user.subscriptions), FormattableNoun.DISTRICT))

            response = BotResponse(message)

            if districts:
                choices = self.generate_districts_choices(districts)
                response.choices = choices
            return response

        location = self.parseLocationInput(user_input)
        if type(location) == District:
            choices = []
            if self.user_manager.add_subscription(user_id, location.id):
                message = "Dein Abonnement für {name} wurde erstellt."

                # Send detailed message on first subscription
                user = self.user_manager.get_user(user_id, True)
                if len(user.subscriptions) <= 2:
                    message += " "
                    message += (
                        f"Du kannst beliebig viele weitere Orte abonnieren oder Daten einsehen, sende dafür einfach "
                        f"einen weiteren Ort!\n\n"
                        f"Wie du uns Feedback zusenden kannst, Statistiken einsehen oder weitere Aktionen ausführst "
                        f"erfährst du über den {self.command_formatter('Hilfe')} Befehl. "
                        f"Danke, dass du unseren Bot benutzt!")
                    choices.append(UserChoice("Hilfe anzeigen", '/hilfe', f'Schreibe "Hilfe", um Informationen zur '
                                                                          f'Benutzung zu bekommen'))
            else:
                message = "Du hast {name} bereits abonniert."

            choices.append(UserChoice("Daten anzeigen", f'/daten {location.id}',
                                      f'Schreibe "Daten {location.id}", um die aktuellen Daten zu erhalten'))
            choices.append(UserChoice("Regeln anzeigen", f'/regeln {location.id}',
                                      f'Schreibe "Regeln {location.id}", um die aktuell gültigen Regeln zu erhalten'))
            choices.append(UserChoice("Abbrechen", f'/noop',
                                      f'Für mehr Optionen sende "Hilfe" oder einen beliebigen Ort'))

            return [BotResponse(message.format(name=location.name), choices=choices)]
        return location

    def unsubscribeHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('unsubscribe').inc()

        location = self.parseLocationInput(user_input, help_command='Beende')
        if type(location) == District:
            if self.user_manager.rm_subscription(user_id, location.id):
                message = "Dein Abonnement für {name} wurde beendet."
            else:
                message = "Du hast {name} nicht abonniert."
            return [BotResponse(message.format(name=location.name))]
        return location

    def rulesHandler(self, user_input: str, user_id: int) -> Union[BotResponse, List[BotResponse]]:
        BOT_COMMAND_COUNT.labels('rules').inc()

        location = self.parseLocationInput(user_input, help_command="Regeln")
        if type(location) == District:
            current_data = self.covid_data.get_district_data(location.id)
            rules, district_name = None, location.name
            if current_data.rules:
                rules = current_data.rules
                district_name = current_data.name

            if not rules and current_data.parent:
                parent = self.covid_data.get_district_data(current_data.parent)
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
        return location

    def currentDataHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('district_data').inc()

        location = self.parseLocationInput(user_input, help_command="Daten")
        if not type(location) == District:
            return location

        graphics = [self.visualization.infections_graph(location.id),
                    self.visualization.incidence_graph(location.id)]
        current_data = self.covid_data.get_district_data(location.id)
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
            message += f"<b>🏥 Intensivbetten</b>\n" \
                       f"{format_float(current_data.icu_data.percent_occupied())}% " \
                       f"({format_noun(current_data.icu_data.occupied_beds, FormattableNoun.BEDS)})" \
                       f"{format_data_trend(current_data.icu_data.occupied_beds_trend)} " \
                       f"der Intensivbetten sind aktuell belegt. " \
                       f"In {format_noun(current_data.icu_data.occupied_covid, FormattableNoun.BEDS)} " \
                       f"({format_float(current_data.icu_data.percent_covid())}%)" \
                       f"{format_data_trend(current_data.icu_data.occupied_covid_trend)} " \
                       f" liegen Patient:innen" \
                       f" mit COVID-19, davon müssen {format_noun(current_data.icu_data.covid_ventilated, FormattableNoun.PERSONS)}" \
                       f" ({format_float(current_data.icu_data.percent_ventilated())}%) invasiv beatmet werden. " \
                       f"Insgesamt gibt es {format_noun(current_data.icu_data.total_beds(), FormattableNoun.BEDS)}.\n\n"
            sources.append(f'Intensivbettenauslastung vom {current_data.icu_data.date.strftime("%d.%m.%Y")}. '
                           f'Daten vom <a href="https://intensivregister.de">DIVI-Intensivregister</a>.')
            graphics.append(self.visualization.icu_graph(current_data.id))

        related_vaccinations = None
        if current_data.vaccinations:
            related_vaccinations = current_data.vaccinations
            message += "<b>💉 Impfdaten</b>\n"
            # TODO: Daten fehlen
            # graphics.append(self.data_visualization.vaccination_graph(district_id))
        else:
            if current_data.parent:
                parent_district = self.covid_data.get_district_data(current_data.parent)
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
            parent_district = self.covid_data.get_district_data(current_data.parent)
            if parent_district and parent_district.rules:
                message += f"<b>👆 Regeln</b>\nDie wichtigsten Regeln für {parent_district.name} erhältst du mit dem " \
                           f"Befehl {self.command_formatter('Regeln ' + parent_district.name)}.\n\n"
        message += "<b>Quellen & Datenstand</b>\n"
        message += "\n\n".join(sources)
        message += '\nSende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten.' \
            .format(info_command=self.command_formatter("Info"), date=current_data.date.strftime("%d.%m.%Y"))

        return [BotResponse(message, graphics)]

    def reportHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('report').inc()
        user = self.user_manager.get_user(user_id, with_subscriptions=True)
        if not user:
            return self._get_report([])

        if self.user_manager.get_user_setting(user_id, BotUserSettings.BETA):
            return self._get_new_report(user.subscriptions, user_id)
        return self._get_report(user.subscriptions, user.id)

    def directHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        location = self.parseLocationInput(user_input, set_feedback=user_id)
        if not type(location) == District:
            return location

        self.chat_states[user_id] = (ChatBotState.WAITING_FOR_COMMAND, str(location.id))
        choices = [UserChoice('Regeln anzeigen', f'/regeln {location.id}',
                              'Schreibe "Regeln", um die aktuell gültigen Regeln zu erhalten'),
                   UserChoice("Daten anzeigen", f'/daten {location.id}',
                              'Schreibe "Daten", um die aktuellen Daten zu erhalten')]

        user = self.user_manager.get_user(user_id, with_subscriptions=True)
        if user and location.id in user.subscriptions:
            choices.append(UserChoice("Beende Abo", f'/beende {location.id}',
                                      'Schreibe "Beende", dein Abo zu beenden'))
            verb = "beenden"
        else:
            choices.append(UserChoice('Abo hinzufügen', f'/abo {location.id}',
                                      'Schreibe "Abo", um den Ort zu abonnieren'))
            verb = "starten"

        message = "Möchtest du dein Abo von {name} {verb}, die aktuellen Daten oder geltende Regeln erhalten?" \
            .format(name=location.name, verb=verb)
        return [BotResponse(message, choices=choices)]

    @staticmethod
    def get_error_message() -> BotResponse:
        return BotResponse("Leider ist ein unvorhergesehener Fehler aufgetreten. Bitte versuche es erneut.")

    def statHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('statistic').inc()
        message = "Aktuell nutzen {total_user} Personen diesen Bot, davon "
        platforms = self.user_manager.get_users_per_messenger()
        platforms.sort(key=lambda p: p[1], reverse=True)
        messenger_strings = [f"{c} über {m}" for m, c in platforms]
        message += ", ".join(messenger_strings[:-1])
        if messenger_strings[-1:]:
            message += f" und {messenger_strings[-1:][0]}. "
        else:
            message += '. '

        platforms = self.user_manager.get_users_per_network()
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
        for county in self.user_manager.get_ranked_subscriptions()[:10]:
            if county[0] == 1:
                message += f"{i}. {county[1]} ({county[0]} Abo)\n"
            else:
                message += f"{i}. {county[1]} ({county[0]} Abos)\n"
            i += 1
        message += "\nIm Durchschnitt hat ein:e Nutzer:in {mean} Orte abonniert, " \
                   "die höchste Anzahl an Abos liegt bei {most_subs}."
        message = message.format(total_user=self.user_manager.get_total_user_number(),
                                 mean=format_float(self.user_manager.get_mean_subscriptions()),
                                 most_subs=self.user_manager.get_most_subscriptions())

        message += "\n\nInformationen zur Nutzung des Bots auf anderen Plattformen findest du unter " \
                   "https://covidbot.d-64.org!"
        return [BotResponse(message, [self.visualization.bot_user_graph()])]

    def privacyHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('privacy').inc()
        return [BotResponse("Unsere Datenschutzerklärung findest du hier: "
                            "https://github.com/eknoes/covid-bot/wiki/Datenschutz\n\n"
                            f"Außerdem kannst du mit dem Befehl {self.command_formatter('loeschmich')} alle deine bei uns gespeicherten "
                            "Daten löschen.")]

    def debugHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('debug').inc()
        user = self.user_manager.get_user(user_id, with_subscriptions=True)

        if not user:
            return [BotResponse("Für dich sind aktuell keine Debug informationen verfügbar.")]

        return [BotResponse(f"<b>Debug Informationen</b>\n"
                            f"platform_id: {user.platform_id}\n"
                            f"user_id: {user.id}\n"
                            f"lang: {user.language}\n"
                            f"last_update: {self.user_manager.get_last_updates(user.id, ReportType.CASES_GERMANY)}\n"
                            f"subscriptions: {user.subscriptions}\n"
                            f"reports: {[x.value for x in user.subscribed_reports]}")]

    def settingsHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('settings').inc()

        if user_input:
            user_input = user_input.split()
            for setting in [BotUserSettings.BETA, BotUserSettings.REPORT_GRAPHICS, BotUserSettings.FORMATTING,
                            BotUserSettings.REPORT_INCLUDE_ICU, BotUserSettings.REPORT_INCLUDE_VACCINATION,
                            BotUserSettings.REPORT_EXTENSIVE_GRAPHICS]:
                if BotUserSettings.command_key(setting).lower() != user_input[0].lower():
                    continue

                if len(user_input) >= 2:
                    user_choice, word = None, None
                    if user_input[1][:3] == "ein" or user_input[1][:2] == "an":
                        user_choice = True
                        word = "ein"
                    elif user_input[1][:3] == "aus":
                        user_choice = False
                        word = "aus"

                    if user_choice is not None and word:
                        self.user_manager.set_user_setting(user_id, setting, user_choice)
                        return self.settingsHandler("", user_id) + [BotResponse(f"{BotUserSettings.title(setting)} wurde {word}geschaltet.")]

                command_without_args = f'einstellung {BotUserSettings.command_key(setting)}'

                if self.user_manager.get_user_setting(user_id, setting):
                    option = "aus"
                    current = "ein"
                else:
                    option = "ein"
                    current = "aus"

                choice = [
                    UserChoice(BotUserSettings.title(setting) + f' {option}schalten', '/' + command_without_args + f' {option}',
                               f'Sende zum {option}schalten {self.command_formatter(command_without_args + f" {option}")}')]

                return [BotResponse(f"<b>{BotUserSettings.title(setting)}:</b> {current}"
                                    f"\n{BotUserSettings.description(setting)}", choices=choice)]

            return [BotResponse("Ich verstehe deine Eingabe leider nicht.")] + self.settingsHandler("", user_id)
        else:
            message = "<b>Einstellungen</b>\n"
            choices = []

            for setting in [BotUserSettings.BETA, BotUserSettings.REPORT_GRAPHICS, BotUserSettings.FORMATTING,
                            BotUserSettings.REPORT_INCLUDE_ICU, BotUserSettings.REPORT_INCLUDE_VACCINATION,
                            BotUserSettings.REPORT_EXTENSIVE_GRAPHICS]:
                if self.user_manager.get_user_setting(user_id, setting):
                    choice = "aus"
                    current = "ein"
                else:
                    choice = "ein"
                    current = "aus"

                command = f"einstellung {BotUserSettings.command_key(setting)} {choice}"
                choices.append(UserChoice(f"{BotUserSettings.title(setting)} {choice}schalten", '/' + command,
                                          f"Sende {self.command_formatter(command)}, um {BotUserSettings.title(setting)} "
                                          f"{choice}zuschalten"))
                message += f"<b>{BotUserSettings.title(setting)}: {current}</b>\n" \
                           f"{BotUserSettings.description(setting)}\n\n"
            return [BotResponse(message, choices=choices)]

    def graphicSettingsHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        return self.settingsHandler(BotUserSettings.command_key(BotUserSettings.REPORT_GRAPHICS) + ' ' + user_input, user_id)

    def betaSettingsHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        return self.settingsHandler(BotUserSettings.command_key(BotUserSettings.BETA) + ' ' + user_input, user_id)

    def deleteMeHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('delete_me').inc()
        self.chat_states[user_id] = (ChatBotState.WAITING_FOR_DELETE_ME, None)
        choices = [UserChoice("Ja", "Ja", "Sende \"Ja\", um alle deine bei uns gespeicherten Daten von dir zu "
                                          "löschen"),
                   UserChoice("Abbrechen", "Nein", "Sende eine andere Nachricht, um keine Daten von dir zu löschen")]
        return [BotResponse("Möchtest du den täglichen Bericht abbestellen und alle von dir bei uns gespeicherten Daten"
                            " löschen?", choices=choices)]

    def _get_new_report(self, subscriptions: List[int], user_id: Optional[int] = None) -> List[BotResponse]:
        # Visualization
        graphs = []
        if self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_GRAPHICS):
            graphs.append(self.visualization.infections_graph(0))

        country = self.covid_data.get_country_data()
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
        message = message.format(date=self.covid_data.get_last_update().strftime("%d.%m.%Y"),
                                 new_cases=format_noun(country.new_cases, FormattableNoun.INFECTIONS),
                                 new_cases_trend=format_data_trend(country.cases_trend),
                                 new_deaths=format_noun(country.new_deaths, FormattableNoun.DEATHS),
                                 new_deaths_trend=format_data_trend(country.deaths_trend),
                                 incidence=format_float(country.incidence),
                                 incidence_trend=format_data_trend(country.incidence_trend))
        if subscriptions and len(subscriptions) > 0:
            # Split Bundeslaender from other
            districts = list(map(lambda rs: self.covid_data.get_district_data(rs), subscriptions))
            states = list(filter(lambda d: d.type == "Bundesland", districts))
            cities = list(filter(lambda d: d.type != "Bundesland" and d.type != "Staat", districts))
            districts = self.sort_districts(states) + self.sort_districts(cities)
            if len(districts) > 0:
                for district in districts:
                    message += "<b>{name}</b>: {incidence}{incidence_trend}" \
                        .format(name=district.name,
                                incidence=format_float(district.incidence),
                                incidence_trend=format_data_trend(district.incidence_trend))

                    if district.incidence_interval_since is not None:
                        date_interval = district.date - district.incidence_interval_since
                        if date_interval.days != 0:
                            days = format_noun(date_interval.days, FormattableNoun.DAYS)
                        else:
                            days = "heute"

                        if district.incidence < district.incidence_interval_threshold:
                            word = "unter"
                        else:
                            word = "über"

                        message += "\n• Seit {interval_length} {word} {interval}" \
                            .format(interval_length=days, interval=district.incidence_interval_threshold, word=word)

                    message += "\n• {new_cases}, {new_deaths}" \
                        .format(new_cases=format_noun(district.new_cases, FormattableNoun.INFECTIONS),
                                new_deaths=format_noun(district.new_deaths, FormattableNoun.DEATHS))
                    if (district.new_cases and district.new_cases < 0) or (
                            district.new_deaths and district.new_deaths < 0):
                        message += "\n• <i>Eine negative Differenz zum Vortag ist idR. auf eine Korrektur der Daten " \
                                   "durch das Gesundheitsamt zurückzuführen</i>"
                    if district.icu_data:
                        message += "\n• {percent_occupied}% ({beds_occupied}){occupied_trend} belegt, in {percent_covid}% ({beds_covid}){covid_trend} Covid19-Patient:innen, {clear_beds} frei" \
                            .format(beds_occupied=format_noun(district.icu_data.occupied_beds, FormattableNoun.BEDS),
                                    percent_occupied=format_float(district.icu_data.percent_occupied()),
                                    occupied_trend=format_data_trend(district.icu_data.occupied_beds_trend),
                                    beds_covid=format_noun(district.icu_data.occupied_covid, FormattableNoun.BEDS),
                                    clear_beds=format_noun(district.icu_data.clear_beds, FormattableNoun.BEDS),
                                    percent_covid=format_float(district.icu_data.percent_covid()),
                                    covid_trend=format_data_trend(district.icu_data.occupied_covid_trend))

                    if district.vaccinations:
                        message += "\n• {no_doses} Neuimpfungen, {vacc_partial}% min. eine, {vacc_full}% beide Impfungen erhalten" \
                            .format(no_doses=format_int(district.vaccinations.doses_diff),
                                    vacc_partial=format_float(district.vaccinations.partial_rate * 100),
                                    vacc_full=format_float(district.vaccinations.full_rate * 100),
                                    )
                    message += "\n\n"
            if self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_GRAPHICS):
                # Generate multi-incidence graph for up to 8 districts
                districts = subscriptions[-8:]
                if 0 in subscriptions and 0 not in districts:
                    districts[0] = 0
                graphs.append(self.visualization.multi_incidence_graph(districts))

        if country.vaccinations and self.user_manager.get_user_setting(user_id,
                                                                       BotUserSettings.REPORT_INCLUDE_VACCINATION,
                                                                       ):
            message += "<b>💉 Impfdaten</b>\n" \
                       "Am {date} wurden {doses} Dosen verimpft. So haben {vacc_partial} ({rate_partial}%) Personen in Deutschland mindestens eine Impfdosis " \
                       "erhalten, {vacc_full} ({rate_full}%) Menschen sind bereits vollständig geimpft. " \
                       "Bei dem Impftempo der letzten 7 Tage werden {vacc_speed} Dosen pro Tag verabreicht und in " \
                       "{vacc_days_to_finish} Tagen wäre die gesamte Bevölkerung vollständig geschützt." \
                       "\n\n" \
                .format(rate_full=format_float(country.vaccinations.full_rate * 100),
                        rate_partial=format_float(country.vaccinations.partial_rate * 100),
                        vacc_partial=format_int(country.vaccinations.vaccinated_partial),
                        vacc_full=format_int(country.vaccinations.vaccinated_full),
                        date=country.vaccinations.date.strftime("%d.%m.%Y"),
                        doses=format_int(country.vaccinations.doses_diff),
                        vacc_speed=format_int(country.vaccinations.avg_speed),
                        vacc_days_to_finish=format_int(country.vaccinations.avg_days_to_finish))
            if self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_EXTENSIVE_GRAPHICS):
                graphs.append(self.visualization.vaccination_graph(country.id))
                graphs.append(self.visualization.vaccination_speed_graph(country.id))

        if country.icu_data and self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_INCLUDE_ICU):
            message += f"<b>🏥 Intensivbetten</b>\n" \
                       f"{format_float(country.icu_data.percent_occupied())}% " \
                       f"({format_noun(country.icu_data.occupied_beds, FormattableNoun.BEDS)})" \
                       f"{format_data_trend(country.icu_data.occupied_beds_trend)} " \
                       f"der Intensivbetten sind aktuell belegt. " \
                       f"In {format_noun(country.icu_data.occupied_covid, FormattableNoun.BEDS)} " \
                       f"({format_float(country.icu_data.percent_covid())}%)" \
                       f"{format_data_trend(country.icu_data.occupied_covid_trend)} " \
                       f" liegen Patient:innen" \
                       f" mit COVID-19, davon müssen {format_noun(country.icu_data.covid_ventilated, FormattableNoun.PERSONS)}" \
                       f" ({format_float(country.icu_data.percent_ventilated())}%) invasiv beatmet werden. " \
                       f"Insgesamt gibt es {format_noun(country.icu_data.total_beds(), FormattableNoun.BEDS)}.\n\n"
            if self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_EXTENSIVE_GRAPHICS):
                graphs.append(self.visualization.icu_graph(country.id))

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
                   'Fortschritt</a>.</i>'.format(info_command=self.command_formatter("Info"))

        message += '\n\n🧒🏽👦🏻 Sharing is caring 👩🏾🧑🏼 <a href="https://covidbot.d-64.org">www.covidbot.d-64.org</a>'

        message += "\n\n<b>Danke für das bisherige Feedback! Wir haben den Bericht jetzt auch konfigurierbar gemacht, " \
                   "so kann man bspw. einstellen, ob man den Impfüberblick oder die Intensivbettenlage sehen möchte. " \
                   f"Sende einfach {self.command_formatter('Einstellungen')} um einen Überblick über die Optionen zu " \
                   f"erhalten. Wir würden uns sehr über Feedback " \
                   "freuen, sende uns einfach eine Nachricht. Danke 🙏</b>"

        reports = [BotResponse(message, graphs)]
        return reports

    def _get_report(self, subscriptions: List[int], user_id: Optional[int] = None) -> List[BotResponse]:
        # Visualization
        graphs = []
        if self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_GRAPHICS):
            graphs.append(self.visualization.infections_graph(0))

        country = self.covid_data.get_country_data()
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
        message = message.format(date=self.covid_data.get_last_update().strftime("%d.%m.%Y"),
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
            subscription_data = list(map(lambda rs: self.covid_data.get_district_data(rs), subscriptions))
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

            if self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_GRAPHICS):
                # Generate multi-incidence graph for up to 8 districts
                districts = subscriptions[-8:]
                if 0 in subscriptions and 0 not in districts:
                    districts[0] = 0
                graphs.append(self.visualization.multi_incidence_graph(districts))

        if country.vaccinations and self.user_manager.get_user_setting(user_id,
                                                                       BotUserSettings.REPORT_INCLUDE_VACCINATION):
            message += "<b>💉 Impfdaten</b>\n" \
                       "Am {date} wurden {doses} Dosen verimpft. So haben {vacc_partial} ({rate_partial}%) Personen in Deutschland mindestens eine Impfdosis " \
                       "erhalten, {vacc_full} ({rate_full}%) Menschen sind bereits vollständig geimpft.\n\n" \
                .format(rate_full=format_float(country.vaccinations.full_rate * 100),
                        rate_partial=format_float(country.vaccinations.partial_rate * 100),
                        vacc_partial=format_int(country.vaccinations.vaccinated_partial),
                        vacc_full=format_int(country.vaccinations.vaccinated_full),
                        date=country.vaccinations.date.strftime("%d.%m.%Y"),
                        doses=format_int(country.vaccinations.doses_diff))
            if self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_EXTENSIVE_GRAPHICS):
                graphs.append(self.visualization.vaccination_graph(country.id))
                graphs.append(self.visualization.vaccination_speed_graph(country.id))

        if country.icu_data and self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_INCLUDE_ICU):
            message += f"<b>🏥 Intensivbetten</b>\n" \
                       f"{format_float(country.icu_data.percent_occupied())}% " \
                       f"({format_noun(country.icu_data.occupied_beds, FormattableNoun.BEDS)})" \
                       f"{format_data_trend(country.icu_data.occupied_beds_trend)} " \
                       f"der Intensivbetten sind aktuell belegt. " \
                       f"In {format_noun(country.icu_data.occupied_covid, FormattableNoun.BEDS)} " \
                       f"({format_float(country.icu_data.percent_covid())}%)" \
                       f"{format_data_trend(country.icu_data.occupied_covid_trend)} " \
                       f" liegen Patient:innen" \
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
                   'Fortschritt</a>.</i>'.format(info_command=self.command_formatter("Info"))

        message += '\n\n🧒🏽👦🏻 Sharing is caring 👩🏾🧑🏼 <a href="https://covidbot.d-64.org">www.covidbot.d-64.org</a>'

        reports = [BotResponse(message, graphs)]
        return reports

    @staticmethod
    def format_district_data(district: DistrictData) -> str:
        return "{name}: {incidence}{incidence_trend} ({new_cases}, {new_deaths})" \
            .format(name=district.name,
                    incidence=format_float(district.incidence),
                    incidence_trend=format_data_trend(district.incidence_trend),
                    new_cases=format_noun(district.new_cases, FormattableNoun.INFECTIONS),
                    new_deaths=format_noun(district.new_deaths, FormattableNoun.DEATHS))

    def get_available_user_messages(self) -> Generator[ReportType, Tuple[Union[int, str], List[BotResponse]], None, None]:
        """
        Needs to be called once in a while to check for new data. Returns a list of messages to be sent, if new data
        arrived
        :rtype: Optional[list[Tuple[str, str]]]
        :return: List of (userid, message)
        """
        users = []
        data_update = self.covid_data.get_last_update()
        for user in self.user_manager.get_all_user(with_subscriptions=True):
            if not user.activated or not user.subscriptions or user.created.date() == date.today():
                continue

            if ReportType.CASES_GERMANY in user.subscribed_reports:
                last_update = self.user_manager.get_last_updates(user.id, ReportType.CASES_GERMANY)
                if not last_update or last_update.date() < data_update:
                    users.append((user, ReportType.CASES_GERMANY))

        for user, report in users:
            if report == ReportType.CASES_GERMANY:
                if self.user_manager.get_user_setting(user.id, BotUserSettings.BETA):
                    yield ReportType.CASES_GERMANY, user.platform_id, self._get_new_report(user.subscriptions, user.id)
                else:
                    yield ReportType.CASES_GERMANY, user.platform_id, self._get_report(user.subscriptions, user.id)
            else:
                self.log.error(f"Unknown report type for user {user.id}: {report}")

    def confirm_message_send(self, report_type: ReportType, user_id: Union[str, int]):
        user_id = self.user_manager.get_user_id(user_id)
        if user_id:
            self.user_manager.add_sent_report(user_id, report_type)

    def user_messages_available(self) -> bool:
        """
        Checks whether there are messages for specific users available
        :rtype: bool
        :return: True if messages are available
        """
        data_update = self.covid_data.get_last_update()
        for user in self.user_manager.get_all_user(with_subscriptions=True):
            if not user.activated or not user.subscriptions or user.created.date() == date.today():
                continue

            if ReportType.CASES_GERMANY in user.subscribed_reports:
                last_update = self.user_manager.get_last_updates(user.id, ReportType.CASES_GERMANY)
                if not last_update or last_update.date() < data_update:
                    return True
        return False

    def parseLocationInput(self, location_query: str, set_feedback=None, help_command="Befehl") -> Union[
        List[BotResponse], District]:
        if not location_query:
            return [BotResponse(
                f'Dieser Befehl benötigt eine Ortsangabe, sende {self.command_formatter(help_command + " Ort")}')]

        response, locations = self.find_district_id(location_query)
        if not locations:
            if set_feedback != 0:
                self.chat_states[set_feedback] = (ChatBotState.WAITING_FOR_IS_FEEDBACK, location_query)
                response.message += " Wenn du nicht nach einem Ort gesucht hast, sondern uns Feedback zukommen möchtest, " \
                                    "kannst du diese Nachricht an die Entwickler weiterleiten."
                response.choices = [UserChoice("Feedback weiterleiten", "Ja", "Sende \"Ja\", um deine Nachricht als "
                                                                              "Feedback weiterzuleiten"),
                                    UserChoice("Abbrechen", "Nein", "Sende \"Nein\", um abzubrechen")]
            return [response]

        elif len(locations) == 1:
            return locations[0]
        else:
            choices = self.generate_districts_choices(locations)
            return [BotResponse(response.message, choices=choices)]

    @staticmethod
    def generate_districts_choices(districts: List[District]) -> List[UserChoice]:
        choices = []
        for location in districts:
            choices.append(UserChoice(location.name, str(location.id), f'{location.name}\t{location.id}',
                                      alt_help=f"Anstatt des kompletten Namens kannst du auch die zugeordnete Nummer nutzen, also "
                                               f"bspw. {location.id} für {location.name}."))
        return choices

    def find_district_id(self, district_query: str) -> Tuple[Optional[BotResponse], Optional[List[District]]]:
        if not district_query:
            return BotResponse('Dieser Befehl benötigt eine Ortsangabe, sende "(Befehl) (Ort)"'), None

        possible_district = self.covid_data.search_district_by_name(district_query)
        online_match = False

        # If e.g. emojis or ?! are part of query, we do not have to query online
        if not possible_district and re.match("^[\w,()\-. ]*$", district_query):
            online_match = True
            osm_results = self.location_service.find_location(district_query)
            possible_district = []
            for district_id in osm_results:
                possible_district.append(self.covid_data.get_district(district_id))

        if not possible_district:
            message = 'Leider konnte kein Ort gefunden werden. Bitte beachte, ' \
                      'dass Daten nur für Orte innerhalb Deutschlands verfügbar sind. Mit {help_cmd} erhältst du ' \
                      'einen Überblick über die Funktionsweise des Bots.' \
                .format(location=district_query, help_cmd=self.command_formatter("Hilfe"))
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


class InteractiveInterface(MessengerInterface):
    bot: Bot

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_message_to_users(self, message: str, users: List[Union[str, int]], append_report=False):
        print("Sending messages is not implemented for interactive interface")

    def send_unconfirmed_reports(self) -> None:
        print("Sending Daily reports is not implemented for interactive interface")

    def run(self) -> None:
        user_input = input("Please enter input:\n> ")
        while user_input != "":
            responses = self.bot.handle_input(user_input, '1')
            for response in responses:
                print(f"{adapt_text(response)}")
            user_input = input("> ")
