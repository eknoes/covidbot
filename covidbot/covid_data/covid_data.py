import logging
from datetime import date
from typing import Tuple, List, Optional, Union

from mysql.connector import MySQLConnection

from covidbot.covid_data.models import TrendValue, District, VaccinationData, RValueData, DistrictData


class CovidData(object):
    connection: MySQLConnection
    log = logging.getLogger(__name__)

    def __init__(self, connection: MySQLConnection) -> None:
        self.connection = connection
        self._create_tables()

    def _create_tables(self):
        self.log.debug("Creating Tables")
        with self.connection.cursor(dictionary=False) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS counties '
                           '(rs INTEGER PRIMARY KEY, county_name VARCHAR(255), type VARCHAR(30),'
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
                           'district_id INTEGER, updated DATETIME, vaccinated_partial INTEGER, '
                           'vaccinated_full INTEGER, rate_full FLOAT, rate_partial FLOAT, '
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id, updated))')

            # R Value Data
            cursor.execute('CREATE TABLE IF NOT EXISTS covid_r_value (id INTEGER PRIMARY KEY AUTO_INCREMENT, '
                           'district_id INTEGER, r_date DATE, 7day_r_value FLOAT, updated DATETIME,'
                           'FOREIGN KEY(district_id) REFERENCES counties(rs), UNIQUE(district_id, r_date))')

            # Check if view exists
            cursor.execute("SHOW FULL TABLES WHERE TABLE_TYPE LIKE '%VIEW%';")
            exists = False
            for row in cursor.fetchall():
                if row[0] == "covid_data_calculated":
                    exists = True

            if not exists:
                self.log.info("View covid_data_calculated does not exist, creating it!")
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
            self.connection.commit()
            self.log.debug("Committed Tables")

    @staticmethod
    def clean_district_name(county_name: str) -> Optional[str]:
        if county_name is not None and county_name.count(" ") > 0:
            return " ".join(county_name.split(" ")[1:])
        return county_name

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

    def get_district_data(self, district_id: int, include_past_days=0, subtract_days=0) \
            -> Optional[Union[DistrictData, List[DistrictData]]]:
        """
        Fetches the Covid19 data for a certain district for today.
        :param district_id: ID of the district
        :param include_past_days: Provide history data. If > 0 will return List[DistrictData] with len = today + past_days
        :param subtract_days: Do not fetch for today, but for today - subtract_days
        :return: DistrictData or List[DistrictData]
        """
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT * FROM covid_data_calculated WHERE rs=%s ORDER BY date DESC LIMIT %s,%s',
                           [district_id, subtract_days, include_past_days + 2])

            results = []
            for record in cursor.fetchall():
                # Check if vaccination data is available
                vacc_data = None
                if include_past_days == 0:
                    cursor.execute('SELECT vaccinated_full, vaccinated_partial, rate_full, rate_partial, '
                                   'DATE(updated) as updated '
                                   'FROM covid_vaccinations WHERE district_id=%s and DATE(updated)<=%s '
                                   'ORDER BY updated DESC LIMIT 1',
                                   [district_id, record['date']])
                    vacc = cursor.fetchone()
                    if vacc:
                        vacc_data = VaccinationData(vacc['vaccinated_full'], vacc['vaccinated_partial'],
                                                    vacc['rate_full'], vacc['rate_partial'], vacc['updated'])

                results.append(DistrictData(name=record['county_name'], incidence=record['incidence'],
                                            parent=record['parent'], type=record['type'],
                                            total_cases=record['total_cases'], total_deaths=record['total_deaths'],
                                            new_cases=record['new_cases'], new_deaths=record['new_deaths'],
                                            date=record['date'], vaccinations=vacc_data))

            # Add R-Value, which is usually just available for day -4, so we have to work with LIMIT $offset
            # (see https://www.rki.de/DE/Content/InfAZ/N/Neuartiges_Coronavirus/Projekte_RKI/R-Wert-Erlaeuterung.pdf?__blob=publicationFile)
            if district_id == 0 and subtract_days == 0 and include_past_days == 0:
                for i in range(0, len(results)):
                    cursor.execute('SELECT r_date, `7day_r_value` FROM covid_r_value WHERE district_id=%s '
                                   'ORDER BY r_date DESC LIMIT %s,1', [district_id, i])
                    data = cursor.fetchone()
                    if data:
                        r_data = RValueData(data['r_date'], data['7day_r_value'])
                        results[i].r_value = r_data

            # Add Trend in comparison to last week
            if len(results) >= 8:
                for i in range(len(results) - 7):
                    results[i] = self.fill_trend(results[i], results[i + 7], results[i + 1])
            elif results:
                cursor.execute('SELECT * FROM covid_data_calculated WHERE rs=%s AND date=SUBDATE(Date(%s), 7) LIMIT 1',
                               [district_id, results[0].date])
                record = cursor.fetchone()
                last_week, yesterday = None, None
                if record:
                    last_week = DistrictData(name=record['county_name'], incidence=record['incidence'],
                                             type=record['type'], total_cases=record['total_cases'],
                                             total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                             new_deaths=record['new_deaths'], date=record['date'])

                if len(results) == 1:
                    cursor.execute('SELECT * FROM covid_data_calculated WHERE rs=%s AND date=SUBDATE(Date(%s), 1) '
                                   'LIMIT 1', [district_id, results[0].date])
                    record = cursor.fetchone()
                    if record:
                        yesterday = DistrictData(name=record['county_name'], incidence=record['incidence'],
                                                 type=record['type'], total_cases=record['total_cases'],
                                                 total_deaths=record['total_deaths'], new_cases=record['new_cases'],
                                                 new_deaths=record['new_deaths'], date=record['date'])
                else:
                    yesterday = results[1]

                if not last_week and yesterday:
                    last_week = yesterday

                if last_week:
                    results[0] = self.fill_trend(results[0], last_week, yesterday)

            if len(results) < include_past_days + 1:
                logging.warning(
                    f"No more data available for District#{district_id}, requested {include_past_days + 1} days "
                    f"but can just provide {len(results)} days")
            elif len(results) == include_past_days + 2:
                results.pop()

            if not results:
                return None
            elif include_past_days == 0:
                return results[0]

            return results

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
