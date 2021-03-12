import logging
from typing import List, Union, Optional

from TwitterAPI import TwitterAPI

from covidbot.covid_data import CovidData, Visualization
from covidbot.messenger_interface import MessengerInterface
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
        self.twitter = TwitterAPI(consumer_key, consumer_secret, access_token_key, access_token_secret)

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

            media_ids = []
            for filename in [self.viz.infections_graph(0), self.viz.incidence_graph(0)]:
                with open(filename, "rb") as f:
                    graph = f.read()
                media_ids.append(await self.upload_media(graph))

            if self.tweet(tweet_text, media_ids):
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

            media_ids = []
            for filename in [self.viz.vaccination_graph(0)]:
                with open(filename, "rb") as f:
                    graph = f.read()
                media_ids.append(await self.upload_media(graph))

            if self.tweet(tweet_text, media_ids):
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

    async def upload_media(self, data: bytes) -> str:
        upload_resp = self.twitter.request('media/upload', None, {'media': data})
        if upload_resp.status_code != 200:
            raise ValueError(f"Could not upload graph to twitter. API response {upload_resp.status_code}: "
                             f"{upload_resp.text}")

        return upload_resp.json()['media_id']

    async def send_message(self, message: str, users: List[Union[str, int]], append_report=False):
        if users:
            self.log.error("Can't tweet to specific users!")
            return

        if len(message) > 240:
            self.log.error("Tweet can't be longer than 240 characters!")
            return

        self.tweet(message)

    def tweet(self, message: str, media_ids: Optional[List[str]] = None) -> bool:
        data = {'status': message}
        if media_ids:
            data['media_ids'] = ",".join(map(str, media_ids))

        response = self.twitter.request('statuses/update', data)
        if 200 <= response.status_code < 300:
            self.log.info(f"Tweet sent successfully {len(message)} chars), response: {response.status_code}")
            return True
        else:
            raise ValueError(f"Could not send tweet: API Code {response.status_code}: {response.text}")

    def run(self) -> None:
        raise NotImplementedError("This is just an interface to make regular tweets if new data appears")
