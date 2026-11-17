import { expect, it } from "vitest";
import { loadSpendingPages, SpendingRevisionChanged } from "@/lib/spending-pages";

const page = (revision: string, cursor: number) => ({ revision, status: "available", support: "100", oppose: "0", count: 60,
  next_cursor: cursor < 40 ? cursor + 20 : null,
  results: [{ id: cursor + 1, name: revision, amount: "100", period: 2026, position: "S" as const, source_url: "https://fec.gov" }] });

it("appends without fetching preceding pages and polls only the first page when unchanged", async () => {
  const calls: number[] = [];
  const read = async (cursor: number) => { calls.push(cursor); return page("v1", cursor); };
  const first = await loadSpendingPages(read, 0);
  const second = await loadSpendingPages(read, 20, first);
  const third = await loadSpendingPages(read, 40, second);
  const polled = await loadSpendingPages(read, 40, third);
  expect(calls).toEqual([0, 20, 40, 0]);
  expect(polled.results.map(row => row.id)).toEqual([1, 21, 41]);
});

it("replaces the whole visible prefix when the revision changes", async () => {
  const first = await loadSpendingPages(async cursor => page("v1", cursor), 20);
  const calls: number[] = [];
  const result = await loadSpendingPages(async cursor => { calls.push(cursor); return page("v2", cursor); }, 20, first);
  expect(calls).toEqual([0, 20]);
  expect(result.results.map(row => row.name)).toEqual(["v2", "v2"]);
});

it("does not publish mixed revisions if data changes during pagination", async () => {
  let call = 0;
  const result = await loadSpendingPages(async cursor => page(++call === 1 ? "v1" : "v2", cursor), 20);
  expect(result.results.map(row => row.name)).toEqual(["v2", "v2"]);
});

it("recovers from a stale cursor and bounds retries during continuous updates", async () => {
  let calls = 0;
  const previous = await loadSpendingPages(async cursor => page("v1", cursor), 0);
  const recovered = await loadSpendingPages(async cursor => {
    if (++calls === 1) throw new SpendingRevisionChanged();
    return page("v2", cursor);
  }, 20, previous);
  expect(recovered.results.map(row => row.name)).toEqual(["v2", "v2"]);
  calls = 0;
  await expect(loadSpendingPages(async () => { calls++; throw new SpendingRevisionChanged(); }, 0)).rejects.toThrow("Please retry");
  expect(calls).toBe(3);
});

it("keeps an abort or network error from becoming a retry loop", async () => {
  let calls = 0;
  await expect(loadSpendingPages(async () => { calls++; throw new DOMException("Aborted", "AbortError"); }, 0)).rejects.toThrow("Aborted");
  expect(calls).toBe(1);
});
