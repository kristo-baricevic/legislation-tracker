import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import LoadingSpinner from "@/app/components/LoadingSpinner";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

it("never shows feedback for a fast request", () => {
  const view = render(<LoadingSpinner active label="Loading representatives…" />);
  advance(200);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  view.rerender(<LoadingSpinner active={false} />);
  advance(1000);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("delays feedback but removes it immediately when content is ready", () => {
  const view = render(<LoadingSpinner active />);
  advance(249);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  advance(1);
  expect(screen.getByRole("status")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("");
  advance(100);
  view.rerender(<LoadingSpinner active={false} />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("does not reuse a previous request's visible spinner for a fast refresh", () => {
  const view = render(<LoadingSpinner active />);
  advance(250);
  view.rerender(<LoadingSpinner active={false} />);
  advance(200);
  view.rerender(<LoadingSpinner active />);
  advance(100);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  view.rerender(<LoadingSpinner active={false} />);
  advance(0);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
