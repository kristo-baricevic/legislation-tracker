import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillDetailPage from "@/app/bills/[id]/page";
import {
  getBill,
  getContracts,
  getVote,
  getVotes,
  getStoredAccessToken,
} from "@/lib/api";

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
  getContracts: vi.fn(),
  getVote: vi.fn(),
  getVotes: vi.fn(),
  getApiBase: () => "http://localhost:8000",
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
      source_api_id: null,
      documents: [
        {
          id: 9,
          version_label: "Introduced",
          is_active_version: true,
          content_type: "application/pdf",
          file_size_bytes: 123,
          source_url: null,
          downloaded_at: null,
          download_url: "/api/documents/9/download/",
          text_url: "/api/documents/9/text/",
        },
      ],
      congress_gov_url: null,
      latest_contract: null,
      created_at: "2026-08-19T00:00:00Z",
      updated_at: "2026-08-19T00:00:00Z",
    });
    vi.mocked(getContracts).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 4,
          schema_version: "1.1",
          contract_json: { plain_summary: "Contract history summary" },
          contract_hash: "hash",
          computed_at: "2026-08-19T00:00:00Z",
          document: null,
          document_version_label: null,
          evidence_spans: [],
        },
      ],
    });
    vi.mocked(getVotes).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 33,
          bill: 10,
          chamber: "house",
          roll_number: 17,
          vote_date: "2026-08-19T00:00:00Z",
          result: "Passed",
          yeas: 220,
          nays: 210,
        },
      ],
    });
    vi.mocked(getVote).mockResolvedValue({
      id: 33,
      bill: 10,
      chamber: "house",
      roll_number: 17,
      vote_date: "2026-08-19T00:00:00Z",
      result: "Passed",
      yeas: 220,
      nays: 210,
      records: [
        {
          representative: {
            id: 1,
            bioguide_id: "V000001",
            name: "Voting Representative",
            chamber: "house",
            party: "Independent",
            state: "NY",
            district: null,
          },
          position: "yes",
        },
      ],
    });
  });

  it("keeps a public bill readable while showing an unauthenticated tracking prompt", async () => {
    const user = userEvent.setup();
    render(<BillDetailPage />);

    expect(await screen.findByRole("heading", { name: "HR 10 (119)" })).toBeVisible();
    expect(screen.getByText("A public bill")).toBeVisible();
    expect(screen.getByRole("link", { name: "Log in to track this bill" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/documents/9/download/",
    );
    expect(screen.getByRole("link", { name: "Read text" })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/documents/9/text/",
    );
    expect(await screen.findByRole("heading", { name: "Contract history" })).toBeVisible();
    expect(screen.getByText("Contract history summary")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Roll-call votes" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "View member positions" }));
    await waitFor(() => expect(getVote).toHaveBeenCalledWith(33));
    expect(await screen.findByText("Voting Representative")).toBeVisible();
  });
});
