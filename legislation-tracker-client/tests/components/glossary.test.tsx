import { describe, expect, it } from "vitest";
import definitions from "../fixtures/hr7583-definitions.json";
import { buildGlossary } from "../../lib/glossary";
import type { LegalNlpDefinitionItem } from "../../lib/contracts";

describe("H.R. 7583 glossary", () => {
  const source = definitions as LegalNlpDefinitionItem[];
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
