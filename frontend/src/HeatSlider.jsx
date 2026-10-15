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
    <div className="heat-slider">
      <div>
        <strong>Forecast time:</strong> {clockLabel(heat, hour)} (origin time) &middot;{" "}
        {hour === 0 ? "departure" : `+${hour} h`}
      </div>
      <input
        type="range"
        min="0"
        max={heat.hours}
        step="1"
        value={hour}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <div className="muted heat-note">
        Dots show risk at the truck's ETA. The shaded corridor shows forecast conditions along the selected
        route at the slider's time.
      </div>
    </div>
  );
}