import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TopicsPage from "@/app/topics/page";
import {
  getTopics,
  getTrackedTopics,
  getSession,
  trackTopic,
  untrackTopic,
} from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getTopics: vi.fn(),
  getTrackedTopics: vi.fn(),
  getSession: vi.fn(),
  trackTopic: vi.fn(),
  untrackTopic: vi.fn(),
}));

describe("TopicsPage", () => {
  beforeEach(() => {
    vi.mocked(getSession).mockResolvedValue({
      authenticated: true,
      user: { email: "person@example.com" },
    });
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

  it("shows an error when a topic tracking request fails", async () => {
    const user = userEvent.setup();
    vi.mocked(trackTopic).mockRejectedValueOnce(
      new Error("Tracking service unavailable"),
    );
    render(<TopicsPage />);

    await screen.findByRole("button", { name: "Following" });
    await user.click(screen.getByRole("button", { name: "Follow" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Tracking service unavailable",
    );
    expect(screen.getByRole("button", { name: "Follow" })).toBeEnabled();
  });

  it("keeps topics visible when refresh fails and retries only the topic list", async () => {
    const user = userEvent.setup();
    render(<TopicsPage />);

    expect(await screen.findByRole("link", { name: "Health" })).toBeVisible();
    vi.mocked(getTopics).mockRejectedValueOnce(new Error("Topic service unavailable"));
    await user.click(screen.getByRole("button", { name: "Refresh topics" }));

    expect(await screen.findByText("Could not load topics. Try again.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Health" })).toBeVisible();
    expect(getTrackedTopics).toHaveBeenCalledTimes(1);

    vi.mocked(getTopics).mockResolvedValueOnce([
      { id: 9, name: "Housing", slug: "housing" },
    ]);
    await user.click(screen.getByRole("button", { name: "Retry topics" }));

    expect(await screen.findByRole("link", { name: "Housing" })).toBeVisible();
    expect(screen.queryByText("Could not load topics. Try again.")).not.toBeInTheDocument();
  });

  it("keeps followed topics when refresh fails and retries only tracking state", async () => {
    const user = userEvent.setup();
    render(<TopicsPage />);

    await screen.findByRole("button", { name: "Following" });
    vi.mocked(getTrackedTopics).mockRejectedValueOnce(
      new Error("Tracked topic service unavailable"),
    );
    await user.click(
      screen.getByRole("button", { name: "Refresh followed topics" }),
    );

    expect(await screen.findByText("Could not load followed topics. Try again.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Following" })).toBeVisible();
    expect(getTopics).toHaveBeenCalledTimes(1);

    vi.mocked(getTrackedTopics).mockResolvedValueOnce([
      {
        id: 2,
        topic: { id: 8, name: "Education", slug: "education" },
        created_at: "2026-08-20T00:00:00Z",
      },
    ]);
    await user.click(
      screen.getByRole("button", { name: "Retry followed topics" }),
    );

    expect(await screen.findByRole("button", { name: "Following" })).toBeVisible();
    expect(screen.queryByText("Could not load followed topics. Try again.")).not.toBeInTheDocument();
  });
});
