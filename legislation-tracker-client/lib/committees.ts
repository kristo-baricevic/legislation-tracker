import { getApiBase, type BillListItem } from "./api";

export type Committee = { id:number; name:string; chamber:string; parent_name:string|null; members:Array<{role:string;rank:number|null;representative:{id:number;name:string;bioguide_id:string;image_url:string;party:string;state:string}}> };
export type CommitteePage<T> = { results:T[]; next:string|null; congress?:number };
export async function committeeRequest<T>(path:string, page:number, signal:AbortSignal):Promise<CommitteePage<T>> {
  const response=await fetch(`${getApiBase()}${path}${path.includes("?") ? "&" : "?"}page=${page}&page_size=6`, {signal});
  if (!response.ok) throw new Error("Could not load records.");
  const data=await response.json();
  if (!Array.isArray(data.results)) throw new Error("Invalid response.");
  return data;
}
export type CommitteeBill = BillListItem;
