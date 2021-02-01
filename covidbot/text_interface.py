import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Callable, Dict, List, Union, Optional, Tuple

from covidbot.bot import Bot, UserDistrictActions
from covidbot.messenger_interface import MessengerInterface
from covidbot.utils import adapt_text


@dataclass
class BotResponse:
    message: str
    image: Optional[BytesIO] = None

    def __str__(self):
        return self.message


@dataclass
class Handler:
    command: str
    method: Callable[[str, str], BotResponse]


class ChatBotState:
    WAITING_FOR_COMMAND = 1
    WAITING_FOR_IS_FEEDBACK = 3
    WAITING_FOR_DELETE_ME = 4
    NOT_ACTIVATED = 5


class SimpleTextInterface(object):
    bot: Bot
    handler_list: List[Handler] = []
    chat_states: Dict[str, Tuple[ChatBotState, Optional[str]]] = {}
    log = logging.getLogger(__name__)

    def __init__(self, bot: Bot):
        self.bot = bot
        self.handler_list.append(Handler("start", self.startHandler))
        self.handler_list.append(Handler("hilfe", self.helpHandler))
        self.handler_list.append(Handler("/hilfe", self.helpHandler))
        self.handler_list.append(Handler("abo", self.subscribeHandler))
        self.handler_list.append(Handler("beende", self.unsubscribeHandler))
        self.handler_list.append(Handler("datenschutz", self.privacyHandler))
        self.handler_list.append(Handler("daten", self.currentDataHandler))
        self.handler_list.append(Handler("bericht", self.reportHandler))
        self.handler_list.append(Handler("statistik", self.statHandler))
        self.handler_list.append(Handler("loeschmich", self.deleteMeHandler))
        self.handler_list.append(Handler("", self.directHandler))

    def handle_input(self, user_input: str, user_id: str) -> Optional[BotResponse]:
        if user_id in self.chat_states.keys():
            state = self.chat_states[user_id]
            if state[0] == ChatBotState.WAITING_FOR_COMMAND:
                if user_input.strip().lower() in ["abo", "daten", "beende"]:
                    user_input += " " + str(state[1])
                del self.chat_states[user_id]
            elif state[0] == ChatBotState.WAITING_FOR_IS_FEEDBACK:
                if user_input.lower().strip() == "ja":
                    self.bot.add_user_feedback(user_id, state[1])
                    del self.chat_states[user_id]
                    return BotResponse("Danke für dein wertvolles Feedback!")
                else:
                    del self.chat_states[user_id]

                    if user_input.strip().lower()[:4] == "nein":
                        return BotResponse("Alles klar, deine Nachricht wird nicht weitergeleitet.")
            elif state[0] == ChatBotState.NOT_ACTIVATED:
                if self.bot.is_user_activated(user_id):
                    del self.chat_states[user_id]
                else:
                    return None
            elif state[0] == ChatBotState.WAITING_FOR_DELETE_ME:
                del self.chat_states[user_id]
                if user_input.strip().lower() == "ja":
                    return BotResponse(self.bot.delete_user(user_id))
                else:
                    return BotResponse(self.bot.no_delete_user())

        # Check whether user has to be activated
        if not self.bot.is_user_activated(user_id):
            self.chat_states[user_id] = (ChatBotState.NOT_ACTIVATED, None)
            return BotResponse("Dein Account wurde noch nicht aktiviert, bitte wende dich an die Entwickler. Bis diese "
                               "deinen Account aktivieren, kannst du den Bot leider noch nicht nutzen.")

        for handler in self.handler_list:
            if handler.command == user_input[:len(handler.command)].lower():
                text_in = user_input[len(handler.command):].strip()
                return handler.method(text_in, user_id)

    def startHandler(self, user_input: str, user_id: str) -> BotResponse:
        return BotResponse(self.bot.start_message(user_id))

    def helpHandler(self, user_input: str, user_id: str) -> BotResponse:
        return BotResponse(f'Hallo,\n'
                           f'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                           f'COVID19-Daten anzeigen lassen und sie dauerhaft abonnieren.\n\n'
                           f'<b>🔎 Orte finden</b>\n'
                           f'Schicke einfach eine Nachricht mit dem Ort, für den Du Informationen erhalten '
                           f'möchtest. So kannst du nach einer Stadt, Adresse oder auch dem Namen deiner '
                           f'Lieblingskneipe suchen.\n\n'
                           f'<b>📈 Informationen erhalten</b>\n'
                           f'Wählst du "Daten" aus, erhältst Du einmalig Informationen über diesen Ort. Diese '
                           f'enthalten eine Grafik, die für diesen Ort generiert wurde.\n'
                           f'Wählst du "Abo" aus, wird dieser Ort in deinem '
                           f'morgendlichen Tagesbericht aufgeführt. Hast du den Ort bereits abonniert, wird dir '
                           f'stattdessen angeboten, das Abo wieder zu beenden. '
                           f'Du kannst beliebig viele Orte abonnieren!'
                           f'\n\n'
                           f'<b>💬 Feedback</b>\n'
                           f'Wir freuen uns über deine Anregungen, Lob & Kritik! Sende dem Bot einfach eine '
                           f'Nachricht, du wirst dann gefragt ob diese an uns weitergeleitet werden darf!\n\n'
                           f'<b>🤓 Statistik</b>\n'
                           f'Wenn du "Statistik" sendest, erhältst du ein Beliebtheitsranking der Orte und ein '
                           f'paar andere Daten zu den aktuellen Nutzungszahlen des Bots.\n\n'
                           f'<b>Weiteres</b>\n'
                           f'• Sende "Bericht" um deinen Tagesbericht erneut zu erhalten\n'
                           f'• Sende "Abo" um deine abonnierten Orte einzusehen\n\n'
                           f'Mehr Informationen zu diesem Bot findest du hier: '
                           f'https://github.com/eknoes/covid-bot\n\n'
                           f'Diesen Hilfetext erhältst du über /hilfe')

    def parseLocationInput(self, location_query: str, set_feedback=None) -> Union[str, int]:
        message, locations = self.bot.find_district_id(location_query)
        if not locations:
            if set_feedback != 0:
                self.chat_states[set_feedback] = (ChatBotState.WAITING_FOR_IS_FEEDBACK, location_query)
                message += " Wenn du nicht nach einem Ort gesucht hast, sondern uns Feedback zukommen möchtest, " \
                           "antworte bitte \"Ja\". Deine Nachricht wird dann an die Entwickler weitergeleitet."
            return message

        elif len(locations) == 1:
            return locations[0][0]
        else:
            locations_list = message + "\n\n"
            for location in locations:
                locations_list += f"• {location[1]}\t{location[0]}\n"

            locations_list += "\n"
            locations_list += "Leider musst du deine Auswahl genauer angeben. Anstatt des kompletten Namens kannst du " \
                              f"auch die ID nutzen, also bspw. Abo {locations[0][0]} für {locations[0][1]}"
            return locations_list

    def subscribeHandler(self, user_input: str, user_id: str) -> BotResponse:
        if not user_input:
            message, locations = self.bot.get_overview(user_id)
            if locations:
                message += "\n"
                for loc in locations:
                    message += f"• {loc[1]}\t{loc[0]}\n"
            return BotResponse(message)
        location = self.parseLocationInput(user_input)
        if type(location) == int:
            return BotResponse(self.bot.subscribe(user_id, location))
        return BotResponse(location)

    def unsubscribeHandler(self, user_input: str, user_id: str) -> BotResponse:
        location = self.parseLocationInput(user_input)
        if type(location) == int:
            return BotResponse(self.bot.unsubscribe(user_id, location))
        return BotResponse(location)

    def currentDataHandler(self, user_input: str, user_id: str) -> BotResponse:
        location = self.parseLocationInput(user_input)
        if type(location) == int:
            message = self.bot.get_district_report(location)
            image = self.bot.get_graphical_report(location)
            return BotResponse(message, image)
        return BotResponse(location)

    def reportHandler(self, user_input: str, user_id: str) -> BotResponse:
        message = self.bot.get_report(user_id)
        graph = self.bot.get_graphical_report(0)
        return BotResponse(message, graph)

    def directHandler(self, user_input: str, user_id: str) -> BotResponse:
        location = self.parseLocationInput(user_input, set_feedback=user_id)
        if type(location) == int:
            self.chat_states[user_id] = (ChatBotState.WAITING_FOR_COMMAND, str(location))
            message, available_actions = self.bot.get_possible_actions(user_id, location)
            message += "\n\n"
            for action in available_actions:
                if action[1] == UserDistrictActions.REPORT:
                    message += '• Schreibe "Daten", um die aktuellen Daten zu erhalten\n'
                elif action[1] == UserDistrictActions.SUBSCRIBE:
                    message += '• Schreibe "Abo", um den Ort zu abonnieren\n'
                elif action[1] == UserDistrictActions.UNSUBSCRIBE:
                    message += '• Schreibe "Beende", dein Abo zu beenden\n'
            return BotResponse(message)
        return BotResponse(location)

    def statHandler(self, user_input: str, user_id: str) -> BotResponse:
        return BotResponse(self.bot.get_statistic())

    def privacyHandler(self, user_input: str, user_id: str) -> BotResponse:
        return BotResponse(self.bot.get_privacy_msg())

    def deleteMeHandler(self, user_input: str, user_id: str) -> BotResponse:
        self.chat_states[user_id] = (ChatBotState.WAITING_FOR_DELETE_ME, None)
        return BotResponse("Wenn alle deine bei uns gespeicherten Daten gelöscht werden sollen, antworte bitte mit Ja!")

    def getUpdates(self) -> List[Tuple[str, BotResponse]]:
        updates = self.bot.get_unconfirmed_daily_reports()
        graph = self.bot.get_graphical_report(0)
        return list(map(lambda x: (x[0], BotResponse(x[1], graph)), updates))

    def confirm_daily_report_send(self, user_identification: Union[int, str]):
        return self.bot.confirm_daily_report_send(user_identification)


class InteractiveInterface(SimpleTextInterface, MessengerInterface):
    async def sendMessageTo(self, message: str, users: List[Union[str, int]], append_report=False):
        print("Sending messages is not implemented for interactive interface")

    def sendDailyReports(self) -> None:
        print("Sending Daily reports is not implemented for interactive interface")

    def run(self) -> None:
        user_input = input("Please enter input:\n> ")
        while user_input != "":
            response = self.handle_input(user_input, '1')
            if response:
                print(f"{adapt_text(response.message)}")
            user_input = input("> ")
