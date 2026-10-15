"""Hourly risk levels for one checkpoint, for the heatmap slider.

No network access: it reads the forecast batch that plan.py already fetched for scoring.
"""
from datetime import timedelta

from ..core.checkpoints import forecast_key
from ..core.risk import classify

HEAT_HOURS = 48   # slider range: 0..48 hours after departure, so 49 values per checkpoint


def hourly_levels(batch, lat, lon, departure_utc, load_lb, hours=HEAT_HOURS):
    """Risk level (0 Low .. 4 No Travel) at one point for each hour from departure.

    An entry is None where the forecast has no usable data for that hour (shown as Unknown,
    never as Low). Uses the same classify() and load rules as the route scoring.
    """
    levels = []
    for h in range(hours + 1):
        key = forecast_key(departure_utc + timedelta(hours=h))
        reading = batch.reading(lat, lon, key)
        if reading is None:
            levels.append(None)
        else:
            levels.append(int(classify(reading.wind, reading.rain, reading.snow, load_lb).level))
    return levels