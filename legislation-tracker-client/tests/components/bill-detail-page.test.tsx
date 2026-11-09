import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillDetailPage from "@/app/bills/[id]/page";
import {
  getBill,
  getBillChanges,
  compareBillContracts,
  getContracts,
  getVote,
  getVotes,
  getSession,
  type VoteDetailItem,
} from "@/lib/api";

const routeState = vi.hoisted(() => ({ id: "10" }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: routeState.id }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  getBill: vi.fn(),
  getBillChanges: vi.fn(),
  acknowledgeBillChanges: vi.fn(),
  compareBillContracts: vi.fn(),
  compareBillDocuments: vi.fn(),
  getContracts: vi.fn(),
  getContractEvidence: vi.fn(),
  getDefinitionItems: vi.fn(),
  getFinancialItems: vi.fn(),
  getOfficialSummary: vi.fn(),
  getReaderItems: vi.fn(),
  getTimelineItems: vi.fn(),
  getVote: vi.fn(),
  getVotes: vi.fn(),
  getApiBase: () => "http://localhost:8000",
  getSession: vi.fn(),
  getMyTracking: vi.fn(),
  trackBill: vi.fn(),
  untrackBill: vi.fn(),
}));

describe("BillDetailPage", () => {
  it("keeps the existing summary through a progress-check failure and refreshes on the next tick", async () => {
    const value = await getBill(10);
    const initial = { ...value, processing_status: "processing", summary_preview: "Initial sourced summary." };
    vi.mocked(getBill).mockResolvedValue(initial);
    vi.useFakeTimers();
    let view: ReturnType<typeof render> | undefined;
    try {
      await act(async () => { view = render(<BillDetailPage />); });
      vi.mocked(getBill).mockRejectedValueOnce(new Error("temporarily unavailable"));
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(screen.getByText("Initial sourced summary.")).toBeVisible();
      expect(screen.getByText(/Could not check progress/)).toBeVisible();
      const completed = { ...value, processing_status: "complete", summary_preview: "Completed sourced summary." };
      vi.mocked(getBill).mockResolvedValue(completed);
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(screen.getByText("Completed sourced summary.")).toBeVisible();
      const unexpected = { ...value, summary_preview: "Unexpected polling after completion." };
      vi.mocked(getBill).mockResolvedValue(unexpected);
      await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
      expect(screen.getByText("Completed sourced summary.")).toBeVisible();
    } finally { view?.unmount(); vi.useRealTimers(); }
  });
  it("refreshes an unfinished bill into its completed summary without navigation", async () => {
    const value = await getBill(10);
    vi.mocked(getBill).mockResolvedValue({ ...value, processing_status: "processing" });
    let view: ReturnType<typeof render>;
    // Wait for the initial request and the resulting polling effect to commit
    // before simulating a return to the window.
    await act(async () => { view = render(<BillDetailPage />); });
    await screen.findByRole("heading", { name: "HR 10 · Congress 119" });
    expect(screen.getByText(/Preparing this bill/)).toBeVisible();
    const completed = { ...value, processing_status: "complete", summary_preview: "This bill protects children in foster care." };
    vi.mocked(getBill).mockResolvedValue(completed);
    try {
      // Returning to an unfinished bill should also refresh immediately.
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      expect(screen.getByText("This bill protects children in foster care.")).toBeVisible();
      expect(screen.queryByText(/Preparing this bill/)).not.toBeInTheDocument();
    } finally { view!.unmount(); }
  });
  it.each([
    { jurisdiction: "federal", session: 121, label: "Congress 121" },
    { jurisdiction: "california", session: 2025, label: "Session 2025" },
  ])("labels the actual legislative scope without invalid ordinals: $label", async ({ jurisdiction, session, label }) => {
    const value = await getBill(10);
    vi.mocked(getBill).mockResolvedValue({ ...value, jurisdiction, session });
    render(<BillDetailPage />);
    expect(await screen.findByRole("heading", { name: `HR 10 · ${label}` })).toBeVisible();
  });
  it("keeps the bill source destinations together in the page header", async () => {
    const value = await getBill(10);
    vi.mocked(getBill).mockResolvedValue({ ...value, congress_gov_url: "https://www.congress.gov/bill/119th-congress/house-bill/10" });
    render(<BillDetailPage />);
    const links = await screen.findByRole("navigation", { name: "Bill source links" });
    expect(within(links).getByRole("link", { name: "Congress.gov" })).toHaveAttribute("href", "https://www.congress.gov/bill/119th-congress/house-bill/10");
    expect(within(links).getByRole("link", { name: "Full bill text" })).toHaveAttribute("href", "/documents/9");
    expect(links.closest("header")).toContainElement(screen.getByRole("heading", { name: "HR 10 · Congress 119" }));
    await userEvent.click(screen.getByRole("tab", { name: "Versions" }));
    const versions = screen.getByRole("tabpanel", { name: "Versions" });
    expect(within(versions).getByRole("heading", { name: "Bill versions" })).toBeVisible();
    expect(within(versions).getByRole("link", { name: "Read text" })).toHaveAttribute("href", "/documents/9");
    expect(screen.getAllByRole("link").filter(link => link.getAttribute("href") === "https://www.congress.gov/bill/119th-congress/house-bill/10")).toHaveLength(1);
  });

  it("does not offer unavailable bill sources", async () => {
    const value = await getBill(10);
    vi.mocked(getBill).mockResolvedValue({ ...value, documents: [] });
    render(<BillDetailPage />);
    await screen.findByRole("heading", { name: "HR 10 · Congress 119" });
    expect(screen.queryByRole("link", { name: "Full bill text" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Congress.gov" })).not.toBeInTheDocument();
  });

  it("shows a short stage and the complete latest action separately", async () => {
    const value = await getBill(10);
    const action = "Referred to the Committee on Education and Workforce, and in addition to the Committees on the Judiciary and Oversight, for consideration of provisions within their respective jurisdictions.";
    vi.mocked(getBill).mockResolvedValue({ ...value, status: action });
    render(<BillDetailPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));
    expect(screen.getAllByText("In committee").some(node => !node.closest("[hidden]"))).toBe(true);
    expect(screen.getByText("Latest action")).toBeVisible();
    expect(screen.getByText(action)).toBeVisible();
  });
  it("shows the document summary before contract generation completes", async () => {
    const value = await getBill(10);
    vi.mocked(getBill).mockResolvedValue({
      ...value, latest_contract: null,
      documents: value.documents.map(document => ({
        ...document, reader_summary: "Bill text: The Secretary shall publish annual reports.",
      })),
    });
    render(<BillDetailPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));
    expect(await screen.findByText("Bill text: The Secretary shall publish annual reports.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Read summary source text" })).toHaveAttribute("href", "/documents/9");
    expect(screen.queryByText(/No generated summary yet/)).not.toBeInTheDocument();
  });
  beforeEach(() => {
    routeState.id = "10";
    vi.clearAllMocks();
    vi.mocked(getSession).mockResolvedValue(null);
    vi.mocked(getBillChanges).mockResolvedValue({
      results: [],
      page_end_cursor: null,
      stream_head_cursor: null,
      older_cursor: null,
      has_more_newer: false,
      has_more_older: false,
      unread_count: null,
      personalized: false,
      initial_window_truncated: false,
    });
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
      summary_preview: null,
      summary_has_more: false,
      summary_source: null,
      summary_action_date: null,
      summary_version_code: null,
      summary_last_updated_at: null,
      processing_status: "complete",
      sponsor: null,
      source_api_id: null,
      documents: [
        {
          id: 9,
          version_label: "Introduced",
          source_order: 1,
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
    } as unknown as Awaited<ReturnType<typeof getBill>>);
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
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));

    expect(await screen.findByRole("heading", { name: "HR 10 · Congress 119" })).toBeVisible();
    expect(screen.getByText("A public bill")).toBeVisible();
    expect(screen.getByRole("link", { name: "Log in to track this bill" })).toHaveAttribute(
      "href",
      "/login",
    );
    await userEvent.click(screen.getByRole("tab", { name: "Versions" }));
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/documents/9/download/",
    );
    expect(screen.getByRole("link", { name: "Read text" })).toHaveAttribute(
      "href",
      "/documents/9",
    );
    expect(screen.queryByRole("heading", { name: "Contract history" })).not.toBeInTheDocument();
    expect(screen.queryByText("Contract history summary")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Votes & sponsor" }));
    expect(screen.getByRole("heading", { name: "Voting record" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "View voting record" }));
    await waitFor(() => expect(getVote).toHaveBeenCalledWith(33));
    expect(await screen.findByRole("link", { name: "Voting Representative" })).toBeVisible();
  });

  it("does not treat different analysis runs as different bill text versions", async () => {
    vi.mocked(getContracts).mockResolvedValueOnce({
      count: 4,
      next: "http://example.test/api/contracts/?page=2",
      previous: null,
      results: [
        { id: 4, schema_version: "1", contract_json: { plain_summary: "Newest" }, contract_hash: "four", computed_at: "2026-08-22T00:00:00Z", document: null, document_version_label: null, evidence_spans: [] },
        { id: 3, schema_version: "1", contract_json: { plain_summary: "Previous" }, contract_hash: "three", computed_at: "2026-08-21T00:00:00Z", document: null, document_version_label: null, evidence_spans: [] },
      ],
    });
    vi.mocked(compareBillContracts).mockResolvedValue({
      before: 3,
      after: 4,
      changes: [],
      total_change_count: 0,
      returned_change_count: 0,
      truncated: false,
    });

    render(<BillDetailPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));

    expect(screen.queryByText("Newest")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Versions" }));
    expect(await screen.findByRole("button", { name: "Compare versions" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Compare analysis" })).not.toBeInTheDocument();
    expect(compareBillContracts).not.toHaveBeenCalled();
  });

  it("discards all bill-specific state when navigating to another bill", async () => {
    const nextBill = {
      ...await getBill(10),
      id: 11,
      bill_number: "HR 11",
      title: "A second public bill",
      documents: [],
    };
    vi.mocked(getBill).mockResolvedValueOnce({
      ...nextBill,
      id: 10,
      bill_number: "HR 10",
      title: "A public bill",
    });
    const { rerender } = render(<BillDetailPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));

    await screen.findByRole("heading", { name: "HR 10 · Congress 119" });
    expect(screen.getByText(/roll call 17: Passed/)).toBeVisible();

    vi.mocked(getBill).mockResolvedValueOnce(nextBill);
    vi.mocked(getContracts).mockReturnValueOnce(new Promise(() => undefined));
    vi.mocked(getVotes).mockReturnValueOnce(new Promise(() => undefined));
    routeState.id = "11";
    rerender(<BillDetailPage />);

    expect(await screen.findByRole("heading", { name: "HR 11 · Congress 119" })).toBeVisible();
    expect(screen.queryByText("Contract history summary")).not.toBeInTheDocument();
    expect(screen.queryByText(/roll call 17: Passed/)).not.toBeInTheDocument();
    expect(screen.queryByText("Loading contract history…")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "What this bill does" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Votes & sponsor" }));
    expect(screen.getByText("Loading vote history…")).toBeVisible();
    expect(getContracts).toHaveBeenLastCalledWith(11, { page: 1, view: "summary" });
    expect(getVotes).toHaveBeenLastCalledWith(11, { page: 1 });
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
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));

    expect(await screen.findByText(/house session unknown roll call 17/)).toBeVisible();
  });

  it("shows a retryable error and clears stale positions when vote detail loading fails", async () => {
    const user = userEvent.setup();
    render(<BillDetailPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));

    const viewPositions = await screen.findByRole("button", {
      name: "View voting record",
    });
    await user.click(viewPositions);
    expect(await screen.findByRole("link", { name: "Voting Representative" })).toBeVisible();

    vi.mocked(getVote).mockRejectedValueOnce(new Error("Vote detail unavailable"));
    await user.click(viewPositions);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load member positions. Try again.",
    );
    expect(screen.queryByRole("link", { name: "Voting Representative" })).not.toBeInTheDocument();
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
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));

    const buttons = await screen.findAllByRole("button", {
      name: "View voting record",
    });
    await user.click(buttons[0]);
    await user.click(buttons[1]);
    resolveSecond(secondVote);
    expect(await screen.findByRole("link", { name: "Second Vote Representative" })).toBeVisible();

    await act(async () => {
      resolveFirst(firstVote);
      await firstRequest;
    });
    expect(screen.queryByRole("link", { name: "First Vote Representative" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Second Vote Representative" })).toBeVisible();
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
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));

    await user.click(
      await screen.findByRole("button", { name: "View voting record" }),
    );
    expect(await screen.findByRole("link", { name: "Voting Representative" })).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: "Next vote history page" }),
    );
    expect(await screen.findByText(/roll call 16: Failed/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Voting Representative" })).not.toBeInTheDocument();
  });

  it("keeps technical contract history hidden while paging through votes", async () => {
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
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));

    expect(screen.queryByText("Newest contract revision")).not.toBeInTheDocument();
    expect(screen.queryByText("Older contract revision")).not.toBeInTheDocument();
    expect(getContracts).toHaveBeenLastCalledWith(10, { page: 1, view: "summary" });

    expect(await screen.findByText(/roll call 17: Passed/)).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "Next vote history page" }),
    );
    expect(await screen.findByText(/roll call 16: Failed/)).toBeVisible();
    expect(getVotes).toHaveBeenLastCalledWith(10, { page: 2 });
  });

  it("keeps vote history visible when a later page fails and retries that section", async () => {
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
      .mockRejectedValueOnce(new Error("Vote service unavailable"))
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
            result: "Recovered",
            yeas: 218,
            nays: 212,
          },
        ],
      });

    render(<BillDetailPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Votes & sponsor" }));

    expect(await screen.findByText(/roll call 17: Passed/)).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "Next vote history page" }),
    );

    expect(await screen.findByText("Could not load vote history. Try again.")).toBeVisible();
    expect(screen.getByText(/roll call 17: Passed/)).toBeVisible();
    expect(screen.queryByText("Contract history summary")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry vote history" }));

    expect(await screen.findByText(/roll call 16: Recovered/)).toBeVisible();
    expect(screen.queryByText("Could not load vote history. Try again.")).not.toBeInTheDocument();
  });
});
