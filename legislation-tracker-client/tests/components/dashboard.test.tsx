import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Dashboard from "@/app/components/Dashboard";
import {
  getBillFilterOptions,
  getMyTracking,
  getSession,
  getTrackingFeed,
} from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getBillFilterOptions: vi.fn(),
  getSession: vi.fn().mockResolvedValue({
    authenticated: true,
    user: { email: "staff@example.com" },
  }),
  getMyTracking: vi.fn().mockResolvedValue({
    bills: [],
    topics: [],
    legislators: [],
    is_staff: true,
  }),
  getTrackingFeed: vi.fn().mockResolvedValue({ entries: [] }),
  triggerDocumentBackfill: vi.fn(),
  triggerPollCongress: vi.fn(),
}));

describe("Dashboard Congress defaults", () => {
  beforeEach(() => {
    vi.mocked(getSession).mockResolvedValue({
      authenticated: true,
      user: { email: "staff@example.com" },
    });
    vi.mocked(getMyTracking).mockResolvedValue({
      bills: [],
      topics: [],
      legislators: [],
      is_staff: true,
    });
    vi.mocked(getTrackingFeed).mockResolvedValue({ entries: [] });
    vi.mocked(getBillFilterOptions).mockResolvedValue({
      jurisdictions: ["federal"],
      current_congress: 120,
    });
  });

  it("initializes both staff workflows from API Congress metadata", async () => {
    render(<Dashboard />);

    expect(await screen.findByLabelText("Congress")).toHaveValue(120);
    expect(screen.getByLabelText("Document session")).toHaveValue(120);
    expect(getBillFilterOptions).toHaveBeenCalledTimes(1);
  });
});
