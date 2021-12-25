import logging
from datetime import datetime
from typing import Optional

from covidbot.covid_data.updater.updater import Updater


class RKIDistrictsUpdater(Updater):
    RKI_LK_SQL = "resources/counties.sql"
    log = logging.getLogger(__name__)

    def get_last_update(self) -> Optional[datetime]:
        return None

    def update(self) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(rs), COUNT(population) FROM counties")
            record = cursor.fetchone()
            if record[0] == 428 and record[1] == 428:
                return False

        with self.connection.cursor(dictionary=True) as cursor:
            with open(self.RKI_LK_SQL, "r") as f:
                cursor.execute(f.read())
        self.connection.commit()
        self.log.debug("Finished inserting county data")