"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";

/** Only the results scroll; changing pages never moves the surrounding controls. */
export function StableResults({ children, page, busy = false, label }: {
  children: ReactNode; page: string | number; busy?: boolean; label: string;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { if (viewport.current) viewport.current.scrollTop = 0; }, [page]);
  return <div ref={viewport} className="stable-results" role="region" aria-label={label} aria-busy={busy} tabIndex={0}>{children}</div>;
}
