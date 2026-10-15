import unittest
from datetime import datetime, timedelta, timezone

from planner.core.checkpoints import forecast_key
from planner.services.heat import HEAT_HOURS, hourly_levels
from planner.services.weather import Reading

DEPARTURE = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)


class FakeBatch:
    """Stands in for WeatherBatch: returns the Reading stored for a forecast hour key."""

    def __init__(self, readings):
        self.readings = readings
        self.asked = []

    def reading(self, lat, lon, key):
        self.asked.append(key)
        return self.readings.get(key)


def calm():
    return Reading(wind=5.0, gust=8.0, rain=0.0, snow=0.0)


def every_hour(reading):
    return {forecast_key(DEPARTURE + timedelta(hours=h)): reading for h in range(HEAT_HOURS + 1)}


class HourlyLevelsTests(unittest.TestCase):
    def test_one_value_per_hour_including_hour_zero(self):
        levels = hourly_levels(FakeBatch(every_hour(calm())), 41.9, -87.6, DEPARTURE, 42000)
        self.assertEqual(len(levels), HEAT_HOURS + 1)
        self.assertEqual(levels, [0] * (HEAT_HOURS + 1))

    def test_asks_for_consecutive_hours_starting_at_departure(self):
        batch = FakeBatch(every_hour(calm()))
        hourly_levels(batch, 41.9, -87.6, DEPARTURE, 42000)
        self.assertEqual(batch.asked[0], "2026-10-15T13:00")
        self.assertEqual(batch.asked[1], "2026-10-15T14:00")
        self.assertEqual(batch.asked[-1], "2026-10-17T13:00")

    def test_missing_forecast_hour_is_none_not_low(self):
        readings = {k: v for k, v in every_hour(calm()).items() if k <= "2026-10-15T14:00"}
        levels = hourly_levels(FakeBatch(readings), 41.9, -87.6, DEPARTURE, 42000)
        self.assertEqual(levels[:2], [0, 0])
        self.assertIsNone(levels[2])
        self.assertIsNone(levels[-1])

    def test_load_rules_are_applied(self):
        windy = every_hour(Reading(wind=40.0, gust=50.0, rain=0.0, snow=0.0))
        self.assertEqual(hourly_levels(FakeBatch(windy), 0, 0, DEPARTURE, 42000)[0], 3)   # over 40,000 lb: Severe
        self.assertEqual(hourly_levels(FakeBatch(windy), 0, 0, DEPARTURE, 40000)[0], 2)   # not over 40,000: High

    def test_rain_is_scored(self):
        rainy = every_hour(Reading(wind=5.0, gust=8.0, rain=0.30, snow=0.0))
        self.assertEqual(hourly_levels(FakeBatch(rainy), 0, 0, DEPARTURE, 10000)[0], 2)   # 0.25-0.50 in/hr: High


if __name__ == "__main__":
    unittest.main()