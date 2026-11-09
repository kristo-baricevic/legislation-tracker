import type { RepresentativeTopicActivity } from "./recommendations";

export function topRepresentativeTopics(activity?: RepresentativeTopicActivity | null) {
  const topics = new Map<number, { id: number; name: string; count: number }>();
  for (const channel of [activity?.channels.sponsor, activity?.channels.active_cosponsor]) {
    for (const metric of channel?.topics ?? []) {
      const count = metric.grouped.topic_observation_count;
      if (count <= 0) continue;
      const previous = topics.get(metric.topic.id);
      topics.set(metric.topic.id, { id: metric.topic.id, name: metric.topic.name, count: (previous?.count ?? 0) + count });
    }
  }
  return [...topics.values()].sort((a, b) => b.count - a.count || a.id - b.id).slice(0, 3);
}
