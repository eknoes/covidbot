import json
from shapely.geometry import shape, Point


class LocationService:

    def __init__(self, file: str):
        with open(file) as f:
            self._data = json.load(f)

    def find_rs(self, lon: float, lat: float) -> int:
        point = Point(lon, lat)

        # check each polygon to see if it contains the point
        for feature in self._data['features']:
            polygon = shape(feature['geometry'])
            if polygon.contains(point):
                return int(feature['properties']['RS'])