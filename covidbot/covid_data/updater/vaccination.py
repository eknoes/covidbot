import io
import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy
import pandas as pd

from covidbot.covid_data.updater.districts import RKIDistrictsUpdater
from covidbot.covid_data.updater.updater import Updater
from covidbot.utils import date_range


class VaccinationGermanyUpdater(Updater):
    log = logging.getLogger(__name__)
    URL = "https://raw.githubusercontent.com/robert-koch-institut/COVID-19-Impfungen_in_Deutschland/master/Aktuell_Deutschland_Bundeslaender_COVID-19-Impfungen.csv"

    def get_last_update(self) -> Optional[datetime]:
        with self.connection.cursor() as cursor:
            germany_id = self.get_district_id("Deutschland")
            cursor.execute("SELECT MAX(last_update) FROM covid_vaccinations WHERE district_id=%s", [germany_id])
            row = cursor.fetchone()
            if row:
                return row[0]

    def update(self) -> bool:
        last_update = self.get_last_update()
        district_id = self.get_district_id("Deutschland")
        new_data = False

        if district_id is None:
            raise ValueError("No district_id for Deutschland")

        if last_update and datetime.now() - last_update < timedelta(hours=12):
            return False

        # Make sure population exists
        RKIDistrictsUpdater(self.connection).update()

        response = self.get_resource(self.URL)
        if response:
            self.log.debug("Got Vaccination Data from RKI")
            data = pd.read_csv(io.StringIO(response), parse_dates=["Impfdatum"])

            population = {d_id: None for d_id in range(1, 17)}
            with self.connection.cursor() as cursor:
                max_date = data['Impfdatum'].max().date()
                cursor.execute("SELECT MAX(date) FROM covid_vaccinations")
                row = cursor.fetchone()
                if row[0] is None:
                    min_date = data['Impfdatum'].min().date()
                else:
                    min_date = row[0]

                cursor.execute("SELECT population FROM counties WHERE rs=0")
                fed_population = cursor.fetchone()[0]

                for date in date_range(start_date=min_date + timedelta(days=1), end_date=max_date + timedelta(days=1)):
                    current_data = data.query("Impfdatum <= @date").groupby(['BundeslandId_Impfort', 'Impfserie', 'Impfstoff']).sum()
                    if current_data.empty:
                        continue

                    new_data = True
                    self.log.info(f"Got new vaccination data for {date}")
                    for district_id in range(1, 17):
                        doses_diff = int(data.query("Impfdatum == @date and BundeslandId_Impfort == @district_id")[['Anzahl']].sum())

                        district_data = current_data.query(f"BundeslandId_Impfort == @district_id")

                        if not population[district_id]:
                            cursor.execute('SELECT population FROM counties WHERE rs=%s', [district_id])
                            population[district_id] = cursor.fetchone()[0]
                            if not population[district_id]:
                                self.log.warning(f"Can't fetch population for {district_id}")
                                continue

                        district_partial = int(district_data.query("Impfserie == 1").sum())
                        district_full = int(district_data.query("Impfserie == 2").sum() + district_data.query("Impfserie == 1 and Impfstoff == 'Janssen'").sum())
                        district_booster = int(district_data.query("Impfserie == 3").sum())

                        rate_partial = district_partial / population[district_id]
                        rate_full = district_full / population[district_id]
                        rate_booster = district_booster / population[district_id]

                        cursor.execute('INSERT INTO covid_vaccinations (district_id, date, vaccinated_partial, '
                                       'vaccinated_full, vaccinated_booster, rate_partial, rate_full, rate_booster, '
                                       'doses_diff) VALUE (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                                       [district_id, date,
                                        district_partial, district_full, district_booster,
                                        rate_partial, rate_full, rate_booster,
                                        int(doses_diff)])

                    # Federal data
                    fed_data = current_data.groupby(['Impfserie']).sum()

                    fed_partial, fed_full, fed_booster = 0, 0, 0
                    if 1 in fed_data.index:
                        fed_partial = int(fed_data.at[1, 'Anzahl'])
                    if 2 in fed_data.index:
                        # Janssen is counted as partial and full vaccination, but as a single dose
                        fed_full = int(fed_data.at[2, 'Anzahl']) + \
                                   int(data.query("Impfdatum <= @date and Impfstoff == 'Janssen' and Impfserie == 1")[['Anzahl']].sum())
                    if 3 in fed_data.index:
                        fed_booster = int(fed_data.at[3, 'Anzahl'])

                    fed_doses = int(data.query("Impfdatum == @date")[['Anzahl']].sum())

                    cursor.execute('INSERT INTO covid_vaccinations (district_id, date, vaccinated_partial, '
                                   'vaccinated_full, vaccinated_booster, rate_partial, rate_full, rate_booster, '
                                   'doses_diff) VALUE (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                                   [0, date,
                                    fed_partial,
                                    fed_full,
                                    fed_booster,
                                    fed_partial / fed_population, fed_full / fed_population, fed_booster / fed_population,
                                    fed_doses])

            self.connection.commit()
        return new_data
