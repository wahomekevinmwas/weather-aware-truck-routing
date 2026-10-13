import random
import unittest

from planner.core.recommend import compute_stats, recommend, segment_lengths
from planner.core.risk import Risk

L, M, H, S, N = Risk.LOW, Risk.MODERATE, Risk.HIGH, Risk.SEVERE, Risk.NO_TRAVEL


class SegmentTests(unittest.TestCase):
    def test_hand_worked_example(self):
        self.assertEqual(segment_lengths([0, 10, 20], 20), [5, 10, 5])

    def test_segments_always_sum_to_total(self):
        rnd = random.Random(1)
        for _ in range(200):
            total = rnd.uniform(5, 3000)
            marks = sorted([0.0] + [rnd.uniform(0, total) for _ in range(rnd.randint(1, 40))] + [total])
            self.assertAlmostEqual(sum(segment_lengths(marks, total)), total, places=6)


class StatsTests(unittest.TestCase):
    def test_miles_and_average(self):
        s = compute_stats([0, 10, 20], [L, S, H], 20, 0.5)
        self.assertEqual((s.severe_miles, s.high_miles, s.no_travel_miles), (10, 5, 0))
        self.assertAlmostEqual(s.average_risk, (0 * 5 + 3 * 10 + 2 * 5) / 20)
        self.assertEqual(s.worst_level, S)
        self.assertAlmostEqual(sum(s.miles_by_level.values()), 20, places=1)

    def test_all_low(self):
        s = compute_stats([0, 25, 50], [L, L, L], 50, 1)
        self.assertEqual((s.average_risk, s.severe_miles, s.high_miles), (0, 0, 0))


def route(levels, hours, miles=100):
    marks = [miles * i / (len(levels) - 1) for i in range(len(levels))]
    return compute_stats(marks, levels, miles, hours)


class RecommendTests(unittest.TestCase):
    def test_fewest_severe_miles_beats_speed(self):
        fast_but_severe = route([L, S, S, L], 5.0)
        slow_but_calm = route([L, L, M, L], 9.0)
        best, _, why, _ = recommend([fast_but_severe, slow_but_calm])
        self.assertEqual(best, 1)
        self.assertIn("Severe", why)

    def test_no_travel_loses_to_any_drivable_route(self):
        blocked = route([L, N, L, L], 4.0)
        severe = route([S, S, S, S], 8.0)
        self.assertEqual(recommend([blocked, severe])[0], 1)

    def test_high_miles_break_a_severe_tie(self):
        a = route([L, H, H, L], 6.0)
        b = route([L, M, M, L], 7.0)
        best, _, why, _ = recommend([a, b])
        self.assertEqual(best, 1)
        self.assertIn("High", why)

    def test_average_risk_then_time(self):
        a = route([L, M, L, L], 6.0)
        b = route([L, L, L, L], 6.5)
        self.assertEqual(recommend([a, b])[0], 1)
        c = route([L, L, L, L], 6.0)
        d = route([L, L, L, L], 5.0)
        best, _, why, _ = recommend([c, d])
        self.assertEqual(best, 1)
        self.assertIn("travel time", why)

    def test_tiny_weather_difference_does_not_beat_a_much_faster_route(self):
        # 0.4 miles of High on the fast route is within the 1-mile tolerance: treated as a tie
        fast = compute_stats([0, 50, 100], [L, L, L], 100, 4.0)
        slow = compute_stats([0, 50, 100], [L, L, L], 100, 6.0)
        fast_with_blip = type(fast)(**{**fast.__dict__, "high_miles": 0.4})
        self.assertEqual(recommend([fast_with_blip, slow])[0], 0)

    def test_all_blocked_is_flagged(self):
        a = route([N, N, L], 5.0)
        b = route([N, L, L], 6.0)
        best, _, why, all_blocked = recommend([a, b])
        self.assertTrue(all_blocked)
        self.assertEqual(best, 1)
        self.assertIn("No Travel", why)

    def test_single_route_and_ordering(self):
        self.assertEqual(recommend([route([L, L], 3.0)])[0], 0)
        _, order, _, _ = recommend([route([S, S], 3.0), route([L, L], 4.0), route([H, H], 3.5)])
        self.assertEqual(order, [1, 2, 0])

    def test_empty_is_rejected(self):
        with self.assertRaises(ValueError):
            recommend([])


if __name__ == "__main__":
    unittest.main()
