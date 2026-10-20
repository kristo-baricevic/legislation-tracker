import type { LegalNlpDefinitionItem } from "./contracts";

export interface GlossaryEntry {
  term: string;
  explanation: string;
  scopes: string[];
  sources: LegalNlpDefinitionItem[];
}

export function cleanDefinition(text: string): string {
  return text.replace(/\[\[QUOTED_BLOCK_(?:START|END)\]\]/g, "")
    .replace(/\s+/g, " ").replace(/(?:\.\s*){2,}/g, ".").trim().replace(/[.;]+$/, "");
}

export function legalDefinition(item: LegalNlpDefinitionItem): string {
  const text = cleanDefinition(item.definition);
  return item.definition_type === "includes" ? `Includes: ${text}`
    : item.definition_type === "excludes" ? `Excludes: ${text}` : text;
}

function explain(item: LegalNlpDefinitionItem): string {
  const text = cleanDefinition(item.definition);
  // Affirmative paraphrases are valid only for "means". Preserve inclusion
  // and exclusion operators rather than silently turning either into identity.
  if (item.definition_type !== "means") {
    if (/meaning given|meaning provided|meaning assigned/i.test(text)) {
      const external = /United States Code|U\.S\.C\.|Act of \d{4}/i.test(text);
      return `This provision ${item.definition_type} a category defined ${external ? "in another law" : "elsewhere in this bill"}. The referenced meaning has not been verified here.`;
    }
    if (item.definition_type === "includes" && text.startsWith("a report prepared by an employer") && text.includes("any such similar record")) {
      return "Includes discrimination-investigation reports, employment statistics about protected characteristics, referenced labor-law records, and similar records needed for this subtitle.";
    }
    if (text.split(/\s+/).length <= 65) return legalDefinition(item) + ".";
    return `This provision ${item.definition_type} the categories listed in the legal definition. Open it below for the complete scope and conditions.`;
  }
  if (/meaning given|meaning provided|meaning assigned/i.test(text)) {
    const external = /United States Code|U\.S\.C\.|Act of \d{4}/i.test(text);
    return `Defined ${external ? "in another law" : "elsewhere in this bill"}. The referenced meaning has not been verified here.`;
  }
  const rewrites: Record<string, string> = {
    "meets the burdens of production and persuasion": "Requires both supporting evidence and persuasion of the decision-maker.",
    "a provision in a contract or agreement establishing that each party to the contract or agreement agrees not to disclose information covered by the terms and conditions of the contract or agreement": "A contract term in which each party agrees not to share the information covered by the agreement.",
    "a provision in a contract or agreement requiring one or more parties to the contract or agreement not to make negative statements about another such party": "A contract term that bars one or more parties from making negative statements about another party.",
    "any agreement to arbitrate a dispute that arose before the time of the making of the agreement": "An agreement to use arbitration made after the dispute has already arisen.",
    "a Federal contract for the procurement of property or services, including construction, valued in excess of $500,000": "A federal contract worth more than $500,000 to buy property or services, including construction.",
  };
  if (Object.hasOwn(rewrites, text)) return rewrites[text];
  if (text.split(/\s+/).length <= 65) return text.charAt(0).toUpperCase() + text.slice(1) + ".";
  // These are previews, not replacement eligibility rules. Match the source
  // wording rather than guessing a meaning from a term's name alone.
  if (text.startsWith("an individual or entity that— is not acting as an employer") &&
      text.includes("intern, fellow, volunteer, or trainee") && text.includes("interstate commerce")) {
    return "A person or organization outside the employer/entity coverage specified in subsection (a) that engages or solicits an independent contractor, intern, fellow, volunteer, or trainee. The services must have the interstate transportation or communication connection described in the legal definition.";
  }
  if (text.startsWith("an employee (including an applicant), as defined in section")) {
    return "Employees and job applicants in the civil-rights and government-employment categories listed in the bill. The referenced laws determine which categories qualify.";
  }
  if (text.startsWith("an employer (as defined in section")) {
    return "Employers and employing offices covered by the listed civil-rights and government-employment laws. Coverage depends on the legal category, not simply on employing someone.";
  }
  if (text.startsWith("in the case of an individual required to be afforded protections under section 301")) {
    return "People entitled to protections under section 301(a) through the listed employer categories, or under section 301(b) through a covered establishment.";
  }
  if (text.startsWith("discrimination that is in violation of applicable Federal, State, or local employment law, including")) {
    return "Discrimination that violates applicable federal, state, or local employment law. The legal definition lists the laws covered.";
  }
  if (text.startsWith("any of the following: A nonprofit organization") && text.includes("An institution of higher education")) {
    return "Qualifying nonprofits that provide services and support to workers, or higher-education institutions as defined in the referenced law. See the full definition for the categories and requirements.";
  }
  return "This term has a detailed legal definition. Open it below to check the complete requirements; no simplified meaning has been verified.";
}

export function buildGlossary(items: LegalNlpDefinitionItem[]): GlossaryEntry[] {
  const groups = new Map<string, GlossaryEntry>();
  for (const item of items) {
    // Keep references and distinct legal operators (means/includes) separate.
    const key = JSON.stringify([item.term.trim().toLowerCase(), item.definition_type, cleanDefinition(item.definition)]);
    const scope = item.section_path.filter(p => ["title", "subtitle", "section"].includes(p.level))
      .map(p => `${p.label}${p.heading ? `: ${p.heading}` : ""}`).join(" · ");
    const entry = groups.get(key) ?? { term: item.term, explanation: explain(item), scopes: [], sources: [] };
    if (!entry.sources.some(s => s.id === item.id)) entry.sources.push(item);
    if (scope && !entry.scopes.includes(scope)) entry.scopes.push(scope);
    groups.set(key, entry);
  }
  return [...groups.values()].sort((a, b) => a.term.localeCompare(b.term));
}
