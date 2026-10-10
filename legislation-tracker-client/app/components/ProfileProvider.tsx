"use client";

import React from "react";
import { usePathname, useSearchParams } from "next/navigation";
import type { BillListItem } from "@/lib/api";
import { profileScopeKey, type ProfileScope } from "@/lib/legislator-profile";
import BillDeckModal from "./BillDeckModal";
import LegislatorProfileModal from "./LegislatorProfileModal";
import { ModalStackProvider, useModalStack } from "./ModalStack";

const FLAG = "legislation-tracker-legislator-profiles";
const EVENT = "legislator-profile-preference";
type ProfileContext = { enabled: boolean; open: (scope: ProfileScope) => boolean };
const Context = React.createContext<ProfileContext | null>(null);
export const useProfileDialogs = () => React.useContext(Context);
type Entry = { key: number; kind: "profile"; scope: ProfileScope } | { key: number; kind: "bill"; bill: BillListItem };

function ProfileDialogs({ children, renderActivity }: { children: React.ReactNode; renderActivity?: (scope: ProfileScope) => React.ReactNode }) {
  const [enabled, setEnabled] = React.useState(false);
  const [entries, setEntries] = React.useState<Entry[]>([]);
  const current = React.useRef<Entry[]>([]);
  const sequence = React.useRef(0);
  const stack = useModalStack()!;
  const pathname = usePathname();
  const query = useSearchParams()?.toString() ?? "";
  const route = `${pathname}?${query}`;
  const previousPath = React.useRef(route);
  React.useEffect(() => {
    const read = () => {
      let value = false;
      try { value = localStorage.getItem(FLAG) === "true"; } catch { /* Storage denial keeps the reversible feature off. */ }
      setEnabled(value);
      if (!value) { stack.closeAll(); current.current = []; setEntries([]); }
    };
    const storage = (event: StorageEvent) => { if (event.key === FLAG || event.key === null) read(); };
    read(); window.addEventListener("storage", storage); window.addEventListener(EVENT, read);
    return () => { window.removeEventListener("storage", storage); window.removeEventListener(EVENT, read); };
  }, [stack]);
  React.useEffect(() => {
    if (previousPath.current !== route) { stack.closeAll(); current.current = []; setEntries([]); previousPath.current = route; }
  }, [route, stack]);
  const close = (key: number) => { const index = current.current.findIndex(entry => entry.key === key); if (index >= 0) { current.current = current.current.slice(0, index); setEntries(current.current); } };
  const open = (scope: ProfileScope) => {
    if (!enabled) return false;
    const identity = `profile:${profileScopeKey(scope)}`;
    const top = current.current.at(-1);
    if (top?.kind === "profile" && profileScopeKey(top.scope) === profileScopeKey(scope)) return true;
    if (stack.contains(identity) || current.current.some(entry => entry.kind === "profile" && profileScopeKey(entry.scope) === profileScopeKey(scope))) return false;
    if (!stack.canOpen() || current.current.length >= 4) return false;
    current.current = [...current.current, { key: ++sequence.current, kind: "profile", scope }]; setEntries(current.current); return true;
  };
  const openBill = (bill: BillListItem) => {
    const top = current.current.at(-1);
    if (enabled && top?.kind === "bill" && top.bill.id === bill.id) return true;
    if (!enabled || !stack.canOpen() || stack.contains(`bill:${bill.id}`) || current.current.some(entry => entry.kind === "bill" && entry.bill.id === bill.id)) return false;
    current.current = [...current.current, { key: ++sequence.current, kind: "bill", bill }]; setEntries(current.current); return true;
  };
  return <Context.Provider value={{ enabled, open }}>{children}{entries.map(entry => entry.kind === "profile" ? <LegislatorProfileModal key={entry.key} scope={entry.scope} onClose={() => close(entry.key)} onOpenBill={openBill} renderActivity={renderActivity} /> : <BillDeckModal key={entry.key} bill={entry.bill} onClose={() => close(entry.key)} />)}</Context.Provider>;
}

export default function ProfileProvider(props: React.ComponentProps<typeof ProfileDialogs>) { return <ModalStackProvider><React.Suspense fallback={props.children}><ProfileDialogs {...props} /></React.Suspense></ModalStackProvider>; }

export function ProfilePreference() {
  const context = useProfileDialogs();
  const [error, setError] = React.useState("");
  if (!context) return null;
  return <label><input type="checkbox" checked={context.enabled} onChange={event => {
    try { localStorage.setItem(FLAG, String(event.target.checked)); window.dispatchEvent(new Event(EVENT)); setError(""); }
    catch { setError("This browser could not save the profile preference."); }
  }} /> Enable legislator profiles{error && <span role="status"> {error}</span>}</label>;
}
