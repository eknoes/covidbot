import logging
from typing import List, Optional, Iterable, Tuple

from mastodon import Mastodon

from covidbot.covid_data import CovidData, Visualization
from covidbot.single_command_interface import SingleCommandInterface
from covidbot.user_manager import UserManager
from covidbot.utils import general_tag_pattern


class MastodonInterface(SingleCommandInterface):
    log = logging.getLogger(__name__)
    user_manager: UserManager
    data: CovidData
    viz: Visualization
    mastodon: Mastodon

    INFECTIONS_UID = "infections"
    VACCINATIONS_UID = "vaccinations"
    ICU_UID = "icu"

    def __init__(self, access_token: str, mastodon_url: str, user_manager: UserManager, covid_data: CovidData,
                 visualization: Visualization, no_write: bool = False):
        super().__init__(user_manager, covid_data, visualization, 5, no_write)
        self.mastodon = Mastodon(access_token=access_token, api_base_url=mastodon_url, ratelimit_method="pace")

    def upload_media(self, filename: str) -> str:
        upload_resp = self.mastodon.media_post(filename, mime_type="image/jpeg")
        if not upload_resp:
            raise ValueError(f"Could not upload media to Mastodon. API response {upload_resp.status_code}: "
                             f"{upload_resp.text}")

        return upload_resp['id']

    def write_message(self, message: str, media_files: Optional[List[str]] = None,
                      reply_id: Optional[int] = None) -> bool:
        media_ids = []
        for file in media_files:
            media_ids.append(self.upload_media(file))

        response = self.mastodon.status_post(message, media_ids=media_ids, language="deu", in_reply_to_id=reply_id)
        if response:
            self.log.info(f"Toot sent successfully {len(message)} chars)")
            return True
        else:
            raise ValueError(f"Could not send toot!")

    def get_mentions(self) -> Iterable[Tuple[int, str, Optional[str]]]:
        notifications = self.mastodon.notifications(
            exclude_types=['follow', 'favourite', 'reblog' 'poll', 'follow_request'])
        mentions = []
        bot_name = "@D64_Covidbot"
        for n in notifications:
            if n['type'] != "mention":
                continue
            text = general_tag_pattern.sub("", n['status']['content'])
            mention_pos = text.lower().find(bot_name.lower())
            text = text[mention_pos + len(bot_name):]
            if text:
                mentions.append((n['status']['id'], text, '@' + n['status']['account']['acct']))
        return mentions
