from unittest import TestCase

from covidbot.utils import *


class Test(TestCase):
    def test_adapt_text_unicode(self):
        test_str = "<b>Dies ist ein Test!</b>"
        actual = adapt_text(test_str)
        expected = "𝗗𝗶𝗲𝘀 𝗶𝘀𝘁 𝗲𝗶𝗻 𝗧𝗲𝘀𝘁!"
        self.assertEqual(expected, actual, "adapt_text should replace bold text with Unicode characters")

        test_str = "<i>Dies ist ein Test!</i>"
        actual = adapt_text(test_str)
        expected = "𝘋𝘪𝘦𝘴 𝘪𝘴𝘵 𝘦𝘪𝘯 𝘛𝘦𝘴𝘵!"
        self.assertEqual(expected, actual, "adapt_text should replace italic text with Unicode characters")

        test_str = "<b>Städte</b>"
        actual = adapt_text(test_str)
        expected = "𝗦𝘁𝗮̈𝗱𝘁𝗲"
        self.assertEqual(expected, actual, "adapt_text should replace bold Städte correctly")

    def test_adapt_text_markdown(self):
        test_str = "<b>Dies ist ein Test mit ein paar schönen Umlauten wie üäö!</b>"
        actual = adapt_text(test_str, threema_format=True)
        expected = "*Dies ist ein Test mit ein paar schönen Umlauten wie üäö!*"
        self.assertEqual(expected, actual, "adapt_text should insert bold markdown")

        test_str = "<i>Dies ist ein Test mit ein paar schönen Umlauten wie üäö!</i>"
        actual = adapt_text(test_str, threema_format=True)
        expected = "_Dies ist ein Test mit ein paar schönen Umlauten wie üäö!_"
        self.assertEqual(expected, actual, "adapt_text should insert italic markdown")

    def test_adapt_text_links(self):
        test_str = "<a href='https://d-64.org/'>D-64</a>"
        actual = adapt_text(test_str)
        expected = "D-64 (https://d-64.org/)"
        self.assertEqual(expected, actual, "adapt_text should remove <a> but link should remain")

        test_str = "<a href='https://d-64.org/'>D-64</a> und der <a href=\"https://www.ccc.de/\">CCC</a> leisten " \
                   "wertvolle Arbeit!"
        actual = adapt_text(test_str)
        expected = "D-64 (https://d-64.org/) und der CCC (https://www.ccc.de/) leisten wertvolle Arbeit!"
        self.assertEqual(expected, actual, "adapt_text work with several links")

        test_str = "<a href='https://tourismus-wegweiser.de/widget/detail/?bl=he&sel=no'>hier</a>"
        actual = adapt_text(test_str)
        expected = "hier (https://tourismus-wegweiser.de/widget/detail/?bl=he&sel=no)"
        self.assertEqual(expected, actual)

    def test_strip(self):
        test_str = "<code>D-64</code>"
        actual = adapt_text(test_str)
        expected = "D-64"
        self.assertEqual(expected, actual, "adapt_text should remove all html tags but a,b,i")

    def test_url_in_italic(self):
        test_str = "<i>Mehr Infos <a href='https://test.de/'>hier</a> und <a href='https://test2.de/'>da</a></i>"
        actual = adapt_text(test_str)
        expected = "𝘔𝘦𝘩𝘳 𝘐𝘯𝘧𝘰𝘴 𝘩𝘪𝘦𝘳 (https://test.de/) 𝘶𝘯𝘥 𝘥𝘢 (https://test2.de/)"
        self.assertEqual(expected, actual, "adapt_text should replace links in italic mode and make them not italic")

    def test_url_in_markdown(self):
        test_str = "<i>Mehr Infos <a href='https://test.de/'>hier</a> und <a href='https://test2.de/'>da</a></i>"
        actual = adapt_text(test_str, threema_format=True)
        expected = "_Mehr Infos hier_ (https://test.de/) _und da_ (https://test2.de/)"
        self.assertEqual(expected, actual, "adapt_text should omit links in italic mode")

        test_str = "<b>Mehr Infos <a href='https://test.de/'>hier</a> und <a href='https://test2.de/'>da</a></b>"
        actual = adapt_text(test_str, threema_format=True)
        expected = "*Mehr Infos hier* (https://test.de/) *und da* (https://test2.de/)"
        self.assertEqual(expected, actual, "adapt_text should omit links in italic mode")

    def test_adapt_strip(self):
        test_str = "<p>Absatz 1.</p> Kein Absatz. <p>Absatz 2</p>"
        actual = adapt_text(test_str, just_strip=True)
        expected = "Absatz 1.\nKein Absatz.\nAbsatz 2"
        self.assertEqual(expected, actual, "Adapt text should also adapt <p> to linebreaks")

    def test_format_int(self):
        expected = "1.121"
        actual = format_int(1121)
        self.assertEqual(expected, actual, "Ints should be formatted for German localization")

    def test_format_incidence(self):
        expected = "1,21"
        actual = format_float(1.21)
        self.assertEqual(expected, actual, "Incidence should be formatted for German localization")

    def test_format_noun(self):
        expected = "1 Neuinfektion"
        actual = format_noun(1, FormattableNoun.NEW_INFECTIONS)
        self.assertEqual(expected, actual)

        expected = "2 Neuinfektionen"
        actual = format_noun(2, FormattableNoun.NEW_INFECTIONS)
        self.assertEqual(expected, actual)

        expected = "0 Neuinfektionen"
        actual = format_noun(0, FormattableNoun.NEW_INFECTIONS)
        self.assertEqual(expected, actual)

        expected = "1 Todesfall"
        actual = format_noun(1, FormattableNoun.DEATHS)
        self.assertEqual(expected, actual)

        expected = "2 Todesfälle"
        actual = format_noun(2, FormattableNoun.DEATHS)
        self.assertEqual(expected, actual)

        expected = "0 Todesfälle"
        actual = format_noun(0, FormattableNoun.DEATHS)
        self.assertEqual(expected, actual)

    def test_get_trend(self):
        self.assertEqual(TrendValue.SAME, get_trend(99, 100))
        self.assertEqual(TrendValue.SAME, get_trend(100, 101))
        self.assertEqual(TrendValue.SAME, get_trend(100, 100))
        self.assertEqual(TrendValue.UP, get_trend(98, 101))
        self.assertEqual(TrendValue.DOWN, get_trend(102, 100))
