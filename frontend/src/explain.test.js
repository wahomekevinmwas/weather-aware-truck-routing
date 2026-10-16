// Offline tests for explain.js. Run with: node --test src/explain.test.js (from the frontend folder).
import test from "node:test";
import assert from "node:assert/strict";
import { answerQuestion, PRESETS } from "./explain.js";

const cp = (mile, level, extra = {}) => ({
  mile, lat: 0, lon: 0, level, eta_local: "2026-10-17T12:00-06:00",
  wind_mph: 10, gust_mph: 20, rain_in_hr: 0, snow_in_hr: 0, reasons: [], ...extra,
});

const plan = {
  recommended_index: 0,
  explanation: "Route 1 wins on weather.",
  spacing: { used: 25, requested: 25 },
  notes: [],
  routes: [
    {
      index: 0, recommended: true, distance_miles: 500, duration_hours: 8, arrival_local: "2026-10-17T20:00-06:00",
      stats: { worst_level: "Low", average_risk: 0, miles_by_level: { Low: 500 } },
      checkpoints: [cp(0, "Low"), cp(250, "Low")],
    },
    {
      index: 1, recommended: false, distance_miles: 500, duration_hours: 10, arrival_local: "2026-10-17T22:00-06:00",
      stats: { worst_level: "High", average_risk: 1.2, miles_by_level: { Low: 300, High: 100, Unknown: 100 } },
      checkpoints: [cp(0, "Low"), cp(125, "High", { reasons: ["Heavy rain"], rain_in_hr: 0.3 }), cp(250, "Unknown")],
    },
  ],
};

test("no plan yet asks the user to plan a trip", () => {
  assert.match(answerQuestion("hello", null, 0), /Plan a trip first/);
});

test("why on the recommended route returns the planner explanation", () => {
  assert.match(answerQuestion("Why is this route recommended?", plan, 0), /Route 1 wins on weather/);
});

test("why on another route says which route is recommended", () => {
  assert.match(answerQuestion("Why is this route recommended?", plan, 1), /not the recommended route; Route 1 is/);
});

test("riskiest stretch reports the highest level, its mile, reasons and missing data", () => {
  const a = answerQuestion("Where is the riskiest stretch on route 2?", plan, 0);
  assert.match(a, /High/);
  assert.match(a, /mile 125/);
  assert.match(a, /Heavy rain/);
  assert.match(a, /no weather data/);
});

test("riskiest stretch on an all-Low route says nothing stands out", () => {
  assert.match(answerQuestion("Where is the riskiest stretch?", plan, 0), /no stretch stands out/);
});

test("missing data lists unknown miles and percent per route", () => {
  assert.match(answerQuestion("How much weather data is missing?", plan, 0), /Route 2: 100 mi without weather data \(20%\)/);
});

test("risk levels answer says Unknown is never Low", () => {
  assert.match(answerQuestion("What do the risk levels mean?", plan, 0), /never counted as Low/);
});

test("arrival answer lists every route", () => {
  const a = answerQuestion("When will I arrive?", plan, 0);
  assert.match(a, /Route 1/);
  assert.match(a, /Route 2/);
});

test("an off-topic weather question gets the fallback, not an invented answer", () => {
  assert.match(answerQuestion("Will it snow in Denver next week?", plan, 0), /only answer from the plan/);
});

test("every preset question is understood", () => {
  for (const p of PRESETS) {
    assert.doesNotMatch(answerQuestion(p, plan, 0), /only answer from the plan/, p);
  }
});

test("ranking answer mentions all three tie tolerances", () => {
  const a = answerQuestion("How are routes ranked?", plan, 0);
  assert.match(a, /1 mile/);
  assert.match(a, /0\.02/);
  assert.match(a, /1 minute/);
});
test("a very long question does not throw", () => {
  assert.doesNotThrow(() => answerQuestion("why ".repeat(5000), plan, 0));
});
