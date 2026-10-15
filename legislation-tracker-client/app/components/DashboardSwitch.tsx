"use client";

import React from "react";
import Dashboard from "./Dashboard";
import BillDeck from "./BillDeck";
import styles from "./bill-deck.module.css";
import { DASHBOARD_FLAG_KEY, readDashboardFlag, persistDashboardFlag } from "@/lib/dashboard-flag";

export default function DashboardSwitch() {
  const [enabled, setEnabled] = React.useState<boolean | null>(null);
  const [notice, setNotice] = React.useState("");
  React.useEffect(() => {
    const sync = () => {
      setEnabled(readDashboardFlag());
      try { if (localStorage.getItem(DASHBOARD_FLAG_KEY) === null) persistDashboardFlag(true); } catch { /* readDashboardFlag supplies the safe default. */ }
    };
    sync();
    const storage = (event: StorageEvent) => { if (event.key === DASHBOARD_FLAG_KEY || event.key === null) sync(); };
    window.addEventListener("storage", storage);
    return () => window.removeEventListener("storage", storage);
  }, []);
  if (enabled === null) return <p role="status">Loading dashboard…</p>;
  return <div className={enabled ? styles.pageFrame : undefined}><div className={enabled ? styles.page : undefined}>
    {enabled ? <BillDeck /> : <Dashboard />}
    <div className="mt-8 flex flex-wrap items-center gap-3 text-sm font-sans">
      <label className="flex items-center gap-2"><input type="checkbox" checked={enabled} onChange={event => {
        const next = event.target.checked;
        setNotice(persistDashboardFlag(next) ? "" : "Browser storage is unavailable. This preference will reset on reload.");
        setEnabled(next);
      }} /> Use card dashboard on this browser</label>
      <span role="status">{notice}</span>
    </div>
  </div></div>;
}
