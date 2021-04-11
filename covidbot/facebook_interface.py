import logging
import os
import shutil
import urllib.parse
from typing import List, Optional, Iterable

import requests

from covidbot.covid_data import CovidData, Visualization
from covidbot.single_command_interface import SingleCommandInterface, SingleArgumentRequest
from covidbot.user_manager import UserManager
from covidbot.utils import BotResponse


class FacebookInterface(SingleCommandInterface):
    log = logging.getLogger(__name__)

    access_token: str
    page_id: str
    web_dir: str
    url: str

    def __init__(self, page_id: str, access_token: str, web_dir: str, url: str, user_manager: UserManager,
                 covid_data: CovidData,
                 visualization: Visualization, no_write: bool = False):
        super().__init__(user_manager, covid_data, visualization, 0, no_write)
        self.page_id = page_id
        self.access_token = access_token
        self.web_dir = web_dir
        self.url = url

    def write_message(self, messages: List[BotResponse], reply_obj: Optional[object] = None) -> bool:
        message_text = ""
        media_file = None
        for response in messages:
            message_text += response.message + '\n\n'
            if not media_file and response.images:
                media_file = response.images[0]

        message = urllib.parse.quote_plus(message_text)

        if media_file:
            filename = os.path.basename(shutil.copy2(media_file, self.web_dir))
            url = self.url + filename
            response = requests.request("POST", f"https://graph.facebook.com/{self.page_id}/photos?"
                                                f"caption={message}&url={url}&access_token={self.access_token}")
        else:
            response = requests.request("POST", f"https://graph.facebook.com/{self.page_id}/feed?"
                                                f"message={message}&access_token={self.access_token}")
            if response.status_code != 200:
                self.log.error(f"Facebook API returned {response.status_code}: {response.text}")
                return False

        self.log.debug(response)
        image_id = response.json()['id']
        if not image_id:
            self.log.error("Facebook API did not return an id")
            return False
        return True

    def get_mentions(self) -> Iterable[SingleArgumentRequest]:
        raise NotImplementedError(f"{__name__} does not support individual queries")
