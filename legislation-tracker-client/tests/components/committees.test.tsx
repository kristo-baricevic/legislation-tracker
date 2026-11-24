import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi } from "vitest";
import Committees from "@/app/committees/page";

const committee = { id: 1, name: "Finance", chamber: "senate", parent_name: null, members: [{ role: "chair", rank: 1, representative: { id: 2, name: "Jane Doe", bioguide_id: "", image_url: "", party: "D", state: "NY" } }] };
const bill = { id: 10, title: "Student support", bill_number: "S 10", jurisdiction: "federal", session: 119, topics: [], status: "Introduced", sponsor_id: null, last_action_at: null, card_summary: "Helps students." };
it("waits for first-page bill cards before revealing the heading and filters", async () => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("introduced-bills")) {
      await gate;
      return Response.json({ results: [bill], next: null });
    }
    if (url.includes("/api/topics/")) return Response.json([{ id: 9, name: "Education", slug: "education" }]);
    if (url.includes("/api/auth/")) return new Response(null, { status: 401 });
    return Response.json({ congress: 119, results: [committee], next: null });
  }));
  render(<Committees />);
  expect(await screen.findByRole("status", { name: "Loading committees" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Committees" })).toBeNull();
  expect(screen.queryByRole("search")).toBeNull();
  release();
  expect(await screen.findByRole("link", { name: bill.title })).toBeVisible();
  expect(screen.getByRole("search")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Committees" })).toBeVisible();
});
it("loads topic options and filters both committees and bill rows, then clears", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url:string) => {
    if(url.includes("/api/topics/"))return Response.json([{id:9,name:"Education",slug:"education"}]);
    return Response.json(url.includes("introduced-bills")?{results:[bill],next:null}:{congress:119,results:[committee],next:null});
  }));
  render(<Committees/>);
  await screen.findByRole("option",{name:"Education"});
  await userEvent.selectOptions(screen.getByLabelText("Topic"),"9");
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes("/api/committees/?topic_id=9"))).toBe(true));
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes("introduced-bills/?congress=119&topic_id=9"))).toBe(true));
  await userEvent.click(screen.getByRole("button",{name:"Clear filters"}));
  expect(screen.getByLabelText("Topic")).toHaveValue("");
});
it("combines name, member and level filters and clears them", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url:string) => Response.json(url.includes("introduced-bills") ? {results:[],next:null} : {congress:119,results: url.includes("member=Jane") ? [] : [committee],next:null})));
  render(<Committees/>);
  await screen.findByRole("heading",{name:"Finance"});
  await userEvent.type(screen.getByLabelText("Committee name"),"Finance");
  await userEvent.type(screen.getByLabelText("Member name"),"Jane");
  await userEvent.selectOptions(screen.getByLabelText("Type"),"committee");
  await screen.findByText("No committees found.");
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes("search=Finance")&&String(url).includes("member=Jane")&&String(url).includes("level=committee"))).toBe(true));
  await userEvent.click(screen.getByRole("button",{name:"Clear filters"}));
  expect(screen.getByLabelText("Committee name")).toHaveValue("");
  expect(screen.getByLabelText("Member name")).toHaveValue("");
  await screen.findByRole("heading",{name:"Finance"});
});
it("shows leadership, profile links and bill cards; filters by chamber", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => Response.json(url.includes("introduced-bills") ? { results: [bill], next: null, count: 1 } : { congress:119, results: url.includes("chamber=house") ? [] : [committee], next: null, count: 1 })));
  render(<Committees />);
  expect(await screen.findByRole("heading", { name: "Committees", level: 1 })).toHaveClass("tracker-heading", "text-ink");
  expect(await screen.findByRole("heading", { name: "Finance" })).toBeVisible();
  expect(screen.getByText("Chair")).toBeVisible();
  expect(screen.getByRole("link", { name: "Jane Doe" })).toHaveAttribute("href", "/representatives/2?congress=119");
  expect(await screen.findByRole("link", { name: "Student support" })).toHaveAttribute("href", "/bills/10");
  await userEvent.selectOptions(screen.getByLabelText("Chamber"), "house");
  expect(await screen.findByText("No committees found.")).toBeVisible();
});

it("retains bill cards when the next page fails and appends on retry", async () => {
  let fail = true;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (!url.includes("introduced-bills")) return Response.json({ congress:119, results:[committee], next:null });
    if (url.includes("page=2")) return fail ? Response.json({}, { status:503 }) : Response.json({ results:[{...bill,id:11,title:"Second bill"}],next:null });
    return Response.json({results:[bill],next:"next"});
  }));
  render(<Committees />);
  const first = await screen.findByRole("link", { name:"Student support" });
  await userEvent.click(screen.getByRole("button", { name:"More bills" }));
  await screen.findByRole("button", { name:"Retry bills" });
  expect(first).toBeVisible();
  fail=false;
  await userEvent.click(screen.getByRole("button", { name:"Retry bills" }));
  await waitFor(() => expect(screen.getByRole("link", { name:"Second bill" })).toBeVisible());
  expect(first).toBeVisible();
});
