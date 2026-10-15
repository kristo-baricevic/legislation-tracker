export const DASHBOARD_FLAG_KEY = "legislation-tracker-dashboard-cards";

export function readDashboardFlag(): boolean {
  if (typeof window === "undefined") return true;
  try { return window.localStorage.getItem(DASHBOARD_FLAG_KEY) !== "false"; }
  catch { return true; }
}

export function persistDashboardFlag(enabled: boolean): boolean {
  try { window.localStorage.setItem(DASHBOARD_FLAG_KEY, String(enabled)); return true; }
  catch { return false; }
}
