import { Fragment, memo, useEffect } from "react";
import { MapContainer, TileLayer, Polyline, CircleMarker, Circle, Popup, Marker, ZoomControl, useMap } from "react-leaflet";
import { divIcon } from "leaflet";
import "leaflet/dist/leaflet.css";
import { LEVELS, dotColor } from "./riskColors.js";
import { formatLocal } from "./format.js";

const METRES_PER_MILE = 1609.34;
const UNKNOWN_HEAT = "#9a9a9a";

// FitBounds: when new routes arrive, zoom the map so every route is visible.
// useMap() gives access to the Leaflet map this component sits inside; it draws nothing itself.
// The left padding clears the sidebar (smaller when it is collapsed); right and bottom clear the zoom control and slider.
function FitBounds({ routes, leftPad }) {
  const map = useMap();
  useEffect(() => {
    const points = routes.flatMap((r) => r.geometry); // each point is [lat, lon]
    if (points.length > 1) {
      map.fitBounds(points, { paddingTopLeft: [leftPad, 40], paddingBottomRight: [100, 130] });
    }
  }, [routes, map, leftPad]);
  return null;
}

const show = (value, unit) => (value == null ? "n/a" : `${value} ${unit}`);

// CheckpointPopup: what appears when you click a checkpoint dot.
function CheckpointPopup({ routeNumber, cp }) {
  return (
    <div style={{ minWidth: 190 }}>
      <strong>Route {routeNumber} &middot; mile {cp.mile}</strong>
      <div>Risk: <strong>{cp.level}</strong></div>
      <div>ETA (origin time): {formatLocal(cp.eta_local)}</div>
      <div>Wind: {show(cp.wind_mph, "mph")} (gusts {show(cp.gust_mph, "mph")})</div>
      <div>Rain: {show(cp.rain_in_hr, "in/hr")}</div>
      <div>Snow: {show(cp.snow_in_hr, "in/hr")}</div>
      {cp.reasons.length > 0 && (
        <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
          {cp.reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// HeatLayer: one translucent circle per checkpoint of the SELECTED route. The colour is the risk at the
// slider's hour (heat_levels[checkpoint][hour]); null (no data) is grey, never green. Neighbouring circles
// overlap, which reads as a shaded corridor. interactive:false lets clicks fall through to lines and dots.
function HeatLayer({ route, hour, spacingUsed }) {
  if (!route || !route.heat_levels) return null;
  const radius = 0.6 * spacingUsed * METRES_PER_MILE;
  return (
    <>
      {route.checkpoints.map((cp, i) => {
        const value = route.heat_levels?.[i]?.[hour];
        const fill = value == null ? UNKNOWN_HEAT : LEVELS[value]?.fill ?? UNKNOWN_HEAT;
        return (
          <Circle
            key={cp.mile}
            center={[cp.lat, cp.lon]}
            radius={radius}
            pathOptions={{ stroke: false, fillColor: fill, fillOpacity: 0.38, interactive: false }}
          />
        );
      })}
    </>
  );
}

// Display-only thresholds for the weather icons. The real risk rules live in the backend; these only decide
// where a small picture is worth drawing.
const RAIN_ICON_IN_HR = 0.02;
const GUST_ICON_MPH = 35;
const ICON_MIN_GAP_MILES = 60;
const MAX_TAGS = 4;

// Returns an HTML entity for the weather picture at a checkpoint, or null when nothing notable is happening.
function weatherGlyph(cp) {
  if ((cp.snow_in_hr ?? 0) > 0) return "&#127784;"; // cloud with snow
  if ((cp.rain_in_hr ?? 0) > 0.02 && (cp.rain_in_hr ?? 0) >= RAIN_ICON_IN_HR) return "&#127783;"; // cloud with rain
  if ((cp.gust_mph ?? 0) >= GUST_ICON_MPH) return "&#128168;"; // wind
  return null;
}

// MapAnnotations: small risk tags and weather pictures along the SELECTED route (like a weather-app overlay).
// A divIcon is a Leaflet marker drawn from a bit of HTML instead of an image, so we can style it with CSS.
// memo() makes React skip re-drawing it while the slider moves, because the route object does not change.
const MapAnnotations = memo(function MapAnnotations({ route }) {
  if (!route || !route.checkpoints || route.checkpoints.length === 0) return null;
  const cps = route.checkpoints;

  // Weather pictures: walk the checkpoints in order and keep one only if it is far enough from the last one kept.
  const gap = Math.max(ICON_MIN_GAP_MILES, (route.distance_miles ?? 0) / 8);
  const glyphs = [];
  let lastMile = -Infinity;
  for (const cp of cps) {
    const html = weatherGlyph(cp);
    if (html && cp.mile - lastMile >= gap) {
      glyphs.push({ cp, html });
      lastMile = cp.mile;
    }
  }

  // Risk tags: the middle checkpoint of each of MAX_TAGS equal slices of the route.
  const count = Math.min(MAX_TAGS, cps.length);
  const tags = Array.from({ length: count }, (_, k) => cps[Math.floor(((k + 0.5) * cps.length) / count)]);

  return (
    <>
      {glyphs.map(({ cp, html }) => (
        <Marker
          key={`${route.index}-wx-${cp.mile}`}
          position={[cp.lat, cp.lon]}
          interactive={false}
          icon={divIcon({ className: "map-wx", html: `<span>${html}</span>`, iconSize: [0, 0] })}
        />
      ))}
      {tags.map((cp) => {
        const known = LEVELS.some((l) => l.key === cp.level && l.key !== "Unknown");
        const label = known ? cp.level : "No data";
        return (
          <Marker
            key={`${route.index}-tag-${cp.mile}`}
            position={[cp.lat, cp.lon]}
            interactive={false}
            icon={divIcon({
              className: "map-tag",
              html: `<span style="--tag:${dotColor(cp.level)}">${label}</span>`,
              iconSize: [0, 0],
            })}
          />
        );
      })}
    </>
  );
});

// RouteLayers: the route lines and checkpoint dots. memo() makes React skip re-drawing it when its props
// are unchanged, so dragging the slider (which only changes `hour`) never redraws these.
const RouteLayers = memo(function RouteLayers({ routes, selectedIndex, onSelect }) {
  // The selected route is drawn last (on top), thicker and teal; the others are grey and smaller.
  const drawOrder = [...routes].sort((a, b) => (a.index === selectedIndex) - (b.index === selectedIndex));
  return (
    <>
      {drawOrder.map((route) => {
        const selected = route.index === selectedIndex;
        return (
          <Fragment key={route.index}>
            {selected && (
              <Polyline positions={route.geometry} pathOptions={{ color: "#4dd6c9", weight: 14, opacity: 0.2, interactive: false }} />
            )}
            <Polyline
              positions={route.geometry}
              pathOptions={{ color: selected ? "#4dd6c9" : "#9fb0bb", weight: selected ? 6 : 4, opacity: selected ? 0.95 : 0.5 }}
              eventHandlers={{ click: () => onSelect(route.index) }}
            />
            {route.checkpoints.map((cp) => (
              <CircleMarker
                key={cp.mile}
                center={[cp.lat, cp.lon]}
                radius={selected ? 7 : 4}
                pathOptions={{ color: "#ffffff", weight: 1, fillColor: dotColor(cp.level), fillOpacity: selected ? 0.95 : 0.55 }}
              >
                <Popup>
                  <CheckpointPopup routeNumber={route.index + 1} cp={cp} />
                </Popup>
              </CircleMarker>
            ))}
          </Fragment>
        );
      })}
    </>
  );
});

// RouteMap: heat first (underneath), then lines and dots on top. preferCanvas draws every shape on one
// <canvas> instead of one SVG element each, which keeps the map smooth with hundreds of shapes.
// The tile layer gets the "dark-tiles" class, which styles.css uses to darken the map.
export default function RouteMap({ routes, selectedIndex, onSelect, hour = 0, spacingUsed = 25, leftPad = 440 }) {
  const selectedRoute = routes.find((r) => r.index === selectedIndex);
  return (
    <MapContainer preferCanvas zoomControl={false} center={[39.5, -98.35]} zoom={4} style={{ height: "100%", width: "100%" }}>
      <TileLayer
        className="dark-tiles"
        attribution="&copy; OpenStreetMap contributors"
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ZoomControl position="topright" />
      <FitBounds routes={routes} leftPad={leftPad} />
      <HeatLayer route={selectedRoute} hour={hour} spacingUsed={spacingUsed} />
      <RouteLayers routes={routes} selectedIndex={selectedIndex} onSelect={onSelect} />
      <MapAnnotations route={selectedRoute} />
    </MapContainer>
  );
}