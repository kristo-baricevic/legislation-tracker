import { authPost, getApiBase } from "./api";

export type ResearchSource = { url: string; attribution: string; license: string; fetched_at: string };
export type ResearchRun = { id: string; status: string; sections: Record<string, { status: string; reason?: string }>; error?: string | null; retry_at?: string | null };
export type Research = { status: string; period: number; run: ResearchRun | null; biography: { text: string; source: ResearchSource; kind?: string } | null; portrait: { url: string; source: ResearchSource } | null; snapshot: string | null };
export type Contributors = { status: string; snapshot: string | null; period?: number; individuals_visible?: boolean; count: number; next_cursor: number | null; results: { id: number; contributor_id: number; name: string; type: string; amount: string; date: string | null; committee: string; source_url: string }[] };
export type Connections = { notice: string; finance_status: string; count: number; next_cursor: number | null; donor_count: number; next_donor_cursor: number | null; related_count: number; next_related_cursor: number | null; donors: { id: number; name: string; amount: string; source_url: string }[]; related_representatives: { id: number; name: string; amount: string; source_url: string }[]; bills: { id: number; title: string; number: string; relations: string[]; votes: { vote_id: number; question: string; position: string; source_url: string }[]; topics: { id: number; name: string }[] }[] };

async function read<T>(id: number, path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${getApiBase()}/api/representatives/${id}/${path}`, { signal });
  if (!response.ok) throw new Error("Could not load saved research. Please retry.");
  return response.json();
}
export const getResearch = (id: number, period: number, signal?: AbortSignal) => read<Research>(id, `research/?period=${period}`, signal);
export const startResearch = (id: number, period: number, signal?: AbortSignal) => authPost<ResearchRun>(`/api/representatives/${id}/research/`, { period }, { signal });
export const getContributors = (id: number, period: number, snapshot: string, cursor: number, sort: string, signal?: AbortSignal, kind = "contribution") => read<Contributors>(id, `contributors/?period=${period}&snapshot=${encodeURIComponent(snapshot)}&cursor=${cursor}&sort=${sort}&kind=${kind}`, signal);
export const getConnections = (id: number, period: number, cursor: number, signal?: AbortSignal, contributor?: number, donorCursor = 0, relatedCursor = 0) => read<Connections>(id, `connections/?period=${period}&cursor=${cursor}&donor_cursor=${donorCursor}&related_cursor=${relatedCursor}${contributor ? `&contributor=${contributor}` : ""}`, signal);
