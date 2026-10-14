"""A stalled weather request must give up early enough that a retry still fits in the time budget.

Self-contained: it uses its own fake session and clock and stubs parse_entry, so it only exercises
the retry/timeout logic of WeatherClient.
"""
import unittest
from unittest import mock

import requests

from planner.services import weather
from planner.services.weather import WeatherClient


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"stub": True}


class StallingSession:
    """The first `stalls` calls hang for the full timeout and then time out; later calls succeed."""

    def __init__(self, clock, stalls):
        self.clock, self.stalls, self.timeouts = clock, stalls, []

    def get(self, url, params=None, timeout=None):
        self.timeouts.append(timeout)
        if len(self.timeouts) <= self.stalls:
            self.clock.now += timeout            # time passes while the request hangs
            raise requests.Timeout("stalled")
        self.clock.now += 1.0                    # a healthy call takes about a second
        return FakeResponse()


def make(stalls):
    clock = FakeClock()
    session = StallingSession(clock, stalls)
    return WeatherClient(session=session, clock=clock, sleep=clock.sleep), session, clock


@mock.patch.object(weather, "parse_entry", lambda entry: "parsed")
class StallTests(unittest.TestCase):
    def test_default_attempt_timeout_is_short(self):
        self.assertLessEqual(WeatherClient().timeout, 10)

    def test_a_stalled_first_attempt_still_leaves_room_for_a_retry(self):
        client, session, _ = make(stalls=1)
        batch = client.fetch([(41.88, -87.63)], days=1)
        self.assertEqual(len(session.timeouts), 2)           # the stall, then a successful retry
        self.assertEqual(batch.errors, [])
        self.assertEqual(list(batch.hours.values()), ["parsed"])

    def test_two_stalls_then_success_still_fits(self):
        client, session, _ = make(stalls=2)
        batch = client.fetch([(41.88, -87.63)], days=1)
        self.assertEqual(batch.errors, [])
        self.assertEqual(len(session.timeouts), 3)

    def test_total_time_never_runs_far_past_the_budget(self):
        client, session, clock = make(stalls=99)
        start = clock.now
        with self.assertRaises(weather.WeatherError):         # every attempt stalls: all chunks failed
            client.fetch([(41.88, -87.63)], days=1)
        self.assertLessEqual(clock.now - start, client.budget + 6)
        self.assertTrue(all(t <= client.timeout for t in session.timeouts))


if __name__ == "__main__":
    unittest.main()
