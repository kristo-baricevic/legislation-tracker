"use client";
import { useLayoutEffect, useRef, type ReactNode } from "react";

/** Keep pagination below results stationary, including a short final page. */
export default function RetainedHeight({ children }: { children: ReactNode }) {
  const frame = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const outer = frame.current, inner = content.current;
    if (!outer || !inner) return;
    let width = 0, height = 0;
    const measure = () => {
      const rect = inner.getBoundingClientRect();
      if (Math.abs(rect.width - width) > 1) { width = rect.width; height = 0; }
      height = Math.max(height, rect.height);
      outer.style.minHeight = `${height}px`;
      // Keep a short replacement page in view at the reader's existing scroll
      // position, rather than reserving an empty screen above the pager.
      inner.style.top = `${Math.min(16, window.innerHeight - rect.height - 80)}px`;
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(inner);
    window.addEventListener("resize", measure);
    return () => { observer.disconnect(); window.removeEventListener("resize", measure); };
  }, []);
  return <div ref={frame}><div ref={content} style={{ position: "sticky" }}>{children}</div></div>;
}
