import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(window.location.search) }));
afterEach(() => window.history.replaceState(null, "", "/"));
import { ReaderTabsProvider, ReaderTabBar, ReaderTabPanel, useReaderTabs } from "@/app/bills/[id]/reader-tabs";
import { SourcePopover } from "@/app/bills/[id]/source-popover";

it("keeps the summary visible and preserves money filters across keyboard tab switches", async () => {
  const user = userEvent.setup();
  render(<ReaderTabsProvider><h2>Bill summary</h2><ReaderTabBar />
    <ReaderTabPanel tab="changes">Changes here</ReaderTabPanel>
    <ReaderTabPanel tab="money"><input aria-label="Money search" /></ReaderTabPanel>
  </ReaderTabsProvider>);
  await user.click(screen.getByRole("tab", { name: "Money" }));
  await user.type(screen.getByRole("textbox"), "grants");
  await user.click(screen.getByRole("tab", { name: "What this bill does" }));
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("textbox")).toHaveValue("grants");
  expect(screen.getByRole("heading", { name: "Bill summary" })).toBeVisible();
});

it("opens numbered evidence and dismisses it with Escape or an outside click", async () => {
  const user = userEvent.setup();
  render(<><button>Outside</button><SourcePopover number={2}><blockquote>Exact legal text</blockquote><a href="/documents/4?start=10&end=30">Read in bill</a></SourcePopover></>);
  const trigger = screen.getByRole("button", { name: "Source 2" });
  await user.click(trigger);
  expect(screen.getByRole("dialog")).toHaveTextContent("Exact legal text");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  await user.click(trigger);
  await user.click(screen.getByRole("button", { name: "Outside" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps parent glossary evidence open while a nested source is used", async () => {
  const user = userEvent.setup();
  const loadMore = vi.fn();
  render(<SourcePopover label="Definition"><p>Legal definition</p><SourcePopover label="Exact passage"><button onClick={loadMore}>More evidence</button></SourcePopover></SourcePopover>);
  await user.click(screen.getByRole("button", { name: "Definition" }));
  const nestedTrigger = screen.getByRole("button", { name: "Exact passage" });
  await user.click(nestedTrigger);
  await user.click(screen.getByRole("button", { name: "More evidence" }));
  expect(loadMore).toHaveBeenCalledOnce();
  expect(screen.getAllByRole("dialog")).toHaveLength(2);
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog", { name: "Definition" })).toBeVisible();
  expect(screen.queryByRole("dialog", { name: "Exact passage" })).not.toBeInTheDocument();
  expect(nestedTrigger).toHaveFocus();
});

it("returns keyboard navigation to the citation rather than the end of the document", async () => {
  const user = userEvent.setup();
  render(<><SourcePopover><a href="#text">Read full source</a></SourcePopover><button>Following action</button></>);
  await user.click(screen.getByRole("button", { name: "Source 1" }));
  await user.tab(); // close button
  await user.tab(); // source link
  expect(screen.getByRole("link")).toHaveFocus();
  await user.tab();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Following action" })).toHaveFocus();
});

it("moves focus out of a hidden tab and removes its portalled source", async () => {
  const user = userEvent.setup();
  function Jump() { const nav = useReaderTabs(); return <button onClick={() => nav?.select("money")}>Show related money</button>; }
  render(<ReaderTabsProvider><ReaderTabBar /><ReaderTabPanel tab="changes"><SourcePopover><Jump /></SourcePopover></ReaderTabPanel><ReaderTabPanel tab="money">Related funds</ReaderTabPanel></ReaderTabsProvider>);
  await user.click(screen.getByRole("button", { name: "Source 1" }));
  await user.click(screen.getByRole("button", { name: "Show related money" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Money" })).toHaveFocus();
});

it("dismisses a detached source when the page scrolls, but not when its evidence scrolls", async () => {
  const user = userEvent.setup();
  render(<SourcePopover><p>Long evidence</p></SourcePopover>);
  await user.click(screen.getByRole("button", { name: "Source 1" }));
  fireEvent.scroll(screen.getByRole("dialog"));
  expect(screen.getByRole("dialog")).toBeVisible();
  fireEvent.scroll(window); // queued scroll without anchor movement
  expect(screen.getByRole("dialog")).toBeVisible();
  const anchor = screen.getByRole("button", { name: "Source 1" });
  vi.spyOn(anchor, "getBoundingClientRect").mockReturnValue({ top: -100, left: 0 } as DOMRect);
  fireEvent.scroll(window);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
