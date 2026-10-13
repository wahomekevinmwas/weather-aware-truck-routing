import math
import unittest

from planner.core.geo import (R_MI, cumulative_miles, haversine, point_at_mile,
                              share_far_from, side_waypoint, simplify)


def east_west(lat, n=1000, lon0=-100.0, lon1=-90.0):
    return [(lat, lon0 + (lon1 - lon0) * i / (n - 1)) for i in range(n)]


class DistanceTests(unittest.TestCase):
    def test_length_along_a_parallel(self):
        pts = east_west(40.0)
        expected = 10 * math.radians(1) * R_MI * math.cos(math.radians(40))
        self.assertAlmostEqual(cumulative_miles(pts)[-1], expected, delta=0.5)

    def test_point_at_mile_midpoint_and_clamping(self):
        pts = east_west(40.0)
        cum = cumulative_miles(pts)
        mid = point_at_mile(pts, cum, cum[-1] / 2)
        self.assertAlmostEqual(mid[1], -95.0, delta=0.01)
        self.assertEqual(point_at_mile(pts, cum, -5), pts[0])
        self.assertEqual(point_at_mile(pts, cum, cum[-1] + 5), pts[-1])


class SimplifyTests(unittest.TestCase):
    def test_straight_line_collapses_to_two_points(self):
        self.assertEqual(len(simplify(east_west(40.0), 0.5)), 2)

    def test_tolerance_decides_what_survives(self):
        spike = [(40, -100), (40, -99.5), (41, -99), (40, -98.5), (40, -98)]
        self.assertEqual(len(simplify(spike, 5)), 5)    # every bend is more than 5 miles off
        self.assertEqual(len(simplify(spike, 50)), 3)   # only the 69-mile spike survives
        self.assertIn((41, -99), simplify(spike, 50))


class OverlapTests(unittest.TestCase):
    def test_same_route_has_no_far_share(self):
        self.assertEqual(share_far_from(east_west(40.0), [east_west(40.0)]), 0.0)

    def test_parallel_route_69_miles_away_is_all_far(self):
        self.assertEqual(share_far_from(east_west(41.0), [east_west(40.0)]), 1.0)

    def test_half_overlap(self):
        cand = east_west(40.0, 500, -100, -95) + east_west(42.0, 500, -95, -90)
        self.assertAlmostEqual(share_far_from(cand, [east_west(40.0)]), 0.5, delta=0.05)


class WaypointTests(unittest.TestCase):
    def test_right_of_eastbound_is_south_and_left_is_north(self):
        pts = east_west(40.0)
        cum = cumulative_miles(pts)
        right = side_waypoint(pts, cum, 0.5, "right", 80)
        left = side_waypoint(pts, cum, 0.5, "left", 80)
        self.assertLess(right[0], 40.0)
        self.assertGreater(left[0], 40.0)
        self.assertAlmostEqual(haversine(right, point_at_mile(pts, cum, cum[-1] / 2)), 80, delta=0.5)

    def test_bad_side_is_rejected(self):
        pts = east_west(40.0)
        with self.assertRaises(ValueError):
            side_waypoint(pts, cumulative_miles(pts), 0.5, "up", 10)


if __name__ == "__main__":
    unittest.main()
