import time, requests
from zoneinfo import ZoneInfo
try:
    ZoneInfo("America/Chicago"); print("tzdata OK")
except Exception as e:
    print("tzdata MISSING ->", type(e).__name__, "- run: pip install tzdata")

URL = "https://api.open-meteo.com/v1/forecast"
def call(lats, lngs, days=3):
    p = {"latitude": ",".join(map(str, lats)), "longitude": ",".join(map(str, lngs)),
         "hourly": "wind_speed_10m,wind_gusts_10m,rain,snowfall",
         "wind_speed_unit": "mph", "precipitation_unit": "inch",
         "timezone": "GMT", "forecast_days": days}
    t = time.time(); r = requests.get(URL, params=p, timeout=30)
    return r, round((time.time() - t) * 1000)

r, ms = call([41.8781, 32.7767], [-87.6298, -96.7970])
print("2 points -> HTTP", r.status_code, ms, "ms")
d = r.json()
print("response is a", type(d).__name__, "of length", len(d) if isinstance(d, list) else "n/a")
first = d[0] if isinstance(d, list) else d
print("keys:", list(first.keys()))
print("units:", first.get("hourly_units"))
print("timezone:", first.get("timezone"), "| hourly rows:", len(first["hourly"]["time"]))
print("first times:", first["hourly"]["time"][:2], "| wind:", first["hourly"]["wind_speed_10m"][:3])
print("nulls in rain:", sum(v is None for v in first["hourly"]["rain"]))

n = 100
lats = [30 + i * 0.1 for i in range(n)]; lngs = [-95 + i * 0.1 for i in range(n)]
r, ms = call(lats, lngs, days=4)
print(f"{n} points -> HTTP {r.status_code}, {ms} ms, body {len(r.content)//1024} KB")
if r.status_code != 200: print(r.text[:300])
r, ms = call([41.8781], [-87.6298], days=16)
print("16 forecast days -> HTTP", r.status_code, "| rows:", len(r.json()["hourly"]["time"]) if r.ok else r.text[:200])
