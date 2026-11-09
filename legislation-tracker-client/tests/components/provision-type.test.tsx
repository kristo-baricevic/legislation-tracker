import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { ProvisionType } from "@/app/bills/[id]/provision-type";

it("explains a provision type on hover without adding text to the row", async () => {
  const user = userEvent.setup();
  render(<ProvisionType action="set_aside" />);
  expect(screen.getByText("Set-aside")).toBeVisible();
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  const icon = screen.getByRole("button", { name: "What does Set-aside mean?" });
  await user.hover(icon);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Money reserved for a specific purpose or group.");
  expect(icon).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
  await user.unhover(icon);
  await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
});

it("supports keyboard focus, Escape, tap, and outside dismissal", async () => {
  const user = userEvent.setup();
  render(<ProvisionType action="limitation" />);
  await user.tab();
  expect(screen.getByRole("tooltip")).toHaveTextContent("A cap or restriction");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "What does Limitation mean?" }));
  expect(screen.getByRole("tooltip")).toBeVisible();
  await user.click(document.body);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
