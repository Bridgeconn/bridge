/**
 * "5 min ago" for a timestamp, for a glance at how recent something is. The
 * exact time belongs in a tooltip or a details row beside it.
 *
 * Returns "" for a missing or unreadable timestamp. A time slightly in the
 * future (clock skew between devices) reads as "just now".
 */
const STEPS: readonly [limit: number, size: number, one: string, many: string][] = [
  [60, 1, "sec", "sec"],
  [3600, 60, "min", "min"],
  [86400, 3600, "hr", "hr"],
  [604800, 86400, "day", "days"],
  [2629800, 604800, "week", "weeks"],
  [31557600, 2629800, "month", "months"],
  [Infinity, 31557600, "year", "years"],
];

export function relativeTime(value: string | number | Date | null | undefined, now: number = Date.now()): string {
  if (value === null || value === undefined || value === "") return "";
  const at = value instanceof Date ? value.getTime() : typeof value === "number" ? value : Date.parse(value);
  if (!Number.isFinite(at)) return "";
  const seconds = Math.floor((now - at) / 1000);
  if (seconds < 1) return "just now";
  for (const [limit, size, one, many] of STEPS) {
    if (seconds < limit) {
      const count = Math.floor(seconds / size);
      return `${count} ${count === 1 ? one : many} ago`;
    }
  }
  return "";
}
