import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillsPage from "@/app/bills/page";
import {
  createSavedBillSearch,
  getBills,
  getSession,
  getMyTracking,
  getSavedBillSearchResults,
  getSavedBillSearches,
  openSavedBillSearch,
} from "@/lib/api";

const searchState = vi.hoisted(() => ({ query: "topic_id=7" }));
const routerState = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(searchState.query),
  useRouter: () => routerState,
}));

vi.mock("@/lib/api", () => ({
  getBillFilterOptions: vi.fn().mockResolvedValue({
    jurisdictions: ["federal"],
    current_congress: 120,
  }),
  getBills: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
  getMyTracking: vi.fn().mockResolvedValue({ bills: [], topics: [], legislators: [], is_staff: false }),
  getSession: vi.fn().mockResolvedValue(null),
  getTopics: vi.fn().mockResolvedValue([{ id: 7, name: "Health", slug: "health" }]),
  parseTopicIdFromSearchParam: (value: string | null) => {
    if (!value || !/^\d+$/.test(value)) return undefined;
    const parsed = Number(value);
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
  },
  trackTopic: vi.fn(),
  trackBill: vi.fn().mockResolvedValue({}),
  untrackBill: vi.fn().mockResolvedValue(undefined),
  capturePersonalizedScope: vi.fn(() => ({})),
  isPersonalizedScopeCurrent: vi.fn(() => true),
  subscribePersonalizedChanges: vi.fn(() => () => {}),
  untrackTopic: vi.fn(),
  createSavedBillSearch: vi.fn(),
  getSavedBillSearches: vi.fn().mockResolvedValue({ count: 0, results: [] }),
  getSavedBillSearchResults: vi.fn(),
  openSavedBillSearch: vi.fn(),
}));

describe("BillsPage", () => {
  it("refreshes every loaded tracking page after a follow change without discarding earlier cards", async () => {
    searchState.query = "session=119&tracking=untracked";
    vi.mocked(getSession).mockResolvedValue({authenticated: true, user: {email: "reader@example.test"}});
    let intersect = () => {};
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) { intersect = () => callback([{isIntersecting: true} as IntersectionObserverEntry], this as unknown as IntersectionObserver); }
      observe() {} disconnect() {}
    });
    const item = (id: number) => ({id, jurisdiction: "federal", session: 119, bill_number: `HR ${id}`, title: `Bill ${id}`, status: "introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: []});
    vi.mocked(getBills).mockImplementation(async params => ({count: 3, next: params?.page === 1 ? "next" : null, previous: null, results: params?.page === 1 ? [item(1)] : [item(2)]}));
    render(<BillsPage />);
    await screen.findByRole("button", {name: "Follow"});
    await act(async () => intersect());
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(2));
    const first = screen.getAllByRole("article")[0];
    vi.mocked(getBills).mockClear();
    vi.mocked(getBills).mockImplementation(async params => ({count: 2, next: params?.page === 1 ? "next" : null, previous: null, results: params?.page === 1 ? [item(1)] : [item(3)]}));
    const api = await import("@/lib/api");
    vi.mocked(api.trackBill).mockImplementationOnce(async () => {
      // The real mutation announces a new interest generation before resolving.
      const listener = vi.mocked(api.subscribePersonalizedChanges).mock.calls[0][0];
      listener({kind: "tracking", scope: {sessionGeneration: 1, interestGeneration: 2}});
      return {} as never;
    });
    await userEvent.click(screen.getAllByRole("button", {name: "Follow"})[1]);
    await screen.findByRole("link", {name: "Bill 3"});
    expect(screen.getAllByRole("article")[0]).toBe(first);
    expect(vi.mocked(getBills).mock.calls.map(([params]) => params?.page)).toEqual([1, 2]);
    expect(screen.queryByRole("link", {name: "Bill 2"})).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });
  it("reaches earlier pages after reloading a page-three URL", async () => {
    searchState.query = "page=3&session=119";
    render(<BillsPage />);
    await userEvent.click(await screen.findByRole("button", {name: "Previous page"}));
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({page: 2, session: 119})));
    await userEvent.click(await screen.findByRole("button", {name: "Previous page"}));
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({page: 1, session: 119})));
    await waitFor(() => expect(screen.queryByRole("button", {name: "Previous page"})).toBeNull());
  });

  it.each([false, true])("clears a private filter when signed out (initially signed in %s)", async initiallySignedIn => {
    searchState.query = "session=119&tracking=tracked";
    if (initiallySignedIn) vi.mocked(getSession).mockResolvedValueOnce({authenticated: true, user: {email: "test@example.test"}});
    render(<BillsPage />);
    if (initiallySignedIn) {
      await waitFor(() => expect(getBills).toHaveBeenCalledWith(expect.objectContaining({tracking: "tracked"})));
      const api = await import("@/lib/api");
      const listener = vi.mocked(api.subscribePersonalizedChanges).mock.calls[0][0];
      act(() => listener({kind: "session", scope: {sessionGeneration: 2, interestGeneration: 2}}));
    }
    await screen.findByText("Log in to filter tracked bills.");
    expect(screen.getByRole("option", {name: "Tracked"})).toBeDisabled();
    await userEvent.selectOptions(screen.getByRole("combobox", {name: "Tracking"}), "");
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({tracking: undefined})));
  });

  it("waits for login resolution before requesting a private bill filter", async () => {
    searchState.query = "session=119&tracking=tracked";
    let resolveSession!: (value: Awaited<ReturnType<typeof getSession>>) => void;
    vi.mocked(getSession).mockReturnValueOnce(new Promise(resolve => { resolveSession = resolve; }));
    render(<BillsPage />);
    await screen.findByRole("status", {name: "Loading bills"});
    expect(screen.queryByRole("combobox", {name: "Tracking"})).toBeNull();
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 50)); });
    expect(getBills).not.toHaveBeenCalled();
    resolveSession({authenticated: true, user: {email: "reader@example.test"}});
    await waitFor(() => expect(getBills).toHaveBeenCalledWith(expect.objectContaining({tracking: "tracked"})));
  });
  it("does not display cancelled authentication requests as errors", async () => {
    vi.mocked(getBills).mockRejectedValue(new DOMException("Session or followed interests changed", "AbortError"));
    render(<BillsPage />);
    await waitFor(() => expect(getBills).toHaveBeenCalled());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 50)); });
    expect(screen.queryByText("Session or followed interests changed")).not.toBeInTheDocument();
    expect(screen.queryByText("Failed to load bills")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("filters tracking on the server and resets pagination without moving focus", async () => {
    searchState.query = "page=3&session=119";
    vi.mocked(getSession).mockResolvedValueOnce({ authenticated: true, user: { email: "reader@example.test" } });
    render(<BillsPage />);
    const filter = await screen.findByRole("combobox", { name: "Tracking" });
    await waitFor(() => expect(filter).toBeEnabled());
    await userEvent.selectOptions(filter, "tracked");
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ tracking: "tracked", page: 1, session: 119 })));
    expect(filter).toHaveFocus();
    await userEvent.selectOptions(filter, "untracked");
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ tracking: "untracked", page: 1 })));
    await userEvent.selectOptions(filter, "");
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ tracking: undefined })));
  });
  it("holds the catalog until tracking settles and restores follow actions after retry", async () => {
    vi.mocked(getSession).mockResolvedValueOnce({ authenticated: true, user: { email: "reader@example.test" } });
    let rejectTracking!: (reason: Error) => void;
    vi.mocked(getMyTracking).mockReturnValueOnce(new Promise((_, reject) => { rejectTracking = reject; }));
    vi.mocked(getBills).mockResolvedValue({ count: 1, next: null, previous: null, results: [{ id: 42, jurisdiction: "federal", session: 119, bill_number: "HR 42", title: "School grants", status: "introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [] }] });
    render(<BillsPage />);
    await screen.findByRole("status", { name: "Loading bills" });
    expect(screen.queryByRole("heading", { name: "Ingested Bills" })).toBeNull();
    expect(screen.queryByRole("searchbox")).toBeNull();
    rejectTracking(new Error("Unavailable"));
    const retry = await screen.findByRole("button", { name: "Retry follow status" });
    expect(retry).toHaveTextContent(/^Retry$/);
    vi.mocked(getSession).mockResolvedValueOnce({ authenticated: true, user: { email: "reader@example.test" } });
    await userEvent.click(retry);
    expect(await screen.findByRole("button", { name: /^Follow$/ })).toBeEnabled();
    expect(screen.queryByText("Load follow status")).not.toBeInTheDocument();
  });
  it("appends infinite-scroll results without replacing existing cards or skipping failed pages", async () => {
    let intersect = () => {};
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) { intersect = () => callback([{isIntersecting: true} as IntersectionObserverEntry], this as unknown as IntersectionObserver); }
      observe() {} disconnect() {}
    });
    const result = { count: 2, next: "next", previous: null, results: [{ id: 42, jurisdiction: "federal", session: 119, bill_number: "HR 42", title: "School grants", status: "introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [] }] };
    vi.mocked(getBills).mockResolvedValue(result);
    render(<BillsPage />);
    const card = await screen.findByRole("article");
    let resolvePage!: (value: typeof result) => void;
    vi.mocked(getBills).mockReturnValueOnce(new Promise(resolve => { resolvePage = resolve; }));
    await act(async () => { intersect(); intersect(); });
    expect(screen.getByRole("article")).toBe(card);
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Previous" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Bill results" })).toHaveAttribute("aria-busy", "true");
    expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({page: 2}));
    await act(async () => resolvePage({...result, results: [{...result.results[0], id: 43, title: "Second bill"}]}));
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(screen.getAllByRole("article")[0]).toBe(card);
    vi.mocked(getBills).mockRejectedValueOnce(new Error("Offline"));
    await act(async () => intersect());
    expect(await screen.findByRole("button", {name: "Retry loading bills"})).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    vi.mocked(getBills).mockResolvedValueOnce({...result, next: null, results: [{...result.results[0], id: 44, title: "Third bill"}]});
    await userEvent.click(screen.getByRole("button", {name: "Retry loading bills"}));
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(3));
    expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({page: 3}));
    vi.mocked(getBills).mockResolvedValueOnce({...result, next: null});
    await userEvent.selectOptions(screen.getByRole("combobox", {name: "Status"}), "stage:law");
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));
    vi.unstubAllGlobals();
  });
  it("does not duplicate the navbar with a Dashboard back link", async () => {
    render(<BillsPage />);
    await screen.findByRole("heading", { name: "Ingested Bills" });
    expect(screen.queryByRole("link", { name: /dashboard/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Jurisdiction", {exact:true})).not.toBeInTheDocument();
  });
  it("selects a status stage and clears it without retaining the old page", async () => {
    searchState.query = "page=3&session=119";
    render(<BillsPage />);
    const user = userEvent.setup();
    const status = await screen.findByRole("combobox", { name: "Status" });
    await screen.findByRole("option", { name: "Passed one chamber" });
    await user.selectOptions(status, "stage:first_chamber");
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ status: "stage:first_chamber", page: 1 })));
    await user.selectOptions(status, "");
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ status: undefined, page: 1 })));
  });

  it("keeps a legacy URL status visible until the reader clears it", async () => {
    searchState.query = "status=House";
    render(<BillsPage />);
    const status = await screen.findByRole("combobox", { name: "Status" });
    expect(status).toHaveValue("House");
    expect(screen.getByRole("option", { name: "Saved filter: House" })).toBeVisible();
  });

  it("keeps neighboring follow buttons usable during a save and background tracking refresh", async () => {
    searchState.query = "session=119";
    const api = await import("@/lib/api");
    vi.mocked(getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.test" } });
    const results = [1, 2].map(id => ({ id, jurisdiction: "federal", session: 119, bill_number: `HR ${id}`, title: `Bill ${id}`, status: "introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [] }));
    vi.mocked(getBills).mockResolvedValue({ count: 2, next: null, previous: null, results });
    let finish!: () => void;
    vi.mocked(api.trackBill).mockImplementationOnce(async () => {
      await new Promise<void>(resolve => { finish = resolve; });
      vi.mocked(api.subscribePersonalizedChanges).mock.calls[0][0]({kind: "tracking", scope: {sessionGeneration: 0, interestGeneration: 1}});
      return {} as never;
    });
    render(<BillsPage />);
    const [first, second] = await screen.findAllByRole("button", {name: "Follow"});
    vi.mocked(getMyTracking).mockReturnValueOnce(new Promise(() => {}));
    await userEvent.click(first);
    expect(first).toHaveTextContent(/^Follow$/);
    expect(second).toBeEnabled();
    await act(async () => finish());
    expect(first).toHaveTextContent("Unfollow");
    expect(screen.getByRole("button", {name: "Follow"})).toBe(second);
    await userEvent.click(second);
    expect(second).toHaveTextContent("Unfollow");
  });

  it("lets signed-in readers follow and unfollow directly from a bill card", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.com" } });
    vi.mocked(getBills).mockResolvedValue({ count: 1, next: null, previous: null, results: [{ id: 881, jurisdiction: "federal", session: 119, bill_number: "HR 7744", title: "DHS funding", status: "introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [] }] });
    render(<BillsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Follow" }));
    expect(await screen.findByRole("button", { name: "Unfollow" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Unfollow" }));
    expect(await screen.findByRole("button", { name: "Follow" })).toHaveAttribute("aria-pressed", "false");
  });
  it("shows search cards with clickable titles and no redundant full-bill links", async () => {
    vi.mocked(getBills).mockResolvedValue({ count: 1, next: null, previous: null, results: [{
      id: 42, jurisdiction: "federal", session: 119, bill_number: "HR 42", title: "Rural health grants",
      status: "introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [],
      highlights: [{ kind: "metadata", segments: [{ text: "Rural", matched: true }, { text: " health grants", matched: false }] }],
    }] });
    render(<BillsPage />);
    expect(await screen.findByRole("article")).toHaveTextContent("Rural health grants");
    expect(screen.getByRole("link", { name: "Rural health grants" })).toHaveAttribute("href", "/bills/42");
    expect(screen.queryByRole("link", { name: "Open full bill page" })).not.toBeInTheDocument();
    expect(screen.getByText("Rural", { selector: "mark" })).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  beforeEach(async () => {
    const api = await import("@/lib/api");
    searchState.query = "topic_id=7";
    vi.clearAllMocks();
    vi.mocked(api.getBillFilterOptions).mockResolvedValue({
      jurisdictions: ["federal"],
      current_congress: 120,
    });
    vi.mocked(api.getBills).mockResolvedValue({
      count: 0,
      next: null,
      previous: null,
      results: [],
    });
    vi.mocked(api.getSession).mockResolvedValue(null);
    vi.mocked(api.getMyTracking).mockResolvedValue({ bills: [], topics: [], legislators: [], is_staff: false });
    vi.mocked(api.getTopics).mockResolvedValue([
      { id: 7, name: "Health", slug: "health" },
    ]);
    vi.mocked(api.getSavedBillSearches).mockResolvedValue({ count: 0, results: [] });
  });

  it("does not flash a loader while the catalog request starts", async () => {
    vi.mocked(getBills).mockReturnValueOnce(new Promise(() => {}));
    render(<BillsPage />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(await screen.findByRole("status", { name: "Loading bills" })).toBeVisible();
  });

  it("shows topic-linked bills across every Congress", async () => {
    render(<BillsPage />);

    await waitFor(() => {
      expect(getBills).toHaveBeenCalledWith(expect.objectContaining({ topic_id: 7, session: undefined }));
    });
    expect(getBills).not.toHaveBeenCalledWith(expect.objectContaining({ topic_id: 7, session: 120 }));
  });

  it("reveals session 119 filters only after topic choices and saved searches settle", async () => {
    const api = await import("@/lib/api");
    searchState.query = "session=119";
    vi.mocked(getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.test" } });
    let resolveTopics!: (value: Awaited<ReturnType<typeof api.getTopics>>) => void;
    let resolveSearches!: (value: Awaited<ReturnType<typeof api.getSavedBillSearches>>) => void;
    vi.mocked(api.getTopics).mockReturnValueOnce(new Promise(resolve => { resolveTopics = resolve; }));
    vi.mocked(api.getSavedBillSearches).mockReturnValueOnce(new Promise(resolve => { resolveSearches = resolve; }));
    render(<BillsPage />);
    await screen.findByRole("status", { name: "Loading bills" });
    expect(screen.queryByRole("searchbox")).toBeNull();
    await act(async () => resolveTopics([]));
    expect(screen.queryByRole("searchbox")).toBeNull();
    await act(async () => resolveSearches({ count: 0, results: [] }));
    expect(screen.getByRole("searchbox")).toBeVisible();
    expect(screen.getByLabelText("Session (Congress)")).toHaveValue("119");
    expect(screen.getByRole("button", { name: "Save this search" })).toBeVisible();
  });

  it("switches between oldest and recent activity for Congress 119 without a text query", async () => {
    searchState.query = "session=119";
    render(<BillsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Sort Unsorted" }));
    for (const [label, sort] of [["Relevance", "relevance"], ["Unsorted", "unsorted"]]) {
      await userEvent.click(screen.getByRole("option", { name: label }));
      await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ session: 119, sort })));
      await userEvent.click(screen.getByRole("button", { name: "Sort " + label }));
    }
    await userEvent.click(screen.getByRole("option", { name: "Oldest activity" }));
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ session: 119, sort: "oldest_activity" })));
    await userEvent.click(screen.getByRole("button", { name: "Sort Oldest activity" }));
    await userEvent.click(screen.getByRole("option", { name: "Recent activity" }));
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ session: 119, sort: "recent_activity" })));
  });

  it.each(["Unsorted", "Recent activity", "Oldest activity", "Relevance"])("keeps explicitly selected %s while entering and clearing a search", async label => {
    searchState.query = "session=119";
    render(<BillsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Sort Unsorted" }));
    await userEvent.click(screen.getByRole("option", { name: label }));
    const input = screen.getByRole("searchbox");
    const sort = label.toLowerCase().replace(" ", "_");
    await userEvent.type(input, "clinic");
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ q: "clinic", sort })));
    await userEvent.clear(input);
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ q: undefined, sort })));
  });

  it("initializes the Congress filter from API metadata", async () => {
    searchState.query = "";
    render(<BillsPage />);

    await waitFor(() => {
      expect(getBills).toHaveBeenCalledWith(
        expect.objectContaining({ session: 120 }),
      );
    });
    expect(getBills).not.toHaveBeenCalledWith(
      expect.objectContaining({ session: 119 }),
    );
  });

  it("keeps the current-Congress default when topic choices fail", async () => {
    const api = await import("@/lib/api");
    searchState.query = "";
    vi.mocked(api.getTopics).mockRejectedValueOnce(new Error("topics unavailable"));

    render(<BillsPage />);

    await waitFor(() => {
      expect(getBills).toHaveBeenCalledWith(
        expect.objectContaining({ session: 120 }),
      );
    });
    expect(screen.getByText("Could not load topic choices.")).toBeVisible();
  });

  it("blocks bill loading and retries when current-Congress metadata fails", async () => {
    const api = await import("@/lib/api");
    const user = userEvent.setup();
    searchState.query = "";
    vi.mocked(api.getBillFilterOptions)
      .mockRejectedValueOnce(new Error("metadata unavailable"))
      .mockResolvedValueOnce({ jurisdictions: ["federal"], current_congress: 120 });

    render(<BillsPage />);

    expect(await screen.findByText("Could not load bill filter metadata.")).toBeVisible();
    expect(getBills).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Retry bill metadata" }));

    await waitFor(() => {
      expect(getBills).toHaveBeenCalledWith(
        expect.objectContaining({ session: 120 }),
      );
    });
  });

  it("surfaces a malformed topic URL instead of widening to all bills", async () => {
    searchState.query = "topic_id=not-a-number";

    render(<BillsPage />);

    expect(await screen.findByText("topic_id must be a positive integer.")).toBeVisible();
    expect(getBills).not.toHaveBeenCalled();
  });

  it("preserves a deep-linked search page instead of resetting it during debounce setup", async () => {
    searchState.query = "q=rural+hospital&sort=relevance&page=3";

    render(<BillsPage />);

    await waitFor(() => {
      expect(getBills).toHaveBeenCalledWith(
        expect.objectContaining({ q: "rural hospital", sort: "relevance", page: 3 }),
      );
    });
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    expect(getBills).not.toHaveBeenCalledWith(
      expect.objectContaining({ q: "rural hospital", page: 1 }),
    );
  });

  it("debounces search and switches automatically between unsorted and relevance", async () => {
    const user = userEvent.setup();
    searchState.query = "";
    render(<BillsPage />);
    await waitFor(() => expect(getBills).toHaveBeenCalled());
    vi.mocked(getBills).mockClear();

    await user.type(screen.getByRole("searchbox", { name: "Full-text search" }), "clinic");
    expect(getBills).not.toHaveBeenCalledWith(expect.objectContaining({ q: "clinic" }));

    await waitFor(
      () => expect(getBills).toHaveBeenCalledWith(expect.objectContaining({ q: "clinic", sort: "relevance" })),
      { timeout: 1000 },
    );
    await user.clear(screen.getByRole("searchbox", { name: "Full-text search" }));
    await waitFor(() => expect(getBills).toHaveBeenLastCalledWith(expect.objectContaining({ q: undefined, sort: "unsorted" })));
  });

  it("rehydrates every public filter when browser history changes", async () => {
    searchState.query = "session=118&id=5&bill_number=HR+5&jurisdiction=federal&status=Passed&sponsor=Smith&topic=health&q=clinics&sort=relevance&page=2";
    const { rerender } = render(<BillsPage />);
    await waitFor(() => {
      expect(getBills).toHaveBeenCalledWith(expect.objectContaining({ session: 118, id: 5, page: 2, q: "clinics" }));
    });

    searchState.query = "session=120&id=9&bill_number=S+9&jurisdiction=state&status=Filed&sponsor=Jones&topic=energy&q=grants&sort=relevance&page=4";
    rerender(<BillsPage />);

    await waitFor(() => {
      expect(screen.getByLabelText("Session (Congress)")).toHaveValue("120");
      expect(screen.getByLabelText("Bill ID")).toHaveValue("9");
      expect(screen.getByLabelText("Bill # (contains)")).toHaveValue("S 9");
      expect(screen.getByRole("combobox", { name: "Status" })).toHaveValue("Filed");
      expect(screen.getByLabelText("Sponsor")).toHaveValue("Jones");
      expect(screen.getByLabelText("Topic contains")).toHaveValue("energy");
      expect(screen.getByRole("searchbox", { name: "Full-text search" })).toHaveValue("grants");
      expect(getBills).toHaveBeenCalledWith(expect.objectContaining({ session: 120, id: 9, page: 4, q: "grants" }));
    });
  });

  it("names and saves the current search without a browser prompt", async () => {
    const api = await import("@/lib/api");
    const user = userEvent.setup();
    searchState.query = "page=2&session=119&jurisdiction=federal&topic_id=7";
    vi.mocked(api.getSession).mockResolvedValue({ id: 1 } as never);
    vi.mocked(createSavedBillSearch).mockResolvedValue({
      id: 12,
      name: "Health policy",
      query_json: { session: 119, jurisdiction: "federal", topic_id: 7 },
      last_opened_at: null,
      last_opened_activity_sequence: null,
      new_result_count: 0,
    });

    render(<BillsPage />);
    await user.click(await screen.findByRole("button", { name: "Save this search" }));

    const nameInput = screen.getByRole("textbox", { name: "Saved search name" });
    await user.type(nameInput, "Health policy");
    await user.click(screen.getByRole("button", { name: "Save search" }));

    await waitFor(() => {
      expect(createSavedBillSearch).toHaveBeenCalledWith("Health policy", {
        session: 119,
        jurisdiction: "federal",
        topic_id: 7,
      });
    });
    expect(await screen.findByRole("button", { name: "Health policy" })).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Saved search name" })).not.toBeInTheDocument();
  });

  it("acknowledges a saved search only after its result page is rendered and refreshes server counts", async () => {
    const api = await import("@/lib/api");
    const user = userEvent.setup();
    searchState.query = "";
    vi.mocked(api.getSession).mockResolvedValue({ id: 1 } as never);
    vi.mocked(getSavedBillSearches)
      .mockResolvedValueOnce({ count: 1, results: [{ id: 4, name: "Rural", query_json: { q: "clinic" }, last_opened_at: null, last_opened_activity_sequence: null, new_result_count: 2 }] })
      .mockResolvedValueOnce({ count: 1, results: [{ id: 4, name: "Rural", query_json: { q: "clinic" }, last_opened_at: "2026-08-31T00:00:00Z", last_opened_activity_sequence: 8, new_result_count: 0 }] });
    const renderedResult = {
      count: 1,
      next: null,
      previous: null,
      results: [{ id: 9, jurisdiction: "federal", session: 120, bill_number: "HR 9", title: "Rendered saved result", status: "Introduced", sponsor_name: null, introduced_at: null, last_action_at: null, topics: [] }],
    };
    vi.mocked(getSavedBillSearchResults).mockResolvedValue({
      ...renderedResult,
      result_watermark: "watermark",
    });
    vi.mocked(openSavedBillSearch).mockResolvedValue({ previous_activity_sequence: null, last_opened_activity_sequence: 8, last_opened_at: "2026-08-31T00:00:00Z" });
    vi.mocked(getBills).mockImplementation((params) => Promise.resolve(
      params?.q === "clinic"
        ? renderedResult
        : { count: 0, next: null, previous: null, results: [] },
    ));

    render(<BillsPage />);
    await user.click(await screen.findByRole("button", { name: "Rural (2 new)" }));

    expect(await screen.findByText("Rendered saved result")).toBeVisible();
    await waitFor(() => expect(openSavedBillSearch).toHaveBeenCalledWith(4, "watermark"));
    await waitFor(() => expect(getSavedBillSearches).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("button", { name: "Rural" })).toBeVisible();
  });
});
