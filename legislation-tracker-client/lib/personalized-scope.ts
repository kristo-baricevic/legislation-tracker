/** In-memory request ownership. Browser storage carries opaque epochs only. */
export interface PersonalizedScope {
  sessionGeneration: number;
  interestGeneration: number;
}
export interface PersonalizedChange {
  kind: "session" | "tracking" | "revalidate";
  scope: PersonalizedScope;
}
export interface PersonalizedRequestOptions {
  signal?: AbortSignal;
  scope?: PersonalizedScope;
}

const SESSION_EPOCH = "legislation-tracker-session-epoch";
const TRACKING_EPOCH = "legislation-tracker-tracking-epoch";
let sessionGeneration = 0;
let interestGeneration = 0;
let transition = false;
let transitionExpires = 0;
let transitionTimer: ReturnType<typeof setTimeout> | undefined;
let initialized = false;
let lastSessionEpoch: string | null = null;
let lastTrackingEpoch: string | null = null;
let identity: string | null | undefined;
const listeners = new Set<(change: PersonalizedChange) => void>();

function readEpoch(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function readTransition(epoch: string | null) {
  if (transitionTimer) clearTimeout(transitionTimer);
  const expiry = epoch?.startsWith("changing:") ? Number(epoch.split(":")[1]) : 0;
  transitionExpires = Number.isFinite(expiry) ? expiry : 0;
  transition = transitionExpires > Date.now();
  if (transition) transitionTimer = setTimeout(() => {
    if (transition && Date.now() >= transitionExpires) {
      transition = false;
      identity = undefined;
      change("session", true);
    }
  }, transitionExpires - Date.now());
}

function change(kind: PersonalizedChange["kind"], persist = false) {
  if (kind === "tracking") interestGeneration += 1;
  else sessionGeneration += 1;
  if (persist && typeof window !== "undefined") {
    const token = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    const epoch = kind === "tracking" ? token : transition ? `changing:${transitionExpires}:${token}` : `stable:${token}`;
    const key = kind === "tracking" ? TRACKING_EPOCH : SESSION_EPOCH;
    try { window.localStorage.setItem(key, epoch); } catch { /* Same-tab guards remain active. */ }
    if (kind === "tracking") lastTrackingEpoch = readEpoch(key);
    else lastSessionEpoch = readEpoch(key);
  }
  const scope = { sessionGeneration, interestGeneration };
  for (const listener of listeners) listener({ kind, scope });
  if (typeof window !== "undefined") window.dispatchEvent(new Event(kind === "tracking" ? "tracking-changed" : "auth-session-changed"));
}

function initialize() {
  if (initialized || typeof window === "undefined") return;
  initialized = true;
  lastSessionEpoch = readEpoch(SESSION_EPOCH);
  readTransition(lastSessionEpoch);
  lastTrackingEpoch = readEpoch(TRACKING_EPOCH);
  window.addEventListener("storage", event => {
    if (event.key === SESSION_EPOCH || event.key === null) {
      lastSessionEpoch = readEpoch(SESSION_EPOCH);
      readTransition(lastSessionEpoch);
      identity = undefined;
      change("session");
    }
    if (event.key === TRACKING_EPOCH || event.key === null) {
      lastTrackingEpoch = readEpoch(TRACKING_EPOCH);
      change("tracking");
    }
  });
  window.addEventListener("focus", () => {
    syncEpochs();
    // A transition already cleared private UI; its completion will revalidate it.
    if (!transition) change("revalidate");
  });
}

function syncEpochs() {
  initialize();
  if (typeof window === "undefined") return;
  const session = readEpoch(SESSION_EPOCH);
  const tracking = readEpoch(TRACKING_EPOCH);
  if (session !== lastSessionEpoch) {
    lastSessionEpoch = session;
    readTransition(session);
    identity = undefined;
    change("session");
  }
  if (tracking !== lastTrackingEpoch) {
    lastTrackingEpoch = tracking;
    change("tracking");
  }
}

export function capturePersonalizedScope(): PersonalizedScope {
  syncEpochs();
  return { sessionGeneration, interestGeneration };
}

export function isPersonalizedScopeCurrent(scope: PersonalizedScope): boolean {
  syncEpochs();
  return !transition && scope.sessionGeneration === sessionGeneration && scope.interestGeneration === interestGeneration;
}

export function assertPersonalizedScope(scope: PersonalizedScope, signal?: AbortSignal) {
  if (signal?.aborted || !isPersonalizedScopeCurrent(scope)) throw new DOMException("Session or followed interests changed", "AbortError");
}

export function subscribePersonalizedChanges(listener: (change: PersonalizedChange) => void): () => void {
  initialize();
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function beginSessionTransition() {
  initialize();
  if (transition) throw new DOMException("A session change is already in progress", "AbortError");
  transition = true;
  transitionExpires = Date.now() + 30_000;
  readTransition(`changing:${transitionExpires}`);
  identity = undefined;
  change("session", true);
  return capturePersonalizedScope();
}

export function assertSessionTransitionScope(scope: PersonalizedScope) {
  syncEpochs();
  if (scope.sessionGeneration !== sessionGeneration) throw new DOMException("Session changed", "AbortError");
}

export function endSessionTransition(email?: string | null, scope?: PersonalizedScope) {
  syncEpochs();
  if (scope && scope.sessionGeneration !== sessionGeneration) return;
  transition = false;
  if (transitionTimer) clearTimeout(transitionTimer);
  identity = email;
  change("session", true);
}

export function observeSession(email: string | null) {
  if (identity !== undefined && identity !== email) change("session");
  identity = email;
}

export function sessionTransitionInProgress() { return transition; }

export function markSessionLost() {
  if (identity !== null) {
    identity = null;
    change("session", true);
  }
}

export function announceTrackingChange() { initialize(); change("tracking", true); }

export function noteAuthenticatedResponse() { if (identity === null) identity = undefined; }
