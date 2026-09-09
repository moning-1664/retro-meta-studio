// Card(격자) 보기 - QA 재검토 P1: 토글 버튼만 있고 실제로 아무것도 안 바뀌던 것을
// 고친다. List/Card 전환이 실제로 다른 DOM(가상 스크롤 행 vs grid 카드)을 그린다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("기본은 List 보기다", async ({ page }) => {
  await expect(page.locator(".lrow")).toHaveCount(3);
  await expect(page.locator(".preview-card")).toHaveCount(0);
});

test("Card를 누르면 카드 격자로 바뀐다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-card")).toHaveCount(3);
  await expect(page.locator(".lrow")).toHaveCount(0);
  await expect(page.locator("#list-window")).toHaveClass(/card-mode/);
});

test("카드에 제목이 보인다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-title").first()).not.toBeEmpty();
});

test("카드를 누르면 선택되고 상세 패널이 열린다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await page.locator(".preview-card").first().click();
  await expect(page.locator(".preview-card").first()).toHaveClass(/selected/);
  await expect(page.locator("#detail-panel")).toHaveClass(/open/);
});

test("다시 List를 누르면 원래대로 돌아온다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-card")).toHaveCount(3);
  await page.locator("#filter-bar .seg-btn[title='목록 보기']").click();
  await expect(page.locator(".lrow")).toHaveCount(3);
  await expect(page.locator(".preview-card")).toHaveCount(0);
});
