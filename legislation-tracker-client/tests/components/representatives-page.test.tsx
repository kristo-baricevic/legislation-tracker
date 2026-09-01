import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepresentativesPage from "@/app/representatives/page";
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
