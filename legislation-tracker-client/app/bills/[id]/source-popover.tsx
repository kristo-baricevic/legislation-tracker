"use client";

import { createContext, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useReaderPanelVisible } from "./reader-tabs";

// Portals are outside their parent's DOM subtree, but still belong to its disclosure.
const SourceAncestors = createContext<string[]>([]);

export function SourcePopover({ children, number = 1, onOpen, label }: { children: ReactNode; number?: number; onOpen?: () => void; label?: string }) {
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();
  const ancestors = useContext(SourceAncestors);
  const visible = useReaderPanelVisible();
  useEffect(() => {
    if (!visible) { setPosition(null); return; }
    if (!position) return;
    panel.current?.focus({ preventScroll: true });
    const anchorRect = trigger.current?.getBoundingClientRect();
    function belongsToTree(target: EventTarget | null) {
      if (!(target instanceof Node)) return false;
      if (panel.current?.contains(target) || trigger.current?.contains(target)) return true;
      const element = target instanceof Element ? target : target.parentElement;
      return element?.closest("[data-source-ancestors]")?.getAttribute("data-source-ancestors")?.split(" ").includes(id) ?? false;
    }
    function outside(event: PointerEvent) {
      if (!belongsToTree(event.target)) setPosition(null);
    }
    function key(event: KeyboardEvent) {
      // Only the innermost focused disclosure handles Escape and Tab.
      if (!panel.current?.contains(event.target as Node) && event.target !== trigger.current) return;
      if (event.key === "Escape") { event.preventDefault(); setPosition(null); trigger.current?.focus(); }
      if (event.key === "Tab" && panel.current) {
        const controls = Array.from(panel.current.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex='0']"));
        const atStart = event.target === panel.current || event.target === controls[0];
        const atEnd = event.target === controls.at(-1);
        if ((event.shiftKey && atStart) || (!event.shiftKey && atEnd)) {
          event.preventDefault();
          setPosition(null);
          const anchor = trigger.current;
          const parentPanel = anchor?.closest("[data-source-ancestors]") ?? null;
          const scope = parentPanel ?? document;
          const nextControls = Array.from(scope.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea, [tabindex]"))
            .filter(element => element.tabIndex >= 0 && !element.matches(":disabled") &&
              !element.closest("[hidden], [inert]") && element.closest("[data-source-ancestors]") === parentPanel);
          const next = anchor ? nextControls[nextControls.indexOf(anchor) + 1] : undefined;
          // Resume at the citation's logical successor, not at the end of the portal.
          (event.shiftKey ? anchor : next ?? anchor)?.focus();
        }
      }
    }
    function focusOutside(event: FocusEvent) { if (!belongsToTree(event.target)) setPosition(null); }
    function dismiss() {
      if (belongsToTree(document.activeElement)) trigger.current?.focus({ preventScroll: true });
      setPosition(null);
    }
    function scroll(event: Event) {
      const currentRect = trigger.current?.getBoundingClientRect();
      // A scroll queued before opening (including browser click auto-scroll) must
      // not immediately close the new disclosure.
      if (!belongsToTree(event.target) && currentRect && anchorRect &&
        (currentRect.top !== anchorRect.top || currentRect.left !== anchorRect.left)) dismiss();
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    document.addEventListener("focusin", focusOutside);
    window.addEventListener("scroll", scroll, true);
    window.addEventListener("resize", dismiss);
    return () => {
      document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", key);
      document.removeEventListener("focusin", focusOutside); window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", dismiss);
    };
  }, [position, visible, id]);
  return <>
    <button ref={trigger} type="button" aria-label={label ?? `Source ${number}`} aria-haspopup="dialog" aria-expanded={!!position} aria-controls={position ? id : undefined}
      className="mx-1 inline-flex rounded px-1 text-sm font-semibold text-blue-900 hover:bg-blue-50 focus-visible:outline-2 dark:text-green-300 dark:hover:bg-green-900"
      onClick={() => {
        if (position) { setPosition(null); return; }
        const rect = trigger.current!.getBoundingClientRect();
        setPosition({ top: Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - 300)), left: Math.max(8, Math.min(rect.left, window.innerWidth - Math.min(400, window.innerWidth - 16) - 8)) });
        onOpen?.();
      }}>[{number}]</button>
    {position && visible && createPortal(<div ref={panel} id={id} data-source-ancestors={ancestors.join(" ")} role="dialog" aria-label={label ?? `Source ${number}`} tabIndex={-1}
      style={{ top: position.top, left: position.left, width: "min(400px, calc(100vw - 16px))", maxHeight: `min(400px, calc(100dvh - ${position.top + 8}px))` }}
      className="fixed z-[100] overflow-y-auto rounded-lg border border-slate-300 bg-white p-4 text-sm text-slate-900 shadow-xl dark:border-green-700 dark:bg-slate-950 dark:text-green-100">
      <div className="mb-3 flex items-center justify-between"><strong>Source {number}</strong><button type="button" aria-label="Close source" onClick={() => { setPosition(null); trigger.current?.focus(); }} className="rounded px-2 py-1">✕</button></div>
      <SourceAncestors.Provider value={[...ancestors, id]}>{children}</SourceAncestors.Provider>
    </div>, document.body)}
  </>;
}
