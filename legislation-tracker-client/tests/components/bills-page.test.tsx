import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillsPage from "@/app/bills/page";
import {
  createSavedBillSearch,
  getBills,
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
  untrackTopic: vi.fn(),
  createSavedBillSearch: vi.fn(),
  getSavedBillSearches: vi.fn().mockResolvedValue({ count: 0, results: [] }),
  getSavedBillSearchResults: vi.fn(),
  openSavedBillSearch: vi.fn(),
}));

describe("BillsPage", () => {
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

  it("shows topic-linked bills across every Congress", async () => {
    render(<BillsPage />);

    await waitFor(() => {
      expect(getBills).toHaveBeenCalledWith(expect.objectContaining({ topic_id: 7, session: undefined }));
    });
    expect(getBills).not.toHaveBeenCalledWith(expect.objectContaining({ topic_id: 7, session: 120 }));
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

  it("debounces text search requests", async () => {
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
      expect(screen.getByLabelText("Status (contains)")).toHaveValue("Filed");
      expect(screen.getByLabelText("Sponsor")).toHaveValue("Jones");
      expect(screen.getByLabelText("Topic contains (fuzzy)")).toHaveValue("energy");
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
