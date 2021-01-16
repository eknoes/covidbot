import codecs
import csv
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Tuple, List, Union, Optional

import requests
from mysql.connector import MySQLConnection


class TrendValue(Enum):
    UP = 0
    SAME = 1
    DOWN = 2


@dataclass
class DistrictData:
    name: str
    date: Optional[datetime] = None
    type: Optional[str] = None
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

    def __init__(self, connection: MySQLConnection) -> None:
        self.connection = connection
        self._create_tables()
        self.fetch_current_data()

    def _create_tables(self):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS counties '
                           '(rs INTEGER PRIMARY KEY, county_name VARCHAR(255), type VARCHAR(30), parent INTEGER,'
                           'FOREIGN KEY(parent) REFERENCES counties(rs) ON DELETE NO ACTION,'
                           'UNIQUE(rs, county_name))')
            # Raw Data
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS covid_data (id SERIAL, rs INTEGER, date TIMESTAMP NULL DEFAULT NULL,'
                'total_cases INT, incidence FLOAT, total_deaths INT,'
                'FOREIGN KEY(rs) REFERENCES counties(rs), UNIQUE(rs, date))')

            cursor.execute('CREATE OR REPLACE VIEW covid_data_calculated AS '
                           'SELECT c.rs, c.county_name, c.type, covid_data.date, '
                           'covid_data.total_cases, covid_data.total_cases - y.total_cases as new_cases, '
                           'covid_data.total_deaths, covid_data.total_deaths - y.total_deaths as new_deaths, '
                           'covid_data.incidence '
                           'FROM covid_data '
                           'LEFT JOIN covid_data y on y.rs = covid_data.rs AND '
                           'DATE(y.date) = subdate(date(covid_data.date), 1) '
                           'LEFT JOIN counties c on c.rs = covid_data.rs '
                           'ORDER BY covid_data.date DESC')
            self.connection.commit()

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
        for row in reader:
            updated = datetime.strptime(row['last_update'], "%d.%m.%Y, %H:%M Uhr")
            if last_update is not None:
                if updated <= last_update:
                    continue

            # Gather Bundesland data
            if row['BL_ID'] not in added_bl:
                covid_data.append(
                    (int(row['BL_ID']), updated, None, float(row['cases7_bl_per_100k']),
                     None))
                rs_data.append((int(row['BL_ID']), row['BL'], 'Bundesland', None))
                added_bl.add(row['BL_ID'])

            covid_data.append((int(row['RS']), updated, int(row['cases']), float(row['cases7_per_100k']),
                               int(row['deaths'])))
            rs_data.append((int(row['RS']), self.clean_district_name(row['county']) + " (" + row['BEZ'] + ")",
                            row['BEZ'], int(row['BL_ID'])))

        with self.connection.cursor(dictionary=True) as cursor:
            cursor.executemany('INSERT INTO counties (rs, county_name, type, parent) VALUES (%s, %s, %s, %s) '
                               'ON DUPLICATE KEY UPDATE '
                               'type=type, parent=parent, county_name=county_name',
                               rs_data)
            cursor.executemany('''INSERT INTO covid_data (rs, date, total_cases, incidence, total_deaths)
             VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE rs=rs''', covid_data)
            # Update Bundesländer
            cursor.execute('''UPDATE covid_data
            INNER JOIN (SELECT parent, date, SUM(total_cases) as total_cases, SUM(total_deaths) as total_deaths
            FROM covid_data JOIN counties c on c.rs = covid_data.rs GROUP BY parent, date) as subquery
            SET covid_data.total_deaths = subquery.total_deaths, covid_data.total_cases = subquery.total_cases
            WHERE covid_data.date=subquery.date AND covid_data.rs=parent''')
            self.connection.commit()

    @staticmethod
    def clean_district_name(county_name: str) -> Optional[str]:
        if county_name is not None and county_name.count(" ") > 0:
            return " ".join(county_name.split(" ")[1:])
        return county_name

    def find_rs(self, search_str: str) -> List[Tuple[int, str]]:
        search_str = search_str.lower()
        search_str = search_str.replace(" ", "%")
        results = []
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT rs, county_name FROM counties WHERE LOWER(county_name) LIKE %s OR '
                           'concat(LOWER(type), LOWER(county_name)) LIKE %s',
                           ['%' + search_str + '%', '%' + search_str + '%'])
            for row in cursor.fetchall():
                if row['county_name'].lower() == search_str.replace("%", " "):
                    return [(row['rs'], row['county_name'])]
                results.append((row['rs'], row['county_name']))
        return results

    def get_rs_name(self, rs: int) -> str:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT county_name FROM counties WHERE rs=%s', [int(rs)])
            return cursor.fetchone()['county_name']

    def get_covid_data(self, rs: int) -> Optional[DistrictData]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT * FROM covid_data_calculated WHERE rs=%s ORDER BY date DESC LIMIT 2', [rs])
            current_data = cursor.fetchone()
            district = DistrictData(name=current_data['county_name'], incidence=current_data['incidence'],
                                    type=current_data['type'], total_cases=current_data['total_cases'],
                                    total_deaths=current_data['total_deaths'], new_cases=current_data['new_cases'],
                                    new_deaths=current_data['new_deaths'], date=current_data['date'])
            previous_data = cursor.fetchone()
            if previous_data:
                if not previous_data['new_cases'] or not current_data['new_cases']:
                    district.cases_trend = None
                elif previous_data['new_cases'] < current_data['new_cases']:
                    district.cases_trend = TrendValue.UP
                elif previous_data['new_cases'] > current_data['new_cases']:
                    district.cases_trend = TrendValue.DOWN
                else:
                    district.cases_trend = TrendValue.SAME

                if not previous_data['new_deaths'] or not current_data['new_deaths']:
                    district.deaths_trend = None
                elif previous_data['new_deaths'] < current_data['new_deaths']:
                    district.deaths_trend = TrendValue.UP
                elif previous_data['new_deaths'] > current_data['new_deaths']:
                    district.deaths_trend = TrendValue.DOWN
                else:
                    district.deaths_trend = TrendValue.SAME

                if not previous_data['incidence'] or not current_data['incidence']:
                    district.incidence_trend = None
                elif previous_data['incidence'] < current_data['incidence']:
                    district.incidence_trend = TrendValue.UP
                elif previous_data['incidence'] > current_data['incidence']:
                    district.incidence_trend = TrendValue.DOWN
                else:
                    district.incidence_trend = TrendValue.SAME

            return district

    def get_country_data(self) -> DistrictData:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT SUM(total_cases) as total_cases, SUM(total_deaths) as total_deaths, "
                           "SUM(new_cases) as new_cases, SUM(new_deaths) as new_deaths, DATE(date) as date "
                           "FROM covid_data_calculated "
                           "WHERE type != 'Bundesland' GROUP BY DATE(date) ORDER BY date DESC LIMIT 2")
            current_data = cursor.fetchone()
            country_data = DistrictData(name="Bundesrepublik Deutschland", date=current_data['date'])
            country_data.total_cases = current_data['total_cases']
            country_data.total_deaths = current_data['total_deaths']

            previous_data = cursor.fetchone()
            if previous_data:
                if not previous_data['new_cases'] or not current_data['new_cases']:
                    country_data.cases_trend = None
                elif previous_data['new_cases'] < current_data['new_cases']:
                    country_data.cases_trend = TrendValue.UP
                elif previous_data['new_cases'] > current_data['new_cases']:
                    country_data.cases_trend = TrendValue.DOWN
                else:
                    country_data.cases_trend = TrendValue.SAME

                if not previous_data['new_deaths'] or not current_data['new_deaths']:
                    country_data.deaths_trend = None
                elif previous_data['new_deaths'] < current_data['new_deaths']:
                    country_data.deaths_trend = TrendValue.UP
                elif previous_data['new_deaths'] > current_data['new_deaths']:
                    country_data.deaths_trend = TrendValue.DOWN
                else:
                    country_data.deaths_trend = TrendValue.SAME

                if not previous_data['incidence'] or not current_data['incidence']:
                    country_data.incidence_trend = None
                elif previous_data['incidence'] < current_data['incidence']:
                    country_data.incidence_trend = TrendValue.UP
                elif previous_data['incidence'] > current_data['incidence']:
                    country_data.incidence_trend = TrendValue.DOWN
                else:
                    country_data.incidence_trend = TrendValue.SAME

        return country_data

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT MAX(date) as "last_updated" FROM covid_data_calculated')
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
