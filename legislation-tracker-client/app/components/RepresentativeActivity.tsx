"use client";
import React from "react";
import Link from "next/link";
import { getRepresentativeTopicActivity, type RepresentativeTopicActivity, type ActivityChannel } from "@/lib/recommendations";
import styles from "./recommendations.module.css";

export interface RepresentativeActivityProps {
  scope: { representativeId: number; congress: number; chamber?: "house" | "senate" };
}
function percent(value: number | null) { return value === null ? "unknown" : `${(100 * value).toFixed(1)}%`; }
function Channel({ name, channel }: { name: string; channel: ActivityChannel }) {
  const shown = channel.topics.slice(0, 5);
  return <section className={styles.channel}><h3>{name}</h3>
    <p>{channel.raw_observation_count} dated bills · {channel.grouped_observation_count} possible repeat-title groups.</p>
    <p>Topic coverage: {percent(channel.raw_tag_coverage?.display ?? null)} of bills; {percent(channel.grouped_tag_coverage?.display ?? null)} of groups.</p>
    {channel.status === "insufficient_history" && <p>Insufficient history for a recurring activity label.</p>}
    {!channel.raw_observation_count && <p>No dated observations in this window.</p>}
    {Boolean(channel.missing_date_count || channel.unknown_session_count) && <p>{channel.missing_date_count} records missing dates; {channel.unknown_session_count} with unknown Congress.</p>}
    {Boolean(channel.withdrawn_count) && <p>{channel.withdrawn_count} withdrawn cosponsorships excluded.</p>}
    <ul className={styles.metrics}>{shown.map(metric => <li key={metric.topic.id}>
      <strong>{metric.topic.name}</strong>{metric.recurring && <span className={styles.badge}>Recurring observed activity</span>}
      <p>{metric.raw.topic_observation_count} tagged bills; fractional share {percent(metric.raw.share)}. After repeat-title grouping: {metric.grouped.topic_observation_count} groups, {percent(metric.grouped.share)} share.</p>
      <div className={styles.examples}>{metric.examples.map(example => <Link key={example.bill_id} href={`/bills/${example.bill_id}`}>{example.bill_number} / {example.session}</Link>)}</div>
    </li>)}</ul>
    {channel.topics.length > 5 && <p>Showing five topics with the largest recorded shares.</p>}
  </section>;
}
export default function RepresentativeActivity({ scope }: RepresentativeActivityProps) {
  const [state, setState] = React.useState<{ id: number; data: RepresentativeTopicActivity | null; error: string } | null>(null);
  const [attempt, retry] = React.useReducer(value => value + 1, 0);
  React.useEffect(() => {
    const controller = new AbortController();
    void getRepresentativeTopicActivity(scope.representativeId, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setState({ id: scope.representativeId, data, error: "" });
    }).catch(error => { if (!controller.signal.aborted && error?.name !== "AbortError") setState({ id: scope.representativeId, data: null, error: "Recorded topic activity could not be loaded." }); });
    return () => controller.abort();
  }, [scope.representativeId, attempt]);
  const data = state?.id === scope.representativeId ? state.data : null;
  const error = state?.id === scope.representativeId ? state.error : "";
  if (error) return <div role="alert" className={styles.activity}>{error} <button className={styles.action} onClick={retry}>Retry activity</button></div>;
  if (!data) return <p role="status" className={styles.activity}>Loading recorded topic activity…</p>;
  return <section className={styles.activity} aria-label="Recorded topic activity">
    <h2>Recorded topic activity</h2>
    <p className={styles.note}>Rolling {data.window.months}-month window starting {data.window.start_date}, through the activity capture on {new Date(data.captured_at).toLocaleString()}. This window is independent of the selected Congress and chamber above.</p>
    <div className={styles.channels}><Channel name="Sponsored bills" channel={data.channels.sponsor} /><Channel name="Active cosponsorships" channel={data.channels.active_cosponsor} /></div>
    <p className={styles.note}>Each bill’s topic weight is divided among its recorded usable tags. A recurring label requires at least {data.policy.minimum_observations} bills and groups, {data.policy.minimum_topic_observations} observations of the topic, {percent(Number(data.policy.topic_share))} fractional share, and {percent(Number(data.policy.minimum_tag_coverage))} tag coverage in both calculations.</p>
    <details><summary>Recorded passage positions, shown separately</summary><p>{data.passage_evidence.yes} yes · {data.passage_evidence.no} no · {data.passage_evidence.present} present · {data.passage_evidence.not_voting} not voting · {data.passage_evidence.other} other.</p>
      <p>{data.passage_evidence.missing_or_uncertain} observed records have missing or uncertain positions. The full eligible-vote denominator and completeness are unknown; an absent record is not a no vote.</p>
      <p>Yes share among known yes/no positions: {percent(data.passage_evidence.yes_rate)}. Procedural votes are excluded. Vote positions are not used for recommendations.</p>
    </details>
    <p className={styles.note}>This is an ingested subset. Exact time in office is unavailable, so no monthly rates are estimated. Repeat-title groups are a sensitivity check; official reintroduction or companion relationships are unavailable. Resolutions are counted separately: {data.resolutions.coverage === "unsupported" ? "no supported resolution history." : `${data.resolutions.joint_count} joint, ${data.resolutions.concurrent_count} concurrent, ${data.resolutions.simple_count} simple.`}</p>
  </section>;
}
