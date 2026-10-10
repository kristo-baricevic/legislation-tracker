"use client";

import React from "react";
import { createPortal } from "react-dom";

type Entry = { node: HTMLDialogElement; opener: HTMLElement | null; close: () => void; identity: string; fallbackFocus?: () => void };
type Stack = { register: (entry: Entry) => () => void; isTop: (node: HTMLDialogElement) => boolean; contains: (identity: string) => boolean; canOpen: () => boolean; closeAll: () => void };
const Context = React.createContext<Stack | null>(null);
const controls = (node: HTMLElement) => [...node.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex='0']")].filter(control => !control.closest("[hidden], [inert], [aria-hidden='true']"));

export function ModalStackProvider({ children }: { children: React.ReactNode }) {
  const entries = React.useRef<Entry[]>([]);
  const overflow = React.useRef("");
  const pageOpener = React.useRef<HTMLElement | null>(null);
  const pageFallbackFocus = React.useRef<(() => void) | undefined>(undefined);
  const stack = React.useMemo<Stack>(() => ({
    register(entry) {
      if (!entries.current.length) { overflow.current = document.body.style.overflow; pageOpener.current = entry.opener; pageFallbackFocus.current = entry.fallbackFocus; document.body.style.overflow = "hidden"; }
      entries.current.push(entry);
      return () => {
        const index = entries.current.indexOf(entry);
        if (index < 0) return;
        const descendants = entries.current.slice(index + 1);
        entries.current = entries.current.slice(0, index);
        descendants.reverse().forEach(item => item.close());
        if (!entries.current.length) document.body.style.overflow = overflow.current;
        // Descendant close callbacks can schedule a second React commit. Restore
        // focus after those dialogs finish unmounting so their removal cannot
        // move focus back to the body.
        setTimeout(() => {
          const top = entries.current.at(-1);
          const target = top ? (entry.opener?.isConnected && top.node.contains(entry.opener) ? entry.opener : controls(top.node)[0]) : pageOpener.current;
          if (target?.isConnected && target !== document.body && !target.closest("[hidden], [inert], [aria-hidden='true'], dialog:not([open])")) {
            target.focus();
            if (document.activeElement === target) return;
          }
          if (top) { controls(top.node)[0]?.focus(); return; }
          pageFallbackFocus.current?.();
          const focused = document.activeElement;
          if (focused instanceof HTMLElement && focused !== document.body && focused.isConnected && !focused.closest("[hidden], [inert], [aria-hidden='true'], dialog")) return;
          controls(document.body).find(control => !control.closest("dialog"))?.focus();
        });
      };
    },
    isTop: node => entries.current.at(-1)?.node === node,
    contains: identity => entries.current.some(entry => entry.identity === identity),
    canOpen: () => entries.current.length < 4,
    closeAll: () => [...entries.current].reverse().forEach(entry => entry.close()),
  }), []);
  React.useEffect(() => () => { document.body.style.overflow = entries.current.length ? overflow.current : document.body.style.overflow; }, []);
  return <Context.Provider value={stack}>{children}</Context.Provider>;
}

export function useModalStack() { return React.useContext(Context); }

function ManagedDialog({ children, identity, titleId, className, onClose, fallbackFocus }: { children: React.ReactNode; identity: string; titleId: string; className: string; onClose: () => void; fallbackFocus?: () => void }) {
  const stack = React.useContext(Context)!;
  const dialog = React.useRef<HTMLDialogElement>(null);
  const opener = React.useRef<HTMLElement | null>(null);
  const close = React.useRef(onClose);
  const fallback = React.useRef(fallbackFocus);
  React.useLayoutEffect(() => { close.current = onClose; fallback.current = fallbackFocus; }, [onClose, fallbackFocus]);
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => { opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setMounted(true); }, []);
  React.useLayoutEffect(() => {
    if (!mounted) return;
    const node = dialog.current!;
    const unregister = stack.register({ node, identity, opener: opener.current, close: () => close.current(), fallbackFocus: () => fallback.current?.() });
    node.showModal();
    return () => { node.close(); unregister(); };
  }, [mounted, stack, identity]);
  if (!mounted) return null;
  return createPortal(<dialog ref={dialog} className={className} aria-labelledby={titleId} onCancel={event => { event.preventDefault(); event.stopPropagation(); if (stack.isTop(event.currentTarget)) close.current(); }} onKeyDown={event => {
    if (!stack.isTop(event.currentTarget) || event.key !== "Tab") return;
    const items = controls(event.currentTarget), first = items[0], last = items.at(-1);
    if (!first || !last) { event.preventDefault(); event.currentTarget.focus(); }
    else if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || document.activeElement === event.currentTarget)) { event.preventDefault(); first.focus(); }
  }} onClick={event => {
    if (event.target !== event.currentTarget || !stack.isTop(event.currentTarget)) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close.current();
  }}>{children}</dialog>, document.body);
}

export default function StackDialog(props: React.ComponentProps<typeof ManagedDialog>) {
  const stack = useModalStack();
  return stack ? <ManagedDialog {...props} /> : <ModalStackProvider><ManagedDialog {...props} /></ModalStackProvider>;
}
