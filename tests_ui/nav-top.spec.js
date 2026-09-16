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

// 실사용 피드백 §8.
test.describe("App Title / Settings 자리와 크기", () => {
  test("App Title 글자가 예전(11.5px)보다 크다", async ({ page }) => {
    const size = await page.locator(".nav-app-title-name")
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(size).toBeGreaterThanOrEqual(12.5);
  });

  test("App Title이 줄 안에서 세로 가운데다", async ({ page }) => {
    const navTop = await page.locator(".nav-top").evaluate((el) => getComputedStyle(el).alignItems);
    expect(navTop).toBe("center");
  });

  test("Settings 아이콘은 줄의 아래쪽에 붙는다", async ({ page }) => {
    const alignSelf = await page.locator(".nav-top .icon-btn")
      .evaluate((el) => getComputedStyle(el).alignSelf);
    expect(alignSelf).toBe("flex-end");
  });

  test("Settings 아이콘 패딩이 다른 조용한 도구 버튼과 같다", async ({ page }) => {
    // HERO의 메타데이터 보내기와 같은 3px(레이아웃 재검토 계약).
    const settingsPad = await page.locator(".nav-top .icon-btn")
      .evaluate((el) => getComputedStyle(el).padding);
    const heroPad = await page.locator("#collection-header .cheader-right .icon-btn").first()
      .evaluate((el) => getComputedStyle(el).padding);
    expect(settingsPad).toBe(heroPad);
  });
});

// Archive/App Title 대표 아이콘 - DB 아이콘 대신 스페이스 인베이더 픽셀 실루엣
// (실사용 피드백). rect로 이루어진 칠한 도형이라는 것으로 구분한다 - database
// 아이콘은 ellipse/path 획이었다.
test.describe("Archive/App Title 아이콘", () => {
  test("App Title 아이콘은 인베이더 픽셀(칠한 사각형들)이다", async ({ page }) => {
    // .icon 클래스는 <svg> 자신에 붙는다(감싸는 태그가 아니다) - 그 안의 <rect>를 센다.
    const rects = await page.locator(".nav-app-title .icon rect").count();
    expect(rects).toBeGreaterThan(5);
  });

  test("Archive 탭 아이콘도 같은 인베이더 픽셀이다", async ({ page }) => {
    const rects = await page.locator(".ctab.archive .icon rect").count();
    expect(rects).toBeGreaterThan(5);
  });
});
