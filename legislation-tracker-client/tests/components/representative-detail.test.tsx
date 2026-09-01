import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepresentativeDetailPage from "@/app/representatives/[id]/page";
import {
  getBillFilterOptions,
  getRepresentative,
  getRepresentativeCommittees,
  getRepresentativeCosponsoredBills,
  getRepresentativeInsights,
  getRepresentativeSponsoredBills,
} from "@/lib/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "8" }),
  useSearchParams: () => new URLSearchParams("congress=119"),
}));
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a>,
}));
vi.mock("@/lib/api", () => ({
  getBillFilterOptions: vi.fn().mockResolvedValue({ current_congress: 120 }),
  getRepresentative: vi.fn().mockResolvedValue({ id: 8, bioguide_id: "R000001", name: "Representative Example", chamber: "house", party: "Independent", state: "NY", district: "12", first_name: "Representative", last_name: "Example", official_website_url: null, image_url: null, is_current: true }),
  getRepresentativeInsights: vi.fn().mockResolvedValue({ representative_id: 8, congress: 119, total_roll_calls: 10, ingested_roll_calls: 10, discovered_roll_calls: 12, participation_numerator: 8, participation_denominator: 10, participation_rate: 0.8, position_counts: { yes: 6, no: 2, present: 0, not_voting: 2, other: 0 }, first_vote_at: "2026-01-01T00:00:00Z", last_vote_at: "2026-02-01T00:00:00Z", coverage_complete: false, coverage_reason: "Some discovered roll calls are still unresolved.", sponsored_bill_count: 2, active_cosponsored_bill_count: 1, committee_count: 1 }),
  getRepresentativeSponsoredBills: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
  getRepresentativeCosponsoredBills: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
  getRepresentativeCommittees: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
}));

describe("RepresentativeDetailPage", () => {
  beforeEach(() => {
    vi.mocked(getBillFilterOptions).mockResolvedValue({ jurisdictions: ["federal"], current_congress: 120 });
    vi.mocked(getRepresentative).mockResolvedValue({ id: 8, bioguide_id: "R000001", name: "Representative Example", chamber: "house", party: "Independent", state: "NY", district: "12", first_name: "Representative", last_name: "Example", official_website_url: null, image_url: null, is_current: true });
    vi.mocked(getRepresentativeInsights).mockResolvedValue({ representative_id: 8, congress: 119, total_roll_calls: 10, ingested_roll_calls: 10, discovered_roll_calls: 12, participation_numerator: 8, participation_denominator: 10, participation_rate: 0.8, position_counts: { yes: 6, no: 2, present: 0, not_voting: 2, other: 0 }, first_vote_at: "2026-01-01T00:00:00Z", last_vote_at: "2026-02-01T00:00:00Z", coverage_complete: false, coverage_reason: "Some discovered roll calls are still unresolved.", sponsored_bill_count: 2, active_cosponsored_bill_count: 1, committee_count: 1 });
    vi.mocked(getRepresentativeSponsoredBills).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    vi.mocked(getRepresentativeCosponsoredBills).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    vi.mocked(getRepresentativeCommittees).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
  });

  it("shows raw vote counts and explains partial coverage", async () => {
    render(<RepresentativeDetailPage />);
    expect(await screen.findByText("80%")).toBeVisible();
    expect(screen.getByText("8 / 10 roll calls")).toBeVisible();
    expect(screen.getByText(/Partial coverage/)).toBeVisible();
    expect(screen.getByText(/Not voting 2/)).toBeVisible();
  });

  it("prevents a second sponsored-history request while the next page is loading", async () => {
    type SponsoredBillsPage = Awaited<ReturnType<typeof getRepresentativeSponsoredBills>>;
    let resolveNextPage: (value: SponsoredBillsPage) => void;
    const nextPage = new Promise<SponsoredBillsPage>((resolve) => {
      resolveNextPage = resolve;
    });
    vi.mocked(getRepresentativeSponsoredBills)
      .mockResolvedValueOnce({
        count: 2,
        next: "/api/representatives/8/sponsored/?page=2",
        previous: null,
        results: [{ id: 101, jurisdiction: "federal", session: 119, bill_number: "HR 101", title: "First sponsored bill", status: "Introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [] }],
      })
      .mockReturnValue(nextPage);
    const user = userEvent.setup();

    render(<RepresentativeDetailPage />);

    const button = await screen.findByRole("button", { name: "Load more sponsored bills" });
    await user.click(button);
    expect(button).toBeDisabled();
    await user.click(button);
    expect(getRepresentativeSponsoredBills).toHaveBeenCalledTimes(2);

    resolveNextPage!({
      count: 2,
      next: null,
      previous: "/api/representatives/8/sponsored/?page=1",
      results: [{ id: 102, jurisdiction: "federal", session: 119, bill_number: "HR 102", title: "Second sponsored bill", status: "Introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [] }],
    });
    expect(await screen.findByText(/Second sponsored bill/)).toBeVisible();
  });
});
