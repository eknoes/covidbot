import csv
import logging
from datetime import datetime, timedelta
from typing import Optional

import ujson as json

from covidbot.covid_data.updater.updater import Updater


class VaccinationGermanyUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://services.arcgis.com/OLiydejKCZTGhvWg/ArcGIS/rest/services/Impftabelle_mit_Zweitimpfungen" \
          "/FeatureServer/0/query?where=1%3D1&objectIds=&time=&resultType=none&outFields=AGS%2C+Bundesland%2C" \
          "+Impfungen_kumulativ%2C+Zweitimpfungen_kumulativ%2C+Differenz_zum_Vortag%2C+Impf_Quote%2C" \
          "+Impf_Quote_Zweitimpfungen%2C+Datenstand&returnIdsOnly=false&returnUniqueIdsOnly=false&returnCountOnly" \
          "=false&returnDistinctValues=false&cacheHint=false&orderByFields=Datenstand+DESC&groupByFieldsForStatistics" \
          "=&outStatistics=&having=&resultOffset=&resultRecordCount=&sqlFormat=none&f=pjson&token= "

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MAX(last_update) FROM covid_vaccinations WHERE district_id != 0")
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
            self.log.debug("Got Vaccination Data")
            data = json.loads(response)

            with self.connection.cursor() as cursor:
                for row in data['features']:
                    row = row['attributes']
                    if row['Bundesland'] == "Gesamt":
                        row['Bundesland'] = "Deutschland"

                    district_id = self.get_district_id(row['Bundesland'])
                    if district_id is None:
                        self.log.warning(f"Can't find district_id for {row['Bundesland']}!")
                        continue

                    updated = datetime.fromtimestamp(row['Datenstand'] // 1000).date() - timedelta(days=1)
                    cursor.execute("SELECT id FROM covid_vaccinations WHERE date = %s AND district_id=%s",
                                   [updated, district_id])
                    record = cursor.fetchone()

                    if record is not None:
                        continue

                    new_data = True
                    cursor.execute('SELECT population FROM counties WHERE rs=%s', [district_id])
                    population = cursor.fetchone()[0]
                    if not population:
                        self.log.warning(f"Can't fetch population for {district_id} ({row['Bundesland']})")
                        continue

                    rate_full, rate_partial = 0, 0
                    if row['Impfungen_kumulativ']:
                        rate_partial = row['Impfungen_kumulativ'] / population

                    if row['Zweitimpfungen_kumulativ']:
                        rate_full = row['Zweitimpfungen_kumulativ'] / population

                    cursor.execute('INSERT INTO covid_vaccinations (district_id, date, vaccinated_partial, '
                                   'vaccinated_full, rate_partial, rate_full, doses_diff) VALUE (%s, %s, %s, %s, %s, %s, %s)',
                                   [district_id, updated, row['Impfungen_kumulativ'],
                                    row['Zweitimpfungen_kumulativ'], rate_partial, rate_full,
                                    row['Differenz_zum_Vortag']])
            self.connection.commit()
        return new_data


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