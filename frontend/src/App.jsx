import { useState } from "react";
import RouteMap from "./RouteMap.jsx";
import HeatSlider from "./HeatSlider.jsx";
import { LEVELS } from "./riskColors.js";
import { formatLocal } from "./format.js";

// Departure is local time at the origin, written without a UTC offset (decision 8).
// <input type="datetime-local"> produces exactly "YYYY-MM-DDTHH:MM", which is what the API expects.
function tomorrowAt8() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T08:00`;
}

// PlanForm: shows the inputs. It owns no data; the parent passes values and a submit function (props).
function PlanForm({ form, setForm, loading, onSubmit }) {
  // Returns a change handler for one field, so each input updates only its own key in `form`.
  const update = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const row = { display: "flex", flexDirection: "column", gap: 4, minWidth: 160 };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault(); // stop the browser's default full-page form submit
        onSubmit();
      }}
      style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-end" }}
    >
      <label style={row}>
        Origin
        <input value={form.origin} onChange={update("origin")} placeholder="City, ST or lat,lon" required />
      </label>
      <label style={row}>
        Destination
        <input value={form.destination} onChange={update("destination")} placeholder="City, ST or lat,lon" required />
      </label>
      <label style={row}>
        Departure (local at origin)
        <input type="datetime-local" value={form.departure} onChange={update("departure")} required />
      </label>
      <label style={row}>
        Load (lb)
        <input type="number" min="0" max="200000" step="1000" value={form.load_lb} onChange={update("load_lb")} required />
      </label>
      <label style={row}>
        Checkpoint spacing
        <select value={form.spacing} onChange={update("spacing")}>
          <option value="10">Every 10 mi</option>
          <option value="25">Every 25 mi</option>
          <option value="50">Every 50 mi</option>
        </select>
      </label>
      <button type="submit" disabled={loading}>
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
    <div style={{ display: "flex", height: 14, borderRadius: 4, overflow: "hidden", background: "#eee" }}>
      {LEVELS.map((l) => {
        const miles = milesByLevel[l.key] ?? 0;
        if (miles <= 0) return null; // skip levels with no miles
        return (
          <div
            key={l.key}
            title={`${l.key}: ${miles} mi`}
            style={{ width: `${(miles / total) * 100}%`, background: l.fill }}
          />
        );
      })}
    </div>
  );
}

// Legend: one swatch per level, so the bar colours are readable.
function Legend() {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 12, fontSize: 13, margin: "8px 0" }}>
      {LEVELS.map((l) => (
        <span key={l.key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 12, height: 12, borderRadius: 2, background: l.fill, display: "inline-block" }} />
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
    <p style={{ margin: "8px 0" }}>
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
    <div onClick={onSelect}
      style={{
        border: route.recommended ? "2px solid #2e9e5b" : "1px solid #ccc",
        cursor: "pointer",
        boxShadow: selected ? "0 0 0 3px #1f5fbf" : "none",
        borderRadius: 8,
        padding: 12,
        flex: "1 1 260px",
        maxWidth: 420,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <strong>Route {route.index + 1}</strong>
        {route.recommended && (
          <span style={{ background: "#2e9e5b", color: "white", borderRadius: 10, padding: "2px 8px", fontSize: 12 }}>
            Recommended
          </span>
        )}
      </div>
      <RiskBar milesByLevel={miles} />
      <p style={{ margin: "8px 0 0" }}>
        {route.distance_miles} mi &middot; {route.duration_hours} h &middot;{" "}
        {extraHours >= 0.05 ? `+${extraHours.toFixed(1)} h vs fastest` : "Fastest"}
      </p>
      <p style={{ margin: "4px 0 0" }}>Arrives (origin time): {formatLocal(route.arrival_local)}</p>
      <p style={{ margin: "4px 0 0" }}>
        Worst: {noData ? "No weather data" : stats.worst_level} &middot; Avg risk:{" "}
        {noData ? "n/a" : Number(stats.average_risk).toFixed(2)}
      </p>
      {unknownMiles > 0 && !noData && (
        <p style={{ margin: "4px 0 0", color: "#666" }}>{unknownMiles} mi without weather data</p>
      )}
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

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 24 }}>
      <h1>Weather-Aware Truck Routing</h1>
      <PlanForm form={form} setForm={setForm} loading={loading} onSubmit={plan} />
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {result && (
        <>
          <p>{result.explanation}</p>
          {result.notes.length > 0 && (
            <ul style={{ color: "#8a5a00" }}>
              {result.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
          <SpacingLine spacing={result.spacing} />
          <Legend />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
            {result.routes.map((r) => (
              <RouteCard
                key={r.index}
                route={r}
                fastestHours={Math.min(...result.routes.map((x) => x.duration_hours))}
                selected={r.index === selected}
                onSelect={() => setSelected(r.index)}
              />
            ))}
          </div>
        <div style={{ marginTop: 16 }}>
            {result.heat && <HeatSlider heat={result.heat} hour={hour} onChange={setHour} />}
            <RouteMap routes={result.routes} selectedIndex={selected} onSelect={setSelected} hour={hour} spacingUsed={result.spacing.used} />
          </div>
        </>
      )}
    </main>
  );
}