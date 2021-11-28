from __future__ import annotations
from enum import Enum
from typing import List


class BotUserSettings(Enum):
    REPORT_GRAPHICS = "report_graphics"
    REPORT_INCLUDE_ICU = "report_include_icu"
    REPORT_INCLUDE_VACCINATION = "report_include_vaccination"
    REPORT_EXTENSIVE_GRAPHICS = "report_extensive_graphics"
    REPORT_ALL_INFECTION_GRAPHS = "report_all_infection_graphics"
    FORMATTING = "disable_fake_format"
    REPORT_SLEEP_MODE = "report_sleep_mode"
    REPORT_WEEKLY = "report_weekly"

    @staticmethod
    def default(setting: BotUserSettings) -> bool:
        if setting == BotUserSettings.REPORT_GRAPHICS:
            return True
        elif setting == BotUserSettings.REPORT_INCLUDE_ICU:
            return True
        elif setting == BotUserSettings.REPORT_INCLUDE_VACCINATION:
            return True
        elif setting == BotUserSettings.REPORT_EXTENSIVE_GRAPHICS:
            return False
        elif setting == BotUserSettings.FORMATTING:
            return True
        elif setting == BotUserSettings.REPORT_ALL_INFECTION_GRAPHS:
            return False
        elif setting == BotUserSettings.REPORT_SLEEP_MODE:
            return False
        elif setting == BotUserSettings.REPORT_WEEKLY:
            return False

    @staticmethod
    def title(setting: BotUserSettings) -> str:
        if setting == BotUserSettings.REPORT_GRAPHICS:
            return "Grafiken im Bericht"
        elif setting == BotUserSettings.REPORT_INCLUDE_ICU:
            return "Intensivbetten im Bericht"
        elif setting == BotUserSettings.REPORT_INCLUDE_VACCINATION:
            return "Impfungen im Bericht"
        elif setting == BotUserSettings.REPORT_EXTENSIVE_GRAPHICS:
            return "Weitere Grafiken im Bericht"
        elif setting == BotUserSettings.FORMATTING:
            return "Formatierung"
        elif setting == BotUserSettings.REPORT_ALL_INFECTION_GRAPHS:
            return "Alle Infektionsgrafiken im Bericht"
        elif setting == BotUserSettings.REPORT_SLEEP_MODE:
            return "Bericht Pausieren"
        elif setting == BotUserSettings.REPORT_WEEKLY:
            return "Wöchentlicher Bericht"

    @staticmethod
    def description(setting: BotUserSettings) -> str:
        if setting == BotUserSettings.REPORT_GRAPHICS:
            return "(De)aktiviert die Grafiken im täglichen Bericht."
        elif setting == BotUserSettings.REPORT_INCLUDE_ICU:
            return "Diese Option zeigt im Bericht einen Überblick über die " \
                   "Intensivbettenkapazität in Deutschland."
        elif setting == BotUserSettings.REPORT_INCLUDE_VACCINATION:
            return "Diese Option zeigt im Bericht einen Überblick über die " \
                   "Impfungen in Deutschland."
        elif setting == BotUserSettings.REPORT_EXTENSIVE_GRAPHICS:
            return "Mit dieser Option werden im Bericht weitere Grafiken versendet."
        elif setting == BotUserSettings.FORMATTING:
            return "Signal und Facebook Messenger Nutzer:innen können mit dieser Option die Formatierung der " \
                   "Nachrichten (de)aktivieren. Diese ist auf manchen Geräten bei Signal und Facebook " \
                   "Messenger nicht lesbar."
        elif setting == BotUserSettings.REPORT_ALL_INFECTION_GRAPHS:
            return "Mit dieser Option bekommst du im Bericht eine Neuinfektionsgrafik für jeden " \
                   "abonnierten Ort."
        elif setting == BotUserSettings.REPORT_SLEEP_MODE:
            return "Pausiere den Bericht, solange die 7-Tage-Inzidenz in allen von dir abonnierten Orte unter 10 liegt."
        elif setting == BotUserSettings.REPORT_WEEKLY:
            return "Mit dieser Option bekommst du deinen persönlichen Bericht nur montags"

    @staticmethod
    def command_key(setting: BotUserSettings) -> List[str]:
        if setting == BotUserSettings.REPORT_GRAPHICS:
            return ["grafik"]
        elif setting == BotUserSettings.REPORT_INCLUDE_ICU:
            return ["intensiv"]
        elif setting == BotUserSettings.REPORT_INCLUDE_VACCINATION:
            return ["impfung"]
        elif setting == BotUserSettings.REPORT_EXTENSIVE_GRAPHICS:
            return ["plus-grafik"]
        elif setting == BotUserSettings.FORMATTING:
            return ["formatierung"]
        elif setting == BotUserSettings.REPORT_ALL_INFECTION_GRAPHS:
            return ["neuinfektion-grafik"]
        elif setting == BotUserSettings.REPORT_SLEEP_MODE:
            return ["pause"]
        elif setting == BotUserSettings.REPORT_WEEKLY:
            return ["woechentlich", "wöchentlich"]
