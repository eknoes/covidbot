import datetime
import logging
import os
from typing import Optional

from mysql.connector import MySQLConnection
import matplotlib.dates as mdates
import matplotlib.pyplot as plt



class Visualization:
    connection: MySQLConnection
    graphics_dir: str
    log = logging.getLogger(__name__)

    def __init__(self, connection: MySQLConnection, directory: str) -> None:
        self.connection = connection
        if not os.path.isdir(directory):
            raise NotADirectoryError(f"Path {directory} is not a directory")

        self.graphics_dir = directory

    def infections_graph(self, district_id: int, duration: int=21) -> str:
        district_name: Optional[str]
        current_date: Optional[datetime.date]

        with self.connection.cursor(dictionary=True) as cursor:
            oldest_date = datetime.date.today() - datetime.timedelta(days=duration)
            cursor.execute("SELECT county_name, new_cases, date FROM covid_data_calculated WHERE rs=%s AND date >= %s ORDER BY date",
                         [district_id, oldest_date])

            y_data = []
            x_data = []
            district_name = None
            current_date = None
            for row in cursor.fetchall():
                if not district_name:
                    district_name = row['county_name']

                if not current_date:
                    current_date = row['date']
                else:
                    while current_date + datetime.timedelta(days=1) != row['date']:
                        # We do not have data for that day, so set -1
                        current_date += datetime.timedelta(days=1)
                        self.log.warning(f"We do not have infection data for requested {current_date}")
                        x_data.append(current_date)
                        y_data.append(-1)
                    current_date = row['date']

                x_data.append(current_date)
                if row['new_cases']:
                    y_data.append(row['new_cases'])
                else:
                    y_data.append(-1)

            px = 1 / plt.rcParams['figure.dpi']
            fig, ax1 = plt.subplots(figsize=(900 * px, 600 * px))

            plt.xticks(x_data)
            plt.bar(x_data, y_data, color="#003f5c", width=0.95, zorder=3)

            # Styling
            plt.title("Neuinfektionen seit " + str(len(y_data) - 1) + " Tagen in {location}"
                      .format(location=district_name))
            plt.ylabel("Neuinfektionen")
            plt.figtext(0.8, 0.01, "Stand: {date}\nDaten vom Robert Koch-Institut (RKI)"
                        .format(date=current_date.strftime("%d.%m.%Y")), horizontalalignment='left', fontsize=8,
                        verticalalignment="baseline")
            plt.figtext(0.05, 0.01,
                        "Erhalte kostenlos die tagesaktuellen Daten auf Telegram, Signal oder Threema für deine Orte!\n"
                        "https://covidbot.d-64.org/", horizontalalignment='left', fontsize=8,
                        verticalalignment="baseline")

            for direction in ["left", "right", "bottom", "top"]:
                ax1.spines[direction].set_visible(False)
            plt.grid(axis="y", zorder=0)

            # One tick every 7 days for easier comparison
            formatter = mdates.DateFormatter("%a, %d %b")
            ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=current_date.weekday()))
            ax1.xaxis.set_major_formatter(formatter)

            # Save to file
            filename = f"infections-{current_date.isoformat()}-{district_id}.jpg"
            plt.savefig(filename, format='JPEG')
            plt.clf()
            return filename
