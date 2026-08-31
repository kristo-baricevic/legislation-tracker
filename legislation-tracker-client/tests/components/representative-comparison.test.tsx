import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepresentativeComparePage from "@/app/representatives/compare/page";
import { compareRepresentatives, getRepresentatives } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("ids=8,9&congress=119"),
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a>,
}));
vi.mock("@/lib/api", () => ({
  getRepresentatives: vi.fn().mockResolvedValue({ count: 2, next: null, previous: null, results: [{ id: 8, name: "First", state: "NY" }, { id: 9, name: "Second", state: "NY" }] }),
  compareRepresentatives: vi.fn().mockResolvedValue({ left_representative_id: 8, right_representative_id: 9, congress: 119, shared_vote_count: 2, agree_count: 1, disagreement_count: 1, excluded_shared_vote_count: 1, agreement_rate: 0.5, coverage_complete: false, reason: null, shared_votes: [{ vote_id: 7, bill_id: 44, vote_date: "2026-01-01T00:00:00Z", question: "On passage", result: "Passed", left_position: "yes", right_position: "no" }] }),
}));

describe("RepresentativeComparePage", () => {
  beforeEach(() => {
    vi.mocked(getRepresentatives).mockResolvedValue({ count: 2, next: null, previous: null, results: [{ id: 8, bioguide_id: "A", name: "First", chamber: "house", party: "", state: "NY", district: null, first_name: "", last_name: "", official_website_url: null, image_url: null, is_current: true }, { id: 9, bioguide_id: "B", name: "Second", chamber: "house", party: "", state: "NY", district: null, first_name: "", last_name: "", official_website_url: null, image_url: null, is_current: true }] });
    vi.mocked(compareRepresentatives).mockResolvedValue({ left_representative_id: 8, right_representative_id: 9, congress: 119, shared_vote_count: 2, agree_count: 1, disagreement_count: 1, excluded_shared_vote_count: 1, agreement_rate: 0.5, coverage_complete: false, reason: null, shared_votes: [{ vote_id: 7, bill_id: 44, vote_date: "2026-01-01T00:00:00Z", question: "On passage", result: "Passed", left_position: "yes", right_position: "no" }] });
  });

  it("renders a linkable two-member comparison with shared-vote evidence", async () => {
    render(<RepresentativeComparePage />);
    expect(await screen.findByText(/1 agreements and 1 disagreements/)).toBeVisible();
    expect(screen.getByText("On passage")).toBeVisible();
    expect(screen.getByRole("link", { name: "View bill" })).toHaveAttribute("href", "/bills/44");
  });
});
