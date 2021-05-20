import datetime
from typing import Tuple, List, Callable, Optional

from covidbot.covid_data import Visualization, CovidData, DistrictData
from covidbot.interfaces.bot_response import BotResponse, UserChoice
from covidbot.settings import BotUserSettings
from covidbot.user_hint_service import UserHintService
from covidbot.user_manager import UserManager, BotUser
from covidbot.utils import MessageType, format_float, format_data_trend, format_noun, FormattableNoun, format_int


class ReportGenerator:
    user_manager: UserManager
    visualization: Visualization
    covid_data: CovidData
    user_hints: UserHintService

    def __init__(self, user_manager: UserManager, covid_data: CovidData, visualization: Visualization,
                 user_hints: UserHintService,
                 command_formatter: Callable[[str], str]):
        self.user_manager = user_manager
        self.covid_data = covid_data
        self.visualization = visualization
        self.command_formatter = command_formatter
        self.user_hints = user_hints

    def get_report_last_update(self, report: MessageType) -> Optional[datetime.date]:
        if report == MessageType.ICU_GERMANY:
            return self.covid_data.get_last_update_icu()
        elif report == MessageType.VACCINATION_GERMANY:
            return self.covid_data.get_last_update_vaccination()
        elif report == MessageType.CASES_GERMANY:
            return self.covid_data.get_last_update_cases()

    def get_available_reports(self, user: BotUser) -> List[MessageType]:
        if not user.activated or not user.subscriptions or user.created.date() == datetime.date.today():
            return []

        available_types = []
        for report_type in user.subscribed_reports:
            last_user_update = self.user_manager.get_last_updates(user.id, report_type)
            last_data_update = self.get_report_last_update(report_type)
            if not last_user_update or last_user_update < last_data_update:
                available_types.append(report_type)
        return available_types

    def generate_report(self, user: BotUser, message_type: MessageType) -> List[BotResponse]:
        if message_type == MessageType.VACCINATION_GERMANY:
            return self.generate_vaccination_report(user)
        elif message_type == MessageType.CASES_GERMANY:
            return self.generate_infection_report(user)
        elif message_type == MessageType.ICU_GERMANY:
            return self.generate_icu_report(user)
        return []

    def generate_infection_report(self, user: BotUser) -> List[BotResponse]:
        # Send How-To use if no subscriptions
        if not user.subscriptions:
            return self.get_how_to()

        # Start creating report
        graphs = []
        subscriptions = []
        for district_id in user.subscriptions:
            subscriptions.append(self.covid_data.get_district_data(district_id))
        subscriptions = self.sort_districts(subscriptions)

        message = "<b>Corona-Bericht vom {date}</b>\n\n".format(date=subscriptions[0].date.strftime("%d.%m.%Y"))

        # Short introduction overview for first country subscribed to
        countries = list(filter(lambda d: d.type == "Staat", subscriptions))
        for c in countries:
            if self.user_manager.get_user_setting(user.id, BotUserSettings.REPORT_GRAPHICS):
                graphs.append(self.visualization.infections_graph(c.id))

        country = None
        if countries:
            country = countries[0]
            subscriptions = list(filter(lambda x: x.id != country.id, subscriptions))
            message += self.get_infection_text(country)

        # Short summary for each subscribed district
        if subscriptions and len(subscriptions) > 0:
            every_graph = self.user_manager.get_user_setting(user.id, BotUserSettings.REPORT_ALL_INFECTION_GRAPHS)

            for district in subscriptions:
                message += self.get_district_summary(district)
                if every_graph:
                    graphs.append(self.visualization.infections_graph(district.id))
                message += "\n\n"

        # Generate multi-incidence graph for up to 8 districts
        if self.user_manager.get_user_setting(user.id, BotUserSettings.REPORT_GRAPHICS):
            districts = user.subscriptions[-8:]
            if 0 in user.subscriptions and 0 not in districts:
                districts[0] = 0
            graphs.append(self.visualization.multi_incidence_graph(districts))

        # Add some information regarding vaccinations, if available
        if country and country.vaccinations and MessageType.VACCINATION_GERMANY and \
                self.user_manager.get_user_setting(user.id, BotUserSettings.REPORT_INCLUDE_VACCINATION):
            message += self.get_vacc_text(country)
            if self.user_manager.get_user_setting(user.id, BotUserSettings.REPORT_EXTENSIVE_GRAPHICS):
                graphs.append(self.visualization.vaccination_graph(country.id))
                graphs.append(self.visualization.vaccination_speed_graph(country.id))

        # Add some information regarding ICU, if available
        if country and country.icu_data and self.user_manager.get_user_setting(user.id,
                                                                               BotUserSettings.REPORT_INCLUDE_ICU):
            message += self.get_icu_text(country)
            if self.user_manager.get_user_setting(user.id, BotUserSettings.REPORT_EXTENSIVE_GRAPHICS):
                graphs.append(self.visualization.icu_graph(country.id))

        # Add a user message, if some exist
        user_hint = self.user_hints.get_hint_of_today()
        if user_hint:
            message += f"{user_hint}\n\n"

        # Sources
        message += '<i>Daten vom Robert Koch-Institut (RKI), Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://corona.rki.de/">Dashboard des RKI</a> und dem ' \
                   '<a href="https://impfdashboard.de/">Impfdashboard</a>. ' \
                   'Intensivbettendaten vom <a href="https://intensivregister.de">DIVI-Intensivregister</a>.</i>' \
                   '\n\n' \
                   '<i>Sende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten. Ein Service von <a href="https://d-64.org">D64 - Zentrum für Digitalen ' \
                   'Fortschritt</a>.</i>'.format(info_command=self.command_formatter("Info"))

        message += '\n\n🧒🏽👦🏻 Sharing is caring 👩🏾🧑🏼 <a href="https://covidbot.d-64.org">www.covidbot.d-64.org</a>'

        message += "\n\n<b>Danke für das bisherige Feedback: Ab Samstag geht dieser Beta-Bericht für alle " \
                   "Nutzer:innen live. Vielen Dank für deine Unterstützung 🙏!</b>"

        reports = [BotResponse(message, graphs)]
        return reports

    def generate_icu_report(self, user: BotUser) -> List[BotResponse]:
        # Start creating report
        graphs = []
        subscriptions = []
        for district_id in user.subscriptions:
            district = self.covid_data.get_district_data(district_id)
            if district.icu_data:
                subscriptions.append(district)
        subscriptions = self.sort_districts(subscriptions)

        # Send How-To use if no subscriptions
        if not subscriptions:
            return self.get_how_to()

        message = "<b>Intensivbetten-Bericht vom {date}</b>\n\n"\
            .format(date=subscriptions[0].icu_data.date.strftime("%d.%m.%Y"))

        # Short introduction overview for first country subscribed to
        countries = list(filter(lambda d: d.type == "Staat", subscriptions))
        for c in countries:
            if self.user_manager.get_user_setting(user.id, BotUserSettings.REPORT_GRAPHICS):
                graphs.append(self.visualization.icu_graph(c.id))

        country = None
        if countries:
            country = countries[0]
            subscriptions = list(filter(lambda x: x.id != country.id, subscriptions))
            message += self.get_icu_text(country)

        # Short summary for each subscribed district
        if subscriptions and len(subscriptions) > 0:
            for district in subscriptions:
                message += self.get_district_icu_summary(district)
                message += "\n\n"

        # Add a user message, if some exist
        user_hint = self.user_hints.get_hint_of_today()
        if user_hint:
            message += f"{user_hint}\n\n"

        # Sources
        message += '<i>Intensivbettendaten vom <a href="https://intensivregister.de">DIVI-Intensivregister</a>.</i>' \
                   '\n\n' \
                   '<i>Sende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten. Ein Service von <a href="https://d-64.org">D64 - Zentrum für Digitalen ' \
                   'Fortschritt</a>.</i>'.format(info_command=self.command_formatter("Info"))

        message += '\n\n🧒🏽👦🏻 Sharing is caring 👩🏾🧑🏼 <a href="https://covidbot.d-64.org">www.covidbot.d-64.org</a>'
        reports = [BotResponse(message, graphs)]
        return reports

    def generate_vaccination_report(self, user: BotUser) -> List[BotResponse]:
        # Start creating report
        graphs = []
        subscriptions = []
        for district_id in user.subscriptions:
            district = self.covid_data.get_district_data(district_id)

            # Add parent, if no vaccination data available
            if not district.vaccinations:
                if district.parent in [d.id for d in subscriptions]:
                    continue
                district = self.covid_data.get_district_data(district.parent)

            if district.vaccinations:
                subscriptions.append(district)

        # Send How-To use if no subscriptions
        if not user.subscriptions:
            return self.get_how_to()

        subscriptions = self.sort_districts(subscriptions)
        message = "<b>Impfbericht zum {date}</b>\n\n".format(date=subscriptions[0].vaccinations.date.strftime("%d.%m.%Y"))

        # Short introduction overview for first country subscribed to
        countries = list(filter(lambda d: d.type == "Staat", subscriptions))
        for c in countries:
            if self.user_manager.get_user_setting(user.id, BotUserSettings.REPORT_GRAPHICS):
                graphs.append(self.visualization.vaccination_graph(c.id))
                graphs.append(self.visualization.vaccination_speed_graph(c.id))

        country = None
        if countries:
            country = countries[0]
            subscriptions = list(filter(lambda x: x.id != country.id, subscriptions))
            message += self.get_vacc_text(country)

        # Short summary for each subscribed district
        if subscriptions and len(subscriptions) > 0:
            for district in subscriptions:
                message += self.get_district_vacc_summary(district)
                message += "\n\n"

        # Add a user message, if some exist
        user_hint = self.user_hints.get_hint_of_today()
        if user_hint:
            message += f"{user_hint}\n\n"

        # Sources
        message += '<i>Daten vom Robert Koch-Institut (RKI) und BMG, Lizenz: dl-de/by-2-0, weitere Informationen findest Du' \
                   ' im <a href="https://impfdashboard.de/">Impfdashboard</a>.</i>' \
                   '\n\n' \
                   '<i>Sende {info_command} um eine Erläuterung ' \
                   'der Daten zu erhalten. Ein Service von <a href="https://d-64.org">D64 - Zentrum für Digitalen ' \
                   'Fortschritt</a>.</i>'.format(info_command=self.command_formatter("Info"))

        message += '\n\n🧒🏽👦🏻 Sharing is caring 👩🏾🧑🏼 <a href="https://covidbot.d-64.org">www.covidbot.d-64.org</a>'

        reports = [BotResponse(message, graphs)]
        return reports

    def get_how_to(self) -> List[BotResponse]:
        # Send How-To use if no subscriptions
        return [BotResponse("Du hast keine abonnierten Orte. Sende uns einen Ort, um diesen zu abonnieren. Dieser "
                            "taucht dann in deinem Bericht auf.",
                            choices=[UserChoice("Hilfe anzeigen", "/hilfe",
                                                f"Sende {self.command_formatter('Hilfe')}, um einen Überblick über "
                                                f"die Funktionsweise zu bekommen.")])]

    @staticmethod
    def get_district_summary(district: DistrictData) -> str:
        message = "<b>{name}</b>: {incidence}{incidence_trend}" \
            .format(name=district.name,
                    incidence=format_float(district.incidence),
                    incidence_trend=format_data_trend(district.incidence_trend))

        if district.incidence_interval_data:
            if district.incidence_interval_data.lower_threshold_days is not None:
                message += "\n• Seit {days} ({working_days}) über {threshold}" \
                    .format(days=format_noun(district.incidence_interval_data.lower_threshold_days,
                                             FormattableNoun.DAYS),
                            working_days=format_noun(
                                district.incidence_interval_data.lower_threshold_working_days,
                                FormattableNoun.WORKING_DAYS),
                            threshold=format_int(district.incidence_interval_data.lower_threshold))

            if district.incidence_interval_data.upper_threshold_days is not None:
                if district.incidence_interval_data.lower_threshold_days is None:
                    message += "\n• Seit "
                else:
                    message += ", seit "
                message += "{days} ({working_days}) unter {threshold}" \
                    .format(days=format_noun(district.incidence_interval_data.upper_threshold_days,
                                             FormattableNoun.DAYS),
                            working_days=format_noun(
                                district.incidence_interval_data.upper_threshold_working_days,
                                FormattableNoun.WORKING_DAYS),
                            threshold=format_int(district.incidence_interval_data.upper_threshold))

        message += "\n• {new_cases}, {new_deaths}" \
            .format(new_cases=format_noun(district.new_cases, FormattableNoun.NEW_INFECTIONS),
                    new_deaths=format_noun(district.new_deaths, FormattableNoun.DEATHS))
        if (district.new_cases and district.new_cases < 0) or (
                district.new_deaths and district.new_deaths < 0):
            message += "\n• <i>Eine negative Differenz zum Vortag ist idR. auf eine Korrektur der Daten " \
                       "durch das Gesundheitsamt zurückzuführen</i>"
        if district.icu_data:
            message += "\n• {percent_occupied}% ({beds_occupied}){occupied_trend} belegt, in " \
                       "{percent_covid}% ({beds_covid}){covid_trend} Covid19-Patient:innen, {clear_beds} frei" \
                .format(beds_occupied=format_noun(district.icu_data.occupied_beds, FormattableNoun.BEDS),
                        percent_occupied=format_float(district.icu_data.percent_occupied()),
                        occupied_trend=format_data_trend(district.icu_data.occupied_beds_trend),
                        beds_covid=format_noun(district.icu_data.occupied_covid, FormattableNoun.BEDS),
                        clear_beds=format_noun(district.icu_data.clear_beds, FormattableNoun.BEDS),
                        percent_covid=format_float(district.icu_data.percent_covid()),
                        covid_trend=format_data_trend(district.icu_data.occupied_covid_trend))

        if district.vaccinations:
            message += "\n• {no_doses} Neuimpfungen, {vacc_partial}% min. eine, {vacc_full}% beide Impfungen erhalten" \
                .format(no_doses=format_int(district.vaccinations.doses_diff),
                        vacc_partial=format_float(district.vaccinations.partial_rate * 100),
                        vacc_full=format_float(district.vaccinations.full_rate * 100))
        return message

    @staticmethod
    def get_district_icu_summary(district: DistrictData) -> str:
        message = "<b>{name}</b>: {percent_occupied}% ({beds_occupied}){occupied_trend} belegt" \
            .format(name=district.name,
                    beds_occupied=format_noun(district.icu_data.occupied_beds, FormattableNoun.BEDS),
                    percent_occupied=format_float(district.icu_data.percent_occupied()),
                    occupied_trend=format_data_trend(district.icu_data.occupied_beds_trend))

        message += "\n• {percent_covid}% ({beds_covid}){covid_trend} Covid19-Patient:innen" \
                   "\n• Davon {percent_ventilated}% ({beds_ventilated}) beatmet" \
                   "\n• {clear_beds} frei" \
            .format(beds_covid=format_noun(district.icu_data.occupied_covid, FormattableNoun.BEDS),
                    percent_covid=format_float(district.icu_data.percent_covid()),
                    covid_trend=format_data_trend(district.icu_data.occupied_covid_trend),
                    beds_ventilated=format_noun(district.icu_data.covid_ventilated, FormattableNoun.BEDS),
                    percent_ventilated=format_float(district.icu_data.percent_ventilated()),
                    clear_beds=format_noun(district.icu_data.clear_beds, FormattableNoun.BEDS))
        return message

    @staticmethod
    def get_district_vacc_summary(district: DistrictData) -> str:
        message = "<b>{name}</b>: {percent_partial}% min. Erstimpfung" \
            .format(name=district.name,
                    percent_partial=format_float(district.vaccinations.partial_rate * 100))

        message += "\n• {percent_full}% vollständig geimpft" \
                   "\n• Ø {vacc_per_day} Impfungen am Tag" \
            .format(percent_full=format_float(district.vaccinations.full_rate * 100),
                    vacc_per_day=format_int(district.vaccinations.avg_speed))
        return message

    @staticmethod
    def get_infection_text(district: DistrictData) -> str:
        message = "<b>🦠 Infektionszahlen in {name}</b>\n" \
                  "Insgesamt wurden {new_cases}{new_cases_trend} und " \
                  "{new_deaths}{new_deaths_trend} gemeldet. Die 7-Tage-Inzidenz liegt bei {incidence}" \
                  "{incidence_trend}."
        if district.r_value:
            message += " Der zuletzt gemeldete 7-Tage-R-Wert beträgt {r_value}{r_trend}." \
                .format(r_value=format_float(district.r_value.r_value_7day),
                        r_trend=format_data_trend(district.r_value.r_trend))
        message += "\n\n"
        message = message.format(name=district.name,
                                 new_cases=format_noun(district.new_cases, FormattableNoun.NEW_INFECTIONS),
                                 new_cases_trend=format_data_trend(district.cases_trend),
                                 new_deaths=format_noun(district.new_deaths, FormattableNoun.DEATHS),
                                 new_deaths_trend=format_data_trend(district.deaths_trend),
                                 incidence=format_float(district.incidence),
                                 incidence_trend=format_data_trend(district.incidence_trend))
        return message

    @staticmethod
    def get_icu_text(district: DistrictData) -> str:
        return f"<b>🏥 Intensivbetten</b>\n" \
               f"{format_float(district.icu_data.percent_occupied())}% " \
               f"({format_noun(district.icu_data.occupied_beds, FormattableNoun.BEDS)})" \
               f"{format_data_trend(district.icu_data.occupied_beds_trend)} " \
               f"der Intensivbetten sind aktuell belegt. " \
               f"In {format_noun(district.icu_data.occupied_covid, FormattableNoun.BEDS)} " \
               f"({format_float(district.icu_data.percent_covid())}%)" \
               f"{format_data_trend(district.icu_data.occupied_covid_trend)} " \
               f" liegen Patient:innen" \
               f" mit COVID-19, davon müssen {format_noun(district.icu_data.covid_ventilated, FormattableNoun.PERSONS)}" \
               f" ({format_float(district.icu_data.percent_ventilated())}%) invasiv beatmet werden. " \
               f"Insgesamt gibt es {format_noun(district.icu_data.total_beds(), FormattableNoun.BEDS)} in {district.name}.\n\n"

    @staticmethod
    def get_vacc_text(district: DistrictData, show_name: bool = False) -> str:
        name = ""
        if show_name:
            name = " (" + district.name + ")"
        return f"<b>💉 Impfdaten{name}</b>\n" \
               "Am {date} wurden {doses} Dosen verimpft. So haben {vacc_partial} ({rate_partial}%) Personen in " \
               "{name} mindestens eine Impfdosis erhalten, {vacc_full} ({rate_full}%) Menschen sind bereits " \
               "vollständig geimpft. " \
               "Bei dem Impftempo der letzten 7 Tage werden {vacc_speed} Dosen pro Tag verabreicht und in " \
               "{vacc_days_to_finish} Tagen wäre die gesamte Bevölkerung vollständig geschützt." \
               "\n\n" \
            .format(name=district.name, rate_full=format_float(district.vaccinations.full_rate * 100),
                    rate_partial=format_float(district.vaccinations.partial_rate * 100),
                    vacc_partial=format_int(district.vaccinations.vaccinated_partial),
                    vacc_full=format_int(district.vaccinations.vaccinated_full),
                    date=district.vaccinations.date.strftime("%d.%m.%Y"),
                    doses=format_int(district.vaccinations.doses_diff),
                    vacc_speed=format_int(district.vaccinations.avg_speed),
                    vacc_days_to_finish=format_int(district.vaccinations.avg_days_to_finish))

    @staticmethod
    def sort_districts(districts: List[DistrictData]) -> List[DistrictData]:
        districts.sort(key=lambda d: d.name)
        return districts
