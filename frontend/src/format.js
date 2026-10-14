// The API gives origin-local times like "2026-10-16T06:39-06:00". We show the clock time as written
// (origin time), without converting to the browser's time zone. Building the Date as UTC and
// formatting it as UTC keeps the digits unchanged.
export function formatLocal(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso ?? "");
  if (!m) return iso ?? "n/a";
  const [, y, mo, d, h, mi] = m.map(Number);
  return new Date(Date.UTC(y, mo - 1, d, h, mi)).toLocaleString("en-US", {
    timeZone: "UTC",
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}