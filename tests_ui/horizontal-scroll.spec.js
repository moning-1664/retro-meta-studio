// 목록을 좌우로 밀 수 있는가 (P1).
//
// 컬럼 폭의 합은 약 1,200px인데 가운데 열은 창이 좁으면 그보다 훨씬 좁다. 그런데도
// 가로로 밀 수가 없었다. 원인이 둘이었다.
//
//   1. `#list-window`가 `position:absolute; left:0; right:0`이라 폭이 스크롤
//      컨테이너에 묶였다. 넘칠 것이 없으니 스크롤할 것도 없었다.
//   2. `#list-head`는 `#list-scroll` **밖에** 있다(세로로는 고정되어야 하므로).
//      가로로 밀어도 헤더만 제자리에 남아 어느 컬럼인지 알 수 없었다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => {
  // 컬럼 합보다 확실히 좁은 창을 만든다.
  await page.setViewportSize({ width: 900, height: 700 });
  await openApp(page);
});

const metrics = (page) => page.evaluate(() => {
  const scroll = document.getElementById("list-scroll");
  return { scrollWidth: scroll.scrollWidth, clientWidth: scroll.clientWidth };
});

test("컬럼 합이 화면보다 넓으면 가로로 넘친다", async ({ page }) => {
  const m = await metrics(page);
  expect(m.scrollWidth).toBeGreaterThan(m.clientWidth);
});

test("실제로 가로로 밀린다", async ({ page }) => {
  await page.evaluate(() => {
    const el = document.getElementById("list-scroll");
    el.scrollLeft = 200;
    el.dispatchEvent(new Event("scroll"));
  });
  const left = await page.evaluate(() => document.getElementById("list-scroll").scrollLeft);
  expect(left).toBeGreaterThan(0);
});

test("헤더가 본문과 같이 밀린다", async ({ page }) => {
  await page.evaluate(() => {
    const el = document.getElementById("list-scroll");
    el.scrollLeft = 200;
    el.dispatchEvent(new Event("scroll"));
  });
  // 밀린 만큼 헤더도 반대로 옮겨져 있어야 컬럼이 맞는다.
  const transform = await page.evaluate(() =>
    getComputedStyle(document.getElementById("list-head")).transform);
  expect(transform).toContain("-200");
});

test("헤더와 본문의 폭이 같다", async ({ page }) => {
  const same = await page.evaluate(() => {
    const head = document.getElementById("list-head");
    const win = document.getElementById("list-window");
    return Math.abs(head.getBoundingClientRect().width - win.getBoundingClientRect().width) < 2;
  });
  expect(same).toBe(true);
});

test("카드 보기에서는 가로로 넘치지 않는다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-card").first()).toBeVisible();
  const m = await metrics(page);
  // 카드는 auto-fill로 세로로 흐른다 - 가로 스크롤이 생기면 그것이 버그다.
  expect(m.scrollWidth).toBeLessThanOrEqual(m.clientWidth + 1);
});
