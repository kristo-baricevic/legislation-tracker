/**
 * Backend API base URL and auth helpers.
 * Set NEXT_PUBLIC_API_URL in .env.local (e.g. http://localhost:8000).
 */

const getApiUrl = () =>
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
    : process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const AUTH_TOKEN_KEY = "legislation_tracker_access";
const AUTH_REFRESH_KEY = "legislation_tracker_refresh";

export function getApiBase(): string {
  return getApiUrl().replace(/\/$/, "");
}

export function getStoredAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function getStoredRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_REFRESH_KEY);
}

export function setStoredTokens(access: string, refresh: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(AUTH_TOKEN_KEY, access);
  localStorage.setItem(AUTH_REFRESH_KEY, refresh);
}

export function clearStoredTokens(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_REFRESH_KEY);
}

export interface LoginResponse {
  access: string;
  refresh: string;
}

export interface RegisterResponse {
  id: number;
  email: string;
}

/** Login: send "email" (backend User.USERNAME_FIELD is email). */
export async function login(email: string, password: string): Promise<LoginResponse> {
  const base = getApiBase();
  const res = await fetch(`${base}/api/auth/token/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? data.error ?? "Login failed");
  }
  return res.json();
}

export async function register(email: string, password: string): Promise<RegisterResponse> {
  const base = getApiBase();
  const res = await fetch(`${base}/api/auth/register/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? "Registration failed");
  }
  return res.json();
}
