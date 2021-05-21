from __future__ import annotations
from enum import Enum


class BotUserSettings(Enum):
    BETA = "beta"
    REPORT_GRAPHICS = "report_graphics"
    REPORT_INCLUDE_ICU = "report_include_icu"
    REPORT_INCLUDE_VACCINATION = "report_include_vaccination"
    REPORT_EXTENSIVE_GRAPHICS = "report_extensive_graphics"
    REPORT_ALL_INFECTION_GRAPHS = "report_all_infection_graphics"
    FORMATTING = "disable_fake_format"

    @staticmethod
    def default(setting: BotUserSettings) -> bool:
        if setting == BotUserSettings.BETA:
            return False
        elif setting == BotUserSettings.REPORT_GRAPHICS:
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

    @staticmethod
    def title(setting: BotUserSettings) -> str:
        if setting == BotUserSettings.BETA:
            return "Beta-Modus"
        elif setting == BotUserSettings.REPORT_GRAPHICS:
            return "Grafiken im Bericht"
        elif setting == BotUserSettings.REPORT_INCLUDE_ICU:
            return "Absatz zu Intensivbetten im Bericht"
        elif setting == BotUserSettings.REPORT_INCLUDE_VACCINATION:
            return "Absatz zu Impfungen im Bericht"
        elif setting == BotUserSettings.REPORT_EXTENSIVE_GRAPHICS:
            return "Weitere Grafiken im Bericht"
        elif setting == BotUserSettings.FORMATTING:
            return "Formatierung"
        elif setting == BotUserSettings.REPORT_ALL_INFECTION_GRAPHS:
            return "Alle Infektionsgrafiken im Bericht"

    @staticmethod
    def description(setting: BotUserSettings) -> str:
        if setting == BotUserSettings.BETA:
            return "In der Beta Version testen wir aktuell einen verbesserten Bericht."
        elif setting == BotUserSettings.REPORT_GRAPHICS:
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

    @staticmethod
    def command_key(setting: BotUserSettings) -> str:
        if setting == BotUserSettings.BETA:
            return "beta"
        elif setting == BotUserSettings.REPORT_GRAPHICS:
            return "grafik"
        elif setting == BotUserSettings.REPORT_INCLUDE_ICU:
            return "intensiv"
        elif setting == BotUserSettings.REPORT_INCLUDE_VACCINATION:
            return "impfung"
        elif setting == BotUserSettings.REPORT_EXTENSIVE_GRAPHICS:
            return "plus-grafik"
        elif setting == BotUserSettings.FORMATTING:
            return "formatierung"
        elif setting == BotUserSettings.REPORT_ALL_INFECTION_GRAPHS:
            return "neuinfektion-grafik"
