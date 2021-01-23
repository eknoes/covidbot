from dataclasses import dataclass
from typing import Callable, Dict, List, TypedDict, Union

from covidbot.bot import Bot


@dataclass
class Handler:
    command: str
    method: Callable[[str, str], str]


class SimpleTextInterface(object):
    bot: Bot
    handler_list: List[Handler] = []

    def __init__(self, bot: Bot):
        self.bot = bot
        self.handler_list.append(Handler("hilfe", self.helpHandler))
        self.handler_list.append(Handler("starte", self.subscribeHandler))
        self.handler_list.append(Handler("beende", self.unsubscribeHandler))
        self.handler_list.append(Handler("daten", self.currentDataHandler))
        self.handler_list.append(Handler("bericht", self.reportHandler))
        self.handler_list.append(Handler("", self.directHandler))

    def handle_input(self, user_input: str, user_id: str) -> str:
        for handler in self.handler_list:
            if handler.command == user_input[:len(handler.command)].lower():
                text_in = user_input[len(handler.command):].strip()
                return handler.method(text_in, user_id)

    def helpHandler(self, user_input: str, user_id: str) -> str:
        return (f'Hallo,\n'
                f'über diesen Bot kannst Du Dir die vom Robert-Koch-Institut (RKI) bereitgestellten '
                f'COVID19-Daten anzeigen lassen und sie dauerhaft abonnieren.\n\n'
                f'<b>📈 Informationen erhalten</b>\n'
                f'Mit "Abo ORT" kannst du einen Ort abonnieren, mit "Beende ORT" diese Abonnement wieder beenden. '
                f'Mit "Daten ORT" erhältst du einmalig die aktuellen Daten für den gegebenen Ort.'
                f'\n\n'
                f'<b>Weiteres</b>\n'
                f'• Sende "Bericht" um deinen aktuellen Tagesbericht zu erhalten. Unabhängig davon erhältst du diesen '
                f'jeden Morgen, wenn neue Daten vorliegen\n'
                f'\n\n'
                f'Mehr Informationen zu diesem Bot findest du hier: '
                f'https://github.com/eknoes/covid-bot\n\n'
                f'Diesen Hilfetext erhältst du über "Hilfe"')

    def parseLocationInput(self, location_query: str) -> Union[str, int]:
        message, locations = self.bot.find_district_id(location_query)
        if not locations:
            return message
        elif len(locations) == 1:
            return locations[0][0]
        else:
            locations_list = message + "\n\n"
            for location in locations:
                locations_list += f"• {location[1]}\t{location[0]}\n"

            locations_list += "\n"
            locations_list += "Leider musst du deine Auswahl genauer angeben. Anstatt des kompletten Namens kannst du " \
                              f"auch die ID nutzen, also bspw. /abo {locations[0][0]} für {locations[0][1]}"
            return locations_list

    def subscribeHandler(self, user_input: str, user_id: str) -> str:
        if not user_input:
            return self.bot.get_overview(user_id)
        location = self.parseLocationInput(user_input)
        if type(location) == int:
            return self.bot.subscribe(user_id, location)
        return location

    def unsubscribeHandler(self, user_input: str, user_id: str) -> str:
        location = self.parseLocationInput(user_input)
        if type(location) == int:
            return self.bot.unsubscribe(user_id, location)
        return location

    def currentDataHandler(self, user_input: str, user_id: str) -> str:
        location = self.parseLocationInput(user_input)
        if type(location) == int:
            return self.bot.get_district_report(location)
        return location

    def reportHandler(self, user_input: str, user_id: str) -> str:
        return self.bot.get_report(user_id)

    def directHandler(self, user_input: str, user_id: str) -> str:
        return self.bot.unknown_action()
