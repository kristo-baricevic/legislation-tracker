/**
 * Backend API base URL and auth helpers.
 * Set NEXT_PUBLIC_API_URL in .env.local (e.g. http://localhost:8000).
 */

import type { ContractJson, EvidenceSpanItem } from "./contracts";

export type { EvidenceSpanItem } from "./contracts";

const getApiUrl = () =>
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
    : process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function getApiBase(): string {
  return getApiUrl().replace(/\/$/, "");
}

let bootstrappedCsrfToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
const AUTH_REFRESH_LOCK = "legislation-tracker-auth-refresh";

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("csrftoken="));
  return cookie
    ? decodeURIComponent(cookie.slice("csrftoken=".length))
    : bootstrappedCsrfToken;
}

function csrfHeaders(headers?: HeadersInit): Headers {
  const result = new Headers(headers);
  const csrfToken = getCsrfToken();
  if (csrfToken) result.set("X-CSRFToken", csrfToken);
  return result;
}

async function bootstrapCsrf(): Promise<void> {
  const base = getApiBase();
  const res = await fetch(`${base}/api/auth/csrf/`, { credentials: "include" });
  if (!res.ok) throw await responseError(res, "Failed to initialize sign-in security");
  const data = (await res.json()) as { csrf_token?: string };
  bootstrappedCsrfToken = data.csrf_token ?? getCsrfToken();
  if (!bootstrappedCsrfToken) {
    throw new ApiError("Failed to initialize sign-in security", res.status);
  }
}

async function ensureCsrf(): Promise<void> {
  if (!getCsrfToken()) await bootstrapCsrf();
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function responseError(res: Response, fallback: string): Promise<ApiError> {
  const data = await res.json().catch(() => ({}));
  return new ApiError(data.detail ?? data.error ?? fallback, res.status);
}

export interface AuthSession {
  authenticated: true;
  user: {
    email: string;
  };
}

export interface RegisterResponse {
  detail: string;
}

export async function login(email: string, password: string): Promise<AuthSession> {
  const base = getApiBase();
  await bootstrapCsrf();
  const res = await fetch(`${base}/api/auth/session/`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  });
  if (!res.ok) {
    throw await responseError(res, "Login failed");
  }
  return res.json();
}

export async function register(email: string, password: string): Promise<RegisterResponse> {
  const base = getApiBase();
  await bootstrapCsrf();
  const res = await fetch(`${base}/api/auth/register/`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  });
  if (!res.ok) {
    throw await responseError(res, "Registration failed");
  }
  return res.json();
}

async function refreshSession(): Promise<boolean> {
  try {
    await ensureCsrf();
  } catch {
    return false;
  }
  const base = getApiBase();
  const res = await fetch(`${base}/api/auth/session/refresh/`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
  });
  return res.ok;
}

async function tryRefreshSession(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  const refresh: Promise<boolean> =
    typeof navigator !== "undefined" && navigator.locks
      ? navigator.locks
          .request<Promise<boolean>>(AUTH_REFRESH_LOCK, refreshSession)
          .then((result) => result)
      : refreshSession();
  const trackedRefresh = refresh.finally(() => {
    refreshInFlight = null;
  });
  refreshInFlight = trackedRefresh;
  return trackedRefresh;
}

export async function getSession(retried = false): Promise<AuthSession | null> {
  const base = getApiBase();
  const res = await fetch(`${base}/api/auth/session/current/`, {
    credentials: "include",
  });
  if (res.status === 401 && !retried && (await tryRefreshSession())) {
    return getSession(true);
  }
  if (res.status === 401 || res.status === 403) return null;
  if (!res.ok) throw await responseError(res, "Failed to load session");
  return res.json();
}

export async function logout(): Promise<void> {
  const base = getApiBase();
  await ensureCsrf();
  const res = await fetch(`${base}/api/auth/session/logout/`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
  });
  if (!res.ok) throw await responseError(res, "Logout failed");
}

export async function publicGet<T = unknown>(path: string): Promise<T> {
  const base = getApiBase();
  const res = await fetch(`${base}${path}`);
  if (!res.ok) {
    throw await responseError(res, `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function authGet<T = unknown>(path: string, retried = false): Promise<T> {
  const base = getApiBase();
  const res = await fetch(`${base}${path}`, { credentials: "include" });
  if (res.status === 401 && !retried) {
    if (await tryRefreshSession()) return authGet<T>(path, true);
  }
  if (!res.ok) {
    throw await responseError(res, `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function authPost<T = unknown>(
  path: string,
  body?: object,
  retried = false,
): Promise<T> {
  const base = getApiBase();
  await ensureCsrf();
  const res = await fetch(`${base}${path}`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: body == null ? undefined : JSON.stringify(body),
  });
  if (res.status === 401 && !retried) {
    if (await tryRefreshSession()) return authPost<T>(path, body, true);
  }
  if (!res.ok) {
    throw await responseError(res, `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function authPut<T = unknown>(
  path: string,
  body: object,
  retried = false,
): Promise<T> {
  const base = getApiBase();
  await ensureCsrf();
  const res = await fetch(`${base}${path}`, {
    method: "PUT",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (res.status === 401 && !retried) {
    if (await tryRefreshSession()) return authPut<T>(path, body, true);
  }
  if (!res.ok) {
    throw await responseError(res, `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function authDelete(path: string, retried = false): Promise<void> {
  const base = getApiBase();
  await ensureCsrf();
  const res = await fetch(`${base}${path}`, {
    method: "DELETE",
    headers: csrfHeaders(),
    credentials: "include",
  });
  if (res.status === 401 && !retried) {
    if (await tryRefreshSession()) return authDelete(path, true);
  }
  if (!res.ok) {
    throw await responseError(res, `Request failed: ${res.status}`);
  }
}

export interface BillTopicItem {
  topic_id: number;
  name: string;
  slug: string;
  confidence_score: number | null;
}

export interface BillListItem {
  id: number;
  jurisdiction: string;
  session: number;
  bill_number: string;
  title: string;
  status: string;
  sponsor_name: string | null;
  introduced_at: string | null;
  last_action_at: string | null;
  topics: BillTopicItem[];
  search_rank?: number | null;
  highlights?: SearchHighlight[];
}

export interface SearchHighlightSegment {
  text: string;
  matched: boolean;
}

export interface SearchHighlight {
  kind: "metadata" | "contract" | "document";
  segments: SearchHighlightSegment[];
}

export interface BillDocumentItem {
  id: number;
  version_label: string;
  source_order: number | null;
  is_active_version: boolean;
  content_type: string | null;
  file_size_bytes: number | null;
  source_url: string | null;
  downloaded_at: string | null;
  download_url: string | null;
  text_url: string | null;
}

export interface BillContractItem {
  id: number;
  schema_version: string;
  contract_json: ContractJson;
  contract_hash: string;
  computed_at: string;
  document: number | null;
  document_version_label: string | null;
  evidence_spans: EvidenceSpanItem[];
}

export interface BillContractsPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: BillContractItem[];
}

export interface BillDetail extends BillListItem {
  summary: string | null;
  processing_status: string;
  sponsor: number | null;
  source_api_id: string | null;
  documents: BillDocumentItem[];
  congress_gov_url: string | null;
  latest_contract: BillContractItem | null;
  created_at: string;
  updated_at: string;
}

export interface BillsPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: BillListItem[];
}

export interface TopicItem {
  id: number;
  name: string;
  slug: string;
}

export interface BillFilterOptions {
  jurisdictions: string[];
  current_congress: number;
}

export interface GetBillsParams {
  page?: number;
  session?: number;
  id?: number;
  bill_number?: string;
  status?: string;
  sponsor?: string;
  jurisdiction?: string;
  topic?: string;
  topic_id?: number;
  q?: string;
  sort?: "recent_activity" | "relevance";
}

export function parseTopicIdFromSearchParam(
  value: string | null | undefined,
): number | undefined {
  if (!value || !/^\d+$/.test(value)) return undefined;
  const topicId = Number(value);
  return Number.isSafeInteger(topicId) && topicId > 0 ? topicId : undefined;
}

export async function getBills(params?: GetBillsParams): Promise<BillsPage> {
  const sp = new URLSearchParams();
  if (params?.page != null) sp.set("page", String(params.page));
  if (params?.session != null) sp.set("session", String(params.session));
  if (params?.id != null) sp.set("id", String(params.id));
  if (params?.bill_number?.trim()) sp.set("bill_number", params.bill_number.trim());
  if (params?.status?.trim()) sp.set("status", params.status.trim());
  if (params?.sponsor?.trim()) sp.set("sponsor", params.sponsor.trim());
  if (params?.jurisdiction?.trim()) sp.set("jurisdiction", params.jurisdiction.trim());
  if (params?.topic?.trim()) sp.set("topic", params.topic.trim());
  if (params?.topic_id != null) sp.set("topic_id", String(params.topic_id));
  if (params?.q?.trim()) sp.set("q", params.q.trim());
  if (params?.sort) sp.set("sort", params.sort);
  const q = sp.toString();
  return publicGet<BillsPage>(`/api/bills/${q ? `?${q}` : ""}`);
}

export async function getTopics(): Promise<TopicItem[]> {
  return publicGet<TopicItem[]>("/api/topics/");
}

export async function getBillFilterOptions(): Promise<BillFilterOptions> {
  return publicGet<BillFilterOptions>("/api/bills/filter-options/");
}

export async function getBill(id: number): Promise<BillDetail> {
  return publicGet<BillDetail>(`/api/bills/${id}/`);
}

export async function getContracts(
  billId: number,
  params?: { page?: number },
): Promise<BillContractsPage> {
  const search = new URLSearchParams({ bill: String(billId) });
  if (params?.page != null) search.set("page", String(params.page));
  return publicGet<BillContractsPage>(`/api/contracts/?${search}`);
}

export interface VoteListItem {
  id: number;
  bill: number | null;
  congress?: number;
  chamber: string;
  session_number: number | null;
  roll_number: number;
  vote_date: string;
  result: string;
  yeas: number;
  nays: number;
  question?: string;
  source_url?: string;
}

export interface VoteRecordItem {
  representative: RepresentativeItem;
  position: string;
  raw_position?: string;
}

export interface VoteDetailItem extends VoteListItem {
  records: VoteRecordItem[];
}

export interface VotesPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: VoteListItem[];
}

export async function getVotes(
  billId: number,
  params?: { page?: number },
): Promise<VotesPage> {
  const search = new URLSearchParams({ bill: String(billId) });
  if (params?.page != null) search.set("page", String(params.page));
  return publicGet<VotesPage>(`/api/votes/?${search}`);
}

export async function getVote(voteId: number): Promise<VoteDetailItem> {
  return publicGet<VoteDetailItem>(`/api/votes/${voteId}/`);
}

export interface BillChangeEvent {
  id: number;
  type: string;
  occurred_at: string;
  summary: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  document_id: number | null;
  contract_id: number | null;
}

export interface BillChangesPage {
  results: BillChangeEvent[];
  page_end_cursor: string | null;
  stream_head_cursor: string | null;
  older_cursor: string | null;
  has_more_newer: boolean;
  has_more_older: boolean;
  unread_count: number | null;
  personalized: boolean;
  initial_window_truncated: boolean;
}

export function getBillChanges(
  billId: number,
  params?: { afterCursor?: string; beforeCursor?: string },
): Promise<BillChangesPage> {
  const search = new URLSearchParams();
  if (params?.afterCursor) search.set("after_cursor", params.afterCursor);
  if (params?.beforeCursor) search.set("before_cursor", params.beforeCursor);
  const query = search.toString();
  return authGet<BillChangesPage>(`/api/bills/${billId}/changes/${query ? `?${query}` : ""}`)
    .catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        return publicGet<BillChangesPage>(`/api/bills/${billId}/changes/${query ? `?${query}` : ""}`);
      }
      throw error;
    });
}

export function acknowledgeBillChanges(
  billId: number,
  cursor: string,
): Promise<{ unread_count: number | null }> {
  return authPost(`/api/bills/${billId}/changes/acknowledge/`, { cursor });
}

export interface ContractComparison {
  before: number;
  after: number;
  changes: Array<{
    path: string;
    operation: "added" | "removed" | "changed";
    before: unknown;
    after: unknown;
  }>;
  total_change_count: number;
  returned_change_count: number;
  truncated: boolean;
}

export function compareBillContracts(
  billId: number,
  before: number,
  after: number,
): Promise<ContractComparison> {
  return publicGet<ContractComparison>(
    `/api/bills/${billId}/comparisons/contracts/?before=${before}&after=${after}`,
  );
}

export interface DocumentComparison {
  before: number;
  after: number;
  sections: Array<{
    section_key: string;
    operation: "added" | "removed" | "modified";
    before_hash: string | null;
    after_hash: string | null;
  }>;
  total_change_count: number;
  returned_change_count: number;
  truncated: boolean;
  fallback: boolean;
  truncation_reasons: string[];
}

export interface DocumentSectionComparison {
  section_key: string;
  operations: Array<{
    operation: "replace" | "delete" | "insert";
    before: string[];
    after: string[];
  }>;
  truncated: boolean;
  truncation_reasons: string[];
}

export function compareBillDocumentSection(
  billId: number,
  before: number,
  after: number,
  sectionKey: string,
): Promise<DocumentSectionComparison> {
  const search = new URLSearchParams({
    before: String(before),
    after: String(after),
    section_key: sectionKey,
  });
  return publicGet<DocumentSectionComparison>(
    `/api/bills/${billId}/comparisons/documents/section/?${search}`,
  );
}

export function compareBillDocuments(
  billId: number,
  before: number,
  after: number,
): Promise<DocumentComparison> {
  return publicGet<DocumentComparison>(
    `/api/bills/${billId}/comparisons/documents/?before=${before}&after=${after}`,
  );
}

export interface RelatedBillItem {
  bill: BillListItem;
  similarity_score: number;
  method: string;
}

export interface RelatedBillsResponse {
  results: RelatedBillItem[];
}

export async function getRelatedBills(
  id: number,
  params?: { limit?: number },
): Promise<RelatedBillsResponse> {
  const sp = new URLSearchParams();
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const q = sp.toString();
  return publicGet<RelatedBillsResponse>(`/api/bills/${id}/related/${q ? `?${q}` : ""}`);
}

export interface RepresentativeItem {
  id: number;
  bioguide_id: string;
  name: string;
  chamber: string;
  party: string;
  state: string;
  district: string | null;
  first_name: string;
  last_name: string;
  official_website_url: string | null;
  image_url: string | null;
  is_current: boolean;
}

export interface RepresentativesPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: RepresentativeItem[];
}

export async function getRepresentatives(params?: {
  state?: string;
  chamber?: string;
  is_current?: boolean;
  page?: number;
  page_size?: number;
}): Promise<RepresentativesPage> {
  const sp = new URLSearchParams();
  if (params?.state) sp.set("state", params.state);
  if (params?.chamber) sp.set("chamber", params.chamber);
  if (params?.is_current != null) sp.set("is_current", String(params.is_current));
  if (params?.page != null) sp.set("page", String(params.page));
  if (params?.page_size != null) sp.set("page_size", String(params.page_size));
  const q = sp.toString();
  return publicGet<RepresentativesPage>(`/api/representatives/${q ? `?${q}` : ""}`);
}

export async function getAllCurrentRepresentatives(): Promise<RepresentativeItem[]> {
  const results: RepresentativeItem[] = [];
  let pageNumber = 1;
  while (true) {
    const page = await getRepresentatives({
      is_current: true,
      page: pageNumber,
      page_size: 100,
    });
    results.push(...page.results);
    if (!page.next || results.length >= page.count) return results;
    pageNumber += 1;
  }
}

export interface RepresentativeInsight {
  representative_id: number;
  congress: number;
  total_roll_calls: number;
  ingested_roll_calls: number;
  discovered_roll_calls: number;
  participation_numerator: number;
  participation_denominator: number;
  participation_rate: number | null;
  position_counts: Record<string, number>;
  first_vote_at: string | null;
  last_vote_at: string | null;
  coverage_complete: boolean;
  coverage_reason: string | null;
  sponsored_bill_count: number;
  active_cosponsored_bill_count: number;
  committee_count: number;
}

export interface RepresentativeComparison {
  left_representative_id: number;
  right_representative_id: number;
  congress: number;
  shared_vote_count: number;
  agree_count: number;
  disagreement_count: number;
  excluded_shared_vote_count: number;
  agreement_rate: number | null;
  coverage_complete: boolean;
  reason: string | null;
  shared_votes: Array<{
    vote_id: number;
    bill_id: number | null;
    vote_date: string;
    question: string;
    result: string;
    left_position: string;
    right_position: string;
  }>;
  returned_shared_vote_count: number;
  shared_votes_truncated: boolean;
}

export interface CommitteeMembershipItem {
  committee: {
    id: number;
    system_code: string;
    name: string;
    chamber: string;
  };
  congress: number;
  rank: number | null;
  role: string;
  is_current: boolean;
}

export interface BillCosponsorItem {
  bill: BillListItem;
  sponsorship_date: string | null;
  is_original_cosponsor: boolean;
  withdrawn_at: string | null;
}

export function getRepresentative(id: number): Promise<RepresentativeItem> {
  return publicGet<RepresentativeItem>(`/api/representatives/${id}/`);
}

export function getRepresentativeInsights(
  id: number,
  congress: number,
): Promise<RepresentativeInsight> {
  return publicGet<RepresentativeInsight>(`/api/representatives/${id}/insights/?congress=${congress}`);
}

export function getRepresentativeSponsoredBills(
  id: number,
  congress: number,
  page = 1,
): Promise<{ count: number; next: string | null; previous: string | null; results: BillListItem[] }> {
  return publicGet(`/api/representatives/${id}/sponsored-bills/?congress=${congress}&page=${page}`);
}

export function getRepresentativeCosponsoredBills(
  id: number,
  congress: number,
  page = 1,
): Promise<{ count: number; next: string | null; previous: string | null; results: BillCosponsorItem[] }> {
  return publicGet(`/api/representatives/${id}/cosponsored-bills/?congress=${congress}&page=${page}`);
}

export function getRepresentativeCommittees(
  id: number,
  congress: number,
  page = 1,
): Promise<{ count: number; next: string | null; previous: string | null; results: CommitteeMembershipItem[] }> {
  return publicGet(`/api/representatives/${id}/committees/?congress=${congress}&page=${page}`);
}

export function compareRepresentatives(
  ids: [number, number],
  congress: number,
): Promise<RepresentativeComparison> {
  return publicGet<RepresentativeComparison>(
    `/api/representatives/compare/?ids=${ids.join(",")}&congress=${congress}`,
  );
}

export interface TrackedBillItem {
  id: number;
  bill: BillListItem;
  created_at: string;
}

export interface TrackedTopicItem {
  id: number;
  topic: TopicItem;
  created_at: string;
}

export function getTrackedTopics(): Promise<TrackedTopicItem[]> {
  return authGet<TrackedTopicItem[]>("/api/tracking/topics/");
}

export interface TrackedLegislatorItem {
  id: number;
  representative: RepresentativeItem;
  created_at: string;
}

export interface TrackingSummary {
  bills: TrackedBillItem[];
  topics: TrackedTopicItem[];
  legislators: TrackedLegislatorItem[];
  is_staff: boolean;
}

export interface TrackingFeedEntry {
  id: number;
  bill: BillListItem;
  change_type: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown>;
  created_at: string;
}

export interface TrackingFeed {
  entries: TrackingFeedEntry[];
}

export function getMyTracking(): Promise<TrackingSummary> {
  return authGet<TrackingSummary>("/api/tracking/");
}

export interface SavedBillSearch {
  id: number;
  name: string;
  query_json: Record<string, unknown>;
  last_opened_at: string | null;
  last_opened_activity_sequence: number | null;
  new_result_count: number;
}

export function getSavedBillSearches(): Promise<{
  count: number;
  results: SavedBillSearch[];
}> {
  return authGet("/api/saved-searches/");
}

export function createSavedBillSearch(
  name: string,
  query: Record<string, unknown>,
): Promise<SavedBillSearch> {
  return authPost("/api/saved-searches/", { name, query });
}

export function getSavedBillSearchResults(
  id: number,
): Promise<BillsPage & { result_watermark: string }> {
  return authGet(`/api/saved-searches/${id}/results/`);
}

export function openSavedBillSearch(
  id: number,
  resultWatermark: string,
): Promise<{
  previous_activity_sequence: number | null;
  last_opened_activity_sequence: number;
  last_opened_at: string;
}> {
  return authPost(`/api/saved-searches/${id}/open/`, {
    result_watermark: resultWatermark,
  });
}

export function getTrackingFeed(params?: { limit?: number }): Promise<TrackingFeed> {
  const sp = new URLSearchParams();
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const q = sp.toString();
  return authGet<TrackingFeed>(`/api/tracking/feed/${q ? `?${q}` : ""}`);
}

export function trackBill(billId: number): Promise<TrackedBillItem> {
  return authPost<TrackedBillItem>("/api/tracking/bills/", { bill: billId });
}

export function untrackBill(billId: number): Promise<void> {
  return authDelete(`/api/tracking/bills/${billId}/`);
}

export function trackTopic(topicId: number): Promise<TrackedTopicItem> {
  return authPost<TrackedTopicItem>("/api/tracking/topics/", { topic: topicId });
}

export function untrackTopic(topicId: number): Promise<void> {
  return authDelete(`/api/tracking/topics/${topicId}/`);
}

export function trackLegislator(
  representativeId: number,
): Promise<TrackedLegislatorItem> {
  return authPost<TrackedLegislatorItem>("/api/tracking/legislators/", {
    representative: representativeId,
  });
}

export function untrackLegislator(representativeId: number): Promise<void> {
  return authDelete(`/api/tracking/legislators/${representativeId}/`);
}

export interface IngestionTaskResponse {
  task_id: string;
  task_name: string;
  jurisdiction?: string;
  congress?: number;
  session?: number;
}

export interface IngestBillResponse {
  work_item_id: number;
  status: "pending" | "dispatched" | "processing" | "succeeded" | "dead";
  status_url: string;
  tracking_status: "pending" | "fulfilled";
  bill_id: number | null;
}

export function ingestBill(params: {
  congress: number;
  billType: string;
  billNumber: string;
}): Promise<IngestBillResponse> {
  return authPost<IngestBillResponse>("/api/ingestion/bills/", {
    congress: params.congress,
    bill_type: params.billType,
    bill_number: params.billNumber,
  });
}

export function triggerPollCongress(params: {
  jurisdiction: string;
  congress: number;
}): Promise<IngestionTaskResponse> {
  return authPost<IngestionTaskResponse>("/api/ingestion/poll-congress/", {
    jurisdiction: params.jurisdiction,
    congress: params.congress,
  });
}

export function triggerDocumentBackfill(params: {
  session: number;
}): Promise<IngestionTaskResponse> {
  return authPost<IngestionTaskResponse>("/api/ingestion/backfill-documents/", {
    session: params.session,
  });
}

export function triggerTopicBackfill(params: {
  session: number;
}): Promise<IngestionTaskResponse> {
  return authPost<IngestionTaskResponse>("/api/ingestion/backfill-topics/", {
    session: params.session,
  });
}

export interface LLMSettings {
  feature_available: boolean;
  configured: boolean;
  provider: string;
  key_suffix: string | null;
  revision: number | null;
  enabled: boolean;
  validation_status: "unverified" | "valid" | "invalid";
  validated_revision: number | null;
  validated_at: string | null;
  requested_model: string;
}

export function getLLMSettings(): Promise<LLMSettings> {
  return authGet<LLMSettings>("/api/settings/llm/");
}

export function updateLLMSettings(
  values: { api_key?: string; enabled?: boolean },
): Promise<LLMSettings> {
  return authPut<LLMSettings>("/api/settings/llm/", values);
}

export function validateLLMCredential(): Promise<LLMSettings> {
  return authPost<LLMSettings>("/api/settings/llm/validate/");
}

export function deleteLLMSettings(): Promise<void> {
  return authDelete("/api/settings/llm/");
}

export interface PublicCapabilities {
  llm_enhancements: boolean;
}

export function getPublicCapabilities(): Promise<PublicCapabilities> {
  return publicGet<PublicCapabilities>("/api/capabilities/");
}

export interface EnhancementConfirmation {
  source_fingerprint: string;
  request_fingerprint: string;
  credential_revision: number;
}

export interface EnhancementUsage {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
}

export interface EnhancementCitedSource {
  source_ref: string;
  label: "Cited source";
  quoted_text: string;
  section_label: string | null;
  start_char: number | null;
  end_char: number | null;
}

export interface EnhancementAtomicItem {
  text: string;
  source_refs: string[];
  cited_sources: EnhancementCitedSource[];
}

export interface EnhancementObligation {
  actor: string;
  modality: "required" | "prohibited" | "permitted";
  action: string;
  conditions: string | null;
  source_refs: string[];
  cited_sources: EnhancementCitedSource[];
}

export interface EnhancementFundingTiming extends EnhancementAtomicItem {
  kind: "funding" | "timing";
}

export interface EnhancementUncertainLanguage extends EnhancementAtomicItem {
  why_it_matters: string;
}

export interface EnhancementResult {
  schema_version: "1.1";
  overview: EnhancementAtomicItem[];
  key_impacts: EnhancementAtomicItem[];
  obligations: EnhancementObligation[];
  funding_and_timing: EnhancementFundingTiming[];
  uncertain_language: EnhancementUncertainLanguage[];
}

export interface EnhancementAttempt {
  id: number;
  sequence: number;
  status: EnhancementStatus;
  credential_revision: number;
  estimated_input_tokens: number;
  usage: EnhancementUsage;
  resolved_model: string | null;
  failure_category: string | null;
  retry_allowed: boolean;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export type EnhancementStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "refused"
  | "outcome_unknown";

export interface BillEnhancement {
  id: number;
  bill_id: number;
  status: EnhancementStatus;
  provider: string;
  requested_model: string;
  reasoning_effort: string;
  prompt_version: string;
  output_schema_version: string;
  source_packet_version: string;
  source_fingerprint: string;
  request_fingerprint: string;
  truncated: boolean;
  coverage_notice: string | null;
  disclaimer: string;
  usage: EnhancementUsage;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  latest_attempt: EnhancementAttempt | null;
  result?: EnhancementResult | null;
  attempts?: EnhancementAttempt[];
  poll_after_seconds?: number | null;
  stale?: boolean;
}

export interface BillEnhancementEstimate {
  feature_available: boolean;
  can_enhance: boolean;
  unavailable_reason: string | null;
  credential_revision: number | null;
  provider?: string;
  requested_model: string;
  reasoning_effort?: string;
  prompt_version?: string;
  output_schema_version?: string;
  source_packet_version?: string;
  source_fingerprint?: string;
  request_fingerprint?: string;
  serialized_request_bytes?: number;
  estimated_input_tokens?: number;
  max_output_tokens?: number;
  max_output_includes_reasoning?: boolean;
  truncated?: boolean;
  coverage_notice?: string | null;
  source_description?: string;
  matching_enhancement?: BillEnhancement | null;
}

export interface BillEnhancementsPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: BillEnhancement[];
}

export function getBillEnhancementEstimate(
  billId: number,
): Promise<BillEnhancementEstimate> {
  return authGet<BillEnhancementEstimate>(
    `/api/bills/${billId}/enhancements/estimate/`,
  );
}

export function getBillEnhancements(
  billId: number,
  options: { page?: number; pageSize?: number } = {},
): Promise<BillEnhancementsPage> {
  const search = new URLSearchParams();
  if (options.page != null) search.set("page", String(options.page));
  if (options.pageSize != null) search.set("page_size", String(options.pageSize));
  const query = search.toString();
  return authGet<BillEnhancementsPage>(
    `/api/bills/${billId}/enhancements/${query ? `?${query}` : ""}`,
  );
}

export async function getLatestBillEnhancement(
  billId: number,
): Promise<BillEnhancement | null> {
  try {
    return await authGet<BillEnhancement>(
      `/api/bills/${billId}/enhancements/latest/`,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function getBillEnhancement(
  billId: number,
  enhancementId: number,
): Promise<BillEnhancement> {
  return authGet<BillEnhancement>(
    `/api/bills/${billId}/enhancements/${enhancementId}/`,
  );
}

export function createBillEnhancement(
  billId: number,
  confirmation: EnhancementConfirmation,
): Promise<BillEnhancement> {
  return authPost<BillEnhancement>(
    `/api/bills/${billId}/enhancements/`,
    confirmation,
  );
}

export function retryBillEnhancement(
  billId: number,
  enhancementId: number,
  confirmation: EnhancementConfirmation,
): Promise<BillEnhancement> {
  return authPost<BillEnhancement>(
    `/api/bills/${billId}/enhancements/${enhancementId}/retry/`,
    confirmation,
  );
}
