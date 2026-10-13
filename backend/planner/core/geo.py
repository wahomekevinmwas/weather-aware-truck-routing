"""Pure geometry helpers for routes. No Django, no network."""
import bisect
import math

R_MI = 3958.8
MI_PER_DEG = 69.172   # used only for local flat-earth distances when simplifying


def haversine(p, q):
    la1, lo1, la2, lo2 = (math.radians(v) for v in (p[0], p[1], q[0], q[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R_MI * math.asin(math.sqrt(h))


def bearing(p, q):
    la1, lo1, la2, lo2 = (math.radians(v) for v in (p[0], p[1], q[0], q[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return math.degrees(math.atan2(y, x)) % 360


def destination(p, brg, miles):
    la1, lo1, b, d = math.radians(p[0]), math.radians(p[1]), math.radians(brg), miles / R_MI
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1),
                           math.cos(d) - math.sin(la1) * math.sin(la2))
    return (math.degrees(la2), math.degrees(lo2))


def cumulative_miles(points):
    """cum[i] = miles along the route from the first point to point i."""
    cum = [0.0]
    for a, b in zip(points, points[1:]):
        cum.append(cum[-1] + haversine(a, b))
    return cum


def point_at_mile(points, cum, mile):
    """Interpolated (lat, lon) at a distance along the route; clamped to the ends."""
    if mile <= 0:
        return points[0]
    if mile >= cum[-1]:
        return points[-1]
    i = bisect.bisect_right(cum, mile)
    seg = cum[i] - cum[i - 1]
    t = (mile - cum[i - 1]) / seg if seg > 0 else 0.0
    a, b = points[i - 1], points[i]
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def simplify(points, tolerance_miles):
    """Douglas-Peucker. Keeps the shape within tolerance; used for the copy sent to the browser."""
    n = len(points)
    if n < 3:
        return list(points)
    lat0 = math.radians(sum(p[0] for p in points) / n)
    kx, ky = math.cos(lat0) * MI_PER_DEG, MI_PER_DEG
    xy = [(p[1] * kx, p[0] * ky) for p in points]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = xy[a]
        dx, dy = xy[b][0] - ax, xy[b][1] - ay
        seg2 = dx * dx + dy * dy
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            if seg2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best:
                best, idx = d, i
        if best > tolerance_miles:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(points, keep) if k]


def share_far_from(candidate, others, miles=5.0, samples=60):
    """Fraction of sampled candidate points that are more than `miles` from every other route."""
    others_s = [o[::max(1, len(o) // 1500)] for o in others]
    idx = [round(i * (len(candidate) - 1) / (samples - 1)) for i in range(samples)]
    far = 0
    for i in idx:
        p = candidate[i]
        if all(haversine(p, q) > miles for o in others_s for q in o):
            far += 1
    return far / samples


def side_waypoint(points, cum, fraction, side, offset_miles):
    """A point `offset_miles` to the left or right of the route, `fraction` of the way along it."""
    if side not in ("left", "right"):
        raise ValueError("side must be 'left' or 'right'")
    total = cum[-1]
    at = total * fraction
    before = point_at_mile(points, cum, max(0.0, at - 10))
    after = point_at_mile(points, cum, min(total, at + 10))
    centre = point_at_mile(points, cum, at)
    brg = (bearing(before, after) + (90 if side == "right" else -90)) % 360
    return destination(centre, brg, offset_miles)
