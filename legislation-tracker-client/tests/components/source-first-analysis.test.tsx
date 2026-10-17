import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import SourceFirstAnalysis from "@/app/bills/[id]/source-first-analysis";
import type { SourceFirstResult } from "@/lib/api";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const result: SourceFirstResult = {
  schema_version: "2.0-source-first", document_fingerprint: "pinned", pipeline_version: "test",
  synopsis: { text: "The bill creates a conditional benefit.", explanation_ids: ["u1"], status: "partial" },
  coverage: { unit_ids: ["u1", "u2"], unresolved_unit_ids: ["u2"], omitted_source_ranges: [], inventory_complete: false },
  quality: { mechanical_status: "partial", semantic_review_status: "unreviewed" },
  provisions: [{ id: "u1", unit_id: "u1", status: "explained", summary: "Eligible residents can receive assistance.", details: [], unresolved_reason: null,
    claims: [{ actor: "Residents", action: "receive assistance", modality: "permitted", money: [{ amount: null, currency: "USD", measure: "authorization", comparator: null, purpose: "Housing assistance", period: "2027", base: null }], conditions: { operator: "leaf", text: "has not abandoned residence", evidence_ids: ["p1"] }, exceptions: [], evidence_ids: ["p1"] }],
    evidence: [{ id: "p1", text: "An applicant who has not abandoned residence may receive assistance.", section_label: "Sec. 1", url: "/documents/511", start: 0, end: 80, text_sha256: "hash" }] },
    { id: "u2", unit_id: "u2", status: "unresolved", summary: "", details: [], claims: [], unresolved_reason: "conditions_unverified", evidence: [{ id: "p2", text: "Complete unresolved provision.", section_label: "Sec. 2", url: "/documents/511", start: 80, end: 110, text_sha256: "hash2" }] }],
};

it("shows partial coverage, complete conditions, unknown money and pinned sources", async () => {
  const user = userEvent.setup();
  render(<SourceFirstAnalysis result={result} />);
  expect(screen.getByText(/1 of 2 provisions explained/)).toBeVisible();
  expect(screen.getByText("The bill creates a conditional benefit.")).toBeVisible();
  await user.click(screen.getByText("All rules and requirements (1)"));
  expect(screen.getByText("has not abandoned residence")).toBeVisible();
  expect(screen.getByText("Amount not specified")).toBeVisible();
  expect(screen.getByText("Housing assistance")).toBeVisible();
  expect(screen.getAllByText("Permitted: Residents — receive assistance").some(node => node.closest("details") === null)).toBe(true);
  await user.click(screen.getAllByText("Source text")[0]);
  expect(screen.getAllByRole("link", { name: "Read source" })[0]).toHaveAttribute("href", "/documents/511");
  expect(screen.getByText("This provision needs review.")).toBeVisible();
});

it("makes every operative claim accessible and preserves prohibitions", async () => {
  const example = structuredClone(result);
  example.provisions[0].claims.push({ actor: "Secretary", action: "refer an applicant for enforcement", modality: "prohibited", conditions: null, exceptions: [], money: [], evidence_ids: ["p1"] });
  example.provisions[0].claims.push({ actor: "Secretary", action: "close the case on withdrawal", modality: "required", conditions: null, exceptions: [], money: [], evidence_ids: ["p1"] });
  render(<SourceFirstAnalysis result={example} />);
  await userEvent.click(screen.getByText("All rules and requirements (3)"));
  expect(screen.getByText("Prohibited: Secretary — refer an applicant for enforcement")).toBeVisible();
  expect(screen.getByText("Required: Secretary — close the case on withdrawal")).toBeVisible();
});

it("discloses outside-law limits even when every explicit rule was explained", async () => {
  const limited = structuredClone(result);
  limited.coverage.unresolved_unit_ids = [];
  limited.coverage.context_limited_unit_ids = ["u1"];
  limited.provisions = [limited.provisions[0]];
  limited.provisions[0].source_limitations = ["section 10 of the Other Act"];
  render(<SourceFirstAnalysis result={limited} />);
  expect(screen.getByText(/does not explain the referenced outside law/)).toBeVisible();
  await userEvent.click(screen.getByText("Referenced law not included"));
  expect(screen.getByText("section 10 of the Other Act")).toBeVisible();
  expect(screen.getByText("Eligible residents can receive assistance.")).toBeVisible();
});

it("renders the real S5 benchmark with distinct harm thresholds and correctly scoped custody", async () => {
  const artifact = JSON.parse(readFileSync(resolve(process.cwd(), "../docs/benchmarks/bill-understanding/claim-repair-v14-20261016-205111-BILLS-119s5enr.json"), "utf8"));
  const saved = artifact.result.output as SourceFirstResult;
  render(<SourceFirstAnalysis result={saved} />);
  expect(screen.getByText(/5 financial items shown/)).toBeVisible();
  expect(screen.getAllByText("more than USD 100")).toHaveLength(5);
  expect(screen.getByText(/harm thresholds, not funding allocations/)).toBeVisible();
  const conditions = screen.getAllByText(/All rules and requirements/)[1];
  await userEvent.click(conditions);
  const panel = conditions.closest("details")!;
  expect(panel.textContent).toContain("take custody");
  const custody = Array.from(panel.querySelectorAll("li")).find(node => node.textContent?.includes("take custody"))!;
  expect(custody.textContent).not.toContain("issue a detainer");
  expect(panel.textContent).toContain("not otherwise detained");
  await userEvent.click(screen.getAllByText("Source text")[1]);
  expect(screen.getByText(/shall issue a detainer/)).toBeVisible();
});

it("renders the corrected H.R. 1589 fine as mandatory and travel limits as nonfinancial", async () => {
  const load = (name: string) => JSON.parse(readFileSync(resolve(process.cwd(), `../docs/benchmarks/bill-understanding/${name}`), "utf8")).result.output as SourceFirstResult;
  const saved = load("claim-repair-v17-low-20261016-211934-BILLS-119hr1589ih.json");
  const travel = load("claim-repair-v16-low-20261016-211507-BILLS-119hr1589ih.json").provisions.find(p => p.evidence[0].section_label.startsWith("Sec. 304"))!;
  const fine = saved.provisions.find(p => p.evidence[0].section_label.startsWith("Sec. 309"))!;
  expect(travel.status).toBe("explained");
  expect(fine.status).toBe("explained");
  saved.provisions = [travel, fine];
  saved.coverage.unresolved_unit_ids = [];
  saved.synopsis = { text: "", explanation_ids: [], status: "unavailable" };
  render(<SourceFirstAnalysis result={saved} />);
  expect(screen.getByText(/1 financial items shown/)).toBeVisible();
  expect(screen.getByText("not more than USD 10000")).toBeVisible();
  expect(screen.getByText(/A person who knowingly.*must be fined up to \$10,000/)).toBeVisible();
  expect(screen.getAllByText("Required: person — must be fined not more than $10,000").some(node => node.closest("details") === null)).toBe(true);
  expect(screen.getByText(/continuous physical presence fails.*90 days.*180 days/)).toBeVisible();
  expect(screen.queryByText("Purpose needs source review")).not.toBeInTheDocument();
});
