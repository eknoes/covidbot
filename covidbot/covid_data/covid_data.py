import logging
import math
from datetime import date, timedelta, datetime
from typing import List, Optional, Dict, Union

from mysql.connector import MySQLConnection

from covidbot.covid_data.WorkingDayChecker import WorkingDayChecker
from covidbot.covid_data.models import District, VaccinationData, RValueData, DistrictData, ICUData, \
    RuleData, IncidenceIntervalData, DistrictFacts
from covidbot.metrics import LOCATION_DB_LOOKUP
from covidbot.utils import get_trend


class CovidData(object):
    connection: MySQLConnection
    log = logging.getLogger(__name__)
    working_day_checker = WorkingDayChecker()

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
                cursor.execute('SELECT district_id, c.county_name, alt_name FROM county_alt_names '
                               'LEFT JOIN counties c on c.rs = county_alt_names.district_id '
                               'WHERE LOWER(alt_name) LIKE %s', [query_str])
                for row in cursor.fetchall():
                    if row['alt_name'].lower() == search_str:
                        exact_matches.append(District(row['county_name'], row['district_id']))
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

    def get_district_facts(self, district_id: int) -> Optional[DistrictFacts]:
        with self.connection.cursor() as cursor:
            cursor.execute('''SELECT 'cases', new_cases, date FROM covid_data_calculated WHERE rs=%s AND new_cases = (SELECT MAX(new_cases) FROM covid_data_calculated WHERE rs=%s)
UNION
SELECT 'deaths', new_deaths, date FROM covid_data_calculated WHERE rs=%s AND new_deaths = (SELECT MAX(new_deaths) FROM covid_data_calculated WHERE rs=%s)
UNION
SELECT 'incidence', incidence, date FROM covid_data_calculated WHERE rs=%s AND incidence = (SELECT MAX(incidence) FROM covid_data_calculated WHERE rs=%s)
UNION 
(SELECT 'first-death', total_deaths, date FROM covid_data WHERE rs=%s AND total_deaths > 0 ORDER BY date LIMIT 1)
UNION 
(SELECT 'first-case', total_cases, date FROM covid_data WHERE rs=%s AND total_cases > 0 ORDER BY date LIMIT 1)
''',
                           [district_id] * 8)
            facts = DistrictFacts()
            for record in cursor.fetchall():
                if record[0] == 'cases':
                    facts.highest_cases = int(record[1])
                    facts.highest_cases_date = record[2]
                elif record[0] == 'deaths':
                    facts.highest_deaths = int(record[1])
                    facts.highest_deaths_date = record[2]
                elif record[0] == 'incidence':
                    facts.highest_incidence = record[1]
                    facts.highest_incidence_date = record[2]
                elif record[0] == 'first-death':
                    facts.first_death_date = record[2]
                elif record[0] == 'first-case':
                    facts.first_case_date = record[2]
            return facts

    def get_district_data(self, district_id: int) \
            -> Optional[DistrictData]:
        """
        Fetches the Covid19 data for a certain district for today.
        :param district_id: ID of the district
        :return: DistrictData
        """
        result = self.get_base_data(district_id)

        if not result:
            return None

        result.vaccinations = self.get_vaccination_data(district_id)
        result.icu_data = self.get_icu_data(district_id)
        result.r_value = self.get_r_value_data(district_id)
        result.rules = self.get_rules_data(district_id)
        return result

    def get_base_data(self, district_id: int) -> Optional[DistrictData]:
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

            # Get data for trends
            cursor.execute(
                'SELECT * FROM covid_data_calculated WHERE rs=%s AND (date=SUBDATE(Date(%s), 7) OR date=SUBDATE(Date(%s), 1)) LIMIT 2',
                [district_id, result.date, result.date])

            for record in cursor.fetchall():
                comparison_data = DistrictData(name=record['county_name'], id=district_id,
                                               incidence=record['incidence'],
                                               type=record['type'], total_cases=record['total_cases'],
                                               total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                               new_deaths=record['new_deaths'], date=record['date'])
                if result.date - comparison_data.date == timedelta(days=1):
                    result.incidence_trend = get_trend(comparison_data.incidence, result.incidence)
                else:
                    result.cases_trend = get_trend(comparison_data.new_cases, result.new_cases)
                    result.deaths_trend = get_trend(comparison_data.new_deaths, result.new_deaths)

            cursor.execute(
                'SELECT alt_name FROM county_alt_names WHERE alt_name LIKE \'DE-%\' AND (district_id=%s OR district_id=(SELECT parent FROM counties WHERE rs=%s)) LIMIT 1',
                [district_id, district_id])
            state_name = None
            record = cursor.fetchone()
            if record:
                state_name = record['alt_name']
                state_name = state_name.split("-")[1]

            # Check, how long incidence is in certain interval
            threshold_values = [35, 50, 100, 150, 165, 200]
            interval_data = IncidenceIntervalData()

            # Get lower threshold
            for i in range(len(threshold_values) - 1, 0, -1):
                if threshold_values[i] < result.incidence:
                    interval_data.lower_threshold = threshold_values[i]
                    break

            if interval_data.lower_threshold:
                cursor.execute('SELECT date FROM covid_data WHERE incidence < %s AND rs=%s ORDER BY date DESC LIMIT 1',
                               [interval_data.lower_threshold, district_id])
                record = cursor.fetchone()
                if record:
                    lower_date = record['date']
                    interval_data.lower_threshold_days = 0
                    interval_data.lower_threshold_working_days = 0
                    while lower_date < date.today():
                        interval_data.lower_threshold_days += 1
                        if not self.working_day_checker.check_holiday(lower_date, state_name):
                            interval_data.lower_threshold_working_days += 1
                        lower_date += timedelta(days=1)

            # Get upper threshold
            for val in threshold_values:
                if result.incidence < val:
                    interval_data.upper_threshold = val
                    break

            if interval_data.upper_threshold:
                cursor.execute('SELECT date FROM covid_data WHERE incidence > %s AND rs=%s ORDER BY date DESC LIMIT 1',
                               [interval_data.upper_threshold, district_id])
                record = cursor.fetchone()
                if record:
                    upper_date = record['date']
                    interval_data.upper_threshold_days = 0
                    interval_data.upper_threshold_working_days = 0
                    while upper_date < date.today():
                        interval_data.upper_threshold_days += 1
                        if not self.working_day_checker.check_holiday(upper_date, state_name):
                            interval_data.upper_threshold_working_days += 1
                        upper_date += timedelta(days=1)

            result.incidence_interval_data = interval_data

            return result

    def get_vaccination_data(self, district_id: int) -> Optional[VaccinationData]:
        with self.connection.cursor(dictionary=True) as cursor:
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

                    return vaccination_data

    def get_icu_data(self, district_id: int) -> Optional[ICUData]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT date, clear, occupied, occupied_covid, covid_ventilated, updated FROM icu_beds '
                           'WHERE district_id=%s ORDER BY date DESC LIMIT 1', [district_id])
            row = cursor.fetchone()
            if row:
                result = ICUData(date=row['date'], clear_beds=row['clear'], occupied_beds=row['occupied'],
                                 occupied_covid=row['occupied_covid'],
                                 covid_ventilated=row['covid_ventilated'], last_update=row['updated'])

                cursor.execute('SELECT occupied, occupied_covid FROM icu_beds '
                               'WHERE district_id=%s AND date=SUBDATE(%s, 7) LIMIT 1',
                               [district_id, result.date])
                row = cursor.fetchone()
                if row:
                    result.occupied_beds_trend = get_trend(row['occupied'], result.occupied_beds)
                    result.occupied_covid_trend = get_trend(row['occupied_covid'], result.occupied_covid)

                return result

    def get_r_value_data(self, district_id: int) -> Optional[RValueData]:
        if district_id != 0:
            return None

        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT r_date, `7day_r_value` FROM covid_r_value WHERE district_id=%s '
                           'ORDER BY r_date DESC LIMIT 1', [district_id])
            data = cursor.fetchone()
            if not data:
                return None

            r_data = RValueData(data['r_date'], data['7day_r_value'])
            cursor.execute('SELECT `7day_r_value`, r_date FROM covid_r_value WHERE district_id=%s '
                           'AND r_date=SUBDATE(%s, 1) LIMIT 1', [district_id, r_data.date])
            row = cursor.fetchone()
            if row:
                r_data.r_trend = get_trend(row['7day_r_value'], r_data.r_value_7day)

            return r_data

    def get_rules_data(self, district_id: int) -> Optional[RuleData]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT text, link, updated FROM district_rules WHERE district_id=%s', [district_id])
            data = cursor.fetchone()
            if data:
                return RuleData(data['updated'], data['text'], data['link'])

    def get_country_data(self) -> DistrictData:
        return self.get_district_data(0)

    def get_icu_general_info(self) -> Dict:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT MAX(date) as current FROM icu_beds')
            current_date = cursor.fetchone()['current']

            result = {'full': None, 'close2full': None}
            # TODO: Use districts table to identify non-aggregated values
            cursor.execute('SELECT COUNT(*) as num_full FROM icu_beds WHERE date=%s AND clear=0 AND district_id > 16',
                           [current_date])
            record = cursor.fetchone()
            if record:
                result['full'] = record['num_full']

            cursor.execute(
                'SELECT COUNT(*) as num_close FROM icu_beds WHERE date=%s AND (occupied / (clear + occupied)) > 0.9 AND district_id > 16',
                [current_date])
            record = cursor.fetchone()
            if record:
                result['close2full'] = record['num_close']

            return result

    def get_last_update_cases(self) -> Optional[datetime]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT last_update FROM covid_data WHERE date=(SELECT MAX(date) FROM covid_data) LIMIT 1')
            result = cursor.fetchone()
            return result['last_update']

    def get_last_update_vaccination(self) -> Optional[datetime]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT last_update FROM covid_vaccinations WHERE date=(SELECT MAX(date) FROM covid_vaccinations) LIMIT 1')
            result = cursor.fetchone()
            return result['last_update']

    def get_last_update_icu(self) -> Optional[datetime]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT updated FROM icu_beds WHERE date=(SELECT MAX(date) FROM icu_beds) LIMIT 1')
            result = cursor.fetchone()
            return result['updated']


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
                           "VALUES (5, 'NRW'), (8, 'BaWü'), (7, 'RLP'), (1, 'DE-SH'), (2, 'DE-HH'), (3, 'DE-NI'), (4, 'DE-HB'), (5, 'DE-NW'), (6, 'DE-HE'), (7, 'DE-RP'), (8, 'DE-BW'), (9, 'DE-BY'), (10, 'DE-SL'), (11, 'DE-BE'), (12, 'DE-BB'), (13, 'DE-MV'), (14, 'DE-SN'), (15, 'DE-ST'), (16, 'DE-TH'), (1, 'SH'), (2, 'HH'), (3, 'NI'), (4, 'HB'), (5, 'NW'), (6, 'HE'), (7, 'RP'), (8, 'BW'), (9, 'BY'), (10, 'SL'), (11, 'BE'), (12, 'BB'), (13, 'MV'), (14, 'SN'), (15, 'ST'), (16, 'TH')")

            connection.commit()
            log.debug("Committed Tables")
