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
  return plainBillText(value).replaceAll("_", " ");
}

/** Display source prose, never provider markup (including truncated anchors). */
export function plainBillText(value: string) {
  return value
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s*\(?\s*<\/?[a-z][\s\S]*$/i, "")
    .replace(/&(?:amp|lt|gt|quot|apos|nbsp);/g, entity => ({ "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'", "&nbsp;": " " })[entity]!)
    .replace(/\s+/g, " ").trim();
}

export function latestActionLabel(status: string) {
  const action = plainBillText(status);
  if (!/^referred to\b/i.test(action)) return action;
  // Committee names can contain commas. Split only at referral boilerplate.
  return action.split(/,\s*(?:(?:and\s+)?in addition to\b|for (?:a period|consideration)\b)/i, 1)[0];
}

export function dateLabel(value: string | null) {
  if (!value) return "Not recorded";
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00Z` : value);
  return Number.isNaN(date.getTime())
    ? "Not recorded"
    : date.toLocaleDateString(undefined, { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
}

/** 119 → "119th", 101 → "101st", 112 → "112th". */
export function ordinal(value: number) {
  const mod100 = value % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${value}th`;
  return `${value}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[value % 10] ?? "th"}`;
}
