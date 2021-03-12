import logging
import time
from pprint import pprint
from typing import List, Union, Optional

from TwitterAPI import TwitterAPI, TwitterResponse

from covidbot.covid_data import CovidData, Visualization
from covidbot.messenger_interface import MessengerInterface
from covidbot.metrics import SENT_MESSAGE_COUNT, RECV_MESSAGE_COUNT, TWITTER_RATE_LIMIT, TWITTER_API_RESPONSE_TIME, \
    TWITTER_API_RESPONSE_CODE
from covidbot.text_interface import BotResponse
from covidbot.user_manager import UserManager
from covidbot.utils import format_noun, FormattableNoun, format_data_trend, format_float, format_int


class TwitterInterface(MessengerInterface):
    log = logging.getLogger(__name__)
    user_manager: UserManager
    data: CovidData
    viz: Visualization
    twitter: TwitterAPI

    INFECTIONS_UID = "infections"
    VACCINATIONS_UID = "vaccinations"
    ICU_UID = "icu"

    def __init__(self, consumer_key: str, consumer_secret: str, access_token_key: str, access_token_secret: str,
                 user_manager: UserManager, covid_data: CovidData,
                 visualization: Visualization):
        self.data = covid_data
        self.viz = visualization
        self.user_manager = user_manager
        self.twitter = TwitterAPI(consumer_key, consumer_secret, access_token_key, access_token_secret, api_version='1.1')

    async def send_daily_reports(self) -> None:
        germany = self.data.get_country_data()
        if not germany:
            raise ValueError("Could not find data for Germany")

        # Infections
        infections_uid = self.user_manager.get_user_id(self.INFECTIONS_UID)
        if self.user_manager.get_user(infections_uid).last_update.date() < germany.date:
            tweet_text = f"🦠 Das @rki_de hat für den {germany.date.strftime('%d. %B %Y')} neue Infektionszahlen veröffentlicht.\n\n" \
                         f"Es wurden {format_noun(germany.new_cases, FormattableNoun.INFECTIONS, hashtag='#')} " \
                         f"{format_data_trend(germany.cases_trend)} und " \
                         f"{format_noun(germany.new_deaths, FormattableNoun.DEATHS)} " \
                         f"{format_data_trend(germany.deaths_trend)} in Deutschland gemeldet. Die bundesweite #Inzidenz liegt " \
                         f"bei {format_float(germany.incidence)} {format_data_trend(germany.incidence_trend)}, der " \
                         f"aktuelle R-Wert beträgt {format_float(germany.r_value.r_value_7day)}. #COVID19"

            if self.tweet(tweet_text, [self.viz.infections_graph(0), self.viz.incidence_graph(0)]):
                self.user_manager.set_last_update(infections_uid, germany.date)
                self.log.info("Tweet was successfully sent")

        # Vaccinations
        vaccinations_uid = self.user_manager.get_user_id(self.VACCINATIONS_UID)
        if self.user_manager.get_user(vaccinations_uid).last_update.date() < germany.vaccinations.date:
            vacc = germany.vaccinations
            tweet_text = f"💉 Das @BMG_BUND hat die Impfdaten für den {vacc.date.strftime('%d. %B %Y')} veröffentlicht." \
                         f"\n\n{format_float(vacc.partial_rate * 100)}% der Bevölkerung haben mindestens eine #Impfung " \
                         f"erhalten, {format_float(vacc.full_rate * 100)}% sind vollständig geimpft. Insgesamt wurden " \
                         f"{format_int(vacc.vaccinated_partial)} Erstimpfungen und {format_int(vacc.vaccinated_full)} " \
                         f"Zweitimpfungen durchgeführt. #COVID19"

            if self.tweet(tweet_text, [self.viz.vaccination_graph(0)]):
                self.user_manager.set_last_update(vaccinations_uid, vacc.date)
                self.log.info("Tweet was successfully sent")

        # Vaccinations
        icu_uid = self.user_manager.get_user_id(self.ICU_UID)
        if self.user_manager.get_user(icu_uid).last_update.date() < germany.icu_data.date:
            icu = germany.icu_data
            tweet_text = f"🏥 Die DIVI hat Daten über die #Intensivbetten in Deutschland für den " \
                         f"{icu.date.strftime('%d. %B %Y')} gemeldet.\n\n{format_float(icu.percent_occupied())}% " \
                         f"({format_noun(icu.occupied_beds, FormattableNoun.BEDS)}) der " \
                         f"Intensivbetten sind aktuell belegt. " \
                         f"In {format_noun(icu.occupied_covid, FormattableNoun.BEDS)} " \
                         f"({format_float(icu.percent_covid())}%) liegen Patient:innen" \
                         f" mit #COVID19, davon werden {format_int(icu.covid_ventilated)} beatmet. " \
                         f"Insgesamt gibt es {format_noun(icu.total_beds(), FormattableNoun.BEDS)}."

            if self.tweet(tweet_text):
                self.user_manager.set_last_update(icu_uid, icu.date)
                self.log.info("Tweet was successfully sent")

    def get_infection_tweet(self, district_id: int) -> BotResponse:
        district = self.data.get_district_data(district_id)
        tweet_text = f"🦠 Am {district.date.strftime('%d. %B %Y')} wurden " \
                     f"{format_noun(district.new_cases, FormattableNoun.INFECTIONS, hashtag='#')} " \
                     f"{format_data_trend(district.cases_trend)} und " \
                     f"{format_noun(district.new_deaths, FormattableNoun.DEATHS)} " \
                     f"{format_data_trend(district.deaths_trend)} in {district.name} gemeldet. Die #Inzidenz liegt " \
                     f"bei {format_float(district.incidence)} {format_data_trend(district.incidence_trend)}. #COVID19"
        return BotResponse(tweet_text, [self.viz.incidence_graph(district_id), self.viz.infections_graph(district_id)])

    async def send_message(self, message: str, users: List[Union[str, int]], append_report=False):
        if users:
            self.log.error("Can't tweet to specific users!")
            return

        if len(message) > 240:
            self.log.error("Tweet can't be longer than 240 characters!")
            return

        self.tweet(message)

    def tweet(self, message: str, media_files: Optional[List[str]] = None, reply_id: Optional[str] = None) -> bool:
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

        if reply_id:
            data['in_reply_to_status_id'] = reply_id
            data['auto_populate_reply_metadata'] = True

        with TWITTER_API_RESPONSE_TIME.time():
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
            TWITTER_RATE_LIMIT.labels(type='limit').set(quota['limit'])

        if 'remaining' in quota and quota['remaining']:
            TWITTER_RATE_LIMIT.labels(type='remaining').set(quota['remaining'])
        TWITTER_API_RESPONSE_CODE.labels(code=response.status_code).inc()

    def run(self) -> None:
        running = True

        while running:
            with TWITTER_API_RESPONSE_TIME.time():
                response = self.twitter.request(f"statuses/mentions_timeline")
            self.update_twitter_metrics(response)
            if 200 <= response.status_code < 300:
                for tweet in response:
                    if self.user_manager.is_message_answered(tweet['id']):
                        continue
                    RECV_MESSAGE_COUNT.inc()
                    mention_position = 0
                    for mention in tweet['entities']['user_mentions']:
                        if mention['id'] == 1367862514579542017:
                            mention_position = mention['indices'][1]
                            break

                    arguments = tweet['text'][mention_position:].split(" ")
                    district_id = None
                    for i in range(min(len(arguments), 3), 0, -1):
                        query = " ".join(arguments[:i])
                        test_district = self.data.search_district_by_name(query)
                        if test_district:
                            if len(test_district) <= 2:
                                district_id = test_district[0][0]
                                break
                    
                    # Answer Tweet
                    if district_id:
                        pprint(tweet)
                        response = self.get_infection_tweet(district_id)
                        message = f"{response.message}"
                        print(message)
                        print(tweet['id'])
                        self.tweet(message, media_files=response.images, reply_id=tweet['id'])

                    self.user_manager.set_message_answered(tweet['id'])
            elif response.status_code == 429:
                time.sleep(60)
                self.log.warning("We hit Twitters Rate Limit, sleep for 60s")
            else:
                raise ValueError(f"Could not get mentions: API Code {response.status_code}: {response.text}")
            time.sleep(20)
