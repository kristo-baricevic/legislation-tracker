"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { FinancialAction } from "@/lib/contracts";
import { financialGlossary } from "@/lib/financial-glossary";

export function ProvisionType({ action }: { action: FinancialAction }) {
  const { label, definition } = financialGlossary[action];
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const tooltip = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  function show() { clearTimeout(timer.current); setOpen(true); }
  function leave() {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      if (document.activeElement !== button.current) setOpen(false);
    }, 120);
  }
  useEffect(() => () => clearTimeout(timer.current), []);
  useLayoutEffect(() => {
    if (!open || !button.current || !tooltip.current) return;
    const anchor = button.current.getBoundingClientRect();
    const box = tooltip.current.getBoundingClientRect();
    setPosition({
      left: Math.max(8, Math.min(anchor.left, window.innerWidth - box.width - 8)),
      top: anchor.bottom + box.height + 8 <= window.innerHeight
        ? anchor.bottom + 6 : Math.max(8, anchor.top - box.height - 6),
    });
    function dismiss() { setOpen(false); }
    function outside(event: PointerEvent) {
      if (!button.current?.contains(event.target as Node) && !tooltip.current?.contains(event.target as Node)) dismiss();
    }
    function key(event: KeyboardEvent) { if (event.key === "Escape") dismiss(); }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", dismiss, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("scroll", dismiss, true);
    };
  }, [open]);
  return <div className="flex items-center gap-1">
    <p className="font-semibold text-slate-950 dark:text-green-300">{label}</p>
    <button ref={button} type="button" aria-label={`What does ${label} mean?`} aria-describedby={open ? id : undefined}
      onMouseEnter={show} onMouseLeave={leave} onFocus={show} onBlur={() => setOpen(false)} onClick={show}
      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-slate-500 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 dark:text-green-500 dark:hover:text-green-200">
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="9" /><path d="M12 11v6" /><circle cx="12" cy="7.5" r=".7" fill="currentColor" stroke="none" /></svg>
    </button>
    {open && createPortal(<div ref={tooltip} id={id} role="tooltip" onMouseEnter={show} onMouseLeave={leave}
      style={{ ...position, width: "min(288px, calc(100vw - 16px))" }}
      className="fixed z-[110] rounded-lg border border-slate-300 bg-white p-3 text-sm leading-5 text-slate-800 shadow-md dark:border-green-800 dark:bg-slate-950 dark:text-green-200">
      {definition}
    </div>, document.body)}
  </div>;
}
