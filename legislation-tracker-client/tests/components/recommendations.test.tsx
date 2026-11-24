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
  let tracked = false;
  let signedIn = true;
  vi.stubGlobal("fetch", vi.fn((url, init) => {
    if (String(url).includes("session/current")) return Promise.resolve(Response.json(signedIn ? { authenticated: true, user: { email: "reader@example.com" } } : {authenticated:false}));
    if (String(url).includes("logout")) { signedIn = false; return Promise.resolve(new Response(null, { status: 204 })); }
    if (String(url).endsWith("/card/")) return Promise.resolve(Response.json({ biography: { text: "Saved representative biography." }, portrait: null, latest_bill: { id: 22, bill_number: "HR 22", title: "Education Act", session: 119, introduced_at: "2026-01-01" } }));
    if (String(url).endsWith("/api/representatives/410/")) return Promise.resolve(Response.json({ id: 410, name: "Katie Boyd Britt", bioguide_id: "B001319", image_url: "https://www.congress.gov/img/member/b001319_200.jpg" }));
    if (String(url).endsWith("/api/tracking/")) return Promise.resolve(Response.json({bills:tracked ? [{id:1,bill}] : [],topics:[],legislators:[]}));
    if (String(url).includes("/tracking/bills/") && init?.method === "POST") { tracked = true; return Promise.resolve(Response.json({ id: 1, bill })); }
    return Promise.resolve(response());
  }));
}
describe("recommendation rows", () => {
  it.each([
    ["bill", true], ["bill", false], ["representative", true], ["representative", false],
  ] as const)("isolates overlapping %s follows when the first save succeeds=%s", async (kind, succeeds) => {
    const ids = [1, 2];
    const results = ids.map(id => kind === "bill"
      ? { ...page.results[0], bill: { ...bill, id, bill_number: `HR ${id}` } }
      : { representative_id: id, name: `Member ${id}`, bioguide_id: `A00000${id}`, reasons: [], topic_activity_evidence: activity });
    mockRequests(() => Response.json({ ...page, results }));
    const original = fetch;
    const saved = new Set<number>();
    const finish = new Map<number, () => void>();
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.includes("/api/tracking/")) {
        const body = JSON.parse(String(init.body));
        const id = body.bill ?? body.representative;
        await new Promise<void>(resolve => finish.set(id, resolve));
        if (id === 1 && !succeeds) return new Response(null, { status: 500 });
        saved.add(id);
        return Response.json({});
      }
      if (url.endsWith("/api/tracking/")) {
        const items = [...saved].map(id => ({ bill: { ...bill, id }, representative: { ...activity.representative, id } }));
        return Response.json({ bills: items, legislators: items, topics: [] });
      }
      return original(url, init);
    });
    render(kind === "bill" ? <BillRecommendations onOpenBill={() => true} /> : <RepresentativeRecommendations />);
    const [first, second] = await screen.findAllByRole("button", { name: new RegExp(`^Follow ${kind} `) });
    fireEvent.click(first);
    await waitFor(() => expect(finish.has(1)).toBe(true));
    expect(first).toHaveTextContent(kind === "bill" ? /^Follow bill$/ : /^Follow$/);
    expect(second).toHaveAttribute("aria-disabled", "false");
    fireEvent.click(second);
    await waitFor(() => expect(finish.has(2)).toBe(true));
    await act(async () => finish.get(2)!());
    expect(second).toHaveTextContent("Unfollow");
    expect(first).toHaveTextContent(kind === "bill" ? /^Follow bill$/ : /^Follow$/);
    await act(async () => finish.get(1)!());
    if (succeeds) expect(first).toHaveTextContent("Unfollow");
    else expect(await screen.findByText("Your follow was not saved. Try again.")).toBeVisible();
    expect(second).toHaveTextContent("Unfollow");
  });

  it.each(["bill", "representative"] as const)("applies a pending %s dismissal after another follow succeeds", async kind => {
    const results = [1, 2].map(id => kind === "bill"
      ? { ...page.results[0], bill: { ...bill, id, bill_number: `HR ${id}` } }
      : { representative_id: id, name: `Member ${id}`, bioguide_id: `A00000${id}`, reasons: [], topic_activity_evidence: activity });
    mockRequests(() => Response.json({ ...page, results }));
    const original = fetch;
    let finish!: () => void;
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url.endsWith("/1/dismiss/")) {
        await new Promise<void>(resolve => { finish = resolve; });
        return new Response(null, { status: 204 });
      }
      return original(url, init);
    });
    render(kind === "bill" ? <BillRecommendations onOpenBill={() => true} /> : <RepresentativeRecommendations />);
    const [first] = await screen.findAllByRole("button", { name: /^Dismiss / });
    fireEvent.click(first);
    await waitFor(() => expect(finish).toBeDefined());
    fireEvent.click(screen.getAllByRole("button", { name: new RegExp(`^Follow ${kind} `) })[1]);
    await screen.findByRole("button", { name: new RegExp(`^Unfollow ${kind} `) });
    await act(async () => finish());
    expect(first).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Dismiss / })).toHaveLength(1);
  });

  it("removes only the dismissed bill without reloading recommendations", async () => {
    let dismissed = false;
    mockRequests(() => Response.json(dismissed ? empty : page));
    const fetchRequest = fetch;
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
      if (url.endsWith("/recommendations/1/dismiss/") && init?.method === "POST") {
        dismissed = true;
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return fetchRequest(url, init);
    });
    render(<BillRecommendations onOpenBill={() => true} />);
    fireEvent.click(await screen.findByRole("button", {name: "Dismiss HR 1 from recommendations"}));
    await waitFor(() => expect(screen.queryByRole("link", { name: bill.title })).not.toBeInTheDocument());
    expect(dismissed).toBe(true);
    expect(vi.mocked(fetchRequest).mock.calls.filter(([url]) => String(url).includes("/tracking/recommendations/"))).toHaveLength(1);
  });
  it("restarts an in-flight filter request after interests change", async () => {
    mockRequests(() => Response.json(page));
    const view = render(<BillRecommendations onOpenBill={() => true} filters={{q: "Before"}} />);
    await screen.findByRole("link", {name: bill.title});
    let requested = 0;
    mockRequests(() => ++requested === 1 ? new Promise<Response>(() => {}) : Response.json({...page, results: [{...page.results[0], bill: {...bill, title: "Updated filter result"}}]}));
    view.rerender(<BillRecommendations onOpenBill={() => true} filters={{q: "After"}} />);
    await waitFor(() => expect(requested).toBe(1));
    await act(async () => (await import("@/lib/personalized-scope")).announceTrackingChange());
    expect(await screen.findByRole("link", {name: "Updated filter result"})).toBeVisible();
    expect(screen.getByRole("button", {name: "Refresh bill recommendations"})).toHaveAttribute("aria-busy", "false");
  });
  it("scopes requests and cached cards to the dashboard filters", async () => {
    mockRequests(() => Response.json(page));
    const { rerender } = render(<BillRecommendations onOpenBill={() => true} filters={{q: "College", topic_id: "9"}} />);
    await screen.findByRole("link", {name: bill.title});
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("q=College") && String(url).includes("topic_id=9"))).toBe(true);
    rerender(<BillRecommendations onOpenBill={() => true} filters={{q: "Hospital"}} />);
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("q=Hospital"))).toBe(true));
    const count = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/tracking/recommendations/")).length;
    const requests = count();
    rerender(<BillRecommendations onOpenBill={() => true} filters={{q: "College", topic_id: "9"}} />);
    await waitFor(() => expect(screen.getByRole("button", {name:"Refresh bill recommendations"})).toHaveAttribute("aria-busy", "false"));
    expect(count()).toBe(requests);
  });
  it("keeps a recommended representative and focus after following", async () => {
    mockRequests(() => Response.json({ ...empty, results: [{ representative_id: 1, name: "Member One", bioguide_id: "A000001", score: .4, reasons: [], topic_activity_evidence: activity }], activity_as_of: activity.captured_at }));
    render(<RepresentativeRecommendations />);
    const follow = await screen.findByRole("button", { name: "Follow representative Member One" });
    const card = screen.getByRole("article");
    follow.focus(); fireEvent.click(follow);
    expect(await screen.findByRole("button", { name: "Unfollow representative Member One" })).toBe(follow);
    expect(screen.getByRole("article")).toBe(card);
    expect(follow).toHaveFocus();
  });
  it("does not expose complete or truncated HTML in card summaries or actions", async () => {
    mockRequests(() => Response.json({ ...page, results: [{ ...page.results[0], bill: { ...bill, card_summary: 'Provides <b>public reports</b> &amp; oversight.', status: 'Petition filed. (<a href="https://clerk.' } }] }));
    render(<BillRecommendations onOpenBill={() => true} />);
    expect(await screen.findByText("Provides public reports & oversight.")).toBeVisible();
    expect(screen.getByText("Petition filed.")).toBeVisible();
    expect(screen.getByRole("article")).not.toHaveTextContent('<a href');
  });
  it("refresh keeps cards and focus mounted while the request is pending", async () => {
    let refreshing = false;
    mockRequests(() => refreshing ? new Promise<Response>(() => {}) : Response.json(page));
    const dismiss = vi.fn();
    render(<BillRecommendations onOpenBill={() => true} onDismissBill={dismiss} />);
    const card = await screen.findByRole("link", { name: bill.title });
    const refresh = screen.getByRole("button", { name: "Refresh bill recommendations" });
    refresh.focus(); refreshing = true;
    fireEvent.click(refresh);
    expect(screen.getByRole("link", { name: bill.title })).toBe(card);
    expect(refresh).toHaveFocus();
    expect(dismiss).not.toHaveBeenCalled();
  });
  it("hides the previous filter's cards and cursor when a new filter fails and retries that filter", async () => {
    let response = () => Response.json({...page, next_cursor: "first-filter-cursor"});
    mockRequests(() => response());
    const view = render(<BillRecommendations filters={{q: "first"}} onOpenBill={() => true} />);
    await screen.findByRole("button", {name: "More recommendations"});
    response = () => new Response(null, {status: 500});
    view.rerender(<BillRecommendations filters={{q: "second"}} onOpenBill={() => true} />);
    await screen.findByText(/Recommendations could not be loaded/);
    expect(screen.queryByText(bill.title)).toBeNull();
    expect(screen.queryByRole("button", {name: "More recommendations"})).toBeNull();
    response = () => Response.json({...page, results: [{...page.results[0], bill: {...bill, title: "Second result"}}]});
    fireEvent.click(screen.getByRole("button", {name: "Refresh bill recommendations"}));
    await screen.findByRole("link", {name: "Second result"});
    expect(vi.mocked(fetch).mock.calls.map(([url]) => String(url)).filter(url => url.includes("q=second")))
      .toEqual([expect.not.stringContaining("cursor="), expect.not.stringContaining("cursor=")]);
  });

  it("does not reveal cached private recommendations before confirming the returning session", async () => {
    mockRequests(() => Response.json(page));
    const view = render(<BillRecommendations onOpenBill={() => true} />);
    await screen.findByRole("link", { name: bill.title });
    view.unmount();
    let release!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(done => { release = done; })));
    render(<BillRecommendations onOpenBill={() => true} />);
    expect(screen.queryByRole("link", { name: bill.title })).not.toBeInTheDocument();
    await act(async () => release(Response.json({ authenticated: true, user: { email: "reader@example.com" } })));
    expect(await screen.findByRole("link", { name: bill.title })).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([["D", "democrat"], ["R", "republican"]])("uses structured party %s for plain-name recommendation cards", async (party, theme) => {
    mockRequests(() => Response.json({ ...empty, results: [{ representative_id: 1, name: "Jane Doe", bioguide_id: "A000001", score: .4, reasons: [], topic_activity_evidence: { ...activity, representative: { ...activity.representative, name: "Jane Doe", party } } }], activity_as_of: activity.captured_at }));
    render(<RepresentativeRecommendations renderName={member => <button>{member.name} profile</button>} />);
    await screen.findByRole("button", { name: "Jane Doe profile" });
    expect(screen.getByRole("article")).toHaveAttribute("data-party", theme);
  });
  it("does not discard unchanged recommendations just because time passed", async () => {
    mockRequests(() => Response.json(page));
    const view = render(<BillRecommendations onOpenBill={() => true} />);
    await screen.findByRole("link", { name: bill.title });
    view.unmount();
    const clock = vi.spyOn(Date, "now").mockReturnValue(Date.now() + 300001);
    try {
      render(<BillRecommendations onOpenBill={() => true} />);
      await screen.findByRole("link", { name: bill.title });
      expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/tracking/recommendations/"))).toHaveLength(1);
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
    expect(screen.getByLabelText("Why recommended")).toHaveTextContent("Health");
    expect(screen.getByLabelText("Why recommended")).not.toHaveTextContent("a topic you follow");
    expect(screen.getByRole("link", { name: "Health" })).toHaveAttribute("href", "/bills?topic_id=1");
    expect(screen.getByRole("region", { name: "Recommended bills" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByText("Not recorded")).toBeVisible();
  });
  it("uses topic pills and a single representative badge with relationship tooltips", async () => {
    mockRequests(() => Response.json({ ...page, results: [{ ...page.results[0], reasons: [
      { kind: "followed_topic", topic_id: 1, name: "Health" },
      { kind: "followed_bill_topic", topic_id: 1, name: "Health", seed_bill_id: 2, seed_bill_number: "HR 2", seed_session: 119 },
      { kind: "followed_representative", representative_id: 410, name: "Sen. Britt, Katie Boyd [R-AL]", relation: "cosponsor" },
    ] }] }));
    render(<BillRecommendations onOpenBill={() => true} />);
    const badge = await screen.findByRole("link", { name: "Katie Boyd Britt" });
    expect(badge).toHaveAttribute("href", "/representatives/410");
    fireEvent.focus(badge);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Cosponsored this bill · You follow this representative");
    fireEvent.blur(badge);
    expect(badge).not.toHaveTextContent("Katie Boyd Britt");
    expect(await screen.findByRole("img", { name: "Katie Boyd Britt" })).toHaveAttribute("src", "https://www.congress.gov/img/member/b001319_200.jpg");
    expect(screen.getAllByRole("link", { name: "Health" })).toHaveLength(1);
    fireEvent.focus(screen.getByRole("link", { name: "Health" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("HR 2");
    fireEvent.blur(screen.getByRole("link", { name: "Health" }));
    expect(screen.queryByText(/Actively cosponsored by/)).not.toBeInTheDocument();
  });
  it("shows cold-start, recoverable error and retry states", async () => {
    let fails = true;
    mockRequests(() => fails ? Response.json({ detail: "unavailable" }, { status: 503 }) : Response.json(empty));
    render(<BillRecommendations onOpenBill={() => true} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    fails = false; fireEvent.click(screen.getByRole("button", { name: "Retry recommendations" }));
    expect(await screen.findByText(/Follow a topic or representative to start/)).toBeVisible();
  });
  it("appends more representatives while the existing cards stay mounted", async () => {
    const rep = (id: number) => ({ representative_id: id, name: `Member ${id}`, bioguide_id: "", reasons: [], topic_activity_evidence: activity });
    let finish!: (r: Response) => void;
    let requests = 0;
    mockRequests(() => ++requests === 1 ? Response.json({ ...empty, has_more: true, results: [rep(1)] }) : new Promise<Response>(resolve => { finish = resolve; }));
    render(<RepresentativeRecommendations />);
    const first = await screen.findByRole("link", { name: "Member 1" });
    fireEvent.click(await screen.findByRole("button", {name: "More representative recommendations"}));
    expect(first).toBeVisible();
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("shown=1"))).toBe(true);
    await act(async () => finish(Response.json({ ...empty, has_more: false, results: [rep(2)] })));
    expect(await screen.findByRole("link", { name: "Member 2" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Member 1" })).toBe(first);
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
    await waitFor(() => expect(screen.queryByRole("button", { name: "More recommendations" })).toBeNull());
    expect(screen.getByRole("link", { name: "Second proposal" })).toBeVisible();
  });
  it("keeps followed recommendations mounted and focused but clears them on session loss", async () => {
    let calls = 0;
    mockRequests(() => { calls++; return Response.json(page); });
    render(<BillRecommendations onOpenBill={() => true} />);
    const follow = await screen.findByRole("button", { name: "Follow bill HR 1 / 119" });
    follow.focus();
    fireEvent.click(follow);
    expect(await screen.findByRole("button", {name:"Unfollow bill HR 1 / 119"})).toBe(follow);
    expect(follow).toHaveFocus();
    expect(screen.getByRole("link", {name:bill.title})).toBeVisible();
    expect(calls).toBe(1);
    await act(async () => { await logout(); });
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
    mockRequests(() => Response.json({ ...empty, results: [{ representative_id: 1, name: "Member One", bioguide_id: "A000001", score: .4, reasons: [{ kind: "followed_topic", topic_id: 1, name: "Health", shared_topics: [], channel_evidence: {} }, { kind: "followed_representative_activity", representative_id: 2, name: "Other member", shared_topics: [{ id: 1, name: "Health", slug: "health" }, { id: 2, name: "Energy", slug: "energy" }], channel_evidence: {} }], topic_activity_evidence: { ...activity, channels: { ...activity.channels, sponsor: { ...channel, topics: [ { topic: { id: 1, name: "Health", slug: "health" }, grouped: { topic_observation_count: 9 } }, { topic: { id: 2, name: "Energy", slug: "energy" }, grouped: { topic_observation_count: 5 } } ] } } } }], activity_as_of: activity.captured_at }));
    render(<RepresentativeRecommendations renderName={member => <button>{member.name} profile</button>} />);
    expect(await screen.findByRole("button", { name: "Member One profile" })).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Health" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Health" })).toHaveAttribute("href", "/bills?topic_id=1");
    expect(screen.getByRole("link", { name: "Energy" })).toHaveAttribute("href", "/bills?topic_id=2");
    expect(screen.getByRole("link", { name: "Other member" })).toHaveAttribute("href", "/representatives/2");
    expect(screen.queryByText("Similar to")).not.toBeInTheDocument();
    expect(await screen.findByText("Saved representative biography.")).toBeVisible();
    expect(screen.getByRole("link", { name: "HR 22" })).toHaveAttribute("href", "/bills/22");
    fireEvent.focus(screen.getByRole("link", { name: "Other member" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Similar to this representative in recorded topic activity");
    fireEvent.blur(screen.getByRole("link", { name: "Other member" }));
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
