import { publicGet, type BillListItem } from "./api.ts";

export type ProfileScope = { representativeId: number; congress: number; chamber?: "house" | "senate" };
export type UnavailableFact = { status: "unavailable"; value: null; precision: null; reason: string; source_url: null; retrieved_at: null };
export type VoteCoverage = {
  scope: { congress: number; chamber: string | null };
  stored_record_count: number; member_position_completeness: "unknown";
  unknown_session_record_count: number;
  provider_scopes: { chamber: string; description: string; source_url: string; historical_availability: "known" | "unknown" }[];
  legacy_ingestion_check: { scopes: {chamber:string;session_number:number;start_at:string;end_at:string;full_session:boolean}[]; coverage_complete: boolean; reason: string | null; discovered_count: number; persisted_count: number; notice: string };
};
export type LegislatorProfile = {
  schema_version: "legislator-profile-v1";
  scope: { congress: number; chamber: string | null };
  identity: { id: number; bioguide_id: string; name: string; is_current: boolean; latest_affiliation: { chamber: string; party: string; state: string; district: string | null }; last_seen_at: string | null; source_url: string | null };
  service: { status: "available" | "unavailable"; precision: "year"; observations: { id: number; chamber: string; state: string | null; district: string | null; start_year: number; end_year: number | null; source_url: string | null; retrieved_at: string | null }[]; notice: string };
  elections: { chamber: string | null; first_elected: UnavailableFact; most_recent_election_won: UnavailableFact; term_start: UnavailableFact }[];
  donors: { status: "unavailable"; reason: string; cycle: null; reporting_period: null; currency: null; source_url: null; methodology: null; donors: [] };
  coverage: VoteCoverage;
};
export type Biography = {
  status: "available" | "stale" | "unavailable"; text: string | null; reason: string | null;
  wikidata_id: string | null; page_id: number | null;
  observed_revision_id: number | null; observed_revision_at: string | null;
  page_url: string | null; observed_revision_url: string | null;
  fetched_at: string | null; shortened: boolean;
  attribution: "Wikipedia contributors"; license: "CC BY-SA 4.0"; license_url: string;
};
export type RecordedVote = {
  id: number; representative_id: number; vote_id: number; congress: number;
  chamber: string; session_number: number | null; roll_number: number;
  vote_date: string; question: string; position: "yes" | "no" | "present" | "not_voting" | "other";
  raw_position: string; bill: BillListItem | null; source_url: string | null;
  source_link_kind: "roll_call" | "session_list" | "unavailable"; source_updated_at: string | null;
};
export type LivePage<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export type VotesPage = LivePage<RecordedVote> & { coverage: VoteCoverage; page_read_at: string; pagination_mode: "live_pages" };

type ObjectValue = Record<string, unknown>;
const object = (value: unknown): value is ObjectValue => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length <= 20000;
const nullableText = (value: unknown): value is string | null => value === null || text(value);
const integer = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const positive = (value: unknown): value is number => integer(value) && value > 0;
const timestamp = (value: unknown): value is string => text(value) && /^\d{4}-\d{2}-\d{2}T/.test(value) && Number.isFinite(Date.parse(value));
const nullableTimestamp = (value: unknown) => value === null || timestamp(value);
const nullableId = (value: unknown) => value === null || positive(value);

function coverage(value: unknown): value is VoteCoverage {
  if (!object(value) || !object(value.scope) || !positive(value.scope.congress) || !nullableText(value.scope.chamber) || !integer(value.stored_record_count) || value.member_position_completeness !== "unknown" || !integer(value.unknown_session_record_count) || !Array.isArray(value.provider_scopes)) return false;
  if (!value.provider_scopes.every(item => object(item) && text(item.chamber) && text(item.description) && text(item.source_url) && ["known", "unknown"].includes(String(item.historical_availability)))) return false;
  const legacy = value.legacy_ingestion_check;
  return object(legacy) && Array.isArray(legacy.scopes) && legacy.scopes.length <= 200 && legacy.scopes.every(scope => object(scope) && text(scope.chamber) && positive(scope.session_number) && timestamp(scope.start_at) && timestamp(scope.end_at) && typeof scope.full_session === "boolean") && typeof legacy.coverage_complete === "boolean" && nullableText(legacy.reason) && integer(legacy.discovered_count) && integer(legacy.persisted_count) && text(legacy.notice);
}

function fact(value: unknown): value is UnavailableFact {
  return object(value) && value.status === "unavailable" && value.value === null && value.precision === null && text(value.reason) && value.source_url === null && value.retrieved_at === null;
}

function profile(value: unknown): value is LegislatorProfile {
  if (!object(value) || value.schema_version !== "legislator-profile-v1" || !object(value.scope) || !positive(value.scope.congress) || !nullableText(value.scope.chamber) || !object(value.identity)) return false;
  const identity = value.identity, latest = identity.latest_affiliation;
  if (!positive(identity.id) || !text(identity.bioguide_id) || !text(identity.name) || typeof identity.is_current !== "boolean" || !object(latest) || ![latest.chamber, latest.party, latest.state].every(text) || !nullableText(latest.district) || !nullableTimestamp(identity.last_seen_at) || !nullableText(identity.source_url)) return false;
  const service = value.service;
  if (!object(service) || !["available", "unavailable"].includes(String(service.status)) || service.precision !== "year" || !text(service.notice) || !Array.isArray(service.observations) || service.observations.length > 100) return false;
  if (!service.observations.every(item => object(item) && positive(item.id) && text(item.chamber) && nullableText(item.state) && nullableText(item.district) && positive(item.start_year) && (item.end_year === null || (positive(item.end_year) && item.end_year >= item.start_year)) && nullableText(item.source_url) && nullableTimestamp(item.retrieved_at))) return false;
  if (!Array.isArray(value.elections) || !value.elections.length || !value.elections.every(item => object(item) && nullableText(item.chamber) && fact(item.first_elected) && fact(item.most_recent_election_won) && fact(item.term_start))) return false;
  const donors = value.donors;
  return object(donors) && donors.status === "unavailable" && text(donors.reason) && donors.cycle === null && donors.reporting_period === null && donors.currency === null && donors.source_url === null && donors.methodology === null && Array.isArray(donors.donors) && donors.donors.length === 0 && coverage(value.coverage);
}

function biography(value: unknown): value is Biography {
  if (!object(value) || !["available", "stale", "unavailable"].includes(String(value.status)) || !nullableText(value.text) || (typeof value.text === "string" && value.text.length > 500) || !nullableText(value.reason) || !nullableText(value.wikidata_id) || !nullableId(value.page_id) || !nullableId(value.observed_revision_id) || !nullableTimestamp(value.observed_revision_at) || !nullableText(value.page_url) || !nullableText(value.observed_revision_url) || !nullableTimestamp(value.fetched_at) || typeof value.shortened !== "boolean" || value.attribution !== "Wikipedia contributors" || value.license !== "CC BY-SA 4.0" || !text(value.license_url)) return false;
  return value.status === "unavailable" ? value.text === null : Boolean(value.text && value.wikidata_id && value.page_id && value.observed_revision_id && value.observed_revision_at && value.fetched_at && safeSourceUrl(value.page_url) && safeSourceUrl(value.observed_revision_url));
}

export function isProfileBill(value: unknown): value is BillListItem {
  if (!object(value) || !positive(value.id) || !positive(value.session) || ![value.jurisdiction, value.bill_number, value.title, value.status].every(text) || !nullableText(value.sponsor_name) || !nullableText(value.introduced_at) || !nullableText(value.last_action_at) || !Array.isArray(value.topics)) return false;
  if (value.sponsor_id !== undefined && !nullableId(value.sponsor_id)) return false;
  if (value.sponsor_bioguide_id !== undefined && !nullableText(value.sponsor_bioguide_id)) return false;
  if (value.congress_gov_url !== undefined && !nullableText(value.congress_gov_url)) return false;
  return value.topics.every(topic => object(topic) && positive(topic.topic_id) && text(topic.name) && text(topic.slug) && (topic.confidence_score === null || typeof topic.confidence_score === "number"));
}

function recordedVote(value: unknown): value is RecordedVote {
  return object(value) && [value.id, value.representative_id, value.vote_id, value.congress, value.roll_number].every(positive) && text(value.chamber) && nullableId(value.session_number) && timestamp(value.vote_date) && text(value.question) && ["yes", "no", "present", "not_voting", "other"].includes(String(value.position)) && text(value.raw_position) && (value.bill === null || isProfileBill(value.bill)) && nullableText(value.source_url) && ["roll_call", "session_list", "unavailable"].includes(String(value.source_link_kind)) && nullableTimestamp(value.source_updated_at);
}

function page<T>(value: unknown, validate: (item: unknown) => item is T): value is LivePage<T> {
  return object(value) && integer(value.count) && nullableText(value.next) && nullableText(value.previous) && Array.isArray(value.results) && value.results.length <= 100 && value.results.every(validate);
}

export function safeSourceUrl(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2048 || !value.startsWith("https://") || /[\x00-\x20\x7f]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (url.username || url.password || url.port) return null;
    const path = url.pathname;
    let valid = false;
    if (url.hostname === "en.wikipedia.org") valid = (path.startsWith("/wiki/") && path.length > 6 && !url.search && !url.hash) || (path === "/w/index.php" && /^\?oldid=[1-9]\d*$/.test(url.search) && !url.hash);
    else if (url.hostname === "www.wikidata.org") valid = /^\/wiki\/Q[1-9]\d*$/.test(path) && !url.search && !url.hash;
    else if (url.hostname === "bioguide.congress.gov") valid = /^\/search\/bio\/[A-Z]\d{6}$/.test(path) && !url.search && !url.hash;
    else if (url.hostname === "www.congress.gov") valid = /^\/bill\/[1-9]\d*(?:st|nd|rd|th)-congress\/(?:house-bill|senate-bill)\/[1-9]\d*$/.test(path) && !url.search && !url.hash;
    else if (url.hostname === "clerk.house.gov") valid = /^\/Votes(?:\/[1-9]\d{4,9})?$/.test(path) && !url.search && !url.hash;
    else if (url.hostname === "www.senate.gov") valid = /^\/legislative\/(?:votes_new\.htm|LIS\/roll_call_votes\/vote\d+\/vote_\d+_[12]_\d{5}\.htm|LIS\/roll_call_lists\/vote_menu_\d+_[12]\.(?:htm|xml))$/.test(path) && !url.search && !url.hash;
    else if (url.hostname === "github.com") valid = path === "/LibraryOfCongress/api.congress.gov/blob/main/Documentation/HouseRollCallVoteEndpoint.md" && !url.search && (!url.hash || url.hash === "#coverage");
    else if (url.hostname === "creativecommons.org") valid = path === "/licenses/by-sa/4.0/" && !url.search && !url.hash;
    return valid ? url.href : null;
  } catch { return null; }
}

function scopeQuery(scope: ProfileScope) {
  if (!Number.isSafeInteger(scope.representativeId) || scope.representativeId < 1 || !Number.isSafeInteger(scope.congress) || scope.congress < 1 || scope.congress > 1000 || (scope.chamber !== undefined && !["house", "senate"].includes(scope.chamber))) throw new Error("Invalid legislator scope");
  const query = new URLSearchParams({ congress: String(scope.congress) });
  if (scope.chamber) query.set("chamber", scope.chamber);
  return query;
}

export function profileHref(scope: ProfileScope) { return `/representatives/${scope.representativeId}?${scopeQuery(scope)}`; }
export function profileScopeKey(scope: ProfileScope) { return `${scope.representativeId}:${scope.congress}:${scope.chamber ?? "all"}`; }

export async function getLegislatorProfile(scope: ProfileScope, signal?: AbortSignal): Promise<LegislatorProfile> {
  const value = await publicGet(`/api/representatives/${scope.representativeId}/profile/?${scopeQuery(scope)}`, { signal });
  if (!profile(value) || value.identity.id !== scope.representativeId || value.scope.congress !== scope.congress || value.scope.chamber !== (scope.chamber ?? null)) throw new Error("Invalid legislator profile response");
  return value;
}
export async function getLegislatorBiography(scope: ProfileScope, signal?: AbortSignal): Promise<Biography> {
  scopeQuery(scope);
  const value = await publicGet(`/api/representatives/${scope.representativeId}/biography/`, { signal });
  if (!biography(value)) throw new Error("Invalid biography response");
  return value;
}
export async function getIntroducedBills(scope: ProfileScope, pageNumber: number, signal?: AbortSignal): Promise<LivePage<BillListItem>> {
  if (!positive(pageNumber)) throw new Error("Invalid page");
  const query = scopeQuery(scope); query.delete("chamber"); query.set("page", String(pageNumber));
  const value = await publicGet(`/api/representatives/${scope.representativeId}/sponsored-bills/?${query}`, { signal });
  if (!page(value, isProfileBill) || value.results.some(bill => bill.session !== scope.congress || (bill.sponsor_id !== undefined && bill.sponsor_id !== scope.representativeId))) throw new Error("Invalid introduced-legislation response");
  return value;
}
export async function getRecordedVotes(scope: ProfileScope, pageNumber: number, signal?: AbortSignal): Promise<VotesPage> {
  if (!positive(pageNumber)) throw new Error("Invalid page");
  const query = scopeQuery(scope); query.set("page", String(pageNumber));
  const value = await publicGet(`/api/representatives/${scope.representativeId}/voting-record/?${query}`, { signal });
  if (!object(value) || value.pagination_mode !== "live_pages" || !timestamp(value.page_read_at) || !coverage(value.coverage) || !page(value, recordedVote) || value.results.some(row => row.representative_id !== scope.representativeId || row.congress !== scope.congress || (scope.chamber && row.chamber !== scope.chamber))) throw new Error("Invalid voting-record response");
  return value as VotesPage;
}
