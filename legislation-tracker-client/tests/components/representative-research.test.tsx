import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import RepresentativeResearch from "@/app/components/RepresentativeResearch";

const empty = { status: "not_started", period: 2026, run: null, biography: null, portrait: null, snapshot: null };

it.each([false, true])("refreshes all-year totals after a published campaign is replaced (modal: %s)", async (modalView) => {
  let refreshed = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("by_size")) return Response.json({ status: "partial", total: refreshed ? "250" : "100", refunds: "0", results: [] });
    if (url.includes("contributors")) return Response.json({ status: "partial", count: 0, next_cursor: null, results: [] });
    return Response.json({ ...empty, status: "succeeded", snapshot: refreshed ? "new" : "old", available_periods: [2026], finance_progress: { pages_loaded: 7, official_totals: [] } });
  }));
  render(<RepresentativeResearch representativeId={1} financeView modalView={modalView} />);
  const dropdown = screen.getByRole("combobox", { name: "Reporting period" });
  await waitFor(() => expect(dropdown).toBeEnabled());
  await userEvent.selectOptions(dropdown, "all");
  expect(await screen.findByText("$100.00")).toBeVisible();
  refreshed = true;
  act(() => window.dispatchEvent(new CustomEvent("representative-research-updated", { detail: 1 })));
  expect(await screen.findByText("$250.00")).toBeVisible();
});

it("appends outside spending on scroll without removing existing rows or showing pagination", async () => {
  let intersect: IntersectionObserverCallback = () => {};
  vi.stubGlobal("IntersectionObserver", class {
    constructor(callback: IntersectionObserverCallback) { intersect = callback; }
    observe() {} disconnect() {}
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (!url.includes("outside-spending")) return Response.json(empty);
    const next = url.includes("cursor=20");
    return Response.json({ status: "available", support: "100", oppose: "0", count: 21, next_cursor: next ? null : 20, results: [{ id: next ? 2 : 1, name: next ? "Second group" : "First group", amount: "50", position: "S", period: 2024, source_url: "https://www.fec.gov/" }] });
  }));
  render(<RepresentativeResearch representativeId={1} financeView />);
  await userEvent.click(screen.getByRole("button", { name: "Outside spending" }));
  await screen.findByRole("link", { name: "First group" });
  expect(screen.queryByRole("navigation", { name: "Outside spending pages" })).not.toBeInTheDocument();
  intersect([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
  expect(await screen.findByRole("link", { name: "Second group" })).toBeVisible();
  expect(screen.getByRole("link", { name: "First group" })).toBeVisible();
});

it("finishes the research button when the overview is ready without stopping background polling", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...empty, status: "running", run: { id: "run", status: "running", sections: {} }, finance_progress: { overview_ready: true, collecting: true, pages_loaded: 3, streams_completed: 1, streams_total: 7, official_totals: [] } })));
  render(<RepresentativeResearch representativeId={1} cardName="Bruce Westerman" />);
  const button = await screen.findByRole("button", { name: "Research Bruce Westerman" });
  await waitFor(() => expect(button).toHaveTextContent("Researched"));
  expect(button).toBeEnabled();
  await userEvent.click(button);
  expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
});

it("keeps the funding layout mounted while changing reporting periods", async () => {
  let finish: (response: Response) => void = () => {};
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("contributors")) return Response.json({ status: "partial", count: 1, next_cursor: null, results: [{ id: 1, name: "Saved donor", amount: "250", source_url: "https://www.fec.gov/" }] });
    if (url.includes("period=2024")) return new Promise<Response>(resolve => { finish = resolve; });
    return Response.json({ ...empty, status: "partial", snapshot: "saved", available_periods: [2026, 2024] });
  }));
  render(<RepresentativeResearch representativeId={1} financeView />);
  const donor = await screen.findByRole("link", { name: "Saved donor" });
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Reporting period" }), "2024");
  expect(donor).toBeInTheDocument();
  expect(screen.queryByText("Loading funding…")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Funding results")).toHaveAttribute("aria-busy", "true");
  finish(Response.json({ ...empty, period: 2024, status: "partial", snapshot: "historic", available_periods: [2026, 2024] }));
  await waitFor(() => expect(screen.getByLabelText("Funding results")).toHaveAttribute("aria-busy", "false"));
});

it("starts collection for an unsaved selected period and groups funding controls", async () => {
  let started = false;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, options?: RequestInit) => {
    if (_url.includes("csrf")) return Response.json({ csrf_token: "test" });
    if (options?.method === "POST") {
      started = JSON.parse(String(options.body)).period === 2024;
      return Response.json({ id: "historical", status: "queued", sections: {} });
    }
    return Response.json({ ...empty, status: started ? "queued" : "not_started", available_periods: [2026, 2024] });
  }));
  render(<RepresentativeResearch representativeId={1} financeView />);
  const dropdown = await screen.findByRole("combobox", { name: "Reporting period" });
  await waitFor(() => expect(dropdown).not.toBeDisabled());
  expect(dropdown.closest('[aria-label="Funding controls"]')).toContainElement(screen.getByRole("button", { name: "Outside spending" }));
  await userEvent.selectOptions(dropdown, "2024");
  expect(await screen.findByText("Campaign research queued.")).toBeVisible();
  expect(dropdown).toHaveValue("2024");
});

it("keeps donations and outside spending separate on the full page", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("outside-spending")) return Response.json({ status: "available", support: "1250000", oppose: "50", count: 1, next_cursor: null, results: [{ id: 1, name: "Example Super PAC", amount: "1250000", position: "S", source_url: "https://www.fec.gov/" }] });
    if (url.includes("contributors")) return Response.json({ status: "partial", count: 1, next_cursor: null, results: [{ id: 1, name: "Donor", amount: "250", source_url: "https://www.fec.gov/" }] });
    return Response.json({ ...empty, snapshot: "saved", available_periods: [2026] });
  }));
  render(<RepresentativeResearch representativeId={1} financeView />);
  expect(await screen.findByRole("link", { name: "Donor" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Refunds" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Outside spending" }));
  expect(await screen.findByRole("link", { name: "Example Super PAC" })).toBeVisible();
  expect(screen.getByText("Supporting")).toBeVisible();
  expect(screen.queryByRole("link", { name: "Donor" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Donations" }));
  expect(await screen.findByRole("link", { name: "Donor" })).toBeVisible();
});

it("shows donation dollars by size as a pie in the modal", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("by_size=true")) return Response.json({ status: "partial", total: "1000", results: [{ label: "Under $200", amount: "250" }, { label: "$200–$999", amount: "750" }] });
    return Response.json({ ...empty, snapshot: "saved", available_periods: [2026] });
  }));
  render(<RepresentativeResearch representativeId={1} financeView modalView />);
  expect(await screen.findByRole("img", { name: "Donation dollars by donation size" })).toBeVisible();
  expect(screen.getByText("25%")).toBeVisible();
  expect(screen.getByText("75%")).toBeVisible();
  expect(screen.queryByRole("list", { name: "Contribution records" })).not.toBeInTheDocument();
});

it("offers only saved funding periods and selects the latest available period", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...empty, available_periods: [2024, 2020] })));
  render(<RepresentativeResearch representativeId={1} financeView />);
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Reporting period" })).toHaveValue("2024"));
  expect(screen.getAllByRole("option").map(option => option.textContent)).toEqual(["All years", "2023–2024", "2019–2020"]);
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Reporting period" }), "2020");
  expect(screen.getByRole("combobox", { name: "Reporting period" })).toHaveValue("2020");
});

it("disables the period selector when no funding data exists", async () => {
  render(<RepresentativeResearch representativeId={1} financeView />);
  await screen.findByText("No campaign records available for this period.");
  expect(screen.getByRole("combobox", { name: "Reporting period" })).toBeDisabled();
  expect(screen.queryByRole("option", { name: "2025–2026" })).not.toBeInTheDocument();
});

it("preserves the list, pagination, and focus while switching funding records", async () => {
  let finish: (value: Response) => void = () => {};
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("contributors")) {
      if (url.includes("kind=refund")) return new Promise<Response>(resolve => { finish = resolve; });
      return Response.json({ status: "partial", results: [{ id: 1, name: "Saved donor", amount: "50", type: "individual", committee: "Campaign", date: "2026-01-01", source_url: "https://www.fec.gov/" }], count: 1, next_cursor: null });
    }
    return Response.json({ ...empty, status: "partial", snapshot: "saved" });
  }));
  render(<RepresentativeResearch representativeId={1} financeView />);
  await screen.findByRole("link", { name: "Saved donor" });
  const list = screen.getByRole("list", { name: "Contribution records" });
  const pages = screen.getByRole("navigation", { name: "Contributor pages" });
  const refunds = screen.getByRole("button", { name: "Refunds" });
  await userEvent.click(refunds);
  expect(refunds).toHaveFocus();
  expect(screen.getByRole("list")).toBe(list);
  expect(list).toHaveAttribute("aria-busy", "true");
  expect(screen.getByRole("link", { name: "Saved donor" })).toBeVisible();
  expect(screen.getByRole("navigation", { name: "Contributor pages" })).toBe(pages);
  finish(Response.json({ status: "partial", results: [], count: 0, next_cursor: null }));
  await waitFor(() => expect(list).toHaveAttribute("aria-busy", "false"));
  expect(screen.getByRole("list", { name: "Refund records" })).toBe(list);
  expect(screen.getByRole("navigation", { name: "Contributor pages" })).toBe(pages);
  expect(refunds).toHaveFocus();
  const calls = vi.mocked(fetch).mock.calls.length;
  await userEvent.click(refunds);
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
});

it.each([undefined, "Bruce Westerman"])("keeps queued research actionable without starting duplicate jobs (card: %s)", async (cardName) => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...empty, status: "queued", run: { id: "run", status: "queued", sections: {} } })));
  render(<RepresentativeResearch representativeId={12} cardName={cardName} />);
  const label = await screen.findByText("Queued…");
  expect(label).toBeEnabled();
  await userEvent.click(label);
  expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  expect(screen.queryByText("Researching…")).not.toBeInTheDocument();
  expect(screen.queryByText("Finding campaign records…")).not.toBeInTheDocument();
});

it("lets general research recover from a failed status check during collection", async () => {
  let checks = 0;
  vi.stubGlobal("fetch", vi.fn(async () => {
    checks++;
    if (checks === 2) throw new Error("Network interrupted");
    return Response.json({ ...empty, status: checks < 3 ? "running" : "partial", run: { id: "run", status: checks < 3 ? "running" : "partial", sections: {} } });
  }));
  render(<RepresentativeResearch representativeId={1} />);
  await userEvent.click(await screen.findByRole("button", { name: "Researching…" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "Researching…" })).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "Researching…" }));
  expect(await screen.findByRole("button", { name: "Research" })).toBeEnabled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("uses the general research button to refresh an already-open funding panel", async () => {
  let started = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("csrf")) return Response.json({ csrf_token: "test" });
    if (init?.method === "POST") { started = true; return Response.json({ id: "run", status: "partial", sections: {} }); }
    return Response.json({ ...empty, status: "partial", finance_progress: started ? { official_totals: [{ committee: "Campaign", source_url: "https://www.fec.gov/", records: [{ receipts: "1234", disbursements: "10" }] }] } : null });
  }));
  render(<><RepresentativeResearch representativeId={1} cardName="Example" /><RepresentativeResearch representativeId={1} financeView /></>);
  await screen.findByText("No campaign records available for this period.");
  expect(screen.queryByRole("button", { name: "Refresh funding" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Research Example" }));
  expect(await screen.findByText("$1,234.00")).toBeVisible();
});

it("shows official totals and partial contributors while the scan continues", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("contributors")) return Response.json({ status: "collecting", results: [{ id: 1, name: "Example PAC", amount: "125.25", type: "committee", committee: "Campaign", source_url: "https://www.fec.gov/" }], count: 1, next_cursor: null });
    return Response.json({ ...empty, status: "running", snapshot: "draft", run: { id: "run", status: "running", sections: {} }, finance_progress: { collecting: true, pages_loaded: 4, streams_completed: 2, streams_total: 7, totals_loaded: 1, official_totals: [{ committee: "Campaign", source_url: "https://www.fec.gov/", records: [{ receipts: "1200.25", disbursements: "300.50", coverage_start_date: "2025-01-01", coverage_end_date: "2026-06-30" }] }] } });
  }));
  render(<RepresentativeResearch representativeId={1} />);
  expect(await screen.findByText("$1,200.25")).toBeVisible();
  expect(screen.getByText("$300.50")).toBeVisible();
  expect(await screen.findByText("Example PAC")).toBeVisible();
  expect(screen.getByText("Loading campaign overview…")).toBeVisible();
  expect(screen.getByText(/Partial results.*still being collected/)).toBeVisible();
});
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("csrf")) return new Response(JSON.stringify({ csrf_token: "test" }), { status: 200 });
    if (init?.method === "POST") return new Response(JSON.stringify({ detail: "Research is unavailable. Try again." }), { status: 503 });
    return new Response(JSON.stringify(empty), { status: 200 });
  }));
});

it("keeps modal funding concise without losing contributor pages or sources", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("contributors")) {
      const second = new URL(url, "http://localhost").searchParams.get("cursor") === "20";
      return Response.json({ status: "collecting", results: [{ id: second ? 21 : 1, name: second ? "Next donor" : "Example PAC", amount: "125.25", type: "committee", committee: "Campaign", date: "2026-06-01", source_url: "https://www.fec.gov/" }], count: 21, next_cursor: second ? null : 20 });
    }
    return Response.json({ ...empty, status: "partial", snapshot: "draft", biography: { text: "Duplicate biography" }, finance_progress: { official_totals: [{ committee: "Campaign", source_url: "https://www.fec.gov/", records: [{ receipts: "1200.25", disbursements: "300.50" }] }] } });
  }));
  render(<RepresentativeResearch representativeId={1} financeView />);
  expect(await screen.findByText("$1,200.25")).toBeVisible();
  expect(await screen.findByRole("link", { name: "Example PAC" })).toHaveAttribute("href", "https://www.fec.gov/");
  expect(screen.queryByText("Duplicate biography")).not.toBeInTheDocument();
  expect(screen.queryByRole("columnheader", { name: "Campaign committee" })).not.toBeInTheDocument();
  expect(screen.queryByText("Contribution categories ▾")).not.toBeInTheDocument();
  expect(screen.getByText("Updating ⓘ")).toBeVisible();
  expect(screen.getByRole("list", { name: "Contribution records" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Contributions" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(await screen.findByRole("link", { name: "Next donor" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Prev" }));
  expect(await screen.findByRole("link", { name: "Example PAC" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Refunds" }));
  expect(await screen.findByRole("list", { name: "Refund records" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Refunds" })).toHaveAttribute("aria-pressed", "true");
});

it("recovers the Research button after a failed request", async () => {
  render(<RepresentativeResearch representativeId={1} />);
  const button = await screen.findByRole("button", { name: "Research" });
  await userEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent("Research is unavailable");
  await waitFor(() => expect(screen.getByRole("button", { name: "Research" })).toBeEnabled());
});

it("shows stored biography when refresh has failed", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...empty, status: "failed", biography: { text: "A saved biography.", source: { url: "https://www.congress.gov/", attribution: "Congress.gov", license: "", fetched_at: "2026-10-01" } }, run: { id: "x", status: "failed", sections: {}, error: "Research failed. You can retry." } }))));
  render(<RepresentativeResearch representativeId={1} />);
  expect(await screen.findByText("A saved biography.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Refresh research" })).toBeEnabled();
});

it("reloads open connections when refreshed research publishes a new snapshot", async () => {
  let snapshot = "old";
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("csrf")) return Response.json({ csrf_token: "test" });
    if (init?.method === "POST") { snapshot = "new"; return Response.json({ id: "run", status: "partial", sections: {} }); }
    if (url.includes("research-snapshots")) return Response.json({ results: [], count: 0, next_cursor: null });
    if (url.includes("contributors")) return Response.json({ results: [], count: 0, next_cursor: null, status: "partial" });
    if (url.includes("connections")) return Response.json({ notice: snapshot === "old" ? "Older connections" : "Updated connections", finance_status: "partial", donors: [{ id: 1, name: snapshot === "old" ? "Older connections" : "Updated connections", amount: "100", source_url: "https://www.fec.gov/" }], related_representatives: [], bills: [], next_cursor: null, next_donor_cursor: null, next_related_cursor: null });
    return Response.json({ ...empty, status: "partial", snapshot });
  }));
  render(<RepresentativeResearch representativeId={1} />);
  await userEvent.click(await screen.findByRole("button", { name: "Explore connections ▾" }));
  expect(await screen.findByText("Older connections")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Refresh research" }));
  expect(await screen.findByText("Updated connections")).toBeVisible();
  expect(screen.queryByText("Older connections")).not.toBeInTheDocument();
});
