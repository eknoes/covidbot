from unittest import TestCase
from covidbot.utils import *


class Test(TestCase):
    def test_adapt_text_unicode(self):
        test_str = "<b>Dies ist ein Test mit ein paar schönen Umlauten wie üäö!</b>"
        actual = adapt_text(test_str)
        expected = "𝗗𝗶𝗲𝘀 𝗶𝘀𝘁 𝗲𝗶𝗻 𝗧𝗲𝘀𝘁 𝗺𝗶𝘁 𝗲𝗶𝗻 𝗽𝗮𝗮𝗿 𝘀𝗰𝗵̈𝗼𝗻𝗲𝗻 𝗨𝗺𝗹𝗮𝘂𝘁𝗲𝗻 𝘄𝗶𝗲 ̈𝘂̈𝗮̈𝗼!"
        self.assertEqual(expected, actual, "adapt_text should replace bold text with Unicode characters")

        test_str = "<i>Dies ist ein Test mit ein paar schönen Umlauten wie üäö!</i>"
        actual = adapt_text(test_str)
        expected = "𝘋𝘪𝘦𝘴 𝘪𝘴𝘵 𝘦𝘪𝘯 𝘛𝘦𝘴𝘵 𝘮𝘪𝘵 𝘦𝘪𝘯 𝘱𝘢𝘢𝘳 𝘴𝘤𝘩̈𝘰𝘯𝘦𝘯 𝘜𝘮𝘭𝘢𝘶𝘵𝘦𝘯 𝘸𝘪𝘦 ̈𝘶̈𝘢̈𝘰!"
        self.assertEqual(expected, actual, "adapt_text should replace italic text with Unicode characters")

    def test_adapt_text_markdown(self):
        test_str = "<b>Dies ist ein Test mit ein paar schönen Umlauten wie üäö!</b>"
        actual = adapt_text(test_str, markdown=True)
        expected = "**Dies ist ein Test mit ein paar schönen Umlauten wie üäö!**"
        self.assertEqual(expected, actual, "adapt_text should insert bold markdown")

        test_str = "<i>Dies ist ein Test mit ein paar schönen Umlauten wie üäö!</i>"
        actual = adapt_text(test_str, markdown=True)
        expected = "*Dies ist ein Test mit ein paar schönen Umlauten wie üäö!*"
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

    def test_strip(self):
        test_str = "<code>D-64</code>"
        actual = adapt_text(test_str)
        expected = "D-64"
        self.assertEqual(expected, actual, "adapt_text should remove all html tags but a,b,i")
