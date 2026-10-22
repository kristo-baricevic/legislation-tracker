import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepresentativesPage from "@/app/representatives/page";
import userEvent from "@testing-library/user-event";
import { getBillFilterOptions, getRepresentatives, getSession } from "@/lib/api";

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
  it("searches the directory by name and resets pagination", async () => {
    vi.mocked(getRepresentatives).mockImplementation(async (params) => ({
      count: params?.search ? 0 : 21, next: params?.search ? null : "?page=2", previous: null,
      results: Array.from({ length: params?.search ? 0 : 20 }, (_, i) => ({ id: i + 1, name: "Member " + i, bioguide_id: "A000001", chamber: "house", party: "D", state: "NY", district: "1", first_name: "Member", last_name: String(i), image_url: null, official_website_url: null, is_current: true })),
    }));
    render(<RepresentativesPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Next" }));
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
    expect(screen.getByRole("link", { name: "Compare two representatives" })).toBeVisible();
  });
});
