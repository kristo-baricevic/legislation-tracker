"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getSession, logout } from "../../lib/api";

export default function AuthNav() {
  const router = useRouter();
  const pathname = usePathname();
  const [hasSession, setHasSession] = useState(false);

  useEffect(() => {
    let active = true;
    getSession()
      .then((session) => {
        if (active) setHasSession(Boolean(session));
      })
      .catch(() => {
        if (active) setHasSession(false);
      });
    return () => {
      active = false;
    };
  }, [pathname]);

  const handleLogout = async () => {
    try {
      await logout();
      setHasSession(false);
      router.push("/");
      router.refresh();
    } catch {
      // Keep the authenticated navigation visible so the user can retry.
    }
  };

  return (
    <nav className="flex flex-wrap items-center gap-x-4 gap-y-2 font-mono text-sm text-slate-800 dark:text-green-400">
      <Link href="/" className="cursor-pointer hover:text-blue-900 dark:hover:text-green-300">
        Home
      </Link>
      <Link href="/bills" className="cursor-pointer hover:text-blue-900 dark:hover:text-green-300">
        Bills
      </Link>
      <Link href="/topics" className="cursor-pointer hover:text-blue-900 dark:hover:text-green-300">
        Topics
      </Link>
      <Link
        href="/representatives"
        className="cursor-pointer hover:text-blue-900 dark:hover:text-green-300"
      >
        Representatives
      </Link>
      {hasSession ? (
        <>
          <Link
            href="/settings"
            className="cursor-pointer hover:text-blue-900 hover:underline dark:hover:text-green-300"
          >
            Settings
          </Link>
          <button
            type="button"
            onClick={handleLogout}
            className="cursor-pointer hover:text-blue-900 hover:underline dark:hover:text-green-300"
          >
            Log out
          </button>
        </>
      ) : (
        <>
          <Link
            href="/login"
            className="cursor-pointer hover:text-blue-900 hover:underline dark:hover:text-green-300"
          >
            Log in
          </Link>
          <Link
            href="/signup"
            className="cursor-pointer hover:text-blue-900 hover:underline dark:hover:text-green-300"
          >
            Sign up
          </Link>
        </>
      )}
    </nav>
  );
}
