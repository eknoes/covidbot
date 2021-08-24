import csv
import logging
from datetime import datetime, timedelta
from typing import Optional

import ujson as json

from covidbot.covid_data.updater.updater import Updater


class VaccinationGermanyImpfdashboardUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://impfdashboard.de/static/data/germany_vaccinations_timeseries_v2.tsv"

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            germany_id = self.get_district_id("Deutschland")
            cursor.execute("SELECT MAX(last_update) FROM covid_vaccinations WHERE district_id=%s", [germany_id])
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()
        district_id = self.get_district_id("Deutschland")
        if district_id is None:
            raise ValueError("No district_id for Deutschland")

        if last_update and datetime.now() - last_update < timedelta(hours=12):
            return False

        new_data = False
        response = self.get_resource(self.URL)
        if response:
            self.log.debug("Got Vaccination Data from Impfdashboard")
            dashboard_data = response.splitlines()
            reader = csv.DictReader(dashboard_data, delimiter='\t', quoting=csv.QUOTE_NONE)

            with self.connection.cursor() as cursor:
                for row in reader:
                    # The other vaccination source uses another timeformat, so we have to add a day
                    updated = datetime.fromisoformat(row['date'])
                    cursor.execute("SELECT id FROM covid_vaccinations WHERE date = %s AND district_id=%s",
                                   [updated, district_id])
                    if cursor.fetchone():
                        continue

                    new_data = True
                    cursor.execute('SELECT population FROM counties WHERE rs=%s', [district_id])
                    population = cursor.fetchone()[0]
                    if not population:
                        self.log.warning(f"Can't fetch population for {district_id} ({row['Bundesland']})")
                        continue

                    rate_full, rate_partial = 0, 0
                    if row['personen_erst_kumulativ']:
                        rate_partial = int(row['personen_erst_kumulativ']) / population

                    if row['personen_voll_kumulativ']:
                        rate_full = int(row['personen_voll_kumulativ']) / population

                    cursor.execute('INSERT INTO covid_vaccinations (district_id, date, vaccinated_partial, '
                                   'vaccinated_full, rate_partial, rate_full, doses_diff) VALUE (%s, %s, %s, %s, %s, %s, %s)',
                                   [district_id, updated, row['personen_erst_kumulativ'],
                                    row['personen_voll_kumulativ'], rate_partial, rate_full,
                                    row['dosen_differenz_zum_vortag']])
            self.connection.commit()
        return new_data


class VaccinationGermanyStatesImpfdashboardUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://impfdashboard.de/static/data/germany_vaccinations_by_state.tsv"

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            hessen_id = self.get_district_id("Hessen")
            cursor.execute("SELECT MAX(last_update) FROM covid_vaccinations WHERE district_id=%s", [hessen_id])
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()

        if last_update and datetime.now() - last_update < timedelta(hours=12):
            return False

        metadata_response = self.get_resource("https://impfdashboard.de/static/data/metadata.json", force=True)
        if not metadata_response:
            return False

        metadata = json.loads(metadata_response)
        data_date = datetime.fromisoformat(metadata["vaccinationsLastUpdated"])
        if last_update and data_date <= last_update:
            return False

        new_data = False
        response = self.get_resource(self.URL)
        if response:
            self.log.debug("Got Vaccination State Data from Impfdashboard")
            dashboard_data = response.splitlines()
            reader = csv.DictReader(dashboard_data, delimiter='\t', quoting=csv.QUOTE_NONE)

            with self.connection.cursor() as cursor:
                for row in reader:
                    district_id = self.get_district_id(row['code'])
                    if district_id is None:
                        raise ValueError(f"No district_id found for {row['code']}")
                    updated = data_date - timedelta(days=1)
                    cursor.execute("SELECT id FROM covid_vaccinations WHERE date=DATE(%s) AND district_id=%s",
                                   [updated, district_id])
                    if cursor.fetchone():
                        continue

                    new_data = True
                    cursor.execute('SELECT population FROM counties WHERE rs=%s', [district_id])
                    population = cursor.fetchone()[0]
                    if not population:
                        self.log.warning(f"Can't fetch population for {district_id} ({row['code']})")
                        continue

                    rate_full, rate_partial = 0, 0
                    if row['peopleFirstTotal']:
                        rate_partial = int(row['peopleFirstTotal']) / population

                    if row['peopleFullTotal']:
                        rate_full = int(row['peopleFullTotal']) / population

                    # Calculate diff
                    cursor.execute('SELECT vaccinated_full, vaccinated_partial FROM covid_vaccinations '
                                   'WHERE district_id=%s AND date=SUBDATE(DATE(%s), 1)', [district_id, updated])
                    record = cursor.fetchone()
                    doses_diff = None
                    if record:
                        doses_diff = int(row['peopleFirstTotal']) + int(row['peopleFullTotal']) - record[0] - record[1]

                    cursor.execute('INSERT INTO covid_vaccinations (district_id, date, vaccinated_partial, '
                                   'vaccinated_full, rate_partial, rate_full, doses_diff) VALUE (%s, %s, %s, %s, %s, %s, %s)',
                                   [district_id, updated, row['peopleFirstTotal'],
                                    row['peopleFullTotal'], rate_partial, rate_full, doses_diff])
            self.connection.commit()
        return new_data
