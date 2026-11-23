"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { getSession, getMyTracking, trackLegislator, untrackLegislator } from "@/lib/api";
import { capturePersonalizedScope, isPersonalizedScopeCurrent, subscribePersonalizedChanges } from "@/lib/personalized-scope";

export default function TrackRepresentativeButton({ representativeId }: { representativeId: number }) {
  const [state, setState] = useState<"loading" | "anonymous" | "tracked" | "untracked" | "error">("loading");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [revision, setRevision] = useState(0);
  const pending = useRef(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    const unsubscribe = subscribePersonalizedChanges(() => {
      setState("loading"); setError(""); setRevision(value => value + 1);
    });
    return () => { mounted.current = false; unsubscribe(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const scope = capturePersonalizedScope();
    const options = { scope, signal: controller.signal };
    setState("loading");
    void (async () => {
      try {
        const session = await getSession(options);
        const tracking = session ? await getMyTracking(options) : null;
        if (controller.signal.aborted || !isPersonalizedScopeCurrent(scope)) return;
        setState(!session ? "anonymous" : tracking?.legislators.some(item => item.representative.id === representativeId) ? "tracked" : "untracked");
      } catch {
        if (!controller.signal.aborted && isPersonalizedScopeCurrent(scope)) setState("error");
      }
    })();
    return () => controller.abort();
  }, [representativeId, revision]);

  async function toggle() {
    if (pending.current || (state !== "tracked" && state !== "untracked")) return;
    pending.current = true; setSaving(true); setError("");
    const scope = capturePersonalizedScope();
    const wasTracked = state === "tracked";
    try {
      await (wasTracked ? untrackLegislator : trackLegislator)(representativeId, { scope });
      if (mounted.current && capturePersonalizedScope().sessionGeneration === scope.sessionGeneration) setState(wasTracked ? "untracked" : "tracked");
    } catch {
      if (mounted.current && isPersonalizedScopeCurrent(scope)) setError("Could not update tracking. Try again.");
    } finally {
      pending.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  const buttonClass = "rounded-full bg-ink px-4 py-2 text-sm font-semibold text-paper disabled:opacity-50";
  if (state === "anonymous") return <Link href="/login" className={buttonClass}>Log in to track</Link>;
  if (state === "error") return <button className={buttonClass} onClick={() => setRevision(value => value + 1)}>Retry tracking</button>;
  return <div>
    <button className={buttonClass} aria-label={state === "loading" ? "Loading tracking" : state === "tracked" ? "Untrack representative" : "Track representative"} aria-pressed={state === "tracked"} aria-busy={state === "loading" || saving} disabled={saving || state === "loading"} onClick={() => void toggle()}>{saving ? "Saving…" : state === "loading" ? "Track" : state === "tracked" ? "Untrack" : "Track"}</button>
    {error && <p role="alert" className="mt-2 text-sm">{error}</p>}
  </div>;
}
