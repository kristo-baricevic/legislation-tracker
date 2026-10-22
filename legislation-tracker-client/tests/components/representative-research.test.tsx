import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import RepresentativeResearch from "@/app/components/RepresentativeResearch";

const empty = { status: "not_started", period: 2026, run: null, biography: null, portrait: null, snapshot: null };

it("shows official totals and partial contributors while the scan continues", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("contributors")) return Response.json({ status: "collecting", results: [{ id: 1, name: "Example PAC", amount: "125.25", type: "committee", committee: "Campaign", source_url: "https://www.fec.gov/" }], count: 1, next_cursor: null });
    return Response.json({ ...empty, status: "running", snapshot: "draft", run: { id: "run", status: "running", sections: {} }, finance_progress: { collecting: true, pages_loaded: 4, streams_completed: 2, streams_total: 7, totals_loaded: 1, official_totals: [{ committee: "Campaign", source_url: "https://www.fec.gov/", records: [{ receipts: "1200.25", disbursements: "300.50", coverage_start_date: "2025-01-01", coverage_end_date: "2026-06-30" }] }] } });
  }));
  render(<RepresentativeResearch representativeId={1} />);
  expect(await screen.findByText("$1,200.25")).toBeVisible();
  expect(screen.getByText("$300.50")).toBeVisible();
  expect(await screen.findByText("Example PAC")).toBeVisible();
  expect(screen.getByText(/4 pages loaded/)).toBeVisible();
  expect(screen.getByText(/Partial results.*still being collected/)).toBeVisible();
});
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("csrf")) return new Response(JSON.stringify({ csrf_token: "test" }), { status: 200 });
    if (init?.method === "POST") return new Response(JSON.stringify({ detail: "Research is unavailable. Try again." }), { status: 503 });
    return new Response(JSON.stringify(empty), { status: 200 });
  }));
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
