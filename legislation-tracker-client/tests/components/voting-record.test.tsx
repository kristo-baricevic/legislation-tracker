import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VotingRecord } from "@/app/bills/[id]/voting-record";
import type { VoteDetailItem, VoteListItem } from "@/lib/api";

const votes: VoteListItem[] = [
  {
    id: 8,
    bill: 10,
    chamber: "House",
    session_number: 1,
    roll_number: 8,
    vote_date: "2026-08-20T00:00:00Z",
    result: "Passed",
    yeas: 3,
    nays: 1,
    question: "On passage",
    source_url: "https://clerk.house.gov/vote/8",
  },
  {
    id: 7,
    bill: 10,
    chamber: "House",
    session_number: 1,
    roll_number: 7,
    vote_date: "2026-08-19T00:00:00Z",
    result: "Agreed to",
    yeas: 1,
    nays: 0,
  },
];

const selectedVote: VoteDetailItem = {
  ...votes[0],
  records: [
    {
      representative: {
        id: 1,
        bioguide_id: "G000001",
        name: "Representative Garcia",
        chamber: "House",
        party: "Democratic",
        state: "CA",
        district: "12",
        first_name: "Garcia",
        last_name: "Representative",
        official_website_url: null,
        image_url: null,
        is_current: true,
      },
      position: "yes",
    },
    {
      representative: {
        id: 2,
        bioguide_id: "A000001",
        name: "Representative Adams",
        chamber: "House",
        party: "Republican",
        state: "AL",
        district: "2",
        first_name: "Adams",
        last_name: "Representative",
        official_website_url: null,
        image_url: null,
        is_current: true,
      },
      position: "yes",
    },
    {
      representative: {
        id: 3,
        bioguide_id: "B000001",
        name: "Representative Baker",
        chamber: "House",
        party: "Independent",
        state: "NY",
        district: null,
        first_name: "Baker",
        last_name: "Representative",
        official_website_url: null,
        image_url: null,
        is_current: true,
      },
      position: "no",
    },
    {
      representative: {
        id: 4,
        bioguide_id: "C000001",
        name: "Representative Chen",
        chamber: "House",
        party: "Democratic",
        state: "WA",
        district: "7",
        first_name: "Chen",
        last_name: "Representative",
        official_website_url: null,
        image_url: null,
        is_current: true,
      },
      position: "not voting",
    },
    {
      representative: {
        id: 5,
        bioguide_id: "D000001",
        name: "Representative Diaz",
        chamber: "House",
        party: "Democratic",
        state: "TX",
        district: "9",
        first_name: "Diaz",
        last_name: "Representative",
        official_website_url: null,
        image_url: null,
        is_current: true,
      },
      position: "present",
    },
  ],
};

describe("VotingRecord", () => {
  it("groups every returned member, sorts the vote list newest first, and retains the source", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <VotingRecord
        votes={[votes[1], votes[0]]}
        selectedVote={selectedVote}
        loadingVoteId={null}
        error={null}
        onSelect={onSelect}
        page={1}
        hasNext={false}
        onPrevious={vi.fn()}
        onNext={vi.fn()}
      />,
    );

    expect(screen.getAllByText(/roll call 8: Passed/)[0].compareDocumentPosition(
      screen.getAllByText(/roll call 7: Agreed to/)[0],
    ) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(screen.getByRole("link", { name: "Official vote source" })).toHaveAttribute(
      "href",
      "https://clerk.house.gov/vote/8",
    );
    expect(screen.getByRole("heading", { name: "Yes — 2" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "No — 1" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Present — 1" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Not voting — 1" })).toBeVisible();
    expect(screen.getAllByText(/Representative (Adams|Garcia|Baker|Chen|Diaz)/)).toHaveLength(5);
    expect(screen.getAllByText("Representative Adams")[0].compareDocumentPosition(
      screen.getAllByText("Representative Garcia")[0],
    ) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(screen.getByText(/Reported yes total 3 differs from 2 returned member records/)).toBeVisible();

    await user.type(screen.getByRole("searchbox", { name: "Search members" }), "Garcia");
    expect(screen.getByText("Representative Garcia")).toBeVisible();
    expect(screen.queryByText("Representative Adams")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "Party" }), "Democratic");
    await user.selectOptions(screen.getByRole("combobox", { name: "State" }), "CA");
    expect(screen.getByText("Representative Garcia")).toBeVisible();
    expect(screen.queryByText("Representative Chen")).not.toBeInTheDocument();
  });

  it("keeps pagination, errors, and retry ownership in the parent", async () => {
    const onSelect = vi.fn();
    const onPrevious = vi.fn();
    const onNext = vi.fn();
    render(
      <VotingRecord
        votes={votes}
        selectedVote={null}
        loadingVoteId={7}
        error="Could not load member positions. Try again."
        onSelect={onSelect}
        page={2}
        hasNext
        onPrevious={onPrevious}
        onNext={onNext}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load member positions. Try again.");
    expect(screen.getByRole("button", { name: "Loading voting record..." })).toBeDisabled();
    await userEvent.setup().click(screen.getByRole("button", { name: "Previous vote history page" }));
    expect(onPrevious).toHaveBeenCalledOnce();
    await userEvent.setup().click(screen.getByRole("button", { name: "Next vote history page" }));
    expect(onNext).toHaveBeenCalledOnce();
  });
});
