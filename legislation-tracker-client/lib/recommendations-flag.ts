/** Reversible browser-local preview, independent of the dashboard flag. */
export const RECOMMENDATIONS_FLAG_KEY = "legislation-tracker-recommendations";
export function readRecommendationsFlag(): boolean {
  if (typeof window === "undefined") return false;
  try { return window.localStorage.getItem(RECOMMENDATIONS_FLAG_KEY) === "true"; }
  catch { return false; }
}
export function persistRecommendationsFlag(enabled: boolean): boolean {
  try { window.localStorage.setItem(RECOMMENDATIONS_FLAG_KEY, String(enabled)); return true; }
  catch { return false; }
}
