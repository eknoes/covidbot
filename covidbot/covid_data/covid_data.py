import logging
from datetime import date, timedelta
from typing import Tuple, List, Optional

from mysql.connector import MySQLConnection

from covidbot.covid_data.models import TrendValue, District, VaccinationData, RValueData, DistrictData, ICUData, \
    RuleData
from covidbot.metrics import LOCATION_DB_LOOKUP


class CovidData(object):
    connection: MySQLConnection
    log = logging.getLogger(__name__)

    def __init__(self, connection: MySQLConnection) -> None:
        self.connection = connection
        CovidDatabaseCreator(self.connection)

    @LOCATION_DB_LOOKUP.time()
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

    def get_district(self, district_id: int) -> District:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT county_name, type, parent FROM counties WHERE rs=%s', [int(district_id)])
            data = cursor.fetchone()
            return District(data['county_name'], type=data['type'], parent=data['parent'])

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

            result = DistrictData(name=record['county_name'], incidence=record['incidence'],
                                  parent=record['parent'], type=record['type'],
                                  total_cases=record['total_cases'], total_deaths=record['total_deaths'],
                                  new_cases=record['new_cases'], new_deaths=record['new_deaths'],
                                  date=record['date'])

            # Check if vaccination data is available
            vaccination_data = None
            cursor.execute('SELECT MAX(date) as last_update FROM covid_vaccinations WHERE district_id=%s', [district_id])
            vacc_date = cursor.fetchone()
            if vacc_date:
                last_update = vacc_date['last_update']
                cursor.execute('SELECT vaccinated_full, vaccinated_partial, rate_full, rate_partial, '
                               'date '
                               'FROM covid_vaccinations WHERE district_id=%s and date<=%s '
                               'ORDER BY date DESC LIMIT 1',
                               [district_id, last_update])
                vaccination_record = cursor.fetchone()
                if vaccination_record:
                    vaccination_data = VaccinationData(vaccination_record['vaccinated_full'],
                                                       vaccination_record['vaccinated_partial'],
                                                       vaccination_record['rate_full'], vaccination_record['rate_partial'],
                                                       vaccination_record['date'])

                    result.vaccinations = vaccination_data
            # Check if ICU data is available
            cursor.execute('SELECT date, clear, occupied, occupied_covid, covid_ventilated FROM icu_beds '
                           'WHERE district_id=%s ORDER BY date DESC LIMIT 1', [district_id])
            row = cursor.fetchone()
            if row:
                icu_data = ICUData(date=row['date'], clear_beds=row['clear'], occupied_beds=row['occupied'],
                                   occupied_covid=row['occupied_covid'], covid_ventilated=row['covid_ventilated'])
                result.icu_data = icu_data

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
                comparison_data = DistrictData(name=record['county_name'], incidence=record['incidence'],
                                               type=record['type'], total_cases=record['total_cases'],
                                               total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                               new_deaths=record['new_deaths'], date=record['date'])
                if result.date - comparison_data.date == timedelta(days=1):
                    yesterday = comparison_data
                else:
                    last_week = comparison_data

            if not last_week and yesterday:
                last_week = yesterday

            if last_week:
                result = self.fill_trend(result, last_week, yesterday)

            # Check, how long incidence is in certain interval
            possible_intervals = [35, 50, 100]
            threshold = 0
            for interval in possible_intervals:
                if result.incidence < interval:
                    threshold = interval
                    break

            if threshold:
                cursor.execute("SELECT date FROM covid_data WHERE rs=%s AND incidence >= %s ORDER BY date DESC LIMIT 1",
                               [district_id, threshold])
                threshold_record = cursor.fetchone()
                if threshold_record:
                    result.incidence_interval_since = threshold_record['date'] + timedelta(days=1)
                    result.incidence_interval_upper_value = threshold
            return result

    def get_country_data(self) -> DistrictData:
        return self.get_district_data(0)

    @staticmethod
    def fill_trend(today: DistrictData, last_week: DistrictData, yesterday: Optional[DistrictData]) -> DistrictData:
        if not yesterday:
            yesterday = last_week

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

        if yesterday:
            if not yesterday.incidence or not today.incidence:
                today.incidence_trend = None
            elif yesterday.incidence < today.incidence:
                today.incidence_trend = TrendValue.UP
            elif yesterday.incidence > today.incidence:
                today.incidence_trend = TrendValue.DOWN
            else:
                today.incidence_trend = TrendValue.SAME

            if today.r_value and yesterday.r_value:
                if yesterday.r_value.r_value_7day < today.r_value.r_value_7day:
                    today.r_value.r_trend = TrendValue.UP
                elif yesterday.r_value.r_value_7day == today.r_value.r_value_7day:
                    today.r_value.r_trend = TrendValue.SAME
                if yesterday.r_value.r_value_7day > today.r_value.r_value_7day:
                    today.r_value.r_trend = TrendValue.DOWN

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
                           '(rs INTEGER PRIMARY KEY, county_name VARCHAR(255)  CHARACTER SET utf8 COLLATE utf8_general_ci, type VARCHAR(30),'
                           'population INTEGER NULL DEFAULT NULL, parent INTEGER, '
                           'FOREIGN KEY(parent) REFERENCES counties(rs) ON DELETE NO ACTION,'
                           'UNIQUE(rs, county_name))')
            # Raw Infection Data
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS covid_data (id INTEGER PRIMARY KEY AUTO_INCREMENT, rs INTEGER, date DATE NULL DEFAULT NULL,'
                'total_cases INT, incidence FLOAT, total_deaths INT,'
                'FOREIGN KEY(rs) REFERENCES counties(rs), UNIQUE(rs, date))')

            # Vaccination Data
            cursor.execute('CREATE TABLE IF NOT EXISTS covid_vaccinations (id INTEGER PRIMARY KEY AUTO_INCREMENT, '
                           'district_id INTEGER, date DATE, vaccinated_partial INTEGER, '
                           'vaccinated_full INTEGER, rate_full FLOAT, rate_partial FLOAT, last_update DATETIME DEFAULT NOW(),'
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id, date))')

            # R Value Data
            cursor.execute('CREATE TABLE IF NOT EXISTS covid_r_value (id INTEGER PRIMARY KEY AUTO_INCREMENT, '
                           'district_id INTEGER, r_date DATE, 7day_r_value FLOAT, updated DATETIME,'
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id, r_date))')

            # Intensive care information
            cursor.execute('CREATE TABLE IF NOT EXISTS icu_beds (id INTEGER PRIMARY KEY AUTO_INCREMENT,'
                           'district_id INTEGER, date DATE, clear INTEGER, occupied INTEGER,'
                           'occupied_covid INTEGER, covid_ventilated INTEGER, updated DATETIME,'
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
                               'covid_data.incidence '
                               'FROM covid_data '
                               'LEFT JOIN covid_data y on y.rs = covid_data.rs AND '
                               'y.date = subdate(covid_data.date, 1) '
                               'LEFT JOIN counties c on c.rs = covid_data.rs '
                               'ORDER BY covid_data.date DESC')

            # Insert if not exists
            cursor.execute("INSERT IGNORE INTO counties (rs, county_name, type, parent) "
                           "VALUES (0, 'Deutschland', 'Staat', NULL)")
            connection.commit()
            log.debug("Committed Tables")
