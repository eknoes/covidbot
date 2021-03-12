import logging
from typing import List, Union, Optional

from TwitterAPI import TwitterAPI
from mastodon import Mastodon

from covidbot.covid_data import CovidData, Visualization
from covidbot.messenger_interface import MessengerInterface
from covidbot.user_manager import UserManager
from covidbot.utils import format_noun, FormattableNoun, format_data_trend, format_float, format_int


class MastodonInterface(MessengerInterface):
    log = logging.getLogger(__name__)
    user_manager: UserManager
    data: CovidData
    viz: Visualization
    mastodon: Mastodon

    INFECTIONS_UID = "infections"
    VACCINATIONS_UID = "vaccinations"
    ICU_UID = "icu"

    def __init__(self, access_token: str, mastodon_url: str,
                 user_manager: UserManager, covid_data: CovidData,
                 visualization: Visualization):
        self.data = covid_data
        self.viz = visualization
        self.user_manager = user_manager
        self.mastodon = Mastodon(access_token=access_token, api_base_url=mastodon_url)

    async def send_daily_reports(self) -> None:

        germany = self.data.get_country_data()
        if not germany:
            raise ValueError("Could not find data for Germany")

        # Infections
        infections_uid = self.user_manager.get_user_id(self.INFECTIONS_UID)
        if self.user_manager.get_user(infections_uid).last_update.date() < germany.date:
            toot_text = f"🦠 Das @rki_de hat für den {germany.date.strftime('%d. %B %Y')} neue Infektionszahlen veröffentlicht.\n\n" \
                         f"Es wurden {format_noun(germany.new_cases, FormattableNoun.INFECTIONS, hashtag='#')} " \
                         f"{format_data_trend(germany.cases_trend)} und " \
                         f"{format_noun(germany.new_deaths, FormattableNoun.DEATHS)} " \
                         f"{format_data_trend(germany.deaths_trend)} in Deutschland gemeldet. Die bundesweite #Inzidenz liegt " \
                         f"bei {format_float(germany.incidence)} {format_data_trend(germany.incidence_trend)}, der " \
                         f"aktuelle R-Wert beträgt {format_float(germany.r_value.r_value_7day)}. #COVID19"

            media_ids = []
            for graph in [self.viz.infections_graph(0), self.viz.incidence_graph(0)]:
                media_ids.append(await self.upload_media(graph))

            if self.toot(toot_text, media_ids):
                self.user_manager.set_last_update(infections_uid, germany.date)
                self.log.info("Toot was successfully sent")

        # Vaccinations
        vaccinations_uid = self.user_manager.get_user_id(self.VACCINATIONS_UID)
        if self.user_manager.get_user(vaccinations_uid).last_update.date() < germany.vaccinations.date:
            vacc = germany.vaccinations
            toot_text = f"💉 Das @BMG_BUND hat die Impfdaten für den {vacc.date.strftime('%d. %B %Y')} veröffentlicht." \
                         f"\n\n{format_float(vacc.partial_rate * 100)}% der Bevölkerung haben mindestens eine #Impfung " \
                         f"erhalten, {format_float(vacc.full_rate * 100)}% sind vollständig geimpft. Insgesamt wurden " \
                         f"{format_int(vacc.vaccinated_partial)} Erstimpfungen und {format_int(vacc.vaccinated_full)} " \
                         f"Zweitimpfungen durchgeführt. #COVID19"

            media_ids = []
            for filename in [self.viz.vaccination_graph(0)]:
                with open(filename, "rb") as f:
                    graph = f.read()
                media_ids.append(await self.upload_media(graph))

            if self.toot(toot_text, media_ids):
                self.user_manager.set_last_update(vaccinations_uid, vacc.date)
                self.log.info("Toot was successfully sent")

        # Vaccinations
        icu_uid = self.user_manager.get_user_id(self.ICU_UID)
        if self.user_manager.get_user(icu_uid).last_update.date() < germany.icu_data.date:
            icu = germany.icu_data
            toot_text = f"🏥 Die DIVI hat Daten über die #Intensivbetten in Deutschland für den " \
                         f"{icu.date.strftime('%d. %B %Y')} gemeldet.\n\n{format_float(icu.percent_occupied())}% " \
                         f"({format_noun(icu.occupied_beds, FormattableNoun.BEDS)}) der " \
                         f"Intensivbetten sind aktuell belegt. " \
                         f"In {format_noun(icu.occupied_covid, FormattableNoun.BEDS)} " \
                         f"({format_float(icu.percent_covid())}%) liegen Patient:innen" \
                         f" mit #COVID19, davon werden {format_int(icu.covid_ventilated)} beatmet. " \
                         f"Insgesamt gibt es {format_noun(icu.total_beds(), FormattableNoun.BEDS)}."

            if self.toot(toot_text):
                self.user_manager.set_last_update(icu_uid, icu.date)
                self.log.info("Toot was successfully sent")

    async def upload_media(self, filename: str) -> str:
        upload_resp = self.mastodon.media_post(filename, mime_type="image/jpeg")
        if not upload_resp:
            raise ValueError(f"Could not upload media to Mastodon. API response {upload_resp.status_code}: "
                             f"{upload_resp.text}")

        return upload_resp['id']

    async def send_message(self, message: str, users: List[Union[str, int]], append_report=False):
        if users:
            self.log.error("Can't toot to specific users!")
            return

        if len(message) > 240:
            self.log.error("Toot can't be longer than 240 characters!")
            return

        self.toot(message)

    def toot(self, message: str, media_ids: Optional[List[str]] = None) -> bool:
        response = self.mastodon.status_post(message, media_ids=media_ids, language="deu")
        if response:
            self.log.info(f"Toot sent successfully {len(message)} chars)")
            return True
        else:
            raise ValueError(f"Could not send toot!")

    def run(self) -> None:
        raise NotImplementedError("This is just an interface to make regular toots if new data appears")
