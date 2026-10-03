const {test,expect}=require('@playwright/test');
const {openApp}=require('./_helpers');
test('translation button follows successful test and disappears after failure',async({page})=>{
  await openApp(page);
  await page.evaluate(()=>{
    window.__verified=false;window.__fail=false;
    window.api.translationSettings=async()=>({ok:true,data:{mode:'google',hasKey:true,verified:window.__verified}});
    window.api.saveTranslationSettings=async()=>({ok:true,data:{mode:'google',hasKey:true,verified:window.__verified}});
    window.api.testTranslationConnection=async()=>{window.__verified=false;return {ok:true,data:{jobId:'test'}};};
    window.api.jobProgress=async()=>{window.__verified=!window.__fail;return{ok:true,data:{done:true,current:1,total:1,error:window.__fail?'ui.translation.authentication':null,result:{verified:window.__verified}}};};
  });
  await page.locator('.lrow').first().click();
  await expect(page.locator('.description-translate')).toBeHidden();
  await page.locator('.settings-btn').click();
  await page.locator('[data-section="metadata"].stg-nav-item').click();
  await page.locator('.translation-test').click();
  await expect(page.locator('.translation-settings-result')).toContainText('연결 정상');
  await page.keyboard.press('Escape');
  await expect(page.locator('.description-translate')).toBeVisible();
  await page.evaluate(()=>{window.__fail=true;});
  await page.locator('.settings-btn').click();
  await page.locator('[data-section="metadata"].stg-nav-item').click();
  await page.locator('.translation-test').click();
  await expect(page.locator('.translation-settings-result')).toContainText('API 키');
  await page.keyboard.press('Escape');
  await expect(page.locator('.description-translate')).toBeHidden();
});
test('title tags have compact fitting controls',async({page})=>{
  await openApp(page);await page.locator('.settings-btn').click();await page.locator('[data-section="tags"].stg-nav-item').click();
  await expect(page.locator('.stg-section-title')).toContainText('제목 태그');
  const size=await page.locator('.stg-title-affix-row').first().evaluate(el=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height,overflow:el.scrollWidth>el.clientWidth}));
  expect(size.width).toBeLessThan(350);expect(size.height).toBeLessThan(35);expect(size.overflow).toBe(false);
  await page.screenshot({path:'.codex-test-tmp/title-tags-final.png'});
});
