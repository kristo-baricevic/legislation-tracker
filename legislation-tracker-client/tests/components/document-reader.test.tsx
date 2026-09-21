import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { DocumentReader } from "@/app/documents/[id]/document-reader";
import { publicGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({ publicGet: vi.fn(), getApiBase: () => "http://localhost:8000" }));
const metadata = { id: 511, bill: 463, bill_title: "Student Success Act", bill_number: "HR 9300", version_label: "Introduced", download_url: "/api/documents/511/download/" };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(publicGet).mockImplementation(async (path) => path.endsWith("/text/") ? { text: "SEC. 1. Grants\nGrants support students.\nSEC. 2. Reports\nPublish a report." } : metadata);
});
it("shows source text, version, return navigation and downloadable original", async () => {
  render(<DocumentReader documentId="511" />);
  expect(await screen.findByRole("heading", { name: "Student Success Act" })).toBeVisible();
  expect(screen.getByText("Introduced")).toBeVisible();
  expect(screen.getByRole("heading", { name: "SEC. 1. Grants" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Back to bill summary" })).toHaveAttribute("href", "/bills/463");
  expect(screen.getByRole("link", { name: "Download original" })).toHaveAttribute("href", "http://localhost:8000/api/documents/511/download/");
});
it("finds literal text and reports no matches", async () => {
  const user = userEvent.setup();
  render(<DocumentReader documentId="511" />);
  await screen.findByText("Grants support students.");
  await user.type(screen.getByRole("searchbox"), "grants");
  expect(screen.getByRole("status")).toHaveTextContent("1 of 2 matches");
  await user.click(screen.getByRole("button", { name: "Next match" }));
  expect(screen.getByRole("status")).toHaveTextContent("2 of 2 matches");
  await user.clear(screen.getByRole("searchbox"));
  await user.type(screen.getByRole("searchbox"), "[[missing]");
  expect(screen.getByRole("status")).toHaveTextContent("No matches");
});
it("retries a failed load without exposing the API page", async () => {
  const user = userEvent.setup();
  vi.mocked(publicGet).mockRejectedValueOnce(new Error("offline"));
  render(<DocumentReader documentId="511" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load");
  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("Grants support students.")).toBeVisible();
});
it("shows an unavailable state for empty text", async () => {
  vi.mocked(publicGet).mockImplementation(async (path) => path.endsWith("/text/") ? { text: "" } : metadata);
  render(<DocumentReader documentId="511" />);
  expect(await screen.findByText("Text is not available for this version yet.")).toBeVisible();
});
