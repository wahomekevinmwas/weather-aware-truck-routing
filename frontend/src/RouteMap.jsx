import { Fragment, useEffect } from "react";
import { MapContainer, TileLayer, Polyline, CircleMarker, Popup, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { dotColor } from "./riskColors.js";
import { formatLocal } from "./format.js";

// FitBounds: when new routes arrive, zoom the map so every route is visible.
// useMap() gives access to the Leaflet map this component sits inside; it draws nothing itself.
function FitBounds({ routes }) {
  const map = useMap();
  useEffect(() => {
    const points = routes.flatMap((r) => r.geometry); // each point is [lat, lon]
    if (points.length > 1) map.fitBounds(points, { padding: [30, 30] });
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

// RouteMap: all routes as lines, every checkpoint as a risk-coloured dot.
// The selected route is drawn last (on top), thicker and blue; the others are grey and smaller.
export default function RouteMap({ routes, selectedIndex, onSelect }) {
  const drawOrder = [...routes].sort((a, b) => (a.index === selectedIndex) - (b.index === selectedIndex));
  return (
    <MapContainer center={[39.5, -98.35]} zoom={4} style={{ height: 520, width: "100%", borderRadius: 8 }}>
      <TileLayer
        attribution="&copy; OpenStreetMap contributors"
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <FitBounds routes={routes} />
      {drawOrder.map((route) => {
        const selected = route.index === selectedIndex;
        return (
          <Fragment key={route.index}>
            <Polyline
              positions={route.geometry}
              pathOptions={{ color: selected ? "#1f5fbf" : "#7a7a7a", weight: selected ? 6 : 4, opacity: selected ? 0.9 : 0.6 }}
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
    </MapContainer>
  );
}