import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import RepresentativeConnections from "@/app/components/RepresentativeConnections";

it("lets keyboard readers switch from the map to sourced, typed relationships", async () => {
  render(<RepresentativeConnections nodes={[
    { id: "representative:1", kind: "representative", label: "Member One", url: "/representatives/1" },
    { id: "bill:2", kind: "bill", label: "Education bill", url: "/bills/2" },
  ]} edges={[
    { id: "vote:1", kind: "recorded_vote", source: "representative:1", target: "bill:2", label: "Motion to table: No", evidence_url: "https://www.senate.gov/vote/1" },
  ]} />);
  expect(screen.getByRole("img", { name: "Recorded connections map" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Evidence list" }));
  expect(screen.getByRole("link", { name: "Motion to table: No" })).toHaveAttribute("href", "https://www.senate.gov/vote/1");
  expect(screen.queryByText(/supports|endorses/i)).not.toBeInTheDocument();
});
