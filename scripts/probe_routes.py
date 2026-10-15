import requests
PAIRS = {
    "Chicago-Dallas": ((41.8781, -87.6298), (32.7767, -96.7970)),
    "Denver-Seattle": ((39.7392, -104.9903), (47.6062, -122.3321)),
    "Atlanta-Boston": ((33.7490, -84.3880), (42.3601, -71.0589)),
    "LosAngeles-Houston": ((34.0522, -118.2437), (29.7604, -95.3698)),
}
def route(a, b, **p):
    url = f"https://router.project-osrm.org/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}"
    r = requests.get(url, params={"overview": "false", **p}, timeout=30)
    return r.json()
def summary(d):
    return [(round(x["distance"] / 1609.344), round(x["duration"] / 3600, 1)) for x in d.get("routes", [])]
for name, (a, b) in PAIRS.items():
    d = route(a, b, alternatives=3)
    print(name, "| alternatives=3 ->", len(d.get("routes", [])), "routes (miles, hours):", summary(d))
    e = route(a, b, exclude="motorway")
    print("   exclude=motorway ->", summary(e) or e.get("code"))
