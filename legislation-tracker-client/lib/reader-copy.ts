import type { LegalNlpLineItem } from "./contracts";
import { cleanLegislativeText } from "./reader-guide";

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const words = (text: string) => text.trim().split(/\s+/).length;

function plainWording(text: string) {
  // Quoted wording can be an exact legal term or amendment instruction.
  // Leave the entire statement intact rather than reinterpret its fragments.
  if (/[“”"]/.test(text)) return text;
  return text
    .replace(/award, on a competitive basis, grants/g, "award competitive grants")
    .replace(/at such time, in such manner, and containing the information required under (?:subsection|section) (?:\([a-zA-Z0-9]+\)|[0-9]+)(?:\([a-zA-Z0-9]+\))*/g, "following the required timing, format, and information rules")
    .replace(/^An eligible entity(?: or eligible Indian entity)? desiring a grant under this Act must submit an application to (.+?) following the required timing, format, and information rules\.$/, "Applicants that qualify for a grant must apply to $1 and follow the required timing, format, and information rules.")
    .replace(/^From the total amount appropriated to carry out this Act for a fiscal year, (.+?) must reserve (\d+(?:\.\d+)?) percent for (.+)$/, (_, actor: string, amount: string, purpose: string) => `${capitalize(actor)} must set aside ${amount}% of the money appropriated under this bill for that year for ${purpose}`);
}

/** Presentation only: never mutate contract text or the identity used by AI citations. */
export function changeCopy(item: LegalNlpLineItem) {
  let text = cleanLegislativeText(item.display_text);
  if (item.actor && item.action && ["requirement", "permission"].includes(item.kind)) {
    const prefix = `${item.kind === "requirement" ? "Requires" : "Allows"} ${item.actor} to ${item.action}`;
    // Do not reinterpret malformed slots or a prefix of another word.
    if (item.display_text.startsWith(prefix) && /^(?:[\s.,;:]|$)/.test(item.display_text.slice(prefix.length))) {
      text = cleanLegislativeText(`${capitalize(item.actor)} ${item.kind === "requirement" ? "must" : "may"} ${item.action}${item.display_text.slice(prefix.length)}`);
    }
  }
  if (item.kind !== "amendment") text = plainWording(text);
  const headings = item.section_path.map(p => cleanLegislativeText(p.heading || ""))
    .filter(h => h && !/^(in general|general rule|definitions?)$/i.test(h));
  const heading = headings.reverse().find(h => words(h) <= 10);
  const labels = { purpose: "Purpose", requirement: "Requirements", prohibition: "Restrictions", permission: "What is allowed", amendment: "Changes to existing law", applicability: "Who is covered", financial: "Funding", timeline: "Timing" };
  const plainHeadings: Record<string, string> = { "short title": "Bill name", "grant authorization": "Awarding grants", "notification and application": "How to apply", "content of application": "What applicants must provide", "effective date": "When it starts", "authorization of appropriations": "Funding allowed", "reservation of funds": "Reserved funding" };
  const title = heading ? plainHeadings[heading.toLowerCase()] ?? capitalize(heading) : labels[item.kind];
  text = cleanLegislativeText(item.reader_text || text);
  if (item.kind !== "amendment") text = plainWording(text);
  return { title, text };
}

/** Keep all conditions visible. Paragraph boundaries are presentation, not omissions. */
export function explanationParagraphs(text: string): string[] {
  const display = text.replace(/\[\[QUOTED_BLOCK_(?:START|END)\]\]/g, " ");
  return Array.from(new Intl.Segmenter("en", { granularity: "sentence" }).segment(display.trim()), s => s.segment.replace(/ {2,}/g, " ").trim()).filter(Boolean);
}
