export function representativeDisplayName(name: string): string {
  const clean = name
    .replace(/^(?:Rep\.|Sen\.|Del\.|Resident Commissioner)\s*/i, "")
    .replace(/\[[^\]]*\]/g, "")
    .replace(/\([^)]*\)/g, "")
    .trim();
  const [last, ...given] = clean.split(",");
  return (given.length ? `${given.join(" ").trim()} ${last.trim()}` : clean).replace(/\s+/g, " ").trim();
}

export function representativeInitials(name: string): string {
  const parts = representativeDisplayName(name).split(/\s+/)
    .filter(part => /\p{L}/u.test(part) && !/^(?:Jr\.?|Sr\.?|II|III|IV)$/i.test(part));
  const first = (part: string | undefined) => part?.match(/\p{L}/u)?.[0] ?? "";
  return (first(parts[0]) + (parts.length > 1 ? first(parts.at(-1)) : "")).toUpperCase() || "?";
}
