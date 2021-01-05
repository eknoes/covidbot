import codecs
import csv
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple, List, Union, Optional

import psycopg2
import requests
from psycopg2._psycopg import connection
from psycopg2.extras import DictCursor


@dataclass
class DistrictData:
    name: str
    type: Union[str, None] = None
    incidence: Union[float, None] = None
    new_cases: Union[int, None] = None
    new_deaths: Union[int, None] = None
    total_cases: Union[int, None] = None
    total_deaths: Union[int, None] = None


class CovidData(object):
    RKI_LK_CSV = "https://opendata.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0.csv"
    DIVI_INTENSIVREGISTER_CSV = "https://opendata.arcgis.com/datasets/8fc79b6cf7054b1b80385bda619f39b8_0.csv"

    _connection: connection
    log = logging.getLogger(__name__)

    def __init__(self, db_user: str, db_password: str, db_name: str, db_port: int = 5432) -> None:
        self._connection = psycopg2.connect(dbname=db_name, user=db_user, password=db_password, port=db_port,
                                            host='localhost', cursor_factory=DictCursor)
        self._create_tables()
        self.fetch_current_data()

    def _create_tables(self):
        with self._connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('CREATE TABLE IF NOT EXISTS counties '
                               '(rs INTEGER PRIMARY KEY, name TEXT, type VARCHAR(30), parent INTEGER,'
                               'FOREIGN KEY(parent) REFERENCES counties(rs) ON DELETE NO ACTION, UNIQUE(rs, name))')
                cursor.execute('''CREATE TABLE IF NOT EXISTS covid_data (id SERIAL, rs INTEGER, date TIMESTAMP,
                 total_cases INT, incidence FLOAT, total_deaths INT,
                 FOREIGN KEY(rs) REFERENCES counties(rs), UNIQUE(rs, date))''')

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
                if updated == last_update:
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

        with self._connection as conn:
            with conn.cursor() as cursor:
                cursor.executemany('INSERT INTO counties (rs, name, type, parent) VALUES (%s, %s, %s, %s) '
                                   'ON CONFLICT(rs) DO UPDATE '
                                   'SET type=EXCLUDED.type, parent=EXCLUDED.parent, name=EXCLUDED.name',
                                   rs_data)
                cursor.executemany('''INSERT INTO covid_data (rs, date, total_cases, incidence, total_deaths)
                 VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING''', covid_data)
                # Update Bundesländer
                cursor.execute('''UPDATE covid_data 
                SET total_deaths = subquery.total_deaths, total_cases = subquery.total_cases 
                FROM (SELECT parent, date, SUM(total_cases) as total_cases, SUM(total_deaths) as total_deaths
                FROM covid_data JOIN counties c on c.rs = covid_data.rs GROUP BY parent, date) as subquery
                WHERE covid_data.date=subquery.date AND rs=parent''')

    @staticmethod
    def clean_district_name(name: str) -> Optional[str]:
        if name is not None and name.count(" ") > 0:
            return " ".join(name.split(" ")[1:])
        return name

    def find_rs(self, search_str: str) -> List[Tuple[int, str]]:
        search_str = search_str.lower()
        results = []
        with self._connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT rs, name FROM counties WHERE LOWER(name) LIKE %s', ['%' + search_str + '%'])
                for row in cursor.fetchall():
                    if row['name'].lower() == search_str:
                        return [(row['rs'], row['name'])]

                    if row['name'].lower().find(search_str) >= 0:
                        results.append((row['rs'], row['name']))
        return results

    def get_rs_name(self, rs: int) -> str:
        with self._connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT name FROM counties WHERE rs=%s', [int(rs)])
                return cursor.fetchone()['name']

    def get_covid_data(self, rs: int) -> Optional[DistrictData]:
        with self._connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT total_cases, total_deaths, incidence, name, type '
                               'FROM covid_data JOIN counties c on c.rs = covid_data.rs WHERE covid_data.rs=%s '
                               'ORDER BY date DESC LIMIT 2', [rs])
                d = cursor.fetchone()
                current_data = DistrictData(name=d['name'], incidence=d['incidence'], type=d['type'],
                                            total_cases=d['total_cases'],
                                            total_deaths=d['total_deaths'], new_cases=None, new_deaths=None)
                data_yesterday = cursor.fetchone()
                if data_yesterday is not None:
                    current_data.new_cases = current_data.total_cases - data_yesterday['total_cases']
                    current_data.new_deaths = current_data.total_deaths - data_yesterday['total_deaths']

                return current_data

    def get_country_data(self) -> DistrictData:
        country_data = DistrictData(name="Bundesrepublik Deutschland")
        with self._connection as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT SUM(total_cases) as total_cases, SUM(total_deaths) as total_deaths, date "
                               "FROM covid_data JOIN counties c on c.rs = covid_data.rs "
                               "WHERE c.type != 'Bundesland' GROUP BY date ORDER BY date DESC LIMIT 2")
                data = cursor.fetchone()
                country_data.total_cases = data['total_cases']
                country_data.total_deaths = data['total_deaths']

                data_yesterday = cursor.fetchone()
                if data_yesterday is not None:
                    country_data.new_cases = country_data.total_cases - data_yesterday['total_cases']
                    country_data.new_deaths = country_data.total_deaths - data_yesterday['total_deaths']

        return country_data

    def get_last_update(self) -> Union[datetime, None]:
        with self._connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT MAX(date) as "last_updated [timestamp]" FROM covid_data')
                return cursor.fetchone()[0]

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
