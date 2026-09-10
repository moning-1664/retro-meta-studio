// Navigator 상하단 고정 영역 - Dashboard(위) / Add External·App Title·Settings(아래).
//
// System 목록만 스크롤한다(레이아웃 재검토 §5) - 그래서 이 넷은 #nav-scroll
// 바깥(형제)에 있어야 한다. 안에 있으면 System이 늘어날 때 같이 밀려난다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("Dashboard/Add External/App Title/Settings는 스크롤 영역 밖에 있다", async ({ page }) => {
  const outside = async (selector) => page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const scroll = document.querySelector(".nav-scroll");
    return !!el && !scroll.contains(el);
  }, selector);

  expect(await outside(".nav-dashboard")).toBe(true);
  expect(await outside(".nav-action")).toBe(true);
  expect(await outside(".nav-bottom")).toBe(true);
});

test("Dashboard는 눌러도 아직 아무 기능이 없다는 것을 알린다", async ({ page }) => {
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#toast")).toContainText("아직 없습니다");
});

test("App Title이 Navigator 하단에 있다", async ({ page }) => {
  await expect(page.locator(".nav-app-title-name")).toHaveText("RetroMeta Studio");
});

test("Settings를 누르면 준비 중이라는 안내가 뜬다", async ({ page }) => {
  await page.locator(".nav-bottom .icon-btn").click();
  await expect(page.locator(".modal-title")).toHaveText("Settings");
  await expect(page.locator(".modal-text")).toContainText("준비 중");
});
