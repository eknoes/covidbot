from unittest import TestCase

from covidbot.user_hint_service import UserHintService


class TestUpdater(TestCase):
    def test_user_hints(self):
        formatter = lambda x: f"/{x}"

        expected = "Lorem /ipsum sim /dolor"
        actual = UserHintService.format_commands("Lorem {ipsum} sim {dolor}", formatter)
        self.assertEqual(expected, actual, "Commands should be formatted correctly in User Hints")

        formatter = lambda x: f"'{x}'"
        expected = "Lorem 'ipsum' sim 'dolor'"
        actual = UserHintService.format_commands("Lorem {ipsum} sim {dolor}", formatter)
        self.assertEqual(expected, actual, "Commands should be formatted correctly in User Hints")
