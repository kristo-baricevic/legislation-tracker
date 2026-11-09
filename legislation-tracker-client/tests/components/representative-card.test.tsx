import { expect, it } from "vitest";
import { topRepresentativeTopics } from "@/lib/representative-card";
import type { RepresentativeTopicActivity } from "@/lib/recommendations";

it("ranks both activity channels, merges duplicate topics, and returns only the top three", () => {
  const metric = (id: number, name: string, count: number) => ({ topic: { id, name }, grouped: { topic_observation_count: count } });
  const activity = { channels: {
    sponsor: { topics: [metric(1, "Health", 4), metric(2, "Education", 8), metric(3, "Energy", 2), metric(4, "Housing", 1), metric(5, "No activity", 0)] },
    active_cosponsor: { topics: [metric(1, "Health", 6), metric(4, "Housing", 7)] },
  } } as RepresentativeTopicActivity;
  expect(topRepresentativeTopics(activity)).toEqual([
    { id: 1, name: "Health", count: 10 },
    { id: 2, name: "Education", count: 8 },
    { id: 4, name: "Housing", count: 8 },
  ]);
  expect(topRepresentativeTopics(null)).toEqual([]);
});
