import json
import logging
from typing import List, Optional

import requests
from shapely.geometry import shape, Point

from covidbot.metrics import OSM_REQUEST_COUNT


class LocationService:

    def __init__(self, file: str):
        with open(file) as f:
            self._data = json.load(f)

    def find_rs(self, lon: float, lat: float) -> Optional[int]:
        point = Point(lon, lat)

        # check each polygon to see if it contains the point
        for feature in self._data['features']:
            polygon = shape(feature['geometry'])
            if polygon.contains(point):
                return int(feature['properties']['RS'])

    def find_location(self, name: str) -> List[int]:
        logging.info("Nomatim Request")
        OSM_REQUEST_COUNT.inc()
        # They provide for fair use, so we need an indication if we make too much requests
        request = requests.get("https://nominatim.openstreetmap.org/search.php",
                               params={'q': name, 'countrycodes': 'de', 'format': 'jsonv2'},
                               headers={'User-Agent': 'CovidUpdateBot (https://github.com/eknoes/covid-bot)'}
                               )
        if request.status_code < 200 or request.status_code > 299:
            logging.warning(f"Did not get a 2XX response from Nominatim for query {name} "
                            f"but {request.status_code}: {request.reason}")
            return []
        response = request.json()
        result = []
        for item in response:
            rs = self.find_rs(float(item['lon']), float(item['lat']))
            if rs and rs not in result:
                result.append(rs)

        return result
