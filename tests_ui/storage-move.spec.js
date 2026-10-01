const {test, expect} = require('@playwright/test');
const {openApp} = require('./_helpers');

test('System Storage drag requests an independent immediate operation', async ({page}) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__storage=[];
    window.api.operationPreview=async (...args) => {
      window.__storage.push(args);
      return {ok:true,data:{operationId:'storage', count:1, action:'storage', undoable:true, collisions:[]}};
    };
    window.api.pasteExecute=async () => ({ok:true,data:{jobId:null}});
  });
  await page.locator('.nav-group', {hasText:'INTERNAL'}).locator('.nav-system', {hasText:'SNES'})
    .dragTo(page.locator('.nav-group', {hasText:'EXTERNAL SD'}));
  await expect.poll(() => page.evaluate(() => window.__storage.length)).toBe(1);
  const args=await page.evaluate(() => window.__storage[0]);
  expect(args[1]).toBe('storage');
  expect(args[2].system).toBe('snes');
  await expect(page.locator('.plan-actions, .pending-move')).toHaveCount(0);
});

test('Storage preview failure reports its reason and never executes', async ({page}) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__executed=0;
    window.api.operationPreview=async () => ({ok:false,error:'대상 Storage에 같은 이름의 파일이 있습니다.'});
    window.api.pasteExecute=async () => {window.__executed++; return {ok:true,data:{}};};
  });
  await page.locator('.nav-group', {hasText:'INTERNAL'}).locator('.nav-system', {hasText:'SNES'})
    .dragTo(page.locator('.nav-group', {hasText:'EXTERNAL SD'}));
  await expect(page.locator('#toast')).toContainText('같은 이름의 파일');
  expect(await page.evaluate(() => window.__executed)).toBe(0);
});
