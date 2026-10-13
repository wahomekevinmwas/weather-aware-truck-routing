import unittest

from planner.services.routing import RawRoute, RoutingError, build_route_options

ORIGIN, DEST = (40.0, -100.0), (40.0, -90.0)


def mk(lat, miles=530.0, hours=9.0, n=500):
    pts = [(lat, -100.0 + 10.0 * i / (n - 1)) for i in range(n)]
    return RawRoute(distance_miles=miles, duration_hours=hours, points=pts)


class FakeClient:
    def __init__(self, base, via=None):
        self.base, self.via, self.calls = base, via, []

    def route(self, points, alternatives=False):
        self.calls.append((list(points), alternatives))
        if len(points) == 2:
            if isinstance(self.base, Exception):
                raise self.base
            return list(self.base)
        if self.via is None:
            raise RoutingError("no via route available")
        result = self.via(points)
        if isinstance(result, Exception):
            raise result
        return [result]


class ThreeRouteTests(unittest.TestCase):
    def test_three_alternatives_means_no_waypoint_calls(self):
        c = FakeClient([mk(40), mk(40.5), mk(41)])
        out = build_route_options(c, ORIGIN, DEST)
        self.assertEqual(len(out.routes), 3)
        self.assertEqual(len(c.calls), 1)
        self.assertEqual(out.notes, [])

    def test_a_different_enough_candidate_becomes_the_third_route(self):
        c = FakeClient([mk(40), mk(40.5)], via=lambda pts: mk(43, 560, 10))
        out = build_route_options(c, ORIGIN, DEST)
        self.assertEqual(len(out.routes), 3)
        self.assertEqual(out.routes[2].source, "waypoint")
        self.assertEqual(len(c.calls), 1 + 4)
        self.assertTrue(any("waypoint" in n for n in out.notes))

    def test_too_long_is_rejected(self):
        c = FakeClient([mk(40), mk(40.5)], via=lambda pts: mk(43, 530 * 1.5, 9))
        out = build_route_options(c, ORIGIN, DEST)
        self.assertEqual(len(out.routes), 2)
        self.assertTrue(any("Only 2" in n for n in out.notes))

    def test_too_slow_is_rejected(self):
        c = FakeClient([mk(40), mk(40.5)], via=lambda pts: mk(43, 540, 9 * 1.6))
        self.assertEqual(len(build_route_options(c, ORIGIN, DEST).routes), 2)

    def test_too_similar_is_rejected(self):
        c = FakeClient([mk(40), mk(40.5)], via=lambda pts: mk(40.01, 531, 9.1))
        self.assertEqual(len(build_route_options(c, ORIGIN, DEST).routes), 2)

    def test_failed_candidate_requests_are_skipped_not_fatal(self):
        c = FakeClient([mk(40), mk(40.5)], via=lambda pts: RoutingError("boom"))
        out = build_route_options(c, ORIGIN, DEST)
        self.assertEqual(len(out.routes), 2)

    def test_failure_of_the_main_request_is_raised(self):
        with self.assertRaises(RoutingError):
            build_route_options(FakeClient(RoutingError("down")), ORIGIN, DEST)

    def test_one_base_route_can_gain_two_candidates_on_opposite_sides(self):
        via = lambda pts: mk(43 if pts[1][0] > 40 else 37, 560, 10)
        c = FakeClient([mk(40)], via=via)
        out = build_route_options(c, ORIGIN, DEST)
        self.assertEqual(len(out.routes), 3)
        self.assertEqual({round(r.points[0][0]) for r in out.routes}, {40, 43, 37})


if __name__ == "__main__":
    unittest.main()
