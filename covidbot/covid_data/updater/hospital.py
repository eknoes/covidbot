import csv
import logging
from datetime import datetime, timedelta
from typing import Optional

from covidbot.covid_data.updater.updater import Updater


class HospitalisationRKIUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://raw.githubusercontent.com/robert-koch-institut/COVID-19-Hospitalisierungen_in_Deutschland/master/Aktuell_Deutschland_COVID-19-Hospitalisierungen.csv"

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            germany_id = self.get_district_id("Deutschland")
            cursor.execute("SELECT MAX(updated) FROM hospitalisation WHERE district_id=%s", [germany_id])
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()

        if last_update and datetime.now() - last_update < timedelta(hours=12):
            return False

        new_data = False
        response = self.get_resource(self.URL)
        if response:
            self.log.debug("Got Hospitalisation Data from RKI")
            hospital_data = response.splitlines()
            reader = csv.DictReader(hospital_data, quoting=csv.QUOTE_NONE)

            with self.connection.cursor() as cursor:
                for row in reader:
                    if row['Bundesland'] == "Bundesgebiet":
                        row['Bundesland'] = "Deutschland"
                    district_id = self.get_district_id(row['Bundesland'])
                    if district_id is None:
                        raise ValueError(f"No district_id for {row['Bundesland']}")

                    if row['7T_Hospitalisierung_Faelle'] == "NA" or row['7T_Hospitalisierung_Inzidenz'] == "NA":
                        continue

                    updated = datetime.fromisoformat(row['Datum'])
                    cursor.execute("SELECT id FROM hospitalisation WHERE date = %s AND district_id=%s AND age=%s",
                                   [updated, district_id, row['Altersgruppe']])
                    data_id = cursor.fetchone()
                    if data_id:
                        cursor.execute("UPDATE hospitalisation SET number=%s, incidence=%s, updated=CURRENT_TIMESTAMP() WHERE id=%s", [row['7T_Hospitalisierung_Faelle'], row['7T_Hospitalisierung_Inzidenz'], data_id[0]])
                        continue

                    new_data = True

                    cursor.execute('INSERT INTO hospitalisation (district_id, date, age, number, incidence) VALUES (%s, %s, %s, %s, %s)',
                                   [district_id, updated, row['Altersgruppe'], row['7T_Hospitalisierung_Faelle'], row['7T_Hospitalisierung_Inzidenz']])
            self.connection.commit()
        return new_data
