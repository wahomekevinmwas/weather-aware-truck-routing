import itertools
import unittest

from planner.core.recommend import RouteStats, compute_stats, recommend
from planner.core.risk import Risk, classify

L, M, H = Risk.LOW, Risk.MODERATE, Risk.HIGH


def mk(hours, unknown=0.0):
    return RouteStats(distance_miles=100.0, duration_hours=hours, miles_by_level={},
                      no_travel_miles=0.0, severe_miles=0.0, high_miles=0.0,
                      average_risk=0.0, worst_level=L, unknown_miles=unknown)


class BadWeatherValueTests(unittest.TestCase):
    def test_nan_and_infinity_are_rejected_not_scored_as_low(self):
        for bad in (float("nan"), float("inf")):
            for args in [(bad, 0, 0, 0), (0, bad, 0, 0), (0, 0, bad, 0), (0, 0, 0, bad)]:
                with self.subTest(args=args):
                    with self.assertRaises(ValueError):
                        classify(*args)


class UnknownStatsTests(unittest.TestCase):
    def test_unknown_miles_are_tracked_and_excluded_from_average(self):
        s = compute_stats([0, 50, 100], [L, None, H], 100, 2.0)
        self.assertEqual(s.unknown_miles, 50)
        self.assertEqual(s.high_miles, 25)
        self.assertAlmostEqual(s.average_risk, 1.0)   # (0*25 + 2*25) / 50 known miles
        self.assertEqual(s.worst_level, H)

    def test_all_unknown_does_not_crash_or_look_safe_in_ranking(self):
        s = compute_stats([0, 50, 100], [None, None, None], 100, 2.0)
        self.assertEqual((s.unknown_miles, s.average_risk), (100, 0.0))

    def test_route_with_gaps_loses_to_a_fully_known_route(self):
        gappy = compute_stats([0, 50, 100], [L, None, L], 100, 4.0)
        known = compute_stats([0, 50, 100], [M, M, M], 100, 6.0)
        self.assertEqual(recommend([gappy, known])[0], 1)
        self.assertEqual(recommend([known, gappy])[0], 0)


class UnknownRankingTests(unittest.TestCase):
    def test_under_one_mile_unknown_is_a_tie_so_speed_decides(self):
        fast, slow = mk(4.0, unknown=0.4), mk(6.0)
        self.assertEqual(recommend([fast, slow])[0], 0)
        self.assertEqual(recommend([slow, fast])[0], 1)

    def test_winner_is_the_same_for_all_6_orderings(self):
        routes = [mk(8.0, 0.0), mk(6.0, 0.9), mk(4.0, 1.8)]
        hours = set()
        for perm in itertools.permutations(routes):
            best = recommend(list(perm))[0]
            hours.add(perm[best].duration_hours)
        self.assertEqual(len(hours), 1, hours)


if __name__ == "__main__":
    unittest.main()
