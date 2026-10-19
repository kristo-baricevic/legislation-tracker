"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  getTopics,
  getTrackedTopics,
  getSession,
  trackTopic,
  type TopicItem,
  untrackTopic,
} from "@/lib/api";

export default function TopicsPage() {
  const [topics, setTopics] = useState<TopicItem[]>([]);
  const [followedIds, setFollowedIds] = useState<Set<number>>(new Set());
  const [loggedIn, setLoggedIn] = useState(false);
  const [topicsLoading, setTopicsLoading] = useState(true);
  const [topicsError, setTopicsError] = useState<string | null>(null);
  const [followedLoading, setFollowedLoading] = useState(false);
  const [followedError, setFollowedError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [trackingError, setTrackingError] = useState<string | null>(null);

  const loadTopics = useCallback(async () => {
    setTopicsLoading(true);
    setTopicsError(null);
    try {
      setTopics(await getTopics());
    } catch {
      setTopicsError("Could not load topics. Try again.");
    } finally {
      setTopicsLoading(false);
    }
  }, []);

  const loadFollowedTopics = useCallback(async () => {
    setFollowedLoading(true);
    setFollowedError(null);
    try {
      const followed = await getTrackedTopics();
      setFollowedIds(new Set(followed.map((row) => row.topic.id)));
    } catch {
      setFollowedError("Could not load followed topics. Try again.");
    } finally {
      setFollowedLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void loadTopics();
    void getSession()
      .then((session) => {
        if (!active) return;
        const authed = Boolean(session);
        setLoggedIn(authed);
        if (authed) void loadFollowedTopics();
      })
      .catch(() => {
        if (active) setLoggedIn(false);
      });
    return () => {
      active = false;
    };
  }, [loadFollowedTopics, loadTopics]);

  const handleToggle = async (topicId: number) => {
    if (busy !== null) return;
    setBusy(topicId);
    setTrackingError(null);
    try {
      if (followedIds.has(topicId)) {
        await untrackTopic(topicId);
        setFollowedIds((prev) => {
          const next = new Set(prev);
          next.delete(topicId);
          return next;
        });
      } else {
        await trackTopic(topicId);
        setFollowedIds((prev) => new Set(prev).add(topicId));
      }
    } catch (error) {
      setTrackingError(
        error instanceof Error ? error.message : "Failed to update tracked topic",
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="tracker-page">
      <h1 className="mb-2 font-sans tracker-heading text-ink">
        Policy Topics
      </h1>
      <p className="mb-6 font-sans text-sm text-muted">
        Browse all policy topics.
        {loggedIn
          ? " Click to follow or unfollow topics you care about — followed topics appear first."
          : " Log in to follow topics and get personalized updates."}
      </p>

      <div className="mb-4 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => void loadTopics()}
          disabled={topicsLoading}
          className="cursor-pointer border border-control px-3 py-1.5 font-sans text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
        >
          {topicsError ? "Retry topics" : "Refresh topics"}
        </button>
        {loggedIn && (
          <button
            type="button"
            onClick={() => void loadFollowedTopics()}
            disabled={followedLoading}
            className="cursor-pointer border border-control px-3 py-1.5 font-sans text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          >
            {followedError ? "Retry followed topics" : "Refresh followed topics"}
          </button>
        )}
      </div>

      {topicsLoading && (
        <p aria-live="polite" className="mb-4 font-sans text-sm text-muted">
          {topics.length > 0 ? "Refreshing topics…" : "Loading topics…"}
        </p>
      )}

      {loggedIn && followedLoading && (
        <p aria-live="polite" className="mb-4 font-sans text-sm text-muted">
          Refreshing followed topics…
        </p>
      )}

      {topicsError && (
        <p
          role="alert"
          className="mb-4 rounded border border-red-200 bg-red-50 p-3 font-sans text-sm text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300"
        >
          {topicsError}
        </p>
      )}

      {followedError && (
        <p
          role="alert"
          className="mb-4 rounded border border-red-200 bg-red-50 p-3 font-sans text-sm text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300"
        >
          {followedError}
        </p>
      )}

      {trackingError && (
        <p
          role="alert"
          className="mb-4 rounded border border-red-200 bg-red-50 p-3 font-sans text-sm text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300"
        >
          {trackingError}
        </p>
      )}

      {!topicsLoading && !topicsError && topics.length === 0 && (
        <p className="font-sans text-sm text-muted">
          No policy topics are available.
        </p>
      )}

      {topics.length > 0 && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[...topics]
          .sort((a, b) => {
            const aFollowed = followedIds.has(a.id) ? 0 : 1;
            const bFollowed = followedIds.has(b.id) ? 0 : 1;
            if (aFollowed !== bFollowed) return aFollowed - bFollowed;
            return a.name.localeCompare(b.name);
          })
          .map((topic) => {
            const isFollowed = followedIds.has(topic.id);
            return (
              <div
                key={topic.id}
                className={`flex items-center justify-between rounded-lg border p-4 transition-colors ${
                  isFollowed
                    ? "border-control bg-wash"
                    : "border-line bg-paper"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/bills?topic_id=${topic.id}`}
                    className="font-sans text-sm font-semibold text-ink hover:underline"
                  >
                    {topic.name}
                  </Link>
                </div>

                {loggedIn && (
                  <button
                    type="button"
                    disabled={
                      busy === topic.id || followedLoading || Boolean(followedError)
                    }
                    onClick={() => handleToggle(topic.id)}
                    className={`ml-3 flex-shrink-0 rounded-md px-3 py-1 font-sans text-xs font-medium transition-colors ${
                      isFollowed
                        ? "bg-ink text-paper hover:opacity-90"
                        : "border border-line text-muted hover:bg-wash"
                    } disabled:opacity-50`}
                  >
                    {busy === topic.id
                      ? "…"
                      : isFollowed
                        ? "Following"
                        : "Follow"}
                  </button>
                )}
              </div>
            );
          })}
      </div>}
    </div>
  );
}
