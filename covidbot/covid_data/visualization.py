import datetime
import logging
import os
from typing import Optional, Tuple

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.axes import Axes
from matplotlib.cbook import get_sample_data
from matplotlib.figure import Figure
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from mysql.connector import MySQLConnection

from covidbot import utils
from covidbot.utils import format_int


class Visualization:
    connection: MySQLConnection
    graphics_dir: str
    log = logging.getLogger(__name__)

    def __init__(self, connection: MySQLConnection, directory: str) -> None:
        self.connection = connection
        if not os.path.isdir(directory):
            raise NotADirectoryError(f"Path {directory} is not a directory")

        self.graphics_dir = directory

    @staticmethod
    def setup_plot(current_date: Optional[datetime.date], title: str, y_label: str) -> Tuple[Figure, Axes]:
        fig = plt.figure(figsize=(8, 5), dpi=200)
        gs = gridspec.GridSpec(15, 3)

        if current_date:
            # Second subplot just for Source and current date
            ax2 = fig.add_subplot(gs[14, 0])
            plt.axis('off')
            ax2.annotate("Stand: {date}\nQuelle: Robert-Koch-Institut"
                         .format(date=current_date.strftime("%d.%m.%Y")),
                         color="#6e6e6e",
                         xy=(0, -4.5), xycoords='axes fraction',
                         horizontalalignment='left',
                         verticalalignment='bottom')

        # Third subplot for Link
        ax3 = fig.add_subplot(gs[14:, 1])
        plt.axis('off')

        ax3.annotate("Tägliche Updates:\n"
                     "https://covidbot.d-64.org",
                     color="#6e6e6e",
                     xy=(0, -4.5), xycoords='axes fraction',
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

        ab = AnnotationBbox(imagebox, xy=(0, 0), frameon=False, xybox=(1, -2.5), xycoords='axes fraction',
                            box_alignment=(1, 1))

        ax4.add_artist(ab)

        ax1 = fig.add_subplot(gs[:14, :])

        # Set title and labels
        fig.suptitle(title, fontweight="bold")
        plt.ylabel(y_label)

        # Styling
        for direction in ["left", "right", "bottom", "top"]:
            ax1.spines[direction].set_visible(False)
        plt.grid(axis="y", zorder=0)
        fig.patch.set_facecolor("#eeeeee")
        ax1.patch.set_facecolor("#eeeeee")
        fig.subplots_adjust(bottom=0.2)

        return fig, ax1

    def infections_graph(self, district_id: int, duration: int = 49) -> str:
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

            filepath = os.path.join(self.graphics_dir, f"infections-{current_date.isoformat()}-{district_id}.jpg")

            # Do not draw new graphic if its cached
            if os.path.isfile(filepath):
                return filepath

            fig, ax1 = self.setup_plot(current_date, f"Neuinfektionen {district_name}", "Neuinfektionen")
            # Plot data
            plt.xticks(x_data, rotation='30', ha='right')

            # Add a label every 7 days
            bars = plt.bar(x_data, y_data_infections, color="#1fa2de", width=0.8, zorder=3)
            props = dict(boxstyle='round', facecolor='#ffffff', alpha=0.7, edgecolor='#ffffff')
            for i in range(0, len(bars), 7):
                rect = bars[i]
                height = rect.get_height()
                ax1.annotate(format_int(int(height)),
                             xy=(rect.get_x() + rect.get_width() / 2., height),
                             xytext=(0, 30), textcoords='offset points',
                             arrowprops=dict(arrowstyle="-", facecolor='black'),
                             horizontalalignment='center', verticalalignment='top', bbox=props)

            # One tick every 7 days for easier comparison
            formatter = mdates.DateFormatter("%a, %d.%m.")
            ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=current_date.weekday()))
            ax1.xaxis.set_major_formatter(formatter)
            ax1.yaxis.set_major_formatter(self.tick_formatter_german_numbers)

            # Save to file
            plt.savefig(filepath, format='JPEG')
            plt.show()
            plt.clf()
            return filepath

    def bot_user_graph(self) -> str:
        now = datetime.datetime.now()
        filepath = os.path.join(self.graphics_dir, f"botuser-{now.strftime('%Y-%m-%d-%H-00')}.jpg")
        if os.path.isfile(filepath):
            return filepath

        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(b.user_id) as count, bot_date FROM "
                           "(SELECT DISTINCT date(added) as bot_date FROM bot_user) as dates "
                           "LEFT JOIN bot_user b ON date(b.added) <= bot_date GROUP BY bot_date ORDER BY bot_date")

            y_data = []
            x_data = []
            today = datetime.date.today()
            current = None
            for row in cursor.fetchall():
                if not current:
                    current = row['bot_date']
                else:
                    while row['bot_date'] != current + datetime.timedelta(days=1):
                        current += datetime.timedelta(days=1)
                        y_data.append(y_data[-1])
                        x_data.append(current)
                current = row['bot_date']
                y_data.append(row['count'])
                x_data.append(row['bot_date'])

            while x_data[-1] != today:
                y_data.append(y_data[-1])
                x_data.append(x_data[-1] + datetime.timedelta(days=1))

            fig, ax1 = self.setup_plot(None, f"Nutzer:innen des Covidbots", "Anzahl")
            # Plot data
            plt.xticks(x_data, rotation='30', ha='right')
            ax1.fill_between(x_data, y_data, color="#1fa2de", zorder=3)

            # One tick every 7 days for easier comparison
            formatter = mdates.DateFormatter("%a, %d.%m.")
            ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=today.weekday()))
            ax1.xaxis.set_major_formatter(formatter)
            ax1.yaxis.set_major_formatter(self.tick_formatter_german_numbers)

            # Save to file
            plt.savefig(filepath, format='JPEG')
            plt.show()
            plt.clf()
            return filepath

    @staticmethod
    def tick_formatter_german_numbers(tick_value, position) -> str:
        return utils.format_int(int(tick_value))