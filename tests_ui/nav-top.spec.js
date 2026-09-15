// Navigator 상하단 고정 영역 - App Title·Settings(위) / Add External·Dashboard(아래).
//
// 사용자 요청으로 위치를 바꿨다: App Title은 GameList 상단 Chromium(.cheader)과
// 세로로 나란히 보이도록 최상단으로, Dashboard는 그 자리(최하단)로 옮겼다.
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
  expect(await outside(".nav-top")).toBe(true);

  // Add External Storage는 이미 External이 있으면 숨는다(사용자 결정) - 기본
  // mock이 그 상태라 먼저 지워야 이 버튼이 보인다.
  await page.locator(".storage-remove-btn").click();
  await page.locator(".modal-actions .btn", { hasText: "확인" }).click();
  await expect(page.locator(".nav-action")).toBeVisible();
  expect(await outside(".nav-action")).toBe(true);
});

test("Dashboard를 누르면 Dashboard 화면으로 바뀐다", async ({ page }) => {
  // 자세한 동작은 dashboard.spec.js에 있다.
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#dashboard-view .dsb-title")).toBeVisible();
});

test("App Title이 Navigator 상단에 있고 GameList 상단 Chromium과 나란하다", async ({ page }) => {
  await expect(page.locator(".nav-app-title-name")).toHaveText("RetroMeta Studio");
  const navTop = await page.locator(".nav-top").boundingBox();
  const cheader = await page.locator(".cheader").first().boundingBox();
  // 정확히 같은 픽셀일 필요는 없다 - 위쪽 시작 지점이 비슷한 높이에 있으면 된다.
  expect(Math.abs(navTop.y - cheader.y)).toBeLessThan(12);
});

test("Dashboard가 Navigator 최하단에 있다", async ({ page }) => {
  const dashboardBox = await page.locator(".nav-dashboard").boundingBox();
  const navBox = await page.locator("#nav").boundingBox();
  expect(dashboardBox.y + dashboardBox.height).toBeGreaterThan(navBox.y + navBox.height - 60);
});

test("Settings를 누르면 Settings 화면이 열린다", async ({ page }) => {
  // 자세한 동작은 settings.spec.js에 있다.
  await page.locator(".nav-top .icon-btn").click();
  await expect(page.locator(".stg-title")).toHaveText("Settings");
});
