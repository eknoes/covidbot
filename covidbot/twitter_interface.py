import logging
import re
from datetime import datetime
from pprint import pprint
from typing import List, Optional, Iterable

from TwitterAPI import TwitterAPI, TwitterResponse

from covidbot.covid_data import CovidData, Visualization
from covidbot.location_service import LocationService
from covidbot.metrics import SENT_MESSAGE_COUNT, API_RATE_LIMIT, API_RESPONSE_TIME, \
    API_RESPONSE_CODE, USER_COUNT
from covidbot.single_command_interface import SingleCommandInterface, SingleArgumentRequest
from covidbot.user_manager import UserManager


class TwitterInterface(SingleCommandInterface):
    log = logging.getLogger(__name__)
    user_manager: UserManager
    data: CovidData
    viz: Visualization
    twitter: TwitterAPI
    handle_regex = re.compile('@(\w){1,15}')
    location_service: LocationService

    INFECTIONS_UID = "infections"
    VACCINATIONS_UID = "vaccinations"
    ICU_UID = "icu"

    def __init__(self, consumer_key: str, consumer_secret: str, access_token_key: str, access_token_secret: str,
                 user_manager: UserManager, covid_data: CovidData, visualization: Visualization,
                 no_write: bool = False):
        super().__init__(user_manager, covid_data, visualization, 15, no_write)
        self.twitter = TwitterAPI(consumer_key, consumer_secret, access_token_key, access_token_secret,
                                  api_version='1.1')
        self.rki_name = "@rki_de"
        self.bmg_name = "@BMG_Bund"
        USER_COUNT.labels(platform="mastodon").set_function(self.get_follower_number)

    def get_follower_number(self) -> Optional[int]:
        response = self.twitter.request('users/show', {'user_id': 1367862514579542017})
        if response.status_code == 200:
            return response.json()['followers_count']
        else:
            return None

    def write_message(self, message: str, media_files: Optional[List[str]] = None,
                      reply_obj: Optional[int] = None) -> bool:
        if reply_obj and type(reply_obj) != int:
            raise ValueError("Twitter client needs reply_obj to be int")

        data = {'status': message}
        if media_files:
            # Upload filenames
            media_ids = []
            for file in media_files:
                with open(file, "rb") as f:
                    upload_resp = self.twitter.request('media/upload', None, {'media': f.read()})
                    if upload_resp.status_code != 200:
                        raise ValueError(f"Could not upload graph to twitter. API response {upload_resp.status_code}: "
                                         f"{upload_resp.text}")

                    media_ids.append(upload_resp.json()['media_id'])

            data['media_ids'] = ",".join(map(str, media_ids))

        if reply_obj:
            data['in_reply_to_status_id'] = reply_obj
            data['auto_populate_reply_metadata'] = True

        with API_RESPONSE_TIME.labels(platform='twitter').time():
            response = self.twitter.request('statuses/update', data)

        if 200 <= response.status_code < 300:
            self.log.info(f"Tweet sent successfully {len(message)} chars), response: {response.status_code}")
            SENT_MESSAGE_COUNT.inc()
            self.update_twitter_metrics(response)
            return True
        else:
            raise ValueError(f"Could not send tweet: API Code {response.status_code}: {response.text}")

    @staticmethod
    def update_twitter_metrics(response: TwitterResponse):
        quota = response.get_quota()
        if 'limit' in quota and quota['limit']:
            API_RATE_LIMIT.labels(platform='twitter', type='limit').set(quota['limit'])

        if 'remaining' in quota and quota['remaining']:
            API_RATE_LIMIT.labels(platform='twitter', type='remaining').set(quota['remaining'])
        API_RESPONSE_CODE.labels(platform='twitter', code=response.status_code).inc()

    def get_mentions(self) -> Iterable[SingleArgumentRequest]:
        with API_RESPONSE_TIME.labels(platform='twitter').time():
            response = self.twitter.request(f"statuses/mentions_timeline")
        self.update_twitter_metrics(response)
        mentions = []
        if 200 <= response.status_code < 300:
            for tweet in response:
                if self.user_manager.is_message_answered(tweet['id']):
                    continue

                mention_position = 0
                for mention in tweet['entities']['user_mentions']:
                    if mention['id'] == 1367862514579542017:
                        mention_position = mention['indices'][1]
                        break

                arguments = self.handle_regex.sub("", tweet['text'][mention_position:]).strip()
                if arguments:
                    created = datetime.strptime(tweet['created_at'], "%a %b %d %H:%M:%S %z %Y")
                    mentions.append(SingleArgumentRequest(tweet['id'], arguments, tweet['id'], created))
        return mentions
