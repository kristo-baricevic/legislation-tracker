import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillDetailPage from "@/app/bills/[id]/page";
import {
  getBill,
  getContracts,
  getVote,
  getVotes,
  getStoredAccessToken,
  type VoteDetailItem,
} from "@/lib/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "10" }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  getBill: vi.fn(),
  getContracts: vi.fn(),
  getVote: vi.fn(),
  getVotes: vi.fn(),
  getApiBase: () => "http://localhost:8000",
  getStoredAccessToken: vi.fn(),
  getMyTracking: vi.fn(),
  trackBill: vi.fn(),
  untrackBill: vi.fn(),
}));

describe("BillDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getStoredAccessToken).mockReturnValue(null);
    vi.mocked(getBill).mockResolvedValue({
      id: 10,
      jurisdiction: "federal",
      session: 119,
      bill_number: "HR 10",
      title: "A public bill",
      status: "Introduced",
      sponsor_name: null,
      introduced_at: null,
      last_action_at: null,
      topics: [],
      summary: null,
      processing_status: "complete",
      sponsor: null,
      source_api_id: null,
      documents: [
        {
          id: 9,
          version_label: "Introduced",
          is_active_version: true,
          content_type: "application/pdf",
          file_size_bytes: 123,
          source_url: null,
          downloaded_at: null,
          download_url: "/api/documents/9/download/",
          text_url: "/api/documents/9/text/",
        },
      ],
      congress_gov_url: null,
      latest_contract: null,
      created_at: "2026-08-19T00:00:00Z",
      updated_at: "2026-08-19T00:00:00Z",
    });
    vi.mocked(getContracts).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 4,
          schema_version: "1.1",
          contract_json: { plain_summary: "Contract history summary" },
          contract_hash: "hash",
          computed_at: "2026-08-19T00:00:00Z",
          document: null,
          document_version_label: null,
          evidence_spans: [],
        },
      ],
    });
    vi.mocked(getVotes).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 33,
          bill: 10,
          chamber: "house",
          session_number: 1,
          roll_number: 17,
          vote_date: "2026-08-19T00:00:00Z",
          result: "Passed",
          yeas: 220,
          nays: 210,
        },
      ],
    });
    vi.mocked(getVote).mockResolvedValue({
      id: 33,
      bill: 10,
      chamber: "house",
      session_number: 1,
      roll_number: 17,
      vote_date: "2026-08-19T00:00:00Z",
      result: "Passed",
      yeas: 220,
      nays: 210,
      records: [
        {
          representative: {
            id: 1,
            bioguide_id: "V000001",
            name: "Voting Representative",
            chamber: "house",
            party: "Independent",
            state: "NY",
            district: null,
            first_name: "Voting",
            last_name: "Representative",
            official_website_url: null,
            image_url: null,
            is_current: true,
          },
          position: "yes",
        },
      ],
    });
  });

  it("keeps a public bill readable while showing an unauthenticated tracking prompt", async () => {
    const user = userEvent.setup();
    render(<BillDetailPage />);

    expect(await screen.findByRole("heading", { name: "HR 10 (119)" })).toBeVisible();
    expect(screen.getByText("A public bill")).toBeVisible();
    expect(screen.getByRole("link", { name: "Log in to track this bill" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/documents/9/download/",
    );
    expect(screen.getByRole("link", { name: "Read text" })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/documents/9/text/",
    );
    expect(await screen.findByRole("heading", { name: "Contract history" })).toBeVisible();
    expect(screen.getByText("Contract history summary")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Roll-call votes" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "View member positions" }));
    await waitFor(() => expect(getVote).toHaveBeenCalledWith(33));
    expect(await screen.findByText("Voting Representative")).toBeVisible();
  });

  it("labels a legacy vote whose session is not known", async () => {
    vi.mocked(getVotes).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 33,
          bill: 10,
          chamber: "house",
          session_number: null,
          roll_number: 17,
          vote_date: "2026-01-02T00:00:00Z",
          result: "Passed",
          yeas: 220,
          nays: 210,
        },
      ],
    });

    render(<BillDetailPage />);

    expect(await screen.findByText(/house session unknown roll call 17/)).toBeVisible();
  });

  it("shows a retryable error and clears stale positions when vote detail loading fails", async () => {
    const user = userEvent.setup();
    render(<BillDetailPage />);

    const viewPositions = await screen.findByRole("button", {
      name: "View member positions",
    });
    await user.click(viewPositions);
    expect(await screen.findByText("Voting Representative")).toBeVisible();

    vi.mocked(getVote).mockRejectedValueOnce(new Error("Vote detail unavailable"));
    await user.click(viewPositions);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load member positions. Try again.",
    );
    expect(screen.queryByText("Voting Representative")).not.toBeInTheDocument();
    expect(viewPositions).toBeEnabled();
  });

  it("ignores an older vote detail response that resolves after the active selection", async () => {
    const user = userEvent.setup();
    const firstVote = {
      id: 33,
      bill: 10,
      chamber: "house",
      session_number: 1,
      roll_number: 17,
      vote_date: "2026-08-19T00:00:00Z",
      result: "Passed",
      yeas: 220,
      nays: 210,
      records: [
        {
          representative: {
            id: 1,
            bioguide_id: "V000001",
            name: "First Vote Representative",
            chamber: "house",
            party: "Independent",
            state: "NY",
            district: null,
            first_name: "First",
            last_name: "Representative",
            official_website_url: null,
            image_url: null,
            is_current: true,
          },
          position: "yes",
        },
      ],
    } satisfies VoteDetailItem;
    const secondVote = {
      ...firstVote,
      id: 34,
      roll_number: 18,
      records: [
        {
          representative: {
            ...firstVote.records[0].representative,
            id: 2,
            bioguide_id: "V000002",
            name: "Second Vote Representative",
            first_name: "Second",
          },
          position: "no",
        },
      ],
    } satisfies VoteDetailItem;
    let resolveFirst: (vote: VoteDetailItem) => void = () => undefined;
    let resolveSecond: (vote: VoteDetailItem) => void = () => undefined;
    const firstRequest = new Promise<VoteDetailItem>((resolve) => {
      resolveFirst = resolve;
    });
    const secondRequest = new Promise<VoteDetailItem>((resolve) => {
      resolveSecond = resolve;
    });

    vi.mocked(getVotes).mockResolvedValue({
      count: 2,
      next: null,
      previous: null,
      results: [firstVote, secondVote],
    });
    vi.mocked(getVote)
      .mockReturnValueOnce(firstRequest)
      .mockReturnValueOnce(secondRequest);
    render(<BillDetailPage />);

    const buttons = await screen.findAllByRole("button", {
      name: "View member positions",
    });
    await user.click(buttons[0]);
    await user.click(buttons[1]);
    resolveSecond(secondVote);
    expect(await screen.findByText("Second Vote Representative")).toBeVisible();

    await act(async () => {
      resolveFirst(firstVote);
      await firstRequest;
    });
    expect(screen.queryByText("First Vote Representative")).not.toBeInTheDocument();
    expect(screen.getByText("Second Vote Representative")).toBeVisible();
  });

  it("clears selected member positions when the vote history page changes", async () => {
    const user = userEvent.setup();
    vi.mocked(getVotes)
      .mockResolvedValueOnce({
        count: 21,
        next: "http://localhost:8000/api/votes/?bill=10&page=2",
        previous: null,
        results: [
          {
            id: 33,
            bill: 10,
            chamber: "house",
            session_number: 1,
            roll_number: 17,
            vote_date: "2026-08-19T00:00:00Z",
            result: "Passed",
            yeas: 220,
            nays: 210,
          },
        ],
      })
      .mockResolvedValueOnce({
        count: 21,
        next: null,
        previous: "http://localhost:8000/api/votes/?bill=10&page=1",
        results: [
          {
            id: 32,
            bill: 10,
            chamber: "house",
            session_number: 1,
            roll_number: 16,
            vote_date: "2026-08-18T00:00:00Z",
            result: "Failed",
            yeas: 210,
            nays: 220,
          },
        ],
      });
    render(<BillDetailPage />);

    await user.click(
      await screen.findByRole("button", { name: "View member positions" }),
    );
    expect(await screen.findByText("Voting Representative")).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: "Next vote history page" }),
    );
    expect(await screen.findByText(/roll call 16: Failed/)).toBeVisible();
    expect(screen.queryByText("Voting Representative")).not.toBeInTheDocument();
  });

  it("pages through contract and vote histories beyond the first result page", async () => {
    const user = userEvent.setup();
    vi.mocked(getContracts)
      .mockResolvedValueOnce({
        count: 21,
        next: "http://localhost:8000/api/contracts/?bill=10&page=2",
        previous: null,
        results: [
          {
            id: 4,
            schema_version: "1.1",
            contract_json: { plain_summary: "Newest contract revision" },
            contract_hash: "hash",
            computed_at: "2026-08-19T00:00:00Z",
            document: null,
            document_version_label: null,
            evidence_spans: [],
          },
        ],
      })
      .mockResolvedValueOnce({
        count: 21,
        next: null,
        previous: "http://localhost:8000/api/contracts/?bill=10&page=1",
        results: [
          {
            id: 3,
            schema_version: "1.0",
            contract_json: { plain_summary: "Older contract revision" },
            contract_hash: "older-hash",
            computed_at: "2026-08-18T00:00:00Z",
            document: null,
            document_version_label: null,
            evidence_spans: [],
          },
        ],
      });
    vi.mocked(getVotes)
      .mockResolvedValueOnce({
        count: 21,
        next: "http://localhost:8000/api/votes/?bill=10&page=2",
        previous: null,
        results: [
          {
            id: 33,
            bill: 10,
            chamber: "house",
            session_number: 1,
            roll_number: 17,
            vote_date: "2026-08-19T00:00:00Z",
            result: "Passed",
            yeas: 220,
            nays: 210,
          },
        ],
      })
      .mockResolvedValueOnce({
        count: 21,
        next: null,
        previous: "http://localhost:8000/api/votes/?bill=10&page=1",
        results: [
          {
            id: 32,
            bill: 10,
            chamber: "house",
            session_number: 1,
            roll_number: 16,
            vote_date: "2026-08-18T00:00:00Z",
            result: "Failed",
            yeas: 210,
            nays: 220,
          },
        ],
      });

    render(<BillDetailPage />);

    expect(await screen.findByText("Newest contract revision")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "Next contract history page" }),
    );
    expect(await screen.findByText("Older contract revision")).toBeVisible();
    expect(getContracts).toHaveBeenLastCalledWith(10, { page: 2 });

    await user.click(
      screen.getByRole("button", { name: "Next vote history page" }),
    );
    expect(await screen.findByText(/roll call 16: Failed/)).toBeVisible();
    expect(getVotes).toHaveBeenLastCalledWith(10, { page: 2 });
  });
});
