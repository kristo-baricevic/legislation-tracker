import { afterEach, expect, it, vi } from "vitest";
import {
  capturePersonalizedScope, getMyTracking, login, subscribePersonalizedChanges,
  trackBill, trackLegislator,
} from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

function deferredFollows(respectAbort = true) {
  document.cookie = "csrftoken=test";
  const bill = { id: 1, jurisdiction: "federal", session: 119, bill_number: "HR 1", title: "Health reporting", status: "introduced", sponsor_name: null, sponsor_id: null, sponsor_bioguide_id: null, congress_gov_url: null, introduced_at: null, last_action_at: null, topics: [], search_rank: null, highlights: [] };
  const representative = { id: 2, bioguide_id: "T000002", name: "Test Member", chamber: "house", state: "NY", party: "", district: "1", first_name: "Test", last_name: "Member", official_website_url: null, image_url: null, is_current: true };
  const followedBill = { id: 1, bill, created_at: "2026-10-12T00:00:00Z" };
  const followedRepresentative = { id: 2, representative, created_at: "2026-10-12T00:00:00Z" };
  const pending = new Map<string, { signal?: AbortSignal | null; save: () => void }>();
  const saved = { bills: [] as number[], legislators: [] as number[] };
  vi.stubGlobal("fetch", vi.fn((url, options?: RequestInit) => {
    const path = new URL(String(url)).pathname;
    if (path === "/api/auth/csrf/") return Promise.resolve(Response.json({ csrf_token: "test" }));
    if (path === "/api/auth/session/") return Promise.resolve(Response.json({ authenticated: true, user: { email: "b@example.com" } }));
    if (path === "/api/tracking/") return Promise.resolve(Response.json({
      bills: saved.bills.map(() => followedBill),
      legislators: saved.legislators.map(() => followedRepresentative),
      topics: [], is_staff: false,
    }));
    if (!["/api/tracking/bills/", "/api/tracking/legislators/"].includes(path) || options?.method !== "POST") throw new Error(`Unexpected request: ${path}`);
    return new Promise<Response>((resolve, reject) => {
      const abort = () => reject(new DOMException("Request aborted", "AbortError"));
      if (respectAbort) options.signal?.addEventListener("abort", abort, { once: true });
      pending.set(path, { signal: options.signal, save: () => {
        // A backend write can commit even after the browser aborts its request.
        if (path === "/api/tracking/bills/") saved.bills.push(1);
        else saved.legislators.push(2);
        options.signal?.removeEventListener("abort", abort);
        resolve(Response.json(path === "/api/tracking/bills/" ? followedBill : followedRepresentative));
      } });
    });
  }));
  return pending;
}

it.each([
  { first: "bills", second: "legislators", firstId: 1, secondId: 2, firstSnapshot: { bills: [1], representatives: [] } },
  { first: "legislators", second: "bills", firstId: 2, secondId: 1, firstSnapshot: { bills: [], representatives: [2] } },
])("reloads both overlapping saved follows when $first finishes first and recommendation reads abort", async ({ first, second, firstId, secondId, firstSnapshot }) => {
  const pending = deferredFollows();
  const scope = capturePersonalizedScope();
  const reads = new AbortController();
  const snapshots: Array<{ bills: number[]; representatives: number[] }> = [];
  const unsubscribe = subscribePersonalizedChanges(change => {
    reads.abort(); // useRecommendations invalidates its read controller here.
    if (change.kind === "tracking") void getMyTracking({ scope: change.scope }).then(summary => snapshots.push({
      bills: summary.bills.map(item => item.bill.id),
      representatives: summary.legislators.map(item => item.representative.id),
    }));
  });
  try {
    const requests: Record<string, Promise<unknown>> = {
      bills: trackBill(1, { scope, signal: reads.signal }).catch(error => error),
      legislators: trackLegislator(2, { scope, signal: reads.signal }).catch(error => error),
    };
    await vi.waitFor(() => expect(pending.size).toBe(2));
    pending.get(`/api/tracking/${first}/`)!.save();
    expect(await requests[first]).toMatchObject({ id: firstId });
    await vi.waitFor(() => expect(snapshots).toEqual([firstSnapshot]));
    pending.get(`/api/tracking/${second}/`)!.save();
    expect(await requests[second]).toMatchObject({ id: secondId });
    await vi.waitFor(() => expect(snapshots).toEqual([
      firstSnapshot,
      { bills: [1], representatives: [2] },
    ]));
    expect(scope.interestGeneration).toBeLessThan(capturePersonalizedScope().interestGeneration);
  } finally { unsubscribe(); }
});

it("never announces A's remaining overlapping follow after the first saves and the account switches to B", async () => {
  const pending = deferredFollows(false); // Exercise the guards even if transport cannot be canceled.
  const scope = capturePersonalizedScope();
  const trackingChanges: number[] = [];
  const unsubscribe = subscribePersonalizedChanges(change => {
    if (change.kind === "tracking") trackingChanges.push(change.scope.interestGeneration);
  });
  try {
    const bill = trackBill(1, { scope }).catch(error => error);
    const representative = trackLegislator(2, { scope }).catch(error => error);
    await vi.waitFor(() => expect(pending.size).toBe(2));
    pending.get("/api/tracking/bills/")!.save();
    expect(await bill).toMatchObject({ id: 1 });
    expect(trackingChanges).toHaveLength(1);
    await login("b@example.com", "password");
    pending.get("/api/tracking/legislators/")!.save();
    expect(await representative).toMatchObject({ name: "AbortError" });
    expect(trackingChanges).toHaveLength(1);
  } finally { unsubscribe(); }
});

it("honors an explicit cancellation before interests change", async () => {
  const pending = deferredFollows();
  const controller = new AbortController();
  const bill = trackBill(1, { signal: controller.signal }).catch(error => error);
  await vi.waitFor(() => expect(pending.size).toBe(1));
  controller.abort();
  expect(await bill).toMatchObject({ name: "AbortError" });
  expect(pending.get("/api/tracking/bills/")!.signal?.aborted).toBe(true);
});
