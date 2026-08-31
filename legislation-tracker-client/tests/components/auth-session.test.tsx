import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { usePathname, useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuthNav from "@/app/components/AuthNav";
import LoginPage from "@/app/login/page";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
}));

describe("cookie-backed web authentication", () => {
  const router = {
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
  };

  beforeEach(() => {
    vi.mocked(useRouter).mockReturnValue(router as never);
    vi.mocked(usePathname).mockReturnValue("/");
    localStorage.clear();
    vi.clearAllMocks();
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
  });

  it("signs in with a cookie session without writing JWTs to localStorage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url, init) => {
      requests.push({ url: String(url), init });
      if (requests.length === 1) {
        return Response.json({ authenticated: false }, { status: 401 });
      }
      if (String(url).endsWith("/api/auth/csrf/")) {
        return Response.json({ csrf_token: "csrf-test-token" });
      }
      return Response.json({
        authenticated: true,
        user: { email: "person@example.com" },
      });
    }));

    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "person@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "secure-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    const loginRequest = requests.find(
      (request) =>
        request.url === "http://api.test/api/auth/session/" &&
        request.init?.method === "POST",
    );
    expect(loginRequest?.init?.credentials).toBe("include");
    expect(setItem).not.toHaveBeenCalled();
  });

  it("uses the server session to render and perform logout", async () => {
    document.cookie = "csrftoken=csrf-test-token";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url, init) => {
      requests.push({ url: String(url), init });
      if (init?.method === "POST") return new Response(null, { status: 204 });
      return Response.json({
        authenticated: true,
        user: { email: "person@example.com" },
      });
    }));

    render(<AuthNav />);
    fireEvent.click(await screen.findByRole("button", { name: "Log out" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    const logoutRequest = requests.find((request) =>
      request.url.endsWith("/api/auth/session/logout/"),
    );
    expect(logoutRequest?.init?.credentials).toBe("include");
    expect(new Headers(logoutRequest?.init?.headers).get("X-CSRFToken")).toBe(
      "csrf-test-token",
    );
  });
});
