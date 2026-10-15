import { Fragment, memo, useEffect } from "react";
import { MapContainer, TileLayer, Polyline, CircleMarker, Circle, Popup, ZoomControl, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { LEVELS, dotColor } from "./riskColors.js";
import { formatLocal } from "./format.js";

const METRES_PER_MILE = 1609.34;
const UNKNOWN_HEAT = "#9a9a9a";

// FitBounds: when new routes arrive, zoom the map so every route is visible.
// useMap() gives access to the Leaflet map this component sits inside; it draws nothing itself.
// The padding keeps routes clear of the floating panels (left panel, top bar, bottom bar).
function FitBounds({ routes }) {
  const map = useMap();
  useEffect(() => {
    const points = routes.flatMap((r) => r.geometry); // each point is [lat, lon]
    if (points.length > 1) {
      map.fitBounds(points, { paddingTopLeft: [440, 120], paddingBottomRight: [40, 130] });
    }
  }, [routes, map]);
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
export default function RouteMap({ routes, selectedIndex, onSelect, hour = 0, spacingUsed = 25 }) {
  const selectedRoute = routes.find((r) => r.index === selectedIndex);
  return (
    <MapContainer preferCanvas zoomControl={false} center={[39.5, -98.35]} zoom={4} style={{ height: "100%", width: "100%" }}>
      <TileLayer
        className="dark-tiles"
        attribution="&copy; OpenStreetMap contributors"
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ZoomControl position="bottomright" />
      <FitBounds routes={routes} />
      <HeatLayer route={selectedRoute} hour={hour} spacingUsed={spacingUsed} />
      <RouteLayers routes={routes} selectedIndex={selectedIndex} onSelect={onSelect} />
    </MapContainer>
  );
}