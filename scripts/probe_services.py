import math
import time
import requests

UA = {"User-Agent": "fs-weather-routing-assessment/0.1"}
R_MI = 3958.8
OSRM = "https://router.project-osrm.org/route/v1/driving/"


def hav(p, q):
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


def osrm(points, **params):
    path = ";".join(f"{lon},{lat}" for lat, lon in points)
    q = {"overview": "full", "geometries": "geojson", "steps": "false"}
    q.update(params)
    r = requests.get(OSRM + path, params=q, timeout=60)
    time.sleep(1)
    return r


def latlon(route):
    return [(lat, lon) for lon, lat in route["geometry"]["coordinates"]]


def halfway(pts):
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + hav(a, b))
    half = cum[-1] / 2
    return next(k for k, c in enumerate(cum) if c >= half), cum[-1]


def share_near(candidate, base, miles=5.0, samples=60):
    base_s = base[::max(1, len(base) // 1500)]
    idx = [round(i * (len(candidate) - 1) / (samples - 1)) for i in range(samples)]
    near = sum(1 for i in idx if min(hav(candidate[i], b) for b in base_s) <= miles)
    return near / samples


print("=== 1. Geocoding ===")
for q in ["Chicago", "Denver, CO", "Atlanta, Georgia", "1600 Pennsylvania Ave NW, Washington"]:
    print(f"\nquery: {q!r}")
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": q, "count": 3, "language": "en", "format": "json"}, timeout=30)
    d = r.json()
    res = d.get("results") or []
    print(f"  open-meteo: HTTP {r.status_code}, {len(res)} results, keys: {list(res[0].keys()) if res else d}")
    for x in res[:2]:
        print("    ", x.get("name"), x.get("admin1"), x.get("country_code"), x.get("latitude"), x.get("longitude"))
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params={"q": q, "format": "jsonv2", "limit": 3, "countrycodes": "us"},
                     headers=UA, timeout=30)
    time.sleep(1.1)
    res = r.json() if r.ok else []
    print(f"  nominatim: HTTP {r.status_code}, {len(res)} results, keys: {list(res[0].keys()) if res else r.text[:100]}")
    for x in res[:2]:
        print("    ", x.get("display_name"), x.get("lat"), x.get("lon"), x.get("type"))

print("\n=== 2. Origin time zone via Open-Meteo timezone=auto ===")
r = requests.get("https://api.open-meteo.com/v1/forecast",
                 params={"latitude": 41.8781, "longitude": -87.6298, "hourly": "wind_speed_10m",
                         "forecast_days": 1, "timezone": "auto"}, timeout=30)
d = r.json()
print("HTTP", r.status_code, "| timezone:", d.get("timezone"), "| utc_offset_seconds:", d.get("utc_offset_seconds"))

print("\n=== 3. OSRM shape and third-route waypoint tests ===")
TRIPS = {"LA-Houston": ((34.0522, -118.2437), (29.7604, -95.3698)),
         "Atlanta-Boston": ((33.7490, -84.3880), (42.3601, -71.0589))}
for name, (a, b) in TRIPS.items():
    r = osrm([a, b], alternatives="3")
    d = r.json()
    print(f"\n{name}: HTTP {r.status_code}, code={d.get('code')}, body {len(r.content)//1024} KB, top keys {list(d.keys())}")
    if d.get("code") != "Ok":
        print(d)
        continue
    print("route keys:", list(d["routes"][0].keys()))
    print("leg keys:", list(d["routes"][0]["legs"][0].keys()))
    print("waypoint keys:", list(d["waypoints"][0].keys()))
    for i, rt in enumerate(d["routes"]):
        print(f"  route {i}: {rt['distance']/1609.344:.1f} mi, {rt['duration']/3600:.2f} h, {len(latlon(rt))} points")
    base = d["routes"][0]
    base_pts = latlon(base)
    i, total = halfway(base_pts)
    k = max(1, min(20, i, len(base_pts) - 1 - i))
    brg = bearing(base_pts[i - k], base_pts[i + k])
    mid = base_pts[i]
    print(f"  waypoint tests from midpoint {mid[0]:.3f},{mid[1]:.3f} (polyline length {total:.0f} mi)")
    for side, delta in (("left", -90), ("right", 90)):
        for off in (40, 80):
            via = destination(mid, (brg + delta) % 360, off)
            rr = osrm([a, via, b])
            dd = rr.json()
            if dd.get("code") != "Ok":
                print(f"   {side} {off} mi: code={dd.get('code')} {dd.get('message', '')}")
                continue
            c = dd["routes"][0]
            cp = latlon(c)
            print(f"   {side} {off:>2} mi: {c['distance']/1609.344:7.1f} mi ({c['distance']/base['distance']:.2f}x), "
                  f"{c['duration']/3600:5.2f} h ({c['duration']/base['duration']:.2f}x), {len(cp)} pts, "
                  f"within 5 mi of base: {share_near(cp, base_pts):.0%}")
