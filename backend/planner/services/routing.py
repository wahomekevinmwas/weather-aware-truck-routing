"""Routing: fetch up to three routes. Pure logic is separate from the HTTP client so it can be tested offline."""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import requests

from planner.core.geo import cumulative_miles, share_far_from, side_waypoint

M_PER_MILE = 1609.344

# A third route is accepted only if it is genuinely different and not absurdly long.
MAX_DISTANCE_RATIO = 1.3   # vs the shortest route found
MAX_DURATION_RATIO = 1.5   # vs the fastest route found
MIN_FAR_SHARE = 0.25       # share of the route more than FAR_MILES from every chosen route
FAR_MILES = 5.0
# (fraction of the way along the base route, side, offset in miles)
CANDIDATE_PLANS = [(0.5, "left", 80), (0.5, "right", 80), (0.35, "left", 50), (0.65, "right", 50)]
MAX_OFFSET_SHARE = 0.25    # offset never exceeds this share of the trip length


class RoutingError(Exception):
    pass


@dataclass(frozen=True)
class RawRoute:
    distance_miles: float
    duration_hours: float
    points: list                 # [(lat, lon), ...] full detail
    source: str = "osrm"         # "osrm" or "waypoint"


@dataclass
class RouteOptions:
    routes: list
    notes: list = field(default_factory=list)


class OsrmClient:
    """Public OSRM demo server: free and car-profile only, not meant for heavy traffic. Hence the cache."""
    BASE = "https://router.project-osrm.org/route/v1/driving/"

    def __init__(self, base_url=BASE, session=None, timeout=60, retries=2):
        self.base_url = base_url
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "fs-weather-routing-assessment/0.1")
        self.timeout = timeout
        self.retries = retries
        self._cache = {}

    def route(self, points, alternatives=False):
        key = (tuple((round(a, 4), round(b, 4)) for a, b in points), bool(alternatives))
        if key in self._cache:
            return self._cache[key]
        url = self.base_url + ";".join(f"{lon},{lat}" for lat, lon in points)
        params = {"overview": "full", "geometries": "geojson", "steps": "false",
                  "alternatives": "3" if alternatives else "false"}
        last = "unknown error"
        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"routing server returned HTTP {r.status_code}"
                else:
                    data = r.json()
                    if data.get("code") != "Ok":
                        raise RoutingError(f"No route: {data.get('code')} {data.get('message', '')}".strip())
                    result = [self._parse(x) for x in data["routes"]]
                    self._cache[key] = result
                    return result
            except (requests.RequestException, ValueError) as exc:
                last = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries:
                time.sleep(1 + attempt)
        raise RoutingError(f"Routing service unavailable ({last})")

    @staticmethod
    def _parse(route):
        coords = route["geometry"]["coordinates"]
        return RawRoute(distance_miles=route["distance"] / M_PER_MILE,
                        duration_hours=route["duration"] / 3600,
                        points=[(lat, lon) for lon, lat in coords])


def build_route_options(client, origin, destination, want=3):
    notes = []
    routes = list(client.route([origin, destination], alternatives=True))[:want]
    if not routes:
        raise RoutingError("No route found between those places")
    if len(routes) >= want:
        return RouteOptions(routes, notes)

    shortest = min(r.distance_miles for r in routes)
    fastest = min(r.duration_hours for r in routes)
    base = routes[0]
    cum = cumulative_miles(base.points)

    def fetch(plan):
        fraction, side, offset = plan
        via = side_waypoint(base.points, cum, fraction, side, min(offset, MAX_OFFSET_SHARE * cum[-1]))
        try:
            got = client.route([origin, via, destination], alternatives=False)
        except RoutingError:
            return None
        return replace(got[0], source="waypoint") if got else None

    with ThreadPoolExecutor(max_workers=4) as pool:
        candidates = [c for c in pool.map(fetch, CANDIDATE_PLANS) if c is not None]

    while len(routes) < want and candidates:
        scored = []
        for c in candidates:
            if c.distance_miles > MAX_DISTANCE_RATIO * shortest or c.duration_hours > MAX_DURATION_RATIO * fastest:
                continue
            far = share_far_from(c.points, [r.points for r in routes], FAR_MILES)
            if far >= MIN_FAR_SHARE:
                scored.append((far, c))
        if not scored:
            break
        _, best = max(scored, key=lambda t: t[0])      # first maximum wins: deterministic
        routes.append(best)
        candidates = [c for c in candidates if c is not best]
        notes.append(f"Route {len(routes)} was built through an off-route waypoint because the routing "
                     f"service returned fewer than {want} alternatives.")

    if len(routes) < want:
        notes.append(f"Only {len(routes)} genuinely different route(s) could be found; showing what exists.")
    return RouteOptions(routes, notes)
