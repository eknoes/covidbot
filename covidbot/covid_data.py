import codecs
import csv
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum
from typing import Tuple, List, Optional, Union

import requests
from mysql.connector import MySQLConnection


class TrendValue(Enum):
    UP = 0
    SAME = 1
    DOWN = 2


@dataclass
class District:
    name: str
    type: Optional[str] = None


@dataclass
class VaccinationData:
    vaccinated_full: int
    vaccinated_partial: int
    full_rate: float
    partial_rate: float
    date: date


@dataclass
class RValueData:
    date: date
    r_value_7day: float
    r_trend: Optional[TrendValue] = None

@dataclass
class DistrictData(District):
    date: Optional[datetime.date] = None
    incidence: Optional[float] = None
    incidence_trend: Optional[TrendValue] = None
    new_cases: Optional[int] = None
    cases_trend: Optional[TrendValue] = None
    new_deaths: Optional[int] = None
    deaths_trend: Optional[TrendValue] = None
    total_cases: Optional[int] = None
    total_deaths: Optional[int] = None
    vaccinations: Optional[VaccinationData] = None
    r_value: Optional[RValueData] = None


class CovidData(object):
    connection: MySQLConnection
    log = logging.getLogger(__name__)

    def __init__(self, connection: MySQLConnection) -> None:
        self.connection = connection
        self._create_tables()

    def _create_tables(self):
        self.log.debug("Creating Tables")
        with self.connection.cursor(dictionary=False) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS counties '
                           '(rs INTEGER PRIMARY KEY, county_name VARCHAR(255), type VARCHAR(30),'
                           'population INTEGER NULL DEFAULT NULL, parent INTEGER, '
                           'FOREIGN KEY(parent) REFERENCES counties(rs) ON DELETE NO ACTION,'
                           'UNIQUE(rs, county_name))')
            # Raw Infection Data
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS covid_data (id INTEGER PRIMARY KEY AUTO_INCREMENT, rs INTEGER, date DATE NULL DEFAULT NULL,'
                'total_cases INT, incidence FLOAT, total_deaths INT,'
                'FOREIGN KEY(rs) REFERENCES counties(rs), UNIQUE(rs, date))')

            # Vaccination Data
            cursor.execute('CREATE TABLE IF NOT EXISTS covid_vaccinations (id INTEGER PRIMARY KEY AUTO_INCREMENT, '
                           'district_id INTEGER, updated DATETIME, vaccinated_partial INTEGER, '
                           'vaccinated_full INTEGER, rate_full FLOAT, rate_partial FLOAT, '
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id, updated))')

            # R Value Data
            cursor.execute('CREATE TABLE IF NOT EXISTS covid_r_value (id INTEGER PRIMARY KEY AUTO_INCREMENT, '
                           'district_id INTEGER, r_date DATE, 7day_r_value FLOAT, updated DATETIME,'
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id, r_date))')

            # Check if view exists
            cursor.execute("SHOW FULL TABLES WHERE TABLE_TYPE LIKE '%VIEW%';")
            exists = False
            for row in cursor.fetchall():
                if row[0] == "covid_data_calculated":
                    exists = True

            if not exists:
                self.log.info("View covid_data_calculated does not exist, creating it!")
                cursor.execute('CREATE VIEW covid_data_calculated AS '
                               'SELECT c.rs, c.county_name, c.type, covid_data.date, '
                               'covid_data.total_cases, covid_data.total_cases - y.total_cases as new_cases, '
                               'covid_data.total_deaths, covid_data.total_deaths - y.total_deaths as new_deaths, '
                               'covid_data.incidence '
                               'FROM covid_data '
                               'LEFT JOIN covid_data y on y.rs = covid_data.rs AND '
                               'y.date = subdate(covid_data.date, 1) '
                               'LEFT JOIN counties c on c.rs = covid_data.rs '
                               'ORDER BY covid_data.date DESC')

            # Insert if not exists
            cursor.execute('INSERT IGNORE INTO counties (rs, county_name, type, parent) '
                           'VALUES (0, "Deutschland", "Staat", NULL)')
            self.connection.commit()
            self.log.debug("Committed Tables")

    @staticmethod
    def clean_district_name(county_name: str) -> Optional[str]:
        if county_name is not None and county_name.count(" ") > 0:
            return " ".join(county_name.split(" ")[1:])
        return county_name

    def search_district_by_name(self, search_str: str) -> List[Tuple[int, str]]:
        search_str = search_str.lower()
        search_str = search_str.replace(" ", "%")
        results = []
        with self.connection.cursor(dictionary=True) as cursor:
            if search_str.isdigit():
                cursor.execute('SELECT rs, county_name FROM counties WHERE rs = %s',
                               [int(search_str)])
            else:
                cursor.execute('SELECT rs, county_name FROM counties WHERE LOWER(county_name) LIKE %s OR '
                               'concat(LOWER(type), LOWER(county_name)) LIKE %s',
                               ['%' + search_str + '%', '%' + search_str + '%'])
            for row in cursor.fetchall():
                if row['county_name'].lower() == search_str.replace("%", " "):
                    return [(row['rs'], row['county_name'])]
                results.append((row['rs'], row['county_name']))
        return results

    def get_district(self, rs: int) -> District:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT county_name, type FROM counties WHERE rs=%s', [int(rs)])
            data = cursor.fetchone()
            return District(data['county_name'], type=data['type'])

    def get_district_data(self, rs: int, include_past_days=0, subtract_days=0) \
            -> Optional[Union[DistrictData, List[DistrictData]]]:
        """
        Fetches the Covid19 data for a certain district for today.
        :param rs: ID of the district
        :param include_past_days: Provide history data. If > 0 will return List[DistrictData] with len = today + past_days
        :param subtract_days: Do not fetch for today, but for today - subtract_days
        :return: DistrictData or List[DistrictData]
        """
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT * FROM covid_data_calculated WHERE rs=%s ORDER BY date DESC LIMIT %s,%s',
                           [rs, subtract_days, include_past_days + 2])

            results = []
            for record in cursor.fetchall():
                # Check if vaccination data is available
                vacc_data = None
                if include_past_days == 0:
                    cursor.execute('SELECT vaccinated_full, vaccinated_partial, rate_full, rate_partial, '
                                   'DATE(updated) as updated '
                                   'FROM covid_vaccinations WHERE district_id=%s and DATE(updated)<=%s '
                                   'ORDER BY updated DESC LIMIT 1',
                                   [rs, record['date']])
                    vacc = cursor.fetchone()
                    if vacc:
                        vacc_data = VaccinationData(vacc['vaccinated_full'], vacc['vaccinated_partial'],
                                                    vacc['rate_full'], vacc['rate_partial'], vacc['updated'])

                results.append(DistrictData(name=record['county_name'], incidence=record['incidence'],
                                            type=record['type'], total_cases=record['total_cases'],
                                            total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                            new_deaths=record['new_deaths'], date=record['date'],
                                            vaccinations=vacc_data))

            # Add R-Value, which is usually just available for day -4, so we have to work with LIMIT $offset
            # (see https://www.rki.de/DE/Content/InfAZ/N/Neuartiges_Coronavirus/Projekte_RKI/R-Wert-Erlaeuterung.pdf?__blob=publicationFile)
            if rs == 0 and subtract_days == 0 and include_past_days == 0:
                for i in range(0, len(results)):
                    cursor.execute('SELECT r_date, `7day_r_value` FROM covid_r_value WHERE district_id=%s '
                                   'ORDER BY r_date DESC LIMIT %s,1', [rs, i])
                    data = cursor.fetchone()
                    if data:
                        r_data = RValueData(data['r_date'], data['7day_r_value'])
                        results[i].r_value = r_data

            # Add Trend in comparison to last week
            if len(results) >= 8:
                for i in range(len(results) - 7):
                    results[i] = self.fill_trend(results[i], results[i + 7], results[i + 1])
            elif results:
                cursor.execute('SELECT * FROM covid_data_calculated WHERE rs=%s AND date=SUBDATE(Date(%s), 7) LIMIT 1',
                               [rs, results[0].date])
                record = cursor.fetchone()
                last_week, yesterday = None, None
                if record:
                    last_week = DistrictData(name=record['county_name'], incidence=record['incidence'],
                                             type=record['type'], total_cases=record['total_cases'],
                                             total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                             new_deaths=record['new_deaths'], date=record['date'])

                if len(results) == 1:
                    cursor.execute('SELECT * FROM covid_data_calculated WHERE rs=%s AND date=SUBDATE(Date(%s), 1) '
                                   'LIMIT 1', [rs, results[0].date])
                    record = cursor.fetchone()
                    if record:
                        yesterday = DistrictData(name=record['county_name'], incidence=record['incidence'],
                                                 type=record['type'], total_cases=record['total_cases'],
                                                 total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                                 new_deaths=record['new_deaths'], date=record['date'])
                else:
                    yesterday = results[1]

                if not last_week and yesterday:
                    last_week = yesterday

                if last_week:
                    results[0] = self.fill_trend(results[0], last_week, yesterday)

            if len(results) < include_past_days + 1:
                logging.warning(f"No more data available for RS{rs}, requested {include_past_days + 1} days "
                                f"but can just provide {len(results)} days")
            elif len(results) == include_past_days + 2:
                results.pop()

            if not results:
                return None
            elif include_past_days == 0:
                return results[0]

            return results

    def get_country_data(self) -> DistrictData:
        return self.get_district_data(0)

    @staticmethod
    def fill_trend(today: DistrictData, last_week: DistrictData, yesterday: Optional[DistrictData]) -> DistrictData:
        if not yesterday:
            yesterday = last_week

        if last_week:
            if not last_week.new_cases or not today.new_cases:
                today.cases_trend = None
            elif last_week.new_cases < today.new_cases:
                today.cases_trend = TrendValue.UP
            elif last_week.new_cases > today.new_cases:
                today.cases_trend = TrendValue.DOWN
            else:
                today.cases_trend = TrendValue.SAME

            if not last_week.new_deaths or not today.new_deaths:
                today.deaths_trend = None
            elif last_week.new_deaths < today.new_deaths:
                today.deaths_trend = TrendValue.UP
            elif last_week.new_deaths > today.new_deaths:
                today.deaths_trend = TrendValue.DOWN
            else:
                today.deaths_trend = TrendValue.SAME

        if yesterday:
            if not yesterday.incidence or not today.incidence:
                today.incidence_trend = None
            elif yesterday.incidence < today.incidence:
                today.incidence_trend = TrendValue.UP
            elif yesterday.incidence > today.incidence:
                today.incidence_trend = TrendValue.DOWN
            else:
                today.incidence_trend = TrendValue.SAME

            if today.r_value and yesterday.r_value:
                if yesterday.r_value.r_value_7day < today.r_value.r_value_7day:
                    today.r_value.r_trend = TrendValue.UP
                elif yesterday.r_value.r_value_7day == today.r_value.r_value_7day:
                    today.r_value.r_trend = TrendValue.SAME
                if yesterday.r_value.r_value_7day > today.r_value.r_value_7day:
                    today.r_value.r_trend = TrendValue.DOWN

        return today

    def get_last_update(self) -> Optional[date]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT MAX(date) as "last_updated" FROM covid_data')
            result = cursor.fetchone()
            return result['last_updated']


class CovidDataUpdater(ABC, CovidData):
    def __init__(self, conn: MySQLConnection):
        super().__init__(conn)

    @abstractmethod
    def update(self) -> bool:
        pass


class RKIUpdater(CovidDataUpdater):
    RKI_LK_CSV = "https://opendata.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0.csv"
    log = logging.getLogger(__name__)

    def update(self) -> bool:
        self.log.info("Check for new RKI data")
        last_update = self.get_last_update()
        header = {}
        if last_update:
            header = {"If-Modified-Since": last_update.strftime('%a, %d %b %Y %H:%M:%S GMT')}
            if last_update == date.today():
                self.log.info(f"Do not update as current data is from {last_update}")
                return False

        r = requests.get(self.RKI_LK_CSV, headers=header)
        if r.status_code == 200:
            self.log.debug("Got RKI Data, checking if new")

            rki_data = codecs.decode(r.content, "utf-8").splitlines()
            reader = csv.DictReader(rki_data)
            self.add_data(reader)
            if last_update is None or last_update < self.get_last_update():
                logging.info(f"Received new data, data is now from {self.get_last_update()}")
                return True
        elif r.status_code == 304:
            self.log.info("RKI has no new data")
        else:
            raise ValueError("RKI CSV Response Status Code is " + str(r.status_code))
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
        if germany.new_cases and germany.new_cases <= 0 or germany.new_deaths and germany.new_deaths <= 0:
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


class VaccinationGermanyUpdater(CovidDataUpdater):
    log = logging.getLogger(__name__)
    URL = "https://services.arcgis.com/OLiydejKCZTGhvWg/ArcGIS/rest/services/Impftabelle_mit_Zweitimpfungen" \
          "/FeatureServer/0/query?where=1%3D1&objectIds=&time=&resultType=none&outFields=AGS%2C+Bundesland%2C" \
          "+Impfungen_kumulativ%2C+Zweitimpfungen_kumulativ%2C+Differenz_zum_Vortag%2C+Impf_Quote%2C" \
          "+Impf_Quote_Zweitimpfungen%2C+Datenstand&returnIdsOnly=false&returnUniqueIdsOnly=false&returnCountOnly" \
          "=false&returnDistinctValues=false&cacheHint=false&orderByFields=Datenstand+DESC&groupByFieldsForStatistics" \
          "=&outStatistics=&having=&resultOffset=&resultRecordCount=17&sqlFormat=none&f=pjson&token= "

    def update(self) -> bool:
        last_update = None
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT updated FROM covid_vaccinations ORDER BY updated DESC LIMIT 1")
            updated = cursor.fetchone()
            if updated:
                last_update = updated[0]

        header = {}
        if last_update:
            if last_update.date() == date.today():
                self.log.info(f"Do not update as current data is from {last_update}")
                return False

            header = {"If-Modified-Since": last_update.strftime('%a, %d %b %Y %H:%M:%S GMT')}

        r = requests.get(self.URL, headers=header)
        if r.status_code == 200:
            self.log.debug("Got Vaccination Data")
            data = json.loads(r.content)

            with self.connection.cursor() as cursor:
                new_data = False
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


class RValueGermanyUpdater(CovidDataUpdater):
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

        header = {}
        if last_update:
            if last_update.date() == date.today():
                self.log.info(f"Do not update R-Value data, current is from {last_update}")
                return False

            header = {"If-Modified-Since": last_update.strftime('%a, %d %b %Y %H:%M:%S GMT')}

        r = requests.get(self.URL, headers=header)
        if r.status_code == 200:
            self.log.debug("Got R-Value Data")

            rki_data = codecs.decode(r.content, "utf-8").splitlines()
            reader = csv.DictReader(rki_data, delimiter=';', )
            district_id = self.search_district_by_name("Deutschland")
            if not district_id:
                raise ValueError("No district_id for Deutschland")
            district_id = district_id[0][0]
            new_data = False
            with self.connection.cursor() as cursor:
                for row in reader:
                    # RKI appends Erläuterungen to Data
                    if row['Datum'] == 'Erläuterung':
                        break

                    if row['Datum'] == '':
                        continue

                    if self.R_VALUE_7DAY_CSV_KEY not in row:
                        raise ValueError(f"{self.R_VALUE_7DAY_CSV_KEY} is not in CSV!")
                    r_date = None
                    try:
                        r_date = datetime.strptime(row['Datum'], "%d.%m.%Y").date()
                    except ValueError as e:
                        self.log.warning(f"Could not get date of string {row['Datum']}")
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
class VaccinationGermanyImpfdashboardUpdater(CovidDataUpdater):
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

        header = {}
        if last_update:
            if last_update.date() == date.today():
                self.log.info(f"Do not update as current data is from {last_update}")
                return False

            header = {"If-Modified-Since": last_update.strftime('%a, %d %b %Y %H:%M:%S GMT')}

        r = requests.get(self.URL, headers=header)
        new_data = False
        if r.status_code == 200:
            self.log.debug("Got Vaccination Data from Impfdashboard")
            dashboard_data = codecs.decode(r.content, "utf-8").splitlines()
            reader = csv.DictReader(dashboard_data, delimiter='\t', quoting=csv.QUOTE_NONE)

            with self.connection.cursor() as cursor:
                for row in reader:
                    updated = datetime.fromisoformat(row['date'])
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
