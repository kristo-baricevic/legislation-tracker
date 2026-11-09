import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import BillModalDetails from "@/app/components/BillModalDetails";
import { getReaderItems, getVotes, getVote } from "@/lib/api";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), getReaderItems: vi.fn(), getVotes: vi.fn(), getVote: vi.fn() }));
const line = { id: "line-1", source_id: "source-1", section_id: "sec-1", section_path: [], kind: "requirement" as const, display_text: "Schools must check applications for identity fraud.", actor: null, action: null, effect: null, exact_financial_count: 0, exact_financial_preview: [], timeline_count: 0, timeline_preview: [], definition_count: 0 };
beforeEach(() => {
  vi.mocked(getVotes).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
  vi.mocked(getReaderItems).mockResolvedValue({ count: 1, next: null, previous: null, results: [line], section_supplements: [] });
});
it("loads explanations with pagination and retries a failed page", async () => {
  vi.mocked(getReaderItems).mockResolvedValueOnce({ count: 7, next: "page2", previous: null, results: [line], section_supplements: [] }).mockRejectedValueOnce(new Error("offline"));
  render(<BillModalDetails billId={1876} contractId={7} />);
  expect(await screen.findByText(line.display_text)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the breakdown");
  await userEvent.click(screen.getByRole("button", { name: "Retry breakdown" }));
  expect(await screen.findByText(line.display_text)).toBeVisible();
  expect(screen.getByText("Page 2")).toBeVisible();
});
it("shows vote history and voter avatars instead of printed member names", async () => {
  const vote = { id: 3, bill: 1876, congress: 119, chamber: "house", session_number: 2, roll_number: 8, vote_date: "2026-11-01", result: "Passed", yeas: 1, nays: 0, question: "On passage" };
  vi.mocked(getVotes).mockResolvedValue({ count: 1, next: null, previous: null, results: [vote] });
  vi.mocked(getVote).mockResolvedValue({ ...vote, records: [{ position: "yes", representative: { id: 121, name: "Burgess Owens", bioguide_id: "O000086", party: "R", chamber: "house", state: "UT", district: "4", image_url: null, first_name: "Burgess", last_name: "Owens", official_website_url: null, is_current: true } }] });
  render(<BillModalDetails billId={1876} />);
  await userEvent.click(await screen.findByRole("button", { name: "View voting record" }));
  expect(await screen.findByRole("link", { name: "Burgess Owens" })).toBeVisible();
  expect(await screen.findByRole("img", { name: "Burgess Owens" })).toHaveAttribute("src", "https://www.congress.gov/img/member/o000086_200.jpg");
  expect(screen.queryByText("Burgess Owens")).not.toBeInTheDocument();
});
