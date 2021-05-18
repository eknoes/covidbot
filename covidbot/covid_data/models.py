from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional


class TrendValue(Enum):
    UP = 0
    SAME = 1
    DOWN = 2


@dataclass
class District:
    name: str
    id: int
    type: Optional[str] = None
    parent: Optional[int] = None


@dataclass
class VaccinationData:
    vaccinated_full: int
    vaccinated_partial: int
    full_rate: float
    partial_rate: float
    date: date
    last_update: datetime
    avg_speed: Optional[int] = None
    avg_days_to_finish: Optional[int] = None
    doses_diff: Optional[int] = None


@dataclass
class RValueData:
    date: date
    r_value_7day: float
    r_trend: Optional[TrendValue] = None


@dataclass
class ICUData:
    date: date
    clear_beds: int
    occupied_beds: int
    occupied_covid: int
    covid_ventilated: int
    last_update: datetime
    occupied_beds_trend: Optional[TrendValue] = None
    occupied_covid_trend: Optional[TrendValue] = None

    def total_beds(self) -> int:
        return self.clear_beds + self.occupied_beds

    def percent_occupied(self) -> float:
        return self.occupied_beds / self.total_beds() * 100

    def percent_covid(self) -> float:
        return self.occupied_covid / self.total_beds() * 100

    def percent_ventilated(self) -> float:
        if self.covid_ventilated == 0 or self.occupied_covid == 0:
            return 0
        return self.covid_ventilated / self.occupied_covid * 100


@dataclass
class RuleData:
    date: datetime
    text: str
    link: str


@dataclass
class IncidenceIntervalData:
    upper_threshold: Optional[int] = None
    upper_threshold_days: Optional[int] = None
    upper_threshold_working_days: Optional[int] = None
    lower_threshold: Optional[int] = None
    lower_threshold_days: Optional[int] = None
    lower_threshold_working_days: Optional[int] = None


@dataclass
class DistrictFacts:
    highest_incidence: Optional[float] = None
    highest_incidence_date: Optional[date] = None
    highest_cases: Optional[int] = None
    highest_cases_date: Optional[date] = None
    first_case_date: Optional[date] = None
    highest_deaths: Optional[int] = None
    highest_deaths_date: Optional[date] = None
    first_death_date: Optional[date] = None


@dataclass
class DistrictData(District):
    date: Optional[date] = None
    incidence: Optional[float] = None
    incidence_trend: Optional[TrendValue] = None
    new_cases: Optional[int] = None
    cases_trend: Optional[TrendValue] = None
    new_deaths: Optional[int] = None
    deaths_trend: Optional[TrendValue] = None
    total_cases: Optional[int] = None
    total_deaths: Optional[int] = None
    last_update: Optional[datetime] = None
    # Optional, pluggable data
    incidence_interval_data: Optional[IncidenceIntervalData] = None
    vaccinations: Optional[VaccinationData] = None
    r_value: Optional[RValueData] = None
    icu_data: Optional[ICUData] = None
    rules: Optional[RuleData] = None
    facts: Optional[DistrictFacts] = None
