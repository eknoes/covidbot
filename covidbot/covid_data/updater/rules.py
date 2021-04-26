import logging
from datetime import datetime, timedelta
from typing import Optional

import ujson as json

from covidbot.covid_data.updater.updater import Updater


class RulesGermanyUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://tourismus-wegweiser.de/json/"

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MAX(updated) FROM district_rules")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()
        if last_update and datetime.now() - last_update < timedelta(hours=12):
            return False

        new_data = False
        response = self.get_resource(self.URL)
        if response:
            self.log.debug("Got RulesGermany Data")
            data = json.loads(response)
            updated = datetime.now()
            with self.connection.cursor() as cursor:
                from covidbot.utils import adapt_text
                for bl in data:
                    district_id = self.get_district_id(bl['Bundesland'])
                    if not district_id:
                        self.log.warning(f"Could not get ID of {bl['Bundesland']}")
                        continue

                    text = bl['allgemein']['Kontaktbeschränkungen']['text']
                    text = adapt_text(text, just_strip=True)
                    link = f'https://tourismus-wegweiser.de/detail/?bl={bl["Kürzel"]}'

                    cursor.execute("SELECT text, link FROM district_rules WHERE district_id=%s", [district_id])
                    row = cursor.fetchone()
                    if row:
                        if row[0] == text and row[1] == link:
                            continue
                        cursor.execute("UPDATE district_rules SET text=%s, link=%s, updated=%s WHERE district_id=%s",
                                       [text, link, updated, district_id])
                    else:
                        cursor.execute("INSERT INTO district_rules (district_id, text, link, updated) "
                                       "VALUES (%s, %s, %s, %s)", [district_id, text, link, updated])
                    new_data = True
            self.connection.commit()
        return new_data
