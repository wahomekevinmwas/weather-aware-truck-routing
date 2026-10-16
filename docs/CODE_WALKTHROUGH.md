# Code walkthrough

This document explains how the code works, in the order a request flows through it. It is also the outline for the video walkthrough. For what the app does and how to run it, see the README.

## 1. The big picture

```
Browser (React)                        Django (backend)
---------------                        ----------------
form: origin, destination,  POST /api/plan   views.plan_view
departure, load, spacing  ----------------->  PlanService.plan
                                                1. geocode both places, find the origin's time zone
                                                2. get up to 3 routes (OSRM)
                                                3. build checkpoints and ETAs for each route
                                                4. fetch the weather once for all checkpoints
                                                5. classify every checkpoint (risk.py)
                                                6. compute route stats, rank, explain (recommend.py)
                                                7. precompute 49 hourly levels per checkpoint (heat.py)
map, cards, notes, slider <-----------------  one JSON response
```

One rule shapes the whole backend: the decisions live in `planner/core` (pure Python, no Django, no network), network access lives in `planner/services` behind small client classes, and `plan.py` only coordinates them. That is why the tests run offline with fake clients.

## 2. Backend core: pure logic

### core/risk.py - the risk rules (40% of the grade is logic like this)

- `Risk` is an integer enum: Low 0, Moderate 1, High 2, Severe 3, No Travel 4. Numbers make "the worst of" a simple `max`, and they feed the average risk.
- `wind_level`, `rain_level` and `snow_level` each walk from the worst level down (`>= 55`, then `>= 45`, ...). Because they use `>=` thresholds from the top, there are no gaps between ranges: 34.6 mph is Moderate, not "undefined".
- Boundaries where the brief's ranges touch go to the higher level (0.25 in/hr of rain is High). The No Travel limits follow the brief exactly: wind `>= 55`, rain `> 1.00`, snow `> 3.0`.
- `apply_load_rules` implements the two load rules, only for wind, with strict "over" comparisons: 45 to 54 mph and over 30,000 lb is No Travel; 35 to 44 mph and over 40,000 lb is at least Severe.
- `classify` first rejects bad input (missing, negative or non-finite numbers raise `ValueError`), then returns an `Assessment`: the overall level (worst of wind-after-load-rules, rain, snow), each component level, and human-readable `reasons` such as "Wind 40 mph with a 42,000 lb load (over 40,000 lb) is Severe".

### core/checkpoints.py - where the truck is, and when

- `departure_to_utc`: the user types a local time at the origin with no offset; this attaches the origin's IANA time zone and converts to UTC. Everything internal is UTC, so daylight saving cannot skew ETAs.
- `build_checkpoints`: marks at mile 0, every `spacing` miles, and the destination (a regular mark within 1 mile of the end is dropped). Each mark gets a position (`point_at_mile` in geo.py) and an ETA: `departure + duration * mark / distance`. The routing service gives one duration per route, so speed is constant by assumption.
- `scale = distance_miles / geometry length` converts between the routing service's distance and the length measured along the drawn line, so the marker lands where the truck would be.
- `forecast_key`: the hourly forecast timestamp nearest an ETA (add 30 minutes, then cut to the hour; exactly :30 rounds up).

### core/geo.py - geometry helpers

- `haversine` (great-circle miles), `bearing`, `destination` (a point at a bearing and distance).
- `cumulative_miles` and `point_at_mile`: miles along the line, and the interpolated point at a given mile (binary search with `bisect`).
- `simplify`: Douglas-Peucker line simplification. The line sent to the browser is simplified to 0.5 mile tolerance (129 points on Chicago to Dallas instead of the full detail), which keeps the response small and the map fast.
- `share_far_from` and `side_waypoint`: used by routing.py to decide whether an extra route is genuinely different, and to pick a point left or right of the route.

### core/recommend.py - route statistics and ranking

- Each checkpoint "owns" the stretch of road from the midpoint with its previous neighbour to the midpoint with its next one (`segment_lengths`). `compute_stats` adds those lengths up per risk level (`miles_by_level`, with Unknown counted separately) and computes a distance-weighted average risk. Unknown stretches are left out of the average and never counted as Low.
- `CRITERIA` is the ranking order, as data: No Travel miles (exact), Unknown miles, Severe miles, High miles, average risk, travel time. The brief's order (Severe, High, average, time) is kept; No Travel and Unknown are added in front.
- `bucket` turns a value into a "bucket" using a tolerance (1 mile, 0.02 risk points, 1 minute), so near-ties compare equal and fall through to the next criterion. Distance and route index are the final tiebreakers, so the result is deterministic. The bucketing is approximate at the edges of a tolerance, which is a known compromise.
- `recommend` sorts routes by `ranking_key`, picks the first, and builds one explanation sentence from the first criterion where the winner differs from the runner-up. If every route has No Travel miles, it says so and suggests another departure time.

## 3. Backend services: network and orchestration

### services/geocoding.py

- Accepts a place name or `lat,lon`. Coordinates skip the network.
- Names go to Nominatim first (US only, `countrycodes=us`), then to the Open-Meteo geocoder as a fallback (also filtered to US). Results are cached for 24 hours. Nominatim calls are spaced at least 1.1 seconds apart (its usage policy) using a lock.
- The origin's time zone comes from Open-Meteo with `timezone=auto`.
- Errors are split into "no such place" and "the service failed"; user-facing messages are safe to show.

### services/routing.py

- `OsrmClient` calls the public OSRM demo server (car profile) with retries and an in-memory cache.
- `build_route_options` asks for three alternatives. If it gets fewer, it tries up to four off-route waypoints (left and right of the first route, fetched in parallel). A candidate is kept only if it is at most 1.3x the shortest distance and 1.5x the fastest time, and at least 25% of it is more than 5 miles from every chosen route. Each added route produces a note that explains how it was built.

### services/weather.py

- One request can carry up to 50 locations. Points are rounded to 0.01 degree (about 0.7 mile), which is also the cache key; entries live 30 minutes.
- `parse_entry` checks the units in the response (mph, inch) instead of assuming them, and `reading_at` returns `None` for missing or invalid values. `None` becomes Unknown further up.
- `WeatherClient.fetch` skips cached points, splits the rest into chunks of 50, and runs chunks on 4 threads. Each chunk has retries for server errors and timeouts. A rate-limit answer (HTTP 429) gets one retry, then stops the other chunks. The whole fetch has a 20 second budget. If only some chunks fail, the rest are used and the failures become notes; if everything fails, the plan returns a clear "weather service unavailable" error.

### services/heat.py - the forecast slider data

- `hourly_levels` takes the weather data already fetched for scoring and, for each of 49 hours after departure, looks up the reading, classifies it with the same `classify` (so the same load rules), and returns an integer 0 to 4 or `None`.
- It makes no network calls. `plan.py` requests enough forecast days to cover departure + 48 hours.

### services/plan.py - the orchestrator

`PlanService.plan` runs the steps in section 1, with validation first:

- `parse_request` checks every field and raises `PlanError` with the field name, so the form can show "(field: departure)". Limits: load 0 to 200,000 lb, spacing 10 / 25 / 50, departure as local time without an offset.
- Same-place check (under 1 mile apart), and a check that the departure is today or later and inside the 16-day forecast window.
- `choose_spacing` raises the spacing when the longest route would need more than 60 checkpoints, and adds a note.
- The weather fetch is one call for all checkpoints of all three routes. `days_needed` works out how many forecast days to ask for; if a trip runs past the 16-day window the later checkpoints are Unknown, with a note.
- Each checkpoint is classified (or left Unknown), `compute_stats` and `recommend` run, and notes are added for any missing weather. The JSON includes routes, checkpoints, simplified geometry, `heat_levels`, the explanation, notes, the spacing used and the heat settings.
- If the time zone lookup fails the departure is read as UTC and a note says so. A failed weather service gives a 503, a failed routing service a 502.

### views.py

A thin wrapper: parse the JSON, call the shared `PlanService`, and turn `PlanError` into `{"error": {code, message, field}}`. Unexpected exceptions are logged on the server and return a generic 500. The service object is created once (behind a lock), so the geocoding, routing and weather caches survive between requests. The view is `csrf_exempt` because it is a stateless JSON API with no cookies or sessions.

## 4. Configuration and deployment

- `config/settings.py`: the secret key and debug flag come from environment variables (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`); without a secret key and without debug mode the app refuses to start. Allowed hosts come from `DJANGO_ALLOWED_HOSTS` and Render's `RENDER_EXTERNAL_HOSTNAME`. WhiteNoise serves the built React app from `frontend/dist`, so one Django process hosts both the API and the UI. `SECURE_REFERRER_POLICY` is set so OpenStreetMap's tile servers receive a Referer.
- `config/urls.py`: everything under `api/` goes to the `planner` app; the Django admin is still routed from the project template.
- `render-build.sh`: install Python dependencies, build the React app, collect static files, run migrations. Start command and environment are in the README.

## 5. Frontend (React)

### React words used here

- **Component**: a function that returns a piece of screen. `RouteCard`, `PlanForm` and so on.
- **Props**: inputs a parent passes to a child (`<RouteCard route={r} selected={...} />`).
- **State** (`useState`): data React remembers between redraws. When it changes, React redraws what depends on it.
- **Effect** (`useEffect`): code that runs after a redraw when certain values change.
- **`key`**: a label React needs on list items so it can tell them apart.
- **`memo`**: tells React to skip redrawing a component when its props did not change.

### App.jsx

- `App` holds all the state: `form` (the inputs), `result` (the API response), `error`, `loading`, `selected` (which route is highlighted) and `hour` (slider position). Components below it receive what they need as props; the form and the slider own no data, they only call the functions they are given. (State lives in one parent so that the cards, map and slider always agree.)
- `plan()` posts the form to `/api/plan`. On success it stores the result, resets the slider to 0 and selects the recommended route; on failure it shows the server's message, including the field name.
- Layout: a full-screen map layer, and over it an overlay with the top bar (form), the left results panel and the bottom slider bar.
- The map stays mounted all the time. Before a result exists it gets `NO_ROUTES`, one constant empty list defined outside the component, so React does not see "new routes" on every redraw.
- `RouteCard`: worst level as a coloured word, average risk, a risk bar (one segment per level, width proportional to miles), distance, duration, "+X h vs fastest", arrival time in origin time, and a warning when part of the route has no weather data. If Unknown covers the whole route, it shows "No data" rather than a misleading "Low". Clicking a card sets `selected`.
- `RiskBar`, `RiskTag`, `Legend`, `SpacingLine`: small display components. Colours come from `riskColors.js`, so cards, legend, dots and heat use one palette.
- `tomorrowAt8` fills the default departure; `<input type="datetime-local">` produces exactly the `YYYY-MM-DDTHH:MM` format the API expects.

### RouteMap.jsx (react-leaflet)

- `MapContainer` is the Leaflet map as a component; everything inside it (tiles, lines, dots, circles) is a child component. `preferCanvas` draws all shapes on one canvas instead of one SVG element each. The tile layer has a CSS class that `styles.css` uses to darken the map.
- `FitBounds` uses `useMap` and an effect to zoom to all routes whenever new routes arrive. Its padding keeps the routes clear of the floating panels.
- `RouteLayers` draws the route lines and checkpoint dots (selected route last, thicker, with bigger dots; clicking a line selects it). It is wrapped in `memo`, so moving the slider (which only changes `hour`) does not redraw it.
- `CheckpointPopup` shows mile, risk, ETA in origin time, wind and gusts, rain, snow and the reasons.
- `HeatLayer` draws one translucent circle per checkpoint of the selected route, coloured by `heat_levels[checkpoint][hour]`. Missing data is grey, never green. Circles overlap so they read as a shaded corridor, and the heat is drawn first so lines and dots sit on top.

### HeatSlider.jsx

A controlled range input: its value is `hour`, owned by `App`, and moving it calls `onChange`. The label converts the departure time plus `hour` hours into the origin's clock time using the time zone from the response. The note under it explains that dots show risk at the truck's ETA while the shaded corridor shows the forecast at the slider's time.

### riskColors.js and format.js

`LEVELS` is the single list of level names and colours (Unknown is grey stripes in the bar and plain grey on the map). `formatLocal` shows an origin-local timestamp exactly as written, without converting it to the browser's time zone.

## 6. Why it is fast

- One weather fetch for all checkpoints of all routes, in chunks of 50 on 4 threads, with caches for weather (30 minutes), routes and places (24 hours), and a 20 second weather budget.
- At most 60 checkpoints per route; the spacing is raised if needed.
- The forecast slider reads numbers already in the browser, so dragging it never waits on the network. The server computes all 49 hours in the same response.
- The line sent to the browser is simplified (Douglas-Peucker, 0.5 mile).
- The map draws on a canvas, the lines and dots are not redrawn while the slider moves, and the app does not remount the map between plans.

## 7. Tests

The tests are in `backend/planner/tests`, one file per area (risk, checkpoints, geo, geocoding, routing, weather, recommend, plan, views, heat, and so on). They use fake clients, so no network is needed.

```powershell
cd backend
python -m unittest discover -s planner/tests -t .
```

## 8. Video walkthrough outline (5 to 10 minutes)

Before recording: open the hosted app once and plan a trip so the free-tier server is awake. Use a trip and departure whose forecast shows some non-green colours, if the current forecast has any.

| Time | What to show | What to say |
|---|---|---|
| 0:00 - 0:45 | The hosted app | The task, the stack (React + Django), that it is live, and that React was new to me on this project so I kept the components small. |
| 0:45 - 3:00 | Live demo | Plan a trip. Read the explanation sentence. Compare the three cards. Click a checkpoint popup. Change the load and plan again to show the load rules. Drag the slider and explain dots (risk at the truck's ETA) versus heat (forecast at the slider's time). Point out the notes. |
| 3:00 - 5:30 | Backend, using section 1 | The data flow. risk.py and its boundary decisions. How an ETA turns into a forecast hour. The ranking order and the tolerances. |
| 5:30 - 7:30 | Frontend, using section 5 | State in App, props, the map layers, `memo`, the slider. |
| 7:30 - 9:00 | Decisions and limits | Unknown is never Low; No Travel and Unknown rank first; spacing is raised at 60 checkpoints; OSRM is a car profile; constant-speed ETAs; heat is per checkpoint, not a grid; the free tier is slow on first load. |
| 9:00 - 9:30 | Wrap | What I would do next: truck-specific routing, rest stops in the ETAs, a gridded heat layer, shared caching. |

## 9. Questions a reviewer might ask

- **Why do No Travel and Unknown rank ahead of Severe?** A route you cannot drive should lose to one you can, and "no data" is not the same as "safe". Both are additions to the brief's order and are documented.
- **Why tolerances in the ranking?** So a trivial difference (under 1 mile, 0.02 risk, 1 minute) cannot beat a much faster route. It is a deliberate deviation from a strict "fewest".
- **Why is the heat one value per checkpoint?** A real grid needs many more weather requests. This keeps the plan fast and the slider free of network calls, at the cost of resolution.
- **What if the weather service fails?** The affected checkpoints are Unknown, a note says why, and the card warns that risk may be understated. If everything fails the user gets a clear error.
- **What does the load weight change?** Only wind scoring: heavy loads turn 35 to 44 mph into Severe and 45 to 54 mph into No Travel.
- **How are times handled?** The departure is local time at the origin. It is converted to UTC once, all math is UTC, and times are displayed in the origin's time zone.
- **What would you improve first?** Truck-specific routing and hours-of-service in the ETAs.
