import { afterEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import {
  authGet, capturePersonalizedScope, isPersonalizedScopeCurrent, login,
  logout, subscribePersonalizedChanges, trackBill,
} from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

describe("personalized request generations", () => {
  it("keeps an in-flight private request valid when focus returns without an account change", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
    const pending = authGet("/api/private/");
    window.dispatchEvent(new Event("focus"));
    finish(Response.json({ ok: true }));
    await expect(pending).resolves.toEqual({ ok: true });
  });
  it("invalidates a captured scope after a successful follow", async () => {
    document.cookie = "csrftoken=test";
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ id: 1 })));
    const scope = capturePersonalizedScope();
    await trackBill(1);
    expect(isPersonalizedScopeCurrent(scope)).toBe(false);
  });

  it("does not change interest generation when a follow fails", async () => {
    document.cookie = "csrftoken=test";
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "unavailable" }, { status: 503 })));
    const scope = capturePersonalizedScope();
    await expect(trackBill(1)).rejects.toThrow("unavailable");
    expect(isPersonalizedScopeCurrent(scope)).toBe(true);
  });

  it("clears subscribers immediately when logout starts", async () => {
    document.cookie = "csrftoken=test";
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
    const changes: string[] = [];
    const unsubscribe = subscribePersonalizedChanges(change => changes.push(change.kind));
    const pending = logout();
    expect(changes).toContain("session");
    await Promise.resolve();
    finish(new Response(null, { status: 204 }));
    await pending;
    unsubscribe();
  });

  it("rejects a late private response after account change", async () => {
    document.cookie = "csrftoken=test";
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn((url) => {
      if (String(url).includes("/api/private/")) return new Promise<Response>(resolve => { finish = resolve; });
      if (String(url).endsWith("csrf/")) return Promise.resolve(Response.json({ csrf_token: "test" }));
      return Promise.resolve(Response.json({ authenticated: true, user: { email: "b@example.com" } }));
    }));
    const pending = authGet("/api/private/");
    await login("b@example.com", "password");
    finish(Response.json({ private: "owner A" }));
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("does not refresh or replay A's 401 under B", async () => {
    document.cookie = "csrftoken=test";
    let finish!: (response: Response) => void;
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url) => {
      requests.push(String(url));
      if (String(url).includes("/api/private/")) return new Promise<Response>(resolve => { finish = resolve; });
      if (String(url).endsWith("csrf/")) return Promise.resolve(Response.json({ csrf_token: "test" }));
      return Promise.resolve(Response.json({ authenticated: true, user: { email: "b@example.com" } }));
    }));
    const pending = authGet("/api/private/");
    await login("b@example.com", "password");
    finish(Response.json({ detail: "expired" }, { status: 401 }));
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(requests.some(url => url.includes("/refresh/"))).toBe(false);
    expect(requests.filter(url => url.includes("/api/private/"))).toHaveLength(1);
  });

  it("does not post a follow after CSRF completes under a changed account", async () => {
    document.cookie = "csrftoken=; Max-Age=0";
    let finish!: (response: Response) => void;
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(url => {
      requests.push(String(url));
      return new Promise<Response>(resolve => { finish = resolve; });
    }));
    const pending = trackBill(1);
    await Promise.resolve();
    localStorage.setItem("legislation-tracker-session-epoch", "stable:csrf-race");
    finish(Response.json({ csrf_token: "late" }));
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(requests.filter(url => url.includes("/tracking/bills/"))).toHaveLength(0);
  });

  it("honors AbortSignal before refresh and replay", async () => {
    document.cookie = "csrftoken=test";
    const controller = new AbortController();
    let finish!: (response: Response) => void;
    const fetch = vi.fn(() => new Promise<Response>(resolve => { finish = resolve; }));
    vi.stubGlobal("fetch", fetch);
    const pending = authGet("/api/private/", { signal: controller.signal });
    controller.abort();
    finish(Response.json({ detail: "expired" }, { status: 401 }));
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("does not wedge login when the window regains focus during POST", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(url => String(url).endsWith("/csrf/")
      ? Promise.resolve(Response.json({ csrf_token: "test" }))
      : new Promise<Response>(resolve => { finish = resolve; })));
    const pending = login("focus@example.com", "password");
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    window.dispatchEvent(new Event("focus"));
    await Promise.resolve();
    finish(Response.json({ authenticated: true, user: { email: "focus@example.com" } }));
    await expect(pending).resolves.toMatchObject({ user: { email: "focus@example.com" } });
    expect(isPersonalizedScopeCurrent(capturePersonalizedScope())).toBe(true);
  });

  it("keeps shared refresh alive when its first UI caller aborts", async () => {
    document.cookie = "csrftoken=test";
    let complete!: (response: Response) => void, refreshSignal: AbortSignal | undefined;
    const seen = new Set<string>();
    vi.stubGlobal("fetch", vi.fn((url, init) => {
      const target = String(url);
      if (target.includes("/refresh/")) {
        refreshSignal = init?.signal;
        return new Promise<Response>(resolve => { complete = resolve; });
      }
      if (!seen.has(target)) { seen.add(target); return Promise.resolve(Response.json({ detail: "expired" }, { status: 401 })); }
      return Promise.resolve(Response.json({ ok: true }));
    }));
    const leader = new AbortController();
    const first = authGet("/api/first/", { signal: leader.signal });
    const second = authGet("/api/second/");
    await waitFor(() => expect(complete).toBeTypeOf("function"));
    leader.abort();
    expect(refreshSignal?.aborted).toBe(false);
    complete(Response.json({ authenticated: true }));
    await expect(first).rejects.toMatchObject({ name: "AbortError" });
    await expect(second).resolves.toEqual({ ok: true });
  });

  it("recovers an abandoned expired cross-tab transition with fresh session ownership", async () => {
    localStorage.setItem("legislation-tracker-session-epoch", `changing:${Date.now() - 1}:abandoned`);
    const scope = capturePersonalizedScope();
    expect(isPersonalizedScopeCurrent(scope)).toBe(true);
    vi.stubGlobal("fetch", vi.fn(async url => String(url).endsWith("/csrf/")
      ? Response.json({ csrf_token: "test" })
      : Response.json({ authenticated: true, user: { email: "recovered@example.com" } })));
    await expect(login("recovered@example.com", "password")).resolves.toMatchObject({ authenticated: true });
  });
});
