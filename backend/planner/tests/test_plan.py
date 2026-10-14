import unittest
from datetime import datetime, timezone

from planner.core.checkpoints import SPACINGS, build_checkpoints
from planner.services.geocoding import GeocodeError, Place
from planner.services.plan import PlanError, PlanService, checkpoint_count, choose_spacing
from planner.services.routing import RawRoute, RouteOptions, RoutingError
from planner.services.weather import WeatherBatch, WeatherError, point_key

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
PLACES = {"Origin": (40.0, -90.0), "Dest": (42.0, -90.0), "Origin Twin": (40.0, -90.0)}


class FakeGeocoder:
    def __init__(self, tz="America/Chicago", tz_error=None):
        self.tz, self.tz_error = tz, tz_error

    def geocode(self, query):
        if query not in PLACES:
            raise GeocodeError(f"Could not find {query!r}")
        lat, lon = PLACES[query]
        return Place(name=query, lat=lat, lon=lon, source="coordinates")

    def timezone(self, lat, lon):
        if self.tz_error:
            raise self.tz_error
        return self.tz


class AnyHour(dict):
    """Pretends to hold the same reading for every hourly timestamp."""

    def __init__(self, row):
        super().__init__()
        self.row = row

    def get(self, key, default=None):
        return self.row


class FakeWeather:
    def __init__(self, wind_at=lambda lat, lon: 10.0, rain=0.0, snow=0.0,
                 drop=lambda lat, lon: False, error=None, errors=()):
        self.wind_at, self.rain, self.snow, self.drop = wind_at, rain, snow, drop
        self.error, self.errors = error, list(errors)
        self.calls = []

    def fetch(self, points, days):
        self.calls.append((list(points), days))
        if self.error:
            raise self.error
        hours = {}
        for lat, lon in points:
            if not self.drop(lat, lon):
                hours[point_key(lat, lon)] = AnyHour((self.wind_at(lat, lon), 15.0, self.rain, self.snow))
        return WeatherBatch(hours, list(self.errors))


def meridian_route(lon, miles, hours):
    pts = [(40.0 + i, lon) for i in range(3)]
    return RawRoute(distance_miles=miles, duration_hours=hours, points=pts)


def three_routes():
    return [meridian_route(-95.0, 140.0, 2.5), meridian_route(-90.0, 150.0, 2.7), meridian_route(-85.0, 160.0, 2.9)]


def make_service(routes=None, weather=None, geocoder=None, notes=(), route_error=None, now=NOW):
    routes = routes if routes is not None else three_routes()
    weather = weather or FakeWeather()

    def build(client, origin, destination):
        if route_error:
            raise route_error
        return RouteOptions(routes=list(routes), notes=list(notes))

    service = PlanService(geocoder or FakeGeocoder(), router=None, weather=weather,
                          build_options=build, now=lambda: now)
    return service, weather


def payload(**over):
    base = {"origin": "Origin", "destination": "Dest", "departure": "2026-10-16T08:00",
            "load_lb": 42000, "spacing": 25}
    base.update(over)
    return base


WEST_IS_BAD = lambda lat, lon: 60.0 if lon < -92 else 10.0


class PlanFlowTests(unittest.TestCase):
    def test_response_shape_and_checkpoints(self):
        service, weather = make_service()
        res = service.plan(payload())
        self.assertEqual(len(res["routes"]), 3)
        self.assertEqual(res["spacing"], {"requested": 25, "used": 25})
        self.assertEqual(len(weather.calls), 1)
        self.assertEqual(weather.calls[0][1], 3)
        first = res["routes"][0]
        cps = first["checkpoints"]
        self.assertEqual([c["mile"] for c in cps], [0.0, 25.0, 50.0, 75.0, 100.0, 125.0, 140.0])
        etas = [c["eta_utc"] for c in cps]
        self.assertEqual(etas, sorted(etas))
        self.assertGreaterEqual(len(first["geometry"]), 2)
        for key in ("distance_miles", "duration_hours", "stats", "rank", "arrival_local", "geometry", "source"):
            self.assertIn(key, first)
        self.assertEqual(sorted(r["rank"] for r in res["routes"]), [1, 2, 3])
        self.assertEqual([r["recommended"] for r in res["routes"]].count(True), 1)
        self.assertEqual(res["origin"]["name"], "Origin")
        self.assertIsInstance(res["explanation"], str)

    def test_fastest_route_wins_when_weather_is_clear(self):
        service, _ = make_service()
        self.assertEqual(service.plan(payload())["recommended_index"], 0)

    def test_recommends_route_that_avoids_bad_weather(self):
        service, _ = make_service(weather=FakeWeather(wind_at=WEST_IS_BAD))
        res = service.plan(payload())
        self.assertEqual(res["recommended_index"], 1)
        west, middle = res["routes"][0], res["routes"][1]
        self.assertGreater(west["stats"]["no_travel_miles"], 0)
        self.assertEqual(middle["stats"]["no_travel_miles"], 0)
        self.assertEqual(west["rank"], 3)
        self.assertEqual(west["stats"]["worst_level"], "No Travel")
        self.assertEqual({c["level"] for c in west["checkpoints"]}, {"No Travel"})

    def test_load_weight_changes_risk(self):
        for load, expected in ((10000, "Severe"), (42000, "No Travel")):
            with self.subTest(load=load):
                service, _ = make_service(weather=FakeWeather(wind_at=lambda lat, lon: 50.0))
                res = service.plan(payload(load_lb=load))
                self.assertEqual({c["level"] for c in res["routes"][0]["checkpoints"]}, {expected})

    def test_missing_weather_is_unknown_never_low(self):
        service, _ = make_service(weather=FakeWeather(drop=lambda lat, lon: lon < -92))
        res = service.plan(payload())
        west, middle = res["routes"][0], res["routes"][1]
        self.assertEqual({c["level"] for c in west["checkpoints"]}, {"Unknown"})
        self.assertTrue(all(c["level_value"] is None and c["wind_mph"] is None for c in west["checkpoints"]))
        self.assertGreater(west["stats"]["unknown_miles"], 0)
        self.assertEqual(west["stats"]["miles_by_level"]["Low"], 0)
        self.assertEqual(west["stats"]["worst_level"], "Unknown")
        self.assertNotIn("Unknown", {c["level"] for c in middle["checkpoints"]})
        self.assertTrue(any("Unknown" in n for n in res["notes"]))

    def test_departure_is_read_as_origin_local_time(self):
        service, _ = make_service()
        res = service.plan(payload())
        self.assertEqual(res["departure"], {"local": "2026-10-16T08:00",
                                            "utc": "2026-10-16T13:00:00+00:00",
                                            "timezone": "America/Chicago"})
        first = res["routes"][0]["checkpoints"][0]
        self.assertEqual(first["eta_utc"], "2026-10-16T13:00:00+00:00")
        self.assertEqual(first["eta_local"], "2026-10-16T08:00-05:00")

    def test_timezone_failure_falls_back_to_utc_with_note(self):
        service, _ = make_service(geocoder=FakeGeocoder(tz_error=GeocodeError("down")))
        res = service.plan(payload())
        self.assertEqual(res["departure"]["timezone"], "UTC")
        self.assertEqual(res["departure"]["utc"], "2026-10-16T08:00:00+00:00")
        self.assertTrue(any("time zone" in n for n in res["notes"]))

    def test_weather_window_truncation_is_reported(self):
        routes = [meridian_route(-95.0, 140.0, 300.0), meridian_route(-90.0, 150.0, 300.0)]
        service, weather = make_service(routes=routes)
        res = service.plan(payload(departure="2026-10-26T08:00"))
        self.assertEqual(weather.calls[0][1], 16)
        self.assertTrue(any("16-day" in n for n in res["notes"]))

    def test_spacing_is_raised_for_long_routes(self):
        routes = [meridian_route(-95.0, 1000.0, 15.0), meridian_route(-90.0, 1050.0, 16.0),
                  meridian_route(-85.0, 1100.0, 17.0)]
        service, _ = make_service(routes=routes)
        res = service.plan(payload(spacing=10))
        self.assertEqual(res["spacing"], {"requested": 10, "used": 25})
        self.assertTrue(any("raised" in n for n in res["notes"]))
        self.assertTrue(all(len(r["checkpoints"]) <= 60 for r in res["routes"]))
        service, _ = make_service(routes=routes)
        res = service.plan(payload(spacing=50))
        self.assertEqual(res["spacing"], {"requested": 50, "used": 50})
        self.assertFalse(any("raised" in n for n in res["notes"]))

    def test_route_notes_are_passed_through(self):
        service, _ = make_service(notes=["Route 3 was built through an off-route waypoint."])
        self.assertIn("Route 3 was built through an off-route waypoint.", service.plan(payload())["notes"])

    def test_partial_weather_errors_add_a_note(self):
        service, _ = make_service(weather=FakeWeather(errors=["HTTP 429 (rate limited)"]))
        res = service.plan(payload())
        self.assertTrue(any("Weather data could not be loaded" in n for n in res["notes"]))


class PlanErrorTests(unittest.TestCase):
    def assertPlanError(self, service, body, status, code, field=None):
        with self.assertRaises(PlanError) as ctx:
            service.plan(body)
        self.assertEqual((ctx.exception.status, ctx.exception.code, ctx.exception.field), (status, code, field))

    def test_unknown_place(self):
        service, _ = make_service()
        self.assertPlanError(service, payload(origin="Nowhere"), 400, "geocode_error", "origin")

    def test_routing_failure(self):
        service, _ = make_service(route_error=RoutingError("No route found"))
        self.assertPlanError(service, payload(), 502, "routing_failed")

    def test_weather_failure(self):
        service, _ = make_service(weather=FakeWeather(error=WeatherError("all chunks failed")))
        self.assertPlanError(service, payload(), 503, "weather_unavailable")

    def test_same_place(self):
        service, _ = make_service()
        self.assertPlanError(service, payload(destination="Origin Twin", origin="Origin"), 400,
                             "invalid_input", "destination")

    def test_departure_in_the_past(self):
        service, _ = make_service()
        self.assertPlanError(service, payload(departure="2026-10-13T08:00"), 400, "invalid_input", "departure")

    def test_departure_beyond_the_forecast_window(self):
        service, _ = make_service()
        self.assertPlanError(service, payload(departure="2026-11-05T08:00"), 400, "invalid_input", "departure")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.service, _ = make_service()

    def field_of(self, body):
        with self.assertRaises(PlanError) as ctx:
            self.service.plan(body)
        return ctx.exception.field

    def test_text_fields_are_required(self):
        self.assertEqual(self.field_of(payload(origin="")), "origin")
        body = payload()
        del body["destination"]
        self.assertEqual(self.field_of(body), "destination")
        self.assertIsNone(self.field_of(["not", "an", "object"]))

    def test_departure_text_must_parse(self):
        for bad in ("tomorrow morning", "", None, 12345):
            with self.subTest(bad=bad):
                self.assertEqual(self.field_of(payload(departure=bad)), "departure")

    def test_departure_must_be_local_time(self):
        for bad in ("2026-10-16T08:00:00Z", "2026-10-16T08:00:00+03:00"):
            with self.subTest(bad=bad):
                self.assertEqual(self.field_of(payload(departure=bad)), "departure")

    def test_load_must_be_a_sane_number(self):
        for bad in (-1, "abc", None, True, float("nan"), float("inf"), 500000):
            with self.subTest(bad=bad):
                self.assertEqual(self.field_of(payload(load_lb=bad)), "load_lb")

    def test_spacing_must_be_a_supported_option(self):
        for bad in (15, "25", True, 0):
            with self.subTest(bad=bad):
                self.assertEqual(self.field_of(payload(spacing=bad)), "spacing")


class SpacingHelperTests(unittest.TestCase):
    def test_choose_spacing(self):
        cases = [(10, 500, 10), (10, 590, 10), (10, 600, 25), (10, 2800, 50),
                 (25, 1000, 25), (25, 2800, 50), (50, 5000, 50)]
        for requested, miles, expected in cases:
            with self.subTest(requested=requested, miles=miles):
                self.assertEqual(choose_spacing(requested, [miles, miles - 50]), expected)

    def test_checkpoint_count_matches_build_checkpoints(self):
        dep = datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)
        pts = [(40.0 + i, -90.0) for i in range(3)]
        for miles in (5.0, 140.0, 150.0, 590.0, 600.0, 1000.0):
            for spacing in SPACINGS:
                with self.subTest(miles=miles, spacing=spacing):
                    self.assertEqual(len(build_checkpoints(pts, miles, 2.0, spacing, dep)),
                                     checkpoint_count(miles, spacing))


if __name__ == "__main__":
    unittest.main()
