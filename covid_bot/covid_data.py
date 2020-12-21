import csv
from typing import Tuple, List


class CovidData(object):

    def __init__(self, filename: str) -> None:
        self.data = dict()
        with open(filename, "r") as rki_csv:
            reader = csv.DictReader(rki_csv)
            for row in reader:
                self.data[row['AGS']] = {'name': row['county'], 'nice_name': row['GEN'], 'prefix': row['BEZ'],
                                         '7day': row['cases7_per_100k_txt']}

    def find_ags(self, search_str: str) -> List[Tuple[str, str]]:
        search_str = search_str.lower()
        results = []
        for key, value in self.data.items():
            if value['name'].lower() == search_str:
                return [(key, value['name'])]

            if value['name'].lower().find(search_str) >= 0 or value['nice_name'].lower().find(search_str) >= 0:
                results.append((key, value['name']))
        return results

    def get_7day_incidence(self, ags: str) -> str:
        return self.data.get(ags)['7day']
