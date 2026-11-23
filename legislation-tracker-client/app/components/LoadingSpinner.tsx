"use client";

import { useEffect, useState } from "react";

export default function LoadingSpinner({ active = true, label = "Loading…", reserveSpace = false, centered = false }: { active?: boolean; label?: string; reserveSpace?: boolean; centered?: boolean }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    setVisible(false);
    if (!active) return;
    const timer = setTimeout(() => setVisible(true), 250);
    return () => clearTimeout(timer);
  }, [active]);

  const indicator = active && visible ? <div role="status" aria-label={label.replace(/…$/, "")} className={centered ? "pointer-events-none fixed inset-0 z-40 flex items-center justify-center" : "flex items-center justify-center py-2"}>
    <span aria-hidden="true" className="h-5 w-5 rounded-full border-2 border-control border-t-ink motion-safe:animate-spin" />
  </div> : null;
  return reserveSpace && !centered ? <div className="min-h-10">{indicator}</div> : indicator;
}
