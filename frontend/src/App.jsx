import { useState } from "react";
import RouteMap from "./RouteMap.jsx";
import HeatSlider from "./HeatSlider.jsx";
import { LEVELS } from "./riskColors.js";
import { formatLocal } from "./format.js";
import "./styles.css";

const NO_ROUTES = []; // a stable empty list, so the map is not told "routes changed" on every render

// Departure is local time at the origin, written without a UTC offset (decision 8).
// <input type="datetime-local"> produces exactly "YYYY-MM-DDTHH:MM", which is what the API expects.
function tomorrowAt8() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T08:00`;
}

// Colour for a level name such as "High"; falls back to grey for anything unexpected.
const fillFor = (key) => LEVELS.find((l) => l.key === key)?.fill ?? "#9a9a9a";

// PlanForm: shows the inputs. It owns no data; the parent passes values and a submit function (props).
function PlanForm({ form, setForm, loading, onSubmit }) {
  // Returns a change handler for one field, so each input updates only its own key in `form`.
  const update = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  return (
    <form
      className="plan-form"
      onSubmit={(e) => {
        e.preventDefault(); // stop the browser's default full-page form submit
        onSubmit();
      }}
    >
      <label className="field">
        Origin
        <input value={form.origin} onChange={update("origin")} placeholder="City, ST or lat,lon" required />
      </label>
      <label className="field">
        Destination
        <input value={form.destination} onChange={update("destination")} placeholder="City, ST or lat,lon" required />
      </label>
      <label className="field">
        Departure (local at origin)
        <input type="datetime-local" value={form.departure} onChange={update("departure")} required />
      </label>
      <label className="field">
        Load (lb)
        <input type="number" min="0" max="200000" step="1000" value={form.load_lb} onChange={update("load_lb")} required />
      </label>
      <label className="field">
        Checkpoint spacing
        <select value={form.spacing} onChange={update("spacing")}>
          <option value="10">Every 10 mi</option>
          <option value="25">Every 25 mi</option>
          <option value="50">Every 50 mi</option>
        </select>
      </label>
      <button className="primary" type="submit" disabled={loading}>
        {loading ? "Planning (up to ~20 s)..." : "Plan routes"}
      </button>
    </form>
  );
}

// RiskBar: one horizontal bar per route. Each coloured segment is as wide as the miles at that level.
function RiskBar({ milesByLevel }) {
  const total = LEVELS.reduce((sum, l) => sum + (milesByLevel[l.key] ?? 0), 0);
  if (total <= 0) return null;
  return (
    <div className="risk-bar">
      {LEVELS.map((l) => {
        const miles = milesByLevel[l.key] ?? 0;
        if (miles <= 0) return null; // skip levels with no miles
        return <div key={l.key} title={`${l.key}: ${miles} mi`} style={{ width: `${(miles / total) * 100}%`, background: l.fill }} />;
      })}
    </div>
  );
}

// RiskTag: a coloured dot plus the level word ("Low", "Moderate", ...).
function RiskTag({ label, fill }) {
  return (
    <span className="risk-tag">
      <span className="dot" style={{ background: fill }} />
      {label}
    </span>
  );
}

// Legend: one swatch per level, so the bar colours are readable.
function Legend() {
  return (
    <div className="legend">
      {LEVELS.map((l) => (
        <span key={l.key}>
          <span className="swatch" style={{ background: l.fill }} />
          {l.key}
        </span>
      ))}
    </div>
  );
}

// SpacingLine: shows the spacing the server actually used (it may differ from the dropdown).
function SpacingLine({ spacing }) {
  if (!spacing) return null;
  const changed = spacing.used !== spacing.requested;
  return (
    <p className="muted" style={{ margin: 0 }}>
      Checkpoints every {spacing.used} mi{changed ? ` (you requested ${spacing.requested})` : ""}.
    </p>
  );
}

// RouteCard: one route's summary. `fastestHours` is the shortest duration among all routes.
function RouteCard({ route, fastestHours, selected, onSelect }) {
  const stats = route.stats;
  const miles = stats.miles_by_level;
  const unknownMiles = miles.Unknown ?? 0;
  // If Unknown covers the whole route, worst_level/average_risk would read as "Low": show "no data" instead.
  const noData = unknownMiles >= route.distance_miles - 0.5;
  const extraHours = route.duration_hours - fastestHours;
  return (
    <div className={`card${selected ? " selected" : ""}`} onClick={onSelect}>
      <div className="card-head">
        <strong>Route {route.index + 1}</strong>
        {route.recommended && <span className="badge">Recommended</span>}
      </div>
      <div className="risk-row">
        <RiskTag label={noData ? "No data" : stats.worst_level} fill={noData ? "#9a9a9a" : fillFor(stats.worst_level)} />
        <span className="muted">Avg risk {noData ? "n/a" : Number(stats.average_risk).toFixed(2)}</span>
      </div>
      <RiskBar milesByLevel={miles} />
      <p>
        {route.distance_miles} mi &middot; {route.duration_hours} h &middot;{" "}
        {extraHours >= 0.05 ? `+${extraHours.toFixed(1)} h vs fastest` : "Fastest"}
      </p>
      <p className="muted">Arrives (origin time): {formatLocal(route.arrival_local)}</p>
      {unknownMiles > 0 && !noData && (<p className="muted" style={{ color: "#e6b800" }}>{Math.round((unknownMiles / route.distance_miles) * 100)}% of this route ({unknownMiles} mi) has no weather data, so its risk may be understated.</p>)}
    </div>
  );
}

export default function App() {
  const [form, setForm] = useState({
    origin: "Chicago, IL",
    destination: "Dallas, TX",
    departure: tomorrowAt8(),
    load_lb: "42000",
    spacing: "25",
  });
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(0);
  const [collapsed, setCollapsed] = useState(false); // true = sidebar hidden, so the whole map shows
  const [hour, setHour] = useState(0); // slider position: hours after departure (0-48)

  async function plan() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin: form.origin.trim(),
          destination: form.destination.trim(),
          departure: form.departure,
          load_lb: Number(form.load_lb),
          spacing: Number(form.spacing),
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        const err = data.error ?? {};
        setError(`${err.message ?? "Request failed"}${err.field ? ` (field: ${err.field})` : ""}`);
      } else {
        setResult(data);
        setHour(0);
        setSelected(data.recommended_index); // start with the recommended route selected
      }
    } catch (e) {
      setError("Could not reach the server.");
    } finally {
      setLoading(false);
    }
  }

  const fastestHours = result ? Math.min(...result.routes.map((x) => x.duration_hours)) : 0;

  return (
    <div className="app">
      {/* Layer 1: the map fills the screen and stays mounted. */}
      <div className="map-layer">
        <RouteMap
          routes={result ? result.routes : NO_ROUTES}
          selectedIndex={selected}
          onSelect={setSelected}
          hour={hour}
          spacingUsed={result ? result.spacing.used : 25}
          leftPad={collapsed ? 60 : 430}
        />
      </div>

      {/* Layer 2: floating UI on top of the map. */}
      <div className="overlay">
        {collapsed ? (
          <button type="button" className="panel show-panel" onClick={() => setCollapsed(false)}>
            Show panel &raquo;
          </button>
        ) : (
          <aside className="panel sidebar">
            <div className="sidebar-head">
              <div className="brand">
                <strong>Weather-Aware</strong>
                <span>Truck Routing</span>
              </div>
              <button type="button" className="icon-btn" title="Hide panel" aria-label="Hide panel" onClick={() => setCollapsed(true)}>
                &laquo;
              </button>
            </div>
            <div className="sidebar-body">
              <PlanForm form={form} setForm={setForm} loading={loading} onSubmit={plan} />
              {error && <div className="error">{error}</div>}
              {result ? (
                <div className="results">
                  <p className="explanation">{result.explanation}</p>
                  <div className="cards">
                    {result.routes.map((r) => (
                      <RouteCard
                        key={r.index}
                        route={r}
                        fastestHours={fastestHours}
                        selected={r.index === selected}
                        onSelect={() => setSelected(r.index)}
                      />
                    ))}
                  </div>
                  <SpacingLine spacing={result.spacing} />
                  <Legend />
                  {result.notes.length > 0 && (
                    <details className="notes" open={result.notes.length <= 2}>
                      <summary>Notes ({result.notes.length})</summary>
                      <ul>
                        {result.notes.map((n, i) => (
                          <li key={i}>{n}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              ) : (
                !error && <p className="hint">Enter a trip and press Plan routes.</p>
              )}
            </div>
          </aside>
        )}

        {result && result.heat && (
          <div className={`panel bottombar${collapsed ? " full" : ""}`}>
            <HeatSlider heat={result.heat} hour={hour} onChange={setHour} />
          </div>
        )}
      </div>
    </div>
  );
}