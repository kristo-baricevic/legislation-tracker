import { test, expect } from '@playwright/test';

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`initial loading is centered and refresh retains content without an overlay (${viewport.width}px)`, async ({ page }, info) => {
    await page.setViewportSize(viewport);
    let release!: () => void;
    let gate = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/topics/') {
        await gate;
        await route.fulfill({ json: [{ id: 7, name: 'Health', slug: 'health' }] });
      } else if (path === '/api/auth/session/current/') {
        await route.fulfill({ json: { authenticated: false } });
      } else {
        await route.fulfill({ json: { count: 0, results: [], next: null } });
      }
    });
    await page.goto('/topics');
    const spinner = page.getByRole('status', { name: 'Loading topics' });
    await expect(spinner).toBeVisible();
    const bounds = await spinner.locator('span').boundingBox();
    expect(bounds).not.toBeNull();
    expect(Math.abs(bounds!.x + bounds!.width / 2 - viewport.width / 2)).toBeLessThan(2);
    expect(Math.abs(bounds!.y + bounds!.height / 2 - viewport.height / 2)).toBeLessThan(2);
    await expect(page.getByRole('link', { name: 'Health', exact: true })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath('SIMULATED-centered-loading.png') });
    release();
    const topic = page.getByRole('link', { name: 'Health', exact: true });
    await expect(topic).toBeVisible();
    await expect(spinner).toHaveCount(0);
    const before = await topic.boundingBox();
    gate = new Promise<void>(resolve => { release = resolve; });
    await page.getByRole('button', { name: 'Refresh topics' }).click();
    // Outlast the delayed spinner to catch an overlay that appears during refresh.
    await page.waitForTimeout(500);
    await expect(topic).toBeVisible();
    await expect(spinner).toHaveCount(0);
    expect(await topic.boundingBox()).toEqual(before);
    await page.screenshot({ path: info.outputPath('SIMULATED-retained-content.png') });
    release();
  });
}
