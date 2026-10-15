"use client";
import React from "react";
import { capturePersonalizedScope, getSession, isPersonalizedScopeCurrent, subscribePersonalizedChanges, type PersonalizedRequestOptions, type PersonalizedScope } from "@/lib/api";

export function useRecommendations<T>(load: (options: PersonalizedRequestOptions) => Promise<T>, onInvalidate?: () => void) {
  const [state, setState] = React.useState<{ data: T | null; scope: PersonalizedScope | null; loading: boolean; signedIn: boolean; error: string }>({ data: null, scope: null, loading: true, signedIn: false, error: "" });
  const [revision, reload] = React.useReducer(value => value + 1, 0);
  const controller = React.useRef<AbortController | null>(null);
  React.useEffect(() => subscribePersonalizedChanges(() => {
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
        const session = await getSession({ scope: initial, signal: abort.signal });
        if (abort.signal.aborted || !isPersonalizedScopeCurrent(initial)) return;
        if (!session) { setState({ data: null, scope: initial, loading: false, signedIn: false, error: "" }); return; }
        const data = await load({ scope: initial, signal: abort.signal });
        if (!abort.signal.aborted && isPersonalizedScopeCurrent(initial)) setState({ data, scope: initial, loading: false, signedIn: true, error: "" });
      } catch (error) {
        if (!abort.signal.aborted && isPersonalizedScopeCurrent(initial)) setState({ data: null, scope: initial, loading: false, signedIn: true, error: error instanceof Error && error.name === "AbortError" ? "" : "Recommendations could not be loaded. Try again." });
      }
    })();
    return () => abort.abort();
  }, [load, revision]);
  const retry = () => {
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
