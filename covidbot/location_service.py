import ujson as json
import logging
from typing import List, Optional

import requests
from shapely.geometry import shape, Point

from covidbot.metrics import OSM_REQUEST_TIME, GEOLOCATION_LOOKUP_TIME


class LocationService:
    file: str

    def __init__(self, file: str):
        self.file = file

    @GEOLOCATION_LOOKUP_TIME.time()
    def find_rs(self, lon: float, lat: float) -> Optional[int]:
        point = Point(lon, lat)

        with open(self.file) as f:
            data = json.load(f)

            # check each polygon to see if it contains the point
            for feature in data['features']:
                polygon = shape(feature['geometry'])
                if polygon.contains(point):
                    return int(feature['properties']['RS'])

    @OSM_REQUEST_TIME.time()
    def find_location(self, name: str) -> List[int]:
        logging.info("Nomatim Request")
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
