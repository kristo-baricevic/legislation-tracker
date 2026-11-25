import { expect, test, type Page } from "@playwright/test";

const api = process.env.E2E_API_URL;
const titles = ["A bill to designate Marshall House", "School Libraries Act", "Clinic Access Act"];
const session = { session: "117" };
const cards = (page: Page) => page.getByRole("region", { name: "Bill results" }).locator("article h3");

async function verify(page: Page, params: Record<string, string>, expected: string[]) {
  for (const reload of [false, true]) {
    if (reload) await page.reload();
    await expect.poll(() => Object.fromEntries(new URL(page.url()).searchParams)).toEqual(params);
    await expect(cards(page)).toHaveText(expected);
  }
}

async function choose(page: Page, label: RegExp, option: string) {
  await page.getByRole("button", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test.beforeEach(async ({ page }) => {
  await page.goto("/bills?session=117");
  await expect(cards(page)).toHaveText(titles);
});

for (const [label, key, filter, indices] of [
  ["Full-text search", "q", "a bill to designate", [0]],
  ["Bill # (contains)", "bill_number", "72", [1]],
  ["Sponsor", "sponsor", "Avery", [0, 2]],
  ["Topic contains", "topic", "educ", [1]],
] as const) {
  test(`${label} changes, clears and survives reload`, async ({ page }) => {
    const input = page.getByLabel(label, { exact: true });
    await input.fill(filter);
    await verify(page, { ...session, [key]: filter }, indices.map(i => titles[i]));
    await expect(input).toHaveValue(filter);
    await input.fill("");
    await verify(page, session, titles);
    await expect(input).toHaveValue("");
  });
}

test("status and exact topic change and clear independently", async ({ page }) => {
  const status = page.locator("select").filter({ has: page.locator('option[value="stage:introduced"]') });
  await status.selectOption("stage:introduced");
  await verify(page, { ...session, status: "stage:introduced" }, [titles[0], titles[2]]);
  await status.selectOption("");
  await verify(page, session, titles);
  const response = await page.request.get(api + "/api/topics/");
  expect(response.ok()).toBe(true);
  const topics: { name: string; id: number }[] = await response.json();
  const education = topics.find(topic => topic.name === "Education")!;
  await choose(page, /^Topic \(exact\)/, education.name);
  await verify(page, { ...session, topic_id: String(education.id) }, [titles[1]]);
  await choose(page, /^Topic \(exact\)/, "All");
  await verify(page, session, titles);
});

test("session changes and clears to all Congresses", async ({ page }) => {
  const field = page.getByLabel("Session (Congress)", { exact: true });
  const other = ["Synthetic integration bill", "Reader grants fixture", "Source-first grants fixture",
    "Rural Hospital Grants Act", "Bill Without a CRS Summary"];
  await field.fill("119");
  await verify(page, { session: "119" }, other);
  await field.fill("");
  await verify(page, { session: "" }, [...other, ...titles]);
  await expect(field).toHaveValue("");
});

test("each sort survives reload and Unsorted restores creation order", async ({ page }) => {
  for (const [label, sort, indices] of [
    ["Recent activity", "recent_activity", [1, 0, 2]], ["Oldest activity", "oldest_activity", [2, 0, 1]],
    ["Relevance", "relevance", [0, 1, 2]], ["Unsorted", "unsorted", [0, 1, 2]],
  ] as const) {
    await choose(page, /^Sort /, label);
    await verify(page, { ...session, sort }, indices.map(i => titles[i]));
  }
});

test("tracked, untracked and all bills reflect the signed-in user's follow", async ({ page }) => {
  const account = { email: `filters-${crypto.randomUUID()}@example.test`, password: "Filter-test-account-2026!" };
  await page.request.get(api + "/api/auth/csrf/");
  const csrf = (await page.context().cookies()).find(cookie => cookie.name === "csrftoken")!;
  const options = { data: account, headers: { "X-CSRFToken": csrf.value } };
  expect((await page.request.post(api + "/api/auth/register/", options)).status()).toBe(202);
  expect((await page.request.post(api + "/api/auth/session/", options)).status()).toBe(200);
  await page.reload();
  const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: titles[1] }) });
  await card.getByRole("button", { name: "Follow", exact: true }).click();
  await expect(card.getByRole("button", { name: "Unfollow" })).toBeVisible();
  const tracking = page.locator("select").filter({ has: page.locator('option[value="tracked"]') });
  await tracking.selectOption("tracked");
  await verify(page, { ...session, tracking: "tracked" }, [titles[1]]);
  await tracking.selectOption("untracked");
  await verify(page, { ...session, tracking: "untracked" }, [titles[0], titles[2]]);
  await tracking.selectOption("");
  await verify(page, session, titles);
});
