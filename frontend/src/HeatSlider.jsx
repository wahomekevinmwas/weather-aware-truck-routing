// HeatSlider: scrubs through the 0-48 h forecast. `hour` is state owned by App (a controlled input).
// Hour 0 is the departure hour; the label shows the clock time at the origin's time zone.
function clockLabel(heat, hour) {
  const when = new Date(Date.parse(heat.start_utc) + hour * 3600 * 1000);
  return when.toLocaleString("en-US", {
    timeZone: heat.timezone,
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function HeatSlider({ heat, hour, onChange }) {
  return (
    <div style={{ margin: "12px 0" }}>
      <label style={{ display: "block", fontWeight: 600 }}>
        Forecast time: {clockLabel(heat, hour)} (origin time) &middot; {hour === 0 ? "departure" : `+${hour} h`}
      </label>
      <input
        type="range"
        min="0"
        max={heat.hours}
        step="1"
        value={hour}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: "100%" }}
      />
      <div style={{ fontSize: 13, color: "#555" }}>
        Dots show risk at the truck's ETA. The shaded corridor shows forecast conditions along the selected
        route at the slider's time.
      </div>
    </div>
  );
}