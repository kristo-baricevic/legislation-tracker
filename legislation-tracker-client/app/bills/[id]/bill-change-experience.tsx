"use client";

import { useEffect, useMemo, useState } from "react";

import {
  acknowledgeBillChanges,
  compareBillContracts,
  compareBillDocumentSection,
  compareBillDocuments,
  getBillChanges,
  type BillChangesPage,
  type BillContractItem,
  type BillDocumentItem,
  type ContractComparison,
  type DocumentComparison,
  type DocumentSectionComparison,
} from "@/lib/api";

function documentTime(document: BillDocumentItem): number {
  const parsed = document.downloaded_at
    ? Date.parse(document.downloaded_at)
    : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function selectDocumentComparisonPair(
  documents: BillDocumentItem[],
): [BillDocumentItem, BillDocumentItem] | null {
  if (documents.length < 2) return null;
  const newestFirst = [...documents].sort(
    (left, right) =>
      documentTime(right) - documentTime(left) || right.id - left.id,
  );
  const after =
    newestFirst.find((document) => document.is_active_version) ?? newestFirst[0];
  const before = newestFirst.find((document) => document.id !== after.id);
  return before ? [before, after] : null;
}

function selectContractComparisonPair(
  contracts: BillContractItem[],
): [BillContractItem, BillContractItem] | null {
  if (contracts.length < 2) return null;
  const newestFirst = [...contracts].sort(
    (left, right) =>
      Date.parse(right.computed_at) - Date.parse(left.computed_at) ||
      right.id - left.id,
  );
  return [newestFirst[1], newestFirst[0]];
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

function RenderValue({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined) return null;
  return (
    <div>
      <p className="font-semibold">{label}</p>
      <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-slate-100 p-2 text-xs dark:bg-black/40">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

export default function BillChangeExperience({
  billId,
  contracts,
  documents,
}: {
  billId: number;
  contracts: BillContractItem[];
  documents: BillDocumentItem[];
}) {
  const [changes, setChanges] = useState<BillChangesPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acknowledging, setAcknowledging] = useState(false);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [contractDiff, setContractDiff] = useState<ContractComparison | null>(null);
  const [documentDiff, setDocumentDiff] = useState<DocumentComparison | null>(null);
  const [sectionDiffs, setSectionDiffs] = useState<
    Record<string, DocumentSectionComparison>
  >({});
  const [loadingSection, setLoadingSection] = useState<string | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);
  const contractPair = useMemo(
    () => selectContractComparisonPair(contracts),
    [contracts],
  );
  const documentPair = useMemo(
    () => selectDocumentComparisonPair(documents),
    [documents],
  );

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
        return {
          ...current,
          results: mergeEvents(current.results, page.results),
          older_cursor:
            direction === "older" ? page.older_cursor : current.older_cursor,
          page_end_cursor:
            direction === "newer"
              ? page.page_end_cursor ?? current.page_end_cursor
              : current.page_end_cursor,
          has_more_older:
            direction === "older" ? page.has_more_older : current.has_more_older,
          has_more_newer:
            direction === "newer" ? page.has_more_newer : current.has_more_newer,
          unread_count: page.unread_count,
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

  async function loadComparison(kind: "contract" | "document") {
    setDiffError(null);
    try {
      if (kind === "contract" && contractPair) {
        setContractDiff(
          await compareBillContracts(
            billId,
            contractPair[0].id,
            contractPair[1].id,
          ),
        );
      } else if (kind === "document" && documentPair) {
        setDocumentDiff(
          await compareBillDocuments(
            billId,
            documentPair[0].id,
            documentPair[1].id,
          ),
        );
        setSectionDiffs({});
      }
    } catch (cause) {
      setDiffError(
        cause instanceof Error ? cause.message : "Could not compare versions.",
      );
    }
  }

  async function loadSection(sectionKey: string) {
    if (!documentPair) return;
    if (sectionDiffs[sectionKey]) {
      setSectionDiffs((current) => {
        const next = { ...current };
        delete next[sectionKey];
        return next;
      });
      return;
    }
    setLoadingSection(sectionKey);
    setDiffError(null);
    try {
      const diff = await compareBillDocumentSection(
        billId,
        documentPair[0].id,
        documentPair[1].id,
        sectionKey,
      );
      setSectionDiffs((current) => ({ ...current, [sectionKey]: diff }));
    } catch (cause) {
      setDiffError(
        cause instanceof Error
          ? cause.message
          : "Could not load the section diff.",
      );
    } finally {
      setLoadingSection(null);
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
        {changes?.personalized && changes.page_end_cursor && (
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
                <p className="text-sm text-slate-600 dark:text-green-600">
                  {new Date(change.occurred_at).toLocaleString()}
                </p>
                {(change.before || change.after) && (
                  <div className="mt-2 grid gap-2 md:grid-cols-2">
                    <RenderValue label="Before" value={change.before} />
                    <RenderValue label="After" value={change.after} />
                  </div>
                )}
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

      <div className="border-t border-slate-300 pt-3 dark:border-green-900/70">
        <h3 className="font-semibold">Compare versions</h3>
        <p className="mb-2 text-sm text-slate-600 dark:text-green-600">
          Compare the active version with its newest predecessor. Diffs are
          bounded and disclose any coverage limit.
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            disabled={!contractPair}
            onClick={() => void loadComparison("contract")}
            className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-green-700"
          >
            Compare analysis
          </button>
          <button
            type="button"
            disabled={!documentPair}
            onClick={() => void loadComparison("document")}
            className="cursor-pointer border border-slate-700 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-green-700"
          >
            Compare bill text
          </button>
        </div>
      </div>
      {diffError && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {diffError}
        </p>
      )}
      {contractDiff && (
        <div>
          <h3 className="font-semibold">
            Analysis changes ({contractDiff.total_change_count})
          </h3>
          <ul className="mt-2 space-y-3 text-sm">
            {contractDiff.changes.map((change) => (
              <li
                key={`${change.path}-${change.operation}`}
                className="space-y-2 rounded border border-slate-300 p-2 dark:border-green-900/70"
              >
                <p>
                  <span className="font-semibold">{change.operation}</span>{" "}
                  {change.path}
                </p>
                <div className="grid gap-2 md:grid-cols-2">
                  <RenderValue label="Before" value={change.before} />
                  <RenderValue label="After" value={change.after} />
                </div>
              </li>
            ))}
          </ul>
          {contractDiff.truncated && (
            <p className="text-sm">Results are truncated.</p>
          )}
        </div>
      )}
      {documentDiff && (
        <div>
          <h3 className="font-semibold">
            Text section changes ({documentDiff.total_change_count})
          </h3>
          <ul className="mt-2 space-y-2 text-sm">
            {documentDiff.sections.map((section) => (
              <li key={section.section_key}>
                <button
                  type="button"
                  onClick={() => void loadSection(section.section_key)}
                  disabled={loadingSection === section.section_key}
                  className="text-left underline disabled:opacity-50"
                >
                  <span className="font-semibold">{section.operation}</span>{" "}
                  {section.section_key}
                </button>
                {sectionDiffs[section.section_key] && (
                  <div className="mt-2 space-y-2 rounded border border-slate-300 p-2 dark:border-green-900/70">
                    {sectionDiffs[section.section_key].operations.map(
                      (operation, index) => (
                        <div key={index} className="grid gap-2 md:grid-cols-2">
                          <RenderValue
                            label={`Before (${operation.operation})`}
                            value={operation.before}
                          />
                          <RenderValue label="After" value={operation.after} />
                        </div>
                      ),
                    )}
                    {sectionDiffs[section.section_key].truncated && (
                      <p>
                        Section diff truncated:{" "}
                        {sectionDiffs[
                          section.section_key
                        ].truncation_reasons.join(", ")}
                      </p>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
          {documentDiff.truncated && (
            <p className="text-sm">
              Results are truncated
              {documentDiff.truncation_reasons.length
                ? `: ${documentDiff.truncation_reasons.join(", ")}`
                : "."}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
