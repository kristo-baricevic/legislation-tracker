import { getSession, type AuthSession } from "./api";
import { capturePersonalizedScope, isPersonalizedScopeCurrent, subscribePersonalizedChanges } from "./personalized-scope";
import { useSyncExternalStore } from "react";

// Tab memory only. Cache promises to coalesce concurrent readers; never retain failures.
const entries = new Map<string, { promise: Promise<unknown>; value?: unknown }>();
let flight: Promise<AuthSession | null> | undefined;
let revision: string | undefined;
let trackingRevision: string | undefined;
let researchRevision: string | undefined;
let installed = false;
let repVersion = 0;
const repListeners = new Set<() => void>();
const subscribeRep = (fn: () => void) => { repListeners.add(fn); return () => { repListeners.delete(fn); }; };
export function useDashboardRepVersion() { return useSyncExternalStore(subscribeRep, () => repVersion, () => 0); }
function clear() { entries.clear(); flight = undefined; revision = trackingRevision = researchRevision = undefined; }
function install() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  subscribePersonalizedChanges(({ kind }) => { if (kind !== "revalidate") clear(); });
  window.addEventListener("representative-research-updated", event => {
    const id = (event as CustomEvent<number>).detail;
    for (const key of entries.keys()) if (key.startsWith(`rep:${id}:`) || key === "tracking") entries.delete(key);
  });
}
export function dashboardSession() {
  install();
  const scope = capturePersonalizedScope();
  if (!flight) {
    const pending = getSession({ scope }, true).then(session => {
      if (!isPersonalizedScopeCurrent(scope)) throw new DOMException("Session changed", "AbortError");
      const next = session && JSON.stringify([session.user.email, session.dashboard_revision, session.current_congress]);
      if (!session) entries.clear();
      else {
        const refreshReps = revision !== next || researchRevision !== session.research_revision;
        if (revision !== next) {
          entries.delete("bill-recommendations"); entries.delete("rep-recommendations");
          for (const key of entries.keys()) if (key.endsWith(":activity") || key.endsWith(":card")) entries.delete(key);
        }
        if (trackingRevision !== session.tracking_revision) entries.delete("tracking");
        if (researchRevision !== session.research_revision) {
          for (const key of entries.keys()) if (key.startsWith("rep:") && !key.endsWith(":activity")) entries.delete(key);
        }
        if (refreshReps) { repVersion++; repListeners.forEach(fn => fn()); }
      }
      trackingRevision = session?.tracking_revision;
      researchRevision = session?.research_revision;
      revision = next ?? undefined;
      return session;
    }).catch(error => { if (flight === pending) clear(); throw error; })
      .finally(() => { if (flight === pending) flight = undefined; });
    flight = pending;
  }
  return flight;
}
export function forgetDashboardValue(key: string) { entries.delete(key); }
export function peekDashboardValue<T>(key: string): T | undefined {
  if (typeof window === "undefined" || !isPersonalizedScopeCurrent(capturePersonalizedScope())) return undefined;
  return entries.get(key)?.value as T | undefined;
}
export function dashboardValue<T>(key: string, load: () => Promise<T>, retain: (value: T) => boolean = () => true): Promise<T> {
  install();
  const existing = entries.get(key);
  if (existing) return existing.promise as Promise<T>;
  const forget = () => { if (entries.get(key) === entry) entries.delete(key); };
  const pending = load().then(value => { if (retain(value)) entry.value = value; else forget(); return value; }, error => { forget(); throw error; });
  const entry: { promise: Promise<T>; value?: T } = {promise: pending};
  if (entries.size >= 512) entries.delete(entries.keys().next().value!);
  entries.set(key, entry);
  return pending;
}
