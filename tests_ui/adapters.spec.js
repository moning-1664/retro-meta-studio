// Frontend Adapter가 늘어난 뒤의 UI (Phase 7).
//
// 백엔드에 Adapter를 추가해도 화면이 그것을 내놓지 않으면 사용자는 쓸 수 없다.
// 여기서는 "고를 수 있는가"와 "Frontend 고유 기능이 그 Frontend에서만 보이는가"를 본다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("새 Collection에서 네 가지 Frontend를 모두 고를 수 있다", async ({ page }) => {
  await page.locator(".ctab-add").click();

  const frontendSelect = page.locator("#add-frontend");
  await expect(frontendSelect.locator("option")).toHaveText([
    "ES-DE", "Pegasus", "LaunchBox", "EmulationStation",
  ]);
});

test("고른 Frontend가 새 Collection에 그대로 반영된다", async ({ page }) => {
  await page.locator(".ctab-add").click();
  await page.locator("#add-frontend").selectOption("pegasus");
  await page.locator(".modal-body input[placeholder='예: Android ES-DE']").fill("펠가수스");
  await page.locator(".modal-body .btn", { hasText: "찾아보기" }).first().click();
  await modalButton(page, "Add").click();
  await expect(page.locator(".ctab.active")).toContainText("펠가수스");
});

test("Frontend 고유 기능은 External Storage 그룹 옆에 있다(§22)", async ({ page }) => {
  // ES-DE의 custom systems XML은 External Storage에 있는 System만 대상으로
  // 하므로, Internal 그룹에는 없고 External 그룹에만 있다.
  const internalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "INTERNAL" }) });
  const externalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "EXTERNAL SD" }) });
  await expect(internalGroup.locator(".nav-group-head .icon-btn")).toHaveCount(0);
  await expect(externalGroup.locator(".nav-group-head .icon-btn[title*='XML']")).toHaveCount(1);
  await expect(externalGroup.locator(".nav-group-head .storage-settings-btn")).toHaveCount(1);
});

test("ES-DE XML 생성을 실행하면 결과를 알려준다", async ({ page }) => {
  const externalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "EXTERNAL SD" }) });
  await externalGroup.locator(".nav-group-head .icon-btn[title*='XML']").click();
  await expect(page.locator(".xml-result")).toContainText("es_systems.xml");
  await expect(page.locator(".xml-result")).toContainText("ps2");
});
