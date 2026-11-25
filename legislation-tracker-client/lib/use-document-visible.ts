import { useSyncExternalStore } from "react";

function subscribe(update: () => void) {
  document.addEventListener("visibilitychange", update);
  return () => document.removeEventListener("visibilitychange", update);
}

export function useDocumentVisible() {
  return useSyncExternalStore(subscribe, () => !document.hidden, () => true);
}
