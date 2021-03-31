from typing import Iterable, Optional, List
from unittest import TestCase

from covidbot.__main__ import parse_config, get_connection
from covidbot.covid_data import CovidData, Visualization
from covidbot.single_command_interface import SingleCommandInterface, SingleArgumentRequest
from covidbot.user_manager import UserManager


class NonAbstractSingleCommandInterface(SingleCommandInterface):

    def write_message(self, message: str, media_files: Optional[List[str]] = None,
                      reply_obj: Optional[object] = None) -> bool:
        pass

    def get_mentions(self) -> Iterable[SingleArgumentRequest]:
        pass


class TestSingleCommandInterface(TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cfg = parse_config("resources/config.unittest.ini")
        cls.conn = get_connection(cfg)

        cls.interface = NonAbstractSingleCommandInterface(UserManager("test", cls.conn), CovidData(cls.conn),
                                                          Visualization(cls.conn, "."), 0, True)

    def test_find_district(self):
        self.assertEqual(5113, self.interface.find_district("Essen"), "Result for Essen should be Essen")
        self.assertEqual(6, self.interface.find_district("Hessen"), "Result for Hessen should be Hessen")
        self.assertEqual(5515, self.interface.find_district("Münster"), "Result for Münster should be Münster")
        self.assertEqual(5515, self.interface.find_district("Münster Westfalen"),
                         "Result for Münster Westfalen should be Münster")
        self.assertEqual(6435, self.interface.find_district("Hanau"), "Result for Hanau should be MKK")
        self.assertEqual(9772, self.interface.find_district("Landkreis Augsburg"), "Result for LK Augsburg should be correct")
        self.assertEqual(8221, self.interface.find_district("Betreutes Trinken"),
                         "Result for Betreutes Trinken should be Heidelberg")
        self.assertEqual(8215, self.interface.find_district("Rheinstetten"), "Result for Rheinstetten is missing")

    def test_find_district_no_query(self):
        self.assertIsNone(self.interface.find_district("via Threema, Telegram oder Signal"))
        self.assertIsNone(self.interface.find_district(
            "ist die Sterblichkeit bei euch gegenüber LK mit niedriger Inzidenz deutlich erhöht?"))
        self.assertIsNone(self.interface.find_district("gut, brauche ihn aber vermutlich nicht"))
        self.assertIsNone(self.interface.find_district("Wie wird den jetzt gezählt?"))
        self.assertIsNone(self.interface.find_district("Risklayer sagt grad eben dies:"))
        self.assertIsNone(
            self.interface.find_district("Das ist aber dann so dass die größten Schwätzer sich am meisten kümmern?"))
        self.assertIsNone(self.interface.find_district("Coole Idee und gute Umsetzung"))
        self.assertIsNone(self.interface.find_district("Wie funktioniert der Twitterbot?"))
        self.assertIsNone(self.interface.find_district("der einen mit aktuellen Zahlen rund um #COVID19 versorgt"))
        self.assertIsNone(self.interface.find_district("ist nun auch bei Twitter aus dem Ei "))
        self.assertIsNone(self.interface.find_district("Riesige Kudos gehen raus an"))
        self.assertIsNone(self.interface.find_district("Vielen Dank für eure mega Arbeit"))
        self.assertIsNone(self.interface.find_district("Super! Funktioniert klasse"))
        self.assertIsNone(self.interface.find_district("Das ist echt großartig, was ihr geleistet habt."))
        self.assertIsNone(self.interface.find_district("Klar..."))
        self.assertIsNone(self.interface.find_district("Bitte korrigiert bei den Regeln für Berlin die Angabe zu den Kindern."))
