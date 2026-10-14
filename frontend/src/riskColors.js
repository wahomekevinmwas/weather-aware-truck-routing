// One entry per risk level in severity order. `key` must match the keys in stats.miles_by_level.
export const LEVELS = [
  { key: "Low", fill: "#2e9e5b" },
  { key: "Moderate", fill: "#e6b800" },
  { key: "High", fill: "#e8820c" },
  { key: "Severe", fill: "#d6322e" },
  { key: "No Travel", fill: "#5a0f1e" },
  // Unknown (no usable weather) is grey stripes, so it can never be mistaken for Low (green).
  { key: "Unknown", fill: "repeating-linear-gradient(45deg, #b8b8b8, #b8b8b8 4px, #e6e6e6 4px, #e6e6e6 8px)" },
];

const UNKNOWN_DOT = "#9a9a9a";

// Map dots are SVG shapes and cannot use the striped gradient, so Unknown gets a plain grey.
export function dotColor(level) {
  const found = LEVELS.find((l) => l.key === level);
  return found && level !== "Unknown" ? found.fill : UNKNOWN_DOT;
}