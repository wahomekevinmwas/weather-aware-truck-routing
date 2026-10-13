"""Checkpoints along a route, with ETAs. Pure Python: no Django, no network."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .geo import cumulative_miles, point_at_mile

SPACINGS = (10, 25, 50)   # miles; the brief's three options
MERGE_MILES = 1.0         # a regular checkpoint this close to the destination is replaced by it


@dataclass(frozen=True)
class Checkpoint:
    mile: float           # miles from the origin, on the routing service's distance scale
    lat: float
    lon: float
    eta: datetime         # timezone-aware, UTC


def departure_to_utc(local_departure, tz_name):
    """Departure is typed as local time at the origin (no UTC offset); return it as aware UTC."""
    if local_departure.tzinfo is not None:
        raise ValueError("departure must be local time without a UTC offset")
    return local_departure.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)


def forecast_key(eta):
    """Open-Meteo hourly timestamp (GMT) nearest to `eta`; exactly :30 rounds up."""
    if eta.tzinfo is None:
        raise ValueError("eta must be timezone-aware")
    return (eta.astimezone(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:00")


def build_checkpoints(points, distance_miles, duration_hours, spacing, departure_utc):
    """Checkpoints at the origin, every `spacing` miles, and the destination.

    ETA is proportional to distance: the routing service gives one total duration per route,
    so average speed is treated as constant along it.
    """
    if spacing not in SPACINGS:
        raise ValueError(f"spacing must be one of {SPACINGS}, got {spacing!r}")
    if len(points) < 2:
        raise ValueError("a route needs at least two points")
    if not distance_miles > 0:
        raise ValueError("distance_miles must be positive")
    if duration_hours < 0:
        raise ValueError("duration_hours must not be negative")
    if departure_utc.tzinfo is None:
        raise ValueError("departure_utc must be timezone-aware")
    departure_utc = departure_utc.astimezone(timezone.utc)

    cum = cumulative_miles(points)
    if cum[-1] <= 0:
        raise ValueError("route geometry has zero length")
    scale = distance_miles / cum[-1]          # routing-service miles per geometry mile

    marks = [0.0]
    m = float(spacing)
    while m < distance_miles - MERGE_MILES:
        marks.append(m)
        m += spacing
    marks.append(float(distance_miles))

    out = []
    for mark in marks:
        lat, lon = point_at_mile(points, cum, mark / scale)
        eta = departure_utc + timedelta(hours=duration_hours * mark / distance_miles)
        out.append(Checkpoint(mark, lat, lon, eta))
    return out
