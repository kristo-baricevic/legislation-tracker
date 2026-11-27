import {test, expect} from '@playwright/test';
import fixture from './fixtures/reader-simulated.json';

test('simulated reader output renders full explanations and source tooltips without model calls', async ({page}, info) => {
  const result = {...fixture.result, identity:fixture.source_manifest};
  const simulated = {...fixture, result};
  let mutations = 0;
  page.on('request', r => { if(r.method() === 'POST' && r.url().includes('/enhancements/')) mutations++; });
  await page.route('**/api/**', async route => {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method()))
      return route.fulfill({status:403,json:{detail:'Read-only simulated test'}});
    return route.fallback();
  });
  await page.route('**/api/auth/session/current/', r => r.fulfill({json:{authenticated:true,user:{email:'simulation@example.test'}}}));
  await page.route('**/api/capabilities/', r => r.fulfill({json:{llm_enhancements:true}}));
  await page.route(url => url.pathname === '/api/tracking/', r => r.fulfill({json:{bills:[],topics:[],legislators:[],is_staff:false}}));
  await page.route('**/enhancements/latest/', r => r.fulfill({json:{...simulated,active_reader:simulated}}));
  await page.route('**/enhancements/', r => r.fulfill({json:{count:0,results:[]}}));
  await page.route(url => url.pathname === '/api/bills/460/', r => r.fulfill({json:{
    id:460, bill_number:'H.R. 460', session:119, title:'Simulated reader bill', jurisdiction:'federal',
    status:'introduced', documents:[], topics:[], summary_preview:'', latest_contract:{
      id:fixture.source_manifest.contract_id, contract_hash:fixture.source_manifest.contract_hash,
      document:fixture.source_manifest.document_id, document_version_label:'Introduced',
      computed_at:'2026-01-01', schema_version:'2.1-legal-nlp', coverage_note:'Simulated bill text',
      orientation:{purpose_clause:null,purpose_line_item_id:null},
      reader_stats:{line_item_count:0,financial_item_count:0,timeline_item_count:0,definition_item_count:0,section_group_count:0}
    },
    sponsor:null, sponsor_name:null, introduced_at:null, last_action_at:null, summary_has_more:false,
    summary_source:null, summary_version_code:null, summary_action_date:null, summary_last_updated_at:null,
    processing_status:'complete', source_api_id:null, congress_gov_url:null,
    created_at:'2026-01-01', updated_at:'2026-01-01'
  }}));
  await page.goto('/bills/460?tab=changes');
  await expect(page.getByText(fixture.result.summary[0].text,{exact:false})).toBeVisible();
  for(const p of fixture.result.source_review.policy_changes) {
    await expect(page.getByRole('heading',{name:p.title,exact:true})).toBeVisible();
    await expect(page.getByText(p.text,{exact:false})).toBeVisible();
  }
  await expect(page.getByRole('list', {name:'Bill policy changes'}).locator('p').filter({hasText:/^\.\[/})).toHaveCount(0);
  await expect(page.getByText('.',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Source 1',exact:true}).click();
  await expect(page.getByRole('link',{name:'Read bill text',exact:true})).toBeVisible();
  await page.keyboard.press('Escape');
  await page.screenshot({path:info.outputPath('SIMULATED-reader-desktop.png'),fullPage:true});
  await page.getByRole('tab',{name:'Money',exact:true}).click();
  await expect(page.getByText(fixture.result.source_review.financial_items[0].text,{exact:false})).toBeVisible();
  await page.getByRole('tab',{name:'What this bill does',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByText(fixture.result.summary[0].text,{exact:false})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('SIMULATED-reader-mobile.png'),fullPage:true});
  expect(mutations).toBe(0);
});
