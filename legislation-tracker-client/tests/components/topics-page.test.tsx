import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TopicsPage from "@/app/topics/page";
import {
  getTopics,
  getTrackedTopics,
  isLoggedIn,
  trackTopic,
  untrackTopic,
} from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getTopics: vi.fn(),
  getTrackedTopics: vi.fn(),
  isLoggedIn: vi.fn(),
  trackTopic: vi.fn(),
  untrackTopic: vi.fn(),
}));

describe("TopicsPage", () => {
  beforeEach(() => {
    vi.mocked(isLoggedIn).mockReturnValue(true);
    vi.mocked(getTopics).mockResolvedValue([
      { id: 7, name: "Health", slug: "health" },
      { id: 8, name: "Education", slug: "education" },
    ]);
    vi.mocked(getTrackedTopics).mockResolvedValue([
      {
        id: 1,
        topic: { id: 7, name: "Health", slug: "health" },
        created_at: "2026-08-19T00:00:00Z",
      },
    ]);
    vi.mocked(trackTopic).mockResolvedValue({
      id: 2,
      topic: { id: 8, name: "Education", slug: "education" },
      created_at: "2026-08-19T00:00:00Z",
    });
    vi.mocked(untrackTopic).mockResolvedValue();
  });

  it("updates the followed state after tracking an untracked topic", async () => {
    const user = userEvent.setup();
    render(<TopicsPage />);

    await screen.findByRole("button", { name: "Following" });
    await user.click(screen.getByRole("button", { name: "Follow" }));

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Following" })).toHaveLength(2);
    });
    expect(trackTopic).toHaveBeenCalledWith(8);
  });
});
