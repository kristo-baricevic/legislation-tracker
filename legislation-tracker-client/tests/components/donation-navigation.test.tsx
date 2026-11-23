import React from "react";
import { render, screen } from "@testing-library/react";
import { it, expect, vi } from "vitest";
import DonationPie from "@/app/components/DonationPie";
vi.mock("@/lib/representative-research", () => ({ getDonationSizes: () => new Promise(() => {}) }));
it.each([[2024, "2024"], [0, "all"]])("links donation records to funding and period %s", (period, query) => {
  render(<DonationPie representativeId={12} period={period} snapshot="saved" refreshToken="" />);
  expect(screen.getByRole("link", { name: "View records" })).toHaveAttribute("href", `/representatives/12?tab=funding&period=${query}`);
});
