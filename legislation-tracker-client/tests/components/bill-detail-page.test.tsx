import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillDetailPage from "@/app/bills/[id]/page";
import { getBill, getStoredAccessToken } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "10" }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  getBill: vi.fn(),
  getStoredAccessToken: vi.fn(),
  getMyTracking: vi.fn(),
  trackBill: vi.fn(),
  untrackBill: vi.fn(),
}));

describe("BillDetailPage", () => {
  beforeEach(() => {
    vi.mocked(getStoredAccessToken).mockReturnValue(null);
    vi.mocked(getBill).mockResolvedValue({
      id: 10,
      jurisdiction: "federal",
      session: 119,
      bill_number: "HR 10",
      title: "A public bill",
      status: "Introduced",
      sponsor_name: null,
      introduced_at: null,
      last_action_at: null,
      topics: [],
      summary: null,
      processing_status: "complete",
      sponsor: null,
      raw_text_url: null,
      pdf_url: null,
      source_api_id: null,
      documents: [],
      congress_gov_url: null,
      latest_contract: null,
      created_at: "2026-08-19T00:00:00Z",
      updated_at: "2026-08-19T00:00:00Z",
    });
  });

  it("keeps a public bill readable while showing an unauthenticated tracking prompt", async () => {
    render(<BillDetailPage />);

    expect(await screen.findByRole("heading", { name: "HR 10 (119)" })).toBeVisible();
    expect(screen.getByText("A public bill")).toBeVisible();
    expect(screen.getByRole("link", { name: "Log in to track this bill" })).toHaveAttribute(
      "href",
      "/login",
    );
  });
});
