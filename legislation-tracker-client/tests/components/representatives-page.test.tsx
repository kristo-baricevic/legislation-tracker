import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepresentativesPage from "@/app/representatives/page";
import userEvent from "@testing-library/user-event";
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
  it("shows a successful tracking change in both views", async () => {
    vi.mocked(getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.com" } });
    vi.mocked(getMyTracking).mockResolvedValue({ is_staff: false, legislators: [], bills: [], topics: [] });
    render(<RepresentativesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Track Representative Example" }));
    expect(trackLegislator).toHaveBeenCalledWith(8);
    expect(await screen.findByRole("button", { name: "Untrack Representative Example" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Table view" }));
    expect(screen.getByRole("button", { name: "Tracked legislator" })).toBeVisible();
  });
  it("starts with avatars and switches to the same results in a table", async () => {
    render(<RepresentativesPage />);
    const grid = await screen.findByRole("list", { name: "Representatives" });
    expect(grid).toHaveTextContent("Independent");
    expect(grid).toHaveTextContent("House");
    expect(grid).toHaveTextContent("NY");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Table view" }));
    expect(screen.getByRole("table")).toHaveTextContent("Representative Example");
    expect(screen.queryByRole("list", { name: "Representatives" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Avatar view" }));
    expect(screen.getByRole("list", { name: "Representatives" })).toBeVisible();
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
    expect(getRepresentatives).toHaveBeenLastCalledWith(expect.objectContaining({ search: "stansbury", page: 1 }));
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
