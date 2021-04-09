import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Union, Optional, Tuple

from covidbot.bot import Bot, UserDistrictActions
from covidbot.covid_data.models import District
from covidbot.messenger_interface import MessengerInterface
from covidbot.metrics import BOT_COMMAND_COUNT
from covidbot.utils import adapt_text, BotResponse, UserChoice


@dataclass
class Handler:
    command: str
    method: Callable[[str, str], Union[BotResponse, List[BotResponse]]]
    has_args: bool


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
        self.handler_list.append(Handler("", self.directHandler, True))

    def handle_input(self, user_input: str, user_id: str) -> Optional[List[BotResponse]]:
        # Strip / on /command
        if user_input[0] == "/":
            user_input = user_input[1:]

        if user_id in self.chat_states.keys():
            state = self.chat_states[user_id]
            if state[0] == ChatBotState.WAITING_FOR_COMMAND:
                if user_input.strip().lower() in ["abo", "daten", "beende", "lösche", "regeln"]:
                    user_input += " " + str(state[1])
                del self.chat_states[user_id]
            elif state[0] == ChatBotState.WAITING_FOR_IS_FEEDBACK:
                if user_input.lower().strip() == "ja":
                    self.bot.add_user_feedback(user_id, state[1])
                    del self.chat_states[user_id]
                    BOT_COMMAND_COUNT.labels('send_feedback').inc()
                    return [BotResponse("Danke für dein wertvolles Feedback!")]
                else:
                    del self.chat_states[user_id]

                    if user_input.strip().lower()[:4] == "nein":
                        return [BotResponse("Alles klar, deine Nachricht wird nicht weitergeleitet.")]
            elif state[0] == ChatBotState.NOT_ACTIVATED:
                if self.bot.is_user_activated(user_id):
                    del self.chat_states[user_id]
                else:
                    return None
            elif state[0] == ChatBotState.WAITING_FOR_DELETE_ME:
                del self.chat_states[user_id]
                if user_input.strip().lower() == "ja":
                    BOT_COMMAND_COUNT.labels('delete_me').inc()
                    return self.bot.delete_user(user_id)
                else:
                    return self.bot.no_delete_user()

        # Check whether user has to be activated
        if not self.bot.is_user_activated(user_id):
            self.chat_states[user_id] = (ChatBotState.NOT_ACTIVATED, None)
            return [
                BotResponse("Dein Account wurde noch nicht aktiviert, bitte wende dich an die Entwickler. Bis diese "
                            "deinen Account aktivieren, kannst du den Bot leider noch nicht nutzen.")]

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
                return responses

    def startHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('start').inc()
        return self.bot.start_message(user_id)

    def helpHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('help').inc()
        return self.bot.help_message(user_id)

    def infoHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('info').inc()
        return self.bot.explain_message()

    def vaccHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('vaccinations').inc()
        return self.bot.get_vaccination_overview(0)

    def parseLocationInput(self, location_query: str, set_feedback=None) -> Union[List[BotResponse], District]:
        response, locations = self.bot.find_district_id(location_query)
        if not locations:
            if set_feedback != 0:
                self.chat_states[set_feedback] = (ChatBotState.WAITING_FOR_IS_FEEDBACK, location_query)
                response.message += " Wenn du nicht nach einem Ort gesucht hast, sondern uns Feedback zukommen möchtest, " \
                                    "antworte bitte \"Ja\". Deine Nachricht wird dann an die Entwickler weitergeleitet."
            return [response]

        elif len(locations) == 1:
            return locations[0]
        else:
            choices = []
            locations_list = response.message + "\n\n"
            for location in locations:
                locations_list += f"• {location.name}\t{location.id}\n"
                choices.append(UserChoice(location.name, str(location.id)))
            locations_list += "\n"
            locations_list += "Leider musst du deine Auswahl genauer angeben. Anstatt des kompletten Namens kannst du " \
                              f"auch die ID nutzen, also bspw. Abo {locations[0].id} für {locations[0].name}"
            return [BotResponse(locations_list, choices=choices)]

    def subscribeHandler(self, user_input: str, user_id: str) -> Union[BotResponse, List[BotResponse]]:
        BOT_COMMAND_COUNT.labels('subscribe').inc()
        if not user_input:
            response, locations = self.bot.get_overview(user_id)
            if locations:
                response.message += "\n"
                for loc in locations:
                    response.message += f"• {loc.name}\t{loc.id}\n"
            return response

        location = self.parseLocationInput(user_input)
        if type(location) == District:
            return self.bot.subscribe(user_id, location.id)
        return location

    def rulesHandler(self, user_input: str, user_id: str) -> Union[BotResponse, List[BotResponse]]:
        BOT_COMMAND_COUNT.labels('rules').inc()
        if not user_input:
            return [BotResponse("Dieser Befehl benötigt eine Ortsangabe.")]

        location = self.parseLocationInput(user_input)
        if type(location) == District:
            return self.bot.get_rules(location.id)
        return location

    def unsubscribeHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('unsubscribe').inc()
        if not user_input:
            return [BotResponse("Dieser Befehl benötigt eine Ortsangabe.")]

        location = self.parseLocationInput(user_input)
        if type(location) == District:
            return self.bot.unsubscribe(user_id, location.id)
        return location

    def currentDataHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('district_data').inc()

        if not user_input:
            return [BotResponse("Dieser Befehl benötigt eine Ortsangabe.")]

        location = self.parseLocationInput(user_input)
        if type(location) == District:
            return self.bot.get_district_report(location.id)
        return location

    def reportHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('report').inc()
        return self.bot.get_report(user_id)

    def directHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        location = self.parseLocationInput(user_input, set_feedback=user_id)
        if type(location) == District:
            self.chat_states[user_id] = (ChatBotState.WAITING_FOR_COMMAND, str(location.id))
            message, available_actions = self.bot.get_possible_actions(user_id, location.id)
            message += "\n\n"
            choices = []
            for action_name, action in available_actions:
                if action == UserDistrictActions.REPORT:
                    choices.append(UserChoice(action_name, f'/daten {location.id}'))
                    message += '• Schreibe "Daten", um die aktuellen Daten zu erhalten\n'
                elif action == UserDistrictActions.SUBSCRIBE:
                    choices.append(UserChoice(action_name, f'/abo {location.id}'))
                    message += '• Schreibe "Abo", um den Ort zu abonnieren\n'
                elif action == UserDistrictActions.UNSUBSCRIBE:
                    choices.append(UserChoice(action_name, f'/beende {location.id}'))
                    message += '• Schreibe "Beende", dein Abo zu beenden\n'
                elif action == UserDistrictActions.RULES:
                    choices.append(UserChoice(action_name, f'/regeln {location.id}'))
                    message += '• Schreibe "Regeln", um die aktuell gültigen Regeln zu erhalten\n'
            return [BotResponse(message, choices=choices)]
        return location

    def statHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('statistic').inc()
        return self.bot.get_statistic()

    def privacyHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('privacy').inc()
        return self.bot.get_privacy_msg()

    def debugHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('debug').inc()
        return self.bot.get_debug_report(user_id)

    def deleteMeHandler(self, user_input: str, user_id: str) -> List[BotResponse]:
        BOT_COMMAND_COUNT.labels('delete_me').inc()
        self.chat_states[user_id] = (ChatBotState.WAITING_FOR_DELETE_ME, None)
        return [BotResponse(
            "Möchtest du den täglichen Bericht abbestellen und alle von dir bei uns gespeicherten Daten löschen? Dann antworte bitte mit Ja.")]

    def getUpdates(self) -> List[Tuple[str, List[BotResponse]]]:
        return self.bot.get_unconfirmed_daily_reports()

    def confirm_daily_report_send(self, user_identification: Union[int, str]):
        return self.bot.confirm_daily_report_send(user_identification)


class InteractiveInterface(SimpleTextInterface, MessengerInterface):
    async def send_message_to_users(self, message: str, users: List[Union[str, int]], append_report=False):
        print("Sending messages is not implemented for interactive interface")

    def send_unconfirmed_reports(self) -> None:
        print("Sending Daily reports is not implemented for interactive interface")

    def run(self) -> None:
        user_input = input("Please enter input:\n> ")
        while user_input != "":
            responses = self.handle_input(user_input, '1')
            for response in responses:
                print(f"{adapt_text(response.message)}")
            user_input = input("> ")
