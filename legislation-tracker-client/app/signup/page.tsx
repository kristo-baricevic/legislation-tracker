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
    <div className="flex min-h-screen flex-col items-center justify-center bg-black px-4 py-12 font-mono text-green-300">
      <div className="w-full max-w-sm rounded border border-green-800 bg-green-950/20 p-8">
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
              className="rounded border border-green-800 bg-black px-3 py-2 text-green-200 outline-none focus:border-green-500"
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
              className="rounded border border-green-800 bg-black px-3 py-2 text-green-200 outline-none focus:border-green-500"
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
              className="rounded border border-green-800 bg-black px-3 py-2 text-green-200 outline-none focus:border-green-500"
            />
          </label>
          {error && (
            <p className="text-sm text-red-400" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="mt-2 rounded bg-green-800 px-4 py-2 font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {loading ? "Creating account…" : "Create account"}
          </button>
        </form>
        <p className="mt-6 text-center text-sm text-green-500/80">
          Already have an account?{" "}
          <Link href="/login" className="underline hover:text-green-400">
            Log in
          </Link>
        </p>
      </div>
      <p className="mt-4 text-xs text-green-700">
        API: {getApiBase()}
      </p>
    </div>
  );
}
