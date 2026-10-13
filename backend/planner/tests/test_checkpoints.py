import unittest
from datetime import datetime, timedelta, timezone

from planner.core.checkpoints import (SPACINGS, build_checkpoints, departure_to_utc,
                                      forecast_key)

UTC = timezone.utc
DEP = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def east_west(n=1000, lat=40.0, lon0=-100.0, lon1=-90.0):
    return [(lat, lon0 + (lon1 - lon0) * i / (n - 1)) for i in range(n)]


class MarkTests(unittest.TestCase):
    def marks(self, distance, spacing):
        return [c.mile for c in build_checkpoints(east_west(), distance, 5.0, spacing, DEP)]

    def test_regular_spacing_with_origin_and_destination(self):
        self.assertEqual(self.marks(100, 25), [0, 25, 50, 75, 100])

    def test_non_multiple_distance_ends_at_the_destination(self):
        self.assertEqual(self.marks(110, 50), [0, 50, 100, 110])

    def test_a_mark_within_one_mile_of_the_end_is_replaced_by_the_end(self):
        self.assertEqual(self.marks(100.5, 25), [0, 25, 50, 75, 100.5])
        self.assertEqual(self.marks(99.4, 25), [0, 25, 50, 75, 99.4])

    def test_long_trip_at_10_miles_is_about_200_points_per_route(self):
        self.assertEqual(len(self.marks(2000, 10)), 201)

    def test_very_short_trip_still_has_origin_and_destination(self):
        self.assertEqual(self.marks(0.5, 25), [0, 0.5])

    def test_only_the_three_allowed_spacings(self):
        self.assertEqual(SPACINGS, (10, 25, 50))
        with self.assertRaises(ValueError):
            build_checkpoints(east_west(), 100, 5.0, 30, DEP)


class PositionAndEtaTests(unittest.TestCase):
    def test_first_and_last_checkpoints_are_the_route_ends(self):
        pts = east_west()
        cps = build_checkpoints(pts, 530, 9.0, 50, DEP)
        self.assertAlmostEqual(cps[0].lon, pts[0][1], places=6)
        self.assertAlmostEqual(cps[-1].lon, pts[-1][1], places=3)

    def test_marks_are_scaled_onto_the_routing_distance(self):
        # geometry is about 530 mi, routing says 600: the 300-mile mark is still the halfway point
        cps = build_checkpoints(east_west(), 600, 10.0, 50, DEP)
        halfway = [c for c in cps if c.mile == 300][0]
        self.assertAlmostEqual(halfway.lon, -95.0, delta=0.02)

    def test_eta_is_proportional_to_distance(self):
        cps = build_checkpoints(east_west(), 100, 5.0, 25, DEP)
        self.assertEqual(cps[0].eta, DEP)
        self.assertEqual(cps[1].eta, DEP + timedelta(hours=1.25))
        self.assertEqual(cps[-1].eta, DEP + timedelta(hours=5))

    def test_naive_departure_is_rejected(self):
        with self.assertRaises(ValueError):
            build_checkpoints(east_west(), 100, 5.0, 25, datetime(2026, 10, 14, 12, 0))


class TimeTests(unittest.TestCase):
    def test_local_departure_becomes_utc(self):
        chicago = departure_to_utc(datetime(2026, 10, 14, 8, 0), "America/Chicago")   # CDT, UTC-5
        self.assertEqual(chicago, datetime(2026, 10, 14, 13, 0, tzinfo=UTC))
        denver = departure_to_utc(datetime(2026, 10, 14, 8, 0), "America/Denver")     # MDT, UTC-6
        self.assertEqual(denver, datetime(2026, 10, 14, 14, 0, tzinfo=UTC))

    def test_departure_with_an_offset_is_rejected(self):
        with self.assertRaises(ValueError):
            departure_to_utc(datetime(2026, 10, 14, 8, 0, tzinfo=UTC), "America/Chicago")

    def test_forecast_key_rounds_to_the_nearest_hour(self):
        d = datetime(2026, 10, 14, 13, 29, 59, tzinfo=UTC)
        self.assertEqual(forecast_key(d), "2026-10-14T13:00")
        self.assertEqual(forecast_key(d.replace(minute=30, second=0)), "2026-10-14T14:00")
        self.assertEqual(forecast_key(datetime(2026, 10, 14, 23, 45, tzinfo=UTC)), "2026-10-15T00:00")

    def test_forecast_key_converts_other_zones_to_utc(self):
        cdt = timezone(timedelta(hours=-5))
        self.assertEqual(forecast_key(datetime(2026, 10, 14, 8, 0, tzinfo=cdt)), "2026-10-14T13:00")

    def test_naive_eta_is_rejected(self):
        with self.assertRaises(ValueError):
            forecast_key(datetime(2026, 10, 14, 8, 0))


if __name__ == "__main__":
    unittest.main()
