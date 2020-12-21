import csv
from typing import Tuple, List, Dict


class CovidData(object):
    data: Dict[str, Dict[str, str]]
    last_update: str

    def __init__(self, filename: str) -> None:
        self.data = dict()
        with open(filename, "r") as rki_csv:
            reader = csv.DictReader(rki_csv)
            for row in reader:
                # TODO: Compare to have earliest data
                self.last_update = row['last_update']
                self.data[row['RS']] = {'name': row['county'], 'nice_name': row['GEN'], 'prefix': row['BEZ'],
                                         '7day': row['cases7_per_100k_txt']}

    def find_rs(self, search_str: str) -> List[Tuple[str, str]]:
        search_str = search_str.lower()
        results = []
        for key, value in self.data.items():
            if value['name'].lower() == search_str:
                return [(key, value['name'])]

            if value['name'].lower().find(search_str) >= 0 or value['nice_name'].lower().find(search_str) >= 0:
                results.append((key, value['name']))
        return results

    def get_rs_name(self, rs: str) -> str:
        if rs in self.data:
            return self.data[rs]['name']
        return rs

    def get_7day_incidence(self, rs: str) -> str:
        return self.data.get(rs)['7day']

    def get_last_update(self) -> str:
        return self.last_update
