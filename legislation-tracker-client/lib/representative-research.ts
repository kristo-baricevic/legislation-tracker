import { authPost, getApiBase } from "./api";

export type ResearchSource = { url: string; attribution: string; license: string; fetched_at: string };
export type ResearchRun = { id: string; status: string; sections: Record<string, { status: string; reason?: string }>; error?: string | null; retry_at?: string | null };
export type FinanceProgress = { snapshot: string; collecting: boolean; pages_loaded: number; streams_completed: number; streams_total: number; totals_loaded: number; official_totals: { committee?: string; source_url: string; records: Record<string, string | number | null>[] }[] };
export type Research = { finance_progress?: FinanceProgress | null; status: string; period: number; run: ResearchRun | null; biography: { text: string; source: ResearchSource; kind?: string } | null; portrait: { url: string; source: ResearchSource } | null; snapshot: string | null };
export type Contributors = { status: string; snapshot: string | null; period?: number; individuals_visible?: boolean; count: number; next_cursor: number | null; results: { id: number; contributor_id: number; name: string; type: string; amount: string; date: string | null; committee: string; source_url: string }[] };
export type Connections = { nodes?: { id: string; kind: string; label: string; url: string }[]; edges?: { id: string; kind: string; source: string; target: string; label: string; evidence_url: string; amount?: string }[]; notice: string; finance_status: string; count: number; next_cursor: number | null; donor_count: number; next_donor_cursor: number | null; related_count: number; next_related_cursor: number | null; donors: { id: number; name: string; amount: string; source_url: string }[]; related_representatives: { id: number; name: string; amount: string; source_url: string }[]; bills: { id: number; title: string; number: string; relations: string[]; votes: { vote_id: number; question: string; position: string; source_url: string }[]; topics: { id: number; name: string }[] }[] };

async function read<T>(id: number, path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${getApiBase()}/api/representatives/${id}/${path}`, { signal });
  if (!response.ok) throw new Error("Could not load saved research. Please retry.");
  return response.json();
}
export const getResearch = async (id: number, period: number, signal?: AbortSignal) => {
  const result = await read<Research>(id, `research/?period=${period}`, signal);
  if (result.portrait?.url.startsWith(`/api/representatives/${id}/portraits/`)) {
    result.portrait.url = `${getApiBase()}${result.portrait.url}`;
  }
  return result;
};
export const startResearch = (id: number, period: number, signal?: AbortSignal) => authPost<ResearchRun>(`/api/representatives/${id}/research/`, { period }, { signal });
export const getContributors = (id: number, period: number, snapshot: string, cursor: number, sort: string, signal?: AbortSignal, kind = "contribution") => read<Contributors>(id, `contributors/?period=${period}&snapshot=${encodeURIComponent(snapshot)}&cursor=${cursor}&sort=${sort}&kind=${kind}`, signal);
export type FinanceHistory = { count: number; next_cursor: number | null; results: { id: string; published_at: string; active: boolean; coverage: string }[] };
export const getFinanceHistory = (id: number, period: number, cursor: number, signal?: AbortSignal) => read<FinanceHistory>(id, `research-snapshots/?period=${period}&cursor=${cursor}`, signal);
export const getConnections = (id: number, period: number, cursor: number, signal?: AbortSignal, contributor?: number, donorCursor = 0, relatedCursor = 0, filters: { snapshot?: string; legislative_start?: string; legislative_end?: string } = {}) => {
  const query = new URLSearchParams({ period: String(period), cursor: String(cursor), donor_cursor: String(donorCursor), related_cursor: String(relatedCursor) });
  if (contributor) query.set("contributor", String(contributor));
  for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);
  return read<Connections>(id, `connections/?${query}`, signal);
};
