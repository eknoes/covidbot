from typing import Optional


def clean_district_name(county_name: str) -> Optional[str]:
    if county_name is not None and county_name.count(" ") > 0:
        return " ".join(county_name.split(" ")[1:])
    return county_name