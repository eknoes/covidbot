import logging
from datetime import datetime, date
from typing import Optional, Dict

import ujson as json

from covidbot.covid_data.updater.utils import clean_district_name
from covidbot.covid_data.updater.updater import Updater


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