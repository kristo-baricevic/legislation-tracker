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

const AUTH_TOKEN_KEY = "legislation_tracker_access";
const AUTH_REFRESH_KEY = "legislation_tracker_refresh";

export function getApiBase(): string {
  return getApiUrl().replace(/\/$/, "");
}

export function getStoredAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function getStoredRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_REFRESH_KEY);
}

export function setStoredTokens(access: string, refresh: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(AUTH_TOKEN_KEY, access);
  localStorage.setItem(AUTH_REFRESH_KEY, refresh);
}

export function clearStoredTokens(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_REFRESH_KEY);
}

export function isLoggedIn(): boolean {
  return !!getStoredAccessToken();
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

export interface LoginResponse {
  access: string;
  refresh: string;
}

export interface RegisterResponse {
  id: number;
  email: string;
}

/** Login: send "email" (backend User.USERNAME_FIELD is email). */
export async function login(email: string, password: string): Promise<LoginResponse> {
  const base = getApiBase();
  const res = await fetch(`${base}/api/auth/token/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? data.error ?? "Login failed");
  }
  return res.json();
}

export async function register(email: string, password: string): Promise<RegisterResponse> {
  const base = getApiBase();
  const res = await fetch(`${base}/api/auth/register/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? "Registration failed");
  }
  return res.json();
}

async function tryRefreshToken(): Promise<string | null> {
  const refresh = getStoredRefreshToken();
  if (!refresh) return null;
  const base = getApiBase();
  const res = await fetch(`${base}/api/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!res.ok) return null;
  const data = (await res.json()) as { access: string };
  if (data.access) {
    setStoredTokens(data.access, refresh);
    return data.access;
  }
  return null;
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
  const token = getStoredAccessToken();
  const headers: HeadersInit = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${base}${path}`, { headers });
  if (res.status === 401 && !retried) {
    const newToken = await tryRefreshToken();
    if (newToken) return authGet<T>(path, true);
    if (token) {
      clearStoredTokens();
      return authGet<T>(path, true);
    }
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
  const token = getStoredAccessToken();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${base}${path}`, {
    method: "POST",
    headers,
    body: body == null ? undefined : JSON.stringify(body),
  });
  if (res.status === 401 && !retried) {
    const newToken = await tryRefreshToken();
    if (newToken) return authPost<T>(path, body, true);
    clearStoredTokens();
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
  const token = getStoredAccessToken();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${base}${path}`, {
    method: "PUT",
    headers,
    body: JSON.stringify(body),
  });
  if (res.status === 401 && !retried) {
    const newToken = await tryRefreshToken();
    if (newToken) return authPut<T>(path, body, true);
    clearStoredTokens();
  }
  if (!res.ok) {
    throw await responseError(res, `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function authDelete(path: string, retried = false): Promise<void> {
  const base = getApiBase();
  const token = getStoredAccessToken();
  const headers: HeadersInit = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${base}${path}`, {
    method: "DELETE",
    headers,
  });
  if (res.status === 401 && !retried) {
    const newToken = await tryRefreshToken();
    if (newToken) return authDelete(path, true);
    clearStoredTokens();
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
}

export interface BillDocumentItem {
  id: number;
  version_label: string;
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
  bill: number;
  chamber: string;
  session_number: number | null;
  roll_number: number;
  vote_date: string;
  result: string;
  yeas: number;
  nays: number;
}

export interface VoteRecordItem {
  representative: RepresentativeItem;
  position: string;
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
  page?: number;
}): Promise<RepresentativesPage> {
  const sp = new URLSearchParams();
  if (params?.state) sp.set("state", params.state);
  if (params?.chamber) sp.set("chamber", params.chamber);
  if (params?.page != null) sp.set("page", String(params.page));
  const q = sp.toString();
  return publicGet<RepresentativesPage>(`/api/representatives/${q ? `?${q}` : ""}`);
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
  bill: BillListItem;
  tracked_bill: TrackedBillItem;
  ingestion: {
    bill_id: number;
    unchanged?: boolean;
  };
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
