import unittest
from datetime import date, datetime, timedelta, timezone

from planner.services.weather import (Reading, WeatherClient, WeatherError, days_needed,
                                      point_key)

KEY = "2026-10-14T05:00"


def times(days):
    start = datetime(2026, 10, 14)
    return [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(24 * days)]


def entry(lat, lon, days=2, units=("mp/h", "inch", "inch")):
    n = 24 * days
    return {"latitude": lat, "longitude": lon,
            "hourly_units": {"time": "iso8601", "wind_speed_10m": units[0], "wind_gusts_10m": units[0],
                             "rain": units[1], "snowfall": units[2]},
            "hourly": {"time": times(days), "wind_speed_10m": [lat] * n, "wind_gusts_10m": [lat + 5] * n,
                       "rain": [0.1] * n, "snowfall": [0.0] * n}}


def ok(params, call_no):
    lats = [float(x) for x in params["latitude"].split(",")]
    lons = [float(x) for x in params["longitude"].split(",")]
    entries = [entry(a, b, params["forecast_days"]) for a, b in zip(lats, lons)]
    return 200, (entries if len(entries) > 1 else entries[0])   # the real API: one point -> dict


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)[:200]

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, handler=ok):
        self.handler, self.calls = handler, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        status, body = self.handler(params, len(self.calls))
        return FakeResponse(status, body)


def client(handler=ok, clock=lambda: 1000.0):
    s = FakeSession(handler)
    return WeatherClient(session=s, sleep=lambda secs: None, clock=clock), s


class FetchTests(unittest.TestCase):
    def test_single_point_dict_response(self):
        c, _ = client()
        batch = c.fetch([(40.0, -100.0)], 2)
        self.assertEqual(batch.reading(40.0, -100.0, KEY), Reading(wind=40.0, gust=45.0, rain=0.1, snow=0.0))

    def test_many_points_are_batched_and_deduplicated(self):
        base = [(30 + i * 0.1, -95.0) for i in range(120)]
        c, s = client()
        batch = c.fetch(base + base[:10], 2)
        self.assertEqual(sorted(len(call["latitude"].split(",")) for call in s.calls), [20, 50, 50])
        self.assertEqual(batch.reading(30.5, -95.0, KEY).wind, 30.5)
        self.assertEqual(batch.errors, [])

    def test_nearby_coordinates_share_one_cache_key(self):
        self.assertEqual(point_key(40.001, -100.004), point_key(40.004, -100.001))

    def test_second_fetch_uses_the_cache(self):
        c, s = client()
        c.fetch([(40.0, -100.0)], 2)
        c.fetch([(40.0, -100.0)], 2)
        self.assertEqual(len(s.calls), 1)

    def test_cache_expires(self):
        now = [1000.0]
        c, s = client(clock=lambda: now[0])
        c.fetch([(40.0, -100.0)], 2)
        now[0] += 1801
        c.fetch([(40.0, -100.0)], 2)
        self.assertEqual(len(s.calls), 2)

    def test_cache_is_not_reused_for_a_longer_forecast(self):
        c, s = client()
        c.fetch([(40.0, -100.0)], 2)
        c.fetch([(40.0, -100.0)], 5)
        self.assertEqual(len(s.calls), 2)
        c.fetch([(40.0, -100.0)], 2)      # the 5-day copy covers it
        self.assertEqual(len(s.calls), 2)

    def test_retry_then_success(self):
        c, s = client(lambda p, n: (500, {}) if n < 3 else ok(p, n))
        self.assertIsNotNone(c.fetch([(40.0, -100.0)], 2).reading(40.0, -100.0, KEY))
        self.assertEqual(len(s.calls), 3)


class UnknownDataTests(unittest.TestCase):
    def test_null_value_is_unknown_not_low(self):
        def with_null(p, n):
            e = entry(40.0, -100.0, p["forecast_days"])
            e["hourly"]["wind_speed_10m"][5] = None
            return 200, e
        c, _ = client(with_null)
        batch = c.fetch([(40.0, -100.0)], 2)
        self.assertIsNone(batch.reading(40.0, -100.0, KEY))
        self.assertIsNotNone(batch.reading(40.0, -100.0, "2026-10-14T06:00"))

    def test_negative_and_infinite_values_are_unknown(self):
        def bad(p, n):
            e = entry(40.0, -100.0, p["forecast_days"])
            e["hourly"]["rain"][5] = -1.0
            e["hourly"]["snowfall"][6] = float("inf")
            return 200, e
        c, _ = client(bad)
        batch = c.fetch([(40.0, -100.0)], 2)
        self.assertIsNone(batch.reading(40.0, -100.0, "2026-10-14T05:00"))
        self.assertIsNone(batch.reading(40.0, -100.0, "2026-10-14T06:00"))

    def test_timestamp_outside_the_forecast_is_unknown(self):
        c, _ = client()
        self.assertIsNone(c.fetch([(40.0, -100.0)], 2).reading(40.0, -100.0, "2030-01-01T00:00"))

    def test_point_that_was_never_fetched_is_unknown(self):
        c, _ = client()
        self.assertIsNone(c.fetch([(40.0, -100.0)], 2).reading(41.0, -100.0, KEY))


class FailureTests(unittest.TestCase):
    def test_unexpected_units_are_rejected(self):
        c, _ = client(lambda p, n: (200, entry(40.0, -100.0, p["forecast_days"], units=("km/h", "inch", "inch"))))
        with self.assertRaises(WeatherError) as ctx:
            c.fetch([(40.0, -100.0)], 2)
        self.assertIn("units", str(ctx.exception))

    def test_one_failed_batch_makes_only_those_points_unknown(self):
        def fail_second(p, n):
            return (500, {}) if p["latitude"].startswith("35.0,") else ok(p, n)
        pts = [(30 + i * 0.1, -95.0) for i in range(120)]
        c, _ = client(fail_second)
        batch = c.fetch(pts, 2)
        self.assertEqual(len(batch.errors), 1)
        self.assertIn("HTTP 500", batch.errors[0])
        self.assertIsNotNone(batch.reading(30.0, -95.0, KEY))
        self.assertIsNone(batch.reading(36.0, -95.0, KEY))
        self.assertIsNotNone(batch.reading(41.0, -95.0, KEY))

    def test_total_failure_raises(self):
        c, _ = client(lambda p, n: (500, {}))
        with self.assertRaises(WeatherError):
            c.fetch([(40.0, -100.0)], 2)


class DaysNeededTests(unittest.TestCase):
    def test_window_edges(self):
        today = date(2026, 10, 14)
        utc = timezone.utc
        self.assertEqual(days_needed(today, datetime(2026, 10, 14, 20, 0, tzinfo=utc)), (1, False))
        self.assertEqual(days_needed(today, datetime(2026, 10, 15, 1, 0, tzinfo=utc)), (2, False))
        self.assertEqual(days_needed(today, datetime(2026, 10, 29, 23, 0, tzinfo=utc)), (16, False))
        self.assertEqual(days_needed(today, datetime(2026, 10, 30, 0, 0, tzinfo=utc)), (16, True))
        self.assertEqual(days_needed(today, datetime(2026, 10, 13, 8, 0, tzinfo=utc)), (1, False))


if __name__ == "__main__":
    unittest.main()
