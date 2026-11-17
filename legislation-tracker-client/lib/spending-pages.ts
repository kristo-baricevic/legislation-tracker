import type { OutsideSpending } from "./representative-research";

export class SpendingRevisionChanged extends Error {}
export type SpendingPages = OutsideSpending & { loadedThrough: number };

// A revision identifies one ordered dataset. Never mix offset pages from
// different revisions; retain the visible data while a replacement is fetched.
export async function loadSpendingPages(
  read: (cursor: number, revision?: string) => Promise<OutsideSpending>,
  through: number,
  previous?: SpendingPages,
): Promise<SpendingPages> {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      let result: OutsideSpending;
      let loadedThrough: number;
      let rows: OutsideSpending["results"];
      if (previous?.revision && through > previous.loadedThrough && previous.next_cursor !== null) {
        loadedThrough = previous.next_cursor;
        result = await read(loadedThrough, previous.revision);
        if (result.revision !== previous.revision) throw new SpendingRevisionChanged();
        rows = [...previous.results, ...result.results];
      } else {
        result = await read(0);
        loadedThrough = 0;
        if (result.revision && result.revision === previous?.revision) {
          return { ...previous, ...result, next_cursor: previous.next_cursor, results: previous.results, loadedThrough: previous.loadedThrough };
        }
        rows = [...result.results];
      }
      const revision = result.revision;
      while (result.next_cursor !== null && result.next_cursor <= through) {
        const next = result.next_cursor;
        if (next <= loadedThrough) throw new Error("Invalid spending cursor");
        result = await read(next, revision);
        if (result.revision !== revision) throw new SpendingRevisionChanged();
        loadedThrough = next;
        rows.push(...result.results);
      }
      return { ...result, results: rows, loadedThrough };
    } catch (error) {
      if (!(error instanceof SpendingRevisionChanged)) throw error;
      previous = undefined;
    }
  }
  throw new Error("Spending data is changing. Please retry.");
}
