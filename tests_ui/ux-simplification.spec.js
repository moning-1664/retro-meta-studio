const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test("Detail Media tab survives a Collection round trip", async ({ page }) => {
  await openApp(page);
  await page.locator(".lrow").first().click();
  await page.locator(".detail-tab").filter({ hasText: /^미디어$/ }).click();
  await page.locator(".ctab-add").click();
  await page.locator(".add-collection-history summary").click();
  await page.locator(".picker-row", { hasText: "Android ES-DE" }).click();
  await page.locator(".ctab", { hasText: "Master Library" }).click();
  await expect(page.locator(".detail-tab.active")).toHaveText("미디어");
});

test("Scraper apply cannot be submitted twice while starting", async ({ page }) => {
  await openApp(page);
  await page.locator(".lrow").first().click({ button: "right" });
  await page.locator(".ctx-item", { hasText: "온라인에서 게임 정보 검색" }).click();
  await page.getByRole("button", { name: "스크랩 시작" }).click();
  await page.locator(".scrape-candidate").first().click();
  await expect(page.getByRole("button", { name: "선택 적용" })).toBeEnabled();
  await page.evaluate(() => {
    window.__applyCount = 0;
    window.api.startApplyScrapeSession = () => {
      window.__applyCount++;
      return new Promise(() => {});
    };
  });
  await page.getByRole("button", { name: "선택 적용" }).click();
  await expect(page.getByRole("button", { name: "선택 적용" })).toBeDisabled();
  await page.evaluate(() => document.querySelector(".scrape-actions .primary").click());
  expect(await page.evaluate(() => window.__applyCount)).toBe(1);
});

test("Archive nested detection updates the metadata folder input", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => {
    const original = window.api.jobProgress;
    window.__detectedPath = "";
    window.api.startInspectCollectionFolder = async (path) => {
      window.__detectedPath = path;
      return { ok: true, data: { jobId: "nested-folder" } };
    };
    window.api.jobProgress = async (id) => id !== "nested-folder" ? original(id) : {
      ok: true, data: { done: true, current: 1, total: 1, result: {
        path: window.__detectedPath + "/ES-DE", selectedPath: window.__detectedPath,
        archive: false, legacyArchive: false, suggestedFrontend: "es-de",
        findings: [{ frontend: "es-de", evidence: "gamelists", systems: [] }],
      } },
    };
  });
  await page.locator(".settings-btn").click();
  await page.locator(".stg-nav-item[data-section='archive']").click();
  await expect(page.locator(".archive-dir")).toBeVisible();
  await page.locator(".archive-dir").fill("D:/Parent");
  await page.locator(".archive-dir").press("Tab");
  await expect(page.locator(".archive-dir")).toHaveValue("D:/Parent/ES-DE");
});
