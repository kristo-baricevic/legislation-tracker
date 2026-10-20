"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { BillEnhancement } from "@/lib/api";
import { subscribePersonalizedChanges } from "@/lib/personalized-scope";

const Context = createContext<{
  enhancement: BillEnhancement | null;
  savedEnhancement: BillEnhancement | null;
  mode: "original" | "ai";
  setMode: (mode: "original" | "ai") => void;
  setEnhancement: (value: BillEnhancement | null) => void;
}>({ enhancement: null, savedEnhancement: null, mode: "original", setMode: () => {}, setEnhancement: () => {} });

export function AiGlossaryProvider({ children }: { children: ReactNode }) {
  const [enhancement, setEnhancement] = useState<BillEnhancement | null>(null);
  const [preferredMode, setMode] = useState<"original" | "ai">("ai");
  useEffect(() => subscribePersonalizedChanges(change => {
    if (change.kind === "session") { setEnhancement(null); setMode("ai"); }
  }), []);
  const available = enhancement?.status === "succeeded" && (enhancement.source_compatible ?? !enhancement.stale) && enhancement.result ? enhancement : null;
  const mode = available ? preferredMode : "original";
  return <Context.Provider value={{ enhancement: mode === "ai" ? available : null, savedEnhancement: available, mode, setMode, setEnhancement }}>{children}</Context.Provider>;
}

export const useAiGlossary = () => useContext(Context);

export function ReaderModeSwitch() {
  const { savedEnhancement, mode, setMode } = useAiGlossary();
  return <div role="group" aria-label="Reading version" className="inline-flex rounded-lg border border-slate-400 p-1 dark:border-green-800">
    {(["original", "ai"] as const).map(value => <button key={value} type="button"
      aria-pressed={mode === value} disabled={value === "ai" && !savedEnhancement}
      onClick={() => setMode(value)}
      className={`rounded-md px-4 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 disabled:cursor-not-allowed disabled:opacity-40 ${mode === value ? "bg-slate-900 text-white dark:bg-green-500 dark:text-black" : "text-slate-700 hover:bg-slate-100 dark:text-green-300 dark:hover:bg-green-950"}`}>
      {value === "ai" ? "AI-enhanced" : "Original"}
    </button>)}
  </div>;
}
