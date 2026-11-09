"use client";

import { createContext, useCallback, useContext, useId, useState, type ReactNode } from "react";

const tabs = { changes: "What changes", money: "Money", votes: "Votes & sponsor", terms: "Key terms", versions: "Versions" };
type Tab = keyof typeof tabs;
const Navigation = createContext<{ active: Tab; select: (tab: Tab) => void; id: string } | null>(null);
const PanelVisible = createContext(true);
export function useReaderPanelVisible() { return useContext(PanelVisible); }

export function ReaderTabsProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<Tab>("changes");
  const id = useId();
  const select = useCallback((tab: Tab) => {
    setActive(tab);
    // Also covers links inside a panel that hide their own focused control.
    document.getElementById(`${id}-${tab}-tab`)?.focus({ preventScroll: true });
  }, [id]);
  return <Navigation.Provider value={{ active, select, id }}>{children}</Navigation.Provider>;
}

export function useReaderTabs() { return useContext(Navigation); }

export function ReaderTabBar() {
  const nav = useReaderTabs();
  if (!nav) return null;
  const keys = Object.keys(tabs) as Tab[];
  return <div role="tablist" aria-label="Bill details" className="mb-5 flex overflow-x-auto border-b border-slate-300 dark:border-green-800">
    {keys.map((tab, index) => <button key={tab} type="button" role="tab"
      id={`${nav.id}-${tab}-tab`} aria-controls={`${nav.id}-${tab}-panel`}
      aria-selected={nav.active === tab} tabIndex={nav.active === tab ? 0 : -1}
      onClick={() => nav.select(tab)}
      onKeyDown={event => {
        const next = event.key === "ArrowRight" ? (index + 1) % keys.length : event.key === "ArrowLeft" ? (index + keys.length - 1) % keys.length : event.key === "Home" ? 0 : event.key === "End" ? keys.length - 1 : null;
        if (next === null) return;
        event.preventDefault(); nav.select(keys[next]);
        document.getElementById(`${nav.id}-${keys[next]}-tab`)?.focus();
      }}
      className={`shrink-0 border-b-2 px-4 py-3 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-[-2px] ${nav.active === tab ? "border-emerald-700 text-emerald-900 dark:text-green-300" : "border-transparent text-slate-600 hover:text-slate-950 dark:text-green-500"}`}
    >{tabs[tab]}</button>)}
  </div>;
}

/** Keep mounted so changing tabs never resets a user's filters or pagination. */
export function ReaderTabPanel({ tab, children }: { tab: Tab; children: ReactNode }) {
  const nav = useReaderTabs();
  if (!nav) return <>{children}</>;
  return <PanelVisible.Provider value={nav.active === tab}><section role="tabpanel" id={`${nav.id}-${tab}-panel`} aria-labelledby={`${nav.id}-${tab}-tab`} hidden={nav.active !== tab} tabIndex={0}>{children}</section></PanelVisible.Provider>;
}
