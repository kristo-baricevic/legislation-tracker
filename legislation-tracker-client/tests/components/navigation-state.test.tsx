import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SiteHeader from "@/app/components/SiteHeader";
import { ReaderTabsProvider, ReaderTabBar, ReaderTabPanel } from "@/app/bills/[id]/reader-tabs";

vi.mock("next/navigation", () => ({ usePathname: () => window.location.pathname, useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }), useSearchParams: () => new URLSearchParams(window.location.search) }));
vi.mock("@/lib/api", () => ({ getSession: async () => null }));
afterEach(() => { window.history.replaceState(null, "", "/"); });

it("marks Bills selected on a bill detail page and removes the theme button", () => {
  window.history.replaceState(null, "", "/bills/463");
  render(<SiteHeader />);
  expect(screen.getByRole("link", { name: "Bills" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  expect(screen.queryByRole("button", { name: /mode/i })).not.toBeInTheDocument();
});

it("opens linked tabs, preserves other query parameters and responds to history navigation", () => {
  window.history.replaceState(null, "", "/bills/463?tab=money&source=dashboard");
  render(<ReaderTabsProvider><ReaderTabBar /><ReaderTabPanel tab="money">Funding</ReaderTabPanel><ReaderTabPanel tab="votes">Voting</ReaderTabPanel></ReaderTabsProvider>);
  expect(screen.getByRole("tab", { name: "Money" })).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("tab", { name: "Votes & sponsor" }));
  expect(new URLSearchParams(window.location.search).get("tab")).toBe("votes");
  expect(new URLSearchParams(window.location.search).get("source")).toBe("dashboard");
  act(() => { window.history.replaceState(null, "", "/bills/463?tab=money"); window.dispatchEvent(new PopStateEvent("popstate")); });
  expect(screen.getByRole("tab", { name: "Money" })).toHaveAttribute("aria-selected", "true");
});
