import codecs
import csv
import logging
import os
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


class CovidData(object):
    RKI_LK_CSV = "https://opendata.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0.csv"
    DIVI_INTENSIVREGISTER_CSV = "https://opendata.arcgis.com/datasets/8fc79b6cf7054b1b80385bda619f39b8_0.csv"

    connection: MySQLConnection
    log = logging.getLogger(__name__)

    def __init__(self, connection: MySQLConnection, disable_autoupdate=False) -> None:
        self.connection = connection
        self._create_tables()
        if not disable_autoupdate:
            self.fetch_current_data()

    def _create_tables(self):
        self.log.debug("Creating Tables")
        with self.connection.cursor(dictionary=False) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS counties '
                           '(rs INTEGER PRIMARY KEY, county_name VARCHAR(255), type VARCHAR(30),'
                           'population INTEGER NULL DEFAULT NULL, parent INTEGER, '
                           'FOREIGN KEY(parent) REFERENCES counties(rs) ON DELETE NO ACTION,'
                           'UNIQUE(rs, county_name))')
            # Raw Data
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS covid_data (id SERIAL, rs INTEGER, date DATE NULL DEFAULT NULL,'
                'total_cases INT, incidence FLOAT, total_deaths INT,'
                'FOREIGN KEY(rs) REFERENCES counties(rs), UNIQUE(rs, date))')

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

    def add_data(self, filename: str):
        if filename is None:
            raise ValueError("filename must be given")
        elif not os.path.isfile(filename):
            raise ValueError("File " + filename + "does not exist")
        else:
            with open(filename, "r") as rki_csv:
                self.log.debug("Reading from Data file")
                reader = csv.DictReader(rki_csv)
                self._add_data(reader)

    def _add_data(self, reader: csv.DictReader) -> None:
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
            self.connection.commit()
        self.calculate_aggregated_values(new_updated)
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

            self.connection.commit()

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
                           [rs, subtract_days, include_past_days + 1])

            results = []
            for record in cursor.fetchall():
                results.append(DistrictData(name=record['county_name'], incidence=record['incidence'],
                                            type=record['type'], total_cases=record['total_cases'],
                                            total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                            new_deaths=record['new_deaths'], date=record['date']))

            # Add Trend in comparison to last week
            if len(results) >= 7:
                for i in range(len(results) - 6):
                    results[i] = self.fill_trend(results[i], results[i + 6])
            elif results:
                cursor.execute('SELECT * FROM covid_data_calculated WHERE rs=%s AND date=(Date(%s) - 7) LIMIT 1',
                               [rs, results[0].date])
                record = cursor.fetchone()
                if record:
                    last_week = DistrictData(name=record['county_name'], incidence=record['incidence'],
                                             type=record['type'], total_cases=record['total_cases'],
                                             total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                             new_deaths=record['new_deaths'], date=record['date'])
                    results[0] = self.fill_trend(results[0], last_week)

            if len(results) < include_past_days + 1:
                logging.warning(f"No more data available for RS{rs}, requested {include_past_days + 1} days "
                                f"but can just provide {len(results)} days")

            if not results:
                return None
            elif include_past_days == 0:
                return results[0]

            return results

    def get_country_data(self) -> DistrictData:
        return self.get_district_data(0)

    @staticmethod
    def fill_trend(today: DistrictData, last_week: DistrictData) -> DistrictData:
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

            if not last_week.incidence or not today.incidence:
                today.incidence_trend = None
            elif last_week.incidence < today.incidence:
                today.incidence_trend = TrendValue.UP
            elif last_week.incidence > today.incidence:
                today.incidence_trend = TrendValue.DOWN
            else:
                today.incidence_trend = TrendValue.SAME
        return today

    def get_last_update(self) -> Optional[date]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT MAX(date) as "last_updated" FROM covid_data')
            result = cursor.fetchone()
            return result['last_updated']

    def fetch_current_data(self) -> bool:
        self.log.info("Start Updating data")
        last_update = self.get_last_update()
        header = {}
        if last_update:
            header = {"If-Modified-Since": last_update.strftime('%a, %d %b %Y %H:%M:%S GMT')}

        r = requests.get(self.RKI_LK_CSV, headers=header)
        if r.status_code == 200:
            self.log.info("Got RKI Data, checking if new")

            rki_data = codecs.decode(r.content, "utf-8").splitlines()
            reader = csv.DictReader(rki_data)
            self._add_data(reader)
            if last_update is None or last_update < self.get_last_update():
                return True
        elif r.status_code == 304:
            self.log.info("RKI has no new data")
        else:
            self.log.warning("RKI CSV Response Status Code is " + str(r.status_code))
        return False
