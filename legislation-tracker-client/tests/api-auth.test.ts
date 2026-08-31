import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import * as api from "../lib/api.ts";

const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;
const originalFetch = globalThis.fetch;
const originalNavigator = globalThis.navigator;

function installBrowserState() {
  const writes: Array<[string, string]> = [];
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) =>
        key === "legislation_tracker_refresh" ? "browser-refresh-jwt" : null,
      setItem: (key: string, value: string) => writes.push([key, value]),
      removeItem: () => undefined,
    },
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: { cookie: "csrftoken=csrf-test-token" },
  });
  return writes;
}

afterEach(() => {
  process.env.NEXT_PUBLIC_API_URL = originalApiUrl;
  globalThis.fetch = originalFetch;
  Reflect.deleteProperty(globalThis, "localStorage");
  Reflect.deleteProperty(globalThis, "document");
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: originalNavigator,
  });
});

describe("web session API helpers", () => {
  it("logs in through the credentialed cookie session endpoint without returning JWTs", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    installBrowserState();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      if (String(url).endsWith("/api/auth/csrf/")) {
        return Response.json({ csrf_token: "csrf-test-token" });
      }
      return Response.json({
        authenticated: true,
        user: { email: "person@example.com" },
      });
    };

    const result = await api.login(" PERSON@example.com ", "secure-password");

    assert.deepEqual(result, {
      authenticated: true,
      user: { email: "person@example.com" },
    });
    assert.equal(requests[0].url, "http://api.test/api/auth/csrf/");
    assert.equal(requests[0].init?.credentials, "include");
    assert.equal(requests[1].url, "http://api.test/api/auth/session/");
    assert.equal(requests[1].init?.credentials, "include");
    assert.equal(
      new Headers(requests[1].init?.headers).get("X-CSRFToken"),
      "csrf-test-token",
    );
    assert.equal(
      requests[1].init?.body,
      JSON.stringify({ email: "person@example.com", password: "secure-password" }),
    );
  });

  it("loads and logs out the current session using cookies plus CSRF", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    installBrowserState();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      if (init?.method === "POST") return new Response(null, { status: 204 });
      return Response.json({ authenticated: true, user: { email: "person@example.com" } });
    };
    const sessionApi = api as typeof api & {
      getSession: () => Promise<{ authenticated: boolean }>;
      logout: () => Promise<void>;
    };

    const session = await sessionApi.getSession();
    await sessionApi.logout();

    assert.equal(session?.authenticated, true);
    assert.equal(requests[0].url, "http://api.test/api/auth/session/current/");
    assert.equal(requests[0].init?.credentials, "include");
    assert.equal(requests[1].url, "http://api.test/api/auth/session/logout/");
    assert.equal(requests[1].init?.method, "POST");
    assert.equal(requests[1].init?.credentials, "include");
    assert.equal(
      new Headers(requests[1].init?.headers).get("X-CSRFToken"),
      "csrf-test-token",
    );
  });

  it("refreshes an expired cookie session and retries without reading or writing JWT storage", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    const writes = installBrowserState();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      if (requests.length === 1) {
        return Response.json({ detail: "expired" }, { status: 401 });
      }
      if (requests.length === 2) {
        return Response.json({ authenticated: true });
      }
      return Response.json({ bills: [], topics: [], legislators: [] });
    };

    const result = await api.authGet("/api/tracking/");

    assert.deepEqual(result, { bills: [], topics: [], legislators: [] });
    assert.equal(requests[0].init?.credentials, "include");
    assert.equal(requests[1].url, "http://api.test/api/auth/session/refresh/");
    assert.equal(requests[1].init?.method, "POST");
    assert.equal(
      new Headers(requests[1].init?.headers).get("X-CSRFToken"),
      "csrf-test-token",
    );
    assert.equal(requests[2].url, "http://api.test/api/tracking/");
    assert.deepEqual(writes, []);
  });

  it("serializes cookie rotation across browser tabs with a named Web Lock", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    installBrowserState();
    const lockNames: string[] = [];
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: {
        locks: {
          request: async <T>(name: string, callback: () => Promise<T>) => {
            lockNames.push(name);
            return callback();
          },
        },
      },
    });
    let requestCount = 0;
    globalThis.fetch = async () => {
      requestCount += 1;
      if (requestCount === 1) {
        return Response.json({ detail: "expired" }, { status: 401 });
      }
      if (requestCount === 2) {
        return Response.json({ authenticated: true });
      }
      return Response.json({ bills: [], topics: [], legislators: [] });
    };

    await api.authGet("/api/tracking/");

    assert.deepEqual(lockNames, ["legislation-tracker-auth-refresh"]);
  });

  it("sends CSRF on unsafe authenticated requests", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    installBrowserState();
    let request: { url: string; init?: RequestInit } | undefined;
    globalThis.fetch = async (url, init) => {
      request = { url: String(url), init };
      return Response.json({ id: 1 });
    };

    await api.authPost("/api/tracking/topics/", { topic: 4 });

    assert.equal(request?.init?.credentials, "include");
    assert.equal(
      new Headers(request?.init?.headers).get("X-CSRFToken"),
      "csrf-test-token",
    );
    assert.equal(new Headers(request?.init?.headers).has("Authorization"), false);
  });

  it("uses the CSRF bootstrap response when the API cookie is on another host", async () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.test";
    installBrowserState();
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { cookie: "" },
    });
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ url: String(url), init });
      if (requests.length === 1) {
        return Response.json({ csrf_token: "cross-origin-csrf" });
      }
      return Response.json({ id: 1 });
    };

    await api.login("person@example.com", "secure-password");

    assert.equal(requests[0].url, "https://api.example.test/api/auth/csrf/");
    assert.equal(
      new Headers(requests[1].init?.headers).get("X-CSRFToken"),
      "cross-origin-csrf",
    );
  });
});
