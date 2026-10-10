import { afterEach, describe, expect, it, vi } from "vitest";
import { focusRecommendationFallback } from "../../lib/recommendation-focus";

afterEach(() => { document.body.innerHTML = ""; vi.restoreAllMocks(); });

function fixture() {
  document.body.innerHTML = '<h2 id="bill-recommendations-title" tabindex="-1">Bills</h2><input data-recommendations-toggle type="checkbox"><h1 data-dashboard-heading tabindex="-1">Dashboard</h1>';
  const [heading, toggle, dashboard] = Array.from(document.body.children) as HTMLElement[];
  for (const target of [heading, toggle, dashboard]) vi.spyOn(target, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  return { heading, toggle, dashboard };
}

describe("recommendation dialog page focus fallback", () => {
  it("prefers the visible persistent row heading", () => {
    const { heading } = fixture();
    focusRecommendationFallback();
    expect(document.activeElement).toBe(heading);
  });
  it("skips hidden row targets and reaches the dashboard when the toggle is gone", () => {
    const { heading, toggle, dashboard } = fixture();
    heading.style.visibility = "hidden";
    toggle.remove();
    focusRecommendationFallback();
    expect(document.activeElement).toBe(dashboard);
  });
  it("continues to the toggle when a connected visible heading cannot receive focus", () => {
    const { heading, toggle } = fixture();
    heading.removeAttribute("tabindex");
    focusRecommendationFallback();
    expect(document.activeElement).toBe(toggle);
  });
});
