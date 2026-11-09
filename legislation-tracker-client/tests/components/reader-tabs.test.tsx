import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { ReaderTabsProvider, ReaderTabBar, ReaderTabPanel } from "@/app/bills/[id]/reader-tabs";
import { SourcePopover } from "@/app/bills/[id]/source-popover";

it("keeps the summary visible and preserves money filters across keyboard tab switches", async () => {
  const user = userEvent.setup();
  render(<ReaderTabsProvider><h2>Bill summary</h2><ReaderTabBar />
    <ReaderTabPanel tab="changes">Changes here</ReaderTabPanel>
    <ReaderTabPanel tab="money"><input aria-label="Money search" /></ReaderTabPanel>
  </ReaderTabsProvider>);
  await user.click(screen.getByRole("tab", { name: "Money" }));
  await user.type(screen.getByRole("textbox"), "grants");
  await user.click(screen.getByRole("tab", { name: "What changes" }));
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
