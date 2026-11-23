import React from "react";
import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import RepresentativeAvatarBadge from "@/app/components/RepresentativeAvatarBadge";
import { dashboardSession } from "@/lib/dashboard-cache";
import { announceTrackingChange, endSessionTransition } from "@/lib/personalized-scope";
import { getSession, getRepresentative } from "@/lib/api";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), getSession: vi.fn(), getRepresentative: vi.fn() }));

it("following a bill retains the senator image node and cached portrait through session revalidation", async () => {
  endSessionTransition("reader@example.test");
  const session = { authenticated: true as const, user: { email: "reader@example.test", is_superuser: false }, dashboard_revision: "before", tracking_revision: "before", research_revision: "unchanged", current_congress: 119 };
  vi.mocked(getSession).mockResolvedValue(session);
  vi.mocked(getRepresentative).mockResolvedValue({ id: 410, name: "Katie Britt", bioguide_id: "B001319", image_url: "https://www.congress.gov/img/member/b001319_200.jpg" } as Awaited<ReturnType<typeof getRepresentative>>);
  await dashboardSession();
  render(<RepresentativeAvatarBadge id={410} name="Katie Britt" notes={[]} />);
  const image = await screen.findByRole("img", { name: "Katie Britt" });
  vi.mocked(getSession).mockResolvedValue({ ...session, dashboard_revision: "after", tracking_revision: "after" });
  await act(async () => { announceTrackingChange(); await dashboardSession(); });
  expect(await screen.findByRole("img", { name: "Katie Britt" })).toBe(image);
  expect(image).toHaveAttribute("src", "https://www.congress.gov/img/member/b001319_200.jpg");
  expect(getRepresentative).toHaveBeenCalledTimes(1);
  // Real research may replace a portrait, but must not blank it while loading.
  let finish!: (value: Awaited<ReturnType<typeof getRepresentative>>) => void;
  vi.mocked(getRepresentative).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  vi.mocked(getSession).mockResolvedValue({ ...session, dashboard_revision: "after", research_revision: "new-photo" });
  await act(async () => { await dashboardSession(); });
  expect(screen.getByRole("img", { name: "Katie Britt" })).toBe(image);
  await act(async () => finish({ id: 410, bioguide_id: "B001319", image_url: "https://www.congress.gov/new-photo.jpg" } as Awaited<ReturnType<typeof getRepresentative>>));
  expect(screen.getByRole("img", { name: "Katie Britt" })).toBe(image);
  expect(image).toHaveAttribute("src", "https://www.congress.gov/new-photo.jpg");
});
