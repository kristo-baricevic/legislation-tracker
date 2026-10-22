import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import RepresentativeResearch from "@/app/components/RepresentativeResearch";

const empty = { status: "not_started", period: 2026, run: null, biography: null, portrait: null, snapshot: null };
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

it("selects saved finance history and independently filters legislative dates", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const path = new URL(url, "http://localhost");
    if (path.pathname.endsWith("research-snapshots/")) return Response.json({ count: 1, next_cursor: null, results: [{ id: "old", published_at: "2026-01-01T12:00:00Z", active: false, coverage: "partial" }] });
    if (path.pathname.endsWith("connections/")) return Response.json({ notice: "Recorded activity, not endorsement.", finance_status: "partial", count: 1, next_cursor: null, next_donor_cursor: null, next_related_cursor: null, donors: [], related_representatives: [], bills: [{ id: 2, number: "HR 2", title: path.searchParams.get("snapshot") === "old" && path.searchParams.get("legislative_start") === "2024-01-01" ? "Earlier activity" : "Current activity", relations: ["Sponsored"], votes: [], topics: [] }] });
    return Response.json(empty);
  }));
  render(<RepresentativeResearch representativeId={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Explore connections ▾" }));
  expect(await screen.findByText("HR 2: Current activity")).toBeVisible();
  await userEvent.selectOptions(await screen.findByLabelText("Finance snapshot"), "old");
  await userEvent.clear(screen.getByLabelText("Legislative start"));
  await userEvent.type(screen.getByLabelText("Legislative start"), "2024-01-01");
  await userEvent.clear(screen.getByLabelText("Legislative end"));
  await userEvent.type(screen.getByLabelText("Legislative end"), "2024-12-31");
  await userEvent.click(screen.getByRole("button", { name: "Apply dates" }));
  expect(await screen.findByText("HR 2: Earlier activity")).toBeVisible();
  expect(screen.queryByText("HR 2: Current activity")).not.toBeInTheDocument();
});
