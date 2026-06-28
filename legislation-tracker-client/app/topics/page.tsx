"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  getTopics,
  getFollowedTopics,
  followTopic,
  unfollowTopic,
  isLoggedIn,
  type TopicItem,
} from "@/lib/api";

export default function TopicsPage() {
  const [topics, setTopics] = useState<TopicItem[]>([]);
  const [followedIds, setFollowedIds] = useState<Set<number>>(new Set());
  const [loggedIn, setLoggedIn] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    const authed = isLoggedIn();
    setLoggedIn(authed);

    const fetchAll = async () => {
      try {
        const [allTopics, followed] = await Promise.all([
          getTopics(),
          authed
            ? getFollowedTopics().catch(() => ({ topic_ids: [] }))
            : Promise.resolve({ topic_ids: [] }),
        ]);
        setTopics(allTopics);
        setFollowedIds(new Set(followed.topic_ids));
      } catch {
        // topics endpoint is public so this is unlikely
      } finally {
        setLoading(false);
      }
    };
    fetchAll();
  }, []);

  const handleToggle = async (topicId: number) => {
    if (busy !== null) return;
    setBusy(topicId);
    try {
      if (followedIds.has(topicId)) {
        await unfollowTopic(topicId);
        setFollowedIds((prev) => {
          const next = new Set(prev);
          next.delete(topicId);
          return next;
        });
      } else {
        await followTopic(topicId);
        setFollowedIds((prev) => new Set(prev).add(topicId));
      }
    } catch {
      // silently fail
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-mono text-slate-500 dark:text-green-600">Loading topics…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-2 font-mono text-2xl font-bold text-slate-900 dark:text-green-400">
        Policy Topics
      </h1>
      <p className="mb-6 font-mono text-sm text-slate-600 dark:text-green-600">
        Browse all policy topics.
        {loggedIn
          ? " Click to follow or unfollow topics you care about — followed topics appear first."
          : " Log in to follow topics and get personalized updates."}
      </p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
                    ? "border-blue-500 bg-blue-50 dark:border-green-500 dark:bg-green-950/30"
                    : "border-slate-300 bg-white dark:border-green-800/40 dark:bg-black"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/bills?topic_id=${topic.id}`}
                    className="font-mono text-sm font-semibold text-slate-900 hover:underline dark:text-green-400"
                  >
                    {topic.name}
                  </Link>
                </div>

                {loggedIn && (
                  <button
                    type="button"
                    disabled={busy === topic.id}
                    onClick={() => handleToggle(topic.id)}
                    className={`ml-3 flex-shrink-0 rounded-md px-3 py-1 font-mono text-xs font-medium transition-colors ${
                      isFollowed
                        ? "bg-blue-600 text-white hover:bg-blue-700 dark:bg-green-600 dark:hover:bg-green-500"
                        : "border border-slate-400 text-slate-600 hover:bg-slate-100 dark:border-green-700 dark:text-green-500 dark:hover:bg-green-950/40"
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
      </div>
    </div>
  );
}
