import unittest

import requests

from planner.services.geocoding import (
    NOMINATIM_MIN_INTERVAL, NOMINATIM_URL, OPEN_METEO_FORECAST_URL, OPEN_METEO_GEOCODE_URL,
    USER_AGENT, GeocodeError, GeocodingClient)


class FakeResponse:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code = status
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Serves queued responses per URL, in order. An exception instance in the queue is raised."""

    def __init__(self, routes):
        self.routes = {url: list(items) for url, items in routes.items()}
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        queue = self.routes.get(url)
        if not queue:
            raise AssertionError(f"unexpected request to {url}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def make(routes, **kw):
    clock = FakeClock()
    session = FakeSession(routes)
    client = GeocodingClient(session=session, clock=clock, sleep=clock.sleep, **kw)
    return client, session, clock


CHICAGO = [{"display_name": "Chicago, Cook County, Illinois, United States", "lat": "41.8755616", "lon": "-87.6244212"}]
EMPTY_METEO = {"generationtime_ms": 0.5}


class CoordinateTests(unittest.TestCase):
    def test_coordinates_need_no_network(self):
        client, session, _ = make({})
        p = client.geocode("41.8781, -87.6298")
        self.assertEqual((p.lat, p.lon, p.source), (41.8781, -87.6298, "coordinates"))
        self.assertEqual(session.calls, [])

    def test_out_of_range_coordinates_are_rejected(self):
        client, _, _ = make({})
        with self.assertRaises(GeocodeError):
            client.geocode("95, -87")
        with self.assertRaises(GeocodeError):
            client.geocode("40, -200")

    def test_empty_and_overlong_queries(self):
        client, _, _ = make({})
        for bad in ("", "   ", None, "x" * 300):
            with self.assertRaises(GeocodeError):
                client.geocode(bad)


class NameLookupTests(unittest.TestCase):
    def test_nominatim_success_sends_the_right_request_and_caches(self):
        client, session, _ = make({NOMINATIM_URL: [FakeResponse(200, CHICAGO)]})
        p = client.geocode("  Chicago,   IL ")
        self.assertEqual((round(p.lat, 4), round(p.lon, 4), p.source), (41.8756, -87.6244, "nominatim"))
        url, params, headers = session.calls[0]
        self.assertEqual(params["q"], "Chicago, IL")
        self.assertEqual(params["countrycodes"], "us")
        self.assertEqual(headers["User-Agent"], USER_AGENT)
        client.geocode("chicago, il")                      # same query, different case/spacing
        self.assertEqual(len(session.calls), 1)

    def test_falls_back_to_open_meteo_when_nominatim_finds_nothing(self):
        meteo = {"results": [
            {"name": "Denver", "admin1": "Georgia", "country_code": "GB", "latitude": 1.0, "longitude": 2.0},
            {"name": "Denver", "admin1": "Colorado", "country_code": "US", "latitude": 39.7392, "longitude": -104.9903}]}
        client, session, _ = make({NOMINATIM_URL: [FakeResponse(200, [])],
                                   OPEN_METEO_GEOCODE_URL: [FakeResponse(200, meteo)]})
        p = client.geocode("Denver")
        self.assertEqual((p.name, p.source), ("Denver, Colorado", "open-meteo"))   # skipped the non-US hit

    def test_falls_back_when_nominatim_is_rate_limited(self):
        meteo = {"results": [{"name": "Atlanta", "admin1": "Georgia", "country_code": "US",
                              "latitude": 33.749, "longitude": -84.388}]}
        client, session, _ = make({NOMINATIM_URL: [FakeResponse(429)],
                                   OPEN_METEO_GEOCODE_URL: [FakeResponse(200, meteo)]})
        self.assertEqual(client.geocode("Atlanta").source, "open-meteo")
        self.assertEqual(sum(1 for c in session.calls if c[0] == NOMINATIM_URL), 2)   # one retry

    def test_unknown_place(self):
        client, _, _ = make({NOMINATIM_URL: [FakeResponse(200, [])],
                             OPEN_METEO_GEOCODE_URL: [FakeResponse(200, EMPTY_METEO)]})
        with self.assertRaises(GeocodeError) as ctx:
            client.geocode("Nowhereville, ZZ")
        self.assertIn("Could not find", str(ctx.exception))

    def test_both_services_down(self):
        client, _, _ = make({NOMINATIM_URL: [requests.ConnectionError()],
                             OPEN_METEO_GEOCODE_URL: [FakeResponse(503)]})
        with self.assertRaises(GeocodeError) as ctx:
            client.geocode("Chicago")
        self.assertIn("unavailable", str(ctx.exception))

    def test_bad_json_counts_as_a_service_failure(self):
        meteo = {"results": [{"name": "Reno", "admin1": "Nevada", "country_code": "US",
                              "latitude": 39.5, "longitude": -119.8}]}
        client, _, _ = make({NOMINATIM_URL: [FakeResponse(200, bad_json=True)],
                             OPEN_METEO_GEOCODE_URL: [FakeResponse(200, meteo)]})
        self.assertEqual(client.geocode("Reno").source, "open-meteo")

    def test_malformed_nominatim_entry_is_ignored(self):
        client, _, _ = make({NOMINATIM_URL: [FakeResponse(200, [{"display_name": "x"}])],
                             OPEN_METEO_GEOCODE_URL: [FakeResponse(200, EMPTY_METEO)]})
        with self.assertRaises(GeocodeError):
            client.geocode("Somewhere")

    def test_nominatim_calls_are_spaced(self):
        client, _, clock = make({NOMINATIM_URL: [FakeResponse(200, CHICAGO)]})
        client.geocode("Chicago, IL")
        client.geocode("Chicago, Illinois")       # different text, so a second real request
        self.assertTrue(any(abs(s - NOMINATIM_MIN_INTERVAL) < 1e-6 for s in clock.slept))

    def test_cache_expires(self):
        client, session, clock = make({NOMINATIM_URL: [FakeResponse(200, CHICAGO)]}, ttl_seconds=100)
        client.geocode("Chicago, IL")
        clock.now += 101
        client.geocode("Chicago, IL")
        self.assertEqual(len(session.calls), 2)


class TimezoneTests(unittest.TestCase):
    def test_timezone_lookup_and_cache(self):
        payload = {"timezone": "America/Chicago", "utc_offset_seconds": -18000}
        client, session, _ = make({OPEN_METEO_FORECAST_URL: [FakeResponse(200, payload)]})
        self.assertEqual(client.timezone(41.8781, -87.6298), "America/Chicago")
        self.assertEqual(client.timezone(41.88, -87.63), "America/Chicago")   # same 0.1 degree cell
        self.assertEqual(len(session.calls), 1)
        params = session.calls[0][1]
        self.assertEqual((params["timezone"], params["forecast_days"]), ("auto", 1))

    def test_timezone_failures_raise_clear_errors(self):
        client, _, _ = make({OPEN_METEO_FORECAST_URL: [FakeResponse(200, {"hourly": {}})]})
        with self.assertRaises(GeocodeError):
            client.timezone(10.0, 10.0)
        client2, _, _ = make({OPEN_METEO_FORECAST_URL: [FakeResponse(500)]})
        with self.assertRaises(GeocodeError):
            client2.timezone(20.0, 20.0)


if __name__ == "__main__":
    unittest.main()
