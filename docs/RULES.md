# Rules and assumptions

The brief leaves a few details open. These are the choices made, and where each is implemented.

1. **Boundaries.** Where ranges overlap (e.g. 0.25 in/hr is listed under both Moderate and High) the
   lower bound is inclusive, so 0.25 in/hr is High. No Travel limits are exactly as written:
   wind >= 55 mph, rain > 1.00 in/hr, snow > 3.0 in/hr. (`planner/core/risk.py`)
2. **Load rules** apply to wind only, as written: 45-54 mph with a load over 30,000 lb is No Travel;
   35-44 mph with a load over 40,000 lb is Severe. Exactly 30,000 / 40,000 lb is not "over".
3. **Checkpoint risk** is the worst of wind (after load rules), rain and snow. Scale used for averages:
   Low 0, Moderate 1, High 2, Severe 3, No Travel 4.
4. **Wind** is the sustained 10 m wind speed in mph. Gusts are shown for information, not scored.
5. **Miles per level.** Each checkpoint covers the road from the midpoint with the previous checkpoint
   to the midpoint with the next one (first starts at mile 0, last ends at the route's end).
6. **Recommendation.** Fewest No Travel miles, then fewest Severe miles, then fewest High miles, then
   lowest average risk, then shortest travel time. Differences under 1 mile (or 0.02 on the risk
   scale) count as ties, so a trivial weather difference cannot override a much faster route.
   (`planner/core/recommend.py`)
7. **Forecast slider** covers hours 0-48 measured from the chosen departure time.
8. **Time zone.** The departure time is read as local time at the origin.
9. **Three routes.** The routing service is asked for alternatives; if it returns fewer than three,
   an extra route is built through an off-route waypoint and kept only if it is genuinely different.
   If fewer than three distinct routes exist, the app shows what exists and says so.

10. **Missing weather is Unknown, never Low.** A checkpoint with no usable forecast (failed request,
    missing or invalid values, or a trip past the 16-day window) is shown as Unknown. Its road is
    counted as `unknown_miles`, left out of the average risk, and the response adds a note.
    (`planner/core/recommend.py`, `planner/services/plan.py`)
11. **Weather at each checkpoint's own ETA.** Every checkpoint is scored with the hourly forecast
    nearest to its own arrival time (exactly :30 rounds up), not the departure time.
    (`planner/core/checkpoints.py`)
12. **ETA at constant average speed.** The routing service gives one duration per route, so ETAs are
    proportional to the distance along it.
13. **Routing profile.** The public OSRM demo server only offers a car profile, so durations are
    car-based, not truck-based. This is a known limitation of the demo setup.
14. **Geometry sent to the browser** is simplified (0.5-mile tolerance) to keep responses small.
    Checkpoint positions and mile marks use the full geometry.
15. **Geocoding.** Place names go to Nominatim (US only) first, then to Open-Meteo's geocoder as a
    fallback (non-US hits are skipped). Plain `lat,lon` input needs no lookup.
    (`planner/services/geocoding.py`)
16. **Checkpoint budget.** If the longest route would need more than about 60 checkpoints at the
    requested spacing, the spacing is raised to the next option (10, then 25, then 50) for all three
    routes, and the response says so. At 50 miles there is no further cap; the UI shows a loading state.
    (`planner/services/plan.py`)
17. **Weather request limits.** The weather lookup has a total time budget of about 20 seconds; after
    that, remaining requests are skipped and their checkpoints become Unknown. A rate-limit response
    (HTTP 429) is retried once after a short wait, then fails fast and the remaining requests are
    skipped. (`planner/services/weather.py`)
18. **Departure window.** Departures in the past, or 16 or more days ahead, are rejected, because the
    forecast covers 16 days from today.
