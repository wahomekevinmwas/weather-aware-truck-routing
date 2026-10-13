"""Weather risk classification for one checkpoint. Pure Python, no Django.

Thresholds and load rules come straight from the assessment brief. Where the brief's ranges
overlap at a boundary (e.g. 0.25 in/hr appears in both Moderate and High) the LOWER bound is
inclusive, so 0.25 in/hr is High. The No Travel limits are applied exactly as written:
wind >= 55 mph, rain > 1.00 in/hr, snow > 3.0 in/hr.
"""
import math
from dataclasses import dataclass, field
from enum import IntEnum


class Risk(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self):
        return self.name.replace("_", " ").title()


def wind_level(mph):
    if mph >= 55:
        return Risk.NO_TRAVEL
    if mph >= 45:
        return Risk.SEVERE
    if mph >= 35:
        return Risk.HIGH
    if mph >= 25:
        return Risk.MODERATE
    return Risk.LOW


def rain_level(in_per_hr):
    if in_per_hr > 1.00:
        return Risk.NO_TRAVEL
    if in_per_hr >= 0.50:
        return Risk.SEVERE
    if in_per_hr >= 0.25:
        return Risk.HIGH
    if in_per_hr >= 0.10:
        return Risk.MODERATE
    return Risk.LOW


def snow_level(in_per_hr):
    if in_per_hr > 3.0:
        return Risk.NO_TRAVEL
    if in_per_hr >= 2.0:
        return Risk.SEVERE
    if in_per_hr >= 1.0:
        return Risk.HIGH
    if in_per_hr >= 0.5:
        return Risk.MODERATE
    return Risk.LOW


@dataclass(frozen=True)
class Assessment:
    level: Risk
    wind: Risk
    rain: Risk
    snow: Risk
    reasons: list = field(default_factory=list)


def apply_load_rules(wind_mph, load_lb, level):
    """Load rules apply to wind only:
    45-54 mph with a load over 30,000 lb -> No Travel; 35-44 mph with a load over 40,000 lb -> Severe.
    (Wind of 55 mph or more is already No Travel for any load.)
    """
    if 45 <= wind_mph < 55 and load_lb > 30000:
        return Risk.NO_TRAVEL, f"Wind {wind_mph:g} mph with a {load_lb:,.0f} lb load (over 30,000 lb) is No Travel"
    if 35 <= wind_mph < 45 and load_lb > 40000:
        return max(level, Risk.SEVERE), f"Wind {wind_mph:g} mph with a {load_lb:,.0f} lb load (over 40,000 lb) is Severe"
    return level, None


def classify(wind_mph, rain_in_hr, snow_in_hr, load_lb):
    """Risk at one checkpoint: the worst of wind (after load rules), rain and snow."""
    for name, value in (("wind", wind_mph), ("rain", rain_in_hr), ("snow", snow_in_hr), ("load", load_lb)):
        if value is None or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite, non-negative number, got {value!r}")

    w = wind_level(wind_mph)
    reasons = []
    w_loaded, load_reason = apply_load_rules(wind_mph, load_lb, w)
    if load_reason:
        reasons.append(load_reason)
    r = rain_level(rain_in_hr)
    s = snow_level(snow_in_hr)

    if w_loaded >= Risk.MODERATE and not load_reason:
        reasons.append(f"Wind {wind_mph:g} mph is {w_loaded.label}")
    if r >= Risk.MODERATE:
        reasons.append(f"Rain {rain_in_hr:g} in/hr is {r.label}")
    if s >= Risk.MODERATE:
        reasons.append(f"Snow {snow_in_hr:g} in/hr is {s.label}")

    return Assessment(level=max(w_loaded, r, s), wind=w_loaded, rain=r, snow=s, reasons=reasons)
