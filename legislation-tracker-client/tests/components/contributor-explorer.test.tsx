import React from "react";
import { render, screen, act, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import ContributorExplorer from "@/app/components/ContributorExplorer";

it("hides the previous page after a failed next-page request and retries the requested page", async () => {
  let fail = true;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const offset = Number(new URL(url).searchParams.get("donor_cursor"));
    if (offset && fail) return new Response("unavailable", { status: 503 });
    return Response.json({ finance_status: "partial", donor_count: 21, related_count: 0, count: 0,
      next_cursor: null, next_donor_cursor: offset ? null : 20, next_related_cursor: null, bills: [], related_representatives: [],
      donors: [{ id: offset + 1, name: `PAC ${offset + 1}`, amount: "100", source_url: "https://www.fec.gov/" }] });
  }));
  render(<ContributorExplorer representativeId={1} period={2026} />);
  await screen.findByRole("button", { name: "PAC 1" });
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "PAC 1" })).not.toBeInTheDocument();
  expect(screen.queryByText(/21–21 of/)).not.toBeInTheDocument();
  fail = false;
  await userEvent.click(screen.getByRole("button", { name: "Retry connections" }));
  expect(await screen.findByRole("button", { name: "PAC 21" })).toBeVisible();
});

it("never attributes old recipients to a newly selected donor when loading fails", async () => {
  let fail = true;
  const donors = [1, 2].map(id => ({ id, name: `PAC ${id}`, amount: "100", source_url: "https://www.fec.gov/" }));
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const selected = new URL(url).searchParams.get("contributor");
    if (selected === "2" && fail) return new Response("unavailable", { status: 503 });
    return Response.json({ finance_status: "partial", donors, donor_count: 2, related_count: 1, count: 0,
      next_cursor: null, next_donor_cursor: null, next_related_cursor: null, bills: [],
      related_representatives: selected ? [{ id: Number(selected), name: `Recipient ${selected}`, amount: "100", source_url: "https://www.fec.gov/" }] : [] });
  }));
  render(<ContributorExplorer representativeId={1} period={2026} />);
  await userEvent.click(await screen.findByRole("button", { name: "PAC 1" }));
  await screen.findByRole("button", { name: "Recipient 1" });
  await userEvent.click(screen.getByRole("button", { name: "PAC 2" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "Recipient 1" })).not.toBeInTheDocument();
  fail = false;
  await userEvent.click(screen.getByRole("button", { name: "Retry connections" }));
  expect(await screen.findByRole("button", { name: "Recipient 2" })).toBeVisible();
});

it("keeps the selected contributor and controls stable during a background update", async () => {
  let pending = false;
  let finish: ((value: Response) => void) | undefined;
  const data = { finance_status: "collecting", donor_count: 1, related_count: 1, count: 0, next_cursor: null, next_donor_cursor: null, next_related_cursor: null, donors: [{ id: 9, name: "Education PAC", amount: "5000", source_url: "https://www.fec.gov/" }], related_representatives: [{ id: 2, name: "Jane Doe", amount: "5000", source_url: "https://www.fec.gov/" }], bills: [] };
  vi.stubGlobal("fetch", vi.fn(async () => pending ? new Promise<Response>(resolve => { finish = resolve; }) : Response.json(data)));
  const view = render(<ContributorExplorer representativeId={1} period={2026} refreshToken="1" />);
  await userEvent.click(await screen.findByRole("button", { name: "Education PAC" }));
  await screen.findByRole("button", { name: "Jane Doe" });
  pending = true;
  view.rerender(<ContributorExplorer representativeId={1} period={2026} refreshToken="2" />);
  expect(screen.getByRole("button", { name: "Jane Doe" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Education PAC" })).toBeEnabled();
  expect(screen.queryByText("Loading connections…")).not.toBeInTheDocument();
  await act(async () => { finish!(Response.json(data)); });
  expect(within(screen.getByRole("navigation", { name: "Contributor connections pages" })).queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
});

it("shows bills only after selecting a contributor and a representative", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => Response.json({
    finance_status: "partial", donor_count: 1, related_count: 1, count: 1,
    next_cursor: null, next_donor_cursor: null, next_related_cursor: null,
    donors: [{ id: 9, name: "Education PAC", amount: "5000", source_url: "https://www.fec.gov/" }],
    related_representatives: url.includes("contributor=9") ? [{ id: 2, name: "Jane Doe", amount: "5000", source_url: "https://www.fec.gov/", snapshot: "saved" }] : [],
    bills: [{ id: 3, number: "HR 3", title: "Education bill", relations: ["Sponsored"], votes: [], topics: [{ id: 1, name: "Education" }] }],
  })));
  render(<ContributorExplorer representativeId={1} period={2026} />);
  await screen.findByRole("button", { name: "Education PAC" });
  expect(screen.queryByText("HR 3: Education bill")).not.toBeInTheDocument();
  expect(screen.queryByRole("img", { name: "Recorded connections map" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Education PAC" }));
  await userEvent.click(await screen.findByRole("button", { name: "Jane Doe" }));
  expect(await screen.findByRole("link", { name: "HR 3: Education bill" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Close activity" }));
  expect(screen.queryByRole("link", { name: "HR 3: Education bill" })).not.toBeInTheDocument();
});

it("does not show ordinary bills as donor connections when finance is missing", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ finance_status: "not_researched", donors: [], donor_count: 0, related_representatives: [], bills: [{ id: 3, title: "Unrelated bill" }], next_donor_cursor: null })));
  render(<ContributorExplorer representativeId={1} period={2026} />);
  expect(await screen.findByText("No campaign contribution data has been saved yet.")).toBeVisible();
  expect(screen.queryByText("Unrelated bill")).not.toBeInTheDocument();
});

it("moves forward and backward when there is more than one contributor page", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const offset = Number(new URL(url).searchParams.get("donor_cursor"));
    return Response.json({ finance_status: "partial", donor_count: 21, related_count: 0, count: 0, next_cursor: null, next_donor_cursor: offset === 0 ? 20 : null, next_related_cursor: null,
      donors: Array.from({ length: offset === 0 ? 20 : 1 }, (_, n) => ({ id: offset + n + 1, name: `PAC ${offset + n + 1}`, amount: "10", source_url: "https://www.fec.gov/" })), related_representatives: [], bills: [] });
  }));
  render(<ContributorExplorer representativeId={1} period={2026} />);
  await screen.findByRole("button", { name: "PAC 1" });
  const pagination = () => within(screen.getByRole("navigation", { name: "Contributor connections pages" }));
  await userEvent.click(pagination().getByRole("button", { name: "Next" }));
  expect(await screen.findByRole("button", { name: "PAC 21" })).toBeVisible();
  expect(pagination().getByRole("button", { name: "Next" })).toBeDisabled();
  await userEvent.click(pagination().getByRole("button", { name: "Prev" }));
  expect(await screen.findByRole("button", { name: "PAC 1" })).toBeVisible();
});
