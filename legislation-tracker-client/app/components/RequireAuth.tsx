"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getStoredAccessToken } from "../../lib/api";

/**
 * Redirects to /login if the user is not signed in. Renders children once auth is confirmed.
 */
export default function RequireAuth({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    if (!getStoredAccessToken()) {
      router.replace("/login");
      return;
    }
    setAllowed(true);
  }, [router]);

  if (!allowed) {
    return null; // or a small "Redirecting…" while checking
  }

  return <>{children}</>;
}
