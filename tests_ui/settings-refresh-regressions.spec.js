const {test,expect}=require('@playwright/test');
const {openApp}=require('./_helpers');
test.beforeEach(async({page})=>openApp(page));
test('settings split and compact path layout',async({page})=>{
  await page.setViewportSize({width:1000,height:640});
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="general"]').click();
  await expect(page.locator('[data-key="media.videoMode"]')).toBeVisible();
  await page.locator('.stg-nav-item[data-section="metadata"]').click();
  await expect(page.locator('.translation-settings')).toBeVisible();
  await expect(page.locator('[data-key="media.videoMode"]')).toHaveCount(0);
  await page.locator('.stg-nav-item[data-section="tags"]').click();
  await expect(page.locator('.stg-title-affix')).toBeVisible();
  await page.locator('.stg-nav-item[data-section="archive"]').click();
  await expect(page.locator('.archive-rescan')).toHaveCount(0);
  const dimensions=await page.locator('[data-key="archive.archiveDir"]').evaluate(el=>{
    const label=el.querySelector('.stg-label').getBoundingClientRect(),path=el.querySelector('.stg-path').getBoundingClientRect();
    return{stacked:path.top>=label.bottom-1,overflow:el.scrollWidth>el.clientWidth};
  });
  expect(dimensions).toEqual({stacked:true,overflow:false});
  await page.screenshot({path:".codex-test-tmp/settings-archive-compact.png"});
});
test('scraper connection cancel restores settings and selected section',async({page})=>{
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="scraper"]').click();
  await page.getByRole('button',{name:'연결 설정…',exact:true}).click();
  await expect(page.locator('.scrape-setup-card')).toBeVisible();
  await page.locator('.scrape-setup-card').getByRole('button',{name:'취소',exact:true}).click();
  await expect(page.locator('.stg-nav-item[data-section="scraper"]')).toHaveClass(/active/);
});
test('advanced omits routine recovery controls',async({page})=>{
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="advanced"]').click();
  await expect(page.locator('[data-key="advanced.recovery"]')).toHaveCount(0);
});

test('old metadata editor disappears while next game is loading',async({page})=>{
  const rows=page.locator('.lrow');
  await rows.nth(0).click();await expect(page.locator('.detail-save')).toBeVisible();
  await page.evaluate(()=>{const original=window.api.getRow;window.api.getRow=(...args)=>new Promise(resolve=>setTimeout(()=>original(...args).then(resolve),600));});
  await rows.nth(1).click();
  await expect(page.locator('.detail-save')).toHaveCount(0);
  await expect(page.locator('.detail-save')).toBeVisible();
});
test('media type labels remain untranslated',async({page})=>{
  await page.locator('.lrow').first().click();
  await page.locator('.detail-tab').nth(1).click();
  await expect(page.locator('.media-tile-label').filter({hasText:'Cover'}).first()).toHaveText('Cover');
  await expect(page.locator('.media-tile-label').filter({hasText:'Screenshot'}).first()).toHaveText('Screenshot');
});
