import logging
from typing import List, Optional

import requests
import ujson as json
from shapely.geometry import shape, Point

from covidbot.metrics import LOCATION_OSM_LOOKUP, LOCATION_GEO_LOOKUP


class GeoLookup:
    json_data: Optional[dict]
    filename: str

    def __init__(self, filename: str):
        self.filename = filename

    def __enter__(self):
        with open(self.filename, "r") as file:
            self.json_data = json.load(file)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        del self.json_data

    def find_rs(self, lon: float, lat: float) -> Optional[int]:
        if not self.json_data:
            raise BaseException("GeoLookup has to be used in with context")

        point = Point(lon, lat)

        # check each polygon to see if it contains the point
        for feature in self.json_data['features']:
            polygon = shape(feature['geometry'])
            if polygon.contains(point):
                return int(feature['properties']['RS'])


class LocationService:
    geolookup: Optional[GeoLookup]

    def __init__(self, filename: str):
        self.geolookup = GeoLookup(filename)

    @LOCATION_GEO_LOOKUP.time()
    def find_rs(self, lon: float, lat: float) -> Optional[int]:
        with self.geolookup as lookup:
            return lookup.find_rs(lon, lat)

    @LOCATION_OSM_LOOKUP.time()
    def find_location(self, name: str, strict=False) -> List[int]:
        p = {'countrycodes': 'de', 'format': 'jsonv2'}
        if strict:
            p['city'] = name
        else:
            p['q'] = name

        request = requests.get("https://nominatim.openstreetmap.org/search.php",
                               params=p,
                               headers={'User-Agent': 'CovidBot (https://github.com/eknoes/covid-bot)'}
                               )
        if request.status_code < 200 or request.status_code > 299:
            logging.warning(f"Did not get a 2XX response from Nominatim for query {name} "
                            f"but {request.status_code}: {request.reason}")
            return []
        response = request.json()
        result = []
        stricter_results = []
        with self.geolookup as geolookup:
            for item in response:
                if strict and item['importance'] < 0.4:
                    continue

                rs = geolookup.find_rs(float(item['lon']), float(item['lat']))
                if rs and rs not in result:
                    result.append(rs)

                if strict and item['display_name'].find(name) == 0:
                    first_part = item['display_name'].split(",")[0]
                    if first_part == name:
                        return [rs]
                    stricter_results.append(rs)

        if strict and stricter_results:
            return stricter_results
        return result
