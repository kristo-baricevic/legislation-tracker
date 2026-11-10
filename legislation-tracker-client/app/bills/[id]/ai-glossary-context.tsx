"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { BillEnhancement } from "@/lib/api";
import { subscribePersonalizedChanges } from "@/lib/personalized-scope";

const Context = createContext<{
  enhancement: BillEnhancement | null;
  analysisPending: boolean;
  setAnalysisPending: (pending: boolean) => void;
  savedEnhancement: BillEnhancement | null;
  mode: "original" | "ai";
  setMode: (mode: "original" | "ai") => void;
  setEnhancement: (value: BillEnhancement | null) => void;
}>({ enhancement: null, analysisPending: false, setAnalysisPending: () => {}, savedEnhancement: null, mode: "original", setMode: () => {}, setEnhancement: () => {} });

export function AiGlossaryProvider({ children }: { children: ReactNode }) {
  const [enhancement, setEnhancement] = useState<BillEnhancement | null>(null);
  const [analysisPending, setAnalysisPending] = useState(true);
  const [preferredMode, setMode] = useState<"original" | "ai">("ai");
  useEffect(() => subscribePersonalizedChanges(change => {
    if (change.kind === "session") { setEnhancement(null); setMode("ai"); setAnalysisPending(true); }
  }), []);
  const available = enhancement?.status === "succeeded" && (enhancement.source_compatible ?? !enhancement.stale) && enhancement.result ? enhancement : null;
  const mode = available ? preferredMode : "original";
  return <Context.Provider value={{ enhancement: mode === "ai" ? available : null, analysisPending, setAnalysisPending, savedEnhancement: available, mode, setMode, setEnhancement }}>{children}</Context.Provider>;
}

export const useAiGlossary = () => useContext(Context);

export function BillAnalysisBoundary({ children }: { children: ReactNode }) {
  const { analysisPending } = useAiGlossary();
  if (!analysisPending) return <>{children}</>;
  return <section role="status" aria-label="Loading bill analysis" aria-busy="true" className="min-h-80 rounded-lg border border-slate-200 bg-white p-6">
    <span className="sr-only">Loading bill analysis</span>
    <div aria-hidden="true" className="space-y-4 motion-safe:animate-pulse">
      <div className="h-6 w-28 rounded bg-slate-200" />
      <div className="h-4 w-full rounded bg-slate-100" />
      <div className="h-4 w-4/5 rounded bg-slate-100" />
      <div className="mt-8 h-10 w-full rounded bg-slate-100" />
    </div>
  </section>;
}

export function ReaderModeSwitch() {
  const { savedEnhancement, mode, setMode } = useAiGlossary();
  return <div role="group" aria-label="Reading version" className="inline-flex rounded-lg border border-slate-400 p-1 dark:border-green-800">
    {(["original", "ai"] as const).map(value => <button key={value} type="button"
      aria-pressed={mode === value} disabled={value === "ai" && !savedEnhancement}
      onClick={() => setMode(value)}
      className={`rounded-md px-4 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 disabled:cursor-not-allowed disabled:opacity-40 ${mode === value ? "bg-slate-900 text-white dark:bg-green-500 dark:text-black" : "text-slate-700 hover:bg-slate-100 dark:text-green-300 dark:hover:bg-green-950"}`}>
      {value === "ai" ? "Enhanced" : "Original"}
    </button>)}
  </div>;
}
