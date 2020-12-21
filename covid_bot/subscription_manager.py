import json
import logging
import os
from typing import Dict, List, Set


class SubscriptionManager(object):
    
    file: str
    # json modules stores ints as strings, so we have to convert the chat_ids everytime
    data: Dict[str, List[str]]
    
    def __init__(self, file: str):
        self.file = file
        
        if os.path.isfile(self.file):
            with open(self.file, "r") as f:
                self.data = json.load(f)
                logging.debug("Loaded Data: " + str(self.data))
        else:
            self.data = dict()

    def add_subscription(self, chat_id: int, rs: str) -> bool:
        if str(chat_id) not in self.data or self.data[str(chat_id)] is None:
            self.data[str(chat_id)] = []

        if rs in self.data[str(chat_id)]:
            return False
        else:
            self.data[str(chat_id)].append(rs)
            self._save()
            return True

    def rm_subscription(self, chat_id: int, rs: str) -> bool:
        if str(chat_id) not in self.data:
            return False
        
        if rs not in self.data[str(chat_id)]:
            return False

        self.data[str(chat_id)].remove(rs)
        self._save()
        return True
    
    def get_subscriptions(self, chat_id: int) -> Set[str]:
        if str(chat_id) not in self.data:
            return set()
        return set(self.data[str(chat_id)])
    
    def get_subscribers(self) -> List[int]:
        return list(map(int, self.data.keys()))
    
    def _save(self) -> None:
        with open(self.file, "w") as f:
            logging.debug("Saving Data: " + str(self.data))
            json.dump(self.data, f)