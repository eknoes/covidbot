import datetime
import logging
import os
from typing import Optional

from matplotlib import gridspec, cbook
from matplotlib.cbook import get_sample_data
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from mysql.connector import MySQLConnection
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from covidbot import utils


class Visualization:
    connection: MySQLConnection
    graphics_dir: str
    log = logging.getLogger(__name__)

    def __init__(self, connection: MySQLConnection, directory: str) -> None:
        self.connection = connection
        if not os.path.isdir(directory):
            raise NotADirectoryError(f"Path {directory} is not a directory")

        self.graphics_dir = directory

    def infections_graph(self, district_id: int, duration: int = 21) -> str:
        district_name: Optional[str]
        current_date: Optional[datetime.date]

        with self.connection.cursor(dictionary=True) as cursor:
            oldest_date = datetime.date.today() - datetime.timedelta(days=duration)
            cursor.execute(
                "SELECT county_name, new_cases, new_deaths, date FROM covid_data_calculated WHERE rs=%s AND date >= %s ORDER BY date",
                [district_id, oldest_date])

            y_data_infections = []
            y_data_deaths = []
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
                        y_data_infections.append(-1)
                        y_data_deaths.append(-1)
                    current_date = row['date']

                x_data.append(current_date)
                if row['new_cases']:
                    y_data_infections.append(row['new_cases'])
                else:
                    y_data_infections.append(-1)

            fig = plt.figure(figsize=(8, 5), dpi=200)
            gs = gridspec.GridSpec(15, 3)

            ax1 = fig.add_subplot(gs[:14, :])
            # Plot data
            plt.xticks(x_data)
            plt.bar(x_data, y_data_infections, color="#1fa2de", width=0.8, zorder=3)

            # One tick every 7 days for easier comparison
            formatter = mdates.DateFormatter("%a, %d.%m.")
            ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=current_date.weekday()))
            ax1.xaxis.set_major_formatter(formatter)

            ax1.yaxis.set_major_formatter(self.tick_formatter_german_numbers)

            # Set title and labels
            fig.suptitle("Neuinfektionen der letzten " + str(len(y_data_infections) - 1) + " Tage\n({location})"
                         .format(location=district_name))
            plt.ylabel("Neuinfektionen")

            # Styling
            for direction in ["left", "right", "bottom", "top"]:
                ax1.spines[direction].set_visible(False)
            plt.grid(axis="y", zorder=0)
            fig.patch.set_facecolor("#eeeeee")
            ax1.patch.set_facecolor("#eeeeee")
            fig.subplots_adjust(bottom=0.2)

            # Second subplot just for Source and current date
            ax2 = fig.add_subplot(gs[14, 0])
            plt.axis('off')
            ax2.annotate("Stand: {date}\nDaten des RKI"
                         .format(date=current_date.strftime("%d.%m.%Y")),
                         color="#6e6e6e",
                         xy=(0, -3), xycoords='axes fraction',
                         horizontalalignment='left',
                         verticalalignment='bottom')

            # Third subplot for Link
            ax3 = fig.add_subplot(gs[14:, 1])
            plt.axis('off')

            ax3.annotate("Tägliche Updates:\n"
                         "https://covidbot.d-64.org",
                         color="#6e6e6e",
                         xy=(0, -3), xycoords='axes fraction',
                         horizontalalignment='left',
                         verticalalignment='bottom')

            # 4th subplot for Logo
            ax4 = fig.add_subplot(gs[14:, 2])
            plt.axis('off')

            # Annotate the 2nd position with another image (a Grace Hopper portrait)
            with get_sample_data(os.path.abspath('resources/d64-logo.png')) as logo:
                arr_img = plt.imread(logo, format='png')

            imagebox = OffsetImage(arr_img, zoom=0.3)
            imagebox.image.axes = ax4

            ab = AnnotationBbox(imagebox, xy=(0, 0), frameon=False, xybox=(1, -1), xycoords='axes fraction', box_alignment=(1, 1))

            ax4.add_artist(ab)

            # Save to file
            filepath = os.path.join(self.graphics_dir, f"infections-{current_date.isoformat()}-{district_id}.jpg")
            plt.savefig(filepath, format='JPEG')
            plt.show()
            plt.clf()
            return filepath

    @staticmethod
    def tick_formatter_german_numbers(tick_value, position) -> str:
        return utils.format_int(int(tick_value))
