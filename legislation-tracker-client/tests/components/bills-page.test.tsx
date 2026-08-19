import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillsPage from "@/app/bills/page";
import { getBills } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("topic_id=7"),
}));

vi.mock("@/lib/api", () => ({
  getBillFilterOptions: vi.fn().mockResolvedValue({ jurisdictions: ["federal"] }),
  getBills: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
  getMyTracking: vi.fn(),
  getStoredAccessToken: vi.fn().mockReturnValue(null),
  getTopics: vi.fn().mockResolvedValue([{ id: 7, name: "Health", slug: "health" }]),
  parseTopicIdFromSearchParam: (value: string | null) => value === "7" ? 7 : undefined,
  trackTopic: vi.fn(),
  untrackTopic: vi.fn(),
}));

describe("BillsPage", () => {
  beforeEach(async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.getBillFilterOptions).mockResolvedValue({ jurisdictions: ["federal"] });
    vi.mocked(api.getBills).mockResolvedValue({
      count: 0,
      next: null,
      previous: null,
      results: [],
    });
    vi.mocked(api.getStoredAccessToken).mockReturnValue(null);
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
});
