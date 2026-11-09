import { describe, expect, it } from "vitest";
import { changeCopy, explanationParagraphs } from "@/lib/reader-copy";
import type { LegalNlpLineItem } from "@/lib/contracts";

const item = (overrides: Partial<LegalNlpLineItem>): LegalNlpLineItem => ({
  id: "x", source_id: "s", section_id: "sec", section_path: [{ level: "section", label: "Sec. 1", heading: "Grant authorization" }],
  kind: "requirement", actor: "the Secretary", action: "award competitive grants", effect: null,
  display_text: "Requires the Secretary to award competitive grants.", exact_financial_count: 0, exact_financial_preview: [], timeline_count: 0, timeline_preview: [], definition_count: 0,
  ...overrides,
});

describe("shared change copy", () => {
  it("removes internal markers from saved reader explanations without altering the stored source", () => {
    const text = "Section 1 is amended by inserting the following: [[QUOTED_BLOCK_START]]Workers must report annually.[[QUOTED_BLOCK_END]]";
    const source = item({ reader_text: text });
    expect(changeCopy(source).text).toBe("Section 1 is amended by inserting the following: Workers must report annually.");
    expect(source.reader_text).toBe(text);
    expect(explanationParagraphs(text).join(" ")).toBe("Section 1 is amended by inserting the following: Workers must report annually.");
  });
  it("does not swallow exceptions after an application cross-reference", () => {
    const text = "Applicants must apply at such time, in such manner, and containing the information required under subsection (c), unless exempt under section 9.";
    expect(changeCopy(item({ display_text: text })).text).toBe("Applicants must apply following the required timing, format, and information rules, unless exempt under section 9.");
  });
  it("simplifies grant-application boilerplate without naming a particular bill", () => {
    const result = changeCopy(item({ actor: "An eligible entity desiring a grant under this Act", action: "submit an application to the Secretary at such time, in such manner, and containing the information required under subsection (c)", display_text: "Requires An eligible entity desiring a grant under this Act to submit an application to the Secretary at such time, in such manner, and containing the information required under subsection (c)." }));
    expect(result.text).toBe("Applicants that qualify for a grant must apply to the Secretary and follow the required timing, format, and information rules.");
  });
  it("explains reservation as a share of annual funding, not an invented dollar cost", () => {
    const result = changeCopy(item({ actor: "From the total amount appropriated to carry out this Act for a fiscal year, the Secretary", action: "reserve 2 percent for grants to eligible Indian entities", display_text: "Requires From the total amount appropriated to carry out this Act for a fiscal year, the Secretary to reserve 2 percent for grants to eligible Indian entities." }));
    expect(result.text).toBe("The Secretary must set aside 2% of the money appropriated under this bill for that year for grants to eligible Indian entities.");
  });
  it("explains a grant duty directly without changing its budget years", () => {
    const result = changeCopy(item({ actor: "For each of fiscal years 2027 through 2032, the Secretary", display_text: "Requires For each of fiscal years 2027 through 2032, the Secretary to award competitive grants." }));
    expect(result.text).toBe("For each of fiscal years 2027 through 2032, the Secretary must award competitive grants.");
    expect(result.title).toBe("Awarding grants");
  });
  it("keeps tax amounts, percentage bases and exceptions intact", () => {
    const text = "Requires employers to pay 20% of wages unless the employee is exempt.";
    expect(changeCopy(item({ actor: "employers", action: "pay 20% of wages", display_text: text })).text).toBe("Employers must pay 20% of wages unless the employee is exempt.");
  });
  it("does not guess when stored actor slots disagree with the source-bound explanation", () => {
    expect(changeCopy(item({ display_text: "No agency may collect a fee unless authorized by law." })).text).toBe("No agency may collect a fee unless authorized by law.");
  });
  it("does not change prohibition wording or infer an amendment's legal effect", () => {
    for (const text of ["Prohibits agencies from collecting fees.", "Changes section 3 by striking paragraph (2)."])
      expect(changeCopy(item({ display_text: text })).text).toBe(text);
  });
  it("preserves the entire explanation when showing a shorter complete sentence", () => {
    const text = "Colleges must report their results. " + "The report must include participation, retention and graduation results for each student group, describe how funding was used, explain differences between groups, identify unmet goals and describe changes planned for the following year, including how the college will evaluate those changes and address any remaining barriers to student success.";
    const result = explanationParagraphs(text);
    expect(result[0]).toBe("Colleges must report their results.");
    expect(result.join(" ")).toBe(text);
  });
  it("keeps a condition attached rather than exposing the first sentence as unconditional", () => {
    const text = "Agencies may collect fees. However, this permission applies only when " + "the applicant qualifies under the requirements in this section and the agency has completed the required review. ".repeat(4);
    expect(explanationParagraphs(text)[1]).toMatch(/^However, this permission applies only when/);
    expect(explanationParagraphs(text).join(" ")).toBe(text.trim());
  });
});
