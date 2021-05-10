import logging
import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import requests
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

            cursor.execute('SELECT district_id, alt_name FROM county_alt_names WHERE alt_name LIKE %s', [f'%{district_name}%'])
            rows = cursor.fetchall()
            if rows:
                if len(rows) == 1:
                    return rows[0][0]

                for row in rows:
                    if row[1] == district_name:
                        return row[0]