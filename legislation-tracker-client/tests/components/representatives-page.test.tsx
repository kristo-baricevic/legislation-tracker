import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepresentativesPage from "@/app/representatives/page";
import userEvent from "@testing-library/user-event";
import { beginSessionTransition, endSessionTransition } from "@/lib/personalized-scope";
import { getBillFilterOptions, getRepresentatives, getSession, getMyTracking, trackLegislator } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a>,
}));

vi.mock("@/lib/api", () => ({
  getRepresentatives: vi.fn().mockResolvedValue({ count: 1, next: null, previous: null, results: [{ id: 8, bioguide_id: "R000001", name: "Representative Example", chamber: "house", party: "Independent", state: "NY", district: "12", first_name: "Representative", last_name: "Example", official_website_url: null, image_url: null, is_current: true }] }),
  getBillFilterOptions: vi.fn().mockResolvedValue({ jurisdictions: ["federal"], current_congress: 119 }),
  getSession: vi.fn().mockResolvedValue(null),
  getMyTracking: vi.fn(),
  trackLegislator: vi.fn(),
  untrackLegislator: vi.fn(),
}));

describe("RepresentativesPage", () => {
  it("waits for tracking before showing the first representative card", async () => {
    const { results: [rep] } = await getRepresentatives();
    vi.mocked(getSession).mockResolvedValueOnce({ authenticated: true, user: { email: "reader@example.test" } });
    let finish!: () => void;
    vi.mocked(getMyTracking).mockImplementationOnce(() => new Promise(resolve => {
      finish = () => resolve({ is_staff: false, bills: [], topics: [], legislators: [{ id: 1, representative: rep, created_at: "" }] });
    }));
    render(<RepresentativesPage />);
    await waitFor(() => expect(finish).toBeDefined());
    expect(screen.queryByRole("list", { name: "Representatives" })).not.toBeInTheDocument();
    expect(await screen.findByRole("status", { name: "Loading representatives" })).toBeVisible();
    await act(async () => finish());
    expect(await screen.findByRole("button", { name: "Untrack Representative Example" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("status", { name: "Loading representatives" })).not.toBeInTheDocument();
  });
  it("clears private tracking results on logout and ignores a late old-account response", async () => {
    const initial = await getRepresentatives();
    vi.mocked(getSession).mockResolvedValueOnce({ authenticated: true, user: { email: "reader@example.test" } });
    vi.mocked(getMyTracking).mockResolvedValue({ is_staff: false, legislators: [], bills: [], topics: [] });
    render(<RepresentativesPage />);
    await screen.findByRole("button", { name: "Track Representative Example" });
    let finish!: (value: typeof initial) => void;
    vi.mocked(getRepresentatives).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    await userEvent.click(screen.getByRole("button", { name: "Tracking All" }));
    await userEvent.click(screen.getByRole("option", { name: "Tracked" }));
    vi.mocked(getSession).mockResolvedValue(null);
    await act(async () => { beginSessionTransition(); endSessionTransition(null); });
    await waitFor(() => expect(screen.getByRole("button", { name: "Tracking All" })).toBeDisabled());
    await act(async () => finish({ ...initial, results: [{ ...initial.results[0], name: "Private old follow" }] }));
    expect(screen.queryByRole("link", { name: "Private old follow" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Track Representative Example" })).not.toBeInTheDocument();
  });
  it("isolates pending tracking to each clicked representative without refetching the directory", async () => {
    const initial = await getRepresentatives();
    const rep = initial.results[0];
    vi.mocked(getRepresentatives).mockResolvedValueOnce({ ...initial, count: 2, results: [rep, { ...rep, id: 9, name: "Second Example" }] });
    vi.mocked(getSession).mockResolvedValueOnce({ authenticated: true, user: { email: "reader@example.test" } });
    vi.mocked(getMyTracking).mockResolvedValue({ is_staff: false, legislators: [], bills: [], topics: [] });
    let first!: () => void;
    let second!: () => void;
    vi.mocked(trackLegislator).mockReturnValueOnce(new Promise(resolve => { first = () => resolve({} as Awaited<ReturnType<typeof trackLegislator>>); }))
      .mockReturnValueOnce(new Promise(resolve => { second = () => resolve({} as Awaited<ReturnType<typeof trackLegislator>>); }));
    render(<RepresentativesPage />);
    const a = await screen.findByRole("button", { name: `Track ${rep.name}` });
    const b = screen.getByRole("button", { name: "Track Second Example" });
    const directoryCalls = vi.mocked(getRepresentatives).mock.calls.length;
    const trackingCalls = vi.mocked(getMyTracking).mock.calls.length;
    await userEvent.click(a);
    expect(a).toHaveAttribute("aria-disabled", "true");
    expect(a).toHaveTextContent("+ Track");
    expect(b).toHaveAttribute("aria-disabled", "false");
    expect(b).toHaveTextContent("+ Track");
    expect(b).toHaveAttribute("aria-busy", "false");
    await userEvent.click(b);
    await act(async () => first());
    expect(a).toHaveAttribute("aria-disabled", "false");
    expect(a).toHaveTextContent("✓ Tracked");
    expect(b).toHaveAttribute("aria-disabled", "true");
    await act(async () => second());
    expect(b).toHaveAttribute("aria-disabled", "false");
    expect(b).toHaveTextContent("✓ Tracked");
    expect(screen.getByRole("button", { name: `Untrack ${rep.name}` })).toBe(a);
    expect(getRepresentatives).toHaveBeenCalledTimes(directoryCalls);
    expect(getMyTracking).toHaveBeenCalledTimes(trackingCalls);
  });
  it.each([true, false])("keeps the same filter controls while the account check resolves: signed in %s", async signedIn => {
    let resolveSession!: (value: Awaited<ReturnType<typeof getSession>>) => void;
    vi.mocked(getSession).mockReturnValueOnce(new Promise(resolve => { resolveSession = resolve; }));
    vi.mocked(getMyTracking).mockResolvedValue({ is_staff: false, legislators: [], bills: [], topics: [] });
    render(<RepresentativesPage />);
    const tracking = screen.getByRole("button", { name: "Tracking All" });
    const state = screen.getByRole("button", { name: "State All" });
    expect(tracking).toBeDisabled();
    await userEvent.click(tracking);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await act(async () => resolveSession(signedIn ? { authenticated: true, user: { email: "reader@example.com" } } : null));
    expect(screen.getByRole("button", { name: "Tracking All" })).toBe(tracking);
    expect(screen.getByRole("button", { name: "State All" })).toBe(state);
    if (signedIn) expect(tracking).toBeEnabled();
    else expect(tracking).toBeDisabled();
  });
  it("keeps the current directory visible until replacement filter results arrive", async () => {
    render(<RepresentativesPage />);
    const member = await screen.findByRole("link", { name: "Representative Example" });
    vi.mocked(getRepresentatives).mockReturnValueOnce(new Promise(() => {}));
    await userEvent.click(screen.getByRole("button", { name: "Party All" }));
    await userEvent.click(screen.getByRole("option", { name: "Democrat" }));
    expect(screen.getByRole("link", { name: "Representative Example" })).toBe(member);
    expect(screen.getByRole("list", { name: "Representatives" })).toHaveAttribute("aria-busy", "true");
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 300)); });
    expect(screen.queryByRole("status", { name: "Loading representatives" })).not.toBeInTheDocument();
  });
  let intersect: () => void;
  let observerReady = false;
  beforeEach(() => {
    vi.clearAllMocks();
    intersect = () => {};
    observerReady = false;
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) {
        intersect = () => callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
      }
      observe() { observerReady = true; }
      disconnect() { observerReady = false; intersect = () => {}; }
    });
  });
  it("appends on scroll, retries the failed page, and resets when party changes", async () => {
    const initial = await getRepresentatives();
    const first = initial.results[0];
    vi.mocked(getRepresentatives).mockResolvedValueOnce({ ...initial, count: 2, next: "?page=2" })
      .mockRejectedValueOnce(new Error("Network unavailable"))
      .mockResolvedValueOnce({ ...initial, count: 2, results: [{ ...first, id: 9, first_name: "Second", name: "Second Example" }] });
    render(<RepresentativesPage />);
    await screen.findByRole("link", { name: "Representative Example" });
    await waitFor(() => expect(observerReady).toBe(true));
    await act(async () => { intersect(); intersect(); });
    await userEvent.click(await screen.findByRole("button", { name: "Retry loading representatives" }));
    expect(await screen.findByRole("link", { name: "Second Example" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Representative Example" })).toBeVisible();
    expect(getRepresentatives).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
    await userEvent.click(screen.getByRole("button", { name: "Party All" }));
    await userEvent.click(screen.getByRole("option", { name: "Independent" }));
    await waitFor(() => expect(getRepresentatives).toHaveBeenLastCalledWith(expect.objectContaining({ party: "I", page: 1 })));
    expect(screen.queryByRole("link", { name: "Second Example" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });
  it("ignores a previous page that arrives after the party filter changes", async () => {
    const initial = await getRepresentatives();
    let finishOld!: (value: typeof initial) => void;
    vi.mocked(getRepresentatives).mockResolvedValueOnce({ ...initial, count: 2, next: "?page=2" })
      .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }))
      .mockResolvedValueOnce({ ...initial, count: 0, results: [] });
    render(<RepresentativesPage />);
    await screen.findByRole("link", { name: "Representative Example" });
    await waitFor(() => expect(observerReady).toBe(true));
    await act(async () => { intersect(); });
    await userEvent.click(screen.getByRole("button", { name: "Party All" }));
    await userEvent.click(screen.getByRole("option", { name: "Democrat" }));
    await screen.findByText("No representatives found.");
    await act(async () => { finishOld(initial); });
    expect(screen.queryByRole("link", { name: "Representative Example" })).not.toBeInTheDocument();
    expect(screen.getByText("No representatives found.")).toBeVisible();
  });
  it("shows a successful tracking change in the grid", async () => {
    vi.mocked(getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.com" } });
    vi.mocked(getMyTracking).mockResolvedValue({ is_staff: false, legislators: [], bills: [], topics: [] });
    render(<RepresentativesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Track Representative Example" }));
    expect(trackLegislator).toHaveBeenCalledWith(8);
    expect(await screen.findByRole("button", { name: "Untrack Representative Example" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Table view" })).not.toBeInTheDocument();
  });
  it("uses only the avatar grid", async () => {
    render(<RepresentativesPage />);
    expect(await screen.findByRole("list", { name: "Representatives" })).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Table view" })).not.toBeInTheDocument();
  });
  it("announces initial loading with a decorative spinner", async () => {
    vi.mocked(getRepresentatives).mockReturnValueOnce(new Promise(() => {}));
    render(<RepresentativesPage />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("");
    expect(status).toHaveAccessibleName("Loading representatives");
    expect(status.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });
  it("retries a failed tracking-filter refresh from the first loaded page", async () => {
    const initial = await getRepresentatives();
    vi.mocked(getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.com" } });
    vi.mocked(getMyTracking).mockResolvedValue({ is_staff: false, legislators: [], bills: [], topics: [] });
    render(<RepresentativesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Tracking All" }));
    vi.mocked(getRepresentatives).mockResolvedValueOnce({ ...initial, next: "?page=2" })
      .mockResolvedValueOnce({ ...initial, results: [{ ...initial.results[0], id: 9, first_name: "Second", name: "Second Example" }] });
    await userEvent.click(screen.getByRole("option", { name: "Untracked" }));
    await waitFor(() => expect(observerReady).toBe(true));
    await act(async () => intersect());
    await screen.findByRole("link", { name: "Second Example" });
    vi.mocked(getRepresentatives).mockRejectedValueOnce(new Error("Refresh failed")).mockResolvedValueOnce({ ...initial, count: 0, results: [] });
    await userEvent.click(screen.getByRole("button", { name: "Track Representative Example" }));
    await userEvent.click(await screen.findByRole("button", { name: "Retry loading representatives" }));
    expect(await screen.findByText("No representatives found.")).toBeVisible();
    expect(getRepresentatives).toHaveBeenLastCalledWith(expect.objectContaining({ tracking: "untracked", page: 1 }));
  });

  it("filters the directory by tracking and refreshes after a tracking change", async () => {
    vi.mocked(getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.com" } });
    vi.mocked(getMyTracking).mockResolvedValue({ is_staff: false, legislators: [], bills: [], topics: [] });
    render(<RepresentativesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Tracking All" }));
    await userEvent.click(screen.getByRole("option", { name: "Untracked" }));
    await waitFor(() => expect(getRepresentatives).toHaveBeenLastCalledWith(expect.objectContaining({tracking: "untracked", page: 1})));
    vi.mocked(getRepresentatives).mockResolvedValueOnce({ count: 0, next: null, previous: null, results: [] });
    await userEvent.click(await screen.findByRole("button", { name: "Track Representative Example" }));
    expect(await screen.findByText("No representatives found.")).toBeVisible();
    expect(getRepresentatives).toHaveBeenLastCalledWith(expect.objectContaining({tracking: "untracked", page: 1}));
    await userEvent.click(screen.getByRole("button", { name: "Tracking Untracked" }));
    await userEvent.click(screen.getByRole("option", { name: "Tracked" }));
    await waitFor(() => expect(getRepresentatives).toHaveBeenLastCalledWith(expect.objectContaining({tracking: "tracked", page: 1})));
  });
  it("searches the directory by name and resets pagination", async () => {
    vi.mocked(getRepresentatives).mockImplementation(async (params) => ({
      count: params?.search ? 0 : 21, next: params?.search ? null : "?page=2", previous: null,
      results: Array.from({ length: params?.search ? 0 : 20 }, (_, i) => ({ id: i + 1, name: "Member " + i, bioguide_id: "A000001", chamber: "house", party: "D", state: "NY", district: "1", first_name: "Member", last_name: String(i), image_url: null, official_website_url: null, is_current: true })),
    }));
    render(<RepresentativesPage />);
    const user = userEvent.setup();
    await screen.findByRole("list", { name: "Representatives" });
    await waitFor(() => expect(observerReady).toBe(true));
    await act(async () => { intersect(); });
    await user.type(screen.getByRole("searchbox", { name: "Search by name" }), "stansbury");
    expect(await screen.findByText("No representatives found.")).toBeVisible();
    await waitFor(() => expect(getRepresentatives).toHaveBeenLastCalledWith(expect.objectContaining({ search: "stansbury", page: 1 })));
  });
  beforeEach(() => {
    vi.mocked(getSession).mockResolvedValue(null);
    vi.mocked(getBillFilterOptions).mockResolvedValue({ jurisdictions: ["federal"], current_congress: 119 });
    vi.mocked(getRepresentatives).mockResolvedValue({ count: 1, next: null, previous: null, results: [{ id: 8, bioguide_id: "R000001", name: "Representative Example", chamber: "house", party: "Independent", state: "NY", district: "12", first_name: "Representative", last_name: "Example", official_website_url: null, image_url: null, is_current: true }] });
  });

  it("links a representative to the factual detail experience", async () => {
    render(<RepresentativesPage />);
    const link = await screen.findByRole("link", { name: "Representative Example" });
    expect(link).toHaveAttribute("href", "/representatives/8?congress=119");
  });
});
