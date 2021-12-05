import datetime
import logging
import math
import os
from functools import reduce
from typing import Optional, Tuple, List

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker
from matplotlib import gridspec
from matplotlib.axes import Axes
from matplotlib.cbook import get_sample_data
from matplotlib.figure import Figure
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from mysql.connector import MySQLConnection

from covidbot import utils
from covidbot.metrics import CACHED_GRAPHS, CREATED_GRAPHS
from covidbot.utils import format_int, format_float


class Visualization:
    connection: MySQLConnection
    graphics_dir: str
    log = logging.getLogger(__name__)
    disable_cache: bool

    def __init__(self, connection: MySQLConnection, directory: str, disable_cache: bool = False) -> None:
        self.connection = connection
        if not os.path.exists(directory):
            os.makedirs(directory)
        if not os.path.isdir(directory):
            raise NotADirectoryError(f"Path {directory} is not a directory")

        self.graphics_dir = directory
        self.disable_cache = disable_cache

    @staticmethod
    def setup_plot(current_date: Optional[datetime.date], title: str, y_label: str,
                   source: str = "Robert-Koch-Institut", quadratic: bool = False) -> Tuple[Figure, Axes]:
        figsize = (8, 5)
        if quadratic:
            figsize = (8, 8)

        fig = plt.figure(figsize=figsize, dpi=200)
        gs = gridspec.GridSpec(15, 3)

        if current_date:
            # Second subplot just for Source and current date
            ax2 = fig.add_subplot(gs[14, 0])
            plt.axis('off')
            ax2.annotate("Stand: {date}\nQuelle: {source}"
                         .format(date=current_date.strftime("%d.%m.%Y"), source=source),
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

        # Annotate the 2nd position with D64 logo
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

        # Ticks also on right side
        ax1.tick_params(axis="y", labelleft=True, labelright=True, grid_color="#666666")

        return fig, ax1

    @staticmethod
    def teardown_plt(figure: Figure):
        figure.clf()
        plt.close(figure)

    def infections_graph(self, district_id: int, duration: int = 49, quadratic=False) -> str:
        district_name, current_date, x_data, y_data = self._get_covid_data("new_cases", district_id, duration)

        filepath = os.path.abspath(
            os.path.join(self.graphics_dir, f"infections-{current_date.isoformat()}-{district_id}-{duration}.jpg"))

        # Do not draw new graphic if its cached
        if not self.disable_cache and os.path.isfile(filepath):
            CACHED_GRAPHS.labels(type='infections').inc()
            return filepath
        CREATED_GRAPHS.labels(type='infections').inc()

        fig, ax1 = self.setup_plot(current_date, f"Neuinfektionen {district_name}", "Neuinfektionen",
                                   quadratic=quadratic)
        # Plot data
        plt.xticks(x_data, rotation='30', ha='right')
        bars = plt.bar(x_data, y_data, color="#1fa2de", width=0.8, zorder=3)
        props = dict(boxstyle='round', facecolor='#ffffff', alpha=0.7, edgecolor='#ffffff')

        # Add a label every 7 days
        if duration < 70:
            for i in range(0, len(bars), 7):
                rect = bars[i]
                height = rect.get_height()
                ax1.annotate(format_int(int(height)),
                             xy=(rect.get_x() + rect.get_width() / 2., height),
                             xytext=(0, 30), textcoords='offset points',
                             arrowprops=dict(arrowstyle="-", facecolor='black'),
                             horizontalalignment='center', verticalalignment='top', bbox=props)

            self.set_weekday_formatter(ax1, current_date.weekday())
        else:
            self.set_monthly_formatter(ax1)

        # Save to file
        plt.savefig(filepath, format='JPEG')
        self.teardown_plt(fig)
        return filepath

    def vaccination_speed_graph(self, district_id: int, duration: int = 49, quadratic=False) -> str:
        with self.connection.cursor(dictionary=True) as cursor:
            oldest_date = datetime.date.today() - datetime.timedelta(days=duration)
            cursor.execute('SELECT c.county_name as name, date, doses_diff FROM covid_vaccinations '
                           'LEFT JOIN counties c on c.rs = covid_vaccinations.district_id '
                           'WHERE district_id=%s AND date > %s ORDER BY date', [district_id, oldest_date])
            x_data = []
            y_data = []
            current_date = None
            district_name = None
            for row in cursor.fetchall():
                if row['doses_diff'] is None:
                    row['doses_diff'] = 0
                y_data.append(row['doses_diff'])
                x_data.append(row['date'])
                if not current_date or row['date'] > current_date:
                    current_date = row['date']
                    district_name = row['name']

        filepath = os.path.abspath(
            os.path.join(self.graphics_dir,
                         f"vaccination-speed-{current_date.isoformat()}-{district_id}-{duration}.jpg"))

        # Do not draw new graphic if its cached
        if not self.disable_cache and os.path.isfile(filepath):
            CACHED_GRAPHS.labels(type='vaccination-speed').inc()
            return filepath
        CREATED_GRAPHS.labels(type='vaccination-speed').inc()

        fig, ax1 = self.setup_plot(current_date, f"Impfungen {district_name}", "Verimpfte Dosen",
                                   quadratic=quadratic)
        # Plot data
        plt.xticks(x_data, rotation='30', ha='right')

        # Add a label every 7 days
        bars = plt.bar(x_data, y_data, color="#1fa2de", width=0.8, zorder=3)
        props = dict(boxstyle='round', facecolor='#ffffff', alpha=0.7, edgecolor='#ffffff')
        for i in range(len(bars) - 1, 0, -7):
            rect = bars[i]
            height = rect.get_height()
            ax1.annotate(format_int(int(height)),
                         xy=(rect.get_x() + rect.get_width() / 2., height),
                         xytext=(0, 30), textcoords='offset points',
                         arrowprops=dict(arrowstyle="-", facecolor='black'),
                         horizontalalignment='center', verticalalignment='top', bbox=props)

        self.set_weekday_formatter(ax1, current_date.weekday())

        # Save to file
        plt.savefig(filepath, format='JPEG')
        self.teardown_plt(fig)
        return filepath

    def bot_user_graph(self) -> str:
        now = datetime.datetime.now()
        quarter = math.floor(now.hour / 4)
        filepath = os.path.abspath(
            os.path.join(self.graphics_dir, f"botuser-{now.strftime(f'%Y-%m-%d-{quarter}')}.jpg"))
        if not self.disable_cache and os.path.isfile(filepath):
            CACHED_GRAPHS.labels(type='botuser').inc()
            return filepath
        CREATED_GRAPHS.labels(type='botuser').inc()

        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT date, SUM(user) as count FROM platform_statistics GROUP BY date")

            y_data = []
            x_data = []
            today = datetime.date.today()
            current = None
            for row in cursor.fetchall():
                if not current:
                    # noinspection PyUnusedLocal
                    current = row['date']
                else:
                    while row['date'] != current + datetime.timedelta(days=1):
                        current += datetime.timedelta(days=1)
                        y_data.append(y_data[-1])
                        x_data.append(current)
                current = row['date']
                y_data.append(row['count'])
                x_data.append(row['date'])

            while x_data[-1] != today:
                y_data.append(y_data[-1])
                x_data.append(x_data[-1] + datetime.timedelta(days=1))

            fig, ax1 = self.setup_plot(None, f"Nutzer:innen des Covidbots", "Anzahl")
            # Plot data
            plt.xticks(x_data, rotation='30', ha='right')
            ax1.fill_between(x_data, y_data, color="#1fa2de", zorder=3)

            self.set_monthly_formatter(ax1)

            # Save to file
            plt.savefig(filepath, format='JPEG')
            self.teardown_plt(fig)
            return filepath

    def vaccination_graph(self, district_id: int) -> str:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT vaccinated_partial, vaccinated_full, vaccinated_booster, date FROM covid_vaccinations WHERE district_id=%s ORDER BY date",
                [district_id])

            y_data_booster = []
            y_data_full = []
            y_data_partial = []
            x_data = []
            for row in cursor.fetchall():
                if not row['vaccinated_partial']:
                    row['vaccinated_partial'] = 0

                if not row['vaccinated_full']:
                    row['vaccinated_full'] = 0

                if not row['vaccinated_booster']:
                    row['vaccinated_booster'] = 0

                if len(y_data_partial) > 1 and y_data_partial[-1] > row['vaccinated_partial']:
                    row['vaccinated_partial'] = y_data_partial[-1]

                if len(y_data_full) > 1 and y_data_full[-1] > row['vaccinated_full']:
                    row['vaccinated_full'] = y_data_full[-1]

                if len(y_data_booster) > 1 and y_data_booster[-1] > row['vaccinated_booster']:
                    row['vaccinated_booster'] = y_data_booster[-1]

                y_data_partial.append(row['vaccinated_partial'])
                y_data_full.append(row['vaccinated_full'])
                y_data_booster.append(row['vaccinated_booster'])

                x_data.append(row['date'])

            filepath = os.path.abspath(
                os.path.join(self.graphics_dir, f"vaccinations-{x_data[-1].isoformat()}-{district_id}.jpg"))

            # Do not draw new graphic if its cached
            if not self.disable_cache and os.path.isfile(filepath):
                CACHED_GRAPHS.labels(type='vaccinations').inc()
                return filepath
            CREATED_GRAPHS.labels(type='vaccinations').inc()

            cursor.execute("SELECT county_name, population FROM counties WHERE rs=%s", [district_id])
            row = cursor.fetchone()
            district_name = row['county_name']
            population = row['population']

            source = "Robert-Koch-Institut"
            fig, ax1 = self.setup_plot(x_data[-1], f"Impfungen {district_name}", "Anzahl Impfungen", source=source)
            # Plot data
            plt.xticks(x_data, rotation='30', ha='right')
            ax1.fill_between(x_data, y_data_partial, color="#1fa2de", zorder=3, label="Erstimpfungen")

            i = 0
            while y_data_full[i] == 0:
                i += 1
            ax1.fill_between(x_data[i:], y_data_full[i:], color="#384955", zorder=3, label="Vollständige Erstimmunisierung")

            i = 0
            while y_data_booster[i] == 0:
                i += 1
            ax1.fill_between(x_data[i:], y_data_booster[i:], color="#9DCCED", zorder=3, label="Auffrischungsimpfungen")

            ax1.legend(loc="upper left")

            # One tick every 7 days for easier comparison
            if len(x_data) < 120:
                formatter = mdates.DateFormatter("%a, %d.%m.")
                ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=x_data[-1].weekday()))
                ax1.xaxis.set_major_formatter(formatter)
            else:
                self.set_monthly_formatter(ax1)
            ax1.yaxis.set_major_formatter(self.tick_formatter_german_numbers)

            secaxy = ax1.secondary_yaxis('right', functions=(lambda x: x / population * 100, lambda x: x * population / 100))
            secaxy.set_ylabel('Anteil der Bevölkerung')
            for direction in ["left", "right", "bottom", "top"]:
                secaxy.spines[direction].set_visible(False)
            secaxy.yaxis.set_major_formatter(lambda x, y: f'{int(x)}%')

            ax1.tick_params(axis="y", labelright=False)

            # Save to file
            plt.savefig(filepath, format='JPEG')
            self.teardown_plt(fig)
            return filepath

    def multi_incidence_graph(self, district_ids: List[int], duration: int = 49) -> Optional[str]:
        if not district_ids:
            return None

        data = []
        district_ids.sort()

        # Source: https://matplotlib.org/stable/gallery/lines_bars_and_markers/linestyles.html
        line_styles = [
            'solid', 'dotted', 'dashed', 'dashdot', (0, (5, 1)), (0, (3, 1, 1, 1)), (0, (3, 1, 1, 1, 1, 1))]

        line_colors = ['#393991', '#916047', '#6D6DDF', '#45291B', '#539140']

        i = 0
        max_y = None
        for district in district_ids:
            district_name, current_date, x_data, y_data = self._get_covid_data("incidence", district, duration)
            data.append({'name': district_name, 'x': x_data, 'y': y_data, 'date': current_date,
                         'linestyle': line_styles[i % len(line_styles)],
                         'linecolor': line_colors[i % len(line_colors)]})
            i += 1
            if max_y is None:
                max_y = max(y_data)
            else:
                max_y = max(y_data + [max_y])

        current_date = data[0].get('date')
        identifier = reduce(lambda x, y: x + y, map(str, district_ids))

        filepath = os.path.abspath(
            os.path.join(self.graphics_dir,
                         f"multi-incidence-{current_date.isoformat()}-duration-{duration}-{identifier}.jpg"))

        # Do not draw new graphic if its cached
        if not self.disable_cache and os.path.isfile(filepath):
            CACHED_GRAPHS.labels(type='incidence').inc()
            return filepath
        CREATED_GRAPHS.labels(type='incidence').inc()

        fig, ax1 = self.setup_plot(current_date, f"7-Tage-Inzidenzen", "7-Tage-Inzidenz")

        x_data = data[0].get('x')
        # Plot data
        plt.xticks(x_data, rotation='30', ha='right')

        # Sort for legend, highest at first
        data.sort(key=lambda element: element.get('y')[-1], reverse=True)
        for d in data:
            plt.plot(d.get('x'), d.get('y'), linestyle=d.get('linestyle'), color=d.get('linecolor'), zorder=3,
                     linewidth=1, label=d.get('name'))

        # Add legend
        plt.legend(loc="lower left")

        ax1.set_ylim(bottom=0)

        # Add a label every 7 days
        self.set_weekday_formatter(ax1, current_date.weekday())

        # Save to file
        plt.savefig(filepath, format='JPEG')
        self.teardown_plt(fig)
        return filepath

    def incidence_graph(self, district_id: int, duration: int = 49) -> str:
        district_name, current_date, x_data, y_data = self._get_covid_data("incidence", district_id, duration)
        filepath = os.path.abspath(
            os.path.join(self.graphics_dir, f"incidence-{current_date.isoformat()}-{district_id}-{duration}.jpg"))

        # Do not draw new graphic if its cached
        if not self.disable_cache and os.path.isfile(filepath):
            CACHED_GRAPHS.labels(type='incidence').inc()
            return filepath
        CREATED_GRAPHS.labels(type='incidence').inc()

        fig, ax1 = self.setup_plot(current_date, f"7-Tage-Inzidenz {district_name}", "7-Tage-Inzidenz")
        # Plot data
        plt.xticks(x_data, rotation='30', ha='right')

        # Add a label every 7 days
        plt.plot(x_data, y_data, color="#1fa2de", zorder=3, linewidth=3)
        ax1.set_ylim(bottom=0)

        if duration < 70:
            self.set_weekday_formatter(ax1, current_date.weekday())
        else:
            self.set_monthly_formatter(ax1)

        # Save to file
        plt.savefig(filepath, format='JPEG')
        self.teardown_plt(fig)
        return filepath

    def icu_graph(self, district_id: int) -> Optional[str]:
        current_date = None
        colors = ['#911425', '#DE354B', '#1fa2de', '']
        y_data = {'covid-ventilated': [],
                  'covid-not-ventilated': [],
                  'no-covid': [],
                  }
        x_data = []

        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                'SELECT date, (clear + occupied) as total, clear, occupied, occupied_covid, covid_ventilated FROM icu_beds WHERE district_id=%s ORDER BY date',
                [district_id])
            for row in cursor.fetchall():
                if row['occupied_covid'] is None or row['covid_ventilated'] is None or row['total'] == 0:
                    continue

                y_data['no-covid'].append((row['occupied'] - row['occupied_covid']) / row['total'] * 100)
                y_data['covid-not-ventilated'].append(
                    (row['occupied_covid'] - row['covid_ventilated']) / row['total'] * 100)
                y_data['covid-ventilated'].append(row['covid_ventilated'] / row['total'] * 100)

                x_data.append(row['date'])

                if not current_date or current_date < row['date']:
                    current_date = row['date']
            cursor.execute('SELECT county_name FROM counties WHERE rs=%s', [district_id])
            district_name = cursor.fetchall()[0]['county_name']

        filepath = os.path.abspath(
            os.path.join(self.graphics_dir, f"icu-{current_date.isoformat()}-{district_id}.jpg"))

        # Do not draw new graphic if its cached
        if not self.disable_cache and os.path.isfile(filepath):
            CACHED_GRAPHS.labels(type='icu').inc()
            return filepath
        CREATED_GRAPHS.labels(type='icu').inc()

        fig, ax1 = self.setup_plot(current_date, f"Auslastung der Intensivstationen ({district_name})", "Auslastung",
                                   source="DIVI-Intensivregister")

        # Plot data
        plt.xticks(x_data, rotation='30', ha='right')
        ax1.stackplot(x_data, y_data.values(), colors=colors,
                      labels=['Covid (beatmet)', 'Covid (ohne Beatmung)', 'Andere'], zorder=0)
        # Add legend
        plt.legend(loc='upper left')

        ax1.set_ylim(bottom=0, top=100)

        # Add a label every 7 days
        self.set_monthly_formatter(ax1)
        ax1.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter())

        # Save to file
        # plt.show()
        plt.savefig(filepath, format='JPEG')
        self.teardown_plt(fig)
        return filepath

    def hospitalization_graph(self, district_id: int, duration: int = 60, quadratic: bool = False) -> str:
        x_data, y_data, current_date = [], [], None
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT date, incidence, updated FROM hospitalisation WHERE age=\'00+\' AND district_id=%s ORDER BY date DESC LIMIT %s', [district_id, duration])
            for row in cursor.fetchall():
                x_data.append(row['date'])
                y_data.append(row['incidence'])

                if current_date is None or current_date < row['updated']:
                    current_date = row['updated']

            cursor.execute('SELECT county_name, population FROM counties WHERE rs=%s', [district_id])
            row = cursor.fetchone()
            district_name = row['county_name']
            population = row['population']

        filepath = os.path.abspath(
            os.path.join(self.graphics_dir, f"hospitalization-{current_date.isoformat()}-{district_id}-{duration}-{quadratic}.jpg"))

        # Do not draw new graphic if its cached
        if not self.disable_cache and os.path.isfile(filepath):
            CACHED_GRAPHS.labels(type="hospitalization").inc()
            return filepath
        CREATED_GRAPHS.labels(type="hospitalization").inc()

        fig, ax1 = self.setup_plot(current_date, f"Hospitalisierung {district_name}", "7-Tage-Hospitalisierungsinzidenz", "Robert-Koch-Institut", quadratic)
        # Plot data
        plt.xticks(x_data, rotation='30', ha='right')

        # Add a label every 7 days
        plt.plot(x_data, y_data, color="#1fa2de", zorder=3, linewidth=3)
        ax1.set_ylim(bottom=0)
        if duration < 70:
            self.set_weekday_formatter(ax1, current_date.weekday())
        else:
            self.set_monthly_formatter(ax1)

        ax1.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=5, steps=[1, 2, 4, 5, 10]))
        ax1.yaxis.set_major_formatter(lambda x, _: format_float(x))

        secaxy = ax1.secondary_yaxis('right', functions=(lambda x: population * x / 100000, lambda x: x / population * 100000))
        secaxy.set_ylabel('7-Tage-Hospitalisierungen')
        for direction in ["left", "right", "bottom", "top"]:
            secaxy.spines[direction].set_visible(False)
        secaxy.yaxis.set_major_formatter(self.tick_formatter_german_numbers)

        ax1.tick_params(axis="y", labelright=False)
        # Save to file
        plt.savefig(filepath, format='JPEG')
        self.teardown_plt(fig)
        return filepath

    def _get_covid_data(self, field: str, district_id: int, duration: int) -> Tuple[
        str, datetime.date, List[datetime.date], List[int]]:
        district_name: Optional[str]
        current_date: Optional[datetime.date]

        with self.connection.cursor(dictionary=True) as cursor:
            oldest_date = datetime.date.today() - datetime.timedelta(days=duration)
            cursor.execute(
                f"SELECT {field}, county_name, date FROM covid_data_calculated WHERE rs=%s AND date >= %s ORDER BY date",
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
                        self.log.warning(f"We do not have data for requested {current_date}")
                        x_data.append(current_date)
                        y_data.append(0)
                    current_date = row['date']

                x_data.append(current_date)
                if row[field]:
                    y_data.append(row[field])
                else:
                    y_data.append(0)
        return district_name, current_date, x_data, y_data

    def set_weekday_formatter(self, ax1, weekday):
        # One tick every 7 days for easier comparison
        formatter = mdates.DateFormatter("%a, %d.%m.")
        ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=weekday))
        ax1.xaxis.set_major_formatter(formatter)
        ax1.yaxis.set_major_formatter(self.tick_formatter_german_numbers)

    def set_monthly_formatter(self, ax1):
        # One tick every 7 days for easier comparison
        formatter = mdates.DateFormatter("%m/%y")
        ax1.xaxis.set_major_locator(mdates.MonthLocator())
        ax1.xaxis.set_major_formatter(formatter)
        ax1.yaxis.set_major_formatter(self.tick_formatter_german_numbers)

    # noinspection PyUnusedLocal
    @staticmethod
    def tick_formatter_german_numbers(tick_value, position) -> str:
        if tick_value > 999999:
            tick_value = float(tick_value / 1000000)
            return str(tick_value).replace(".", ",") + " Mio."
        return utils.format_int(int(tick_value))
