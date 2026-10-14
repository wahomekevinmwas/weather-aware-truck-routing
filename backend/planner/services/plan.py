"""Plan service: one trip request in, scored and ranked routes out.

Orchestration only: the rules live in planner.core, and all network access goes through the
injected clients, so everything here is testable offline.
"""
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.checkpoints import MERGE_MILES, SPACINGS, build_checkpoints, departure_to_utc, forecast_key
from ..core.geo import haversine, simplify
from ..core.recommend import compute_stats, recommend
from ..core.risk import classify
from .geocoding import GeocodeError
from .routing import RoutingError, build_route_options
from .weather import MAX_FORECAST_DAYS, WeatherError, days_needed

logger = logging.getLogger(__name__)

MAX_CHECKPOINTS_PER_ROUTE = 60       # decision 16(a): above this, spacing is raised
DEFAULT_SPACING = 25
MAX_LOAD_LB = 200_000
MIN_TRIP_MILES = 1.0
GEOMETRY_TOLERANCE_MILES = 0.5       # polyline simplification for the browser
EXAMPLE_DEPARTURE = "2026-10-16T08:00"


class PlanError(Exception):
    """A problem the user can act on; the view turns it into a JSON error."""

    def __init__(self, message, code="invalid_input", status=400, field=None):
        super().__init__(message)
        self.message, self.code, self.status, self.field = message, code, status, field


@dataclass(frozen=True)
class PlanRequest:
    origin: str
    destination: str
    departure: datetime      # naive: local time at the origin
    load_lb: float
    spacing: int


def _text_field(payload, name, label):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"Enter {label}.", field=name)
    return value.strip()


def _departure_field(payload):
    raw = payload.get("departure")
    if not isinstance(raw, str):
        raise PlanError(f"Enter a departure date and time, like {EXAMPLE_DEPARTURE}.", field="departure")
    try:
        value = datetime.fromisoformat(raw.strip())
    except ValueError:
        raise PlanError(f"Could not read the departure time. Use a local date and time like {EXAMPLE_DEPARTURE}.",
                        field="departure") from None
    if value.tzinfo is not None:
        raise PlanError("Enter the departure as local time at the origin, without a UTC offset or 'Z'.",
                        field="departure")
    return value


def _load_field(payload):
    raw = payload.get("load_lb")
    if raw is None or isinstance(raw, bool):
        raise PlanError("Enter the load weight in pounds.", field="load_lb")
    try:
        load = float(raw)
    except (TypeError, ValueError):
        raise PlanError("Load weight must be a number of pounds.", field="load_lb") from None
    if not math.isfinite(load) or load < 0 or load > MAX_LOAD_LB:
        raise PlanError(f"Load weight must be between 0 and {MAX_LOAD_LB:,} lb.", field="load_lb")
    return load


def _spacing_field(payload):
    raw = payload.get("spacing")
    if raw is None:
        return DEFAULT_SPACING
    if isinstance(raw, bool) or raw not in SPACINGS:
        raise PlanError(f"Checkpoint spacing must be one of {', '.join(map(str, SPACINGS))} miles.", field="spacing")
    return int(raw)


def parse_request(payload):
    if not isinstance(payload, dict):
        raise PlanError("Send the trip as a JSON object.")
    return PlanRequest(
        origin=_text_field(payload, "origin", "an origin"),
        destination=_text_field(payload, "destination", "a destination"),
        departure=_departure_field(payload),
        load_lb=_load_field(payload),
        spacing=_spacing_field(payload),
    )


def checkpoint_count(distance_miles, spacing):
    """How many checkpoints build_checkpoints will produce (same marks, no geometry needed)."""
    n, mark = 2, float(spacing)          # origin and destination
    while mark < distance_miles - MERGE_MILES:
        n += 1
        mark += spacing
    return n


def choose_spacing(requested, distances):
    """Smallest spacing >= requested that keeps the longest route within the checkpoint budget."""
    longest = max(distances)
    for spacing in SPACINGS:
        if spacing < requested:
            continue
        if spacing == SPACINGS[-1] or checkpoint_count(longest, spacing) <= MAX_CHECKPOINTS_PER_ROUTE:
            return spacing
    return SPACINGS[-1]


def _check_forecast_window(departure_utc, today):
    days_ahead = (departure_utc.date() - today).days
    if days_ahead < 0:
        raise PlanError("That departure time has already passed. Forecasts start today, "
                        "so choose a departure from today onward.", field="departure")
    if days_ahead >= MAX_FORECAST_DAYS:
        raise PlanError(f"Weather forecasts cover {MAX_FORECAST_DAYS} days from today. "
                        "Choose a departure within that window.", field="departure")


def _place_json(place):
    return {"name": place.name, "lat": round(place.lat, 5), "lon": round(place.lon, 5)}


def _checkpoint_json(cp, reading, assessment, tz):
    known = assessment is not None
    return {
        "mile": round(cp.mile, 1),
        "lat": round(cp.lat, 5),
        "lon": round(cp.lon, 5),
        "eta_utc": cp.eta.isoformat(),
        "eta_local": cp.eta.astimezone(tz).isoformat(timespec="minutes"),
        "level": assessment.level.label if known else "Unknown",
        "level_value": int(assessment.level) if known else None,
        "wind_mph": reading.wind if known else None,
        "gust_mph": reading.gust if known else None,
        "rain_in_hr": reading.rain if known else None,
        "snow_in_hr": reading.snow if known else None,
        "reasons": list(assessment.reasons) if known else ["No usable weather data for this checkpoint"],
    }


def _stats_json(stats, any_known):
    return {
        "distance_miles": round(stats.distance_miles, 1),
        "duration_hours": round(stats.duration_hours, 2),
        "miles_by_level": stats.miles_by_level,
        "no_travel_miles": round(stats.no_travel_miles, 1),
        "severe_miles": round(stats.severe_miles, 1),
        "high_miles": round(stats.high_miles, 1),
        "average_risk": round(stats.average_risk, 2),
        "worst_level": stats.worst_level.label if any_known else "Unknown",
        "unknown_miles": round(stats.unknown_miles, 1),
    }


class PlanService:
    def __init__(self, geocoder, router, weather, build_options=build_route_options, now=None):
        self.geocoder, self.router, self.weather = geocoder, router, weather
        self._build_options = build_options
        self._now = now or (lambda: datetime.now(timezone.utc))

    def plan(self, payload):
        req = parse_request(payload)
        today = self._now().astimezone(timezone.utc).date()
        notes = []

        origin = self._place(req.origin, "origin")
        destination = self._place(req.destination, "destination")
        if haversine((origin.lat, origin.lon), (destination.lat, destination.lon)) < MIN_TRIP_MILES:
            raise PlanError("Origin and destination are the same place.", field="destination")

        departure_utc, tz_name = self._departure(req.departure, origin, notes)
        _check_forecast_window(departure_utc, today)

        routes = self._routes(origin, destination, notes)
        spacing = choose_spacing(req.spacing, [r.distance_miles for r in routes])
        if spacing != req.spacing:
            longest = max(r.distance_miles for r in routes)
            notes.append(f"Checkpoint spacing was raised from {req.spacing} to {spacing} miles because the longest "
                         f"route ({longest:,.0f} mi) would need more than {MAX_CHECKPOINTS_PER_ROUTE} checkpoints "
                         f"at {req.spacing} miles. This keeps the weather lookup fast.")

        try:
            all_cps = [build_checkpoints(r.points, r.distance_miles, r.duration_hours, spacing, departure_utc)
                       for r in routes]
        except ValueError as exc:
            raise PlanError(f"A route could not be sampled for weather ({exc}).",
                            code="routing_failed", status=502) from exc

        days, truncated = days_needed(today, max(cps[-1].eta for cps in all_cps))
        if truncated:
            notes.append(f"The {MAX_FORECAST_DAYS}-day forecast window ends before this trip does, "
                         "so checkpoints after it are shown as Unknown.")
        batch = self._weather(all_cps, days, notes)

        scored = []
        for route, cps in zip(routes, all_cps):
            readings = [batch.reading(cp.lat, cp.lon, forecast_key(cp.eta)) for cp in cps]
            assessments = [None if rd is None else classify(rd.wind, rd.rain, rd.snow, req.load_lb)
                           for rd in readings]
            levels = [a.level if a else None for a in assessments]
            stats = compute_stats([cp.mile for cp in cps], levels, route.distance_miles, route.duration_hours)
            scored.append((route, cps, readings, assessments, levels, stats))

        best, order, explanation, all_blocked = recommend([row[5] for row in scored])

        for i, (_, cps, _, _, levels, stats) in enumerate(scored):
            missing = sum(level is None for level in levels)
            if missing:
                notes.append(f"Route {i + 1}: weather was unavailable for {missing} of {len(cps)} checkpoints "
                             f"(about {stats.unknown_miles:,.0f} mi). That stretch is shown as Unknown and left out "
                             "of the average risk.")
        if scored[best][5].unknown_miles > 0:
            notes.append("The recommended route has stretches with no weather data, so its risk may be understated.")

        tz = ZoneInfo(tz_name)
        route_json = []
        for i, (route, cps, readings, assessments, levels, stats) in enumerate(scored):
            route_json.append({
                "index": i,
                "source": route.source,
                "recommended": i == best,
                "rank": order.index(i) + 1,
                "distance_miles": round(route.distance_miles, 1),
                "duration_hours": round(route.duration_hours, 2),
                "arrival_utc": cps[-1].eta.isoformat(),
                "arrival_local": cps[-1].eta.astimezone(tz).isoformat(timespec="minutes"),
                "stats": _stats_json(stats, any(level is not None for level in levels)),
                "checkpoints": [_checkpoint_json(cp, rd, a, tz) for cp, rd, a in zip(cps, readings, assessments)],
                "geometry": [[round(p[0], 5), round(p[1], 5)]
                             for p in simplify(route.points, GEOMETRY_TOLERANCE_MILES)],
            })

        return {
            "origin": _place_json(origin),
            "destination": _place_json(destination),
            "departure": {"local": req.departure.isoformat(timespec="minutes"),
                          "utc": departure_utc.isoformat(), "timezone": tz_name},
            "load_lb": req.load_lb,
            "spacing": {"requested": req.spacing, "used": spacing},
            "routes": route_json,
            "recommended_index": best,
            "explanation": explanation,
            "all_blocked": all_blocked,
            "notes": notes,
        }

    def _place(self, text, field):
        try:
            return self.geocoder.geocode(text)
        except GeocodeError as exc:
            raise PlanError(str(exc), code="geocode_error", field=field) from exc

    def _departure(self, local_departure, origin, notes):
        """Departure is typed as local time at the origin (decision). Falls back to UTC, with a note."""
        tz_name = "UTC"
        try:
            tz_name = self.geocoder.timezone(origin.lat, origin.lon)
        except Exception as exc:    # best effort: a failed time zone lookup must not sink the plan
            logger.warning("time zone lookup failed: %s", exc)
            notes.append("Could not determine the origin's time zone, so the departure time was read as UTC.")
        try:
            return departure_to_utc(local_departure, tz_name), tz_name
        except ZoneInfoNotFoundError:
            notes.append(f"Unknown time zone {tz_name!r}, so the departure time was read as UTC.")
            return departure_to_utc(local_departure, "UTC"), "UTC"

    def _routes(self, origin, destination, notes):
        try:
            options = self._build_options(self.router, (origin.lat, origin.lon), (destination.lat, destination.lon))
        except RoutingError as exc:
            raise PlanError(f"Routing failed: {exc}", code="routing_failed", status=502) from exc
        notes.extend(options.notes)
        return options.routes

    def _weather(self, all_cps, days, notes):
        points = [(cp.lat, cp.lon) for cps in all_cps for cp in cps]
        try:
            batch = self.weather.fetch(points, days)
        except WeatherError as exc:
            logger.warning("weather unavailable: %s", exc)
            raise PlanError("The weather service is unavailable right now, so the routes can't be scored. "
                            "Try again in a minute.", code="weather_unavailable", status=503) from exc
        if batch.errors:
            notes.append("Weather data could not be loaded for some checkpoints "
                         f"({len(batch.errors)} request(s) failed); those checkpoints are shown as Unknown.")
        return batch
