"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function SourcePopover({ children, number = 1, onOpen, label }: { children: ReactNode; number?: number; onOpen?: () => void; label?: string }) {
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!position) return;
    panel.current?.focus();
    function outside(event: PointerEvent) {
      if (!panel.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setPosition(null);
    }
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") { setPosition(null); trigger.current?.focus(); }
    }
    function dismiss() { setPosition(null); }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", dismiss);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", key); window.removeEventListener("resize", dismiss); };
  }, [position]);
  return <>
    <button ref={trigger} type="button" aria-label={label ?? `Source ${number}`} aria-haspopup="dialog" aria-expanded={!!position} aria-controls={position ? id : undefined}
      className="mx-1 inline-flex rounded px-1 text-sm font-semibold text-blue-900 hover:bg-blue-50 focus-visible:outline-2 dark:text-green-300 dark:hover:bg-green-900"
      onClick={() => {
        if (position) { setPosition(null); return; }
        const rect = trigger.current!.getBoundingClientRect();
        setPosition({ top: Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - 300)), left: Math.max(8, Math.min(rect.left, window.innerWidth - Math.min(400, window.innerWidth - 16) - 8)) });
        onOpen?.();
      }}>[{number}]</button>
    {position && createPortal(<div ref={panel} id={id} role="dialog" aria-label={label ?? `Source ${number}`} tabIndex={-1}
      style={{ top: position.top, left: position.left, width: "min(400px, calc(100vw - 16px))", maxHeight: `min(400px, calc(100dvh - ${position.top + 8}px))` }}
      className="fixed z-[100] overflow-y-auto rounded-lg border border-slate-300 bg-white p-4 text-sm text-slate-900 shadow-xl dark:border-green-700 dark:bg-slate-950 dark:text-green-100">
      <div className="mb-3 flex items-center justify-between"><strong>Source {number}</strong><button type="button" aria-label="Close source" onClick={() => { setPosition(null); trigger.current?.focus(); }} className="rounded px-2 py-1">✕</button></div>
      {children}
    </div>, document.body)}
  </>;
}
