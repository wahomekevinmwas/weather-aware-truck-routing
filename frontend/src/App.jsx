import { useState } from "react";

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
          <ul>
            {result.routes.map((r) => (
              <li key={r.index}>
                Route {r.index + 1}: {r.distance_miles} mi, {r.duration_hours} h, worst {r.stats.worst_level}
                {r.recommended ? " (recommended)" : ""}
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}