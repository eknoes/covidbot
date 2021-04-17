import csv
import logging
import re
from datetime import datetime, timedelta, date
from typing import Optional

from covidbot.covid_data.updater.updater import Updater


class ICUGermanyUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://diviexchange.blob.core.windows.net/%24web/DIVI_Intensivregister_Auszug_pro_Landkreis.csv"

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MAX(updated) FROM icu_beds")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()

        if last_update and datetime.now() - last_update < timedelta(hours=12):
            return False

        response = self.get_resource(self.URL)
        if response:
            self.log.debug("Got ICU Data from DIVI")
            divi_data = response.splitlines()
            reader = csv.DictReader(divi_data)
            results = []
            for row in reader:
                # Berlin is here AGS = 11000
                if row['gemeindeschluessel'] == '11000':
                    row['gemeindeschluessel'] = '11'
                results.append((row['gemeindeschluessel'], row['daten_stand'], row['betten_frei'], row['betten_belegt'],
                                row['faelle_covid_aktuell'], row['faelle_covid_aktuell_invasiv_beatmet'],
                                row['daten_stand']))

            with self.connection.cursor() as cursor:
                for row in results:
                    cursor.execute("INSERT IGNORE INTO icu_beds (district_id, date, clear, occupied, occupied_covid,"
                                   " covid_ventilated, updated) VALUES (%s, %s, %s, %s, %s, %s, %s)", row)

                # Calculate aggregated values for states
                for i in range(2):
                    cursor.execute(
                        "INSERT IGNORE INTO icu_beds (district_id, date, clear, occupied, occupied_covid, covid_ventilated, updated) "
                        "SELECT c.parent, date, SUM(clear), SUM(occupied), SUM(occupied_covid), "
                        "SUM(covid_ventilated), updated FROM icu_beds "
                        "INNER JOIN counties c on c.rs = icu_beds.district_id "
                        "GROUP BY c.parent, date "
                        "HAVING (COUNT(c.parent) = (SELECT COUNT(*) FROM counties WHERE parent=c.parent) OR c.parent > 0) AND parent IS NOT NULL")
            self.connection.commit()
            if last_update != self.get_last_update():
                return True
        return False


class ICUGermanyHistoryUpdater(Updater):
    log = logging.getLogger(__name__)

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MIN(updated) FROM icu_beds")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        if self.get_last_update() == date(2020, 4, 24):
            return False

        new_data = False

        csv_list = self.get_resource(
            'https://www.divi.de/divi-intensivregister-tagesreport-archiv-csv?start=0&limit=500')
        urls = []

        for url in re.finditer(
                '/divi-intensivregister-tagesreport-archiv-csv/viewdocument/\d{4}/divi-intensivregister-(202[01])-(\d\d)-(\d\d)[-\d]*',
                csv_list):
            urls.append(
                ('https://www.divi.de' + url.group(0), date(int(url.group(1)), int(url.group(2)), int(url.group(3)))))

        for url, data_date in urls:
            with self.connection.cursor(dictionary=True) as cursor:
                cursor.execute('SELECT * FROM icu_beds WHERE date=%s', [data_date])
                data = cursor.fetchall()
                if data:
                    continue

                response = self.get_resource(url)
                if response:
                    self.log.debug("Got historic ICU Data from DIVI")
                    divi_data = response.splitlines()
                    reader = csv.DictReader(divi_data)
                    results = []

                    key_district_id = "gemeindeschluessel"
                    if key_district_id not in reader.fieldnames:
                        key_district_id = "kreis"

                    key_covid_ventilated = "faelle_covid_aktuell_invasiv_beatmet"
                    if key_covid_ventilated not in reader.fieldnames:
                        key_covid_ventilated = "faelle_covid_aktuell_beatmet"

                    if key_covid_ventilated not in reader.fieldnames:
                        key_covid_ventilated = None

                    key_covid = "faelle_covid_aktuell"
                    if key_covid not in reader.fieldnames:
                        key_covid = None

                    for row in reader:
                        # Berlin is here AGS = 11000
                        if row[key_district_id] == '11000':
                            row[key_district_id] = '11'

                        if key_covid_ventilated:
                            num_ventilated = row[key_covid_ventilated]
                        else:
                            num_ventilated = None

                        if key_covid:
                            num_covid = row[key_covid]
                        else:
                            num_covid = None

                        row_contents = [row[key_district_id], data_date, row['betten_frei'], row['betten_belegt'],
                                        num_covid, num_ventilated, data_date]
                        results.append(row_contents)

                    cursor.executemany(
                        "INSERT IGNORE INTO icu_beds (district_id, date, clear, occupied, occupied_covid,"
                        " covid_ventilated, updated) VALUES (%s, %s, %s, %s, %s, %s, %s)", results)
                    self.connection.commit()
                    new_data = True
                else:
                    self.log.warning(f"Not available: {url}")
        return new_data