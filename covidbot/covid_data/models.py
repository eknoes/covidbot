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
    type: Optional[str] = None
    parent: Optional[int] = None


@dataclass
class VaccinationData:
    vaccinated_full: int
    vaccinated_partial: int
    full_rate: float
    partial_rate: float
    date: date


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

    def total_beds(self) -> int:
        return self.clear_beds + self.occupied_beds

    def percent_occupied(self) -> float:
        return self.occupied_beds / self.total_beds() * 100

    def percent_covid(self) -> float:
        return self.occupied_covid / self.total_beds() * 100


@dataclass
class RuleData:
    date: datetime
    text: str
    link: str


@dataclass
class DistrictData(District):
    date: Optional[datetime.date] = None
    incidence: Optional[float] = None
    incidence_trend: Optional[TrendValue] = None
    incidence_interval_since: Optional[datetime.date] = None
    incidence_interval_upper_value: Optional[int] = None
    new_cases: Optional[int] = None
    cases_trend: Optional[TrendValue] = None
    new_deaths: Optional[int] = None
    deaths_trend: Optional[TrendValue] = None
    total_cases: Optional[int] = None
    total_deaths: Optional[int] = None
    vaccinations: Optional[VaccinationData] = None
    r_value: Optional[RValueData] = None
    icu_data: Optional[ICUData] = None
    rules: Optional[RuleData] = None
