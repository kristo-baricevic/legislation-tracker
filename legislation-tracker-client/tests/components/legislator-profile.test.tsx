import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import ProfileProvider from "@/app/components/ProfileProvider";
import LegislatorName from "@/app/components/LegislatorName";
import BillDeckModal from "@/app/components/BillDeckModal";

const navigation = vi.hoisted(() => ({ query: "" }));
vi.mock("next/navigation", () => ({ usePathname: () => "/", useSearchParams: () => new URLSearchParams(navigation.query) }));
const FLAG = "legislation-tracker-legislator-profiles";
const coverage = { scope: { congress: 119, chamber: null }, stored_record_count: 1, member_position_completeness: "unknown", unknown_session_record_count: 0, provider_scopes: [{ chamber: "house", description: "House legislation-linked coverage only", source_url: "https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/HouseRollCallVoteEndpoint.md#coverage", historical_availability: "known" }], legacy_ingestion_check: { scopes: [], coverage_complete: false, reason: "Service history unavailable", discovered_count: 0, persisted_count: 0, notice: "Member completeness unknown" } };
const fact = { status: "unavailable", value: null, precision: null, reason: "source_not_connected", source_url: null, retrieved_at: null };
const profile = (id = 1) => ({ schema_version: "legislator-profile-v1", scope: { congress: 119, chamber: null }, identity: { id, bioguide_id: id === 1 ? "S000033" : "I000002", name: id === 1 ? "First Member" : "Second Member", is_current: true, latest_affiliation: { chamber: "senate", state: "VT", party: "Independent", district: null }, last_seen_at: null, source_url: "https://bioguide.congress.gov/search/bio/S000033" }, service: { status: "available", precision: "year", observations: [{ id: 1, chamber: "house", state: "VT", district: "1", start_year: 2023, end_year: 2027, source_url: null, retrieved_at: null }], notice: "Year precision; exact dates unverified" }, elections: [{ chamber: "house", first_elected: fact, most_recent_election_won: fact, term_start: fact }], donors: { status: "unavailable", reason: "source_not_configured", cycle: null, reporting_period: null, currency: null, source_url: null, methodology: null, donors: [] }, coverage });
const biography = { status: "available", text: "A factual Wikipedia excerpt.", reason: null, wikidata_id: "Q359442", page_id: 361176, observed_revision_id: 1378464460, observed_revision_at: "2026-10-04T16:55:30Z", page_url: "https://en.wikipedia.org/wiki/Bernie_Sanders", observed_revision_url: "https://en.wikipedia.org/w/index.php?oldid=1378464460", fetched_at: "2026-10-10T00:00:00Z", shortened: true, attribution: "Wikipedia contributors", license: "CC BY-SA 4.0", license_url: "https://creativecommons.org/licenses/by-sa/4.0/" };
const bill = { id: 10, jurisdiction: "federal", session: 119, bill_number: "HR 5", title: "Introduced legislation", status: "introduced", sponsor_name: "First Member", sponsor_id: 1, sponsor_bioguide_id: "S000033", introduced_at: "2025-01-09", last_action_at: null, topics: [], congress_gov_url: "https://www.congress.gov/bill/119th-congress/house-bill/5" };
const vote = { id: 1, representative_id: 1, vote_id: 1, congress: 119, chamber: "house", session_number: 1, roll_number: 1, vote_date: "2025-01-09T19:00:00Z", question: "On the motion", position: "not_voting", raw_position: "Absent", bill: null, source_url: "javascript:alert(1)", source_link_kind: "roll_call", source_updated_at: null };

beforeEach(() => {
  localStorage.clear();
  navigation.query = "";
  if (!HTMLDialogElement.prototype.showModal) Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() {} });
  if (!HTMLDialogElement.prototype.close) Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() {} });
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.setAttribute("open", ""); this.querySelector<HTMLElement>("[autofocus]")?.focus(); });
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (this: HTMLDialogElement) { this.removeAttribute("open"); });
  vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
    const path = String(input);
    const data = path.includes("/research/") ? { status: "partial", period: 2026, run: null, portrait: null, snapshot: null, biography: { text: biography.text, source: { url: biography.page_url, attribution: biography.attribution, license: biography.license, fetched_at: biography.fetched_at } } } : path.includes("/profile/") ? profile(path.includes("/2/") ? 2 : 1) : path.includes("/biography/") ? biography : path.includes("/sponsored-bills/") ? { count: 1, next: null, previous: null, results: [bill] } : path.includes("/voting-record/") ? { count: 1, next: null, previous: null, results: [vote], page_read_at: "2026-10-10T00:00:00Z", pagination_mode: "live_pages", coverage } : { ...bill, summary: "Official bill summary", processing_status: "pending", sponsor: 1, source_api_id: null, documents: [], latest_contract: null, created_at: "2025-01-09T00:00:00Z", updated_at: "2025-01-09T00:00:00Z" };
    return new Response(JSON.stringify(data));
  }));
});

it.each(["loading", "error"])("bill Close remains usable while details are %s and supports reopening", async state => {
  vi.stubGlobal("fetch", vi.fn(() => state === "loading" ? new Promise<Response>(() => {}) : Promise.reject(new Error("offline"))));
  function Fixture() {
    const [open, setOpen] = React.useState(false);
    return <ProfileProvider><button onClick={() => setOpen(true)}>Open bill</button>{open && <BillDeckModal bill={bill} onClose={() => setOpen(false)} />}</ProfileProvider>;
  }
  render(<React.StrictMode><Fixture /></React.StrictMode>);
  const user = userEvent.setup();
  const opener = screen.getByRole("button", { name: "Open bill" });
  for (let attempt = 0; attempt < 2; attempt++) {
    await user.click(opener);
    await screen.findByRole("dialog", { name: bill.title });
    if (state === "error") await screen.findByRole("alert");
    else expect(screen.getByText("Loading bill details…")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close bill details" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(opener).toHaveFocus());
    expect(document.body.style.overflow).toBe("");
  }
});

it.each(["loading", "error"])("profile Close remains usable while profile is %s", async state => {
  localStorage.setItem(FLAG, "true");
  vi.stubGlobal("fetch", vi.fn(() => state === "loading" ? new Promise<Response>(() => {}) : Promise.reject(new Error("offline"))));
  render(<React.StrictMode>{page()}</React.StrictMode>);
  const user = userEvent.setup();
  const opener = screen.getByRole("link", { name: "First Member" });
  await user.click(opener);
  await screen.findByRole("dialog");
  await user.click(screen.getByRole("button", { name: "Close legislator profile" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await waitFor(() => expect(opener).toHaveFocus());
  expect(document.body.style.overflow).toBe("");
});

function page() {
  return <ProfileProvider><LegislatorName id={1} name="First Member" congress={119} /><LegislatorName id={2} name="Second Member" congress={119} /></ProfileProvider>;
}

it("retains historical anchor context and does not fetch profiles while disabled", async () => {
  render(page());
  const link = screen.getByRole("link", { name: "First Member" });
  expect(link).toHaveAttribute("href", "/representatives/1?congress=119");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

it("opens factual sections by ID, loads votes lazily, and suppresses unsafe source URLs", async () => {
  localStorage.setItem(FLAG, "false"); render(page());
  const user = userEvent.setup();
  const opener = screen.getByRole("link", { name: "First Member" });
  await user.click(opener);
  const dialog = await screen.findByRole("dialog", { name: "First Member" });
  expect(within(dialog).getByText("Latest stored affiliation")).toBeInTheDocument();
  expect(within(dialog).getByText(/2023.*2027/)).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Refresh research" })).toBeInTheDocument();
  expect(await within(dialog).findByText("A factual Wikipedia excerpt.")).toBeInTheDocument();
  expect(within(dialog).getByRole("link", { name: "Wikipedia contributors" })).toHaveAttribute("href", biography.page_url);
  expect(vi.mocked(fetch).mock.calls.some(([path]) => String(path).includes("voting-record"))).toBe(false);
  await user.click(within(dialog).getByRole("button", { name: "Show voting record" }));
  expect(await within(dialog).findByText("Absent (source wording)")).toBeInTheDocument();
  expect(within(dialog).getByText("Bill link unavailable")).toBeInTheDocument();
  expect(dialog.querySelector('a[href^="javascript:"]')).toBeNull();
  fireEvent(dialog, new Event("cancel", { bubbles: false, cancelable: true }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(opener).toHaveFocus();
  expect(document.body.style.overflow).toBe("");
});

it("keeps bill→profile nesting in one stack, with unique titles and rollback close", async () => {
  localStorage.setItem(FLAG, "true"); render(page());
  const user = userEvent.setup();
  await user.click(screen.getByRole("link", { name: "First Member" }));
  const parent = await screen.findByRole("dialog", { name: "First Member" });
  const introduced = await within(parent).findByRole("link", { name: "Introduced legislation" });
  await user.click(introduced);
  const child = await screen.findByRole("dialog", { name: "Introduced legislation" });
  expect(parent.getAttribute("aria-labelledby")).not.toBe(child.getAttribute("aria-labelledby"));
  fireEvent(child, new Event("cancel", { cancelable: true }));
  await waitFor(() => expect(child).not.toBeInTheDocument());
  expect(introduced).toHaveFocus();
  expect(document.body.style.overflow).toBe("hidden");
  await user.click(screen.getByRole("button", { name: "Close legislator profile" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(document.body.style.overflow).toBe("");
});

it("does not put a late response for one person into a new profile", async () => {
  localStorage.setItem(FLAG, "true");
  let resolveFirst!: (value: Response) => void;
  const original = fetch;
  vi.stubGlobal("fetch", vi.fn((input: string | URL | Request, init?: RequestInit) => String(input).includes("/1/profile/") ? new Promise<Response>(resolve => { resolveFirst = resolve; }) : original(input, init)));
  render(page()); const user = userEvent.setup();
  await user.click(screen.getByRole("link", { name: "First Member" }));
  await user.click(screen.getByRole("button", { name: "Close legislator profile" }));
  await user.click(screen.getByRole("link", { name: "Second Member" }));
  expect(await screen.findByRole("dialog", { name: "Second Member" })).toBeInTheDocument();
  resolveFirst(new Response(JSON.stringify(profile(1))));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "First Member" })).not.toBeInTheDocument());
});

it("pairs the detail sponsor name and ID after a sponsor correction", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...bill, sponsor: 2, sponsor_name: "Corrected Sponsor", summary: null, documents: [] }))));
  render(<ProfileProvider><BillDeckModal bill={bill} onClose={() => {}} /></ProfileProvider>);
  const modal = await screen.findByRole("dialog", { name: "Introduced legislation" });
  const corrected = await within(modal).findByRole("link", { name: "Corrected Sponsor" });
  expect(corrected).toHaveAttribute("href", "/representatives/2?congress=119");
  expect(within(modal).queryByRole("link", { name: "First Member" })).not.toBeInTheDocument();
});

it("closes and aborts the stack on query-only navigation", async () => {
  localStorage.setItem(FLAG, "true");
  const view = render(page()); const user = userEvent.setup();
  await user.click(screen.getByRole("link", { name: "First Member" }));
  await screen.findByRole("dialog", { name: "First Member" });
  navigation.query = "congress=118"; view.rerender(page());
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  const calls = vi.mocked(fetch).mock.calls;
  expect(calls.filter(([url]) => String(url).includes("/representatives/")).every(([, options]) => options?.signal?.aborted)).toBe(true);
  expect(document.body.style.overflow).toBe("");
});

it("returns focus to a connected page control when the opener disappears", async () => {
  localStorage.setItem(FLAG, "true");
  const view = render(page()); const user = userEvent.setup();
  await user.click(screen.getByRole("link", { name: "First Member" }));
  await screen.findByRole("dialog", { name: "First Member" });
  view.rerender(<ProfileProvider><button>Page action</button></ProfileProvider>);
  await user.click(screen.getByRole("button", { name: "Close legislator profile" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Page action" })).toHaveFocus());
});

it("repeated clicks consume the same profile navigation without duplicate dialogs", async () => {
  localStorage.setItem(FLAG, "true"); render(page());
  const link = screen.getByRole("link", { name: "First Member" });
  expect(fireEvent.click(link)).toBe(false);
  expect(fireEvent.click(link)).toBe(false);
  await screen.findByRole("dialog", { name: "First Member" });
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/profile/"))).toHaveLength(1);
});

it("restores a connected bill opener before its owner fallback", async () => {
  const fallback = vi.fn();
  function Fixture() {
    const [open, setOpen] = React.useState(false);
    return <ProfileProvider><button onClick={() => setOpen(true)}>Recommended bill</button>{open && <BillDeckModal bill={bill} onClose={() => setOpen(false)} fallbackFocus={fallback} />}</ProfileProvider>;
  }
  render(<Fixture />); const user = userEvent.setup();
  const opener = screen.getByRole("button", { name: "Recommended bill" });
  await user.click(opener);
  await screen.findByRole("dialog", { name: "Introduced legislation" });
  await user.click(screen.getByRole("button", { name: "Close bill details" }));
  await waitFor(() => expect(opener).toHaveFocus());
  expect(fallback).not.toHaveBeenCalled();
});

it("uses the current bill owner fallback after its row disappears", async () => {
  localStorage.setItem(FLAG, "true");
  const firstFallback = vi.fn();
  const finalFallback = vi.fn(() => document.getElementById("bill-recommendations-title")?.focus());
  function Fixture({ showRow, fallback }: { showRow: boolean; fallback: () => void }) {
    const [open, setOpen] = React.useState(false);
    return <ProfileProvider><button>Unrelated page action</button><h2 id="bill-recommendations-title" tabIndex={-1}>Recommended bills</h2>{showRow && <button onClick={() => setOpen(true)}>Recommended bill</button>}{open && <BillDeckModal bill={bill} onClose={() => setOpen(false)} fallbackFocus={fallback} />}</ProfileProvider>;
  }
  const view = render(<Fixture showRow fallback={firstFallback} />); const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Recommended bill" }));
  const parent = await screen.findByRole("dialog", { name: "Introduced legislation" });
  const sponsor = await within(parent).findByRole("link", { name: "First Member" });
  await user.click(sponsor);
  await screen.findByRole("dialog", { name: "First Member" });
  view.rerender(<Fixture showRow={false} fallback={finalFallback} />);
  await user.click(screen.getByRole("button", { name: "Close legislator profile" }));
  await waitFor(() => expect(sponsor).toHaveFocus());
  expect(finalFallback).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Close bill details" }));
  await waitFor(() => expect(screen.getByRole("heading", { name: "Recommended bills" })).toHaveFocus());
  expect(finalFallback).toHaveBeenCalledOnce();
  expect(firstFallback).not.toHaveBeenCalled();
});

 it("removes profile and introduced-bill descendants when the owning root disappears", async () => {
  localStorage.setItem(FLAG, "true");
  const original = fetch;
  vi.stubGlobal("fetch", vi.fn((input: string | URL | Request, init?: RequestInit) => String(input).includes("/sponsored-bills/") ? Promise.resolve(new Response(JSON.stringify({ count: 1, next: null, previous: null, results: [{ ...bill, id: 11, title: "Different introduced bill" }] }))) : original(input, init)));
  const fallback = vi.fn(() => document.getElementById("owner-heading")?.focus());
  function Fixture({ show }: { show: boolean }) { return <ProfileProvider><h2 id="owner-heading" tabIndex={-1}>Owner heading</h2>{show && <BillDeckModal bill={bill} onClose={() => {}} fallbackFocus={fallback} />}</ProfileProvider>; }
  const view = render(<Fixture show />); const user = userEvent.setup();
  const root = await screen.findByRole("dialog", { name: "Introduced legislation" });
  await user.click(await within(root).findByRole("link", { name: "First Member" }));
  const profileDialog = await screen.findByRole("dialog", { name: "First Member" });
  await user.click(await within(profileDialog).findByRole("link", { name: "Different introduced bill" }));
  await screen.findByRole("dialog", { name: "Different introduced bill" });
  view.rerender(<Fixture show={false} />);
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await waitFor(() => expect(screen.getByRole("heading", { name: "Owner heading" })).toHaveFocus());
  expect(document.body.style.overflow).toBe("");
  expect(fallback).toHaveBeenCalledOnce();
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/representatives/")).every(([, options]) => options?.signal?.aborted)).toBe(true);
 });
