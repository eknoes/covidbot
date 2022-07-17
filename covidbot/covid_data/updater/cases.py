import csv
import logging
from datetime import datetime, date, timedelta
from typing import Optional

import ujson as json

from covidbot.covid_data.updater.districts import RKIDistrictsUpdater
from covidbot.covid_data.updater.updater import Updater


class RKIKeyDataUpdater(Updater):
    RKI_DATA = "https://services7.arcgis.com/mOBPykOjAyBO2ZKk/arcgis/rest/services/rki_key_data_hubv/FeatureServer/0/query?where=1%3D1&objectIds=&time=&resultType=none&outFields=*&returnIdsOnly=false&returnUniqueIdsOnly=false&returnCountOnly=false&returnDistinctValues=false&cacheHint=false&orderByFields=&groupByFieldsForStatistics=&outStatistics=&having=&resultOffset=&resultRecordCount=&sqlFormat=none&f=pjson&token="
    RKI_STATUS = "https://services7.arcgis.com/mOBPykOjAyBO2ZKk/arcgis/rest/services/rki_data_status_v/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=json"

    log = logging.getLogger(__name__)

    def update(self) -> bool:
        # First check that districts exist
        RKIDistrictsUpdater(self.connection).update()

        last_update = self.get_last_update()

        # Do not fetch if data is from today
        if last_update == date.today():
            return False

        # Check RKI Status
        response = self.get_resource(self.RKI_STATUS)
        if not response:
            return False

        response = json.loads(response)
        if response['features'][0]['attributes']['Status'] != "OK":
            return False

        online_date = date.fromtimestamp(response['features'][0]['attributes']['Datum'] / 1000)
        if last_update is not None and online_date <= last_update:
            return False

        self.log.warning(f"RKIDEBUG: New Data, Timestamp_txt: {response['features'][0]['attributes']['Timestamp_txt']}")

        response = self.get_resource(self.RKI_DATA)
        if response:
            self.log.debug("Got RKI Data, checking if new")
            response_data = json.loads(response)

            covid_data = []
            for item in response_data['features']:
                district = item['attributes']
                covid_data.append((district['AdmUnitId'], online_date, district['AnzFall'], district['Inz7T'], district['AnzTodesfall']))
                if district['AdmUnitId'] == 0:
                    self.log.warning(f"RKIDEBUG: Inz7T: {district['Inz7T']}, AnzFall: {district['AnzFall']}")

            with self.connection.cursor(dictionary=True) as cursor:
                cursor.executemany('''INSERT INTO covid_data (rs, date, total_cases, incidence, total_deaths)
                 VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE rs=rs''', covid_data)

                # Plausibility check
                cursor.execute("SELECT * FROM covid_data_calculated WHERE county_name LIKE '%Deutschland%' ORDER BY date DESC LIMIT 1")
                row = cursor.fetchone()
                if (row['new_cases'] is not None and row['new_cases'] < 0) or (row['new_deaths'] is not None and row['new_deaths'] < 0) or (row['new_cases'] == 0 and online_date.weekday() not in [0, 6]):
                    self.connection.rollback()
                    raise ValueError(f"Invalid Data: {row['new_cases']} reported cases, {row['new_deaths']} reported deaths")
            self.connection.commit()

            if last_update is None or last_update < self.get_last_update():
                logging.info(f"Received new data, data is now from {self.get_last_update()}")
                return True
        return False

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MAX(date) FROM covid_data")
            row = cursor.fetchone()
            if row:
                return row[0]


class RKIHistoryUpdater(Updater):
    DEATHS_URL = "https://raw.githubusercontent.com/jgehrcke/covid-19-germany-gae/master/deaths-rki-by-ags.csv"
    CASES_URL = "https://raw.githubusercontent.com/jgehrcke/covid-19-germany-gae/master/cases-rki-by-ags.csv"
    INCIDENCE_URL = "https://raw.githubusercontent.com/jgehrcke/covid-19-germany-gae/master/more-data/7di-rki-by-ags.csv"
    max_delta = 1
    min_delta = 60
    log = logging.getLogger(__name__)

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT last_update FROM covid_data WHERE date = SUBDATE(CURRENT_DATE, 8) AND rs=0 LIMIT 1")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        updated = False
        if self.update_cases():
            self.log.info("New case data available")
            updated = True

        if self.update_deaths():
            self.log.info("New deaths data available")
            updated = True

        if self.update_incidences():
            self.log.info("New incidence data available")
            updated = True
        return updated

    def calculate_aggregated_values(self, new_updated: Optional[date] = None):
        self.log.debug("Calculating aggregated values")
        with self.connection.cursor(dictionary=True) as cursor:
            # Calculate all parents, must be executed for every depth
            for i in range(2):
                # Calculate COVID-19 Data
                args = []
                where_query = ""
                if new_updated:
                    where_query = "AND date = DATE(%s) "
                    args = [new_updated]

                cursor.execute(f'''INSERT INTO covid_data (rs, date, total_cases, total_deaths, last_update)
                                    SELECT new.parent, new_date, new_cases, new_deaths, last_update
                                    FROM
                                    (SELECT c.parent as parent, date as new_date, SUM(total_cases) as new_cases,
                                     SUM(total_deaths) as new_deaths, last_update FROM covid_data 
                                     LEFT JOIN counties c on covid_data.rs = c.rs
                                     WHERE c.parent IS NOT NULL {where_query}
                                     GROUP BY c.parent, date)
                                    as new
                                  ON DUPLICATE KEY UPDATE 
                                  date=new.new_date, total_cases=new.new_cases, total_deaths=new.new_deaths, 
                                  last_update=new.last_update''',
                               args)
                # Calculate Incidence
                cursor.execute('UPDATE covid_data, '
                               '(SELECT c.parent as rs, d.date, SUM(c.population * d.incidence) / SUM(c.population) '
                               'as incidence FROM covid_data as d '
                               'LEFT JOIN counties c on c.rs = d.rs '
                               'WHERE c.parent IS NOT NULL '
                               'GROUP BY date, c.parent) as incidence '
                               'SET covid_data.incidence = incidence.incidence '
                               'WHERE covid_data.incidence IS NULL AND covid_data.date = incidence.date '
                               'AND covid_data.rs = incidence.rs')

    def update_cases(self) -> bool:
        cases = self.get_resource(self.CASES_URL, True)
        if not cases:
            return False

        cases_csv = csv.DictReader(cases.splitlines())

        new_cases = False
        with self.connection.cursor() as cursor:
            for row in cases_csv:
                updated = None
                for field in cases_csv.fieldnames:
                    if field[:3] == "sum":
                        continue
                    elif field[:4] == "time":
                        updated = row[field]
                        updated = date(int(updated[:4]), int(updated[5:7]), int(updated[8:10]))
                        # To keep it in sync with fresh RKI data
                        updated = updated + timedelta(days=1)
                        self.log.info(f"Got historic case data for {updated}")
                        delta = (date.today() - updated)
                        if not (self.max_delta < delta.days < self.min_delta):
                            self.log.info(f"Skip {updated}")
                            break
                        continue

                    district_id = field
                    if district_id == '11000':
                        district_id = '11'

                    if district_id == '16056':
                        continue

                    cases_num = int(row[field])
                    cursor.execute('INSERT INTO covid_data (rs, date, total_cases) VALUE (%s, %s, %s) '
                                   'ON DUPLICATE KEY UPDATE covid_data.total_cases=%s, covid_data.last_update=CURRENT_TIMESTAMP()',
                                   [int(district_id), updated, cases_num, cases_num])
                    new_cases = True
                self.connection.commit()
            self.calculate_aggregated_values()
        self.connection.commit()

        return new_cases

    def update_deaths(self) -> bool:
        deaths = self.get_resource(self.DEATHS_URL, True)
        if not deaths:
            return False
        deaths_csv = csv.DictReader(deaths.splitlines())
        new_deaths = False
        with self.connection.cursor() as cursor:
            for row in deaths_csv:
                updated = None
                for field in deaths_csv.fieldnames:
                    if field[:3] == "sum":
                        continue
                    elif field[:4] == "time":
                        updated = row[field]
                        updated = date(int(updated[:4]), int(updated[5:7]), int(updated[8:10]))
                        # To keep it in sync with fresh RKI data
                        updated = updated + timedelta(days=1)
                        self.log.info(f"Got historic deaths data for {updated}")
                        delta = (date.today() - updated)
                        if not (self.max_delta < delta.days < self.min_delta):
                            self.log.info(f"Skip {updated}")
                            break
                        continue

                    district_id = field
                    if district_id == '11000':
                        district_id = '11'

                    if district_id == '16056':
                        continue

                    deaths_num = int(row[field])
                    cursor.execute('INSERT INTO covid_data (rs, date, total_deaths) VALUE (%s, %s, %s) '
                                   'ON DUPLICATE KEY UPDATE covid_data.total_deaths=%s, covid_data.last_update=CURRENT_TIMESTAMP()',
                                   [int(district_id), updated, deaths_num, deaths_num])
                    new_deaths = True
                self.connection.commit()
            self.calculate_aggregated_values()
        self.connection.commit()

        return new_deaths

    def update_incidences(self) -> bool:
        incidences = self.get_resource(self.INCIDENCE_URL, True)
        if not incidences:
            return False
        incidences_csv = csv.DictReader(incidences.splitlines())

        new_data = False
        with self.connection.cursor() as cursor:
            for row in incidences_csv:
                updated = None
                for field in incidences_csv.fieldnames:
                    if field[:3] == "sum":
                        continue
                    elif field[:4] == "time":
                        updated = row[field]
                        updated = date(int(updated[:4]), int(updated[5:7]), int(updated[8:10]))
                        # To keep it in sync with fresh RKI data
                        updated = updated + timedelta(days=1)
                        self.log.info(f"Got historic incidence data for {updated}")

                        delta = (date.today() - updated)
                        if not (self.max_delta < delta.days < self.min_delta):
                            self.log.info(f"Skip {updated}")
                            break
                        continue

                    district_id = field[:-4]
                    if district_id == '11000':
                        district_id = '11'

                    if district_id == 'germany':
                        district_id = '0'

                    if district_id == '16056':
                        continue

                    incidence = float(row[field])

                    cursor.execute(
                        'INSERT INTO covid_data (rs, date, incidence) VALUE (%s, %s, %s) '
                        'ON DUPLICATE KEY UPDATE covid_data.incidence=%s, covid_data.last_update=CURRENT_TIMESTAMP()',
                        [int(district_id), updated, incidence, incidence])
                    new_data = True
                self.connection.commit()

        return new_data
