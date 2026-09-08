// Frontend Adapter가 늘어난 뒤의 UI (Phase 7).
//
// 백엔드에 Adapter를 추가해도 화면이 그것을 내놓지 않으면 사용자는 쓸 수 없다.
// 여기서는 "고를 수 있는가"와 "Frontend 고유 기능이 그 Frontend에서만 보이는가"를 본다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("새 Collection에서 네 가지 Frontend를 모두 고를 수 있다", async ({ page }) => {
  await page.locator(".ctab-add").click();
  await modalButton(page, "새 Collection 추가").click();

  const frontendSelect = page.locator(".modal-body select").first();
  await expect(frontendSelect.locator("option")).toHaveText([
    "ES-DE", "Pegasus", "LaunchBox", "EmulationStation",
  ]);
});

test("고른 Frontend가 새 Collection에 그대로 반영된다", async ({ page }) => {
  await page.locator(".ctab-add").click();
  await modalButton(page, "새 Collection 추가").click();
  await page.locator(".modal-body .field-input").first().fill("펠가수스");
  await page.locator(".modal-body select").first().selectOption("pegasus");
  await page.locator(".modal-body .btn", { hasText: "찾아보기" }).click();
  await modalButton(page, "추가").click();
  await expect(page.locator(".ctab.active")).toContainText("펠가수스");
});

test("Frontend 고유 기능은 헤더를 펼쳐야 나온다(§22)", async ({ page }) => {
  // 접힌 상태에서는 보이지 않는다 - 자주 쓰는 기능이 아니다.
  await expect(page.locator(".cheader-extras")).toHaveCount(0);
  await page.locator("#collection-header .icon-btn").last().click();
  const extras = page.locator(".cheader-extras");
  await expect(extras).toBeVisible();
  await expect(extras.locator(".btn")).toHaveText("[ES-DE XML 생성]");
});

test("ES-DE XML 생성을 실행하면 결과를 알려준다", async ({ page }) => {
  await page.locator("#collection-header .icon-btn").last().click();
  await page.locator(".cheader-extras .btn", { hasText: "ES-DE XML" }).click();
  await expect(page.locator("#toast")).toContainText("완료");
  await expect(page.locator("#toast")).toContainText("ps2");
});
