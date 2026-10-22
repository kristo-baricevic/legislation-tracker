import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BillRecommendations from "@/app/components/BillRecommendations";
import RecommendationsPreview from "@/app/components/RecommendationsPreview";
import RepresentativeRecommendations from "@/app/components/RepresentativeRecommendations";
import RepresentativeActivity from "@/app/components/RepresentativeActivity";
import { logout } from "@/lib/api";
import type { BillRecommendationsPage, RepresentativeTopicActivity } from "@/lib/recommendations";

const bill = { id: 1, jurisdiction: "federal", session: 119, bill_number: "HR 1", title: "Public health reporting", status: "introduced", sponsor_name: "Member One", introduced_at: "2025-01-10", last_action_at: null, topics: [{ topic_id: 1, name: "Health", slug: "health", confidence_score: null }] };
const page: BillRecommendationsPage = { algorithm: "test", generated_at: "2026-10-10T00:00:00Z", count: 1, next_cursor: null, candidate_pool_truncated: false, ranking_limit_reached: false, empty_reason: null, unsupported_follow_types: [], results: [{ bill, score: 1, reasons: [{ kind: "followed_topic", topic_id: 1, name: "Health" }] }] };
const empty = { ...page, results: [], empty_reason: "no_follows" };
const channel = { status: "insufficient_history", missing_date_count: 2, unknown_session_count: 0, withdrawn_count: 0, raw_observation_count: 3, grouped_observation_count: 3, raw_tagged_count: 3, grouped_tagged_count: 3, raw_tag_coverage: { fraction: { numerator: "1", denominator: "1" }, display: 1 }, grouped_tag_coverage: { fraction: { numerator: "1", denominator: "1" }, display: 1 }, recurring_topic_ids: [], topics: [] };
const activity = { schema_version: "representative-topic-activity-v1", policy_version: "test", representative: { id: 1, name: "Member One", bioguide_id: "A000001", chamber: "house", state: "NY", is_current: true }, captured_at: "2026-10-10T00:00:00Z", window: { start_date: "2024-10-09", end_date_exclusive: "2026-10-10", timezone: "America/New_York", months: 24 }, policy: { topic_share: "0.20", minimum_observations: 20, minimum_topic_observations: 5, minimum_tag_coverage: "0.80" }, exposure: { status: "unknown", term_precision: "unknown", service_days: null, monthly_rate: null, reason: "term_precision_unknown" }, channels: { sponsor: channel, active_cosponsor: channel }, passage_evidence: { status: "coverage_unknown", yes: 0, no: 0, present: 0, not_voting: 0, other: 0, selected_bill_count: 0, yes_rate: null, missing_or_uncertain: 1, missing_eligibility: "unknown", topics: [], examples: [] }, resolutions: { coverage: "unsupported", joint_count: null, simple_count: null, concurrent_count: null }, caveats: [] } as RepresentativeTopicActivity;

beforeEach(async () => { document.cookie = "csrftoken=test"; localStorage.clear(); (await import("@/lib/personalized-scope")).announceTrackingChange(); });
afterEach(() => vi.unstubAllGlobals());
function mockRequests(response: () => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn((url, init) => {
    if (String(url).includes("session/current")) return Promise.resolve(Response.json({ authenticated: true, user: { email: "reader@example.com" } }));
    if (String(url).includes("logout")) return Promise.resolve(new Response(null, { status: 204 }));
    if (String(url).includes("/tracking/bills/") && init?.method === "POST") return Promise.resolve(Response.json({ id: 1, bill }));
    return Promise.resolve(response());
  }));
}
describe("recommendation rows", () => {
  it.each([["D", "democrat"], ["R", "republican"]])("uses structured party %s for plain-name recommendation cards", async (party, theme) => {
    mockRequests(() => Response.json({ ...empty, results: [{ representative_id: 1, name: "Jane Doe", bioguide_id: "A000001", score: .4, reasons: [], topic_activity_evidence: { ...activity, representative: { ...activity.representative, name: "Jane Doe", party } } }], activity_as_of: activity.captured_at }));
    render(<RepresentativeRecommendations renderName={member => <button>{member.name} profile</button>} />);
    await screen.findByRole("button", { name: "Jane Doe profile" });
    expect(screen.getByRole("article")).toHaveAttribute("data-party", theme);
  });
  it("expires cached recommendations after five minutes", async () => {
    mockRequests(() => Response.json(page));
    const view = render(<BillRecommendations onOpenBill={() => true} />);
    await screen.findByRole("link", { name: bill.title });
    view.unmount();
    const clock = vi.spyOn(Date, "now").mockReturnValue(Date.now() + 300001);
    try {
      render(<BillRecommendations onOpenBill={() => true} />);
      await screen.findByRole("link", { name: bill.title });
      expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/tracking/recommendations/"))).toHaveLength(2);
    } finally { clock.mockRestore(); }
  });
  it("reuses recommendations across navigation until explicitly refreshed", async () => {
    mockRequests(() => Response.json(page));
    const view = render(<BillRecommendations onOpenBill={() => true} />);
    await screen.findByRole("link", { name: bill.title });
    const calls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/tracking/recommendations/")).length;
    expect(calls()).toBe(1);
    view.unmount();
    render(<BillRecommendations onOpenBill={() => true} />);
    await screen.findByRole("link", { name: bill.title });
    expect(calls()).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh bill recommendations" }));
    await waitFor(() => expect(calls()).toBe(2));
  });
  it("always renders recommendations even with a legacy disabled preference", () => {
    localStorage.setItem("legislation-tracker-recommendations", "false");
    mockRequests(() => Response.json(empty));
    render(<RecommendationsPreview onOpenBill={() => true} />);
    expect(screen.queryByLabelText("Show recommendations on this browser")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Bills to discover" })).toBeInTheDocument();
  });
  it("shows neutral reasons and reuses the bill opener with a navigable fallback", async () => {
    mockRequests(() => Response.json(page));
    const open = vi.fn(() => true);
    render(<BillRecommendations onOpenBill={open} />);
    fireEvent.click(await screen.findByRole("link", { name: bill.title }));
    expect(open).toHaveBeenCalledWith(bill);
    expect(screen.getByLabelText("Why recommended")).toHaveTextContent("Tagged Health, a topic you follow");
    expect(screen.getByRole("link", { name: "Health" })).toHaveAttribute("href", "/bills?topic_id=1");
    expect(screen.getByRole("region", { name: "Recommended bills" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByText("Not recorded")).toBeVisible();
  });
  it("shows cold-start, recoverable error and retry states", async () => {
    let fails = true;
    mockRequests(() => fails ? Response.json({ detail: "unavailable" }, { status: 503 }) : Response.json(empty));
    render(<BillRecommendations onOpenBill={() => true} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    fails = false; fireEvent.click(screen.getByRole("button", { name: "Retry recommendations" }));
    expect(await screen.findByText(/Follow a topic or representative to start/)).toBeVisible();
  });
  it("deduplicates continuation pages and restarts expired cursors", async () => {
    let count = 0;
    mockRequests(() => {
      count += 1;
      if (count === 1) return Response.json({ ...page, next_cursor: "cursor" });
      if (count === 2) return Response.json({ ...page, next_cursor: "cursor2", results: [page.results[0], { ...page.results[0], bill: { ...bill, id: 2, title: "Second proposal" } }] });
      if (count === 3) return Response.json({ detail: "expired" }, { status: 410 });
      return Response.json(empty);
    });
    render(<BillRecommendations onOpenBill={() => true} />);
    fireEvent.click(await screen.findByRole("button", { name: "More recommendations" }));
    expect(await screen.findByRole("link", { name: "Second proposal" })).toBeVisible();
    expect(screen.getAllByRole("link", { name: bill.title })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "More recommendations" }));
    expect(await screen.findByText(/Follow a topic or representative to start/)).toBeVisible();
  });
  it("clears cards on successful follows and session loss before a late reload", async () => {
    let resolve!: (response: Response) => void, calls = 0;
    mockRequests(() => ++calls === 1 ? Response.json(page) : new Promise<Response>(done => { resolve = done; }));
    render(<BillRecommendations onOpenBill={() => true} />);
    const follow = await screen.findByRole("button", { name: "Follow bill HR 1 / 119" });
    follow.focus();
    fireEvent.click(follow);
    await waitFor(() => expect(screen.queryByRole("link", { name: bill.title })).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Bills to discover" })).toHaveFocus();
    await waitFor(() => expect(calls).toBe(2));
    await act(async () => { await logout(); resolve(Response.json(page)); });
    expect(screen.queryByRole("link", { name: bill.title })).not.toBeInTheDocument();
  });
  it("clears cards immediately on cross-tab epoch change", async () => {
    let calls = 0;
    mockRequests(() => ++calls === 1 ? Response.json(page) : new Promise<Response>(() => {}));
    render(<BillRecommendations onOpenBill={() => true} />);
    await screen.findByRole("link", { name: bill.title });
    act(() => { localStorage.setItem("legislation-tracker-session-epoch", "stable:new-tab"); window.dispatchEvent(new StorageEvent("storage", { key: "legislation-tracker-session-epoch" })); });
    expect(screen.queryByRole("link", { name: bill.title })).not.toBeInTheDocument();
  });
  it("renders representative reasons through the profile adapter", async () => {
    mockRequests(() => Response.json({ ...empty, results: [{ representative_id: 1, name: "Member One", bioguide_id: "A000001", score: .4, reasons: [{ kind: "followed_topic", topic_id: 1, name: "Health", shared_topics: [], channel_evidence: {} }, { kind: "followed_representative_activity", representative_id: 2, name: "Other member", shared_topics: [{ id: 1, name: "Health", slug: "health" }, { id: 2, name: "Energy", slug: "energy" }], channel_evidence: {} }], topic_activity_evidence: activity }], activity_as_of: activity.captured_at }));
    render(<RepresentativeRecommendations renderName={member => <button>{member.name} profile</button>} />);
    expect(await screen.findByRole("button", { name: "Member One profile" })).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Health" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Health" })).toHaveAttribute("href", "/bills?topic_id=1");
    expect(screen.getByRole("link", { name: "Energy" })).toHaveAttribute("href", "/bills?topic_id=2");
    expect(screen.getByRole("link", { name: "Other member" })).toHaveAttribute("href", "/representatives/2");
    expect(screen.getByText("Similar to")).toBeVisible();
    expect(screen.getByRole("img", { name: "Member One" })).toHaveAttribute("src", "https://www.congress.gov/img/member/a000001_200.jpg");
    expect(screen.queryByText(/Recorded sponsorship or active cosponsorship in/)).not.toBeInTheDocument();
  });
  it("keeps activity window and uncertainty separate from the selected Congress", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(activity)));
    render(<RepresentativeActivity scope={{ representativeId: 1, congress: 117, chamber: "senate" }} />);
    expect(await screen.findByText(/Rolling 24-month window/)).toHaveTextContent("independent of the selected Congress");
    expect(screen.getAllByText(/Insufficient history/)).toHaveLength(2);
    expect(screen.getByText(/activity completeness and exact time in office are unknown/)).toBeVisible();
    fireEvent.click(screen.getByText("Repeat-title groups and resolution coverage"));
    expect(screen.getByText(/Exact time in office is unavailable/)).toBeVisible();
  });
  it("recovers recorded activity after an unavailable response when Retry activity is clicked", async () => {
    let available = false;
    const fetch = vi.fn(async () => available
      ? Response.json(activity)
      : Response.json({ detail: "recommendations_unavailable" }, { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    render(<RepresentativeActivity scope={{ representativeId: 1, congress: 119 }} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Recorded topic activity could not be loaded.");
    expect(screen.queryByRole("heading", { name: "Recorded topic activity" })).not.toBeInTheDocument();
    available = true;
    fireEvent.click(screen.getByRole("button", { name: "Retry activity" }));
    expect(await screen.findByRole("heading", { name: "Recorded topic activity" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it.each([{}, {...activity, representative: {...activity.representative, id: 2}}, {...activity, channels: {...activity.channels, sponsor: {...activity.channels.sponsor, raw_observation_count: {}}}}])("fails closed for malformed or wrong-person activity", async payload => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(payload)));
    render(<RepresentativeActivity scope={{representativeId: 1, congress: 119}} />);
    expect(await screen.findByRole("button", {name: /Retry/})).toBeVisible();
    expect(screen.queryByText(/Rolling 24-month/)).not.toBeInTheDocument();
  });

});
