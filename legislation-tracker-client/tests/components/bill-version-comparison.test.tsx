import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import BillVersionComparison from "@/app/bills/[id]/bill-version-comparison";
import { compareBillDocuments, compareBillDocumentSection, type BillDocumentItem, type DocumentComparison } from "@/lib/api";

vi.mock("@/lib/api", () => ({ compareBillDocuments: vi.fn(), compareBillDocumentSection: vi.fn() }));
const documents: BillDocumentItem[] = [1, 2, 3].map(id => ({
  id, version_label: `Version ${id}`, is_active_version: id === 3, source_order: id,
  content_type: null, file_size_bytes: null, source_url: null, downloaded_at: null, download_url: null, text_url: null,
}));
const result = (count = 1): DocumentComparison => ({
  before: 1, after: 3, sections: Array.from({ length: count }, (_, index) => ({
    section_key: `sec. ${index + 1}#1`, operation: "modified", before_hash: "a", after_hash: "b",
  })),
  total_change_count: count, returned_change_count: count, truncated: false, fallback: false, truncation_reasons: [],
});
beforeEach(() => {
  vi.mocked(compareBillDocuments).mockResolvedValue(result());
  vi.mocked(compareBillDocumentSection).mockImplementation(async (_bill, _before, _after, key) => ({
    section_key: key, operations: [{ operation: "insert", before: [], after: [`New passage ${key}`] }],
    truncated: false, truncation_reasons: [],
  }));
});
function show() {
  render(<BillVersionComparison billId={10} documents={documents} initialPair={[documents[0], documents[2]]} />);
  return userEvent.setup();
}

it("paginates sections and keeps added text opposite an explicit empty before card", async () => {
  vi.mocked(compareBillDocuments).mockResolvedValue(result(6));
  const user = show();
  await user.click(screen.getByRole("button", { name: "Compare versions" }));
  expect(await screen.findByText("New passage sec. 1#1")).toBeVisible();
  expect(screen.getAllByText("No corresponding text in this version.")).toHaveLength(5);
  expect(compareBillDocumentSection).toHaveBeenCalledTimes(5);
  await user.click(screen.getByRole("button", { name: "Next" }));
  expect(await screen.findByText("New passage sec. 6#1")).toBeVisible();
  expect(screen.queryByText("New passage sec. 1#1")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Prev" }));
  expect(await screen.findByText("New passage sec. 1#1")).toBeVisible();
});

it("retries failed passage requests and discloses incomplete comparisons", async () => {
  vi.mocked(compareBillDocuments).mockResolvedValue({ ...result(), truncated: true });
  vi.mocked(compareBillDocumentSection).mockRejectedValueOnce(new Error("unavailable"));
  const user = show();
  await user.click(screen.getByRole("button", { name: "Compare versions" }));
  await user.click(await screen.findByRole("button", { name: "Retry comparison" }));
  expect(await screen.findByText("New passage sec. 1#1")).toBeVisible();
  expect(screen.getByRole("note")).toHaveTextContent("This comparison is incomplete");
});

it("does not display a stale request after changing versions or closing", async () => {
  let resolve!: (value: DocumentComparison) => void;
  vi.mocked(compareBillDocuments).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const user = show();
  await user.click(screen.getByRole("button", { name: "Compare versions" }));
  await user.selectOptions(screen.getByLabelText("Before version"), "2");
  expect(await screen.findByText("New passage sec. 1#1")).toBeVisible();
  await act(async () => resolve(result(6)));
  expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  expect(compareBillDocumentSection).toHaveBeenLastCalledWith(10, 2, 3, "sec. 1#1");
  await user.click(screen.getByRole("button", { name: "Close comparison" }));
  expect(screen.queryByText("New passage sec. 1#1")).not.toBeInTheDocument();
});

it("shows an honest empty state", async () => {
  vi.mocked(compareBillDocuments).mockResolvedValue(result(0));
  const user = show();
  await user.click(screen.getByRole("button", { name: "Compare versions" }));
  expect(await screen.findByText("No text changes were found between these versions.")).toBeVisible();
});
