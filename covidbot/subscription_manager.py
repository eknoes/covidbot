import json
import logging
import os
from typing import Dict, List, Set, Union, Optional


class SubscriptionManager(object):
    _file: str
    # json modules stores ints as strings, so we have to convert the chat_ids everytime
    _data: Dict[str, List[str]]
    _last_update: Union[str, None]

    def __init__(self, file: str):
        self._file = file

        if os.path.isfile(self._file):
            with open(self._file, "r") as f:
                data = json.load(f)
                self._data = data['subscriptions']
                self._last_update = data['last_update']
                logging.debug("Loaded Data: " + str(self._data))
        else:
            self._data = dict()
            self._last_update = None

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

    def set_last_update(self, last_update: str) -> None:
        self._last_update = last_update
        self._save()

    def get_last_update(self) -> str:
        return self._last_update

    def _save(self) -> None:
        with open(self._file, "w") as f:
            logging.debug("Saving Data: " + str(self._data))
            json.dump({"subscriptions": self._data, "last_update": self._last_update}, f)
