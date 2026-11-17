import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepresentativeDetailPage from "@/app/representatives/[id]/page";
import { getRecordedVotes } from "@/lib/legislator-profile";
const route = vi.hoisted(() => ({ query: "congress=119" }));
import {
  getSession, getMyTracking, trackLegislator, untrackLegislator, getTopics,
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
  getRecordedVotes: vi.fn().mockResolvedValue({ results: [], next: null, previous: null, count: 0 }),
  safeSourceUrl: () => null,
}));
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a>,
}));
vi.mock("@/lib/api", () => ({
  getTopics: vi.fn().mockResolvedValue([{ id: 9, name: "Education", slug: "education" }]),
  getSession: vi.fn().mockResolvedValue({ authenticated: true, user: { email: "reader@example.com" } }),
  getMyTracking: vi.fn().mockResolvedValue({ bills: [], topics: [], legislators: [] }),
  trackLegislator: vi.fn().mockResolvedValue({}),
  untrackLegislator: vi.fn().mockResolvedValue(undefined),
  getBillFilterOptions: vi.fn().mockResolvedValue({ current_congress: 120 }),
  getRepresentative: vi.fn().mockResolvedValue({ id: 8, bioguide_id: "R000001", name: "Representative Example", chamber: "house", party: "Independent", state: "NY", district: "12", first_name: "Representative", last_name: "Example", official_website_url: null, image_url: null, is_current: true }),
  getRepresentativeInsights: vi.fn().mockResolvedValue({ representative_id: 8, congress: 119, total_roll_calls: 10, ingested_roll_calls: 10, discovered_roll_calls: 12, participation_numerator: 8, participation_denominator: 10, participation_rate: 0.8, position_counts: { yes: 6, no: 2, present: 0, not_voting: 2, other: 0 }, first_vote_at: "2026-01-01T00:00:00Z", last_vote_at: "2026-02-01T00:00:00Z", coverage_complete: false, coverage_reason: "Some discovered roll calls are still unresolved.", sponsored_bill_count: 2, active_cosponsored_bill_count: 1, committee_count: 1 }),
  getRepresentativeSponsoredBills: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
  getRepresentativeCosponsoredBills: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
  getRepresentativeCommittees: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
}));

describe("RepresentativeDetailPage", () => {
  it("ignores an older topic response after selecting all topics", async () => {
    const bill = { id: 101, jurisdiction: "federal", session: 119, bill_number: "HR 101", title: "Unfiltered bill", status: "Introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [] };
    type Page = Awaited<ReturnType<typeof getRepresentativeSponsoredBills>>;
    let finish!: (value: Page) => void;
    vi.mocked(getRepresentativeSponsoredBills).mockImplementation(async (_id, _congress, _page, topic) => topic ? new Promise<Page>(resolve => { finish = resolve; }) : { count: 1, next: null, previous: null, results: [bill] });
    render(<RepresentativeDetailPage />);
    const row = await screen.findByText("Unfiltered bill");
    const dropdown = screen.getByRole("combobox", { name: "Bills introduced topic" });
    await userEvent.selectOptions(dropdown, "9");
    expect(row).toBeVisible();
    await userEvent.selectOptions(dropdown, "");
    await act(async () => finish({ count: 0, next: null, previous: null, results: [] }));
    expect(screen.getByText("Unfiltered bill")).toBeVisible();
  });
  it("filters introduced and cosponsored bills independently", async () => {
    const bill = { id: 101, jurisdiction: "federal", session: 119, bill_number: "HR 101", title: "School support", status: "Introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [] };
    vi.mocked(getRepresentativeSponsoredBills).mockImplementation(async (_id, _congress, _page, topic) => ({ count: topic ? 1 : 0, next: null, previous: null, results: topic ? [bill] : [] }));
    render(<RepresentativeDetailPage />);
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Bills introduced topic" }), "9");
    expect(await screen.findByText("School support")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Bills cosponsored topic" })).toHaveValue("");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Bills introduced topic" }), "");
    await act(async () => {});
    expect(screen.queryByText("School support")).not.toBeInTheDocument();
  });
  it("keeps vote rows mounted during filter requests and replaces them only when ready", async () => {
    const base = await getRecordedVotes({ representativeId: 8, congress: 119 }, 1);
    vi.mocked(getRecordedVotes).mockResolvedValueOnce({ ...base, results: [{ id: 1, representative_id: 8, vote_id: 1, congress: 119, chamber: "house", session_number: 1, roll_number: 1, vote_date: "2026-01-01T00:00:00Z", question: "Existing vote", position: "yes", raw_position: "Yea", bill: null, source_url: null, source_link_kind: "unavailable", source_updated_at: null }] });
    render(<RepresentativeDetailPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Votes" }));
    const row = await screen.findByText("Existing vote");
    let finish!: (value: typeof base) => void;
    vi.mocked(getRecordedVotes).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Vote" }), "no");
    expect(row).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Vote results" })).toHaveAttribute("aria-busy", "true");
    await act(async () => finish(base));
    expect(screen.queryByText("Existing vote")).not.toBeInTheDocument();
    expect(screen.getByText("No voting records available.")).toBeVisible();
  });
  it("filters voting records by position and topic together", async () => {
    render(<RepresentativeDetailPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Votes" }));
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Vote" }), "no_vote");
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Topic" }), "9");
    expect(getRecordedVotes).toHaveBeenLastCalledWith(expect.objectContaining({ representativeId: 8 }), 1, expect.any(AbortSignal), { position: "no_vote", topicId: 9 });
  });
  it("recognizes representatives already tracked on a previous visit", async () => {
    vi.mocked(getMyTracking).mockResolvedValueOnce({ bills: [], topics: [], is_staff: false, legislators: [{ id: 1, created_at: "2026-01-01", representative: await getRepresentative(8) }] });
    render(<RepresentativeDetailPage />);
    expect(await screen.findByRole("button", { name: "Untrack representative" })).toHaveAttribute("aria-pressed", "true");
  });
  it("lets readers track and untrack the representative from the header", async () => {
    render(<RepresentativeDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Track representative" }));
    expect(trackLegislator).toHaveBeenCalledWith(8, expect.any(Object));
    await userEvent.click(await screen.findByRole("button", { name: "Untrack representative" }));
    expect(untrackLegislator).toHaveBeenCalledWith(8, expect.any(Object));
    expect(await screen.findByRole("button", { name: "Track representative" })).toBeEnabled();
  });

  it("keeps the tracking state unchanged when saving fails and permits retry", async () => {
    vi.mocked(trackLegislator).mockRejectedValueOnce(new Error("offline"));
    render(<RepresentativeDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Track representative" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not update tracking");
    expect(screen.getByRole("button", { name: "Track representative" })).toBeEnabled();
  });

  it("offers login instead of a tracking mutation to signed-out readers", async () => {
    vi.mocked(getSession).mockResolvedValueOnce(null);
    render(<RepresentativeDetailPage />);
    expect(await screen.findByRole("link", { name: "Log in to track" })).toHaveAttribute("href", "/login");
  });
  beforeEach(() => {
    vi.mocked(getRecordedVotes).mockResolvedValue({ results: [], next: null, previous: null, count: 0, pagination_mode: "live_pages", page_read_at: "2026-11-17T00:00:00Z", coverage: { scope: { congress: 119, chamber: null }, stored_record_count: 0, member_position_completeness: "unknown", unknown_session_record_count: 0, provider_scopes: [], legacy_ingestion_check: { scopes: [], coverage_complete: false, reason: null, discovered_count: 0, persisted_count: 0, notice: "" } } });
    vi.mocked(getTopics).mockResolvedValue([{ id: 9, name: "Education", slug: "education" }]);
    vi.mocked(getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.com" } });
    vi.mocked(getMyTracking).mockResolvedValue({ bills: [], topics: [], legislators: [], is_staff: false });
    vi.mocked(trackLegislator).mockReset().mockResolvedValue({} as Awaited<ReturnType<typeof trackLegislator>>);
    vi.mocked(untrackLegislator).mockReset().mockResolvedValue(undefined);
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

  it("keeps loaded profile and panels mounted when the router updates the tab query", async () => {
    const view = render(<RepresentativeDetailPage />);
    const heading = await screen.findByRole("heading", { name: "Representative Example" });
    await userEvent.click(screen.getByRole("tab", { name: "Votes" }));
    const votes = await screen.findByRole("heading", { name: "Voting record" });
    route.query = "congress=119&tab=votes";
    view.rerender(<RepresentativeDetailPage />);
    expect(heading).toBeInTheDocument();
    expect(votes).toBeInTheDocument();
    expect(screen.queryByText("Loading representative…")).not.toBeInTheDocument();
    route.query = "congress=119&tab=bills";
    view.rerender(<RepresentativeDetailPage />);
    expect(votes).toBeInTheDocument();
    expect(votes).not.toBeVisible();
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

  it("resets loaded panels when the Congress scope changes", async () => {
    const view = render(<RepresentativeDetailPage />);
    const heading = await screen.findByRole("heading", { name: "Representative Example" });
    route.query = "congress=120";
    view.rerender(<RepresentativeDetailPage />);
    expect(heading).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Representative Example" })).toBeVisible();
    expect(getRepresentativeSponsoredBills).toHaveBeenLastCalledWith(8, 120, 1);
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
