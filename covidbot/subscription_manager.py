import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Set, Union, Optional

from psycopg2._psycopg import connection

from covidbot.utils import serialize_datetime, unserialize_datetime


class SubscriptionManager(object):
    connection: connection

    def __init__(self, db_connection: connection):
        self.connection = db_connection
        self._create_db()

    def _create_db(self):
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('CREATE TABLE IF NOT EXISTS subscriptions '
                               '(user_id INTEGER, rs INTEGER, added DATE DEFAULT now(), '
                               'UNIQUE(user_id, rs))')

    def add_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('INSERT INTO subscriptions (user_id, rs) VALUES (%s, %s) '
                               'ON CONFLICT DO NOTHING', [user_id, rs])
                if cursor.rowcount == 1:
                    return True
        return False

    def rm_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM subscriptions WHERE user_id=%s AND rs=%s', [user_id, rs])
                if cursor.rowcount == 1:
                    return True
        return False

    def get_subscriptions(self, user_id: int) -> Optional[List[int]]:
        result = []
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT rs FROM subscriptions WHERE user_id=%s', [user_id])
                for row in cursor.fetchall():
                    result.append(row['rs'])
        return result

    def delete_user(self, user_id: int) -> bool:
        pass

    def get_all_user(self) -> List[int]:
        pass


class FileBasedSubscriptionManager(object):
    _file: str = None
    # json modules stores ints as strings, so we have to convert the chat_ids everytime
    _data: Dict[str, List[str]] = dict()
    _last_update: Union[datetime, None] = None
    log = logging.getLogger(__name__)

    def __init__(self, file: str):
        self._file = file

        if os.path.isfile(self._file):
            with open(self._file, "r") as f:
                data = json.load(f)
                self._data = data['subscriptions']
                self._last_update = unserialize_datetime(data['last_update'])
                self.log.debug("Loaded Data: " + str(self._data))

    def add_subscription(self, chat_id: str, rs: str) -> bool:
        if chat_id not in self._data or self._data[chat_id] is None:
            self._data[chat_id] = []

        if rs in self._data[chat_id]:
            return False
        else:
            self._data[chat_id].append(rs)
            self._save()
            return True

    def rm_subscription(self, chat_id: str, rs: str) -> bool:
        if chat_id not in self._data:
            return False

        if rs not in self._data[chat_id]:
            return False

        self._data[chat_id].remove(rs)
        if not self._data[chat_id]:
            del self._data[chat_id]
        self._save()
        return True

    def get_subscriptions(self, chat_id: str) -> Optional[Set[str]]:
        if chat_id not in self._data:
            return None
        return set(self._data[chat_id])

    def get_subscribers(self) -> List[str]:
        return list(self._data.keys())

    def set_last_update(self, last_update: datetime) -> None:
        self._last_update = last_update
        self._save()

    def get_last_update(self) -> Union[None, datetime]:
        return self._last_update

    def _save(self) -> None:
        with open(self._file, "w") as f:
            self.log.debug("Saving Data: " + str(self._data))
            json.dump({"subscriptions": self._data, "last_update": self._last_update}, f, default=serialize_datetime)
