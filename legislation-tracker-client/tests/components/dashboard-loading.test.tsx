import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import DashboardLoading, { useDashboardLoading } from "@/app/components/DashboardLoading";

function Section({ name, loading }: { name: string; loading: boolean }) {
  useDashboardLoading(name, loading);
  return <h2>{name}</h2>;
}
function Dashboard({ followed, bills, representatives }: { followed: boolean; bills: boolean; representatives: boolean }) {
  return <DashboardLoading>
    <Section name="Following" loading={followed} />
    <Section name="Bills to discover" loading={bills} />
    <Section name="Representatives to discover" loading={representatives} />
  </DashboardLoading>;
}
afterEach(() => vi.useRealTimers());

it("uses one spinner and reveals all rows only when the slowest section settles", () => {
  vi.useFakeTimers();
  const { rerender } = render(<Dashboard followed bills representatives />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  act(() => vi.advanceTimersByTime(250));
  expect(screen.getAllByRole("status")).toHaveLength(1);
  rerender(<Dashboard followed={false} bills={false} representatives />);
  expect(screen.getByText("Following")).not.toBeVisible();
  expect(screen.getByText("Bills to discover")).not.toBeVisible();
  act(() => vi.advanceTimersByTime(500));
  expect(screen.getByRole("status", { name: "Loading dashboard" })).toBeVisible();
  rerender(<Dashboard followed={false} bills={false} representatives={false} />);
  expect(screen.getByText("Following")).toBeVisible();
  expect(screen.getByText("Representatives to discover")).toBeVisible();
  act(() => vi.runOnlyPendingTimers());
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  rerender(<Dashboard followed={false} bills representatives />);
  act(() => vi.advanceTimersByTime(250));
  expect(screen.getByRole("status")).toBeVisible();
  rerender(<Dashboard followed={false} bills={false} representatives />);
  expect(screen.getByText("Bills to discover")).not.toBeVisible();
  expect(screen.getByRole("status")).toBeVisible();
  rerender(<Dashboard followed={false} bills={false} representatives={false} />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByText("Bills to discover")).toBeVisible();
});

it("does not flash a spinner when all rows finish quickly", () => {
  vi.useFakeTimers();
  const { rerender } = render(<Dashboard followed bills representatives />);
  act(() => vi.advanceTimersByTime(100));
  rerender(<Dashboard followed={false} bills={false} representatives={false} />);
  act(() => vi.advanceTimersByTime(500));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByText("Following")).toBeVisible();
});
