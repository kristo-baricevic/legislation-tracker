import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import BillCard from "@/app/components/BillCard";
import type { BillListItem } from "@/lib/api";

const bill: BillListItem = {
  id: 1, bill_number: "HR 1", session: 119, jurisdiction: "federal",
  title: "A reader-friendly bill", status: "Passed House", sponsor_id: null,
  sponsor_name: null, sponsor_bioguide_id: null, introduced_at: "2025-01-01",
  last_action_at: "2025-02-01", topics: [
    { topic_id: 1, name: "Health", slug: "health", confidence_score: 1 },
    { topic_id: 2, name: "Education", slug: "education", confidence_score: 1 },
  ],
};

it("shows the preferred topic, congress and accessible stage without breaking card actions", async () => {
  const open = vi.fn(), follow = vi.fn();
  render(<BillCard bill={bill} accentTopicId={2} onOpen={open} footer={<button onClick={follow}>Follow</button>} />);
  expect(screen.getByText("119th Congress")).toBeInTheDocument();
  expect(screen.getByText("Education")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Step 3 of 5: Passed the House" })).toBeInTheDocument();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: bill.title }));
  await user.click(screen.getByRole("button", { name: "Follow" }));
  expect(open).toHaveBeenCalledOnce();
  expect(follow).toHaveBeenCalledOnce();
});

it("retains unrecognized action text instead of inventing progress", () => {
  render(<BillCard bill={{ ...bill, status: "Motion withdrawn" }} onOpen={() => {}} footer={null} />);
  expect(screen.getByText("Motion withdrawn")).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
