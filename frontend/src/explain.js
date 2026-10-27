// explain.js: answers questions about the plan that is on screen.
// There is no AI model and no network call here. Every answer is assembled from the plan data the server
// already returned, so it cannot invent weather or numbers, and it never changes the recommendation.
import { LEVELS } from "./riskColors.js";
import { formatLocal } from "./format.js";

const MAX_QUESTION_CHARS = 200;
const RANKED = LEVELS.map((l) => l.key).filter((k) => k !== "Unknown"); // Low ... No Travel, mildest first
const rank = (level) => RANKED.indexOf(level); // -1 means Unknown or an unrecognised level

export const PRESETS = [
  "Why is this route recommended?",
  "Where is the riskiest stretch?",
  "Compare the routes",
  "How much weather data is missing?",
  "What do the risk levels mean?",
  "How are routes ranked?",
  "When will I arrive?",
];

const FALLBACK =
  "I can only answer from the plan on screen. Try one of the questions below, or name a route, " +
  "for example: Where is the riskiest stretch on route 2?";

const label = (route) => `Route ${route.index + 1}`;
const num = (value, unit) => (value == null ? "n/a" : `${value} ${unit}`);
const unknownMiles = (route) => route.stats.miles_by_level?.Unknown ?? 0;
// If Unknown covers the whole route, the stats would read as "Low", so say "no data" instead.
const hasNoData = (route) => unknownMiles(route) >= route.distance_miles - 0.5;
const worst = (route) => (hasNoData(route) ? "no weather data" : route.stats.worst_level);
const avg = (route) => (hasNoData(route) ? "n/a" : Number(route.stats.average_risk).toFixed(2));
const summary = (route) =>
  `${label(route)}: ${route.distance_miles} mi, ${route.duration_hours} h, worst level ${worst(route)}, average risk ${avg(route)}.`;

// Which route is the question about? "route 2" in the text wins; otherwise the one selected on the map.
function pickRoute(question, result, selectedIndex) {
  const m = /route\s*#?\s*(\d+)/i.exec(question);
  if (m) {
    const found = result.routes.find((r) => r.index === Number(m[1]) - 1);
    if (found) return found;
  }
  return result.routes.find((r) => r.index === selectedIndex) ?? result.routes[0];
}

function whyRoute(result, route) {
  const rec = result.routes.find((r) => r.index === result.recommended_index);
  const reason = result.explanation ?? "";
  if (!rec) return reason || FALLBACK;
  if (route.index === rec.index) return [reason, summary(rec)].join("\n");
  const diff = route.duration_hours - rec.duration_hours;
  const timeLine =
    diff >= 0
      ? `${label(route)} takes ${diff.toFixed(1)} h longer than ${label(rec)}.`
      : `${label(route)} takes ${Math.abs(diff).toFixed(1)} h less than ${label(rec)}.`;
  return [
    `${label(route)} is not the recommended route; ${label(rec)} is.`,
    summary(route),
    summary(rec),
    timeLine,
    `The planner's reason for its pick: ${reason}`,
  ].join("\n");
}

function riskiest(route) {
  const known = route.checkpoints.filter((c) => rank(c.level) >= 0);
  if (known.length === 0) {
    return `${label(route)} has no checkpoints with weather data, so I cannot name a riskiest stretch.`;
  }
  const top = Math.max(...known.map((c) => rank(c.level)));
  const atTop = known.filter((c) => rank(c.level) === top);
  const first = atTop[0];
  const lines = [];
  if (top === 0) {
    lines.push(`Every checkpoint with data on ${label(route)} is Low, so no stretch stands out.`);
  } else {
    lines.push(
      `Highest risk on ${label(route)}: ${first.level}, first reached at mile ${first.mile} of ${route.distance_miles} ` +
        `(ETA ${formatLocal(first.eta_local)}, origin time). ${atTop.length} checkpoint(s) are at this level.`
    );
    lines.push(
      `Conditions there: wind ${num(first.wind_mph, "mph")} (gusts ${num(first.gust_mph, "mph")}), ` +
        `rain ${num(first.rain_in_hr, "in/hr")}, snow ${num(first.snow_in_hr, "in/hr")}.`
    );
    if (first.reasons && first.reasons.length > 0) lines.push(`Reasons: ${first.reasons.join("; ")}`);
  }
  const miles = unknownMiles(route);
  if (miles > 0) {
    lines.push(`Note: ${miles} mi of ${label(route)} has no weather data, so a worse stretch could be hiding there.`);
  }
  return lines.join("\n");
}

function compare(result) {
  const lines = result.routes.map((r) => {
    const tag = r.recommended ? " (recommended)" : "";
    return `${summary(r).replace(":", `${tag}:`)} Arrives ${formatLocal(r.arrival_local)}.`;
  });
  if (result.explanation) lines.push(result.explanation);
  return lines.join("\n");
}

function missing(result) {
  const lines = result.routes.map((r) => {
    const miles = unknownMiles(r);
    const pct = r.distance_miles > 0 ? Math.round((miles / r.distance_miles) * 100) : 0;
    return `${label(r)}: ${miles} mi without weather data (${pct}%).`;
  });
  lines.push("Where data is missing the risk shows as Unknown (grey), never Low, so risk may be understated there.");
  return lines.join("\n");
}

// These thresholds repeat backend/planner/core/risk.py, which is the source of truth. If risk.py changes, update this text and its test.
function levelsText() {
  return [
    `Risk levels, mildest to most severe: ${RANKED.join(", ")}.`,
    "Unknown (grey) means no usable weather data; it is never counted as Low.",
    "Each checkpoint takes the worst of its wind, rain and snow levels.",
    "Wind (mph): Moderate from 25, High from 35, Severe from 45, No Travel from 55.",
    "Rain (in/hr): Moderate from 0.10, High from 0.25, Severe from 0.50, No Travel above 1.00.",
    "Snow (in/hr): Moderate from 0.5, High from 1.0, Severe from 2.0, No Travel above 3.0.",
    "A load over 40,000 lb makes 35-44 mph wind Severe; over 30,000 lb makes 45-54 mph wind No Travel.",
    "Gusts are shown but not scored. Average risk uses a 0-4 scale: Low 0, Moderate 1, High 2, Severe 3, No Travel 4.",
    "Click any checkpoint dot on the map to see its wind, rain, snow and the reasons behind its level.",
  ].join("\n");
}

function rankingRule() {
  return [
    "Routes are ordered by: fewest No Travel miles, then fewest Severe miles, then fewest High miles, then lower average risk, then shorter travel time.",
    "Near-ties fall through to the next rule: differences under 1 mile, 0.02 average risk or 1 minute count as equal, so a trivial weather difference cannot beat a much faster route.",
    "The first route in that order is the recommended one. This panel only reads the result; it never changes it.",
  ].join("\n");
}

function arrival(result) {
  const lines = result.routes.map((r) => `${label(r)}: ${formatLocal(r.arrival_local)}`);
  lines.push("Times are clock time at the origin, as in the route cards.");
  return lines.join("\n");
}

function spacing(result) {
  const s = result.spacing;
  if (!s) return "This plan carries no checkpoint spacing information.";
  const lines = [`Checkpoints are every ${s.used} mi.`];
  if (s.used !== s.requested) {
    lines.push(`You asked for ${s.requested} mi; the server widened it so a long route stays within the weather-request budget.`);
  } else {
    lines.push("Long routes can be widened automatically to stay within the weather-request budget.");
  }
  if (result.notes && result.notes.length > 0) lines.push(`Notes from the server: ${result.notes.slice(0, 3).join(" | ")}`);
  return lines.join("\n");
}

// answerQuestion: picks an intent from keywords in the question and returns plain text (lines joined by \n).
export function answerQuestion(rawQuestion, result, selectedIndex) {
  if (!result || !result.routes || result.routes.length === 0) return "Plan a trip first, then ask me about the routes.";
  const question = String(rawQuestion ?? "").slice(0, MAX_QUESTION_CHARS);
  const text = question.toLowerCase();
  const tokens = text.split(/[^a-z0-9]+/).filter(Boolean);
  // Words must match whole tokens ("low" must not match "slow"); entries with a space match as phrases.
  const has = (words) => words.some((w) => (w.includes(" ") ? text.includes(w) : tokens.includes(w)));
  const route = pickRoute(question, result, selectedIndex);

  if (has(["missing", "no data", "unknown", "coverage", "incomplete", "partial"])) return missing(result);
  if (has(["rank", "ranked", "ranking", "order", "rules", "rule", "tie", "ties"])) return rankingRule();
  if (has(["level", "levels", "meaning", "mean", "means", "scale", "legend", "color", "colour", "colors", "colours"])) return levelsText();
  if (has(["spacing", "checkpoint", "checkpoints"])) return spacing(result);
  if (has(["arrive", "arrives", "arrival", "eta", "when"])) return arrival(result);
  if (has(["riskiest", "worst", "dangerous", "danger", "highest", "stretch", "where"])) return riskiest(route);
  if (has(["recommend", "recommended", "why", "best", "pick", "chosen", "choose"])) return whyRoute(result, route);
  if (has(["compare", "comparison", "versus", "vs", "difference", "differences", "safer", "safest", "faster", "fastest", "slower"])) return compare(result);
  return FALLBACK;
}
