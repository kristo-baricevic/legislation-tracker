"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getSession } from "../../lib/api";

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
    let active = true;
    getSession()
      .then((session) => {
        if (!active) return;
        if (!session) {
          router.replace("/login");
          return;
        }
        setAllowed(true);
      })
      .catch(() => {
        if (active) router.replace("/login");
      });
    return () => {
      active = false;
    };
  }, [router]);

  if (!allowed) {
    return null; // or a small "Redirecting…" while checking
  }

  return <>{children}</>;
}
