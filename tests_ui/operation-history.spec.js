// The Explorer model replaces staged Plan badges with immediate jobs and history.
const {test, expect} = require('@playwright/test');
const {openApp} = require('./_helpers');

test('completed operations use history instead of a staged Apply toolbar', async ({page}) => {
  await openApp(page);
  await expect(page.locator('#filter-bar .plan-actions, .plan-apply-badge, .lno-mark')).toHaveCount(0);
  await page.evaluate(() => {
    window.api.operationHistory = async () => ({ok:true, data:{items:[
      {id:'done', status:'committed', action:'paste', createdAt:1, bytes:1024, canDiscard:true},
      {id:'pending', status:'restoring', action:'move', createdAt:2, bytes:2048, canDiscard:false}
    ]}});
  });
  await page.locator('.lrow').first().click({button:'right'});
  await expect(page.locator('.ctx-item', {hasText:'작업 기록…'})).toHaveCount(0);
});

test('redo shortcut dispatches only the active Collection', async ({page}) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__redoCalls=[];
    window.api.pasteRedo=async id => {window.__redoCalls.push(id); return {ok:true,data:{jobId:null}};};
  });
  await page.locator('.lrow').first().click();
  await page.keyboard.press('Control+y');
  await expect.poll(() => page.evaluate(() => window.__redoCalls.length)).toBe(1);
  expect(await page.evaluate(() => window.__redoCalls[0])).not.toBe('__archive__');
});

test('cancelled conflict does not execute or stage a paste', async ({page}) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__deletes=[];
    window.__RMS_MOCK_IMMEDIATE_PASTE=true;
    window.api.pasteExecute=async (...args) => {window.__deletes.push(args);return {ok:true,data:{}};};
  });
  await page.locator('.lrow').first().click();
  await page.keyboard.press('Control+c');
  await page.keyboard.press('Control+v');
  await page.locator('.modal-actions .btn', {hasText:'취소'}).click();
  expect(await page.evaluate(() => window.__deletes)).toEqual([]);
  await expect(page.locator('.plan-apply-badge, .lno-mark')).toHaveCount(0);
});
