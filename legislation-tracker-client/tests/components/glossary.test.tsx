import { describe, expect, it } from "vitest";
import definitions from "../fixtures/hr7583-definitions.json";
import { buildGlossary } from "../../lib/glossary";
import type { LegalNlpDefinitionItem } from "../../lib/contracts";
import { render, screen } from "@testing-library/react";
import { GlossaryEntryView } from "../../app/bills/[id]/bill-brief";

describe("H.R. 7583 glossary", () => {
  const source = definitions as LegalNlpDefinitionItem[];
  it.each(["includes", "excludes"] as const)("preserves %s in explanations and legal text", definition_type => {
    const item = { ...source[0], term: "eligible worker", definition_type, definition: "an independent contractor" };
    const entry = buildGlossary([item])[0];
    const prefix = definition_type === "includes" ? "Includes:" : "Excludes:";
    expect(entry.explanation).toBe(`${prefix} an independent contractor.`);
    render(<GlossaryEntryView entry={entry} contractId={10} document={null} />);
    expect(screen.getByText(`${prefix} an independent contractor`)).toBeInTheDocument();
  });
  it("does not apply affirmative rewrites to exclusions or merge legal operators", () => {
    const items = (["means", "includes", "excludes"] as const).map((definition_type, i) => ({
      ...source[0], id: `operator-${i}`, definition_type,
      definition: "meets the burdens of production and persuasion",
    }));
    const entries = buildGlossary(items);
    expect(entries).toHaveLength(3);
    expect(entries[2].explanation).toBe("Excludes: meets the burdens of production and persuasion.");
  });
  it.each(["includes", "excludes"] as const)("retains %s for long definitions and unresolved references", definition_type => {
    const long = buildGlossary([{ ...source[0], definition_type, definition: "a qualifying worker ".repeat(30) }])[0];
    expect(long.explanation).toContain(` ${definition_type} `);
    const reference = buildGlossary([{ ...source[0], definition_type,
      definition: "the meaning given in section 101 of the Education Act of 1965" }])[0];
    expect(reference.explanation).toContain(definition_type);
    expect(reference.explanation).toContain("has not been verified");
  });
  it("merges identical meanings but retains every source and distinct scope", () => {
    const entries = buildGlossary(source);
    expect(entries).toHaveLength(30);
    expect(entries.find(e => e.term === "Commission")?.sources).toHaveLength(3);
    expect(entries.filter(e => e.term === "worker")).toHaveLength(3);
    expect(entries.filter(e => e.term === "worker").every(e => e.scopes.length > 0)).toBe(true);
    expect(entries.flatMap(e => e.sources).map(s => s.id).sort()).toEqual(source.map(s => s.id).sort());
  });
  it("keeps qualifications, financial thresholds and unresolved references visible", () => {
    const entries = buildGlossary(source);
    expect(entries.find(e => e.term === "covered contract")?.explanation).toContain("more than $500,000");
    expect(entries.find(e => e.term === "covered client")?.explanation).toContain("eligible client");
    expect(entries.find(e => e.term === "covered client")?.explanation).toContain("and");
    expect(entries.find(e => e.term === "program or activity")?.explanation).toContain("another law");
    expect(entries.find(e => e.term === "predispute arbitration agreement")?.explanation).toContain("elsewhere in this bill");
    expect(entries.every(e => !e.explanation.includes("[[QUOTED_BLOCK"))).toBe(true);
    expect(entries.every(e => e.explanation.split(/\s+/).length <= 65)).toBe(true);
  });
});
