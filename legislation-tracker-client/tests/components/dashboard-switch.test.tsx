import React from "react";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import DashboardSwitch from "@/app/components/DashboardSwitch";
import { DASHBOARD_FLAG_KEY, readDashboardFlag } from "@/lib/dashboard-flag";

vi.mock("@/app/components/Dashboard", () => ({ default: () => <h1>Existing operations dashboard</h1> }));
vi.mock("@/app/components/BillDeck", () => ({ default: () => <h1>New bill cards</h1> }));
beforeEach(() => localStorage.clear());
afterEach(cleanup);
describe("local dashboard flag", () => {
  it("defaults to the new dashboard and persists explicit rollback across remounts", async () => {
    const user = userEvent.setup();
    const view = render(<DashboardSwitch />);
    expect(await screen.findByText("New bill cards")).toBeInTheDocument();
    expect(localStorage.getItem(DASHBOARD_FLAG_KEY)).toBe("true");
    await user.click(screen.getByRole("checkbox"));
    expect(localStorage.getItem(DASHBOARD_FLAG_KEY)).toBe("false");
    expect(screen.getByText("Existing operations dashboard")).toBeInTheDocument();
    view.unmount(); render(<DashboardSwitch />);
    expect(await screen.findByText("Existing operations dashboard")).toBeInTheDocument();
    expect(screen.queryByText("New bill cards")).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox"));
    expect(localStorage.getItem(DASHBOARD_FLAG_KEY)).toBe("true");
    expect(screen.getByText("New bill cards")).toBeInTheDocument();
  });
  it("respects stored false from the first mount and syncs storage changes", async () => {
    localStorage.setItem(DASHBOARD_FLAG_KEY, "false"); render(<DashboardSwitch />);
    expect(await screen.findByText("Existing operations dashboard")).toBeInTheDocument();
    localStorage.removeItem(DASHBOARD_FLAG_KEY);
    window.dispatchEvent(new StorageEvent("storage", { key: DASHBOARD_FLAG_KEY }));
    await waitFor(() => expect(screen.getByText("New bill cards")).toBeInTheDocument());
  });
  it("handles denied local storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    expect(readDashboardFlag()).toBe(true);
  });
});
