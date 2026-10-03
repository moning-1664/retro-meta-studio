const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test("Archive tab displays cached rows without waiting for ownership summary", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__ownershipCalls = 0;
    window.api.archiveConfig = () => Promise.resolve({ ok: true, data: {
      configured: true, frontend: "es-de", archiveDir: "C:/mock-archive", mediaInternal: true,
    } });
    window.api.archiveSystems = () => Promise.resolve({ ok: true, data: [{ system: "ps2", count: 1 }] });
    window.api.archiveRows = () => Promise.resolve({ ok: true, data: {
      rows: [{ romUid: "cached", romIdentityId: "cached", system: "ps2", file: "Cached.iso",
        title: "Cached", hasMetadata: true, hasMedia: false, present: true, storageId: "archive" }],
      total: 1, offset: 0,
    } });
    window.api.archiveOwnershipSummary = () => {
      window.__ownershipCalls += 1;
      return new Promise(() => {});
    };
  });
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".ctab.archive")).toHaveClass(/active/);
  await expect(page.locator(".lrow").first()).toBeVisible();
  expect(await page.evaluate(() => window.__ownershipCalls)).toBe(0);
});

test("directory refresh remains available through Archive refresh", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__refreshCalls = 0;
    window.api.archiveConfig = () => Promise.resolve({ ok: true, data: {
      configured: true, frontend: "es-de", archiveDir: "C:/mock-archive", mediaInternal: true,
    } });
    window.api.startArchiveRefresh = () => {
      window.__refreshCalls += 1;
      return Promise.resolve({ ok: true, data: { jobId: "refresh-test" } });
    };
    window.api.jobProgress = () => Promise.resolve({ ok: true, data: {
      current: 1, total: 1, label: "done", done: true, error: null,
      result: { scanSeconds: 0.1, sharedSnapshot: { status: "published" } },
    } });
  });
  await page.locator(".settings-btn").click();
  await page.locator(".stg-nav-item[data-section='archive']").click();
  await expect(page.locator(".archive-rescan")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.locator(".ctab.archive").click();
  await page.keyboard.press("F5");
  await expect.poll(() => page.evaluate(() => window.__refreshCalls)).toBe(1);

});
