"use client";
import React from "react";
import { capturePersonalizedScope, isPersonalizedScopeCurrent, subscribePersonalizedChanges, type PersonalizedRequestOptions, type PersonalizedScope } from "@/lib/api";
import { dashboardSession, dashboardValue, forgetDashboardValue, peekDashboardValue } from "@/lib/dashboard-cache";

// Private, tab-local cache: never persisted to browser storage or shared across identities.

export function useRecommendations<T>(key: string, load: (options: PersonalizedRequestOptions) => Promise<T>, onInvalidate?: () => void) {
  const [state, setState] = React.useState<{ data: T | null; scope: PersonalizedScope | null; loading: boolean; signedIn: boolean; error: string }>(() => {
    const data = peekDashboardValue<T>(key) ?? null;
    return { data, scope: data ? capturePersonalizedScope() : null, loading: !data, signedIn: !!data, error: "" };
  });
  const [revision, reload] = React.useReducer(value => value + 1, 0);
  const controller = React.useRef<AbortController | null>(null);
  React.useEffect(() => subscribePersonalizedChanges(({ kind }) => {
    if (kind === "revalidate") { reload(); return; }
    controller.current?.abort();
    onInvalidate?.();
    setState({ data: null, scope: null, loading: true, signedIn: false, error: "" });
    reload();
  }), [onInvalidate]);
  React.useEffect(() => {
    const abort = new AbortController();
    controller.current = abort;
    const initial = capturePersonalizedScope();
    void (async () => {
      try {
        const session = await dashboardSession();
        if (abort.signal.aborted || !isPersonalizedScopeCurrent(initial)) return;
        if (!session) { setState({ data: null, scope: initial, loading: false, signedIn: false, error: "" }); return; }
        const data = await dashboardValue(key, () => load({ scope: initial }));
        if (!abort.signal.aborted && isPersonalizedScopeCurrent(initial)) {
          setState({ data, scope: initial, loading: false, signedIn: true, error: "" });
        }
      } catch (error) {
        if (!abort.signal.aborted && isPersonalizedScopeCurrent(initial)) setState({ data: null, scope: initial, loading: false, signedIn: true, error: error instanceof Error && error.name === "AbortError" ? "" : "Recommendations could not be loaded. Try again." });
      }
    })();
    return () => abort.abort();
  }, [key, load, revision]);
  const retry = () => {
    forgetDashboardValue(key);
    controller.current?.abort();
    onInvalidate?.();
    setState({ data: null, scope: null, loading: true, signedIn: false, error: "" });
    reload();
  };
  const update = (scope: PersonalizedScope, transform: (data: T) => T) => {
    if (isPersonalizedScopeCurrent(scope)) setState(previous => previous.data && previous.scope === scope ? { ...previous, data: transform(previous.data) } : previous);
  };
  return { ...state, retry, update, requestOptions: () => ({ scope: state.scope ?? undefined, signal: controller.current?.signal }) };
}
