// Called by the PostgreSQL staged-flow test while its isolated API is live.
const { chromium, expect } = require("@playwright/test");

async function check() {
  const [api, billId] = process.argv.slice(2);
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const origin = process.env.STAGED_READER_CLIENT;
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      const response = await route.fetch({
        url: api + url.pathname + url.search,
        headers: {cookie: process.env.STAGED_READER_SESSION},
      });
      await route.fulfill({response, headers: {...response.headers(),
        "access-control-allow-origin": origin, "access-control-allow-credentials":"true"}});
    });
    await page.goto(origin + "/bills/" + billId + "?tab=changes");
    const enhanced = page.getByRole("button", {name:"Enhanced", exact:true});
    await enhanced.click();
    await expect(page.getByText("School grants require a non-Federal contribution equal to 50 percent of the grant amount.", {exact:false}).first()).toBeVisible();
    await expect(page.getByText("The Secretary must award grants to qualifying schools, requiring a non-Federal matching contribution equal to 50 percent of the grant amount.", {exact:false}).first()).toBeVisible();
    await page.getByRole("tab",{name:"Money",exact:true}).click();
    await expect(page.getByRole("tabpanel")).toContainText("50 percent");
  } finally {
    await browser.close();
  }
}
check().catch(error => {console.error(error); process.exitCode = 1;});
