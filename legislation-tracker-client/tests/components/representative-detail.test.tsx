import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepresentativeDetailPage from "@/app/representatives/[id]/page";
const route = vi.hoisted(() => ({ query: "congress=119" }));
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
  useSearchParams: () => new URLSearchParams(route.query),
}));
vi.mock("@/lib/recommendations", () => ({ getRepresentativeTopicActivity: async () => ({ channels: { sponsor: { topics: [] }, active_cosponsor: { topics: [] } } }) }));
vi.mock("@/app/components/RepresentativeResearch", () => ({ default: ({ financeView }: { financeView?: boolean }) => financeView ? <div>Campaign funding controls</div> : <button>Research</button> }));
vi.mock("@/lib/legislator-profile", () => ({
  getVoteSummary: async () => ({ totals: { yes: 6, no: 2, present: 0, not_voting: 2, other: 0 }, topics: [{ id: 9, name: "Education", yes: 6, no: 2 }] }),
  getRecordedVotes: async () => ({ results: [], next: null, previous: null, count: 0 }),
  safeSourceUrl: () => null,
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
    route.query = "congress=119";
    window.history.replaceState(null, "", "/representatives/8?congress=119");
    vi.mocked(getBillFilterOptions).mockResolvedValue({ jurisdictions: ["federal"], current_congress: 120 });
    vi.mocked(getRepresentative).mockResolvedValue({ id: 8, bioguide_id: "R000001", name: "Representative Example", chamber: "house", party: "Independent", state: "NY", district: "12", first_name: "Representative", last_name: "Example", official_website_url: null, image_url: null, is_current: true });
    vi.mocked(getRepresentativeInsights).mockResolvedValue({ representative_id: 8, congress: 119, total_roll_calls: 10, ingested_roll_calls: 10, discovered_roll_calls: 12, participation_numerator: 8, participation_denominator: 10, participation_rate: 0.8, position_counts: { yes: 6, no: 2, present: 0, not_voting: 2, other: 0 }, first_vote_at: "2026-01-01T00:00:00Z", last_vote_at: "2026-02-01T00:00:00Z", coverage_complete: false, coverage_reason: "Some discovered roll calls are still unresolved.", sponsored_bill_count: 2, active_cosponsored_bill_count: 1, committee_count: 1 });
    vi.mocked(getRepresentativeSponsoredBills).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    vi.mocked(getRepresentativeCosponsoredBills).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    vi.mocked(getRepresentativeCommittees).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
  });

  it("opens campaign funding directly from a modal link", async () => {
    route.query = "congress=119&tab=funding";
    render(<RepresentativeDetailPage />);
    expect(await screen.findByText("Campaign funding controls")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Campaign funding" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Votes" }));
    expect(window.location.search).toBe("?congress=119&tab=votes");
  });

  it("keeps the profile concise and separates bills, voting, funding and committees", async () => {
    render(<RepresentativeDetailPage />);
    expect(await screen.findByRole("heading", { name: "Representative Example" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Bills" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Roll-call coverage")).not.toBeInTheDocument();
    expect(screen.queryByText("Campaign funding controls")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Votes" }));
    expect(await screen.findByRole("region", { name: "Yes votes" })).toHaveTextContent("Education6");
    expect(screen.getByRole("heading", { name: "Voting record" })).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "Campaign funding" }));
    expect(screen.getByText("Campaign funding controls")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Campaign funding" })).toHaveAttribute("aria-selected", "true");
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
