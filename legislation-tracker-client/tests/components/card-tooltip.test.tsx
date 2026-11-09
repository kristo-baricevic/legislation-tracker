import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it } from "vitest";
import CardTooltip from "@/app/components/CardTooltip";

it("shows a styled, accessible tooltip on focus and dismisses it with Escape", () => {
  render(<CardTooltip text="Similar to Melanie Stansbury"><a href="/representatives/242">MS</a></CardTooltip>);
  const link = screen.getByRole("link");
  expect(link).not.toHaveAttribute("title");
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.focus(link);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Similar to Melanie Stansbury");
  expect(link).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).toBeNull();
});
