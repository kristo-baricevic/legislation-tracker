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
    <nav className="flex flex-wrap items-center gap-x-4 gap-y-2 font-sans text-sm text-ink">
      <Link href="/" className="cursor-pointer hover:text-ink">
        Home
      </Link>
      <Link href="/bills" className="cursor-pointer hover:text-ink">
        Bills
      </Link>
      <Link href="/topics" className="cursor-pointer hover:text-ink">
        Topics
      </Link>
      <Link
        href="/representatives"
        className="cursor-pointer hover:text-ink"
      >
        Representatives
      </Link>
      {hasSession ? (
        <>
          <Link
            href="/settings"
            className="cursor-pointer hover:text-ink hover:underline"
          >
            Settings
          </Link>
          <button
            type="button"
            onClick={handleLogout}
            className="cursor-pointer hover:text-ink hover:underline"
          >
            Log out
          </button>
        </>
      ) : (
        <>
          <Link
            href="/login"
            className="cursor-pointer hover:text-ink hover:underline"
          >
            Log in
          </Link>
          <Link
            href="/signup"
            className="cursor-pointer hover:text-ink hover:underline"
          >
            Sign up
          </Link>
        </>
      )}
    </nav>
  );
}
