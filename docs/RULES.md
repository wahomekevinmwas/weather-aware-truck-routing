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
