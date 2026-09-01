import type {
  LegalNlpFinancialItem,
  LegalNlpLineItem,
  LegalNlpSectionPathItem,
} from "@/lib/contracts";

const topicExplanations: Record<string, string> = {
  agriculture: "Changes nutrition assistance or agricultural programs.",
  budget: "Changes federal spending, revenue, or budget rules.",
  "budget & taxation": "Changes federal spending, revenue, and tax rules.",
  defense: "Changes military programs, operations, or funding.",
  education: "Changes education programs, student aid, or school funding.",
  energy: "Changes energy production, regulation, or assistance programs.",
  "economy & finance": "Changes financial programs, economic policy, or federal support for businesses and households.",
  environment: "Changes environmental protections, land use, or conservation programs.",
  health: "Changes health-care programs, coverage, funding, or administration.",
  immigration: "Changes immigration policy, border operations, or enforcement.",
  taxation: "Changes individual, family, or business tax rules.",
};

const overviewTopicNames: Record<string, string> = {
  agriculture: "nutrition and agriculture",
  budget: "the federal budget",
  "budget & taxation": "the federal budget and taxes",
  defense: "defense",
  education: "education",
  energy: "energy",
  "economy & finance": "the economy and financial policy",
  environment: "environmental policy",
  health: "health policy",
  immigration: "immigration and border policy",
  taxation: "taxes",
};

const genericHeadings = new Set([
  "appropriations",
  "authorization of appropriations",
  "funding",
  "general provisions",
  "miscellaneous",
]);

export function cleanLegislativeText(value: string): string {
  return value
    .replace(/<<NOTE:[\s\S]*?(?:>>|$)/gi, " ")
    .replace(/\[\[Page[^\]]*\]\]/gi, " ")
    .replace(/\[\[[^\]]*\]\]/g, " ")
    .replace(/\s+/g, " ")
    .replace(/^[-–—;:,.)\s]+/, "")
    .trim();
}

function sentenceCase(value: string): string {
  const cleaned = cleanLegislativeText(value);
  if (!cleaned) return cleaned;
  if (cleaned === cleaned.toUpperCase()) {
    const minorWords = new Set(["a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to"]);
    return cleaned.toLowerCase().split(" ").map((word, index) => {
      if (index > 0 && minorWords.has(word)) return word;
      return word.charAt(0).toUpperCase() + word.slice(1);
    }).join(" ");
  }
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function joinNatural(values: string[]): string {
  if (values.length <= 1) return values[0] ?? "federal policy";
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values.at(-1)}`;
}

export function readerOverview(
  jurisdiction: string,
  status: string,
  topicNames: string[],
): string {
  const subject = status.toLowerCase().includes("public law") ? "law" : "bill";
  const areas = topicNames.map((name) => overviewTopicNames[name.toLowerCase()] ?? name.toLowerCase());
  if (areas.length === 1) {
    return `This ${jurisdiction} ${subject} changes ${areas[0]}.`;
  }
  return `This ${jurisdiction} ${subject} changes policy across ${joinNatural(areas)}.`;
}

export function topicExplanation(name: string): string {
  return topicExplanations[name.toLowerCase()] ?? `Contains provisions related to ${name.toLowerCase()}.`;
}

export function isReaderReady(item: LegalNlpLineItem): boolean {
  const fields = [item.display_text, item.actor, item.action, item.effect].filter(
    (value): value is string => Boolean(value),
  );
  if (fields.some((value) => /<<|\[\[|\]\]/.test(value))) return false;
  const display = cleanLegislativeText(item.display_text);
  if (display.length < 18 || !/[a-z]{3}/i.test(display)) return false;
  return !/^(?:section|subsection|paragraph|clause)\s+[\w().-]+\.?$/i.test(display);
}

export function readablePath(path: LegalNlpSectionPathItem[]): string {
  const prepared = path.map((item) => {
    const heading = item.heading ? sentenceCase(item.heading) : "";
    const usefulHeading = heading && !/\b(?:for|of|to|and|or)$/i.test(heading) ? heading : null;
    return { ...item, heading: usefulHeading };
  });
  const meaningful = prepared.filter((item) => item.heading);
  const selected = meaningful.length > 0
    ? meaningful.slice(-2)
    : prepared.filter((item) => item.level === "title" || item.level === "section").slice(-2);
  return selected
    .map((item) => item.heading ? `${item.label}: ${item.heading}` : item.label)
    .join(" · ");
}

export function financialPurpose(item: LegalNlpFinancialItem): string {
  const purpose = item.purpose ? cleanLegislativeText(item.purpose) : "";
  const normalizedPurpose = purpose.toLowerCase().replace(/[.:;]+$/, "");
  const genericPurpose = /^(?:carry out|implementation of|for purposes of)\b/i;
  const danglingPurpose = /\b(?:for|of|to|and|or)$/i;
  if (purpose && !genericPurpose.test(purpose) && !genericHeadings.has(normalizedPurpose) && !danglingPurpose.test(purpose)) return sentenceCase(purpose);

  for (const part of [...item.section_path].reverse()) {
    if (!part.heading) continue;
    const heading = cleanLegislativeText(part.heading);
    const normalizedHeading = heading.toLowerCase().replace(/[.:;]+$/, "");
    if (heading && !genericHeadings.has(normalizedHeading) && !danglingPurpose.test(heading)) return sentenceCase(heading);
  }
  return "Purpose not clear from the extracted text";
}

export function isUnhelpfulOfficialTitle(title: string): boolean {
  return /provide for reconciliation pursuant to/i.test(title);
}
