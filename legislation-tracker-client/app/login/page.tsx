"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getApiBase, getSession, login } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Redirect to home if already signed in
  useEffect(() => {
    let active = true;
    getSession()
      .then((session) => {
        if (active && session) router.replace("/");
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] w-full bg-background px-4 py-8 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-8">
      <div className="flex min-h-[calc(100vh-8rem)] w-full flex-col items-center justify-center">
        <div className="w-full max-w-md rounded border border-slate-400/80 bg-white/90 p-6 shadow-sm dark:border-green-800 dark:bg-green-950/20 dark:shadow-none sm:p-8">
          <h1 className="mb-6 text-xl font-semibold">Log in</h1>
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
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
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
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>
          <p className="mt-6 text-center text-sm text-slate-600 dark:text-green-500/80">
            No account?{" "}
            <Link
              href="/signup"
              className="cursor-pointer text-blue-900 underline hover:text-blue-950 dark:text-green-400 dark:hover:text-green-300"
            >
              Sign up
            </Link>
          </p>
        </div>
        <p className="mt-4 text-center text-xs text-slate-600 dark:text-green-700">
          API: {getApiBase()}
        </p>
      </div>
    </div>
  );
}
