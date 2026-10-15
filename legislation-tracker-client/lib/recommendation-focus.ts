/** Persistent page destination when a recommendation opener was removed. */
export function focusRecommendationFallback() {
  if (typeof document === "undefined") return;
  for (const selector of ["#bill-recommendations-title", "[data-recommendations-toggle]", "[data-dashboard-heading]"]) {
    const target = document.querySelector<HTMLElement>(selector);
    if (!target?.isConnected || !target.getClientRects().length || getComputedStyle(target).visibility !== "visible") continue;
    target.focus();
    if (document.activeElement === target) return;
  }
}
