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
                results.append((row['gemeindeschluessel'], row['daten_stand'], row['betten_frei_nur_erwachsen'], row['betten_belegt_nur_erwachsen'],
                                row['faelle_covid_aktuell'], row['faelle_covid_aktuell_invasiv_beatmet']))

            with self.connection.cursor() as cursor:
                for row in results:
                    cursor.execute("INSERT IGNORE INTO icu_beds (district_id, date, clear, occupied, occupied_covid,"
                                   " covid_ventilated) VALUES (%s, %s, %s, %s, %s, %s)", row)

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
    URL = "https://diviexchange.blob.core.windows.net/%24web/zeitreihe-tagesdaten.csv"
    log = logging.getLogger(__name__)

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MIN(date) FROM icu_beds")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()
        if last_update is not None and last_update.date() == date(2020, 4, 24):
            return False

        new_data = False

        data = self.get_resource(self.URL, True)
        if not data:
            return new_data

        reader = csv.DictReader(data.splitlines())

        with self.connection.cursor(dictionary=True) as cursor:
            results = []

            key_district_id = "gemeindeschluessel"
            key_covid_ventilated = "faelle_covid_aktuell_invasiv_beatmet"
            key_covid = "faelle_covid_aktuell"

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

                row_contents = [row[key_district_id], row['date'], row['betten_frei_nur_erwachsen'], row['betten_belegt_nur_erwachsen'],
                                num_covid, num_ventilated]
                results.append(row_contents)

            cursor.executemany(
                "INSERT IGNORE INTO icu_beds (district_id, date, clear, occupied, occupied_covid,"
                " covid_ventilated) VALUES (%s, %s, %s, %s, %s, %s)", results)

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
            new_data = True
        return new_data
