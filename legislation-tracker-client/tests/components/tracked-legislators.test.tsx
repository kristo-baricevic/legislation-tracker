import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { it, expect } from "vitest";
import TrackedLegislators from "@/app/components/TrackedLegislators";
import type { TrackedLegislatorItem } from "@/lib/api";

const item: TrackedLegislatorItem = {
  id: 1, created_at: "2026-01-01", representative: { id: 242, bioguide_id: "S001218", name: "Melanie Stansbury", first_name: "Melanie", last_name: "Stansbury", party: "D", state: "NM", district: "1", chamber: "house", image_url: null, official_website_url: null, is_current: true },
  card: { biography: { text: "Works on education.", source: {url: "https://www.congress.gov", attribution: "Congress", license: ""} }, portrait: { url: "https://www.congress.gov/img/member/s001218_200.jpg", source: {url: "https://www.congress.gov", attribution: "Congress", license: ""} }, latest_bill: {id: 22, title: "Education Act", bill_number: "HR 22", session: 119, introduced_at: "2026-01-01"} },
};
it("shows saved profile basics, party color, and the newest sponsored bill", () => {
  render(<TrackedLegislators items={[item]} congress={119} />);
  expect(screen.getByRole("img", {name: "Melanie Stansbury"})).toBeVisible();
  expect(screen.getByText("Works on education.")).toBeVisible();
  expect(screen.getByText(/Democrat/)).toBeVisible();
  expect(screen.getByRole("link", { name: "HR 22 · Education Act" })).toHaveAttribute("href", "/bills/22");
  expect(screen.getByRole("link", {name: "Melanie Stansbury"})).toHaveAttribute("href", "/representatives/242?congress=119");
  expect(screen.getByRole("article")).toHaveAttribute("data-party", "democrat");
  fireEvent.error(screen.getByRole("img"));
  expect(screen.queryByRole("img")).toBeNull();
});
it("offers a directory link with no tracked legislators", () => {
  render(<TrackedLegislators items={[]} congress={119} />);
  expect(screen.getByRole("link", {name: "Find representatives"})).toHaveAttribute("href", "/representatives");
});
