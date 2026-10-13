"""Route statistics and the recommendation rule. Pure Python, no Django.

Each checkpoint "owns" the stretch of road around it: from the midpoint with the previous
checkpoint to the midpoint with the next one (the first starts at mile 0, the last ends at the
route's total length). Miles at each risk level, and the distance-weighted average risk, come
from those stretches.

Ranking follows the brief's order of preference, with No Travel miles placed first because a
route that cannot be driven must lose to one that can:
    1. fewest No Travel miles   2. fewest Severe miles   3. fewest High miles
    4. lowest average risk      5. shortest travel time
Differences smaller than a small tolerance count as ties and fall through to the next
criterion, so a trivial weather difference cannot override a much faster route.
"""
from dataclasses import dataclass

from .risk import Risk

MILE_TOLERANCE = 1.0      # miles
RISK_TOLERANCE = 0.02     # points on the 0-4 scale


def segment_lengths(marks, total_miles):
    """Length of road owned by each checkpoint. `marks` are sorted checkpoint mile markers."""
    if not marks:
        return []
    bounds = [0.0]
    for a, b in zip(marks, marks[1:]):
        bounds.append((a + b) / 2)
    bounds.append(float(total_miles))
    return [max(0.0, bounds[i + 1] - bounds[i]) for i in range(len(marks))]


@dataclass(frozen=True)
class RouteStats:
    distance_miles: float
    duration_hours: float
    miles_by_level: dict      # {"Low": 12.0, "Moderate": ...}
    no_travel_miles: float
    severe_miles: float
    high_miles: float
    average_risk: float       # 0 (all Low) to 4 (all No Travel)
    worst_level: Risk
    unknown_miles: float = 0.0   # road with no usable weather; excluded from average_risk


def compute_stats(marks, levels, total_miles, duration_hours):
    """`marks[i]` is the mile marker of checkpoint i and `levels[i]` its Risk."""
    if len(marks) != len(levels):
        raise ValueError("marks and levels must have the same length")
    lengths = segment_lengths(marks, total_miles)
    by_level = {r.label: 0.0 for r in Risk}
    unknown = 0.0
    known_miles = 0.0
    weighted = 0.0
    for length, level in zip(lengths, levels):
        if level is None:            # no usable weather here: never counted as Low
            unknown += length
            continue
        by_level[Risk(level).label] += length
        known_miles += length
        weighted += length * int(level)
    avg = weighted / known_miles if known_miles else 0.0
    return RouteStats(
        distance_miles=float(total_miles),
        duration_hours=float(duration_hours),
        miles_by_level={**{k: round(v, 2) for k, v in by_level.items()}, "Unknown": round(unknown, 2)},
        no_travel_miles=by_level["No Travel"],
        severe_miles=by_level["Severe"],
        high_miles=by_level["High"],
        average_risk=avg,
        worst_level=max((Risk(l) for l in levels if l is not None), default=Risk.LOW),
        unknown_miles=unknown,
    )


CRITERIA = [
    ("no_travel_miles", "fewest No Travel miles", None),   # None = exact: no tolerance
    ("unknown_miles", "fewest miles without weather data", MILE_TOLERANCE),
    ("severe_miles", "fewest Severe miles", MILE_TOLERANCE),
    ("high_miles", "fewest High miles", MILE_TOLERANCE),
    ("average_risk", "lowest average risk", RISK_TOLERANCE),
    ("duration_hours", "shortest travel time", 1 / 60),
]


def bucket(value, tol):
    """Near-ties compare equal. tol=None (No Travel miles) means exact: never a tie."""
    if tol is None:
        return round(value, 6)
    return round(value / tol)


def ranking_key(stats, index=0):
    """Smaller is better. Values are bucketed by tolerance so near-ties compare equal."""
    return tuple(bucket(getattr(stats, attr), tol) for attr, _, tol in CRITERIA) + (
        round(stats.distance_miles, 1), index)


def recommend(stats_list):
    """Return (best_index, order, explanation, all_blocked)."""
    if not stats_list:
        raise ValueError("no routes to rank")
    order = sorted(range(len(stats_list)), key=lambda i: ranking_key(stats_list[i], i))
    best = order[0]
    all_blocked = all(s.no_travel_miles > 0 for s in stats_list)

    if len(order) == 1:
        explanation = "Only one route was available."
    else:
        runner_up = order[1]
        a, b = stats_list[best], stats_list[runner_up]
        explanation = "Best overall: tied with the alternatives on weather risk, so the shortest travel time wins."
        for attr, text, tol in CRITERIA:
            va, vb = getattr(a, attr), getattr(b, attr)
            if bucket(va, tol) != bucket(vb, tol):
                if attr == "duration_hours":
                    explanation = f"Weather risk is similar across routes, so the {text} wins ({va:.1f} h vs {vb:.1f} h)."
                elif attr == "no_travel_miles":
                    explanation = f"Chosen for the {text} ({va:.1f} vs {vb:.1f} miles)."
                elif attr == "average_risk":
                    explanation = f"Chosen for the {text} ({va:.2f} vs {vb:.2f})."
                else:
                    explanation = f"Chosen for the {text} ({va:.0f} vs {vb:.0f} miles)."
                break
    if all_blocked:
        explanation = ("Every route passes through No Travel conditions at the chosen departure time. "
                       "This one has the least; consider departing at another time. " + explanation)
    return best, order, explanation, all_blocked
