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
