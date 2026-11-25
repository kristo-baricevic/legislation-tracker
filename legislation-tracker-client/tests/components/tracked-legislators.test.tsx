import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { it, expect, vi, beforeEach } from "vitest";
import { getRepresentativeTopicActivity, type RepresentativeTopicActivity } from "@/lib/recommendations";
import userEvent from "@testing-library/user-event";
import { getResearch, startResearch } from "@/lib/representative-research";
import TrackedLegislators from "@/app/components/TrackedLegislators";
import { getRepresentativeCard, type TrackedLegislatorItem } from "@/lib/api";
vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), getRepresentativeCard: vi.fn() }));
vi.mock("@/lib/representative-research", () => ({ getResearch: vi.fn().mockResolvedValue({ status: "not_started", biography: null, portrait: null, snapshot: null, run: null }), startResearch: vi.fn() }));
vi.mock("@/lib/recommendations", () => ({ getRepresentativeTopicActivity: vi.fn().mockResolvedValue({ channels: { sponsor: { topics: [{ topic: { id: 9, name: "Education" }, grouped: { topic_observation_count: 12 } }] }, active_cosponsor: { topics: [] } } }) }));
beforeEach(() => {
  const channel = { status: "observed_subset" as const, missing_date_count: 0, unknown_session_count: 0, withdrawn_count: 0, raw_observation_count: 12, grouped_observation_count: 12, raw_tagged_count: 12, grouped_tagged_count: 12, raw_tag_coverage: null, grouped_tag_coverage: null, recurring_topic_ids: [], topics: [] };
  vi.mocked(getRepresentativeTopicActivity).mockResolvedValue({
    schema_version: "representative-topic-activity-v1", policy_version: "test", captured_at: "2026-11-09",
    representative: { id: 242, bioguide_id: "S001218", name: "Melanie Stansbury", chamber: "house", state: "NM", is_current: true },
    window: { start_date: "2024-11-09", end_date_exclusive: "2026-11-09", timezone: "America/New_York", months: 24 },
    policy: { topic_share: "0.20", minimum_observations: 20, minimum_topic_observations: 5, minimum_tag_coverage: "0.80" },
    exposure: { status: "unknown", term_precision: "unknown", service_days: null, monthly_rate: null, reason: "unknown" },
    channels: { sponsor: { ...channel, topics: [{ topic: { id: 9, name: "Education", slug: "education" }, raw: { topic_observation_count: 12, mass: {numerator: "12", denominator: "1"}, share: 1 }, grouped: { topic_observation_count: 12, mass: {numerator: "12", denominator: "1"}, share: 1 }, recurring: false, classification: null, examples: [] }] }, active_cosponsor: channel },
    passage_evidence: { status: "coverage_unknown", missing_eligibility: "unknown", yes: 0, no: 0, present: 0, not_voting: 0, other: 0, selected_bill_count: 0, yes_rate: null, missing_or_uncertain: 0, topics: [], examples: [] },
    resolutions: { coverage: "unsupported", joint_count: null, simple_count: null, concurrent_count: null }, caveats: [],
  });
});

const item: TrackedLegislatorItem = {
  id: 1, created_at: "2026-01-01", representative: { id: 242, bioguide_id: "S001218", name: "Melanie Stansbury", first_name: "Melanie", last_name: "Stansbury", party: "D", state: "NM", district: "1", chamber: "house", image_url: null, official_website_url: null, is_current: true },
  card: { biography: { text: "Works on education.", source: {url: "https://www.congress.gov", attribution: "Congress", license: ""} }, portrait: { url: "https://www.congress.gov/img/member/s001218_200.jpg", source: {url: "https://www.congress.gov", attribution: "Congress", license: ""} }, latest_bill: {id: 22, title: "Education Act", bill_number: "HR 22", session: 119, introduced_at: "2026-01-01"} },
};
it("shows saved profile basics, top topics, party color, and the newest sponsored bill", async () => {
  render(<TrackedLegislators items={[item]} congress={119} />);
  expect(screen.getByText("MS")).toBeVisible();
  fireEvent.load(screen.getByRole("img", {name: "Melanie Stansbury"}));
  expect(screen.getByRole("img", {name: "Melanie Stansbury"})).toBeVisible();
  expect(screen.getByText("Works on education.")).toBeVisible();
  expect(screen.getByText(/Democrat/)).toBeVisible();
  expect(screen.getByRole("link", { name: "HR 22" })).toHaveAttribute("href", "/bills/22");
  fireEvent.focus(screen.getByRole("link", { name: "HR 22" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent("Education Act");
  fireEvent.blur(screen.getByRole("link", { name: "HR 22" }));
  expect(screen.getByRole("link", {name: "Melanie Stansbury"})).toHaveAttribute("href", "/representatives/242?congress=119");
  expect(screen.getByRole("article")).toHaveAttribute("data-party", "democrat");
  expect(await screen.findByRole("link", { name: "Education" })).toHaveAttribute("href", "/bills?topic_id=9");
  fireEvent.error(screen.getByRole("img"));
  expect(screen.queryByRole("img")).toBeNull();
});
it("offers a directory link with no tracked legislators", () => {
  render(<TrackedLegislators items={[]} congress={119} />);
  expect(screen.getByRole("link", {name: "Find representatives"})).toHaveAttribute("href", "/representatives");
});
it("renders a complete tracked card without any detail requests", async () => {
  render(<TrackedLegislators items={[{...item, card: {...item.card!, top_topics: [{id: 9, name: "Education", count: 12}], research: {status: "succeeded", period: 2026, overview_ready: true}}}]} congress={119} />);
  expect(await screen.findByRole("link", {name: "Education"})).toBeVisible();
  expect(screen.getByText("Works on education.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Refresh research for Melanie Stansbury" })).toHaveTextContent("Refresh research");
  expect(getRepresentativeCard).not.toHaveBeenCalled();
  expect(getRepresentativeTopicActivity).not.toHaveBeenCalled();
  expect(getResearch).not.toHaveBeenCalled();
});
it("researches a representative and updates the card biography without a reload", async () => {
  vi.mocked(startResearch).mockResolvedValue({ id: "research-1", status: "queued", sections: {} });
  render(<TrackedLegislators items={[item]} congress={119} />);
  const button = await screen.findByRole("button", { name: "Refresh research for Melanie Stansbury" });
  vi.mocked(getRepresentativeCard).mockResolvedValue({...item.card!, biography: {...item.card!.biography!, text: "New saved biography."}, research: {status: "succeeded", period: 2026, overview_ready: true}});
  await userEvent.click(button);
  expect(startResearch).toHaveBeenCalledWith(242, expect.any(Number), expect.any(AbortSignal), true);
  expect(await screen.findByText("New saved biography.")).toBeVisible();
  expect(screen.queryByText("Works on education.")).not.toBeInTheDocument();
  expect(button).toBeEnabled();
});
