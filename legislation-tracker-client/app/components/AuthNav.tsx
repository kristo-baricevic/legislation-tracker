"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getSession, logout } from "../../lib/api";
import { dashboardSession } from "@/lib/dashboard-cache";

export default function AuthNav() {
  const router = useRouter();
  const pathname = usePathname();
  const [hasSession, setHasSession] = useState<boolean | null>(null);
  const linkState = (href: string) => {
    const active = href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
    return { "aria-current": active ? "page" as const : undefined, className: `cursor-pointer border-b-2 py-1 hover:text-ink ${active ? "border-current font-semibold" : "border-transparent"}` };
  };

  useEffect(() => {
    let active = true;
    (pathname === "/" ? dashboardSession() : getSession())
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
      <Link href="/" {...linkState("/")}>
        Home
      </Link>
      <Link href="/bills" {...linkState("/bills")}>
        Bills
      </Link>
      <Link
        href="/representatives"
        {...linkState("/representatives")}
      >
        Representatives
      </Link>
      <Link href="/topics" {...linkState("/topics")}>
        Topics
      </Link>
      <Link href="/committees" {...linkState("/committees")}>
        Committees
      </Link>
      <span className="inline-flex h-8 w-32 shrink-0 items-center gap-4">
      {hasSession === null ? <span className="inline-block w-32" aria-label="Loading account" aria-busy="true" /> : hasSession ? (
        <>
          <Link
            href="/settings"
            {...linkState("/settings")}
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
            {...linkState("/login")}
          >
            Log in
          </Link>
          <Link
            href="/signup"
            {...linkState("/signup")}
          >
            Sign up
          </Link>
        </>
      )}
      </span>
    </nav>
  );
}
