// Freshness is the product's whole claim, so it is rendered as an age rather
// than a calendar date everywhere it appears. "3 hours ago" carries the claim;
// "8/18/2026" is the least persuasive possible rendering of the same fact.
//
// Mirrors humanAge in backend/internal/server/digest.go, which does the same job
// for the email, where no JavaScript runs.
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";

  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return "just now";

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return plural(minutes, "min");

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return plural(hours, "hour");

  const days = Math.floor(hours / 24);
  if (days < 30) return plural(days, "day");

  return new Date(then).toLocaleDateString();
}

function plural(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
}
