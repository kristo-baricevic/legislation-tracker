/**
 * Backend API base URL and auth helpers.
 * Set NEXT_PUBLIC_API_URL in .env.local (e.g. http://localhost:8000).
 */

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

/** Try to refresh the access token using the stored refresh token. Returns new access token or null. */
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

/** Public GET (no auth required). */
export async function publicGet<T = unknown>(path: string): Promise<T> {
  const base = getApiBase();
  const res = await fetch(`${base}${path}`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? data.error ?? `Request failed: ${res.status}`);
  }
  return res.json();
}

/** Authenticated GET. On 401, tries to refresh the token and retries once; then throws. */
export async function authGet<T = unknown>(path: string, retried = false): Promise<T> {
  const base = getApiBase();
  const token = getStoredAccessToken();
  const headers: HeadersInit = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${base}${path}`, { headers });
  if (res.status === 401 && !retried) {
    const newToken = await tryRefreshToken();
    if (newToken) return authGet<T>(path, true);
    clearStoredTokens();
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? data.error ?? `Request failed: ${res.status}`);
  }
  return res.json();
}

/** Authenticated POST. */
export async function authPost<T = unknown>(path: string, body: unknown): Promise<T> {
  const base = getApiBase();
  const token = getStoredAccessToken();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${base}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? data.error ?? `Request failed: ${res.status}`);
  }
  return res.json();
}

/** Topic tag on a bill (from Phase 6 keyword inference). */
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
  source_url: string | null;
  downloaded_at: string | null;
}

/** Phase 5 contract evidence row (field → quote from bill text). */
export interface EvidenceSpanItem {
  field_path: string;
  quoted_text: string;
  page_number: number | null;
}

/** Phase 5 plain-language contract snapshot (nested on bill detail). */
export interface BillContractItem {
  id: number;
  schema_version: string;
  contract_json: Record<string, unknown>;
  contract_hash: string;
  computed_at: string;
  document: number;
  document_version_label: string;
  evidence_spans: EvidenceSpanItem[];
}

export interface BillDetail extends BillListItem {
  summary: string | null;
  processing_status: string;
  sponsor: number | null;
  raw_text_url: string | null;
  pdf_url: string | null;
  source_api_id: string | null;
  documents: BillDocumentItem[];
  congress_gov_url: string | null;
  /** Latest generated contract (after Celery processes documents). */
  latest_contract: BillContractItem | null;
  topics: BillTopicItem[];
  created_at: string;
  updated_at: string;
}

export interface BillsPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: BillListItem[];
}

/** Policy topic (for bill filters). */
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
  /** Exact primary key */
  id?: number;
  /** Case-insensitive substring match on bill_number */
  bill_number?: string;
  /** Case-insensitive substring match */
  status?: string;
  /** Sponsor: numeric = Representative id, else name substring */
  sponsor?: string;
  jurisdiction?: string;
  /** Fuzzy: topic name or slug contains this string */
  topic?: string;
  /** Exact topic tag (bill must have this topic); takes precedence over `topic` text */
  topic_id?: number;
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

export interface RepresentativeItem {
  id: number;
  bioguide_id: string;
  name: string;
  chamber: string;
  party: string;
  state: string;
  district: string | null;
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

// --- User preferences (auth required) ---

export interface FollowedTopicsResponse {
  topic_ids: number[];
}

export async function getFollowedTopics(): Promise<FollowedTopicsResponse> {
  return authGet<FollowedTopicsResponse>("/api/preferences/followed-topics/");
}

export async function followTopic(topicId: number): Promise<unknown> {
  return authPost("/api/preferences/follow-topic/", { topic_id: topicId });
}

export async function unfollowTopic(topicId: number): Promise<unknown> {
  return authPost("/api/preferences/unfollow-topic/", { topic_id: topicId });
}

export function isLoggedIn(): boolean {
  return !!getStoredAccessToken();
}
