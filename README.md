# Weather-Aware Truck Routing

A React + Django web app that helps a truck driver choose the safest of three routes, based on the weather at the time the truck will actually be there, the load weight and the travel time.

- Hosted app: https://weather-aware-truck-routing-ssmj.onrender.com
- Repository: https://github.com/wahomekevinmwas/weather-aware-truck-routing

The hosted app runs on Render's free tier, which spins down when idle. The first load after a quiet spell can take about 30 seconds (one measurement: 32 s for the page). After that it is fast. Planning a trip took roughly 6 to 11 seconds in my tests, because it calls three public services (see "External services").

## What it does

1. You enter an origin, a destination, a departure date and time (local time at the origin), a load weight in pounds and a checkpoint spacing (10, 25 or 50 miles).
2. The backend finds the places and up to three routes.
3. It puts a checkpoint at the origin, every N miles and at the destination, and works out when the truck will reach each one.
4. It reads the hourly forecast for each checkpoint at that arrival time and classifies the weather with the risk rules from the brief (wind, rain, snow, plus the load rules).
5. It ranks the routes, recommends one and explains why in one sentence.
6. The map shows all routes, risk-coloured checkpoints (click one for its arrival time and weather), route cards with risk bars and summaries, and a forecast slider from 0 to 48 hours after departure that colours a corridor along the selected route.

## Run it locally

Requirements: Python 3.14, Node 22 or newer. Commands are for Windows PowerShell, from the repo root.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

Backend (terminal 1):

```powershell
cd backend
$env:DJANGO_DEBUG = "1"
python manage.py runserver
```

Frontend (terminal 2):

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server forwards /api requests to Django on 127.0.0.1:8000.

Tests (no network needed, 135 tests):

```powershell
cd backend
python -m unittest discover -s planner/tests -t .
```

## API

`POST /api/plan` with JSON:

| Field | Meaning |
|---|---|
| origin, destination | A US place such as "Chicago, IL", or coordinates as "lat,lon" |
| departure | Local time at the origin, `YYYY-MM-DDTHH:MM`, no UTC offset |
| load_lb | Load weight in pounds (0 to 200,000) |
| spacing | 10, 25 or 50 miles (default 25) |

The response contains `routes[]` (distance, duration, arrival time, `stats` with miles at each risk level, average risk and worst level, `checkpoints[]`, `geometry`, `heat_levels`), `recommended_index`, `explanation`, `notes[]`, `spacing {requested, used}`, `departure {local, utc, timezone}` and `heat {start_utc, timezone, hours}`.

Errors look like `{"error": {"code", "message", "field"}}`: 400 for invalid input or an unknown place, 405 for anything but POST, 502 when routing fails, 503 when the weather service is unavailable, 500 for anything unexpected (logged on the server, generic message to the client).

## How risk is scored

Each checkpoint gets the worst of its wind, rain and snow levels, after the load rules.

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph) | < 25 | 25 to < 35 | 35 to < 45 | 45 to < 55 | >= 55 |
| Rain (in/hr) | < 0.10 | 0.10 to < 0.25 | 0.25 to < 0.50 | 0.50 to 1.00 | > 1.00 |
| Snow (in/hr) | < 0.5 | 0.5 to < 1.0 | 1.0 to < 2.0 | 2.0 to 3.0 | > 3.0 |

Load rules (wind only): 45 to 54 mph with a load over 30,000 lb is No Travel; 35 to 44 mph with a load over 40,000 lb is Severe (never lower than the table says). Wind of 55 mph or more is No Travel for any load.

Boundary decisions, because the brief's ranges touch at their edges:

- A value exactly on a shared boundary goes to the higher level (0.25 in/hr of rain is High).
- No Travel is applied exactly as written: wind >= 55, rain > 1.00, snow > 3.0 (so exactly 1.00 in/hr of rain is Severe).
- "Over 30,000 lb" and "over 40,000 lb" are strict, so exactly 30,000 or 40,000 lb does not trigger the load rule.
- Sustained 10 m wind is what is scored. Gusts are shown in the checkpoint popup but not scored.
- Missing weather is **Unknown** (grey stripes), never Low. Unknown stretches are excluded from the average risk and counted separately.

The risk rules have their own offline tests (`backend/planner/tests/test_risk.py`), and the boundaries listed above were also checked by hand.

## How routes are ranked

The brief prefers: fewest Severe miles, then fewest High miles, then lowest average risk, then shortest time. The code follows that order with two additions at the front:

1. Fewest **No Travel** miles (exact), because a route that cannot be driven should lose to one that can.
2. Fewest **Unknown** miles, because "no data" is not the same as "safe".
3. Fewest Severe miles.
4. Fewest High miles.
5. Lowest average risk.
6. Shortest travel time.

Near-ties fall through to the next criterion: differences under 1 mile, 0.02 risk points or 1 minute count as equal, so a trivial weather difference cannot beat a much faster route. This is a deliberate deviation from a strict "fewest", and the bucketing is approximate near the edges of a tolerance. The explanation sentence names the first criterion where the winner differs from the next-best route.

Average risk is distance-weighted: each checkpoint owns the stretch of road halfway to its neighbours, on a 0 (Low) to 4 (No Travel) scale.

## ETAs and checkpoints

- Arrival time at a checkpoint = departure + the route's total duration x (miles so far / total miles). The routing service gives one duration per route, so speed is treated as constant.
- The forecast hour used is the hourly timestamp nearest the arrival time (exactly :30 rounds up).
- Departure is entered as local time at the origin, and times are shown in origin time. The origin's time zone comes from Open-Meteo; if that lookup fails, the departure is read as UTC and the app says so.
- A regular checkpoint within 1 mile of the destination is replaced by the destination.
- If a route would need more than 60 checkpoints at the requested spacing, the spacing is raised (for example 10 to 25 miles) and the app says so. This keeps the weather lookup fast. All checkpoints of all three routes go to the weather service together, in batches of up to 50 points.

## The forecast heatmap

- The slider runs from 0 to 48 hours after the departure hour (49 values per checkpoint).
- The levels are computed on the server from the same forecast data fetched for scoring, with the same classification and load rules, and sent in the plan response. Dragging the slider only reads numbers already in the browser: there is no network call.
- The heat is drawn for the selected route as soft circles at each checkpoint, coloured by the level at the slider's clock time.
- Dots and heat mean different things: a dot is the risk when the truck arrives there; the heat is the forecast at the slider's time. A stretch can look severe on the slider and still be Low on the route card, if the truck passes it hours later.
- Hours beyond the forecast window show as Unknown (grey).
- The heat is one value per checkpoint, not a gridded weather field. A grid would need many more weather requests and defeat the "no waiting on the network while dragging" goal.

## External services

- Routing: the public OSRM demo server (car profile). Free, no guarantees. Responses are cached in memory.
- Geocoding: Nominatim first (US only), then the Open-Meteo geocoder as a fallback. Typing coordinates as "lat,lon" skips the network. Results are cached for 24 hours, and Nominatim calls are spaced at least 1.1 seconds apart to respect its usage policy.
- Weather: Open-Meteo hourly forecast (wind, gusts, rain, snowfall), up to 50 points per request, a 20 second time budget, a 30 minute in-memory cache and a 16-day window.
- Map tiles: OpenStreetMap standard tiles, darkened with CSS.

If a weather request fails, the affected checkpoints are shown as Unknown and a note explains why. If most of a route has no data, its card says so instead of showing a misleading "Low".

## Three routes

OSRM sometimes returns fewer than three alternatives. When it does, the backend tries routes through an off-route waypoint (offset to the left or right of the first route) and accepts one only if it is not absurdly long (at most 1.3x the shortest distance and 1.5x the fastest time) and at least 25% of it is more than 5 miles from every chosen route. A note tells you which routes were built this way.

## Known limitations

- Constant-speed ETAs: no traffic, no rest stops or hours-of-service limits. On a long trip the weather at later checkpoints is read earlier than a real driver would arrive.
- OSRM uses a car profile, not truck routing (no height, weight or hazmat restrictions).
- Waypoint-built routes are not checked against borders: for example a Chicago to New York alternative can pass through Ontario.
- Geocoding covers US places only.
- The heat is per checkpoint, not a gridded field (see above).
- The public OSRM server and the free hosting tier have no uptime guarantees, and the first request after an idle period is slow.
- Departures must be today or later (the check is by date, not by time of day) and within the 16-day forecast window.

## Project layout

```
backend/
  config/            Django settings, urls, wsgi
  planner/
    core/            pure Python, no Django, no network:
                     checkpoints.py, geo.py, risk.py, recommend.py
    services/        network clients and orchestration:
                     geocoding.py, routing.py, weather.py, heat.py, plan.py
    tests/           offline tests (fake clients, no network)
    views.py         POST /api/plan
frontend/src/        React app: App.jsx, RouteMap.jsx, HeatSlider.jsx,
                     riskColors.js, format.js, styles.css
scripts/             manual probe scripts for the external APIs
docs/RULES.md        design decisions log
render-build.sh      build script used on Render
```

## Deployment (Render)

- Build command: `bash render-build.sh` (pip install, npm ci, npm run build, collectstatic, migrate).
- Start command: `gunicorn --chdir backend config.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 90`
- Environment: `DJANGO_SECRET_KEY`, `NODE_VERSION=22.12.0`.
- Django serves the built React app (`frontend/dist`) with WhiteNoise, so there is one service and no CORS. A single worker is used because the caches live in memory.
