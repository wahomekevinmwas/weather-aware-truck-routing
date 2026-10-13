import itertools
import unittest

from planner.core.recommend import RouteStats, recommend
from planner.core.risk import Risk


def mk(hours, no_travel=0.0, severe=0.0, high=0.0, avg=0.0, miles=100.0):
    return RouteStats(distance_miles=miles, duration_hours=hours, miles_by_level={},
                      no_travel_miles=no_travel, severe_miles=severe, high_miles=high,
                      average_risk=avg, worst_level=Risk.LOW)


class OrderIndependenceTests(unittest.TestCase):
    def winner_hours(self, routes):
        best, _, _, _ = recommend(routes)
        return routes[best].duration_hours

    def test_winner_is_the_same_for_all_6_orderings(self):
        scenarios = {
            "severe chain": [mk(8, severe=0.0), mk(6, severe=0.9), mk(4, severe=1.8)],
            "avg risk chain": [mk(8, avg=0.0), mk(6, avg=0.015), mk(4, avg=0.03)],
            "high chain": [mk(8, high=0.0), mk(6, high=0.9), mk(4, high=1.8)],
        }
        for name, routes in scenarios.items():
            winners = {self.winner_hours(list(p)) for p in itertools.permutations(routes)}
            self.assertEqual(len(winners), 1, f"{name}: winners differ by input order: {winners}")


class NoTravelHasNoToleranceTests(unittest.TestCase):
    def test_any_no_travel_miles_lose_to_a_route_with_none(self):
        for nt in (0.1, 0.4, 0.5, 0.8, 1.5):
            drivable = mk(9.0)
            blocked = mk(5.0, no_travel=nt)
            for routes, expected in (([drivable, blocked], 0), ([blocked, drivable], 1)):
                with self.subTest(no_travel_miles=nt, order=expected):
                    self.assertEqual(recommend(routes)[0], expected)


if __name__ == "__main__":
    unittest.main()
