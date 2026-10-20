import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import BillDeckModal from "@/app/components/BillDeckModal";
import ProfileProvider from "@/app/components/ProfileProvider";

vi.mock("next/navigation", () => ({ usePathname: () => "/bills", useSearchParams: () => new URLSearchParams() }));
const bill = { id: 463, jurisdiction: "federal", session: 119, bill_number: "HR 9300", title: "Postsecondary Student Success Act of 2026", status: "introduced", sponsor_name: "", introduced_at: null, last_action_at: null, topics: [] };
const synopsis = "This bill aims to support participation, retention, and completion activities for high-need students.";
const document = { id: 511, version_label: "Introduced in House", source_order: 1, is_active_version: true, content_type: "application/xml", file_size_bytes: 22755, source_url: null, downloaded_at: "2026-09-01", download_url: "/api/documents/511/download/", text_url: "/api/documents/511/text/" };
const detail = { ...bill, summary: null, summary_source: "", summary_version_code: "", processing_status: "complete", sponsor: null, source_api_id: "119-hr-9300", congress_gov_url: null, documents: [document], latest_contract: { id: 4729, document: 511, document_version_label: "Introduced in House", schema_version: "2.1-legal-nlp", contract_json: { orientation: { purpose_clause: synopsis, purpose_line_item_id: "line-purpose-108-1" } }, contract_hash: "hash", computed_at: "2026-09-01", evidence_spans: [] }, created_at: "2026-09-01", updated_at: "2026-09-01" };

beforeEach(() => {
  if (!HTMLDialogElement.prototype.showModal) Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() {} });
  if (!HTMLDialogElement.prototype.close) Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() {} });
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.setAttribute("open", ""); });
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (this: HTMLDialogElement) { this.removeAttribute("open"); });
});

function show(value: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(value))));
  render(<ProfileProvider><BillDeckModal bill={bill} onClose={() => {}} /></ProfileProvider>);
}

function selectedSection() {
  return within(screen.getByRole("heading", { name: /^Selected version:/ }).closest("section")!);
}

it("shows the generated synopsis and source document when the official summary is absent", async () => {
  show(detail);
  await screen.findByRole("heading", { name: "Selected version: Introduced in House" });
  expect(selectedSection().getByText(synopsis)).toBeInTheDocument();
  expect(selectedSection().getByRole("link", { name: "Read this document" })).toHaveAttribute("href", "/documents/511");
  expect(screen.queryByText(/specifically linked.*unavailable/)).not.toBeInTheDocument();
  expect(screen.queryByText("No bill summary is available yet.")).not.toBeInTheDocument();
});

it("does not assign the current document synopsis to a different selected version", async () => {
  show({ ...detail, documents: [document, { ...document, id: 512, version_label: "Reported in House", is_active_version: false, source_order: null }] });
  await screen.findByRole("heading", { name: "Selected version: Introduced in House" });
  await userEvent.setup().click(screen.getByRole("button", { name: "Reported in House" }));
  expect(selectedSection().queryByText(synopsis)).not.toBeInTheDocument();
  expect(selectedSection().getByText(/No summary is available for this version/)).toBeInTheDocument();
});

it("does not refer to a summary above when neither summary source exists", async () => {
  show({ ...detail, latest_contract: null });
  await screen.findByRole("heading", { name: "Selected version: Introduced in House" });
  expect(selectedSection().getByText(/No summary is available for this version/)).toBeInTheDocument();
  expect(screen.queryByText(/bill summary above/)).not.toBeInTheDocument();
});

it("keeps the official bill summary while using the matching document synopsis", async () => {
  show({ ...detail, summary: "Official overview from an earlier version.", summary_source: "crs", summary_version_code: "earlier" });
  await screen.findByRole("heading", { name: "Selected version: Introduced in House" });
  expect(screen.getByText("Official overview from an earlier version.")).toBeInTheDocument();
  expect(selectedSection().getByText(synopsis)).toBeInTheDocument();
});

it("uses a source-based document summary when no extracted purpose exists", async () => {
  show({ ...detail, latest_contract: null, documents: [{ ...document, reader_summary: "This bill would provide funding for Department of Homeland Security for fiscal year 2026." }] });
  await screen.findByRole("heading", { name: "Selected version: Introduced in House" });
  expect(selectedSection().getByText(/would provide funding for Department/)).toBeVisible();
  expect(screen.queryByText("No bill summary is available yet.")).not.toBeInTheDocument();
});

it("prefers the document synopsis over a fragmentary legacy extraction", async () => {
  show({ ...detail, latest_contract: { ...detail.latest_contract, contract_json: { plain_summary: "SEC." } }, documents: [{ ...document, reader_summary: "This bill would fund homeland security programs in fiscal year 2026." }] });
  await screen.findByRole("heading", { name: "Selected version: Introduced in House" });
  expect(selectedSection().getByText(/would fund homeland security/)).toBeVisible();
  expect(screen.queryByText("SEC.")).not.toBeInTheDocument();
});

it("keeps a supported synopsis ahead of an extractive fallback", async () => {
  show({ ...detail, documents: [{ ...document, reader_summary: "Bill text: The Secretary shall establish a program." }] });
  await screen.findByRole("heading", { name: "Selected version: Introduced in House" });
  expect(selectedSection().getByText(synopsis)).toBeVisible();
});

it("shows a source-linked fallback even before analysis is generated", async () => {
  const fallback = "Bill text: The Secretary shall publish annual reports.";
  show({ ...detail, latest_contract: null, documents: [{ ...document, reader_summary: fallback }] });
  await screen.findByRole("heading", { name: "Selected version: Introduced in House" });
  expect(selectedSection().getByText(fallback)).toBeVisible();
  expect(selectedSection().getByRole("link", { name: "Read this document" })).toHaveAttribute("href", "/documents/511");
  expect(screen.queryByText("No bill summary is available yet.")).not.toBeInTheDocument();
});
