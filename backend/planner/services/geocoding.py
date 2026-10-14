"""Place name -> coordinates, and origin coordinates -> IANA time zone.

Order of preference for names: Nominatim (US only; best with 'City, ST'), then the Open-Meteo
geocoder as a fallback (handles plain city names, not street addresses). Plain 'lat,lon' input
skips the network entirely. Results are cached, and Nominatim calls are spaced at least 1.1 s
apart to respect its usage policy.
"""
import re
import threading
import time
from dataclasses import dataclass

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "fs-weather-routing-assessment/0.1"
NOMINATIM_MIN_INTERVAL = 1.1     # seconds between Nominatim requests (their policy: max 1 per second)
CACHE_TTL = 24 * 3600
MAX_QUERY_LENGTH = 200
COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$")


class GeocodeError(Exception):
    """A place or time zone could not be resolved. The message is safe to show to the user."""


class _ServiceFailure(Exception):
    """Internal: the remote service failed (as opposed to answering 'no such place')."""


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float
    source: str    # "coordinates", "nominatim" or "open-meteo"


class GeocodingClient:
    def __init__(self, session=None, timeout=20, retries=1, ttl_seconds=CACHE_TTL,
                 clock=time.monotonic, sleep=time.sleep):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.ttl = ttl_seconds
        self.clock = clock
        self.sleep = sleep
        self._cache = {}
        self._cache_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._last_nominatim = float("-inf")

    # ---- public API -------------------------------------------------------------------------
    def geocode(self, query):
        text = " ".join((query or "").split())
        if not text:
            raise GeocodeError("Please enter a place.")
        if len(text) > MAX_QUERY_LENGTH:
            raise GeocodeError("That place name is too long.")

        coords = self._parse_coordinates(text)
        if coords:
            return coords

        key = ("place", text.lower())
        hit = self._cache_get(key)
        if hit:
            return hit

        failures, place = 0, None
        for finder in (self._nominatim, self._open_meteo):
            try:
                place = finder(text)
            except _ServiceFailure:
                failures += 1
                continue
            if place:
                break

        if place is None:
            if failures == 2:
                raise GeocodeError("The geocoding services are unavailable right now. "
                                   "Try again in a minute, or enter coordinates as 'lat,lon'.")
            note = " A geocoding service was unavailable, so try again shortly." if failures else ""
            raise GeocodeError(f"Could not find '{text}' in the United States. "
                               f"Try 'City, ST' or coordinates as 'lat,lon'.{note}")
        self._cache_set(key, place)
        return place

    def timezone(self, lat, lon):
        """IANA time zone name at a point, e.g. 'America/Chicago' (Open-Meteo timezone=auto)."""
        key = ("tz", round(lat, 1), round(lon, 1))
        hit = self._cache_get(key)
        if hit:
            return hit
        try:
            data = self._get(OPEN_METEO_FORECAST_URL, {
                "latitude": lat, "longitude": lon, "hourly": "wind_speed_10m",
                "forecast_days": 1, "timezone": "auto"})
        except _ServiceFailure:
            raise GeocodeError("The time zone service is unavailable right now. Please try again shortly.")
        name = data.get("timezone") if isinstance(data, dict) else None
        if not name:
            raise GeocodeError("Could not determine the time zone at the origin.")
        self._cache_set(key, name)
        return name

    # ---- finders ------------------------------------------------------------------------------
    @staticmethod
    def _parse_coordinates(text):
        m = COORD_RE.match(text)
        if not m:
            return None
        lat, lon = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise GeocodeError("Coordinates out of range: latitude must be -90 to 90 and longitude -180 to 180.")
        return Place(f"{lat:.4f}, {lon:.4f}", lat, lon, "coordinates")

    def _nominatim(self, text):
        self._wait_for_nominatim()
        data = self._get(NOMINATIM_URL, {"q": text, "format": "jsonv2", "limit": 1, "countrycodes": "us"})
        if not isinstance(data, list) or not data:
            return None
        try:
            first = data[0]
            return Place(first["display_name"], float(first["lat"]), float(first["lon"]), "nominatim")
        except (KeyError, TypeError, ValueError):
            return None

    def _open_meteo(self, text):
        data = self._get(OPEN_METEO_GEOCODE_URL, {"name": text, "count": 5, "language": "en", "format": "json"})
        for item in (data.get("results") or []) if isinstance(data, dict) else []:
            if item.get("country_code") != "US":
                continue
            try:
                label = ", ".join(p for p in (item.get("name"), item.get("admin1")) if p) or text
                return Place(label, float(item["latitude"]), float(item["longitude"]), "open-meteo")
            except (KeyError, TypeError, ValueError):
                continue
        return None

    # ---- plumbing -----------------------------------------------------------------------------
    def _wait_for_nominatim(self):
        with self._rate_lock:
            wait = self._last_nominatim + NOMINATIM_MIN_INTERVAL - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._last_nominatim = self.clock()

    def _get(self, url, params):
        last = "unknown error"
        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
            except requests.RequestException as exc:
                last = type(exc).__name__
            else:
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"HTTP {r.status_code}"
                elif r.status_code != 200:
                    raise _ServiceFailure(f"HTTP {r.status_code}")
                else:
                    try:
                        return r.json()
                    except ValueError:
                        last = "invalid JSON"
            if attempt < self.retries:
                self.sleep(0.5 * (attempt + 1))
        raise _ServiceFailure(last)

    def _cache_get(self, key):
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and hit[0] > self.clock():
                return hit[1]
            self._cache.pop(key, None)
            return None

    def _cache_set(self, key, value):
        with self._cache_lock:
            self._cache[key] = (self.clock() + self.ttl, value)
