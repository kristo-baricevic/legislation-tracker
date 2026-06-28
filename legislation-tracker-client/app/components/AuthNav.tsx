"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearStoredTokens, getStoredAccessToken } from "../../lib/api";

export default function AuthNav() {
  const router = useRouter();
  const pathname = usePathname();
  const [hasToken, setHasToken] = useState(false);

  // Re-check token on mount and when route changes (e.g. after login redirect)
  useEffect(() => {
    setHasToken(!!getStoredAccessToken());
  }, [pathname]);

  const handleLogout = () => {
    clearStoredTokens();
    setHasToken(false);
    router.push("/");
    router.refresh();
  };

  return (
    <nav className="flex items-center gap-4 font-mono text-sm text-slate-800 dark:text-green-400">
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
      {hasToken ? (
        <button
          type="button"
          onClick={handleLogout}
          className="cursor-pointer hover:text-blue-900 hover:underline dark:hover:text-green-300"
        >
          Log out
        </button>
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
