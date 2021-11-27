import io
import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy
import pandas as pd

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
        if district_id is None:
            raise ValueError("No district_id for Deutschland")

        if last_update and datetime.now() - last_update < timedelta(hours=12):
            return False

        response = self.get_resource(self.URL)
        if response:
            self.log.debug("Got Vaccination Data from RKI")
            data = pd.read_csv(io.StringIO(response), parse_dates=["Impfdatum"])

            vaccinations = {d_id: {'partial': numpy.int64(0), 'full': numpy.int64(0), 'booster': numpy.int64(0), 'population': None} for d_id in range(1, 17)}

            with self.connection.cursor() as cursor:
                max_date = data['Impfdatum'].max()
                cursor.execute("SELECT * FROM covid_vaccinations WHERE date=%s LIMIT 1", [max_date])
                if cursor.fetchone():
                    return False

                cursor.execute("SELECT population FROM counties WHERE rs=0")
                fed_population = cursor.fetchone()[0]

                cursor.execute("TRUNCATE covid_vaccinations")

                for date in date_range(start_date=datetime.fromisoformat("2020-12-27").date(), end_date=(datetime.today() + timedelta(days=1)).date()):
                    d = data.query("Impfdatum == @date").groupby(['BundeslandId_Impfort', 'Impfserie']).sum()
                    if d.empty:
                        continue

                    for district_id in range(1, 17):
                        if not vaccinations[district_id]['population']:
                            cursor.execute('SELECT population FROM counties WHERE rs=%s', [district_id])
                            vaccinations[district_id]['population'] = cursor.fetchone()[0]
                            if not vaccinations[district_id]['population']:
                                self.log.warning(f"Can't fetch population for {district_id}")
                                continue

                        doses_diff = numpy.int64(0)
                        if (district_id, 1) in d.index:
                            vaccinations[district_id]['partial'] += d.at[(district_id, 1), 'Anzahl']
                            doses_diff += d.at[(district_id, 1), 'Anzahl']

                        if (district_id, 2) in d.index:
                            vaccinations[district_id]['full'] += d.at[(district_id, 2), 'Anzahl']
                            doses_diff += d.at[(district_id, 2), 'Anzahl']

                        if (district_id, 3) in d.index:
                            vaccinations[district_id]['booster'] += d.at[(district_id, 3), 'Anzahl']
                            doses_diff += d.at[(district_id, 3), 'Anzahl']

                        rate_partial = vaccinations[district_id]['partial'] / vaccinations[district_id]['population']
                        rate_full = vaccinations[district_id]['full'] / vaccinations[district_id]['population']
                        rate_booster = vaccinations[district_id]['booster'] / vaccinations[district_id]['population']

                        cursor.execute('INSERT INTO covid_vaccinations (district_id, date, vaccinated_partial, '
                                       'vaccinated_full, vaccinated_booster, rate_partial, rate_full, rate_booster, '
                                       'doses_diff) VALUE (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                                       [district_id, date,
                                        int(vaccinations[district_id]['partial']),
                                        int(vaccinations[district_id]['full']),
                                        int(vaccinations[district_id]['booster']),
                                        rate_partial.astype(float), rate_full.astype(float), rate_booster.astype(float),
                                        int(doses_diff)])

                    # Federal data
                    fed_data = data.query("Impfdatum <= @date").groupby(['Impfserie']).sum()

                    fed_partial, fed_full, fed_booster = 0, 0, 0
                    if 1 in fed_data.index:
                        fed_partial = int(fed_data.at[1, 'Anzahl'])
                    if 2 in fed_data.index:
                        fed_full = int(fed_data.at[2, 'Anzahl'])
                    if 3 in fed_data.index:
                        fed_booster = int(fed_data.at[3, 'Anzahl'])

                    fed_doses = int(d['Anzahl'].sum())

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
        return True
