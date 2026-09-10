// 앱이 실제로 "뜨는가"를 본다. 여기가 깨지면 아래 spec들의 실패는 전부 의미가 없다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("TopBar에 Archive 탭과 Collection 탭이 그려진다", async ({ page }) => {
  // Archive가 맨 앞이다(레이아웃 재검토) - App Title은 없앴다.
  await expect(page.locator(".ctab").first()).toHaveClass(/archive/);
  await expect(page.locator(".ctab.archive")).toContainText("Archive");
  await expect(page.locator(".ctab").nth(1)).toContainText("Master Library");
});

test("좌측 내비가 SYSTEMS와 All 행을 보여준다", async ({ page }) => {
  await expect(page.locator(".nav-eyebrow")).toHaveText("SYSTEMS");
  await expect(page.locator("#nav .nav-all")).toContainText("All");
});

test("Gamelist가 목업 3행을 렌더하고 총 개수를 알린다", async ({ page }) => {
  await expect(page.locator(".lrow")).toHaveCount(3);
  await expect(page.locator("#filter-total")).toContainText("3");
  await expect(page.locator(".lrow").first()).toContainText("Final Fantasy X");
});

test("상태바가 선택 개수와 Storage 용량을 보여준다", async ({ page }) => {
  await expect(page.locator(".sb-left")).toContainText("Selected 0");
  await expect(page.locator(".sb-storage")).toHaveCount(2);
});

test("Archive 탭으로 전환하면 Archive 화면이 활성화된다", async ({ page }) => {
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".ctab.archive")).toHaveClass(/active/);
});
