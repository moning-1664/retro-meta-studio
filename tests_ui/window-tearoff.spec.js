// Collection 탭 떼어 내기/붙이기 - 메인 창 탭 메뉴의 "새 창으로 분리", 떼어 낸 창(Collection 하나)의
// "메인 창으로 합치기", 다른 창에서 온 Settings/Collection 변경 알림.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.describe("메인 창", () => {
  test.beforeEach(async ({ page }) => { await openApp(page); });

  test("탭 메뉴의 새 창으로 분리는 요청 후 탭을 뺀다(Collection은 닫지 않는다)", async ({ page }) => {
    await page.evaluate(() => {
      window.__calls = [];
      const detach = window.api.detachCollection;
      const close = window.api.closeCollection;
      window.api.detachCollection = (...a) => { window.__calls.push(["detach", ...a]); return detach(...a); };
      window.api.closeCollection = (...a) => { window.__calls.push(["close", ...a]); return close(...a); };
    });
    await expect(page.locator(".ctab:not(.archive)")).toHaveCount(1);
    await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
    await page.locator(".tab-detach").click();
    await expect(page.locator(".ctab:not(.archive)")).toHaveCount(0);
    expect(await page.evaluate(() => window.__calls)).toEqual([["detach", "c1"]]);
    await expect(page.locator(".ctab.archive")).toBeVisible();
  });

  test("다른 창이 합치면 탭이 다시 열린다", async ({ page }) => {
    await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
    await page.locator(".tab-detach").click();
    await expect(page.locator(".ctab:not(.archive)")).toHaveCount(0);
    await page.evaluate(() => window.__rmsAdoptCollection("c1"));
    await expect(page.locator(".ctab.active", { hasText: "Master Library" })).toBeVisible();
    await expect(page.locator(".toast-msg")).toContainText("다시 붙였습니다");
  });

  test("다른 창에서 바꾼 Settings가 반영된다", async ({ page }) => {
    await page.evaluate(() => window.__rmsSettingsChanged({ appearance: { scale: 120 } }));
    await expect.poll(() => page.evaluate(() =>
      document.documentElement.style.getPropertyValue("--font-scale"))).toBe("1.2");
  });
});

test.describe("떼어 낸 창", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/index.html?window=w1&collection=c2");
    await expect.poll(() => page.evaluate(() => window.api && window.api.isMock())).toBe(true);
    await expect(page.locator(".ctab.detached")).toBeVisible();
  });

  test("Collection 탭 하나만 있고 Archive 탭과 추가 버튼이 없다", async ({ page }) => {
    await expect(page.locator(".ctab")).toHaveCount(1);
    await expect(page.locator(".ctab.detached")).toContainText("Android ES-DE");
    await expect(page.locator(".ctab.archive")).toHaveCount(0);
    await expect(page.locator(".ctab-add")).toHaveCount(0);
    await expect(page.locator("body")).toHaveClass(/detached-window/);
  });

  test("탭 메뉴에는 메인 창으로 합치기만 있다", async ({ page }) => {
    await page.evaluate(() => {
      window.__merged = 0;
      window.api.mergeWindow = async () => { window.__merged += 1; return { ok: true, data: true }; };
    });
    await page.locator(".ctab.detached").click({ button: "right" });
    await expect(page.locator(".tab-detach")).toHaveCount(0);
    await page.locator(".tab-merge").click();
    await expect.poll(() => page.evaluate(() => window.__merged)).toBe(1);
  });

  test("탭 닫기는 창을 닫는다", async ({ page }) => {
    await page.evaluate(() => {
      window.__controls = [];
      window.api.windowControl = async (a) => { window.__controls.push(a); return { ok: true, data: true }; };
    });
    await page.locator(".ctab.detached .ctab-close").click();
    await expect.poll(() => page.evaluate(() => window.__controls)).toEqual(["close"]);
  });

  test("다른 창에서 Collection 이름이 바뀌면 탭 이름도 바뀐다", async ({ page }) => {
    await page.evaluate(async () => {
      await window.api.renameCollection("c2", "SD 카드");
      await window.__rmsCollectionsChanged();
    });
    await expect(page.locator(".ctab.detached")).toContainText("SD 카드");
  });
});
