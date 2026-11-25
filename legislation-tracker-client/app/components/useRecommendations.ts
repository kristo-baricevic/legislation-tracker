"use client";
import React from "react";
import { capturePersonalizedScope, isPersonalizedScopeCurrent, subscribePersonalizedChanges, type PersonalizedRequestOptions, type PersonalizedScope } from "@/lib/api";
import { dashboardSession, dashboardValue, forgetDashboardValue } from "@/lib/dashboard-cache";

// Private, tab-local cache: never persisted to browser storage or shared across identities.

export function useRecommendations<T>(key: string, load: (options: PersonalizedRequestOptions) => Promise<T>, onInvalidate?: () => void, keepOnTracking = false) {
  const [state, setState] = React.useState<{ data: T | null; dataKey: string | null; scope: PersonalizedScope | null; loading: boolean; signedIn: boolean; error: string }>(() => {
    return { data: null, dataKey: null, scope: null, loading: true, signedIn: false, error: "" };
  });
  const [revision, reload] = React.useReducer(value => value + 1, 0);
  const [dismissals, setDismissals] = React.useState<{ session: number; ids: Set<number> } | null>(null);
  function dismiss(scope: PersonalizedScope, id: number) {
    if (!isPersonalizedScopeCurrent(scope)) return;
    setDismissals(previous => ({
      session: scope.sessionGeneration,
      ids: new Set(previous?.session === scope.sessionGeneration ? previous.ids : []).add(id),
    }));
    forgetDashboardValue(key.split(":")[0]);
  }
  const controller = React.useRef<AbortController | null>(null);
  const current = React.useRef(state);
  const currentKey = React.useRef(key);
  currentKey.current = key;
  const settledKey = React.useRef<string | null>(null);
  current.current = state;
  React.useEffect(() => subscribePersonalizedChanges(({ kind, scope }) => {
    if (kind === "revalidate") { reload(); return; }
    controller.current?.abort();
    if (kind === "tracking") {
      // Following must not clear mounted content or move the reader's focus.
      if (keepOnTracking && !current.current.loading && settledKey.current === currentKey.current && current.current.dataKey === currentKey.current && current.current.data && current.current.scope?.sessionGeneration === scope.sessionGeneration) {
        controller.current = new AbortController();
        setState(previous => ({ ...previous, scope, loading: false }));
        return;
      }
      reload();
      return;
    }
    onInvalidate?.();
    setState({ data: null, dataKey: null, scope: null, loading: true, signedIn: false, error: "" });
    reload();
  }), [onInvalidate, keepOnTracking]);
  React.useEffect(() => {
    setState(previous => ({ ...previous, loading: true, error: "" }));
    const abort = new AbortController();
    controller.current = abort;
    const initial = capturePersonalizedScope();
    void (async () => {
      try {
        const session = await dashboardSession(Boolean(settledKey.current && settledKey.current !== key));
        if (abort.signal.aborted || !isPersonalizedScopeCurrent(initial)) return;
        if (!session) { settledKey.current = key; setState({ data: null, dataKey: null, scope: initial, loading: false, signedIn: false, error: "" }); return; }
        const data = await dashboardValue(key, () => load({ scope: initial }));
        if (!abort.signal.aborted && isPersonalizedScopeCurrent(initial)) {
          settledKey.current = key;
          setState({ data, dataKey: key, scope: initial, loading: false, signedIn: true, error: "" });
        }
      } catch (error) {
        if (!abort.signal.aborted && isPersonalizedScopeCurrent(initial)) { settledKey.current = key; setState(previous => ({ ...previous, scope: initial, loading: false, signedIn: true, error: error instanceof Error && error.name === "AbortError" ? "" : "Recommendations could not be loaded. Try again." })); }
      }
    })();
    return () => abort.abort();
  }, [key, load, revision]);
  const retry = () => {
    if (current.current.loading) return;
    current.current = { ...current.current, loading: true };
    forgetDashboardValue(key);
    controller.current?.abort();
    setState(previous => ({ ...previous, loading: true, error: "" }));
    reload();
  };
  const update = (scope: PersonalizedScope, transform: (data: T) => T) => {
    if (currentKey.current === key && isPersonalizedScopeCurrent(scope)) setState(previous => previous.dataKey === key && previous.data && previous.scope === scope ? { ...previous, data: transform(previous.data) } : previous);
  };
  return { ...state, dismiss, dismissed: dismissals && dismissals.session === state.scope?.sessionGeneration ? dismissals.ids : null, data: state.dataKey === key ? state.data : null, loading: state.loading || settledKey.current !== key, retry, update, requestOptions: () => ({ scope: state.scope ?? undefined, signal: controller.current?.signal }) };
}
