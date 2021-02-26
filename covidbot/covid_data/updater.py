import codecs
import csv
import json
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from mysql.connector import MySQLConnection

from covidbot.covid_data.covid_data import CovidData


class Updater(ABC, CovidData):
    def __init__(self, conn: MySQLConnection):
        super().__init__(conn)

    def get_resource(self, url: str, last_update: Optional[datetime]) -> Optional[bytes]:
        header = {}
        if last_update:
            header = {"If-Modified-Since": last_update.strftime('%a, %d %b %Y %H:%M:%S GMT')}
        response = requests.get(url, headers=header)
        if response.status_code == 200:
            return response.content
        elif response.status_code == 304:
            self.log.info("No new data available")
        else:
            raise ValueError("Updater Response Status Code is " + str(response.status_code))

    @abstractmethod
    def update(self) -> bool:
        pass


class RKIUpdater(Updater):
    RKI_LK_CSV = "https://opendata.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0.csv"
    log = logging.getLogger(__name__)

    def update(self) -> bool:
        last_update = self.get_last_update()

        response = self.get_resource(self.RKI_LK_CSV, last_update)
        if response:
            self.log.debug("Got RKI Data, checking if new")
            rki_data = codecs.decode(response, "utf-8").splitlines()
            reader = csv.DictReader(rki_data)
            self.add_data(reader)
            if last_update is None or last_update < self.get_last_update():
                logging.info(f"Received new data, data is now from {self.get_last_update()}")
                return True
        return False

    def add_data(self, reader: csv.DictReader) -> None:
        covid_data = []
        rs_data = []
        added_bl = set()
        last_update = self.get_last_update()
        now = datetime.now().date()
        new_updated = None
        for row in reader:
            new_updated = datetime.strptime(row['last_update'], "%d.%m.%Y, %H:%M Uhr").date()
            if last_update and new_updated <= last_update or now < new_updated:
                # Do not take data from future, important for testing
                continue

            # Gather Bundesland data
            if row['BL_ID'] not in added_bl:
                covid_data.append(
                    (int(row['BL_ID']), new_updated, None, float(row['cases7_bl_per_100k']),
                     None))
                rs_data.append((int(row['BL_ID']), row['BL'], 'Bundesland', None, 0))
                added_bl.add(row['BL_ID'])

            covid_data.append((int(row['RS']), new_updated, int(row['cases']), float(row['cases7_per_100k']),
                               int(row['deaths'])))
            rs_data.append((int(row['RS']), self.clean_district_name(row['county']) + " (" + row['BEZ'] + ")",
                            row['BEZ'], int(row['EWZ']), int(row['BL_ID'])))

        self.log.debug("Insert new data into counties and covid_data")
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.executemany('INSERT INTO counties (rs, county_name, type, population, parent) '
                               'VALUES (%s, %s, %s, %s, %s) '
                               'ON DUPLICATE KEY UPDATE population=VALUES(population)',
                               rs_data)
            cursor.executemany('''INSERT INTO covid_data (rs, date, total_cases, incidence, total_deaths)
             VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE rs=rs''', covid_data)
        self.calculate_aggregated_values(new_updated)

        # Check for Plausibility, as Dataset has been wrong sometimes
        germany = self.get_country_data()
        if germany.new_cases and (germany.new_cases <= 0 or germany.new_cases >= 100000) \
                or germany.new_deaths and germany.new_deaths <= 0:
            self.log.error("Data is looking weird! Rolling back data update!")
            self.connection.rollback()
            raise ValueError(
                f"COVID19 {germany.new_cases} new cases and {germany.new_deaths} deaths are not plausible. Aborting!")
        else:
            self.connection.commit()
        self.log.debug("Finished inserting new data")

    def calculate_aggregated_values(self, new_updated: date):
        self.log.debug("Calculating aggregated values")
        with self.connection.cursor(dictionary=True) as cursor:
            # Calculate all parents, must be executed for every depth
            for i in range(2):
                # Calculate Covid Data
                cursor.execute('''INSERT INTO covid_data (rs, date, total_cases, total_deaths)
                                    SELECT new.parent, new_date, new_cases, new_deaths
                                    FROM
                                    (SELECT c.parent as parent, date as new_date, SUM(total_cases) as new_cases,
                                     SUM(total_deaths) as new_deaths FROM covid_data_calculated 
                                     LEFT JOIN counties c on covid_data_calculated.rs = c.rs
                                     WHERE c.parent IS NOT NULL AND date = DATE(%s)
                                     GROUP BY c.parent, date)
                                    as new
                                  ON DUPLICATE KEY UPDATE 
                                  date=new.new_date, total_cases=new.new_cases, total_deaths=new.new_deaths''',
                               [new_updated])
                # Calculate Population
                cursor.execute(
                    'UPDATE counties, (SELECT ncounties.rs as id, SUM(counties.population) as pop FROM counties\n'
                    '    LEFT JOIN counties ncounties ON ncounties.rs = counties.parent\n'
                    'WHERE counties.parent IS NOT NULL GROUP BY counties.parent) as pop_sum\n'
                    'SET population=pop_sum.pop WHERE rs=pop_sum.id')
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


class VaccinationGermanyUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://services.arcgis.com/OLiydejKCZTGhvWg/ArcGIS/rest/services/Impftabelle_mit_Zweitimpfungen" \
          "/FeatureServer/0/query?where=1%3D1&objectIds=&time=&resultType=none&outFields=AGS%2C+Bundesland%2C" \
          "+Impfungen_kumulativ%2C+Zweitimpfungen_kumulativ%2C+Differenz_zum_Vortag%2C+Impf_Quote%2C" \
          "+Impf_Quote_Zweitimpfungen%2C+Datenstand&returnIdsOnly=false&returnUniqueIdsOnly=false&returnCountOnly" \
          "=false&returnDistinctValues=false&cacheHint=false&orderByFields=Datenstand+DESC&groupByFieldsForStatistics" \
          "=&outStatistics=&having=&resultOffset=&resultRecordCount=51&sqlFormat=none&f=pjson&token= "

    def update(self) -> bool:
        last_update = None
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT updated FROM covid_vaccinations WHERE district_id != 0 "
                           "ORDER BY updated DESC LIMIT 1")
            updated = cursor.fetchone()
            if updated:
                last_update = updated[0]
        new_data = False

        response = self.get_resource(self.URL, last_update)
        if response:
            self.log.debug("Got Vaccination Data")
            data = json.loads(response)

            with self.connection.cursor() as cursor:
                for row in data['features']:
                    row = row['attributes']
                    if row['Bundesland'] == "Gesamt":
                        row['Bundesland'] = "Deutschland"

                    district = self.search_district_by_name(row['Bundesland'])
                    if not district:
                        self.log.warning(f"Can't find district_id for {row['Bundesland']}!")
                        continue

                    district_id = district[0][0]
                    updated = datetime.fromtimestamp(row['Datenstand'] // 1000)
                    cursor.execute("SELECT id FROM covid_vaccinations WHERE updated = %s AND district_id=%s",
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
                    if row['Impfungen_kumulativ']:
                        rate_partial = row['Impfungen_kumulativ'] / population

                    if row['Zweitimpfungen_kumulativ']:
                        rate_full = row['Zweitimpfungen_kumulativ'] / population

                    cursor.execute('INSERT INTO covid_vaccinations (district_id, updated, vaccinated_partial, '
                                   'vaccinated_full, rate_partial, rate_full) VALUE (%s, %s, %s, %s, %s, %s)',
                                   [district_id, updated, row['Impfungen_kumulativ'],
                                    row['Zweitimpfungen_kumulativ'], rate_partial, rate_full])
            self.connection.commit()
        return new_data


class RValueGermanyUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://www.rki.de/DE/Content/InfAZ/N/Neuartiges_Coronavirus/Projekte_RKI/Nowcasting_Zahlen_csv.csv?__blob" \
          "=publicationFile"
    R_VALUE_7DAY_CSV_KEY = "Schätzer_7_Tage_R_Wert"

    def update(self) -> bool:
        last_update = None
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT updated FROM covid_r_value ORDER BY updated DESC LIMIT 1")
            updated = cursor.fetchone()
            if updated:
                last_update = updated[0]
        new_data = False

        response = self.get_resource(self.URL, last_update)

        if response:
            self.log.debug("Got R-Value Data")

            rki_data = codecs.decode(response, "utf-8").splitlines()
            reader = csv.DictReader(rki_data, delimiter=';', )
            district_id = self.search_district_by_name("Deutschland")
            if not district_id:
                raise ValueError("No district_id for Deutschland")
            district_id = district_id[0][0]
            with self.connection.cursor() as cursor:
                for row in reader:
                    # RKI appends Erläuterungen to Data
                    if row['Datum'] == 'Erläuterung':
                        break

                    if row['Datum'] == '':
                        continue

                    if self.R_VALUE_7DAY_CSV_KEY not in row:
                        raise ValueError(f"{self.R_VALUE_7DAY_CSV_KEY} is not in CSV!")

                    try:
                        r_date = datetime.strptime(row['Datum'], "%d.%m.%Y").date()
                    except ValueError as e:
                        self.log.error(f"Could not get date of string {row['Datum']}", exc_info=e)
                        continue

                    r_value = row[self.R_VALUE_7DAY_CSV_KEY]
                    if r_value == '.':
                        continue
                    else:
                        r_value = float(r_value.replace(",", "."))

                    cursor.execute("SELECT id FROM covid_r_value WHERE district_id=%s AND r_date=%s",
                                   [district_id, r_date])
                    if cursor.fetchone():
                        continue

                    new_data = True
                    cursor.execute("INSERT INTO covid_r_value (district_id, r_date, `7day_r_value`, updated) "
                                   "VALUES (%s, %s, %s, %s)", [district_id, r_date, r_value, datetime.now()])
            self.connection.commit()
        return new_data


# As a backup, it provides numbers only for Germany not for the single states, but is more up-to-date
class VaccinationGermanyImpfdashboardUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://impfdashboard.de/static/data/germany_vaccinations_timeseries_v2.tsv"

    def update(self) -> bool:
        last_update = None
        district_id = self.search_district_by_name("Deutschland")
        if not district_id:
            raise ValueError("No district_id for Deutschland")
        district_id = district_id[0][0]

        with self.connection.cursor() as cursor:
            cursor.execute("SELECT updated FROM covid_vaccinations WHERE district_id=%s ORDER BY updated DESC LIMIT 1",
                           [district_id])
            updated = cursor.fetchone()
            if updated:
                last_update = updated[0]
        new_data = False

        response = self.get_resource(self.URL, last_update)
        if response:
            self.log.debug("Got Vaccination Data from Impfdashboard")
            dashboard_data = codecs.decode(response, "utf-8").splitlines()
            reader = csv.DictReader(dashboard_data, delimiter='\t', quoting=csv.QUOTE_NONE)

            with self.connection.cursor() as cursor:
                for row in reader:
                    # The other vaccination source uses another timeformat, so we have to add a day
                    updated = datetime.fromisoformat(row['date']) + timedelta(days=1)
                    cursor.execute("SELECT id FROM covid_vaccinations WHERE updated = %s AND district_id=%s",
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

                    cursor.execute('INSERT INTO covid_vaccinations (district_id, updated, vaccinated_partial, '
                                   'vaccinated_full, rate_partial, rate_full) VALUE (%s, %s, %s, %s, %s, %s)',
                                   [district_id, updated, row['personen_erst_kumulativ'],
                                    row['personen_voll_kumulativ'], rate_partial, rate_full])
            self.connection.commit()
        return new_data
