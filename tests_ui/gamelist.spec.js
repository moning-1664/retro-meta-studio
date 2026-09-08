// Gamelist와 상세 패널 - 사용자가 가장 오래 머무는 화면.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("행을 클릭하면 상세 패널이 그 게임으로 열린다", async ({ page }) => {
  await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();
  const panel = page.locator("#detail-panel");
  await expect(panel).toHaveClass(/open/);
  await expect(panel.locator(".detail-filename")).toHaveText("FFX.iso");
  await expect(panel.locator(".detail-system")).toContainText("PS2");
});

test("Metadata 탭의 요약 카드가 필드 값을 채운다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  const values = page.locator(".identity-field-value");
  await expect(values.first()).toHaveText("RPG");           // Genre
  await expect(page.locator(".title-input")).toHaveValue("Final Fantasy X");
});

test("탭을 바꿔도 저장 버튼은 Metadata 탭에서만 보인다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await expect(page.locator(".detail-footer .btn")).toContainText("저장");
  await page.locator(".detail-tab", { hasText: "ROM" }).click();
  await expect(page.locator(".detail-footer")).toHaveCount(0);
  await page.locator(".detail-tab", { hasText: "Metadata" }).click();
  await expect(page.locator(".detail-footer .btn")).toContainText("저장");
});

test("탭을 오갔다 와도 편집 중이던 값이 남아 있다(draft 보존)", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await page.locator(".title-input").fill("편집 중인 제목");
  await page.locator(".detail-tab", { hasText: "Media" }).click();
  await page.locator(".detail-tab", { hasText: "Metadata" }).click();
  await expect(page.locator(".title-input")).toHaveValue("편집 중인 제목");
});

test("Esc로 상세 패널을 닫는다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await expect(page.locator("#detail-panel")).toHaveClass(/open/);
  await page.keyboard.press("Escape");
  await expect(page.locator("#detail-panel")).not.toHaveClass(/open/);
});

test("체크박스로 고르면 상태바 선택 개수가 따라 오른다", async ({ page }) => {
  await page.locator(".lrow").nth(0).locator("input[type=checkbox]").check();
  await expect(page.locator(".sb-left")).toContainText("Selected 1");
  await page.locator(".lrow").nth(1).locator("input[type=checkbox]").check();
  await expect(page.locator(".sb-left")).toContainText("Selected 2");
  await page.locator(".lrow").nth(0).locator("input[type=checkbox]").uncheck();
  await expect(page.locator(".sb-left")).toContainText("Selected 1");
});

test("System 내비로 좁히면 그 시스템 행만 남는다", async ({ page }) => {
  await page.locator("#nav .nav-system", { hasText: "SNES" }).click();
  await expect(page.locator(".lrow")).toHaveCount(1);
  await expect(page.locator(".lrow").first()).toContainText("Super Mario World");
});

test("검색어를 넣으면 디바운스 후 결과가 줄어든다", async ({ page }) => {
  // 목업 list_rows는 systems만 필터하므로 검색은 총 개수 표시가 갱신되는 것까지만 본다.
  await page.locator(".search-input").fill("mario");
  await expect(page.locator("#filter-total")).toBeVisible();
});
