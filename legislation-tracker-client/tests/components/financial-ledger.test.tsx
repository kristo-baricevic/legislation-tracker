import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinancialLedger } from "@/app/bills/[id]/financial-ledger";
import { getFinancialItems } from "@/lib/api";
import type { LegalNlpFinancialItem } from "@/lib/contracts";

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

  it("sends action, year, line, and section filters to the server", async () => {
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
        sectionId: "section-4",
      }),
    );
    expect(screen.getByText("0 of 9 provisions shown")).toBeVisible();
  });
});
