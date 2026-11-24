import { test, expect } from '@playwright/test';

test('native and custom filters share one dropdown appearance on desktop and mobile', async ({ page }) => {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.includes('/session/current') ? { authenticated: false }
      : path === '/api/topics/' ? [{ id: 9, name: 'Education', slug: 'education' }]
      : path.includes('filter-options') ? { jurisdictions: ['federal'], current_congress: 119 }
      : { congress: 119, count: 0, results: [], next: null, previous: null } });
  });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    let reference: unknown;
    for (const path of ['/bills', '/representatives', '/committees']) {
      await page.goto(path);
      const controls = page.locator('select, button[aria-haspopup="listbox"]');
      await expect(controls.first()).toBeVisible();
      const styles = await controls.evaluateAll(elements => elements.map(element => {
        const css = getComputedStyle(element);
        return { arrow: css.backgroundImage, appearance: css.appearance, height: css.height,
          border: css.border, radius: css.borderRadius, padding: css.padding, fontSize: css.fontSize,
          color: css.color, background: css.backgroundColor };
      }));
      reference ??= styles[0];
      expect(styles[0].arrow).not.toBe('none');
      for (const style of styles) expect(style).toEqual(reference);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }
});
