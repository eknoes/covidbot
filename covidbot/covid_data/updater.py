import csv
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Optional, Dict

import requests
import ujson as json
from mysql.connector import MySQLConnection

from covidbot.covid_data.covid_data import CovidDatabaseCreator


class Updater(ABC):
    connection: MySQLConnection
    log: logging.Logger

    def __init__(self, conn: MySQLConnection):
        self.connection = conn
        self.log = logging.getLogger(str(self.__class__.__name__))
        CovidDatabaseCreator(self.connection)

    def get_resource(self, url: str, chance: Optional[float] = 1.0) -> Optional[str]:
        # Just fetch for a certain chance, 100% by default
        if random.uniform(0.0, 1.0) > chance:
            return None

        header = {}  # {"User-Agent": "CovidBot (https://github.com/eknoes/covid-bot | https://covidbot.d-64.org)"}
        last_update = self.get_last_update()
        if last_update:
            # need to use our own day/month, as locale can't be changed on the fly and we have to ensure not asking for
            # Mär in March
            day = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][last_update.weekday()]
            month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            month = month[last_update.month - 1]
            header["If-Modified-Since"] = day + ", " + last_update.strftime(f'%d {month} %Y %H:%M:%S GMT')

        self.log.debug(f"Requesting url {url}")
        response = requests.get(url, headers=header)

        if response.status_code == 200:
            return response.text
        elif response.status_code == 304:
            self.log.info("No new data available")
        else:
            raise ValueError(f"Updater Response Status Code is {response.status_code}: {response.reason}\n{url}")

    @abstractmethod
    def update(self) -> bool:
        pass

    @abstractmethod
    def get_last_update(self) -> Optional[datetime]:
        pass

    def get_district_id(self, district_name: str) -> Optional[int]:
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT rs, county_name FROM counties WHERE county_name LIKE %s',
                           ["%" + district_name + "%"])
            rows = cursor.fetchall()
            if rows:
                if len(rows) == 1:
                    return rows[0][0]

                for row in rows:
                    if row[1] == district_name:
                        return row[0]


class RKIUpdater(Updater):
    RKI_LK_CSV = "https://services7.arcgis.com/mOBPykOjAyBO2ZKk/arcgis/rest/services/RKI_Landkreisdaten/FeatureServer/0/query?where=1%3D1&objectIds=&time=&geometry=&geometryType=esriGeometryEnvelope&inSR=&spatialRel=esriSpatialRelIntersects&resultType=none&distance=0.0&units=esriSRUnit_Meter&returnGeodetic=false&outFields=RS%2C+cases%2C+county%2C+BEZ%2C+EWZ%2C+BL%2C+BL_ID%2C+cases7_per_100k%2C+deaths%2C+cases7_bl_per_100k%2C+last_update&returnGeometry=false&returnCentroid=false&featureEncoding=esriDefault&multipatchOption=xyFootprint&maxAllowableOffset=&geometryPrecision=&outSR=&datumTransformation=&applyVCSProjection=false&returnIdsOnly=false&returnUniqueIdsOnly=false&returnCountOnly=false&returnExtentOnly=false&returnQueryGeometry=false&returnDistinctValues=false&cacheHint=false&orderByFields=&groupByFieldsForStatistics=&outStatistics=&having=&resultOffset=&resultRecordCount=&returnZ=false&returnM=false&returnExceededLimitFeatures=true&quantizationParameters=&sqlFormat=none&f=pjson&token="
    log = logging.getLogger(__name__)

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MAX(date) FROM covid_data")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()

        # Do not fetch if data is from today
        if last_update == date.today():
            return False

        response = self.get_resource(self.RKI_LK_CSV)
        if response:
            self.log.debug("Got RKI Data, checking if new")
            response_data = json.loads(response)
            self.add_data(response_data['features'])
            if last_update is None or last_update < self.get_last_update():
                logging.info(f"Received new data, data is now from {self.get_last_update()}")
                return True
        return False

    def add_data(self, json_data: Dict) -> None:
        covid_data = []
        rs_data = []
        added_bl = set()
        last_update = self.get_last_update()
        now = datetime.now().date()
        new_updated = None
        for feature in json_data:
            row = feature['attributes']
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
            rs_data.append((int(row['RS']), clean_district_name(row['county']) + " (" + row['BEZ'] + ")",
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
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT new_cases, new_deaths FROM covid_data_calculated '
                           'WHERE rs=%s ORDER BY date DESC LIMIT 1', [self.get_district_id("Deutschland")])
            germany = cursor.fetchone()
            if germany['new_cases'] and (germany['new_cases'] <= 0 or germany['new_cases'] >= 100000) \
                    or germany['new_deaths'] and germany['new_deaths'] <= 0:
                self.log.error("Data is looking weird! Rolling back data update!")
                self.connection.rollback()
                raise ValueError(
                    f"COVID19 {germany['new_cases']} new cases and {germany['new_deaths']} deaths are not plausible. Aborting!")
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

                    updated = datetime.fromtimestamp(row['Datenstand'] // 1000).date()
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


class RValueGermanyUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://www.rki.de/DE/Content/InfAZ/N/Neuartiges_Coronavirus/Projekte_RKI/Nowcasting_Zahlen_csv.csv?__blob" \
          "=publicationFile"
    R_VALUE_7DAY_CSV_KEY = "Schätzer_7_Tage_R_Wert"
    R_VALUE_7DAY_CSV_KEY_ALT = "Sch�tzer_7_Tage_R_Wert"

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MAX(updated) FROM covid_r_value")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()
        if last_update and last_update.date() == date.today():
            return False

        new_data = False
        response = self.get_resource(self.URL, 1)

        if response:
            self.log.debug("Got R-Value Data")

            rki_data = response.splitlines()
            reader = csv.DictReader(rki_data, delimiter=';', )
            district_id = self.get_district_id("Deutschland")
            if district_id is None:
                raise ValueError("No district_id for Deutschland")

            with self.connection.cursor() as cursor:
                for row in reader:
                    # RKI appends Erläuterungen to Data
                    if row['Datum'] == 'Erläuterung':
                        break

                    if row['Datum'] == '':
                        continue

                    if self.R_VALUE_7DAY_CSV_KEY not in row:
                        if self.R_VALUE_7DAY_CSV_KEY_ALT not in row:
                            raise ValueError(f"{self.R_VALUE_7DAY_CSV_KEY} is not in CSV!")
                        r_value = row[self.R_VALUE_7DAY_CSV_KEY_ALT]
                    else:
                        r_value = row[self.R_VALUE_7DAY_CSV_KEY]

                    if r_value == '.':
                        continue
                    else:
                        r_value = float(r_value.replace(",", "."))

                    try:
                        r_date = datetime.strptime(row['Datum'], "%d.%m.%Y").date()
                    except ValueError as e:
                        self.log.error(f"Could not get date of string {row['Datum']}", exc_info=e)
                        continue

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
                    updated = (datetime.fromisoformat(row['date']) + timedelta(days=1))
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


class ICUGermanyUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://diviexchange.blob.core.windows.net/%24web/DIVI_Intensivregister_Auszug_pro_Landkreis.csv"

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MAX(updated) FROM icu_beds")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()

        if last_update and datetime.now() - last_update < timedelta(hours=12):
            return False

        response = self.get_resource(self.URL)
        if response:
            self.log.debug("Got ICU Data from DIVI")
            divi_data = response.splitlines()
            reader = csv.DictReader(divi_data)
            results = []
            for row in reader:
                # Berlin is here AGS = 11000
                if row['gemeindeschluessel'] == '11000':
                    row['gemeindeschluessel'] = '11'
                results.append((row['gemeindeschluessel'], row['daten_stand'], row['betten_frei'], row['betten_belegt'],
                                row['faelle_covid_aktuell'], row['faelle_covid_aktuell_invasiv_beatmet'],
                                row['daten_stand']))

            with self.connection.cursor() as cursor:
                for row in results:
                    cursor.execute("INSERT IGNORE INTO icu_beds (district_id, date, clear, occupied, occupied_covid,"
                                   " covid_ventilated, updated) VALUES (%s, %s, %s, %s, %s, %s, %s)", row)

                # Calculate aggregated values for states
                for i in range(2):
                    cursor.execute(
                        "INSERT IGNORE INTO icu_beds (district_id, date, clear, occupied, occupied_covid, covid_ventilated, updated) "
                        "SELECT c.parent, date, SUM(clear), SUM(occupied), SUM(occupied_covid), "
                        "SUM(covid_ventilated), updated FROM icu_beds "
                        "INNER JOIN counties c on c.rs = icu_beds.district_id "
                        "GROUP BY c.parent, date "
                        "HAVING (COUNT(c.parent) = (SELECT COUNT(*) FROM counties WHERE parent=c.parent) OR c.parent > 0) AND parent IS NOT NULL")
            self.connection.commit()
            if last_update != self.get_last_update():
                return True
        return False


class ICUGermanyHistoryUpdater(Updater):
    log = logging.getLogger(__name__)

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MIN(updated) FROM icu_beds")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        if self.get_last_update() == date(2020, 4, 25):
            return False

        new_data = False

        csv_list = self.get_resource(
            'https://www.divi.de/divi-intensivregister-tagesreport-archiv-csv?start=0&limit=500')
        urls = []

        for url in re.finditer(
                '/divi-intensivregister-tagesreport-archiv-csv/viewdocument/\d{4}/divi-intensivregister-(202[01])-(\d\d)-(\d\d)[-\d]*',
                csv_list):
            urls.append(
                ('https://www.divi.de' + url.group(0), date(int(url.group(1)), int(url.group(2)), int(url.group(3)))))

        for url, data_date in urls:
            with self.connection.cursor(dictionary=True) as cursor:
                cursor.execute('SELECT * FROM icu_beds WHERE date=%s', [data_date])
                data = cursor.fetchall()
                if data:
                    print(f"Data for {data_date} already exists, skipping")
                    continue

                print(f"Get data for {data_date}")
                response = self.get_resource(url)
                if response:
                    self.log.debug("Got historic ICU Data from DIVI")
                    divi_data = response.splitlines()
                    reader = csv.DictReader(divi_data)
                    results = []

                    key_district_id = "gemeindeschluessel"
                    if key_district_id not in reader.fieldnames:
                        key_district_id = "kreis"

                    key_covid_ventilated = "faelle_covid_aktuell_invasiv_beatmet"
                    if key_covid_ventilated not in reader.fieldnames:
                        key_covid_ventilated = "faelle_covid_aktuell_beatmet"

                    if key_covid_ventilated not in reader.fieldnames:
                        key_covid_ventilated = None

                    key_covid = "faelle_covid_aktuell"
                    if key_covid not in reader.fieldnames:
                        key_covid = None

                    for row in reader:
                        # Berlin is here AGS = 11000
                        if row[key_district_id] == '11000':
                            row[key_district_id] = '11'

                        if key_covid_ventilated:
                            num_ventilated = row[key_covid_ventilated]
                        else:
                            num_ventilated = None

                        if key_covid:
                            num_covid = row[key_covid]
                        else:
                            num_covid = None

                        row_contents = [row[key_district_id], data_date, row['betten_frei'], row['betten_belegt'],
                                        num_covid, num_ventilated, data_date]
                        results.append(row_contents)

                    cursor.executemany(
                        "INSERT IGNORE INTO icu_beds (district_id, date, clear, occupied, occupied_covid,"
                        " covid_ventilated, updated) VALUES (%s, %s, %s, %s, %s, %s, %s)", results)
                    self.connection.commit()
                    new_data = True
                else:
                    self.log.warning(f"Not available: {url}")
        return new_data

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


def clean_district_name(county_name: str) -> Optional[str]:
    if county_name is not None and county_name.count(" ") > 0:
        return " ".join(county_name.split(" ")[1:])
    return county_name
