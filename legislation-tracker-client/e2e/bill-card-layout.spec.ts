import { test, expect } from '@playwright/test';

test('bill cards show enhancement state, center the list, and require confirmation', async ({ page }, info) => {
  let starts = 0;
  const bill = { id: 41, jurisdiction: 'federal', session: 119, bill_number: 'HR 41', title: 'Student support',
    status: 'introduced', sponsor_name: null, introduced_at: null, last_action_at: '2026-01-01', topics: [],
    card_summary: 'Helps students finish college.', enhancement_status: null, enhancement_id: null };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = { count: 0, results: [], next: null, previous: null };
    if (path === '/api/auth/session/current/') data = { authenticated: true, user: { email: 'fixture@example.test' } };
    else if (path === '/api/auth/csrf/') data = { csrf_token: 'fixture-csrf' };
    else if (path === '/api/tracking/') data = { bills: [], topics: [], legislators: [], is_staff: false };
    else if (path === '/api/topics/') data = [];
    else if (path === '/api/bills/filter-options/') data = { jurisdictions: ['federal'], current_congress: 119 };
    else if (path === '/api/bills/') data = { count: 2, next: null, previous: null, results: [bill, { ...bill, id: 42, title: 'School meals', enhancement_status: 'succeeded', enhancement_id: 9 }] };
    else if (path.includes('estimate')) data = { can_enhance: true, credential_revision: 1, source_fingerprint: 'source', request_fingerprint: 'request', estimated_input_tokens: 100, max_output_tokens: 100, provider: 'fixture', requested_model: 'fixture' };
    else if (route.request().method() === 'POST' && path.includes('enhancements')) { starts++; data = { id: 10, status: 'pending' }; }
    await route.fulfill({ json: data });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/bills');
  const results = page.getByRole('region', { name: 'Bill results' });
  await expect(results.getByRole('article')).toHaveCount(2);
  await expect(results.getByRole('button', { name: 'Enhanced', exact: true })).toBeDisabled();
  const enhanced = results.locator('article[data-enhanced="true"]');
  expect(await enhanced.evaluate(el => getComputedStyle(el).boxShadow)).toBe('none');
  const enhancedButton = enhanced.getByRole('button', { name: 'Enhanced', exact: true });
  await expect(enhancedButton).toHaveCSS('background-color', 'rgb(115, 80, 153)');
  await expect(enhancedButton).toHaveCSS('color', 'rgb(255, 255, 255)');
  await expect(enhancedButton).toHaveCSS('opacity', '1');
  const layout = page.getByLabel('Card layout');
  expect(await layout.evaluate(el => getComputedStyle(el.parentElement!).borderBottomWidth)).toBe('0px');
  await page.screenshot({ path: info.outputPath('SIMULATED-grid.png'), fullPage: true });
  await page.getByRole('button', { name: 'List', exact: true }).click();
  const box = await results.boundingBox();
  expect(Math.abs(box!.x + box!.width / 2 - 720)).toBeLessThan(2);
  await page.screenshot({ path: info.outputPath('SIMULATED-list.png'), fullPage: true });
  await results.getByRole('button', { name: 'Enhance', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByText('100 estimated input tokens')).toBeVisible();
  expect(starts).toBe(0);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(starts).toBe(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Grid', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const actions = results.getByRole('article').first();
  const follow = await actions.getByRole('button', { name: 'Follow', exact: true }).boundingBox();
  const enhance = await actions.getByRole('button', { name: 'Enhance', exact: true }).boundingBox();
  expect(Math.abs(follow!.y + follow!.height / 2 - enhance!.y - enhance!.height / 2)).toBeLessThan(2);
  await page.screenshot({ path: info.outputPath('SIMULATED-mobile.png'), fullPage: true });
  await actions.getByRole('button', { name: 'Enhance', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm and enhance' }).click();
  await expect(actions.getByRole('button', { name: 'Queued' })).toBeVisible();
  expect(starts).toBe(1);
});
