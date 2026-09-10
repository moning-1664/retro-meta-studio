// 미리보기(상세 패널) 켜고 끄기 (P1).
//
// 끄면 목록이 그 자리까지 넓어져야 한다 - 탐색기의 미리보기 창과 같다. 상세를 안
// 보는 동안 화면 3분의 1을 빈 채로 둘 이유가 없다.
//
// 레이아웃(grid의 3번째 트랙 `auto` + `display:none`)은 처음부터 맞았다. 버그는
// `applyPreviewMode()`가 툴바 버튼의 클릭 처리기에서**만** 불렸다는 것이다. 그래서
// 꺼 둔 상태로 앱을 다시 열면 상태는 OFF인데 화면에는 패널이 그대로 보였고,
// 게임을 눌러도 아무 일이 없는 것처럼 보였다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const previewButton = (page) => page.locator("#filter-bar .icon-btn[title*='미리보기']");
const listWidth = (page) => page.evaluate(() =>
  document.getElementById("list-wrap").getBoundingClientRect().width);

test("끄면 목록이 그 자리까지 넓어진다", async ({ page }) => {
  const before = await listWidth(page);
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).toHaveClass(/hidden/);
  const after = await listWidth(page);
  // 패널 폭(306px)만큼 넓어져야 한다. 숨기기만 하고 자리가 남으면 안 된다.
  expect(after).toBeGreaterThan(before + 200);
});

test("다시 켜면 원래 폭으로 돌아온다", async ({ page }) => {
  const before = await listWidth(page);
  await previewButton(page).click();
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).not.toHaveClass(/hidden/);
  expect(Math.abs((await listWidth(page)) - before)).toBeLessThan(2);
});

test("꺼 둔 상태는 다시 그려도 유지된다", async ({ page }) => {
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).toHaveClass(/hidden/);

  // 전체를 다시 그리는 동작(탭 전환)을 거쳐도 꺼진 상태여야 한다. 예전에는
  // renderAll()이 applyPreviewMode()를 부르지 않아 패널이 되살아났다.
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".ctab.archive")).toHaveClass(/active/);
  await expect(page.locator("#detail-panel")).toHaveClass(/hidden/);
});
