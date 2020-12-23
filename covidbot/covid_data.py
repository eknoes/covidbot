import codecs
import csv
import logging
import os
from datetime import datetime
from typing import Tuple, List, Dict

import requests


class CovidData(object):
    RKI_LK_CSV = "https://opendata.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0.csv"

    _data: Dict[str, Dict[str, str]]
    _last_update: datetime
    log = logging.getLogger(__name__)

    def __init__(self, filename: str = None) -> None:
        self._data = dict()
        self._last_update = datetime(2020, 1, 1)
        if filename is None or not os.path.isfile(filename):
            self.log.debug("No data file provided, fetching current data...")
            self.fetch_current_data()
        else:
            with open(filename, "r") as rki_csv:
                self.log.debug("Reading from Data file")
                reader = csv.DictReader(rki_csv)
                self._init_data(reader)

    def _init_data(self, reader: csv.DictReader) -> None:
        self._data = {}
        self.log.debug("Initializing data")
        for row in reader:
            updated = datetime.strptime(row['last_update'], "%d.%m.%Y, %H:%M Uhr")
            if self._last_update is None or self._last_update < updated:
                self._last_update = updated

            self._data[row['RS']] = {'name': row['county'], 'nice_name': row['GEN'],
                                     '7day': row['cases7_per_100k_txt']}

            # Gather Bundesland data
            if row['BL_ID'] not in self._data:
                self._data[row['BL_ID']] = {'name': row['BL'], 'nice_name': row['BL'],
                                            '7day': "{0:.2f}".format(float(row['cases7_bl_per_100k'])).replace("."
                                                                                                               ",")}

    def find_rs(self, search_str: str) -> List[Tuple[str, str]]:
        search_str = search_str.lower()
        results = []
        for key, value in self._data.items():
            if value['name'].lower() == search_str:
                return [(key, value['name'])]

            if value['name'].lower().find(search_str) >= 0 or value['nice_name'].lower().find(search_str) >= 0:
                results.append((key, value['name']))
        return results

    def get_rs_name(self, rs: str) -> str:
        if rs in self._data:
            return self._data[rs]['name']
        return rs

    def get_7day_incidence(self, rs: str) -> str:
        return self._data.get(rs)['7day']

    def get_last_update(self) -> datetime:
        return self._last_update

    def fetch_current_data(self) -> bool:
        self.log.info("Start Updating data")
        # TODO: Provide If-Not-Modified since
        header = {"If-Modified-Since": self._last_update.strftime('%a, %d %b %Y %H:%M:%S GMT')}
        r = requests.get(self.RKI_LK_CSV, headers=header)
        if r.status_code == 200:
            old_update = self._last_update
            rki_data = codecs.decode(r.content, "utf-8").splitlines()
            reader = csv.DictReader(rki_data)
            self._init_data(reader)
            if old_update < self._last_update:
                return True
        elif r.status_code == 304:
            self.log.info("RKI has no new data")
        else:
            self.log.warning("RKI CSV Response Status Code is " + str(r.status_code))
        return False
