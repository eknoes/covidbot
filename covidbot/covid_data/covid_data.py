import logging
import math
from datetime import date, timedelta
from typing import List, Optional, Dict

from mysql.connector import MySQLConnection

from covidbot.covid_data.models import TrendValue, District, VaccinationData, RValueData, DistrictData, ICUData, \
    RuleData
from covidbot.metrics import LOCATION_DB_LOOKUP
from covidbot.utils import get_trend


class CovidData(object):
    connection: MySQLConnection
    log = logging.getLogger(__name__)

    def __init__(self, connection: MySQLConnection) -> None:
        self.connection = connection
        CovidDatabaseCreator(self.connection)

    @LOCATION_DB_LOOKUP.time()
    def search_district_by_name(self, search_str: str) -> List[District]:
        search_str = search_str.lower().strip()
        query_str = '%' + search_str.replace(" ", "%") + '%'
        results = []
        with self.connection.cursor(dictionary=True) as cursor:
            if search_str.isdigit():
                cursor.execute('SELECT rs, county_name FROM counties WHERE rs = %s',
                               [int(search_str)])
            else:
                cursor.execute('SELECT rs, county_name FROM counties WHERE LOWER(county_name) LIKE %s '
                               'OR concat(LOWER(type), LOWER(county_name)) LIKE %s',
                               [query_str, query_str])

            exact_matches = []
            for row in cursor.fetchall():
                if row['county_name'].lower() == search_str:
                    return [District(row['county_name'], row['rs'])]

                if len(search_str) < len(row['county_name']) and row['county_name'][
                                                                 :len(search_str) + 1].lower() == search_str + " ":
                    exact_matches.append(District(row['county_name'], row['rs']))

                results.append(District(row['county_name'], row['rs']))

            if not search_str.isdigit():
                cursor.execute('SELECT district_id, c.county_name FROM county_alt_names '
                               'LEFT JOIN counties c on c.rs = county_alt_names.district_id '
                               'WHERE LOWER(alt_name) LIKE %s', [query_str])
                for row in cursor.fetchall():
                    results.append(District(row['county_name'], row['district_id']))

            if len(exact_matches) == 1:
                return exact_matches
        return results

    def get_district(self, district_id: int) -> District:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT county_name, type, parent FROM counties WHERE rs=%s', [int(district_id)])
            data = cursor.fetchone()
            return District(data['county_name'], id=district_id, type=data['type'], parent=data['parent'])

    def get_children_data(self, district_id: int) -> Optional[List[DistrictData]]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT rs FROM counties WHERE parent=%s', [int(district_id)])
            children = []
            for row in cursor.fetchall():
                children.append(row['rs'])
        if children:
            children_data = []
            for child in children:
                children_data.append((self.get_district_data(child)))
            return children_data

    def get_district_data(self, district_id: int) \
            -> Optional[DistrictData]:
        """
        Fetches the Covid19 data for a certain district for today.
        :param district_id: ID of the district
        :return: DistrictData
        """
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT * FROM covid_data_calculated WHERE rs=%s ORDER BY date DESC LIMIT 1',
                           [district_id])

            record = cursor.fetchone()
            if not record:
                return None

            result = DistrictData(name=record['county_name'], id=district_id, incidence=record['incidence'],
                                  parent=record['parent'], type=record['type'],
                                  total_cases=record['total_cases'], total_deaths=record['total_deaths'],
                                  new_cases=record['new_cases'], new_deaths=record['new_deaths'],
                                  date=record['date'], last_update=record['last_update'])

            # Check if vaccination data is available
            cursor.execute('SELECT MAX(date) as last_update FROM covid_vaccinations WHERE district_id=%s',
                           [district_id])
            vacc_date = cursor.fetchone()
            if vacc_date:
                last_update = vacc_date['last_update']
                cursor.execute('SELECT vaccinated_full, vaccinated_partial, rate_full, rate_partial, '
                               'date, doses_diff, last_update '
                               'FROM covid_vaccinations WHERE district_id=%s and date<=%s '
                               'ORDER BY date DESC LIMIT 1',
                               [district_id, last_update])
                vaccination_record = cursor.fetchone()
                if vaccination_record:
                    vaccination_data = VaccinationData(vaccination_record['vaccinated_full'],
                                                       vaccination_record['vaccinated_partial'],
                                                       vaccination_record['rate_full'],
                                                       vaccination_record['rate_partial'],
                                                       vaccination_record['date'],
                                                       doses_diff=vaccination_record['doses_diff'],
                                                       last_update=vaccination_record['last_update'])

                    cursor.execute(
                        'SELECT AVG(doses_diff) as avg_7day, population FROM covid_vaccinations LEFT JOIN counties c on c.rs = covid_vaccinations.district_id WHERE district_id=%s AND date > SUBDATE(%s, 7) AND doses_diff IS NOT NULL GROUP BY district_id',
                        [district_id, last_update])
                    record = cursor.fetchone()
                    if record:
                        vaccination_data.avg_speed = int(record['avg_7day'])
                        population_to_be_vaccinated = 2 * record['population'] - (
                                vaccination_data.vaccinated_full + vaccination_data.vaccinated_partial)
                        if vaccination_data.avg_speed > 0:
                            vaccination_data.avg_days_to_finish = math.ceil(
                                population_to_be_vaccinated / vaccination_data.avg_speed)

                    result.vaccinations = vaccination_data
            # Check if ICU data is available
            cursor.execute('SELECT date, clear, occupied, occupied_covid, covid_ventilated, updated FROM icu_beds '
                           'WHERE district_id=%s ORDER BY date DESC LIMIT 1', [district_id])
            row = cursor.fetchone()
            if row:
                result.icu_data = ICUData(date=row['date'], clear_beds=row['clear'], occupied_beds=row['occupied'],
                                          occupied_covid=row['occupied_covid'],
                                          covid_ventilated=row['covid_ventilated'], last_update=row['updated'])

                cursor.execute('SELECT date, clear, occupied, occupied_covid, covid_ventilated, updated FROM icu_beds '
                               'WHERE district_id=%s AND date=SUBDATE(%s, 7) LIMIT 1',
                               [district_id, result.icu_data.date])
                row_lastweek = cursor.fetchone()
                if row_lastweek:
                    icu_yesterday = ICUData(date=row_lastweek['date'], clear_beds=row_lastweek['clear'],
                                            occupied_beds=row_lastweek['occupied'],
                                            occupied_covid=row_lastweek['occupied_covid'],
                                            covid_ventilated=row_lastweek['covid_ventilated'],
                                            last_update=row['updated'])
                    result.icu_data = self.fill_trend_icu(result.icu_data, icu_yesterday)

            # Check if R-Value is available
            if district_id == 0:
                cursor.execute('SELECT r_date, `7day_r_value` FROM covid_r_value WHERE district_id=%s '
                               'ORDER BY r_date DESC LIMIT 1', [district_id])
                data = cursor.fetchone()
                if data:
                    r_data = RValueData(data['r_date'], data['7day_r_value'])
                    result.r_value = r_data

            # Check if Rules are available
            cursor.execute('SELECT text, link, updated FROM district_rules WHERE district_id=%s', [district_id])
            data = cursor.fetchone()
            if data:
                result.rules = RuleData(data['updated'], data['text'], data['link'])

            # Add Trend in comparison to yesterday and last week
            cursor.execute(
                'SELECT * FROM covid_data_calculated WHERE rs=%s AND (date=SUBDATE(Date(%s), 7) OR date=SUBDATE(Date(%s), 1)) LIMIT 2',
                [district_id, result.date, result.date])
            last_week, yesterday = None, None
            for record in cursor.fetchall():
                comparison_data = DistrictData(name=record['county_name'], id=district_id,
                                               incidence=record['incidence'],
                                               type=record['type'], total_cases=record['total_cases'],
                                               total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                               new_deaths=record['new_deaths'], date=record['date'])
                if result.date - comparison_data.date == timedelta(days=1):
                    yesterday = comparison_data
                    if result.r_value:
                        cursor.execute('SELECT `7day_r_value`, r_date FROM covid_r_value WHERE district_id=%s '
                                       'AND r_date=SUBDATE(%s, 1) LIMIT 1', [district_id, result.r_value.date])
                        row = cursor.fetchone()
                        if row:
                            yesterday.r_value = RValueData(row['r_date'], row['7day_r_value'])
                else:
                    last_week = comparison_data

            if not last_week and yesterday:
                last_week = yesterday

            if last_week:
                result = self.fill_trend(result, last_week, yesterday)

            # Check, how long incidence is in certain interval
            if result.incidence < 100:
                threshold_values = [25, 50, 100]
                threshold = 0
                while result.incidence > threshold_values[threshold] and len(threshold_values) > threshold:
                    threshold += 1
                operator = ">"
                result.incidence_interval_threshold = threshold_values[threshold]
            else:
                threshold_values = [200, 165, 150, 100]
                threshold = 0
                while result.incidence < threshold_values[threshold] and len(threshold_values) > threshold:
                    threshold += 1
                operator = "<="
                result.incidence_interval_threshold = threshold_values[threshold]

            cursor.execute(f'SELECT date FROM covid_data_calculated WHERE rs=%s AND incidence {operator} %s '
                           f'ORDER BY date DESC LIMIT 1', [district_id, result.incidence_interval_threshold])
            rows = cursor.fetchall()
            if rows:
                result.incidence_interval_since = rows[0]['date']

            return result

    def get_country_data(self) -> DistrictData:
        return self.get_district_data(0)

    def get_icu_general_info(self) -> Dict:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT MAX(date) as current FROM icu_beds')
            current_date = cursor.fetchone()['current']

            result = {'full': None, 'close2full': None}
            # TODO: Use districts table to identify non-aggregated values
            cursor.execute('SELECT COUNT(*) as num_full FROM icu_beds WHERE date=%s AND clear=0 AND district_id > 16', [current_date])
            record = cursor.fetchone()
            if record:
                result['full'] = record['num_full']

            cursor.execute('SELECT COUNT(*) as num_close FROM icu_beds WHERE date=%s AND (occupied / (clear + occupied)) > 0.9 AND district_id > 16', [current_date])
            record = cursor.fetchone()
            if record:
                result['close2full'] = record['num_close']

            return result
    @staticmethod
    def fill_trend(today: DistrictData, last_week: DistrictData, yesterday: Optional[DistrictData]) -> DistrictData:
        if not yesterday:
            yesterday = last_week

        if last_week:
            today.cases_trend = get_trend(last_week.new_cases, today.new_cases)
            today.deaths_trend = get_trend(last_week.new_deaths, today.new_deaths)

        if yesterday:
            today.incidence_trend = get_trend(yesterday.incidence, today.incidence)

            if today.r_value and yesterday.r_value:
                today.r_value.r_trend = get_trend(yesterday.r_value.r_value_7day, today.r_value.r_value_7day)

        return today

    @staticmethod
    def fill_trend_icu(today: ICUData, yesterday: ICUData) -> ICUData:
        if not yesterday:
            return today

        today.occupied_beds_trend = get_trend(yesterday.occupied_beds, today.occupied_beds)
        today.occupied_beds_trend = get_trend(yesterday.occupied_covid, today.occupied_covid)

        return today

    def get_last_update(self) -> Optional[date]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT MAX(date) as "last_updated" FROM covid_data')
            result = cursor.fetchone()
            return result['last_updated']


class CovidDatabaseCreator:
    def __init__(self, connection: MySQLConnection):
        log = logging.getLogger(str(self.__class__))
        log.debug("Creating Tables")
        with connection.cursor(dictionary=False) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS counties '
                           '(rs INTEGER PRIMARY KEY, county_name VARCHAR(255), type VARCHAR(30),'
                           'population INTEGER NULL DEFAULT NULL, parent INTEGER, '
                           'FOREIGN KEY(parent) REFERENCES counties(rs) ON DELETE NO ACTION,'
                           'UNIQUE(rs, county_name))')

            cursor.execute('CREATE TABLE IF NOT EXISTS county_alt_names '
                           '(district_id INTEGER, alt_name VARCHAR(255) PRIMARY KEY, '
                           'added DATETIME DEFAULT NOW(), delete_at DATETIME DEFAULT ADDDATE(NOW(), INTERVAL 14 DAY), '
                           'FOREIGN KEY(district_id) REFERENCES counties(rs) ON DELETE NO ACTION)')

            # Raw Infection Data
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS covid_data (id INTEGER PRIMARY KEY AUTO_INCREMENT, rs INTEGER, date DATE NULL DEFAULT NULL,'
                'total_cases INT, incidence FLOAT, total_deaths INT, last_update DATETIME DEFAULT NOW(), '
                'FOREIGN KEY(rs) REFERENCES counties(rs), UNIQUE(rs, date))')

            # Vaccination Data
            cursor.execute('CREATE TABLE IF NOT EXISTS covid_vaccinations (id INTEGER PRIMARY KEY AUTO_INCREMENT, '
                           'district_id INTEGER, date DATE, vaccinated_partial INTEGER, doses_diff INTEGER, '
                           'vaccinated_full INTEGER, rate_full FLOAT, rate_partial FLOAT, last_update DATETIME DEFAULT NOW(),'
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id, date))')

            # R Value Data
            cursor.execute('CREATE TABLE IF NOT EXISTS covid_r_value (id INTEGER PRIMARY KEY AUTO_INCREMENT, '
                           'district_id INTEGER, r_date DATE, 7day_r_value FLOAT, updated DATETIME,'
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id, r_date))')

            # Intensive care information
            cursor.execute('CREATE TABLE IF NOT EXISTS icu_beds (id INTEGER PRIMARY KEY AUTO_INCREMENT,'
                           'district_id INTEGER, date DATE, clear INTEGER, occupied INTEGER,'
                           'occupied_covid INTEGER, covid_ventilated INTEGER, updated DATETIME DEFAULT NOW(),'
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id, date))')

            # Rule Data
            cursor.execute('CREATE TABLE IF NOT EXISTS district_rules (id INTEGER PRIMARY KEY AUTO_INCREMENT,'
                           'district_id INTEGER, text TEXT CHARACTER SET utf8 COLLATE utf8_general_ci, link VARCHAR(255), updated DATETIME,'
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id))')

            # Check if view exists
            cursor.execute("SHOW FULL TABLES WHERE TABLE_TYPE LIKE '%VIEW%';")
            exists = False
            for row in cursor.fetchall():
                if row[0] == "covid_data_calculated":
                    exists = True

            if not exists:
                log.info("View covid_data_calculated does not exist, creating it!")
                cursor.execute('CREATE VIEW covid_data_calculated AS '
                               'SELECT c.rs, c.county_name, c.type, c.parent, covid_data.date, '
                               'covid_data.total_cases, covid_data.total_cases - y.total_cases as new_cases, '
                               'covid_data.total_deaths, covid_data.total_deaths - y.total_deaths as new_deaths, '
                               'covid_data.incidence, covid_data.last_update '
                               'FROM covid_data '
                               'LEFT JOIN covid_data y on y.rs = covid_data.rs AND '
                               'y.date = subdate(covid_data.date, 1) '
                               'LEFT JOIN counties c on c.rs = covid_data.rs '
                               'ORDER BY covid_data.date DESC')

            # Insert if not exists
            cursor.execute("INSERT IGNORE INTO counties (rs, county_name, type, parent) "
                           "VALUES (0, 'Deutschland', 'Staat', NULL)")

            # Insert common abbreviations
            cursor.execute("INSERT IGNORE INTO county_alt_names (district_id, alt_name) "
                           "VALUES (5, 'NRW'), (8, 'BaWü'), (7, 'RLP'), (1, 'DE-SH'), (2, 'DE-HH'), (3, 'DE-NI'), (4, 'DE-HB'), (5, 'DE-NW'), (6, 'DE-HE'), (7, 'DE-RP'), (8, 'DE-BW'), (9, 'DE-BY'), (10, 'DE-SL'), (11, 'DE-BE'), (12, 'DE-BB'), (13, 'DE-MV'), (14, 'DE-SN'), (15, 'DE-ST'), (16, 'DE-TH')")

            connection.commit()
            log.debug("Committed Tables")
