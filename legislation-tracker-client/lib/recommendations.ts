import { authGet, publicGet, type BillListItem, type PersonalizedRequestOptions } from "./api";

export type RecommendationEmptyReason = "no_follows" | "unsupported_follows_only" | "insufficient_metadata" | "no_matches";
export type BillRecommendationReason =
  | { kind: "followed_topic"; topic_id: number; name: string }
  | { kind: "followed_bill_topic"; topic_id: number; name: string; seed_bill_id: number; seed_bill_number: string; seed_session: number }
  | { kind: "followed_representative"; representative_id: number; name: string; relation: "sponsor" | "cosponsor" }
  | { kind: "followed_bill_sponsor"; representative_id: number; name: string; relation: "sponsor"; seed_bill_id: number; seed_bill_number: string; seed_session: number };
export interface BillRecommendation { bill: BillListItem; score: number; reasons: BillRecommendationReason[] }
export interface BillRecommendationsPage {
  algorithm: string; generated_at: string; count: number; next_cursor: string | null;
  candidate_pool_truncated: boolean; ranking_limit_reached: boolean;
  empty_reason: RecommendationEmptyReason | null; unsupported_follow_types: string[];
  results: BillRecommendation[];
}
export interface ActivityTopic { id: number; name: string; slug: string }
export interface ExactFraction { numerator: string; denominator: string }
export interface ActivityExample {
  bill_id: number; bill_number: string; session: number; event_date: string;
  source_kind: string; source_url: string | null;
}
export interface ActivityTopicMetric {
  topic: ActivityTopic;
  raw: { topic_observation_count: number; mass: ExactFraction; share: number | null };
  grouped: { topic_observation_count: number; mass: ExactFraction; share: number | null };
  recurring: boolean; classification: "recurring_observed_activity" | null; examples: ActivityExample[];
}
export interface ActivityChannel {
  status: "no_dated_observations" | "insufficient_history" | "observed_subset";
  missing_date_count: number; unknown_session_count: number; withdrawn_count: number;
  raw_observation_count: number; grouped_observation_count: number;
  raw_tagged_count: number; grouped_tagged_count: number;
  raw_tag_coverage: { fraction: ExactFraction; display: number } | null;
  grouped_tag_coverage: { fraction: ExactFraction; display: number } | null;
  topics: ActivityTopicMetric[]; recurring_topic_ids: number[];
}
export interface PassageCounts {
  yes: number; no: number; present: number; not_voting: number; other: number;
  selected_bill_count: number; yes_rate: number | null; missing_or_uncertain: number;
}
export interface RepresentativeTopicActivity {
  schema_version: "representative-topic-activity-v1"; policy_version: string;
  representative: { id: number; bioguide_id: string; name: string; chamber: string; state: string; is_current: boolean };
  captured_at: string;
  window: { start_date: string; end_date_exclusive: string; timezone: string; months: number };
  policy: { topic_share: string; minimum_observations: number; minimum_topic_observations: number; minimum_tag_coverage: string };
  exposure: { status: "unknown"; term_precision: "year_derived" | "unknown"; service_days: null; monthly_rate: null; reason: string };
  channels: { sponsor: ActivityChannel; active_cosponsor: ActivityChannel };
  passage_evidence: PassageCounts & {
    status: "coverage_unknown"; missing_eligibility: "unknown"; cross_chamber_history_count?: number;
    topics: Array<PassageCounts & { topic: ActivityTopic }>;
    examples: Array<ActivityExample & { vote_id: number; question: string; position: string; cross_chamber_history?: boolean }>;
  };
  resolutions: { coverage: "observed_subset" | "unsupported"; joint_count: number | null; concurrent_count: number | null; simple_count: number | null };
  caveats: string[];
}
export type RepresentativeRecommendationReason =
  | { kind: "followed_topic"; topic_id: number; name: string; shared_topics: ActivityTopic[]; channel_evidence: Record<string, unknown> }
  | { kind: "followed_representative_activity"; representative_id: number; name: string; shared_topics: ActivityTopic[]; channel_evidence: Record<string, unknown> };
export interface RepresentativeRecommendation {
  representative_id: number; bioguide_id: string; name: string; score: number;
  reasons: RepresentativeRecommendationReason[]; topic_activity_evidence: RepresentativeTopicActivity;
}
export interface RepresentativeRecommendationsResponse {
  algorithm: string; policy_version: string | null; generated_at: string; activity_as_of: string | null;
  count: number; empty_reason: RecommendationEmptyReason | null; unsupported_follow_types: string[];
  coverage: { status: "ingested_subset"; service_exposure: "unknown"; bill_families: "unavailable"; votes_used_for_ranking: false };
  results: RepresentativeRecommendation[];
}
export function getBillRecommendations(params: { cursor?: string; pageSize?: number } = {}, options: PersonalizedRequestOptions = {}): Promise<BillRecommendationsPage> {
  const search = new URLSearchParams();
  if (params.cursor) search.set("cursor", params.cursor);
  if (params.pageSize !== undefined) search.set("page_size", String(params.pageSize));
  const query = search.toString();
  return authGet(`/api/tracking/recommendations/${query ? `?${query}` : ""}`, options);
}
export function getRepresentativeRecommendations(options: PersonalizedRequestOptions = {}): Promise<RepresentativeRecommendationsResponse> {
  return authGet("/api/tracking/representative-recommendations/", options);
}
export function getRepresentativeTopicActivity(id: number, options: { signal?: AbortSignal } = {}): Promise<RepresentativeTopicActivity> {
  return publicGet(`/api/representatives/${id}/topic-activity/`, options);
}
