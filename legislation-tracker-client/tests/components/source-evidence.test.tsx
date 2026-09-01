import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SourceEvidence } from "@/app/bills/[id]/source-evidence";
import { getContractEvidence } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getApiBase: () => "http://localhost:8000",
  getContractEvidence: vi.fn(),
}));

describe("SourceEvidence", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads exact source text only when opened and appends later chunks", async () => {
    const user = userEvent.setup();
    vi.mocked(getContractEvidence)
      .mockResolvedValueOnce({
        count: 2,
        next: "page-2",
        previous: null,
        results: [{ start_char: 10, end_char: 16, quoted_text: "first\n", page_number: 1 }],
      })
      .mockResolvedValueOnce({
        count: 2,
        next: null,
        previous: "page-1",
        results: [{ start_char: 16, end_char: 22, quoted_text: " second", page_number: 2 }],
      });

    render(
      <SourceEvidence
        contractId={12}
        lineItemId="line-10"
        textUrl="/api/documents/4/text/"
        downloadUrl="/api/documents/4/download/"
      />,
    );

    expect(getContractEvidence).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Read bill text" }));
    expect(await screen.findByText("first", { exact: false })).toBeVisible();
    expect(getContractEvidence).toHaveBeenCalledWith(12, {
      lineItemId: "line-10",
      page: 1,
      pageSize: 25,
    });

    await user.click(screen.getByRole("button", { name: "Load more source text" }));
    await waitFor(() =>
      expect(screen.getByTestId("source-evidence-text").textContent).toBe("first\n second"),
    );
    expect(screen.getByRole("link", { name: "Read full text" })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/documents/4/text/",
    );
    expect(screen.getByRole("link", { name: "Download document" })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/documents/4/download/",
    );
  });

  it("keeps a failed request retryable", async () => {
    const user = userEvent.setup();
    vi.mocked(getContractEvidence)
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce({
        count: 1,
        next: null,
        previous: null,
        results: [{ start_char: 0, end_char: 5, quoted_text: "exact", page_number: null }],
      });

    render(<SourceEvidence contractId={12} financialItemId="financial-1" />);
    await user.click(screen.getByRole("button", { name: "Read bill text" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load bill text");
    await user.click(screen.getByRole("button", { name: "Retry source text" }));
    expect(await screen.findByText("exact")).toBeVisible();
  });
});
