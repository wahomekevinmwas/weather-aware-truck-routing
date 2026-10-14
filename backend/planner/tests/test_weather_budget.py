import threading
import unittest

from planner.services import weather as W


class Clock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Resp:
    def __init__(self, status):
        self.status_code = status
        self.text = ""

    def json(self):
        raise ValueError("no body in this fake")


class FakeSession:
    def __init__(self, status):
        self.status = status
        self.calls = 0
        self.timeouts = []
        self._lock = threading.Lock()

    def get(self, url, params=None, timeout=None):
        with self._lock:
            self.calls += 1
            self.timeouts.append(timeout)
        return Resp(self.status)


POINT = [(34.05, -118.24)]


class WeatherBudgetTests(unittest.TestCase):
    def make(self, status, **kw):
        clk = Clock()
        sess = FakeSession(status)
        client = W.WeatherClient(session=sess, clock=clk.now, sleep=clk.sleep, **kw)
        return client, sess, clk

    def test_429_fails_fast_after_one_short_retry(self):
        client, sess, clk = self.make(429)
        with self.assertRaises(W.WeatherError) as ctx:
            client.fetch(POINT, 4)
        self.assertIn("429", str(ctx.exception))
        self.assertEqual(sess.calls, 2)
        self.assertEqual(clk.t - 1000.0, 1.0)

    def test_time_budget_stops_retries(self):
        client, sess, clk = self.make(500, budget_seconds=2.5)
        with self.assertRaises(W.WeatherError) as ctx:
            client.fetch(POINT, 4)
        self.assertIn("time budget", str(ctx.exception))
        self.assertEqual(sess.calls, 2)

    def test_request_timeout_is_capped_by_budget(self):
        client, sess, clk = self.make(500, budget_seconds=5.0, timeout=30)
        with self.assertRaises(W.WeatherError):
            client.fetch(POINT, 4)
        self.assertEqual(sess.timeouts[0], 5.0)

    def test_rate_limit_skips_remaining_chunks(self):
        points = [(30 + i * 0.1, -100.0) for i in range(W.CHUNK * 12)]
        client, sess, clk = self.make(429)
        with self.assertRaises(W.WeatherError):
            client.fetch(points, 4)
        self.assertLessEqual(sess.calls, 8)   # 4 workers x (1 try + 1 retry); the other 8 chunks are skipped


if __name__ == "__main__":
    unittest.main()
