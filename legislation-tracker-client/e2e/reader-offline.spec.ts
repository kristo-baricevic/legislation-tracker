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
  await page.route('**/api/tracking/', r => r.fulfill({json:{bills:[],topics:[],legislators:[],is_staff:false}}));
  await page.route('**/enhancements/latest/', r => r.fulfill({json:{...simulated,active_reader:simulated}}));
  await page.route('**/enhancements/', r => r.fulfill({json:{count:0,results:[]}}));
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
