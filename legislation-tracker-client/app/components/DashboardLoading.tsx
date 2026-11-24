"use client";

import { createContext, useCallback, useContext, useLayoutEffect, useState, type ReactNode } from "react";
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

export default function DashboardLoading({ children, loading = false }: { children: ReactNode; loading?: boolean }) {
  const [sections, setSections] = useState<Record<string, boolean>>({});
  const report = useCallback((id: string, loading: boolean | null) => {
    setSections(previous => {
      if (previous[id] === loading || (loading === null && !(id in previous))) return previous;
      const next = { ...previous };
      if (loading === null) delete next[id];
      else next[id] = loading;
      return next;
    });
  }, []);
  const pending = loading || Object.values(sections).some(Boolean);

  return <DashboardLoadingContext.Provider value={report}>
    <LoadingSpinner centered active={pending} label="Loading dashboard…" />
    <div hidden={pending} aria-busy={pending}>{children}</div>
  </DashboardLoadingContext.Provider>;
}
