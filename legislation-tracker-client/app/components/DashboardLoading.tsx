"use client";

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import { subscribePersonalizedChanges } from "@/lib/api";
import LoadingSpinner from "./LoadingSpinner";

const DashboardLoadingContext = createContext<((id: string, loading: boolean | null) => void) | null>(null);

export function useDashboardLoading(id: string, loading: boolean) {
  const report = useContext(DashboardLoadingContext);
  useLayoutEffect(() => {
    report?.(id, loading);
    return () => report?.(id, null);
  }, [report, id, loading]);
  return report !== null;
}

export default function DashboardLoading({ children }: { children: ReactNode }) {
  const [sections, setSections] = useState<Record<string, boolean>>({});
  const [revealed, setRevealed] = useState(false);
  const report = useCallback((id: string, loading: boolean | null) => {
    setSections(previous => {
      if (previous[id] === loading || (loading === null && !(id in previous))) return previous;
      const next = { ...previous };
      if (loading === null) delete next[id];
      else next[id] = loading;
      return next;
    });
  }, []);
  const pending = Object.values(sections).some(Boolean);
  useEffect(() => {
    if (Object.keys(sections).length && !pending) setRevealed(true);
  }, [sections, pending]);
  useEffect(() => subscribePersonalizedChanges(({ kind }) => {
    if (kind === "session") setRevealed(false);
  }), []);

  return <DashboardLoadingContext.Provider value={report}>
    <LoadingSpinner centered active={pending && !revealed} label="Loading dashboard…" />
    <div hidden={pending && !revealed} aria-busy={pending}>{children}</div>
  </DashboardLoadingContext.Provider>;
}
