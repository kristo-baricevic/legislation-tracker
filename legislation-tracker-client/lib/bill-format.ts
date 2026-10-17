// Shared display helpers for the card dashboard and the recommendations row.
// Keep these free of path aliases so node's strip-types test runner can import them.

/** Number of topic hues defined as --topic-0 … --topic-9 in globals.css. */
export const TOPIC_COLOR_COUNT = 10;

/**
 * A stable colour per topic id. Returns a CSS variable so the light and dark
 * themes each get a hue tuned for their own surface (see globals.css).
 * The same topic id gets the same colour everywhere it appears.
 */
export function topicColor(id: number) {
  return `var(--topic-${Math.abs(id) % TOPIC_COLOR_COUNT})`;
}

export function readable(value: string) {
  return value.replaceAll("_", " ");
}

export function dateLabel(value: string | null) {
  if (!value) return "Not recorded";
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value);
  return Number.isNaN(date.getTime())
    ? "Not recorded"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** 119 → "119th", 101 → "101st", 112 → "112th". */
export function ordinal(value: number) {
  const mod100 = value % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${value}th`;
  return `${value}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[value % 10] ?? "th"}`;
}
