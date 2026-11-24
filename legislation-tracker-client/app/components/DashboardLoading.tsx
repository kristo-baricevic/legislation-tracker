"use client";

import { createContext, useCallback, useContext, useLayoutEffect, useState, type ReactNode } from "react";
import LoadingSpinner from "./LoadingSpinner";

const DashboardLoadingContext = createContext<((id: string, loading: boolean | null) => void) | null>(null);

const DashboardBusyContext = createContext(false);

export function useDashboardCardLoading(id: string, loading: boolean) {
  const dashboardBusy = useContext(DashboardBusyContext);
  // Wait for card details during a dashboard load. A newly followed card
  // can fill in its details without hiding rows the reader is already using.
  const [openedDuringLoad] = useState(dashboardBusy);
  useDashboardLoading(id, openedDuringLoad && loading);
}

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
    <DashboardBusyContext.Provider value={pending}>
      <div hidden={pending} aria-busy={pending}>{children}</div>
    </DashboardBusyContext.Provider>
  </DashboardLoadingContext.Provider>;
}
