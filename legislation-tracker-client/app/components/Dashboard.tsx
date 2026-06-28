"use client";

import Link from "next/link";
import React from "react";
import {
  getMyTracking,
  getStoredAccessToken,
  getTrackingFeed,
  triggerDocumentBackfill,
  triggerPollCongress,
  type IngestionTaskResponse,
  type TrackingFeed,
  type TrackingSummary,
} from "@/lib/api";

type WorkflowKey = "poll" | "backfill";

export default function Dashboard() {
  const [congress, setCongress] = React.useState("119");
  const [documentSession, setDocumentSession] = React.useState("119");
  const [running, setRunning] = React.useState<WorkflowKey | null>(null);
  const [result, setResult] = React.useState<IngestionTaskResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [trackingSummary, setTrackingSummary] =
    React.useState<TrackingSummary | null>(null);
  const [trackingSummaryError, setTrackingSummaryError] =
    React.useState<string | null>(null);
  const [trackingFeed, setTrackingFeed] = React.useState<TrackingFeed | null>(null);
  const [trackingFeedError, setTrackingFeedError] = React.useState<string | null>(
    null,
  );

  React.useEffect(() => {
    if (!getStoredAccessToken()) return;
    let cancelled = false;
    getMyTracking()
      .then((summary) => {
        if (!cancelled) setTrackingSummary(summary);
      })
      .catch((err) => {
        if (!cancelled) {
          setTrackingSummaryError(
            err instanceof Error ? err.message : "Failed to load tracked items",
          );
        }
      });
    getTrackingFeed({ limit: 5 })
      .then((feed) => {
        if (!cancelled) setTrackingFeed(feed);
      })
      .catch((err) => {
        if (!cancelled) {
          setTrackingFeedError(
            err instanceof Error ? err.message : "Failed to load tracked changes",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function runWorkflow(workflow: WorkflowKey) {
    setRunning(workflow);
    setResult(null);
    setError(null);

    try {
      const response =
        workflow === "poll"
          ? await triggerPollCongress({
              jurisdiction: "federal",
              congress: parseInt(congress, 10),
            })
          : await triggerDocumentBackfill({
              session: parseInt(documentSession, 10),
            });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Workflow request failed");
    } finally {
      setRunning(null);
    }
  }

  const congressIsValid = Number.isInteger(parseInt(congress, 10));
  const sessionIsValid = Number.isInteger(parseInt(documentSession, 10));

  return (
    <div className="w-full font-mono text-slate-900 dark:text-green-300">
      <div className="mb-8 border-b border-slate-400 pb-4 dark:border-green-900/70">
        <h1 className="text-2xl font-semibold text-slate-950 dark:text-green-400">
          Legislation Tracker Operations
        </h1>
        <p className="mx-auto mt-2 max-w-3xl text-sm text-slate-600 dark:text-green-600">
          Queue ingestion work through Django and Celery, then review the
          stored dataset from the backend-backed views.
        </p>
      </div>

      <section className="mb-8">
        <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-green-400">
          Queue workflows
        </h2>
        <div className="responsive-card-grid">
          <div className="border border-slate-400 bg-white/70 p-4 dark:border-green-900/70 dark:bg-black">
            <label className="mb-3 block text-sm text-slate-600 dark:text-green-500">
              Congress
              <input
                type="number"
                inputMode="numeric"
                min="1"
                value={congress}
                onChange={(event) => setCongress(event.target.value)}
                className="mt-1 block w-full border border-slate-400 bg-white px-3 py-2 text-slate-900 dark:border-green-800 dark:bg-black dark:text-green-300"
              />
            </label>
            <button
              type="button"
              disabled={running !== null || !congressIsValid}
              onClick={() => runWorkflow("poll")}
              className="cursor-pointer border border-slate-800 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
            >
              {running === "poll" ? "Queuing..." : "Poll Congress"}
            </button>
          </div>

          <div className="border border-slate-400 bg-white/70 p-4 dark:border-green-900/70 dark:bg-black">
            <label className="mb-3 block text-sm text-slate-600 dark:text-green-500">
              Document session
              <input
                type="number"
                inputMode="numeric"
                min="1"
                value={documentSession}
                onChange={(event) => setDocumentSession(event.target.value)}
                className="mt-1 block w-full border border-slate-400 bg-white px-3 py-2 text-slate-900 dark:border-green-800 dark:bg-black dark:text-green-300"
              />
            </label>
            <button
              type="button"
              disabled={running !== null || !sessionIsValid}
              onClick={() => runWorkflow("backfill")}
              className="cursor-pointer border border-slate-800 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
            >
              {running === "backfill" ? "Queuing..." : "Backfill documents"}
            </button>
          </div>
        </div>

        {(result || error) && (
          <div className="mt-4 border border-slate-400 bg-slate-100 p-3 text-sm dark:border-green-900 dark:bg-green-950/20">
            {result && (
              <p>
                Queued <span className="font-semibold">{result.task_name}</span>{" "}
                as <span className="font-semibold">{result.task_id}</span>.
              </p>
            )}
            {error && <p className="text-red-700 dark:text-red-300">{error}</p>}
          </div>
        )}
      </section>

      <section className="mb-8">
        <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-green-400">
          My tracked
        </h2>
        {trackingSummaryError && (
          <div className="mb-3 border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            {trackingSummaryError}
          </div>
        )}
        {!trackingSummary && !trackingSummaryError && (
          <p className="text-sm text-slate-600 dark:text-green-500">
            Loading tracked items...
          </p>
        )}
        {trackingSummary && (
          <div className="responsive-card-grid">
            <div className="border border-slate-400 bg-white/70 p-4 dark:border-green-900/70 dark:bg-black">
              <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-green-400">
                Bills ({trackingSummary.bills.length})
              </h3>
              {trackingSummary.bills.length === 0 ? (
                <p className="text-sm text-slate-600 dark:text-green-600">
                  No tracked bills.
                </p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {trackingSummary.bills.slice(0, 4).map((item) => (
                    <li key={item.id}>
                      <Link
                        href={`/bills/${item.bill.id}`}
                        className="text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
                      >
                        {item.bill.bill_number}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="border border-slate-400 bg-white/70 p-4 dark:border-green-900/70 dark:bg-black">
              <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-green-400">
                Topics ({trackingSummary.topics.length})
              </h3>
              {trackingSummary.topics.length === 0 ? (
                <p className="text-sm text-slate-600 dark:text-green-600">
                  No tracked topics.
                </p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {trackingSummary.topics.slice(0, 4).map((item) => (
                    <li key={item.id}>{item.topic.name}</li>
                  ))}
                </ul>
              )}
            </div>

            <div className="border border-slate-400 bg-white/70 p-4 dark:border-green-900/70 dark:bg-black">
              <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-green-400">
                Legislators ({trackingSummary.legislators.length})
              </h3>
              {trackingSummary.legislators.length === 0 ? (
                <p className="text-sm text-slate-600 dark:text-green-600">
                  No tracked legislators.
                </p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {trackingSummary.legislators.slice(0, 4).map((item) => (
                    <li key={item.id}>
                      {item.representative.name} ({item.representative.state})
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="mb-8">
        <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-green-400">
          Recent tracked changes
        </h2>
        {trackingFeedError && (
          <div className="mb-3 border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            {trackingFeedError}
          </div>
        )}
        {!trackingFeed && !trackingFeedError && (
          <p className="text-sm text-slate-600 dark:text-green-500">
            Loading tracked changes...
          </p>
        )}
        {trackingFeed && trackingFeed.entries.length === 0 && (
          <p className="border border-slate-400 bg-white/70 p-4 text-sm text-slate-600 dark:border-green-900/70 dark:bg-black dark:text-green-600">
            No tracked changes yet.
          </p>
        )}
        {trackingFeed && trackingFeed.entries.length > 0 && (
          <ul className="divide-y divide-slate-300 border border-slate-400 bg-white/70 dark:divide-green-900/70 dark:border-green-900/70 dark:bg-black">
            {trackingFeed.entries.map((entry) => (
              <li key={entry.id} className="p-4 text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <Link
                    href={`/bills/${entry.bill.id}`}
                    className="font-semibold text-blue-900 underline hover:text-blue-950 dark:text-green-500 dark:hover:text-green-400"
                  >
                    {entry.bill.bill_number}
                  </Link>
                  <time
                    dateTime={entry.created_at}
                    className="text-xs text-slate-500 dark:text-green-700"
                  >
                    {new Date(entry.created_at).toLocaleString()}
                  </time>
                </div>
                <p className="mt-1 text-slate-700 dark:text-green-500">
                  {entry.change_type.replaceAll("_", " ")}
                </p>
                <p className="mt-1 truncate text-slate-600 dark:text-green-600">
                  {entry.bill.title}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-green-400">
          Review data
        </h2>
        <div className="flex flex-wrap gap-3">
          <Link
            href="/bills"
            className="border border-slate-800 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-slate-200 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
          >
            Ingested bills
          </Link>
          <Link
            href="/representatives"
            className="border border-slate-800 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-slate-200 dark:border-green-700 dark:text-green-300 dark:hover:bg-green-950/40"
          >
            Representatives
          </Link>
        </div>
      </section>
    </div>
  );
}
