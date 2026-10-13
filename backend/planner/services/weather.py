"""Weather: batched Open-Meteo requests with a cache. HTTP is isolated here so the rest is testable offline."""
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timezone

import requests

URL = "https://api.open-meteo.com/v1/forecast"
COLUMNS = ("wind_speed_10m", "wind_gusts_10m", "rain", "snowfall")
CHUNK = 50                 # points per request
MAX_FORECAST_DAYS = 16     # probed: 16 days works (384 hourly rows)
COORD_DECIMALS = 2         # about 0.7 mile; also the cache key


class WeatherError(Exception):
    pass


@dataclass(frozen=True)
class Reading:
    wind: float            # sustained 10 m wind, mph (scored)
    gust: float | None     # gusts, mph (shown, not scored)
    rain: float            # in/hr
    snow: float            # in/hr


def point_key(lat, lon):
    return (round(lat, COORD_DECIMALS), round(lon, COORD_DECIMALS))


def days_needed(today_utc, last_eta):
    """Forecast days to request so the last ETA is covered (the forecast starts at 00:00 GMT today).
    Returns (days, truncated): truncated is True when the trip runs past the 16-day window."""
    days = max(1, (last_eta.astimezone(timezone.utc).date() - today_utc).days + 1)
    if days > MAX_FORECAST_DAYS:
        return MAX_FORECAST_DAYS, True
    return days, False


def parse_entry(entry):
    """One location's response -> {timestamp: (wind, gust, rain, snow)}. Units are checked, never assumed."""
    try:
        units = entry["hourly_units"]
        hourly = entry["hourly"]
        times = hourly["time"]
        cols = [hourly[name] for name in COLUMNS]
    except (KeyError, TypeError) as exc:
        raise WeatherError(f"unexpected weather response shape ({exc!r})") from exc
    if (units.get("wind_speed_10m") not in ("mp/h", "mph")
            or units.get("rain") != "inch" or units.get("snowfall") != "inch"):
        raise WeatherError(f"unexpected weather units: {units}")
    if any(len(c) != len(times) for c in cols):
        raise WeatherError("weather columns have different lengths")
    return {t: (w, g, r, s) for t, w, g, r, s in zip(times, *cols)}


def reading_at(hours, key):
    """Reading for one hourly timestamp, or None when data is missing or unusable (-> Unknown)."""
    row = hours.get(key)
    if row is None:
        return None
    wind, gust, rain, snow = row
    for v in (wind, rain, snow):
        if v is None or not math.isfinite(v) or v < 0:
            return None
    if gust is None or not math.isfinite(gust) or gust < 0:
        gust = None
    return Reading(wind=wind, gust=gust, rain=rain, snow=snow)


@dataclass
class WeatherBatch:
    hours: dict            # point_key -> {timestamp: row}
    errors: list           # one message per batch that failed

    def reading(self, lat, lon, key):
        hours = self.hours.get(point_key(lat, lon))
        return None if hours is None else reading_at(hours, key)


class WeatherClient:
    def __init__(self, session=None, timeout=30, retries=2, ttl_seconds=1800,
                 clock=time.time, sleep=time.sleep):
        self.session = session or requests.Session()
        self.timeout, self.retries, self.ttl = timeout, retries, ttl_seconds
        self.clock, self.sleep = clock, sleep
        self._cache = {}   # point_key -> (expires_at, days, hours)

    def fetch(self, points, days):
        keys = list(dict.fromkeys(point_key(lat, lon) for lat, lon in points))
        now = self.clock()
        result, todo = {}, []
        for k in keys:
            hit = self._cache.get(k)
            if hit and hit[0] > now and hit[1] >= days:
                result[k] = hit[2]
            else:
                todo.append(k)
        errors = []
        chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
        if chunks:
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(lambda c: self._fetch_chunk(c, days), chunks))
            for chunk, (data, err) in zip(chunks, outcomes):
                if err:
                    errors.append(err)
                    continue
                for k, hours in zip(chunk, data):
                    self._cache[k] = (now + self.ttl, days, hours)
                    result[k] = hours
            if len(errors) == len(chunks) and not result:
                raise WeatherError("Weather service unavailable: " + "; ".join(errors))
        return WeatherBatch(result, errors)

    def _fetch_chunk(self, keys, days):
        params = {"latitude": ",".join(str(k[0]) for k in keys),
                  "longitude": ",".join(str(k[1]) for k in keys),
                  "hourly": ",".join(COLUMNS), "wind_speed_unit": "mph",
                  "precipitation_unit": "inch", "timezone": "GMT", "forecast_days": days}
        last = "unknown error"
        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(URL, params=params, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"HTTP {r.status_code}"
                elif r.status_code != 200:
                    return None, f"HTTP {r.status_code}: {r.text[:120]}"
                else:
                    body = r.json()
                    entries = body if isinstance(body, list) else [body]   # one point -> dict, many -> list
                    if len(entries) != len(keys):
                        return None, f"expected {len(keys)} locations, got {len(entries)}"
                    return [parse_entry(e) for e in entries], None
            except WeatherError as exc:
                return None, str(exc)
            except (requests.RequestException, ValueError) as exc:
                last = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries:
                self.sleep(1 + attempt)
        return None, f"weather request failed after retries ({last})"
