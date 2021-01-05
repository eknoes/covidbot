import os
import shutil
from datetime import datetime
from unittest import TestCase

from covidbot.file_based_subscription_manager import FileBasedSubscriptionManager


class SubscriptionManagerTest(TestCase):
    TESTFILE = "covidbot/tests/testuser_empty.json"
    ORIG_TESTFILE = "testuser_empty.json"

    def setUp(self) -> None:
        if os.path.isfile(self.TESTFILE):
            os.remove(self.TESTFILE)

        shutil.copy2(self.ORIG_TESTFILE, self.TESTFILE)

        self.manager = FileBasedSubscriptionManager(self.TESTFILE)

    def tearDown(self) -> None:
        del self.manager
        
    def test_all(self):
        self.assertEqual([], self.manager.get_subscribers(), "Subscribers of new list should be empty")

        self.manager.add_subscription(str(1), "test")
        self.assertIn("test", self.manager.get_subscriptions(str(1)), "Subscribers should have a subscription")
        self.manager.rm_subscription(str(1), "test")
        self.assertEqual(None, self.manager.get_subscriptions(str(1)))
        self.assertIsNone(self.manager.get_last_update(), "last_update should be None if initialized empty")
        self.manager.set_last_update(datetime(year=2020, month=1, day=1))
        self.assertEqual(datetime(year=2020, month=1, day=1), self.manager.get_last_update(),
                         "last_update should be changed "
                         "after set_last_update")

    def test_persistence(self):
        self.manager.add_subscription(str(1), "test1")
        self.manager.add_subscription(str(3), "test1")
        self.manager.add_subscription(str(2), "test2")
        self.manager.add_subscription(str(4), "removed")
        self.manager.rm_subscription(str(4), "removed")
        self.manager.set_last_update(datetime(year=2020, month=1, day=1))
        
        del self.manager
        self.manager = FileBasedSubscriptionManager(self.TESTFILE)

        self.assertEqual({"test1"}, self.manager.get_subscriptions(str(1)), "Should save persistently")
        self.assertEqual({"test1"}, self.manager.get_subscriptions(str(3)), "Should save persistently")
        self.assertEqual({"test2"}, self.manager.get_subscriptions(str(2)), "Should save persistently")
        self.assertEqual(datetime(year=2020, month=1, day=1), self.manager.get_last_update(), "Should save persistently")
        self.assertIsNone(self.manager.get_subscriptions(str(4)), "Should remove persistently")
