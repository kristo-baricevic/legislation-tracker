import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillsPage from "@/app/bills/page";
import { getBills } from "@/lib/api";

const searchState = vi.hoisted(() => ({ query: "topic_id=7" }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(searchState.query),
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  getBillFilterOptions: vi.fn().mockResolvedValue({
    jurisdictions: ["federal"],
    current_congress: 120,
  }),
  getBills: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
  getMyTracking: vi.fn(),
  getSession: vi.fn().mockResolvedValue(null),
  getTopics: vi.fn().mockResolvedValue([{ id: 7, name: "Health", slug: "health" }]),
  parseTopicIdFromSearchParam: (value: string | null) => {
    if (!value || !/^\d+$/.test(value)) return undefined;
    const parsed = Number(value);
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
  },
  trackTopic: vi.fn(),
  untrackTopic: vi.fn(),
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
    vi.mocked(api.getTopics).mockResolvedValue([
      { id: 7, name: "Health", slug: "health" },
    ]);
  });

  it("passes a topic id from the URL into the bill query", async () => {
    render(<BillsPage />);

    await waitFor(() => {
      expect(getBills).toHaveBeenCalledWith(expect.objectContaining({ topic_id: 7 }));
    });
  });

  it("initializes the Congress filter from API metadata", async () => {
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
});
