import csv
import logging
from datetime import datetime, date
from typing import Optional

from covidbot.covid_data.updater.updater import Updater


class RValueGermanyUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://www.rki.de/DE/Content/InfAZ/N/Neuartiges_Coronavirus/Projekte_RKI/Nowcasting_Zahlen_csv.csv?__blob" \
          "=publicationFile"
    R_VALUE_7DAY_CSV_KEY = "Schätzer_7_Tage_R_Wert"
    R_VALUE_7DAY_CSV_KEY_ALT = "Sch�tzer_7_Tage_R_Wert"

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT MAX(updated) FROM covid_r_value")
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()
        if last_update and last_update.date() == date.today():
            return False

        new_data = False
        response = self.get_resource(self.URL)

        if response:
            self.log.debug("Got R-Value Data")

            rki_data = response.splitlines()
            reader = csv.DictReader(rki_data, delimiter=';', )
            district_id = self.get_district_id("Deutschland")
            if district_id is None:
                raise ValueError("No district_id for Deutschland")

            with self.connection.cursor() as cursor:
                for row in reader:
                    # RKI appends Erläuterungen to Data
                    if row['Datum'] == 'Erläuterung':
                        break

                    if row['Datum'] == '':
                        continue

                    if self.R_VALUE_7DAY_CSV_KEY not in row:
                        if self.R_VALUE_7DAY_CSV_KEY_ALT not in row:
                            raise ValueError(f"{self.R_VALUE_7DAY_CSV_KEY} is not in CSV!")
                        r_value = row[self.R_VALUE_7DAY_CSV_KEY_ALT]
                    else:
                        r_value = row[self.R_VALUE_7DAY_CSV_KEY]

                    if r_value == '.':
                        continue
                    else:
                        r_value = float(r_value.replace(",", "."))

                    try:
                        r_date = datetime.strptime(row['Datum'], "%d.%m.%Y").date()
                    except ValueError as e:
                        self.log.error(f"Could not get date of string {row['Datum']}", exc_info=e)
                        continue

                    cursor.execute("SELECT id FROM covid_r_value WHERE district_id=%s AND r_date=%s",
                                   [district_id, r_date])
                    if cursor.fetchone():
                        continue

                    new_data = True
                    cursor.execute("INSERT INTO covid_r_value (district_id, r_date, `7day_r_value`, updated) "
                                   "VALUES (%s, %s, %s, %s)", [district_id, r_date, r_value, datetime.now()])
            self.connection.commit()
        return new_data
