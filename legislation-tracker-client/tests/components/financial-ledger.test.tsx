import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinancialLedger } from "@/app/bills/[id]/financial-ledger";
import { getFinancialItems } from "@/lib/api";
import type { LegalNlpFinancialItem } from "@/lib/contracts";
import { isLegalNlpFinancialItem } from "@/lib/contracts";

vi.mock("@/lib/api", () => ({
  getApiBase: () => "http://localhost:8000",
  getContractEvidence: vi.fn(),
  getFinancialItems: vi.fn(),
}));

const path = [{ level: "section" as const, label: "Sec. 4", heading: "Funding" }];

function item(id: string, financial_action: LegalNlpFinancialItem["financial_action"], direction: LegalNlpFinancialItem["direction"]): LegalNlpFinancialItem {
  return {
    id,
    source_id: id,
    section_id: "section-4",
    section_label: "Sec. 4",
    section_path: path,
    display_text: `${financial_action} provision ${id}`,
    financial_action,
    direction,
    amount: "1000000.00",
    amount_type: "specified",
    currency: "USD",
    fiscal_years: [2027],
    purpose: "the program",
    source_account: null,
    destination_account: null,
  };
}

describe("FinancialLedger", () => {
  beforeEach(() => vi.clearAllMocks());

  it("displays fees and exemptions separately from spending", async () => {
    const records = [
      { ...item("financial-1", "fee", "not_applicable"), amount: "495.00", amount_type: "ceiling" as const, display_text: "The application fee must not exceed $495.", purpose: "application processing" },
      { ...item("financial-2", "fee_exemption", "not_applicable"), amount: null, currency: null, amount_type: "unspecified" as const, display_text: "An applicant may be exempted from paying a fee.", purpose: "fee exemptions" },
    ];
    for (const record of records) expect(isLegalNlpFinancialItem(record)).toBe(true);
    vi.mocked(getFinancialItems).mockResolvedValue({ count: 2, next: null, previous: null, results: records });
    render(<FinancialLedger contractId={12} totalCount={2} />);
    expect(await screen.findByText(records[0].display_text)).toBeVisible();
    expect(screen.getByText("Amount not extracted")).toBeVisible();
    expect(screen.queryByText("No fixed dollar amount")).not.toBeInTheDocument();
    expect(screen.getAllByText("Application or processing fee").some((element) => element.tagName === "P")).toBe(true);
    expect(screen.getByRole("option", { name: "Fee exemption" })).toHaveValue("fee_exemption");
  });

  it("shows qualified financial text including minimums and percentage caps", async () => {
    const records = [
      { ...item("minimum", "set_aside", "limit"), amount: "5000000.00", display_text: "Sets aside at least $5,000,000.00 for rural grants.", purpose: "rural grants" },
      { ...item("maximum", "limitation", "limit"), amount: "5.00", amount_type: "ceiling" as const, currency: null, display_text: "Limits funding to no more than 5 percent of available funds for administration.", purpose: "administration" },
    ];
    vi.mocked(getFinancialItems).mockResolvedValue({ count: 2, next: null, previous: null, results: records });
    render(<FinancialLedger contractId={12} totalCount={2} />);
    expect(await screen.findByText("Rural grants")).toBeVisible();
    expect(screen.getByText(records[0].display_text)).toBeVisible();
    expect(screen.getByText(records[1].display_text)).toBeVisible();
  });

  it("keeps legal actions distinct and never presents a computed total", async () => {
    vi.mocked(getFinancialItems).mockResolvedValue({
      count: 7,
      next: null,
      previous: null,
      results: [
        item("financial-1", "appropriation", "increase"),
        item("financial-2", "authorization", "increase"),
        item("financial-3", "transfer", "neutral_transfer"),
        item("financial-4", "rescission", "decrease"),
        item("financial-5", "reduction", "decrease"),
        item("financial-6", "set_aside", "limit"),
        item("financial-7", "limitation", "limit"),
      ],
    });

    render(<FinancialLedger contractId={12} totalCount={7} />);

    expect(await screen.findByRole("heading", { name: "Money in this bill" })).toBeVisible();
    for (const label of ["Appropriation", "Authorization", "Transfer", "Rescission", "Reduction", "Set-aside", "Limitation"]) {
      expect(screen.getAllByText(label).some((element) => element.tagName === "P")).toBe(true);
    }
    expect(screen.getByText(/not a CBO cost estimate/i)).toBeVisible();
    expect(screen.queryByText(/grand total|total spending/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("The program").length).toBe(7);
  });

  it("uses the clean section heading when an extracted money purpose is missing", async () => {
    const withoutPurpose = {
      ...item("financial-8", "appropriation", "increase"),
      purpose: null,
      section_path: [
        { level: "title" as const, label: "Title II", heading: "Defense" },
        { level: "section" as const, label: "Sec. 20001", heading: "ENHANCEMENT OF DEPARTMENT OF DEFENSE RESOURCES" },
      ],
    };
    vi.mocked(getFinancialItems).mockResolvedValue({ count: 1, next: null, previous: null, results: [withoutPurpose] });

    render(<FinancialLedger contractId={12} totalCount={1} />);

    expect(await screen.findByText("Enhancement of Department of Defense Resources")).toBeVisible();
    expect(screen.getByText("What the money is for")).toBeVisible();
  });

  it("reports only the number of provisions actually loaded", async () => {
    vi.mocked(getFinancialItems).mockResolvedValue({
      count: 101,
      next: "page-2",
      previous: null,
      results: [item("financial-1", "appropriation", "increase")],
    });

    render(<FinancialLedger contractId={12} totalCount={101} />);

    expect(await screen.findByText("1 of 101 provisions shown")).toBeVisible();
    expect(screen.queryByText("101 of 101 provisions shown")).not.toBeInTheDocument();
  });

  it("sends one association scope with the action and year filters", async () => {
    const user = userEvent.setup();
    vi.mocked(getFinancialItems).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });

    render(
      <FinancialLedger
        contractId={12}
        totalCount={9}
        lineItemId="line-4"
        sectionId="section-4"
      />,
    );
    await waitFor(() => expect(getFinancialItems).toHaveBeenCalled());
    await user.selectOptions(screen.getByLabelText("Financial action"), "transfer");
    await user.type(screen.getByLabelText("Fiscal year"), "2027");
    await user.click(screen.getByRole("button", { name: "Apply money filters" }));

    await waitFor(() =>
      expect(getFinancialItems).toHaveBeenLastCalledWith(12, {
        page: 1,
        pageSize: 25,
        financialAction: "transfer",
        fiscalYear: 2027,
        lineItemId: "line-4",
      }),
    );
    expect(screen.getByText("0 of 0 matching provisions shown")).toBeVisible();
  });

  it("restores all results when All actions is applied and reports completion", async () => {
    const user = userEvent.setup();
    const records = [item("a", "set_aside", "limit"), { ...item("b", "limitation", "limit"), amount: "5.00", amount_type: "ceiling" as const, currency: null }];
    vi.mocked(getFinancialItems).mockImplementation(async (_id, params) => {
      const results = records.filter((record) => !params?.financialAction || record.financial_action === params.financialAction);
      return { count: results.length, results, next: null, previous: null };
    });
    render(<FinancialLedger contractId={12} totalCount={2} />);
    expect(await screen.findByText("2 of 2 provisions shown")).toBeVisible();
    expect(screen.getByText("5%")).toBeVisible();
    expect(screen.queryByText("$5")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Financial action"), "set_aside");
    await user.click(screen.getByRole("button", { name: "Apply money filters" }));
    expect(await screen.findByText("1 of 1 matching provisions shown")).toBeVisible();
    await user.selectOptions(screen.getByLabelText("Financial action"), "");
    await user.click(screen.getByRole("button", { name: "Apply money filters" }));
    expect(await screen.findByText("2 of 2 provisions shown")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("2 matching provisions");
  });

  it("explains missing records and disables filters when nothing has been extracted", async () => {
    vi.mocked(getFinancialItems).mockResolvedValue({ count: 0, results: [], next: null, previous: null });
    render(<FinancialLedger contractId={12} totalCount={0} />);
    expect(await screen.findByText(/No financial provisions have been extracted/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply money filters" })).toBeDisabled();
  });
});
