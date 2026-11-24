import { expect, test, type Locator, type Page } from "@playwright/test";
const bill = { id: 1, jurisdiction: "federal", session: 119, bill_number: "HR 1", title: "Public health reporting", status: "introduced", sponsor_name: "Member One", introduced_at: "2025-01-10", last_action_at: null, topics: [{ topic_id: 1, name: "Health", slug: "health", confidence_score: null }] };
const second = { ...bill, id: 2, bill_number: "HR 2", title: "Rural health reporting" };
const third = { ...bill, id: 3, bill_number: "HR 3", title: "Community health reporting" };
const recommendations = { algorithm: "explicit-facets-mmr-v1", generated_at: "2026-10-10T00:00:00Z", count: 3, next_cursor: null, candidate_pool_truncated: false, ranking_limit_reached: false, empty_reason: null, unsupported_follow_types: [], results: [bill, second, third].map(bill => ({ bill, score: 1, reasons: [{ kind: "followed_topic", topic_id: 1, name: "Health" }] })) };
async function fixtures(page: Page) {
  let followed = false, signedIn = true;
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let response: unknown;
    if (path === "/api/auth/session/current/") { await route.fulfill({ status: signedIn ? 200 : 401, json: signedIn ? { authenticated: true, user: { email: "fixture@example.com" } } : { detail: "anonymous" } }); return; }
    if (path === "/api/auth/session/refresh/") { await route.fulfill({ status: 401, json: { detail: "anonymous" } }); return; }
    if (path === "/api/auth/csrf/") response = { csrf_token: "fixture" };
    else if (path === "/api/auth/session/logout/") { signedIn = false; await route.fulfill({ status: 204 }); return; }
    else if (path === "/api/tracking/") response = { bills: followed ? [{ id: 1, bill, created_at: "2025-01-01" }] : [], topics: [{ id: 1, topic: { id: 1, name: "Health", slug: "health" }, created_at: "2025-01-01" }], legislators: [], is_staff: false };
    else if (path === "/api/tracking/bills/") { followed = true; response = { id: 1, bill, created_at: "2025-01-01" }; }
    else if (path === "/api/tracking/recommendations/") response = { ...recommendations, results: recommendations.results.filter(item => !followed || item.bill.id !== 1) };
    else if (path === "/api/tracking/representative-recommendations/") response = { algorithm: "explicit-representative-topics-mmr-v1", generated_at: "2026-10-10T00:00:00Z", activity_as_of: null, count: 0, results: [], empty_reason: "insufficient_metadata", unsupported_follow_types: [], policy_version: null, coverage: { status: "ingested_subset", service_exposure: "unknown", bill_families: "unavailable", votes_used_for_ranking: false } };
    else if (path === "/api/representatives/") response = { count: 0, next: null, previous: null, results: [] };
    else if (path === "/api/bills/1/") response = { ...bill, documents: [], summary: null, latest_contract: null };
    else if (path === "/api/bills/filter-options/") response = { jurisdictions: ["federal"], current_congress: 119 };
    else if (path === "/api/tracking/feed/") response = { entries: [] };
    else response = {};
    await route.fulfill({ json: response });
  });
}
test("always-on row, shared bill modal, persisted follow and responsive scrolling", async ({ page }) => {
  await fixtures(page);
  await page.goto("/");
  const preview = page.getByLabel("Show recommendations on this browser");
  await expect(preview).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Follow the bills that matter to you." })).toBeVisible();
  const row = page.getByRole("region", { name: "Recommended bills" });
  const opener = row.getByRole("link", { name: bill.title });
  await expect(opener).toBeVisible();
  await expect(row.getByLabel("Why recommended").first()).toContainText("Health");
  await opener.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByText("No bill summary is available yet.")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
  const request = page.waitForRequest(request => request.url().endsWith("/api/tracking/bills/") && request.method() === "POST");
  await row.getByRole("button", { name: "Follow bill HR 1 / 119" }).click();
  expect((await request).postDataJSON()).toEqual({ bill: 1 });
  await expect(row.getByRole("link", { name: second.title })).toBeVisible();
  await expect(opener).toBeVisible();
  await expect(row.getByRole("button", { name: "Unfollow bill HR 1 / 119" })).toBeFocused();
  await page.reload();
  await expect(preview).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Followed bills" })).toBeVisible();
  for (const [name, width] of [["desktop", 1280], ["tablet", 768], ["mobile", 390]] as const) {
    await page.setViewportSize({ width, height: 850 });
    await expect(row.getByRole("link", { name: second.title })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (name === "mobile") expect(await row.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
    await page.screenshot({ path: `test-results/recommendations-${name}.png`, fullPage: true });
  }
  await expect(page.getByRole("heading", { name: "Follow the bills that matter to you." })).toBeVisible();
  await expect(row).toBeVisible();
  await page.reload();
  await expect(preview).toHaveCount(0);
  await expect(page.getByLabel("Use card dashboard on this browser")).toHaveCount(0);
});
test("error, retry, no-match and logout clear private cards", async ({ page }) => {
  await fixtures(page);
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({ status: 503, json: { detail: "unavailable" } }));
  await page.goto("/");
  const bills = page.getByRole("region", { name: "Recommended bills" });
  await expect(page.getByRole("alert").filter({ hasText: "Recommendations could not" })).toBeVisible();
  await page.unroute("**/api/tracking/recommendations/**");
  await page.getByRole("button", { name: "Retry recommendations" }).click();
  await expect(bills.getByRole("link", { name: bill.title })).toBeVisible();
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({ json: { ...recommendations, results: [], count: 0, empty_reason: "no_matches" } }));
  const refresh = page.waitForRequest(request => new URL(request.url()).pathname === "/api/tracking/recommendations/");
  await page.getByRole("button", { name: "Refresh bill recommendations" }).click();
  await refresh;
  await expect(page.getByText("No other ingested legislation matches your followed interests yet.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Bills to discover" })).toBeFocused();
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Bills to discover" })).toBeVisible();
  await expect(bills).toHaveCount(0);
  await expect(page.getByText("Log in to discover legislation", { exact: false })).toHaveCount(2);
});

async function expectStableClick(page: Page, button: Locator, settled: () => Promise<void>) {
  await button.evaluate(el => el.scrollIntoView({ block: "center", inline: "nearest" }));
  const measure = await page.evaluateHandle(() => {
    const initial = window.scrollY;
    let maxShift = 0;
    let frame: number;
    const sample = () => {
      maxShift = Math.max(maxShift, Math.abs(window.scrollY - initial));
      frame = requestAnimationFrame(sample);
    };
    sample();
    return { initial, stop: () => { cancelAnimationFrame(frame); return maxShift; } };
  });
  expect(await measure.evaluate(value => value.initial)).toBeGreaterThan(0);
  await button.click();
  await settled();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  expect(await measure.evaluate(value => value.stop())).toBeLessThanOrEqual(1);
  await measure.dispose();
}

for (const width of [390, 1280]) {
  for (const kind of ["bills", "representatives"] as const) {
    test(`dashboard scroll stays stable on more and dismiss for ${kind} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 650 });
      await fixtures(page);
      const people = kind === "representatives";
      const endpoint = people ? "representative-recommendations" : "recommendations";
      const moreName = people ? "More representative recommendations" : "More recommendations";
      const row = page.getByRole("region", { name: people ? "Recommended representatives" : "Recommended bills" });
      let release!: () => void;
      const waitForResponse = () => new Promise<void>(resolve => { release = resolve; });
      await page.route(`**/api/tracking/${endpoint}/**`, async route => {
        if (route.request().method() === "POST") {
          await waitForResponse();
          return route.fulfill({ status: 204 });
        }
        const more = new URL(route.request().url()).searchParams.has(people ? "shown" : "cursor");
        if (more) await waitForResponse();
        const results = (more ? [3, 4] : [1, 2]).map(id => {
          const name = `Member ${id}`;
          return people ? {
            representative_id: id, name, reasons: [], bioguide_id: "",
            card: { top_topics: [] }, topic_activity_evidence: { representative: { id, name, state: "NY", chamber: "house" } },
          } : { bill: { ...bill, id, title: `Bill ${id}` }, reasons: [] };
        });
        return route.fulfill({ json: { ...recommendations, results, next_cursor: more ? null : "next", has_more: !more } });
      });
      await page.goto("/");
      const cards = row.getByRole("article");
      await expect(cards).toHaveCount(2);
      const checkPending = async () => {
        await expect.poll(() => typeof release).toBe("function");
        // Hold the response past the dashboard spinner's delay.
        await page.waitForTimeout(350);
        await expect(row).toBeVisible();
        await expect(page.getByRole("status", { name: "Loading dashboard" })).toHaveCount(0);
        release();
      };
      await expectStableClick(page, page.getByRole("button", { name: moreName, exact: true }), async () => {
        await checkPending();
        await expect(cards).toHaveCount(4);
      });
      const dismissStarted = page.waitForRequest(req => req.method() === "POST" && req.url().endsWith("/dismiss/"));
      await expectStableClick(page, cards.first().getByRole("button", { name: /^Dismiss/ }), async () => {
        await dismissStarted;
        await checkPending();
        await expect(cards).toHaveCount(3);
      });
    });
  }
}

for (const width of [390, 1280]) {
  for (const surface of ["dashboard bills", "dashboard representatives", "dashboard followed bills", "bills", "representatives", "committees"] as const) {
    test(`follow and unfollow keep scroll and neighboring cards stable on ${surface} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 600 });
      await fixtures(page);
      const dashboard = surface.startsWith("dashboard");
      const people = surface.endsWith("representatives");
      const items = Array.from({ length: 32 }, (_, i) => ({
        ...bill, id: i + 1, title: `Bill ${i + 1}`, bill_number: `HR ${i + 1}`,
      }));
      const members = items.map(({ id }) => ({
        id, name: `Member ${id}`, first_name: "Member", last_name: String(id), state: "NY", party: "D",
        chamber: "house", is_current: true, bioguide_id: "",
      }));
      const card = { top_topics: [], biography: { text: "Representative biography" } };
      const committees = surface === "committees";
      const target = dashboard ? 1 : committees ? 2 : 24;
      const collection = surface === "dashboard followed bills";
      let tracked = collection;
      let release!: () => void;
      const endpoint = people ? "legislators" : "bills";
      const writes: string[] = [];
      await page.route("**/api/**", async route => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        if (path.startsWith(`/api/tracking/${endpoint}/`) && ["POST", "DELETE"].includes(request.method())) {
          const following = request.method() === "POST";
          if (following) expect(request.postDataJSON()[people ? "representative" : "bill"]).toBe(target);
          else expect(path).toBe(`/api/tracking/${endpoint}/${target}/`);
          writes.push(request.method());
          await new Promise<void>(resolve => { release = resolve; });
          tracked = following;
          return following ? route.fulfill({ json: { id: target, bill: items[target - 1], representative: members[target - 1], card } }) : route.fulfill({ status: 204 });
        }
        if (path === "/api/tracking/") return route.fulfill({ json: {
          bills: [...(tracked && !people ? [{ id: target, bill: items[target - 1] }] : []), ...(collection ? items.slice(1, 3).map(bill => ({ id: bill.id, bill })) : [])],
          legislators: tracked && people ? [{ id: target, representative: members[target - 1], card }] : [],
          topics: [], is_staff: false,
        } });
        if (path === "/api/topics/") return route.fulfill({ json: [] });
        if (path === "/api/committees/") return route.fulfill({ json: { congress: 119, next: null, results: [{ id: 1, name: "Finance", chamber: "senate", members: [] }] } });
        if (path === "/api/committees/1/introduced-bills/") return route.fulfill({ json: { next: null, results: items.slice(0, 6) } });
        if (path.includes("saved-search")) return route.fulfill({ json: { count: 0, results: [] } });
        if (path === "/api/bills/" || path === "/api/representatives/") return route.fulfill({ json: {
          count: items.length, previous: null, next: null, results: path === "/api/bills/" ? items : members,
        } });
        if (path === "/api/tracking/representative-recommendations/") return route.fulfill({ json: {
          ...recommendations, results: members.slice(0, 3).map(representative => ({
            representative_id: representative.id, name: representative.name, reasons: [], card,
            topic_activity_evidence: { representative },
          })),
        } });
        return route.fallback();
      });
      await page.goto(dashboard ? "/" : committees ? "/committees" : people ? "/representatives" : "/bills?session=119");
      const row = dashboard ? page.getByRole("region", { name: collection ? "Followed bills" : people ? "Recommended representatives" : "Recommended bills" })
        : committees ? page.getByRole("region", { name: "Finance bills introduced" })
        : people ? page.getByRole("list", { name: "Representatives", exact: true }) : page.getByRole("region", { name: "Bill results" });
      const buttons = row.locator("button[aria-pressed]");
      const button = buttons.nth(target - 1);
      await expect(button).toHaveAttribute("aria-pressed", String(collection));
      const neighbors = await row.evaluateHandle((el, selected) =>
        Array.from(el.querySelectorAll("button[aria-pressed]")).filter((_, index) => index !== selected).map(node => ({ node, html: node.outerHTML })), target - 1);
      const checkNeighbors = async () => {
        expect(await neighbors.evaluate(entries => entries.length > 0 && entries.every(({ node, html }) =>
          node.isConnected && node.getClientRects().length > 0 && node.outerHTML === html))).toBe(true);
      };
      for (const [index, method] of (collection ? ["DELETE"] : ["POST", "DELETE"]).entries()) {
        const originalLabel = await button.innerText();
        await expectStableClick(page, button, async () => {
          await expect.poll(() => writes.length).toBe(index + 1);
          expect(writes[index]).toBe(method);
          await expect(button).toHaveText(originalLabel);
          await page.waitForTimeout(350);
          await checkNeighbors();
          release();
          if (collection) await expect(buttons).toHaveCount(2);
          else await expect(button).toHaveAttribute("aria-pressed", String(method === "POST"));
          if (!collection) await expect(button).not.toHaveText(originalLabel);
          await checkNeighbors();
        });
      }
      await neighbors.dispose();
    });
  }
}
