import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import RepresentativeAvatar from "@/app/representatives/representative-avatar";
import RepresentativeAvatarBadge from "@/app/components/RepresentativeAvatarBadge";
import { representativeInitials } from "@/lib/representative-name";

it.each([
  ["Rep. Mackenzie, Ryan [R-PA-7] (PA-house)", "RM"],
  ["Ryan Mackenzie", "RM"],
  ["Sen. Britt, Katie Boyd [R-AL]", "KB"],
  ["Rep. Smith, John, Jr. [D-NY-1]", "JS"],
  ["Ocasio-Cortez, Alexandria", "AO"],
])("uses name initials for %s", (name, expected) => {
  expect(representativeInitials(name)).toBe(expected);
});

it("shows Ryan Mackenzie's initials when a badge has no picture or its picture fails", async () => {
  const name = "Rep. Mackenzie, Ryan [R-PA-7] (PA-house)";
  const { rerender } = render(<RepresentativeAvatarBadge id={8} name={name} notes={[]} representative={{ bioguide_id: "" }} />);
  expect(screen.getByRole("link", { name })).toHaveTextContent("RM");
  rerender(<RepresentativeAvatarBadge id={8} name={name} notes={[]} representative={{ bioguide_id: "M000001" }} />);
  fireEvent.error(await screen.findByRole("img", { name }));
  expect(screen.getByRole("link", { name })).toHaveTextContent("RM");
});

it("links portrait, fallback initials, and name to the full profile", () => {
  render(<RepresentativeAvatar congress={119} rep={{ id: 8, bioguide_id: "R000001", name: "Representative Example", first_name: "Representative", last_name: "Example", party: "I", state: "NY", chamber: "house", district: "12", image_url: "https://www.congress.gov/img/member/r000001_200.jpg", official_website_url: null, is_current: true }} />);
  const portrait = screen.getByRole("link", { name: "View Representative Example profile" });
  const name = screen.getByRole("link", { name: "Representative Example" });
  expect(portrait).toHaveAttribute("href", "/representatives/8?congress=119");
  expect(name).toHaveAttribute("href", "/representatives/8?congress=119");
  fireEvent.error(screen.getByRole("img"));
  expect(portrait).toHaveTextContent("RE");
  expect(portrait).toHaveAttribute("href", "/representatives/8?congress=119");
});
