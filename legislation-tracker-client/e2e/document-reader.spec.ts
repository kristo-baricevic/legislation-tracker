import { test, expect } from '@playwright/test';

test('document-only enhancement renders on desktop and mobile without generation', async ({ page }, info) => {
  const citation = { source_ref: 'src_0001', quoted_text: 'Employers must protect workers.', start_char: 0, end_char: 30 };
  const enhancement = { id: 1, bill_id: 1, status: 'succeeded', source_compatible: true, stale: false,
    result: { schema_version: '1.4', identity: { contract_id: null, contract_hash: null, document_id: 4, document_content_hash: 'text' },
      summary: [{ text: 'Protects workers from harassment.', cited_sources: [citation] }], explanations: [],
      source_review: { reviewed_sources: ['src_0001'], additional_changes: [],
        policy_changes: [{ title: 'Protect workers', text: 'Employers must protect workers.', cited_sources: [citation] }],
        financial_items: [{ label: 'Penalty', amount_display: '$1,000', text: 'Employers face a fine.', fiscal_years: [], cited_sources: [citation] }] } } };
  let generationCalls = 0;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === 'POST' && path.includes('enhancements')) generationCalls++;
    let data: unknown = { count: 0, results: [], next: null, previous: null };
    if (path === '/api/auth/session/current/') data = { authenticated: true, user: { email: 'fixture@example.test' } };
    else if (path === '/api/capabilities/') data = { llm_enhancements: true };
    else if (path === '/api/tracking/') data = { bills: [], topics: [], legislators: [], is_staff: false };
    else if (path.endsWith('/enhancements/latest/')) data = { ...enhancement, active_reader: enhancement };
    else if (path === '/api/bills/1/') data = { id: 1, bill_number: 'HR 1', session: 119, title: 'Worker protection test bill',
      status: 'introduced', jurisdiction: 'federal', sponsor: null, sponsor_name: null, introduced_at: null, last_action_at: null,
      latest_contract: null, summary_preview: 'Original summary.', summary_has_more: false,
      summary_source: null, summary_version_code: null, summary_action_date: null, summary_last_updated_at: null,
      processing_status: 'complete', topics: [], source_api_id: null, congress_gov_url: null,
      created_at: '2026-01-01', updated_at: '2026-01-01',
      documents: [{ id: 4, is_active_version: true, source_order: 1, version_label: 'Introduced', content_type: 'text/xml',
        file_size_bytes: 30, source_url: null, downloaded_at: null, download_url: null, text_url: null }] };
    await route.fulfill({ json: data });
  });
  await page.goto('/bills/1?tab=changes');
  await expect(page.getByText('Protects workers from harassment.', { exact: false })).toBeVisible();
  await expect(page.getByText('Employers must protect workers.', { exact: false })).toBeVisible();
  await page.screenshot({ path: info.outputPath('SIMULATED-document-review-desktop.png'), fullPage: true });
  await page.getByRole('tab', { name: 'Money', exact: true }).click();
  await expect(page.getByText('Employers face a fine.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Original', exact: true }).click();
  await expect(page.getByText('Original summary.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Enhanced', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText('Employers face a fine.', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('SIMULATED-document-review-mobile.png'), fullPage: true });
  expect(generationCalls).toBe(0);
});
