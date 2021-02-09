from unittest import TestCase

from covidbot.location_service import LocationService


class TestLocationService(TestCase):
    location_service: LocationService

    def setUp(self) -> None:
        self.location_service = LocationService("resources/germany_rs.geojson")

    def test_find_rs(self):
        expected = [((10.47304756818778, 52.49145414079065), 3151)]
        for ex in expected:
            self.assertEqual(ex[1], self.location_service.find_rs(ex[0][0], ex[0][1]))

        self.assertIsNone(self.location_service.find_rs(2.323020153685483, 48.83753707055439),
                          "Paris should not resolve to a RS")

    def test_find_location(self):
        self.assertCountEqual([3151], self.location_service.find_location("Neubokel"))
        self.assertCountEqual([6631, 6633, 16069], self.location_service.find_location("Simmershausen"))
