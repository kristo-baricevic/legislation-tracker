import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import BillDeck from "@/app/components/BillDeck";
import { authGet, authPost, getMyTracking, getSession, getBillFilterOptions, getAllCurrentRepresentatives } from "@/lib/api";
vi.mock("@/app/components/RecommendationsPreview", () => ({ default: () => <h2>Recommendation section</h2> }));

vi.mock("@/lib/api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  getSession: vi.fn(),
  getMyTracking: vi.fn(),
  getBillFilterOptions: vi.fn().mockResolvedValue({ jurisdictions: ["federal"], current_congress: 119 }),
  getAllCurrentRepresentatives: vi.fn().mockResolvedValue([]),
  authGet: vi.fn(),
  authPost: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  localStorage.setItem("legislation-tracker-ingestion-telemetry", "true");
  vi.mocked(getBillFilterOptions).mockResolvedValue({ jurisdictions: ["federal"], current_congress: 119 });
  vi.mocked(getAllCurrentRepresentatives).mockResolvedValue([]);
  vi.mocked(getSession).mockResolvedValue({ authenticated: true, user: { email: "reader@example.com" } });
  vi.mocked(getMyTracking).mockResolvedValue({ bills: [], topics: [], legislators: [], is_staff: false });
});

it("keeps followed bills in one collection with sorting and topic filtering", async () => {
  const makeBill = (id: number, title: string, date: string, topic: string) => ({ id, title, bill_number: `HR ${id}`, session: 119, jurisdiction: "federal", status: "introduced", sponsor_id: null, sponsor_name: null, sponsor_bioguide_id: null, introduced_at: date, last_action_at: date, topics: [{ topic_id: id, name: topic, slug: topic, confidence_score: 1 }] });
  const bills = [makeBill(1, "Alpha", "2025-01-01", "Health"), makeBill(2, "Zulu", "2025-02-01", "Education")];
  vi.mocked(getMyTracking).mockResolvedValue({ bills: bills.map(bill => ({ id: bill.id, bill, created_at: "2025-03-01" })), topics: [], legislators: [], is_staff: false });
  render(<BillDeck />);
  await screen.findByRole("button", { name: "Alpha" });
  expect(screen.getAllByRole("region", { name: "Followed bills" })).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "View all bills" })).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Followed bills" }).compareDocumentPosition(screen.getByRole("heading", { name: "Recommendation section" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const titles = () => screen.getAllByRole("article").map(card => card.querySelector("h3")?.textContent);
  expect(titles()).toEqual(["Zulu", "Alpha"]);
  const user = userEvent.setup();
  await user.selectOptions(screen.getByLabelText("Sort bills"), "title");
  expect(titles()).toEqual(["Alpha", "Zulu"]);
  await user.selectOptions(screen.getByLabelText("Topic", { exact: true }), "2");
  expect(titles()).toEqual(["Zulu"]);
  expect(screen.queryByRole("heading", { name: "Education" })).not.toBeInTheDocument();
});

it("keeps the live telemetry panel visible without exposing samples or starting work", async () => {
  render(<BillDeck />);
  await screen.findByRole("heading", { name: "Your collection starts with a bill" });
  expect(screen.queryByText("24 sample")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Legislation ingestion" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start discovery and ingestion" })).toBeEnabled();
  expect(screen.queryByLabelText("Show ingestion telemetry preview")).not.toBeInTheDocument();
  expect(authGet).not.toHaveBeenCalled();
  expect(authPost).not.toHaveBeenCalled();
});

it("shows real telemetry to staff on refresh without requiring sample mode", async () => {
  vi.mocked(getMyTracking).mockResolvedValue({ bills: [], topics: [], legislators: [], is_staff: true });
  vi.mocked(authGet).mockImplementation(async path => path.includes("source-readiness")
    ? { available: false, missing_unqueued_metadata: null }
    : { observed_at: "2026-10-15T12:00:00Z", last_discovery_completed_at: null, last_successful_work_item_at: null, counts_by_kind_and_status: [{ kind: "bill", status: "pending", count: 17 }], stale_leases: 0, discovery_run: null, recent_work_states: [] });
  const user = userEvent.setup();
  render(<BillDeck />);
  await user.click(await screen.findByRole("button", { name: "Refresh telemetry" }));
  expect(screen.getByRole("heading", { name: "Queued" }).parentElement).toHaveTextContent("17");
  expect(screen.queryByLabelText("Show ingestion telemetry preview")).not.toBeInTheDocument();
  expect(screen.queryByText("24 sample")).not.toBeInTheDocument();
  expect(authPost).not.toHaveBeenCalled();
});
