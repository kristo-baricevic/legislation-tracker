"use client";

import { useEffect, useState } from "react";

import {
  acknowledgeBillChanges,
  getBillChanges,
  type BillChangesPage,
  type BillDocumentItem,
} from "@/lib/api";

import BillVersionComparison from "./bill-version-comparison";

interface ContractComparisonIdentity {
  id: number;
  computed_at: string;
}

export function selectDocumentComparisonPair(
  documents: BillDocumentItem[],
): [BillDocumentItem, BillDocumentItem] | null {
  const after = documents.find((document) => document.is_active_version);
  if (!after || after.source_order === null) return null;
  let before: BillDocumentItem | null = null;
  for (const document of documents) {
    if (
      document.source_order !== null &&
      document.source_order < after.source_order &&
      document.source_order > (before?.source_order ?? 0)
    ) {
      before = document;
    }
  }
  return before ? [before, after] : null;
}

function mergeEvents(
  existing: BillChangesPage["results"],
  incoming: BillChangesPage["results"],
) {
  const byId = new Map(
    [...existing, ...incoming].map((event) => [event.id, event]),
  );
  return [...byId.values()].sort(
    (left, right) =>
      Date.parse(left.occurred_at) - Date.parse(right.occurred_at) ||
      left.id - right.id,
  );
}

function objectValue(value: unknown, key: string): unknown {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return (value as Record<string, unknown>)[key];
}

function readableChangeDetail(change: BillChangesPage["results"][number]): string | null {
  const beforeStatus = objectValue(change.before, "status");
  const afterStatus = objectValue(change.after, "status");
  if (typeof afterStatus === "string") {
    return typeof beforeStatus === "string" ? `${beforeStatus} → ${afterStatus}` : `Status: ${afterStatus}`;
  }
  const version = objectValue(change.after, "version_label");
  if (typeof version === "string") return `Version: ${version}`;
  const topics = objectValue(change.after, "topics");
  if (Array.isArray(topics) && topics.every((topic) => typeof topic === "string")) {
    return `Policy areas: ${topics.join(", ")}`;
  }
  return null;
}

export default function BillChangeExperience({
  billId,
  documents,
}: {
  billId: number;
  contracts: ContractComparisonIdentity[];
  documents: BillDocumentItem[];
}) {
  const [changes, setChanges] = useState<BillChangesPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acknowledging, setAcknowledging] = useState(false);
  const [loadingTimeline, setLoadingTimeline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setChanges(null);
    setError(null);
    getBillChanges(billId)
      .then((page) => {
        if (!cancelled) setChanges(page);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(
            cause instanceof Error
              ? cause.message
              : "Could not load bill changes.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [billId]);

  async function acknowledge() {
    if (!changes?.page_end_cursor) return;
    setAcknowledging(true);
    setError(null);
    try {
      const result = await acknowledgeBillChanges(
        billId,
        changes.page_end_cursor,
      );
      setChanges((current) =>
        current ? { ...current, unread_count: result.unread_count } : current,
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not acknowledge changes.",
      );
    } finally {
      setAcknowledging(false);
    }
  }

  async function loadTimeline(direction: "older" | "newer") {
    if (!changes) return;
    const cursor =
      direction === "older" ? changes.older_cursor : changes.page_end_cursor;
    if (!cursor) return;
    setLoadingTimeline(true);
    setError(null);
    try {
      const page = await getBillChanges(
        billId,
        direction === "older"
          ? { beforeCursor: cursor }
          : { afterCursor: cursor },
      );
      setChanges((current) => {
        if (!current) return page;
        const completedInitialHistory =
          direction === "older" &&
          current.initial_window_truncated &&
          !page.has_more_older;
        return {
          ...current,
          results: mergeEvents(current.results, page.results),
          older_cursor:
            direction === "older" ? page.older_cursor : current.older_cursor,
          page_end_cursor:
            direction === "newer"
              ? page.page_end_cursor ?? current.page_end_cursor
              : completedInitialHistory
                ? current.stream_head_cursor
                : current.page_end_cursor,
          has_more_older:
            direction === "older" ? page.has_more_older : current.has_more_older,
          has_more_newer:
            direction === "newer" ? page.has_more_newer : current.has_more_newer,
          unread_count: page.unread_count,
          initial_window_truncated: completedInitialHistory
            ? false
            : current.initial_window_truncated,
        };
      });
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not load more changes.",
      );
    } finally {
      setLoadingTimeline(false);
    }
  }


  return (
    <section className="mb-6 space-y-4 rounded-lg border border-slate-400/80 bg-white/80 p-4 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-green-400">
            What changed?
          </h2>
          <p className="text-sm text-slate-600 dark:text-green-600">
            A chronological record of bill updates, versions, analysis,
            relationships, and votes.
          </p>
        </div>
        {changes?.personalized &&
          changes.page_end_cursor &&
          !changes.initial_window_truncated && (
          <button
            type="button"
            onClick={acknowledge}
            disabled={acknowledging}
            className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
          >
            {acknowledging
              ? "Saving…"
              : changes.unread_count
                ? `Mark ${changes.unread_count} as seen`
                : "Changes seen"}
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}
      {!changes && !error && (
        <p className="text-sm text-slate-600 dark:text-green-600">
          Loading change history…
        </p>
      )}
      {changes?.initial_window_truncated && (
        <p className="text-sm text-slate-600 dark:text-green-600">
          Showing the newest changes first; older history is available.
        </p>
      )}
      {changes &&
        (changes.results.length ? (
          <ol className="divide-y divide-slate-300 dark:divide-green-900/70">
            {changes.results.map((change) => (
              <li key={change.id} className="py-3">
                <p className="font-semibold">{change.summary}</p>
                {readableChangeDetail(change) && <p className="mt-1 text-sm text-slate-800 dark:text-green-200">{readableChangeDetail(change)}</p>}
                <p className="text-sm text-slate-600 dark:text-green-600">
                  {new Date(change.occurred_at).toLocaleString()}
                </p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-slate-600 dark:text-green-600">
            No changes have been recorded yet.
          </p>
        ))}
      {changes && (changes.has_more_older || changes.has_more_newer) && (
        <div className="flex flex-wrap gap-3">
          {changes.has_more_older && (
            <button
              type="button"
              disabled={loadingTimeline}
              onClick={() => void loadTimeline("older")}
              className="border border-slate-700 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-green-700"
            >
              Load older changes
            </button>
          )}
          {changes.has_more_newer && (
            <button
              type="button"
              disabled={loadingTimeline}
              onClick={() => void loadTimeline("newer")}
              className="border border-slate-700 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-green-700"
            >
              Load newer changes
            </button>
          )}
        </div>
      )}

      <BillVersionComparison key={billId} billId={billId} documents={documents} initialPair={selectDocumentComparisonPair(documents)} />
    </section>
  );
}
