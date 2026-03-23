"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getApiBase, getStoredAccessToken, login, register, setStoredTokens } from "../../lib/api";

export default function SignUpPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Redirect to home if already signed in
  useEffect(() => {
    if (getStoredAccessToken()) {
      router.replace("/");
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setLoading(true);
    try {
      await register(email, password);
      const { access, refresh } = await login(email, password);
      setStoredTokens(access, refresh);
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign up failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12 font-mono text-slate-900 dark:text-green-300">
      <div className="w-full max-w-sm rounded border border-slate-400/80 bg-white/90 p-8 shadow-sm dark:border-green-800 dark:bg-green-950/20 dark:shadow-none">
        <h1 className="mb-6 text-xl font-semibold">Sign up</h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="rounded border border-slate-400 bg-white px-3 py-2 text-slate-900 outline-none focus:border-blue-800 dark:border-green-800 dark:bg-black dark:text-green-200 dark:focus:border-green-500"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Password (min 8 characters)
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
              className="rounded border border-slate-400 bg-white px-3 py-2 text-slate-900 outline-none focus:border-blue-800 dark:border-green-800 dark:bg-black dark:text-green-200 dark:focus:border-green-500"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Confirm password
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              autoComplete="new-password"
              className="rounded border border-slate-400 bg-white px-3 py-2 text-slate-900 outline-none focus:border-blue-800 dark:border-green-800 dark:bg-black dark:text-green-200 dark:focus:border-green-500"
            />
          </label>
          {error && (
            <p className="text-sm text-red-700 dark:text-red-400" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="mt-2 cursor-pointer rounded bg-slate-800 px-4 py-2 font-medium text-white hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-green-800 dark:hover:bg-green-700"
          >
            {loading ? "Creating account…" : "Create account"}
          </button>
        </form>
        <p className="mt-6 text-center text-sm text-slate-600 dark:text-green-500/80">
          Already have an account?{" "}
          <Link
            href="/login"
            className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
          >
            Log in
          </Link>
        </p>
      </div>
      <p className="mt-4 text-xs text-slate-600 dark:text-green-700">
        API: {getApiBase()}
      </p>
    </div>
  );
}
