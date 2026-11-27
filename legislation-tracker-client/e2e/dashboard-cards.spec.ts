import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

const bill = { id: 1, bill_number: "H.R. 1589", session: 119, title: "To amend the Internal Revenue Code of 1986 to increase the limitation on the deduction for state and local taxes.", jurisdiction: "federal", status: "introduced", sponsor_id: 1, sponsor_state: "NY", sponsor_bioguide_id: "T000001", sponsor_name: "Test Representative", introduced_at: "2025-02-26", last_action_at: "2025-02-26", topics: [{ topic_id: 1, name: "Taxation", slug: "taxation", confidence_score: 1 }] };
const other = { ...bill, id: 2, bill_number: "H.R. 619", title: "A second bill in the test collection", sponsor_name: null, topics: [], status: "passed_house" };
const documents = [1, 2, 3].map(id => ({ id, source_order: id, version_label: ["Introduced", "Reported", "Engrossed"][id - 1], is_active_version: id === 3, content_type: "text/html", file_size_bytes: 400, source_url: null, downloaded_at: null, download_url: null, text_url: null }));

const compactBill = {
  ...bill, documents, summary_preview: "Raises the deduction limit.", summary_has_more: false,
  summary_source: "source_metadata", summary_version_code: "Introduced", summary_action_date: null,
  summary_last_updated_at: null, processing_status: "complete", sponsor: 1, source_api_id: null,
  congress_gov_url: null, latest_contract: null, created_at: "2025-01-01", updated_at: "2025-01-01"
};

async function fixtures(page: Page, empty = false) {
  let following = !empty;
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let response: unknown = {};
    if (path === "/api/auth/session/current/") response = { authenticated: true, user: { email: "fixture@example.com" } };
    else if (path === "/api/auth/csrf/") response = { csrf_token: "fixture" };
    else if (path === "/api/tracking/topics/") response = [];
    else if (path === "/api/tracking/") response = { bills: following ? [{ id: 1, bill, created_at: "2025-01-01" }] : [], topics: empty ? [] : [{ id: 1, topic: { id: 1, name: "Taxation", slug: "taxation" }, created_at: "2025-01-01" }], legislators: [], is_staff: false };
    else if (path === "/api/tracking/bills/1/") { following = false; await route.fulfill({ status: 204 }); return; }
    else if (path === "/api/tracking/bills/") { following = true; response = { id: 1, bill, created_at: "2025-01-01" }; }
    else if (path === "/api/representatives/") response = { count: 1, next: null, previous: null, results: [{ id: 1, name: "Test Representative", state: "NY" }] };
    else if (path === "/api/bills/") response = { count: 2, next: null, previous: null, results: [bill, other] };
    else if (path === "/api/bills/1/changes/") response = { results: [], stream_head_cursor: null, page_end_cursor: null,
      older_cursor: null, unread_count: 0, personalized: true, has_more_newer: false, initial_window_truncated: false };
    else if (path === "/api/bills/1/votes/" || path === "/api/bills/1/contracts/") response = { count: 0, results: [], next: null, previous: null };
    else if (path === "/api/bills/1/" && url.searchParams.has("contract_view")) response = compactBill;
    else if (path === "/api/bills/1/") response = { ...bill, documents, summary: "This bill increases the limitation on the deduction for state and local taxes.", summary_source: "source_metadata", summary_version_code: "Introduced", latest_contract: null };
    else if (path === "/api/bills/1/comparisons/documents/") response = { before: Number(url.searchParams.get("before")), after: Number(url.searchParams.get("after")), sections: [{ section_key: `section-for-version-${url.searchParams.get("after")}`, operation: "modified" }], total_change_count: 1, returned_change_count: 1, truncated: false, fallback: false, truncation_reasons: [] };
    else if (path === "/api/bills/filter-options/") response = { jurisdictions: ["federal"], current_congress: 119 };
    else if (path === "/api/topics/") response = [{ id: 1, name: "Taxation", slug: "taxation" }];
    else if (path === "/api/tracking/feed/") response = { entries: [] };
    else if (path === "/api/saved-searches/") response = { count: 0, results: [] };
    else if (path.includes("recommendations")) response = { algorithm: "fixture", generated_at: "2026-10-15T00:00:00Z", count: 0, results: [], next_cursor: null, candidate_pool_truncated: false, ranking_limit_reached: false, empty_reason: "no_candidates", unsupported_follow_types: [] };
    await route.fulfill({ json: response });
  });
}

for (const path of ["/", "/bills?session=119"]) test(`sponsor avatars stay next to timelines on ${path}`, async ({page}) => {
  await page.setViewportSize({width:1280,height:1000});
  await fixtures(page);
  const cards = ["D", "R", "I"].map((party, index) => ({...bill, id:index+1, sponsor_party:party, title:`Bill ${index+1}`, card_summary: "Supports students. ".repeat(index * 10 + 1)}));
  await page.route("**/api/bills/?**", route => route.fulfill({json:{count:3,next:null,previous:null,results:cards}}));
  await page.route("**/api/tracking/", route => route.fulfill({json:{bills:cards.map((bill,index)=>({id:index+1,bill,created_at:"2025-01-01"})),topics:[],legislators:[],is_staff:false}}));
  await page.goto(path);
  await expect(page.getByRole("article")).toHaveCount(3);
  const gaps: number[] = [];
  const colors: string[] = [];
  for (const card of await page.getByRole("article").all()) {
    const avatar = card.getByRole("link",{name:"Test Representative",exact:true});
    const timeline = card.getByRole("img",{name:/Step .* of 5/});
    const a = (await avatar.boundingBox())!, t = (await timeline.boundingBox())!;
    gaps.push(t.y-a.y-a.height);
    colors.push(await avatar.evaluate(el => getComputedStyle(el).borderTopColor));
  }
  expect(Math.max(...gaps)-Math.min(...gaps)).toBeLessThan(2);
  expect(Math.max(...gaps)).toBeLessThan(30);
  expect(new Set(colors).size).toBe(3);
  expect(await page.getByText("Jurisdiction",{exact:true}).count()).toBe(0);
  await page.screenshot({path:`/tmp/sponsor-anchored-${path === "/" ? "dashboard" : "catalog"}.png`});
});

for (const width of [1440, 390]) test(`list filters do not retain empty scroll space at ${width}px`, async ({page}) => {
  await page.setViewportSize({width, height:900});
  await fixtures(page);
  await page.route("**/api/bills/?**", async route => {
    const filtered = new URL(route.request().url()).searchParams.has("status");
    const results = filtered ? [bill] : Array.from({length:20}, (_, i) => ({...bill, id:i + 10, title:`Bill ${i + 10}`}));
    await route.fulfill({json:{count:results.length,next:null,previous:null,results}});
  });
  await page.goto("/bills?session=119");
  await expect(page.getByRole("article")).toHaveCount(20);
  await page.getByRole("button",{name:"List",exact:true}).click();
  await page.evaluate(() => document.fonts.ready);
  await page.getByRole("combobox",{name:"Status",exact:true}).selectOption("stage:introduced");
  await expect(page.getByRole("article")).toHaveCount(1);
  await expect.poll(() => page.getByRole("article").last().evaluate(el => document.documentElement.scrollHeight - (el.getBoundingClientRect().bottom + window.scrollY))).toBeLessThan(150);
  await page.screenshot({path:`/tmp/bills-list-scroll-${width}.png`});
});

for (const width of [1440, 390]) test(`bills append on scroll at ${width}px`, async ({page}) => {
  await page.setViewportSize({width, height: 900});
  await fixtures(page);
  const requests: number[] = [];
  await page.route("**/api/bills/?**", async route => {
    const current = Number(new URL(route.request().url()).searchParams.get("page") || 1);
    requests.push(current);
    const results = current === 1 ? Array.from({length:20}, (_, i) => ({...bill, id:i + 10, title:`Bill ${i + 10}`})) : [{...other, id: 30, title:"Final bill"}];
    await route.fulfill({json:{count:21, next:current === 1 ? "?page=2" : null, previous:null, results}});
  });
  await page.goto("/bills?session=119");
  await expect(page.getByRole("article")).toHaveCount(20);
  await expect(page.getByRole("button", {name:"Next",exact:true})).toHaveCount(0);
  await page.locator('[aria-label="More bills"]').scrollIntoViewIfNeeded();
  await expect(page.getByRole("article")).toHaveCount(21);
  await expect(page.getByRole("link", {name:"Bill 10",exact:true})).toHaveCount(1);
  expect(requests).toEqual([1,2]);
  await page.screenshot({path:`/tmp/bills-infinite-${width}.png`});
});

for (const width of [1440, 390]) test(`bill tracking filter preserves layout at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  await fixtures(page);
  await page.route("**/api/bills/?**", async route => {
    const tracking = new URL(route.request().url()).searchParams.get("tracking");
    await route.fulfill({json: {count: 1, next: null, previous: null, results: [tracking === "untracked" ? other : bill]}});
  });
  await page.goto("/bills?session=119");
  const filter = page.getByRole("combobox", { name: "Tracking", exact: true });
  await expect(filter).toBeEnabled();
  await filter.scrollIntoViewIfNeeded();
  await filter.focus();
  const before = await filter.boundingBox();
  await filter.selectOption("untracked");
  await expect(page.getByRole("link", {name: other.title, exact: true})).toBeVisible();
  await expect(page).toHaveURL(/tracking=untracked/);
  expect(await filter.boundingBox()).toEqual(before);
  await expect(filter).toBeFocused();
  await page.screenshot({path: `/tmp/bill-tracking-filter-${width}.png`});
  await filter.selectOption("tracked");
  await expect(page.getByRole("link", {name: bill.title, exact: true})).toBeVisible();
  await expect(page).toHaveURL(/tracking=tracked/);
});

test("following from an accumulated private list refreshes all loaded pages", async ({page}) => {
  await fixtures(page);
  let followed = false;
  const requested: number[] = [];
  await page.route("**/api/tracking/bills/", async route => {
    followed = true;
    await route.fulfill({json:{id:31,bill:{...bill,id:31}}});
  });
  await page.route("**/api/bills/?**", async route => {
    const number = Number(new URL(route.request().url()).searchParams.get("page") || 1);
    requested.push(number);
    await route.fulfill({json:{count:followed?20:21,next:number===1&&!followed?"next":null,previous:null,
      results:number===1?Array.from({length:20},(_,i)=>({...bill,id:i+10,title:`Loaded bill ${i+10}`})):[{...bill,id:31,title:"Last untracked bill"}]}});
  });
  await page.goto("/bills?session=119&tracking=untracked");
  await expect(page.getByRole("article")).toHaveCount(20);
  await page.locator('[aria-label="More bills"]').scrollIntoViewIfNeeded();
  await expect(page.getByRole("article")).toHaveCount(21);
  await page.getByRole("article").filter({hasText:"Last untracked bill"}).getByRole("button",{name:"Follow",exact:true}).click();
  await expect(page.getByRole("article")).toHaveCount(20);
  await expect(page.getByRole("link",{name:"Loaded bill 10",exact:true})).toBeAttached();
  expect(requested).toEqual([1,2,1]);
});

test("dashboard filters scope both recommendation requests without losing search focus", async ({ page }) => {
  await fixtures(page);
  const calls: URL[] = [];
  await page.route("**/api/tracking/*recommendations/**", async route => {
    calls.push(new URL(route.request().url()));
    await route.fulfill({json:{algorithm:"fixture",generated_at:"2026-11-23",count:0,next_cursor:null,unsupported_follow_types:[],candidate_pool_truncated:false,ranking_limit_reached:false,empty_reason:"no_matches",results:[]}});
  });
  await page.goto("/");
  await expect(page.getByRole("combobox", {name:"Topic",exact:true})).toBeVisible();
  await page.getByRole("combobox", {name:"Topic",exact:true}).selectOption("1");
  await page.getByRole("combobox", {name:"Representative (sponsor)",exact:true}).selectOption("id:1");
  await page.getByRole("combobox", {name:"Status",exact:true}).selectOption("introduced");
  await page.getByRole("searchbox", {name:"Search bills",exact:true}).fill("tax");
  for (const path of ["/api/tracking/recommendations/", "/api/tracking/representative-recommendations/"]) {
    await expect.poll(() => calls.some(url => url.pathname === path && url.searchParams.get("q") === "tax" && url.searchParams.get("topic_id") === "1" && url.searchParams.get("sponsor") === "id:1" && url.searchParams.get("status") === "introduced")).toBe(true);
  }
  await expect(page.getByRole("searchbox", {name:"Search bills",exact:true})).toBeFocused();
});

for (const width of [1280, 390]) test(`refreshing topics and recommendations keeps geometry at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await fixtures(page);
  let refreshing = false;
  let release!: () => void;
  await page.route("**/api/topics/", async route => {
    if (refreshing) await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ json: [{ id: 1, name: "Taxation", slug: "taxation" }] });
  });
  await page.goto("/topics");
  const topic = page.getByRole("link", { name: "Taxation", exact: true });
  await expect(topic).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh followed topics" })).toBeEnabled();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const before = await topic.boundingBox();
  refreshing = true;
  await page.getByRole("button", { name: "Refresh topics", exact: true }).click();
  await expect.poll(() => Boolean(release)).toBe(true);
  expect(await topic.boundingBox()).toEqual(before);
  release();
  await expect(page.getByRole("button", { name: "Refresh topics", exact: true })).toBeEnabled();
  expect(await topic.boundingBox()).toEqual(before);
  let refreshRecs = false;
  let releaseRecs!: () => void;
  await page.route("**/api/tracking/recommendations/**", async route => {
    if (refreshRecs) await new Promise<void>(resolve => { releaseRecs = resolve; });
    await route.fulfill({json: {algorithm:"fixture",generated_at:"2026-11-22",count:1,next_cursor:null,unsupported_follow_types:[],candidate_pool_truncated:false,ranking_limit_reached:false,empty_reason:null,results:[{bill:other,score:1,reasons:[]}]}});
  });
  await page.goto("/");
  const refresh = page.getByRole("button", { name: "Refresh bill recommendations" });
  const row = page.getByRole("region", { name: "Recommended bills", exact: true });
  await expect(row).toBeVisible();
  await refresh.scrollIntoViewIfNeeded();
  const box = await row.boundingBox();
  const scroll = await page.evaluate(() => window.scrollY);
  refreshRecs = true;
  await refresh.click();
  await expect.poll(() => Boolean(releaseRecs)).toBe(true);
  expect(await row.boundingBox()).toEqual(box);
  expect(await page.evaluate(() => window.scrollY)).toBe(scroll);
  releaseRecs();
  await expect(refresh).toBeEnabled();
  await expect(refresh).toBeFocused();
  expect(await row.boundingBox()).toEqual(box);
});

test("opening a saved search on page two keeps that page until the search changes", async ({page}) => {
  await fixtures(page);
  await page.clock.install();
  await page.route("**/api/bills/?**", route => {
    const second = new URL(route.request().url()).searchParams.get("page") === "2";
    return route.fulfill({json:{count:21,next:null,previous:second ? "prev" : null,results:[second ? other : bill]}});
  });
  await page.goto("/bills?session=119&q=test&page=2");
  await expect(page.getByRole("link", {name:other.title, exact:true})).toBeVisible();
  await page.clock.fastForward(1000);
  await expect(page).toHaveURL(/[?&]page=2(?:&|$)/);
  await expect(page.getByRole("link", {name:other.title, exact:true})).toBeVisible();
  await page.getByPlaceholder("Words in title, summary, etc.").fill("changed");
  await page.clock.fastForward(1000);
  await expect(page.getByRole("link", {name:bill.title, exact:true})).toBeVisible();
  const params = new URL(page.url()).searchParams;
  expect(params.get("q")).toBe("changed");
  expect(params.has("page")).toBe(false);
});

for (const width of [1280, 390]) test(`catalog pagination retains content during requests at ${width}px`, async ({ page }) => {
  await page.setViewportSize({width,height:900});
  await fixtures(page);
  let release!: () => void;
  await page.route("**/api/bills/?**", async route => {
    const second = new URL(route.request().url()).searchParams.get("page") === "2";
    if (second) await new Promise<void>(resolve => {release = resolve;});
    await route.fulfill({json:{count:21,next:second?null:"next",previous:second?"prev":null,results:second?[{...other,id:21}]:Array.from({length:20}, (_, i) => ({...bill,id:bill.id+i,title:i?`Catalog bill ${i}`:bill.title}))}});
  });
  await page.goto("/bills?session=119");
  await expect(page.getByRole("link",{name:bill.title,exact:true})).toBeVisible();
  const next = page.locator('[aria-label="More bills"]');
  await next.scrollIntoViewIfNeeded();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const box = await next.boundingBox();
  const scroll = await page.evaluate(() => window.scrollY);
  await expect.poll(() => Boolean(release)).toBe(true);
  await expect(page.getByRole("link",{name:bill.title,exact:true})).toBeAttached();
  expect(await next.boundingBox()).toEqual(box);
  expect(await page.evaluate(() => window.scrollY)).toBe(scroll);
  release();
  await expect(page.getByRole("link",{name:other.title,exact:true})).toBeAttached();
  await expect(page.getByRole("button",{name:"Previous",exact:true})).toHaveCount(0);
  expect(Math.abs(await page.evaluate(() => window.scrollY) - scroll)).toBeLessThan(1);
  await expect(page.getByRole("article")).toHaveCount(21);
});

for (const width of [1280, 390]) test(`directory filters preserve portraits while pending at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({width,height:900});
  await fixtures(page);
  let release!: () => void;
  await page.route("**/api/representatives/?**", async route => {
    if (new URL(route.request().url()).searchParams.has("party")) await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({json:{count:1,next:null,previous:null,results:[{id:1,name:"Test Representative",bioguide_id:"T000001",chamber:"house",party:"D",state:"NY",district:"1",first_name:"Test",last_name:"Representative",image_url:null,official_website_url:null,is_current:true}]}});
  });
  await page.goto("/representatives");
  const results = page.getByRole("list",{name:"Representatives",exact:true});
  await expect(results).toBeVisible();
  const node = await results.elementHandle();
  await page.getByRole("button",{name:"Party All",exact:true}).click();
  await page.getByRole("option",{name:"Democrat",exact:true}).click();
  await expect.poll(() => Boolean(release)).toBe(true);
  await expect(results).toHaveAttribute("aria-busy","true");
  expect(await node!.evaluate(element => element.isConnected)).toBe(true);
  await page.screenshot({path:info.outputPath(`directory-pending-${width}.png`)});
  release();
  await expect(results).toHaveAttribute("aria-busy","false");
});

for (const width of [1280, 390]) test(`bill tracking does not flash the wrong action at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({width,height:900});
  await fixtures(page);
  let release!: () => void;
  await page.route(url => url.pathname === "/api/tracking/" && url.searchParams.get("view") === "membership", async route => {
    await new Promise<void>(resolve => {release = resolve;});
    await route.fulfill({json:{bills:[{id:1,bill,created_at:"2026-01-01"}],topics:[],legislators:[],is_staff:false}});
  });
  await page.goto("/bills/1");
  const control = page.getByRole("button",{name:"Loading follow status",exact:true});
  await expect(control).toBeDisabled();
  await expect(page.getByRole("button",{name:"Track bill",exact:true})).toHaveCount(0);
  await page.screenshot({path:info.outputPath(`tracking-pending-${width}.png`)});
  await expect.poll(() => Boolean(release)).toBe(true);
  release();
  await expect(page.getByRole("button",{name:"Tracked bill",exact:true})).toBeEnabled();
});

for (const width of [1280, 390]) test(`following a recommendation preserves cards, focus and scroll at ${width}px`, async ({ page }) => {
  await page.setViewportSize({width,height:900});
  await fixtures(page);
  let followed = false;
  let release!: () => void;
  let refreshHeld = false;
  let portraitRequests = 0;
  await page.route("**/api/auth/session/current/**", route => route.fulfill({json:{authenticated:true,user:{email:"fixture@example.com"},dashboard_revision:followed ? "after" : "before",tracking_revision:followed ? "after" : "before",research_revision:"unchanged",current_congress:119}}));
  await page.route("**/api/representatives/410/", route => {
    portraitRequests++;
    return route.fulfill({json:{id:410,name:"Katie Britt",bioguide_id:"B001319",image_url:"https://www.congress.gov/img/member/b001319_200.jpg"}});
  });
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({json: {
    algorithm:"fixture", generated_at:"2026-11-21T12:00:00Z", count:1, next_cursor:null,
    unsupported_follow_types:[], candidate_pool_truncated:false, ranking_limit_reached:false,
    empty_reason:null, results:followed ? [] : [{bill:other,score:1,reasons:[{kind:"followed_representative",representative_id:410,name:"Katie Britt",relation:"sponsor"}]}],
  }}));
  await page.route("**/api/tracking/bills/", async route => {
    followed = true;
    await route.fulfill({json:{id:2,bill:other,created_at:"2026-11-22"}});
  });
  await page.route("**/api/tracking/", async route => {
    if (followed && !refreshHeld) {
      refreshHeld = true;
      await new Promise<void>(resolve => { release = resolve; });
    }
    await route.fulfill({json:{bills:[{id:1,bill,created_at:"2025-01-01"}, ...(followed ? [{id:2,bill:other,created_at:"2026-11-22"}] : [])],topics:[],legislators:[]}});
  });
  await page.goto("/");
  const row = page.getByRole("region",{name:"Recommended bills",exact:true});
  const button = row.getByRole("button",{name:/Follow bill/});
  await button.scrollIntoViewIfNeeded();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const before = await button.boundingBox();
  const scroll = await page.evaluate(() => window.scrollY);
  const portrait = row.getByRole("img",{name:"Katie Britt"});
  await expect(portrait).toBeAttached();
  const portraitNode = await portrait.elementHandle();
  await button.click();
  await expect.poll(() => Boolean(release)).toBe(true);
  await expect(page.getByRole("region",{name:"Followed bills",exact:true})).toBeVisible();
  await expect(row.getByRole("link",{name:other.title})).toBeVisible();
  expect(await page.evaluate(() => window.scrollY)).toBe(scroll);
  release();
  await expect(page.getByRole("region",{name:"Followed bills",exact:true}).getByRole("article")).toHaveCount(1);
  const saved = row.getByRole("button",{name:/Unfollow bill/});
  await expect(saved).toBeFocused();
  expect(await saved.boundingBox()).toEqual(before);
  expect(await page.evaluate(() => window.scrollY)).toBe(scroll);
  expect(await portraitNode!.evaluate(node => node.isConnected)).toBe(true);
  expect(portraitRequests).toBe(1);
  await page.reload();
  await expect(page.getByRole("region",{name:"Followed bills"}).getByRole("article")).toHaveCount(2);
});

for (const width of [1280, 390]) test(`bill modal pagination stays stable at ${width}px during loading, errors and short pages`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 900 });
  await fixtures(page);
  let finishBill!: () => void;
  await page.route("**/api/bills/1/?contract_view=summary", async route => { await new Promise<void>(resolve => { finishBill = resolve; }); await route.fulfill({ json: {
    ...compactBill, summary_preview: "Helps students stay in school.",
    latest_contract: { id:7, document:3, schema_version:"2.1-legal-nlp", contract_hash:"fixture", computed_at:"2026-01-01", document_version_label:"Engrossed", coverage_note:"Test", orientation:{purpose_clause:null,purpose_line_item_id:null}, reader_stats:{line_item_count:7,financial_item_count:0,timeline_item_count:0,definition_item_count:0,section_group_count:1} },
  } }); });
  let finish: (() => void) | undefined;
  let failNext = false;
  const item = (id: number) => ({ id: `item-${id}`, source_id: "source-1", section_id: "section-1", section_path: [{ level: "section", label: "1", heading: "School programs" }], kind: "requirement", display_text: `Schools must report student outcomes for program ${id}.`, actor: null, action: null, effect: null, exact_financial_count: 0, exact_financial_preview: [], timeline_count: 0, timeline_preview: [], definition_count: 0 });
  await page.route("**/api/contracts/7/reader-items/**", async route => {
    const second = new URL(route.request().url()).searchParams.get("page") === "2";
    if (second) await new Promise<void>(resolve => { finish = resolve; });
    if (second && failNext) { await route.fulfill({ status: 503, json: {} }); return; }
    await route.fulfill({ json: { count: 7, next: second ? null : "page2", previous: second ? "page1" : null, results: second ? [item(7)] : [1,2,3,4,5,6].map(item), section_supplements: [] } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: bill.title, exact: true }).click();
  const dialog = page.locator("dialog:modal");
  await expect(dialog.getByRole("status",{name:"Loading bill details"})).toBeVisible();
  const loadingFrame = await dialog.boundingBox();
  await expect.poll(() => Boolean(finishBill)).toBe(true);
  finishBill();
  const nav = dialog.getByRole("navigation", { name: "Bill explanation pages" });
  const next = nav.getByRole("button", { name: "Next" });
  await expect(next).toBeEnabled();
  expect(await dialog.boundingBox()).toEqual(loadingFrame);
  await next.scrollIntoViewIfNeeded();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const geometry = () => dialog.evaluate(el => {
    const rect = el.querySelector('[aria-label="Bill explanation pages"]')!.getBoundingClientRect();
    const frame = el.getBoundingClientRect();
    return { y: rect.y, height: rect.height, scroll: el.scrollTop, windowScroll: window.scrollY, frame: {x:frame.x,y:frame.y,width:frame.width,height:frame.height} };
  });
  const before = await geometry();
  failNext = true;
  await next.click();
  await expect(next).toBeDisabled();
  expect(await geometry()).toEqual(before);
  await expect.poll(() => Boolean(finish)).toBe(true);
  finish!(); finish = undefined;
  await expect(dialog.getByRole("alert")).toBeVisible();
  expect(await geometry()).toEqual(before);
  failNext = false;
  // Retry using the same pager; no error banner may displace it.
  await next.click();
  await expect.poll(() => Boolean(finish)).toBe(true);
  finish!();
  await expect(nav).toContainText("Page 2");
  expect(await geometry()).toEqual(before);
  await nav.getByRole("button", { name: "Prev" }).click();
  await expect(nav).toContainText("Page 1");
  expect(await geometry()).toEqual(before);
  await page.screenshot({ path: info.outputPath(`stable-modal-${width}.png`) });
});

test("both dashboard rows open a native estimate modal without starting work", async ({ page }) => {
  await fixtures(page);
  const starts: string[] = [];
  page.on("request", request => {
    if (request.method() === "POST" && request.url().includes("/enhancements/")) starts.push(request.url());
  });
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({ json: {
    algorithm: "fixture", generated_at: "2026-11-21T12:00:00Z", count: 1, next_cursor: null,
    unsupported_follow_types: [], candidate_pool_truncated: false, ranking_limit_reached: false,
    empty_reason: null, results: [{ bill: { ...other, card_summary: "Helps schools buy books." }, score: 1, reasons: [] }],
  } }));
  await page.route("**/enhancements/estimate/", route => route.fulfill({ json: {
    can_enhance: true, feature_available: true, credential_revision: 1, estimated_input_tokens: 1234,
    max_output_tokens: 100, request_fingerprint: "request", source_fingerprint: "source", requested_model: "test",
  } }));
  await page.goto("/");
  await expect(page.getByText("Helps schools buy books.")).toBeVisible();
  for (const name of ["Followed bills", "Recommended bills"]) {
    const opener = page.getByRole("region", { name, exact: true }).getByRole("button", { name: "Enhance", exact: true }).first();
    await opener.click();
    const modal = page.locator("dialog:modal");
    await expect(modal).toContainText("1,234 estimated input tokens");
    await page.keyboard.press("Escape");
    await expect(modal).toHaveCount(0);
    await expect(opener).toBeFocused();
  }
  await page.route("**/enhancements/estimate/", route => route.fulfill({status: 503, json: {}}));
  for (const name of ["Followed bills", "Recommended bills"]) {
    const card = page.getByRole("region", { name, exact: true }).getByRole("article").first();
    const enhance = card.getByRole("button", { name: "Enhance", exact: true });
    const follow = card.getByRole("button", { name: /^(Unfollow|Follow bill)/ });
    await enhance.scrollIntoViewIfNeeded();
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    const boxes = () => Promise.all([enhance.boundingBox(), follow.boundingBox()]);
    const before = await boxes();
    await enhance.click();
    await expect(card.getByRole("alert")).toBeVisible();
    expect(await boxes()).toEqual(before);
  }
  expect(starts).toEqual([]);
});

for (const width of [1280, 390, 320]) test(`card actions stay side by side at the bottom right at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 900 });
  await fixtures(page);
  let failPortrait!: () => void;
  await page.route("**/img/member/t000001_200.jpg", async route => {
    await new Promise<void>(resolve => { failPortrait = resolve; });
    await route.abort();
  });
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({ json: {
    algorithm: "fixture", generated_at: "2026-11-21T12:00:00Z", count: 1, next_cursor: null,
    unsupported_follow_types: [], candidate_pool_truncated: false, ranking_limit_reached: false,
    results: [{ bill: other, score: 1, reasons: [] }], empty_reason: null,
  } }));
  await page.route("**/enhancements/estimate/", route => route.fulfill({status:503,json:{}}));
  await page.goto("/");
  for (const name of ["Followed bills", "Recommended bills"]) {
    const card = page.getByRole("region", {name, exact:true}).getByRole("article").first();
    const follow = card.getByRole("button", {name:/^(Unfollow|Follow bill)/});
    const enhance = card.getByRole("button", {name:"Enhance", exact:true});
    await enhance.scrollIntoViewIfNeeded();
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    const f = (await follow.boundingBox())!, e = (await enhance.boundingBox())!, c = (await card.boundingBox())!;
    const date = (await card.locator("time").locator("..").boundingBox())!;
    expect(Math.abs(date.y + date.height / 2 - e.y - e.height / 2)).toBeLessThan(2);
    expect(date.x + date.width).toBeLessThanOrEqual(f.x - 4);
    expect(Math.abs(f.y + f.height / 2 - e.y - e.height / 2)).toBeLessThan(2);
    expect(e.x).toBeGreaterThanOrEqual(f.x + f.width);
    expect(c.x + c.width - e.x - e.width).toBeLessThan(28);
    expect(c.y + c.height - Math.max(e.y + e.height, f.y + f.height)).toBeLessThan(85);
    if (name === "Followed bills") {
      await expect.poll(() => Boolean(failPortrait)).toBe(true);
      failPortrait();
      await expect(card.getByText("TR", {exact:true})).toBeVisible();
      expect(await enhance.boundingBox()).toEqual(e);
    }
    await enhance.click();
    await expect(card.getByRole("alert")).toBeVisible();
    expect(await enhance.boundingBox()).toEqual(e);
    expect(await follow.boundingBox()).toEqual(f);
    await card.screenshot({path:info.outputPath(`${name.replaceAll(" ", "-")}-${width}.png`)});
  }
});

test("estimate modal keeps its outer dimensions when details expand", async ({page}) => {
  await fixtures(page);
  await page.route("**/enhancements/estimate/", route => route.fulfill({json:{
    can_enhance:true, feature_available:true, credential_revision:1, source_fingerprint:"source", request_fingerprint:"request",
    estimated_input_tokens:100, max_output_tokens:100, requested_model:"fixture",
    reader_coverage:{selected_count:1,total_count:21,batch_count:1,unavailable_count:20,unavailable:Array.from({length:20},(_,i)=>({target_id:`item-${i}`,reason:"source_unavailable"}))},
  }}));
  await page.goto("/");
  await page.getByRole("button", {name:"Enhance",exact:true}).first().click();
  const modal = page.locator("dialog:modal");
  await expect(modal).toBeVisible();
  const before = await modal.boundingBox();
  await modal.getByText("Items that will keep their original explanation",{exact:true}).click();
  expect(await modal.boundingBox()).toEqual(before);
});

test("dashboard to bill and back reuses unchanged cards without loading the directory", async ({ page }) => {
  const paths: string[] = [];
  page.on("request", req => { if (req.method() === "GET") paths.push(new URL(req.url()).pathname + new URL(req.url()).search); });
  await fixtures(page);
  await page.route("**/api/tracking/recommendations/**", route => route.fulfill({json: {
    algorithm: "fixture", generated_at: "2026-11-21T12:00:00Z", count: 1, next_cursor: null,
    unsupported_follow_types: [], candidate_pool_truncated: false, ranking_limit_reached: false,
    empty_reason: null, results: [{bill: other, score: 1, reasons: []}]
  }}));
  const member = { id: 5, name: "Test Senator", bioguide_id: "T000005", chamber: "senate", state: "NY" };
  await page.route("**/api/tracking/representative-recommendations/", route => route.fulfill({json: {
    results: [{representative_id: 5, ...member, reasons: [], topic_activity_evidence: {
      representative: member, channels: {sponsor: {topics: []}, active_cosponsor: {topics: []}}
    }}]
  }}));
  await page.route("**/api/representatives/5/card/", route => route.fulfill({json: {
    biography: {text: "Represents New York."}, portrait: null, latest_bill: null
  }}));
  await page.route("**/api/representatives/5/research/**", route => route.fulfill({json: {
    status: "not_started", period: 2026, run: null, portrait: null, biography: null, snapshot: null
  }}));
  await page.goto("/");
  const title = page.getByRole("button", { name: bill.title, exact: true });
  await expect(title).toBeVisible();
  await expect(page.getByText("Represents New York.")).toBeVisible();
  await expect(page.getByRole("link", {name: other.title})).toBeVisible();
  expect(paths).not.toContain("/api/representatives/");
  expect(paths).toContain("/api/tracking/");
  await title.click();
  await page.getByRole("dialog").getByRole("link", { name: bill.title }).click();
  await expect(page).toHaveURL(/\/bills\/1$/);
  await expect(page.getByRole("heading", { name: "H.R. 1589 · Congress 119" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tracked bill", exact: true })).toBeVisible();
  expect(paths.filter(p => p === "/api/tracking/")).toHaveLength(1);
  paths.length = 0;
  const checked = page.waitForResponse(r => new URL(r.url()).searchParams.get("dashboard") === "1" && new URL(r.url()).pathname === "/api/auth/session/current/" && r.status() === 200);
  await page.goBack();
  await checked;
  await expect(title).toBeVisible();
  await expect(page.getByText("Represents New York.")).toBeVisible();
  await expect(page.getByRole("link", {name: other.title})).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh bill recommendations" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Refresh representative recommendations" })).toBeEnabled();
  expect(paths.filter(p => p.startsWith("/api/tracking/") || p.startsWith("/api/representatives/") || p === "/api/bills/filter-options/")).toEqual([]);
  expect(paths.filter(p => p === "/api/auth/session/current/?dashboard=1")).toHaveLength(1);
});

test("ordinary readers cannot access ingestion controls or trigger ingestion requests", async ({ page }) => {
  const writes: string[] = [];
  const ingestionRequests: string[] = [];
  page.on("request", request => { if (!["GET", "HEAD", "OPTIONS"].includes(request.method()) && request.url().includes("/api/")) writes.push(request.url()); });
  page.on("request", request => { if (request.url().includes("/api/ingestion/")) ingestionRequests.push(request.url()); });
  await page.addInitScript(() => localStorage.setItem("legislation-tracker-ingestion-telemetry", "true"));
  await fixtures(page); await page.goto("/");
  await expect(page.getByRole("button", { name: bill.title, exact: true })).toBeVisible();
  const panel = page.getByRole("region", { name: "Legislation ingestion" });
  await expect(panel).toHaveCount(0);
  await expect(page.getByLabel("Show ingestion telemetry preview")).toHaveCount(0);
  await expect(page.getByText("24 sample", { exact: true })).toHaveCount(0);
  expect(writes).toEqual([]);
  expect(ingestionRequests).toEqual([]);
});

test("staff dashboard never exposes sample telemetry even with a legacy preference", async ({ page }) => {
  const ingestionRequests: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/ingestion/")) ingestionRequests.push(request.url()); });
  await page.addInitScript(() => localStorage.setItem("legislation-tracker-ingestion-telemetry", "true"));
  await fixtures(page);
  await page.route("**/api/auth/session/current/**", route => route.fulfill({ json: { authenticated: true, user: { email: "admin@example.com", is_superuser: true } } }));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Expand legislation ingestion" })).toBeVisible();
  const toggle = page.getByLabel("Show ingestion telemetry preview");
  await expect(toggle).toHaveCount(0);
  await expect(page.getByText("24 sample", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Show sample data")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand legislation ingestion" })).toBeVisible();
  await expect(toggle).toHaveCount(0);
  await expect(page.getByText("24 sample", { exact: true })).toHaveCount(0);
  expect(ingestionRequests).toEqual([]);
});

test("staff operational telemetry refresh is read-only and start is an explicit mocked action", async ({page})=>{
  await fixtures(page);
  await page.route("**/api/auth/session/current/**", route => route.fulfill({ json: { authenticated: true, user: { email: "admin@example.com", is_superuser: true } } }));
  await page.route("**/api/tracking/",route=>route.fulfill({json:{bills:[],topics:[],legislators:[],is_staff:true}}));
  let starts=0;const keys:string[]=[];
  await page.route("**/api/ingestion/telemetry/**",route=>route.fulfill({json:{observed_at:"2026-10-09T18:00:00Z",last_discovery_completed_at:"2026-10-09T17:00:00Z",last_successful_work_item_at:"2026-10-09T17:15:00Z",counts_by_kind_and_status:[{kind:"bill",status:"pending",count:4},{kind:"bill_versions",status:"processing",count:2},{kind:"document_download",status:"blocked",count:1}],stale_leases:0,discovery_run:{id:starts ? "fixture-start" : "fixture-run",status:"succeeded",started_at:"2026-10-09T16:55:00Z",finished_at:"2026-10-09T17:00:00Z",discovered:6,created:4},recent_work_states:[{id:1,kind:"bill",status:"pending",updated_at:"2026-10-09T18:00:00Z"}]}}));
  await page.route("**/api/ingestion/source-readiness/**",route=>route.fulfill({json:{available:false,ready_to_start:null,age_seconds:500,complete:true,reason:"Source check stale"}}));
  await page.route("**/api/ingestion/poll-congress/",route=>{starts++;keys.push(route.request().postDataJSON().idempotency_key);return route.fulfill({json:{run_id:"fixture-start",status:"pending"}});});
  await page.goto("/");
  await expect(page.getByLabel("Show ingestion telemetry preview")).toHaveCount(0);
  await expect(page.getByText("24 sample", { exact: true })).toHaveCount(0);
  const panel=page.getByRole("region",{name:"Legislation ingestion"});
  await panel.getByRole("button", {name:"Expand legislation ingestion"}).click();
  await expect(panel.getByRole("button",{name:"Start discovery and ingestion",exact:true})).toBeEnabled();
  const refresh = panel.getByRole("button",{name:"Refresh telemetry"});
  await refresh.scrollIntoViewIfNeeded();
  const refreshPosition = await refresh.boundingBox();
  await refresh.click();
  await expect(panel.getByText("Current pipeline backlog",{exact:true})).toBeVisible();
  expect(await refresh.boundingBox()).toEqual(refreshPosition);
  await expect(panel.getByText("Source & technical details").locator("..")).not.toHaveAttribute("open", "");
  await panel.getByText("Source & technical details", {exact:true}).click();
  await expect(panel.getByText(/Stale — readiness is unavailable/)).toBeVisible();
  expect(starts).toBe(0);
  await panel.screenshot({path:"test-results/ingestion-telemetry-operational-fixture.png"});
  const start=panel.getByRole("button",{name:"Start discovery and ingestion",exact:true});
  await start.click();await expect(panel.getByRole("status")).toContainText("fixture-start");
  await expect(panel.getByRole("button",{name:"Prepare a new discovery request"})).toBeDisabled();
  await start.click();await expect.poll(()=>starts).toBe(2);expect(keys[0]).toBe(keys[1]);
  await panel.getByRole("button",{name:"Refresh telemetry"}).click();
  await panel.getByRole("button",{name:"Prepare a new discovery request"}).click();
  await start.click();await expect.poll(()=>starts).toBe(3);expect(keys[2]).not.toBe(keys[0]);
});

test("filters, collection, follow behavior and modal keyboard navigation", async ({ page }) => {
  await fixtures(page); await page.goto("/");
  const title = page.getByRole("button", { name: bill.title, exact: true });
  await expect(title).toBeVisible();
  await page.getByLabel("Sponsor state").selectOption("NY"); await expect(title).toBeVisible();
  await page.getByLabel("Status", { exact: true }).selectOption("introduced");
  await page.getByLabel("Topic", { exact: true }).selectOption("1");
  await page.getByLabel("Representative (sponsor)").selectOption("id:1");
  await page.getByLabel("Search bills").fill("no match"); await expect(page.getByText("No bills match these filters")).toBeVisible();
  await page.getByLabel("Search bills").fill("");
  await title.click(); const modal = page.getByRole("dialog"); await expect(modal).toBeVisible();
  await expect(modal.getByText("Raises the deduction limit.")).toBeVisible();
  for (let index = 0; index < 14; index++) { await page.keyboard.press("Tab"); expect(await modal.evaluate(element => element.contains(document.activeElement))).toBe(true); }
  await modal.getByRole("button",{name:"Close bill details"}).focus();
  await page.keyboard.press("Escape"); await expect(modal).toHaveCount(0); await expect(title).toBeFocused();
  await expect(page.getByRole("button", { name: "View all bills" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: other.title })).toHaveCount(0);
  await page.reload(); await expect(title).toBeVisible();
  await page.getByRole("button", { name: "Unfollow", exact: true }).click();
  await expect(page.getByText("Your collection starts with a bill")).toBeVisible();
  await expect(title).toHaveCount(0);
});

test("responsive visual evidence and empty collection", async ({ page }) => {
  await fixtures(page); await page.goto("/"); await expect(page.getByRole("button", { name: bill.title })).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-desktop.png", fullPage: true });
  await page.goto("/bills"); await expect(page.getByRole("link", { name: other.title })).toBeVisible();
  await page.screenshot({ path: "test-results/bills-catalog.png", fullPage: true });
  await page.goto("/");
  await page.setViewportSize({ width: 1280, height: 1050 });
  await page.getByRole("button", { name: bill.title }).click();
  await expect(page.getByRole("dialog").getByText("Raises the deduction limit.")).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-modal-desktop.png", fullPage: false });
  await page.keyboard.press("Escape");
  for (const [name, width] of [["tablet", 768], ["mobile", 390]] as const) {
    await page.setViewportSize({ width, height: 850 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/dashboard-${name}.png`, fullPage: true });
  }
  await page.getByRole("button", { name: bill.title }).click(); await expect(page.getByRole("dialog").getByText("Raises the deduction limit.")).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-modal-mobile.png", fullPage: false });
  await page.keyboard.press("Escape"); await page.setViewportSize({ width: 1280, height: 850 });
  await page.emulateMedia({colorScheme:"dark"});
  await page.screenshot({ path: "test-results/dashboard-dark.png", fullPage: true });
});

test("empty followed bills and topics", async ({ page }) => {
  await fixtures(page, true); await page.goto("/"); await expect(page.getByText("Your collection starts with a bill")).toBeVisible(); await expect(page.getByText("Follow topics to organize")).toBeVisible();
});

test("catalog cards append in list view and link to full bill pages", async ({ page }) => {
  await fixtures(page);
  await page.route("**/api/bills/?**", async route => {
    const params = new URL(route.request().url()).searchParams;
    const second = params.get("page") === "2";
    expect(params.get("session")).toBe("119");
    const firstPage = [bill, ...Array.from({ length: 19 }, (_, index) => ({ ...bill, id: 100 + index, title: `Catalog bill ${index + 1}` }))];
    await route.fulfill({ json: { count: 21, next: second ? null : "?page=2", previous: second ? "?page=1" : null, results: second ? [other] : firstPage } });
  });
  await page.goto("/bills?session=119");
  const title = page.getByRole("link", { name: bill.title, exact: true });
  await expect(title).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  await expect(title).toHaveAttribute("href", "/bills/1");
  await page.getByRole("button", { name: "List", exact: true }).click();
  await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.locator('[aria-label="More bills"]').scrollIntoViewIfNeeded();
  await expect(page.getByRole("link", { name: other.title })).toBeAttached();
  await expect(title).toHaveCount(1);
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByRole("article")).toHaveCount(21);
});

test("dashboard tracking errors remain actionable without offering a catalog", async ({ page }) => {
  await fixtures(page);
  await page.route("**/api/tracking/", route => route.fulfill({ status: 503, json: { detail: "Unavailable" } }));
  await page.goto("/");
  const alert = page.getByRole("alert").filter({ hasText: "Couldn’t refresh your bills." });
  await expect(alert).toBeVisible();
  await expect(page.getByRole("button", { name: "View all bills" })).toHaveCount(0);
  await page.unroute("**/api/tracking/");
  await alert.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("button", { name: bill.title })).toBeVisible();
});

test("an absent summary stays empty and an older comparison cannot replace the selected versions", async ({page}) => {
  await fixtures(page);
  await page.route("**/api/bills/1/?contract_view=summary", route => route.fulfill({json:{...compactBill,summary_preview:null}}));
  await page.goto("/");
  await page.getByRole("button",{name:bill.title}).click();
  const modal = page.getByRole("dialog");
  await expect(modal.getByText("No bill summary is available yet.")).toBeVisible();
  await modal.getByRole("link",{name:bill.title}).click();
  await page.getByRole("tab",{name:"Versions"}).click();
  let release!: () => void;
  const pending = new Promise<void>(resolve => {release = resolve;});
  await page.route("**/comparisons/documents/**", async route => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get("after") === "3") await pending;
    await route.fulfill({json:{before:Number(params.get("before")),after:Number(params.get("after")),sections:[],
      total_change_count:0,returned_change_count:0,truncated:params.get("after")==="3",fallback:false,truncation_reasons:[]}}).catch(() => {});
  });
  const old = page.waitForRequest(r => r.url().includes("/comparisons/documents/") && new URL(r.url()).searchParams.get("after") === "3");
  await page.getByRole("button",{name:"Compare versions"}).click();
  await old;
  await page.getByLabel("Before version").selectOption("1");
  await page.getByLabel("After version").selectOption("2");
  await expect(page.getByText("No text changes were found between these versions.")).toBeVisible();
  const stale = page.waitForResponse(r => r.url().includes("/comparisons/documents/") && new URL(r.url()).searchParams.get("after") === "3");
  release();
  await stale;
  await expect(page.getByText("No text changes were found between these versions.")).toBeVisible();
  await expect(page.getByText("No changes were found in the portion compared.")).toHaveCount(0);
  await expect(page.getByRole("link",{name:"Read full after version"})).toHaveAttribute("href","/documents/2");
});

test("telemetry separates incremental readiness from historical inventory gaps", async ({page}) => {
  await fixtures(page);
  await page.route("**/api/auth/session/current/**", route => route.fulfill({ json: { authenticated: true, user: { email: "admin@example.com", is_superuser: true } } }));
  await page.route("**/api/ingestion/telemetry/**",route=>route.fulfill({json:{observed_at:"2026-10-09T18:10:00Z",counts_by_kind_and_status:[],stale_leases:0,discovery_run:null,recent_work_states:[]}}));
  let valid=true;
  await page.route("**/api/ingestion/source-readiness/**",route=>route.fulfill({json:{available:true,age_seconds:1,complete:true,missing_unqueued_metadata:9,ready_to_start:valid?3:null,incremental_discoverable_count_available:valid,discovery_basis:{cursor_at:"2026-10-09T18:00:00Z",from_date_time:"2026-10-09T17:55:00Z"},discovery_checked_completed_at:"2026-10-09T18:10:00Z"}}));
  await page.goto("/");
  const panel=page.getByRole("region",{name:"Legislation ingestion"});
  await panel.getByRole("button",{name:"Expand legislation ingestion"}).click();
  await panel.getByText("Source & technical details", {exact:true}).click();
  const ready=panel.getByRole("heading",{name:"Ready for incremental discovery"}).locator("..");
  const gaps=panel.getByRole("heading",{name:"Missing unqueued metadata"}).locator("..");
  await expect(ready.locator("strong")).toHaveText("3");await expect(gaps.locator("strong")).toHaveText("9");
  await expect(panel.getByText(/Discovery basis: cursor/)).toContainText("2026-10-09T17:55:00Z");
  await panel.screenshot({path:"test-results/ingestion-telemetry-readiness-fixture.png"});
  valid=false;await panel.getByRole("button",{name:"Refresh telemetry"}).click();
  await expect(ready.locator("strong")).toHaveText("Unavailable");await expect(gaps.locator("strong")).toHaveText("9");
});
