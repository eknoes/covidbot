import logging
import re
from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import Callable, Dict, List, Union, Optional, Tuple, Generator

from covidbot.covid_data import CovidData, Visualization
from covidbot.covid_data.models import District, DistrictData
from covidbot.interfaces.bot_response import UserChoice, BotResponse
from covidbot.interfaces.messenger_interface import MessengerInterface
from covidbot.location_service import LocationService
from covidbot.metrics import BOT_COMMAND_COUNT
from covidbot.report_generator import ReportGenerator
from covidbot.settings import BotUserSettings
from covidbot.user_hint_service import UserHintService
from covidbot.user_manager import UserManager, BotUser
from covidbot.utils import adapt_text, format_float, format_int, format_noun, FormattableNoun, \
    format_data_trend, MessageType, message_type_name, message_type_desc


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
    report_generator: ReportGenerator

    def __init__(self, user_manager: UserManager, covid_data: CovidData, visualization: Visualization,
                 command_formatter: Callable[[str], str], has_location_feature: bool = False):
        self.user_manager = user_manager
        self.covid_data = covid_data
        self.visualization = visualization
        self.has_location_feature = has_location_feature
        self.command_formatter = command_formatter
        self.user_hints = UserHintService(self.command_formatter)

        self.report_generator = ReportGenerator(user_manager, covid_data, visualization, self.user_hints,
                                                command_formatter)

        self.handler_list.append(Handler("start", self.startHandler, True))
        self.handler_list.append(Handler("hilfe", self.helpHandler, True))
        self.handler_list.append(Handler("feedback", self.feedbackHandler, False))
        self.handler_list.append(Handler("info", self.infoHandler, False))
        self.handler_list.append(Handler("impfungen", self.vaccHandler, True))
        self.handler_list.append(Handler("abo", self.subscribeHandler, True))
        self.handler_list.append(Handler("berichte", self.subscribeReportHandler, True))
        self.handler_list.append(Handler("regeln", self.rulesHandler, True))
        self.handler_list.append(Handler("beende", self.unsubscribeHandler, True))
        self.handler_list.append(Handler("lösche", self.unsubscribeHandler, True))
        self.handler_list.append(Handler("datenschutz", self.privacyHandler, False))
        self.handler_list.append(Handler("daten", self.currentDataHandler, True))
        self.handler_list.append(Handler("historie", self.historyHandler, True))
        self.handler_list.append(Handler("bericht", self.reportHandler, True))
        self.handler_list.append(Handler("statistik", self.statHandler, False))
        self.handler_list.append(Handler("loeschmich", self.deleteMeHandler, False))
        self.handler_list.append(Handler("löschmich", self.deleteMeHandler, False))
        self.handler_list.append(Handler("stop", self.deleteMeHandler, False))
        self.handler_list.append(Handler("stopp", self.deleteMeHandler, False))
        self.handler_list.append(Handler("debug", self.debugHandler, False))
        self.handler_list.append(Handler("einstellungen", self.settingsHandler, True))
        self.handler_list.append(Handler("einstellung", self.settingsHandler, True))
        self.handler_list.append(Handler("grafik", self.graphicSettingsHandler, True))
        self.handler_list.append(Handler("daswaralles", self.thatsItHandler, False))
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
        user_id = self.user_manager.get_user_id(platform_id, create_if_not_exists=False)
        if not user_id:
            user_id = self.user_manager.get_user_id(platform_id, create_if_not_exists=True)
            if user_input.lower().find("start") == -1:
                user_input = "start"

        # Strip / on /command
        if user_input[0] == "/":
            user_input = user_input[1:]

        if user_id and user_id in self.chat_states.keys():
            state = self.chat_states[user_id]
            if state[0] == ChatBotState.WAITING_FOR_COMMAND:
                if user_input.strip().lower() in ["abo", "daten", "beende", "lösche", "regeln", "impfungen", "historie"]:
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
            choices.append(self.get_abort_userchoice())
            return [BotResponse("Die Daten für die folgenden Orte und Regionen sind für deinen Standort verfügbar",
                                choices=choices)]
        return self.handle_input(str(districts[0].id), user_id)

    def startHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('start').inc()
        if user_input == "los":
            return [BotResponse("Du kannst mir jederzeit einen Ortsnamen zusenden: Danach kannst du dich entscheiden, "
                                "ob du diesen abonnieren willst, oder nur einmalig aktuelle Daten oder Regeln angezeigt"
                                " bekommen möchtest."),
                    BotResponse("Für welchen Ort interessierst du dich?")]
        message = (f'Hallo,\n'
                   f'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                   f'COVID19-Daten anzeigen lassen und sie dauerhaft kostenlos abonnieren. Du erhältst dann jeden '
                   f'Morgen eine Zusammenfassung der Lage in deinen abonnierten Orten!')

        choices = [UserChoice("Loslegen", "/start los", "Sende einfach den Namen eines Ortes, den du abonnieren "
                                                        "möchtest oder zu dem du Informationen suchst",
                              alt_help="Ich funktioniere über Befehle, die du mir als Nachricht zusendest. "
                                       "Du kannst mir jederzeit einen Ort oder bspw. \"Hilfe\" zusenden. Weitere "
                                       "Aktionen werden dir unter den jeweiligen Nachrichten angezeigt."),
                   UserChoice("Infos zur Benutzung", "/hilfe", "Du kannst jederzeit \"Hilfe\" an den Bot senden, um "
                                                               "Informationen zur Benutzung angezeigt zu bekommen")]
        # Add subscription for Germany on start
        self.user_manager.add_subscription(user_id, 0)
        self.user_manager.add_report_subscription(user_id, MessageType.CASES_GERMANY)
        return [BotResponse(message, choices=choices)]

    @staticmethod
    def feedbackHandler(user_input: str, user_id: int) -> List[BotResponse]:
        return [BotResponse('Wir freuen uns über deine Anregungen, Lob & Kritik! Sende dem Bot einfach eine '
                            'Nachricht, du wirst dann gefragt ob diese an uns weitergeleitet werden darf!')]

    @staticmethod
    def thatsItHandler(user_input: str, user_id: int) -> List[BotResponse]:
        return [BotResponse('Alles klar! Wenn du weitere Informationen brauchst kannst du mir jederzeit einen Ort '
                            'oder "Hilfe" senden. Bis später 👋')]

    def helpHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('help').inc()
        short_help = True

        if user_input and re.match("plus|mehr|lang|erweitert[e]?", user_input.lower()):
            short_help = False

        message = 'Hallo,\n' \
                  'über diesen Bot kannst Du Dir relevante Daten zur COVID19-Pandemie anzeigen lassen ' \
                  'und sie dauerhaft abonnieren.\n\n'

        if short_help:
            message += 'Schicke mir einfach eine Nachricht mit dem Ort, für den Du Informationen erhalten ' \
                       'möchtest. '
            if self.has_location_feature:
                message += 'Du kannst auch einen Standort senden. '

            message += 'Die möglichen Aktionen werden dir dann angezeigt: Sei es den Ort zu abonnieren, dir die ' \
                       'aktuellen Daten anzuzeigen oder gültige Regeln abzurufen.\n\n'
            message += '<b>🔔 Berichte</b>\n' \
                       'Wenn du Orte abonnierst erhältst du am Morgen einen täglichen Bericht mit den ' \
                       'aktuellen Infektionsdaten in all deinen Orten. Zusätzlich kannst du auch Berichte zu ' \
                       'Impfungen und zur Intensivbettenlage abonnieren.\n\n' \
                       '<b>💬 Feedback</b>\n' \
                       'Wenn du Ideen, Kritik oder Probleme hast kannst du dich gerne bei uns melden: Sende einfach ' \
                       'eine Nachricht an den Covidbot, die keinen Ort enthält - du wirst dann gefragt, ob diese an ' \
                       'unser Team weitergeleitet werden darf.\n\n' \
                       '<b>📖 Mehr Informationen</b>\n' \
                       'Es gibt eine Vielzahl an weiteren Funktionen und Möglichkeiten: Lass dir dafür die erweiterte' \
                       ' Hilfe anzeigen. Wenn du uns weiterempfehlen möchtest, kannst du einfach den Link unserer ' \
                       'Website teilen: https://covidbot.d-64.org\n\n' \
                       'Diesen Text erhältst du immer, wenn du "Hilfe" als Nachricht an den Bot schickst.'
            choices = [UserChoice('Weitere Informationen', '/hilfe lang', 'Schreibe "Hilfe Lang", um alle Informationen'
                                                                          ' zur Benutzung zu erhalten')]
        else:
            message += ('<b>🔎 Orte finden</b>\n'
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
                        '<b>📖 Weitere Berichte</b>\n'
                        'Du kannst separat auch die Intensivbettenlage oder Impflage abonnieren. Du bekommst dann einen'
                        'zusätzlichen Bericht, wenn diese Daten erscheinen. Sende {berichte_command} um diese zu '
                        'verwalten.\n\n'
                        '<b>📈 Einmalig Informationen erhalten</b>\n'
                        'Sendest du "Daten", erhältst Du einmalig Informationen über den zuvor gewählten Ort. Diese '
                        'enthalten eine Grafik die für diesen Ort generiert wurde.\n'
                        'Wenn du "Regeln" sendest, erhältst du die aktuell gültigen Regeln für dein Bundesland. '
                        'Du kannst auch "Impfungen" senden, um einen Überblick über die Impflage zu bekommen. '
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
                .format(stat_command=self.command_formatter('Statistik'),
                        report_command=self.command_formatter('Bericht'),
                        abo_command=self.command_formatter('Abo'),
                        privacy_command=self.command_formatter('Datenschutz'),
                        help_command=self.command_formatter('Hilfe'), info_command=self.command_formatter('Info'),
                        vacc_command=self.command_formatter('Impfungen'),
                        deleteme_command=self.command_formatter('Loeschmich'),
                        abo_example=self.command_formatter('Abo ORT'),
                        beende_example=self.command_formatter('Beende ORT'),
                        berichte_command=self.command_formatter('Berichte'))
            choices = [UserChoice('Weniger Informationen', '/hilfe', 'Schreibe "Hilfe", um den Kurzüberblick über die '
                                                                     'Funktionen zu erhalten')]

        choices.append(UserChoice('Berichte', '/berichte', 'Schreibe "Berichte", um deine verschiedenen Berichte zu '
                                                           'verwalten'))
        choices.append(UserChoice('Einstellungen', '/einstellungen', 'Schreibe "Einstellungen", um deine '
                                                                     'Einstellungen zu ändern'))
        choices.append(self.get_default_userchoice())
        return [BotResponse(message, choices=choices)]

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

        if user_input:
            location = self.parseLocationInput(user_input, help_command="Impfungen")
            if location and type(location) != District:
                return location
            location = self.covid_data.get_district_data(location.id)
        else:
            location = self.covid_data.get_district_data(0)

        if not location.vaccinations and location.parent is not None:
            location = self.covid_data.get_district_data(location.parent)

        if not location.vaccinations:
            return [BotResponse(
                f"Leider kann für {location.name} keine Impfübersicht generiert werden, da keine Daten vorliegen.")]

        message = self.report_generator.get_vacc_text(location, show_name=True)
        message += "Verabreichte Erstimpfdosen: {vacc_partial}\n" \
                   "Verabreichte Zweitimpfdosen: {vacc_full}\n\n" \
            .format(vacc_partial=format_int(location.vaccinations.vaccinated_partial),
                    vacc_full=format_int(location.vaccinations.vaccinated_full))

        if location.id == 0:
            children_data = self.covid_data.get_children_data(location.id)
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
            message += "\n\n"
        else:
            earliest_data = location

        message += '<i>Stand: {earliest_vacc_date}. Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://impfdashboard.de/">Impfdashboard</a>. ' \
                   'Sende {info_command} um eine Erläuterung der Daten zu erhalten.</i>' \
            .format(info_command=self.command_formatter("Info"),
                    earliest_vacc_date=earliest_data.vaccinations.date.strftime("%d.%m.%Y"))
        graphs = [self.visualization.vaccination_graph(location.id)]

        if location.id == 0:
            graphs.append(self.visualization.vaccination_speed_graph(location.id))

        return [BotResponse(message, graphs)]

    def subscribeReportHandler(self, user_input: str, user_id: int) -> Union[BotResponse, List[BotResponse]]:
        BOT_COMMAND_COUNT.labels('report-types').inc()
        responses = []
        if user_input:
            user = self.user_manager.get_user(user_id, with_subscriptions=True)
            for item in [MessageType.CASES_GERMANY, MessageType.ICU_GERMANY, MessageType.VACCINATION_GERMANY]:
                if user_input.capitalize() == message_type_name(item)[:len(user_input)]:
                    if item not in user.subscribed_reports:
                        if self.user_manager.add_report_subscription(user_id, item):
                            self.user_manager.add_sent_report(user_id, item)
                            responses.append(BotResponse(f"Du erhältst nun Berichte für {message_type_name(item)}."))
                    else:
                        if self.user_manager.rm_report_subscription(user_id, item):
                            responses.append(
                                BotResponse(f"Du erhältst nun keine Berichte mehr zu {message_type_name(item)}."))

        user = self.user_manager.get_user(user_id, True)
        response = BotResponse("Du hast {report_count} abonniert. Jeder Bericht enthält individuelle "
                               "Grafiken und ist an deine abonnierten Orte angepasst. Du erhältst deine "
                               "personalisierten Berichte einmal am Tag: Direkt, wenn neue Daten verfügbar sind. "
                               "Sobald du den Impf- oder Intensivbericht aktiviert hast, werden dir diese Daten nicht "
                               "mehr im Infektionsbericht angezeigt. Dies kannst du danach aber in den Einstellungen "
                               "ändern!"
                               .format(report_count=format_noun(len(user.subscribed_reports), FormattableNoun.REPORT)))

        choices = []
        for item in [MessageType.CASES_GERMANY, MessageType.ICU_GERMANY, MessageType.VACCINATION_GERMANY]:
            if item in user.subscribed_reports:
                cmd = "/berichte"
                label_verb = "abbestellen"
                text_verb = "abzubestellen"
                status = "✅"
            else:
                cmd = "/berichte"
                label_verb = "abonnieren"
                text_verb = "zu abonnieren"
                status = "❎"
            response.message += f"\n\n<b>{message_type_name(item)}:</b> <i>{status}</i>\n{message_type_desc(item)}"

            choices.append(UserChoice(f'{message_type_name(item)} {label_verb}',
                                      f'{cmd} {message_type_name(item)}',
                                      f'Schreibe {self.command_formatter(f"{cmd[1:].capitalize()} {message_type_name(item)}")} um '
                                      f'den Bericht zu {message_type_name(item)} {text_verb}'))
        choices.append(UserChoice('Einstellungen', '/einstellungen', 'Schreibe "Einstellungen", um deine '
                                                                     'Einstellungen zu ändern'))
        choices.append(self.get_default_userchoice())
        response.choices = choices
        responses.append(response)
        return responses

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
                choices.append(self.get_abort_userchoice())
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
                        f"Du kannst <b>beliebig viele weitere Orte</b> abonnieren oder Daten einsehen, sende dafür einfach "
                        f"einen weiteren Ort! Außerdem kannst du verschiedene Arten von Berichten abonnieren, bspw. "
                        f"zur den Intensivbetten und den Impfungen in von dir abonnierten Orten.\n\n"
                        f"Wie du uns Feedback zusenden kannst, Statistiken einsehen oder weitere Aktionen ausführst "
                        f"erfährst du über den {self.command_formatter('Hilfe')} Befehl.\n"
                        f"Danke, dass du unseren Bot benutzt!")
                    choices.append(
                        UserChoice("Hilfe anzeigen", '/hilfe', f'Schreibe "Hilfe", um mehr Informationen zur '
                                                               f'Benutzung zu bekommen'))
                    choices.append(UserChoice("Berichte verwalten", '/berichte', f'Schreibe "Berichte", deine '
                                                                                 f'täglichen Berichte zu verwalten'))
                    choices.append(self.get_default_userchoice())
                    return [BotResponse(message.format(name=location.name), choices=choices)]
            else:
                message = "Du hast {name} bereits abonniert."

            choices.append(UserChoice("Daten anzeigen", f'/daten {location.id}',
                                      f'Schreibe "Daten {location.id}", um die aktuellen Daten zu erhalten'))
            choices.append(UserChoice("Regeln anzeigen", f'/regeln {location.id}',
                                      f'Schreibe "Regeln {location.id}", um die aktuell gültigen Regeln zu erhalten'))
            choices.append(UserChoice("Impfbericht anzeigen", f'/Impfungen {location.id}',
                                      f'Schreibe "Impfungen {location.id}", um den aktuellen Impfbericht zu erhalten'))
            choices.append(self.get_default_userchoice())

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

    def historyHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('history').inc()

        location = self.parseLocationInput(user_input, help_command="Historie")
        if not type(location) == District:
            return location

        data = self.covid_data.get_base_data(location.id)
        facts = self.covid_data.get_district_facts(location.id)

        message = f'''<b>Pandemieverlauf in {location.name}</b>
Am {facts.first_case_date.strftime("%d.%m.%Y")} wurde der erste Covid-19 Fall in {location.name} gemeldet, am {facts.first_death_date.strftime("%d.%m.%Y")} gab es den ersten Todesfall im Zusammenhang mit Covid-19. 
Insgesamt wurden bisher {format_noun(data.total_cases, FormattableNoun.INFECTIONS)} und {format_noun(data.total_deaths, FormattableNoun.DEATHS)} in {location.name} gemeldet.

• Höchste 7-Tage-Inzidenz: {format_float(facts.highest_incidence)} am {facts.highest_incidence_date.strftime("%d.%m.%Y")}
• Höchste Anzahl von Neuinfektionen an einem Tag: {format_int(facts.highest_cases)} am {facts.highest_cases_date.strftime("%d.%m.%Y")}
• Höchste Anzahl von Todesfällen an einem Tag: {format_int(facts.highest_deaths)} am {facts.highest_deaths_date.strftime("%d.%m.%Y")}

Stand: {data.date.strftime("%d.%m.%Y")}
Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0.
Weitere Informationen findest Du im <a href="https://corona.rki.de/">Dashboard des RKI</a>'''

        graphs = [self.visualization.infections_graph(location.id, 9999),
                  self.visualization.incidence_graph(location.id, 9999)]

        if self.covid_data.get_icu_data(location.id):
            graphs.append(self.visualization.icu_graph(location.id))
        return [BotResponse(message, images=graphs)]

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
            if current_data.incidence_interval_data:
                if current_data.incidence_interval_data.lower_threshold_days is not None:
                    message += " Die Inzidenz ist damit seit {days} ({working_days}) über {threshold}." \
                        .format(days=format_noun(current_data.incidence_interval_data.lower_threshold_days,
                                                 FormattableNoun.DAYS),
                                working_days=format_noun(
                                    current_data.incidence_interval_data.lower_threshold_working_days,
                                    FormattableNoun.WORKING_DAYS),
                                threshold=format_int(current_data.incidence_interval_data.lower_threshold))

                if current_data.incidence_interval_data.upper_threshold_days is not None:
                    if current_data.incidence_interval_data.lower_threshold_days is not None:
                        message = message[:-1] + " und "
                    else:
                        message += " Die Inzidenz ist damit "

                    message += "seit {days} ({working_days}) unter {threshold}." \
                        .format(days=format_noun(current_data.incidence_interval_data.upper_threshold_days,
                                                 FormattableNoun.DAYS),
                                working_days=format_noun(
                                    current_data.incidence_interval_data.upper_threshold_working_days,
                                    FormattableNoun.WORKING_DAYS),
                                threshold=format_int(current_data.incidence_interval_data.upper_threshold))

        if current_data.r_value:
            message += " Der 7-Tage-R-Wert liegt bei {r_value}{r_trend}." \
                .format(r_value=format_float(current_data.r_value.r_value_7day),
                        r_trend=format_data_trend(current_data.r_value.r_trend))
        message += "\n\n"
        message += "Neuinfektionen (seit gestern): {new_cases}{new_cases_trend}\n" \
                   "Infektionen seit Ausbruch der Pandemie: {total_cases}\n\n" \
                   "Neue Todesfälle (seit gestern): {new_deaths}{new_deaths_trend}\n" \
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
            message += self.report_generator.get_icu_text(current_data)
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

        if user_input:
            if user_input.lower() == message_type_name(MessageType.ICU_GERMANY)[:len(user_input)].lower():
                return self.report_generator.generate_icu_report(user)
            elif user_input.lower() == message_type_name(MessageType.VACCINATION_GERMANY)[:len(user_input)].lower():
                return self.report_generator.generate_vaccination_report(user)

        return self.report_generator.generate_infection_report(user)

    def directHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        location = self.parseLocationInput(user_input, set_feedback=user_id)
        if not type(location) == District:
            return location

        self.chat_states[user_id] = (ChatBotState.WAITING_FOR_COMMAND, str(location.id))
        choices = []

        user = self.user_manager.get_user(user_id, with_subscriptions=True)
        if user and location.id in user.subscriptions:
            choices.append(UserChoice("Beende Abo", f'/beende {location.id}',
                                      'Schreibe "Beende", dein Abo zu beenden'))
            verb = "beenden"
        else:
            choices.append(UserChoice('Abo hinzufügen', f'/abo {location.id}',
                                      'Schreibe "Abo", um den Ort zu abonnieren'))
            verb = "starten"

        choices.append(UserChoice("Daten anzeigen", f'/daten {location.id}',
                                  'Schreibe "Daten", um die aktuellen Daten zu erhalten'))
        choices.append(UserChoice('Regeln anzeigen', f'/regeln {location.id}',
                                  'Schreibe "Regeln", um die aktuell gültigen Regeln zu erhalten'))
        choices.append(UserChoice('Impfdaten anzeigen', f'/Impfungen {location.id}',
                                  'Schreibe "Impfungen", um den aktuellen Impfbericht zu erhalten'))
        choices.append(UserChoice("Historie anzeigen", f'/historie {location.id}',
                                  'Schreibe "Historie", um einen Rückblick zu erhalten'))
        choices.append(UserChoice('Abbrechen', f'/noop'))
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
                            f"last_update: {self.user_manager.get_last_updates(user.id, MessageType.CASES_GERMANY)}\n"
                            f"subscriptions: {user.subscriptions}\n"
                            f"reports: {[x.value for x in user.subscribed_reports]}")]

    def settingsHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('settings').inc()

        if user_input:
            user_input = user_input.split()
            for setting in [BotUserSettings.REPORT_INCLUDE_ICU, BotUserSettings.REPORT_INCLUDE_VACCINATION,
                            BotUserSettings.REPORT_EXTENSIVE_GRAPHICS, BotUserSettings.REPORT_ALL_INFECTION_GRAPHS,
                            BotUserSettings.REPORT_GRAPHICS, BotUserSettings.FORMATTING]:
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
                        return self.settingsHandler("", user_id) + [
                            BotResponse(f"{BotUserSettings.title(setting)} wurde {word}geschaltet.")]

                command_without_args = f'einstellung {BotUserSettings.command_key(setting)}'

                if self.user_manager.get_user_setting(user_id, setting):
                    option = "aus"
                    current = "ein"
                else:
                    option = "ein"
                    current = "aus"

                choice = [
                    UserChoice(BotUserSettings.title(setting) + f' {option}schalten',
                               '/' + command_without_args + f' {option}',
                               f'Sende zum {option}schalten {self.command_formatter(command_without_args + f" {option}")}')]

                return [BotResponse(f"<b>{BotUserSettings.title(setting)}:</b> {current}"
                                    f"\n{BotUserSettings.description(setting)}", choices=choice)]

            return [BotResponse("Ich verstehe deine Eingabe leider nicht.")] + self.settingsHandler("", user_id)
        else:
            message = "<b>Einstellungen</b>\n"
            message += "Mit den folgenden Einstellungen kannst du deinen Bericht konfigurieren: " \
                       "Beispielsweise kannst du den Absatz zu Intensivbetten oder zu Impfungen ein- und " \
                       "ausschalten. Du kannst auch alle Grafiken abschalten, oder dir mehr Grafiken zusenden lassen." \
                       "\n\nAußerdem kannst du nun separate Intensiv- und Impfberichte abonnieren: " \
                       f"Informationen dazu erhältst du, wenn du {self.command_formatter('Berichte')} sendest.\n\n"

            choices = []

            for setting in [BotUserSettings.REPORT_INCLUDE_ICU, BotUserSettings.REPORT_INCLUDE_VACCINATION,
                            BotUserSettings.REPORT_EXTENSIVE_GRAPHICS, BotUserSettings.REPORT_ALL_INFECTION_GRAPHS,
                            BotUserSettings.REPORT_GRAPHICS, BotUserSettings.FORMATTING]:
                if self.user_manager.get_user_setting(user_id, setting):
                    choice = "aus"
                    current = "✅"
                else:
                    choice = "ein"
                    current = "❎"

                command = f"einstellung {BotUserSettings.command_key(setting)} {choice}"
                choices.append(UserChoice(f"{BotUserSettings.title(setting)} {choice}schalten", '/' + command,
                                          f"Sende {self.command_formatter(command)}, um {BotUserSettings.title(setting)} "
                                          f"{choice}zuschalten"))
                message += f"<b>{BotUserSettings.title(setting)}: {current}</b>\n" \
                           f"{BotUserSettings.description(setting)}\n\n"
            choices.append(UserChoice("Berichte verwalten", '/berichte', f'Schreibe "Berichte", deine '
                                                                         f'täglichen Berichte zu verwalten'))
            choices.append(self.get_default_userchoice())
            return [BotResponse(message, choices=choices)]

    def graphicSettingsHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        return self.settingsHandler(BotUserSettings.command_key(BotUserSettings.REPORT_GRAPHICS) + ' ' + user_input,
                                    user_id)

    def deleteMeHandler(self, user_input: str, user_id: int) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('delete_me').inc()
        self.chat_states[user_id] = (ChatBotState.WAITING_FOR_DELETE_ME, None)
        choices = [UserChoice("Ja", "Ja", "Sende \"Ja\", um alle deine bei uns gespeicherten Daten von dir zu "
                                          "löschen"),
                   UserChoice("Abbrechen", "/noop", "Sende eine andere Nachricht, um keine Daten von dir zu löschen")]
        return [BotResponse("Möchtest du den täglichen Bericht abbestellen und alle von dir bei uns gespeicherten Daten"
                            " löschen?", choices=choices)]

    def _get_report(self, subscriptions: List[int], user_id: Optional[int] = None) -> List[BotResponse]:
        # Visualization
        graphs = []
        if self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_GRAPHICS):
            graphs.append(self.visualization.infections_graph(0))

        country = self.covid_data.get_country_data()
        message = "<b>Corona-Bericht vom {date}</b>\n\n".format(date=country.date.strftime("%d.%m.%Y"))
        message += self.report_generator.get_infection_text(country)

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

        if country.icu_data:  # and self.user_manager.get_user_setting(user_id, BotUserSettings.REPORT_INCLUDE_ICU):
            message += self.report_generator.get_icu_text(country)

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
                    new_cases=format_noun(district.new_cases, FormattableNoun.NEW_INFECTIONS),
                    new_deaths=format_noun(district.new_deaths, FormattableNoun.DEATHS))

    def get_available_user_messages(self) -> Generator[
        Tuple[MessageType, Union[int, str], List[BotResponse]], None, None]:
        """
        Needs to be called once in a while to check for new data. Returns a list of messages to be sent, if new data
        arrived
        :rtype: Optional[list[Tuple[str, str]]]
        :return: List of (userid, message)
        """
        for user in self.user_manager.get_all_user(with_subscriptions=True):
            for t in self.report_generator.get_available_reports(user):
                yield t, user.platform_id, self.report_generator.generate_report(user, t)

            if not user.activated:
                continue

            messages = self.user_manager.get_user_messages(user.id)
            if messages:
                responses = []
                for m in messages:
                    responses.append(BotResponse(UserHintService.format_commands(m, self.command_formatter)))
                yield MessageType.USER_MESSAGE, user.platform_id, responses

    def confirm_message_send(self, report_type: MessageType, user_id: Union[str, int]):
        user_id = self.user_manager.get_user_id(user_id)
        if user_id:
            if report_type == MessageType.USER_MESSAGE:
                self.user_manager.confirm_user_messages_sent(user_id)
            self.user_manager.add_sent_report(user_id, report_type)

    def user_messages_available(self) -> bool:
        """
        Checks whether there are messages for specific users available
        :rtype: bool
        :return: True if messages are available
        """
        for user in self.user_manager.get_all_user(with_subscriptions=True):
            for t in self.report_generator.get_available_reports(user):
                return True

            if self.user_manager.get_user_messages(user.id):
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
                                    UserChoice("Abbrechen", "/noop", "Sende \"Nein\", um abzubrechen")]
            return [response]

        elif len(locations) == 1:
            return locations[0]
        else:
            choices = self.generate_districts_choices(locations)
            choices.append(self.get_abort_userchoice())
            return [BotResponse(response.message, choices=choices)]

    @staticmethod
    def generate_districts_choices(districts: List[District]) -> List[UserChoice]:
        choices = []
        for location in districts:
            choices.append(UserChoice(location.name, str(location.id), f'{location.name}\t{location.id}',
                                      alt_help=f"Anstatt des kompletten Namens kannst du auch die Nummer hinter dem jeweiligen Ort schreiben, also "
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
                message = "Es wurden mehrere Orte mit diesem oder ähnlichen Namen gefunden, bitte sende uns eine " \
                          "genauere Ortsangabe:"
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

    @staticmethod
    def get_default_userchoice() -> UserChoice:
        return UserChoice("Das war alles, danke!", "/daswaralles")

    @staticmethod
    def get_abort_userchoice() -> UserChoice:
        return UserChoice("Abbrechen", "/noop")


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
                print(f"{adapt_text(str(response))}")
            user_input = input("> ")
