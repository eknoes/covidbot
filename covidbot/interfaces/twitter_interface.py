import logging
import re
import time
from datetime import datetime, timezone
from typing import List, Optional, Iterable

from TwitterAPI import TwitterAPI, TwitterResponse, TwitterConnectionError

from covidbot.covid_data import CovidData, Visualization
from covidbot.location_service import LocationService
from covidbot.metrics import SENT_MESSAGE_COUNT, API_RATE_LIMIT, API_RESPONSE_TIME, \
    API_RESPONSE_CODE, API_ERROR
from covidbot.interfaces.single_command_interface import SingleCommandInterface, SingleArgumentRequest
from covidbot.user_manager import UserManager
from covidbot.utils import replace_by_list
from covidbot.interfaces.bot_response import BotResponse


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
        self.twitter.CONNECTION_TIMEOUT = 120
        self.twitter.REST_TIMEOUT = 120
        self.twitter.STREAMING_TIMEOUT = 120
        self.rki_name = "@rki_de"
        self.bmg_name = "@BMG_Bund"
        self.update_follower_number()

    def update_follower_number(self):
        response = self.twitter.request('users/show', {'user_id': 1367862514579542017})
        if response.status_code == 200:
            number = response.json()['followers_count']
            self.user_manager.set_platform_user_number(number)

    def write_message(self, messages: List[BotResponse], reply_obj: Optional[object] = None) -> bool:
        if reply_obj and type(reply_obj) != int:
            raise ValueError("Twitter client needs reply_obj to be int")

        for message in messages:
            data = {'status': message.message}
            if message.images:
                # Upload filenames
                media_ids = []
                for file in message.images:
                    with open(file, "rb") as f:
                        upload_resp = self.twitter.request('media/upload', None, {'media': f.read()})
                        if upload_resp.status_code != 200:
                            if upload_resp.status_code == 429: # Rate Limit exceed
                                reset_time = int(upload_resp.headers.get("x-rate-limit-reset", 0))
                                if reset_time:
                                    sleep_time = (datetime.fromtimestamp(reset_time, timezone.utc) - datetime.now(
                                        tz=timezone.utc)).seconds
                                    self.log.warning(f"Rate Limit exceed: Wait for reset in {sleep_time}s")
                                    time.sleep(sleep_time)
                                    return False
                            raise ValueError(
                                f"Could not upload graph to twitter. API response {upload_resp.status_code}: "
                                f"{upload_resp.text}")

                        media_ids.append(upload_resp.json()['media_id'])

                data['media_ids'] = ",".join(map(str, media_ids))

            if reply_obj:
                data['in_reply_to_status_id'] = reply_obj
                data['auto_populate_reply_metadata'] = True

            with API_RESPONSE_TIME.labels(platform='twitter').time():
                response = self.twitter.request('statuses/update', data)

            if 200 <= response.status_code < 300:
                self.log.info(f"Tweet sent successfully {len(data['status'])} chars), response: {response.status_code}")
                SENT_MESSAGE_COUNT.inc()
                self.update_twitter_metrics(response)
                reply_obj = response.json()['id']
            else:
                if upload_resp.status_code == 429:  # Rate Limit exceed
                    reset_time = int(upload_resp.headers.get("x-rate-limit-reset", 0))
                    if reset_time:
                        sleep_time = (datetime.fromtimestamp(reset_time, timezone.utc) - datetime.now(tz=timezone.utc)).seconds
                        self.log.warning(f"Rate Limit exceed: Wait for reset in {sleep_time}s")
                        time.sleep(sleep_time)
                        return False
                raise ValueError(f"Could not send tweet: API Code {response.status_code}: {response.text}")
        return True

    @staticmethod
    def update_twitter_metrics(response: TwitterResponse):
        quota = response.get_quota()
        if 'limit' in quota and quota['limit']:
            API_RATE_LIMIT.labels(platform='twitter', type='limit').set(quota['limit'])

        if 'remaining' in quota and quota['remaining']:
            API_RATE_LIMIT.labels(platform='twitter', type='remaining').set(quota['remaining'])
        API_RESPONSE_CODE.labels(platform='twitter', code=response.status_code).inc()

    def get_mentions(self) -> Iterable[SingleArgumentRequest]:
        return [] # Workaround: We do not reply anymore to single tweets on twitter

        try:
            with API_RESPONSE_TIME.labels(platform='twitter').time():
                response = self.twitter.request(f"statuses/mentions_timeline", params={'tweet_mode': 'extended',
                                                                                       'count': 200,
                                                                                       'trim_user': 1})
        except TwitterConnectionError as e:
            self.log.warning(f"TwitterConnectionError while fetching mentions: {e}", exc_info=e)
            API_ERROR.inc()
            return []
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

                arguments = self.handle_regex.sub("", tweet['full_text'][mention_position:]).strip()
                if arguments:
                    # As our locale is different, we have to adapt Twitter Time & Date String
                    day_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    day_de = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
                    month_en = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                    month_de = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

                    localized_str = replace_by_list(tweet['created_at'], day_en + month_en, day_de + month_de)
                    created = None
                    try:
                        created = datetime.strptime(localized_str, "%a %b %d %H:%M:%S %z %Y")
                    except ValueError as e:
                        self.log.warning(f"Cant parse twitters date string {localized_str}:", exc_info=e)

                    mentions.append(SingleArgumentRequest(tweet['id'], arguments, tweet['id'], created))
        return mentions
