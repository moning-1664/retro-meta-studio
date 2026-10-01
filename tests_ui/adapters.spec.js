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
  const labels = await frontendSelect.locator("option").allTextContents();
  for (const frontend of ["ES-DE", "Pegasus", "LaunchBox", "EmulationStation"]) {
    expect(labels).toContain(frontend);
  }
});

test("고른 Frontend가 새 Collection에 그대로 반영된다", async ({ page }) => {
  await page.locator(".ctab-add").click();
  await page.locator("#add-frontend").selectOption("pegasus");
  await page.locator(".modal-body input[placeholder='예: Android ES-DE']").fill("펠가수스");
  await page.locator(".modal-body .btn", { hasText: "찾아보기" }).first().click();
  await modalButton(page, "Add").click();
  await expect(page.locator(".ctab.active")).toContainText("펠가수스");
});

test("설정 버튼은 Internal/External 둘 다 있고, 제거 버튼은 External에만 있다(사용자 결정)", async ({ page }) => {
  // ES-DE XML 생성은 이제 그 설정 안에 있다(§22 개정 - 예전엔 그룹 머리에 따로
  // 아이콘이 있었는데, External이 여럿일 때 "어느 그룹에서 눌러도 전체를 다시
  // 쓴다"는 뜻이 아이콘만 봐서는 안 보였다).
  const internalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "INTERNAL" }) });
  const externalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "EXTERNAL SD" }) });
  await expect(internalGroup.locator(".nav-group-head .storage-settings-btn")).toHaveCount(1);
  await expect(internalGroup.locator(".nav-group-head .storage-remove-btn")).toHaveCount(0);
  await expect(externalGroup.locator(".nav-group-head .storage-settings-btn")).toHaveCount(1);
  await expect(externalGroup.locator(".nav-group-head .storage-remove-btn")).toHaveCount(1);
});

test("ES-DE XML 생성은 Storage 설정 안에 있고, 실행하면 결과를 알려준다", async ({ page }) => {
  const externalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "EXTERNAL SD" }) });
  await externalGroup.locator(".storage-settings-btn").click();
  await expect(page.locator(".modal-body.storage-settings")).toBeVisible();
  await page.locator(".modal-actions .btn", { hasText: "ES-DE XML 생성" }).click();
  // 결과는 파일 경로 같은 긴 설명이 아니라 Storage 이름과 System 목록만 짧게
  // 보여준다(실사용 피드백 - "밑에 설명은 너무 길다. 설명은 필요없을 듯").
  await expect(page.locator(".xml-result")).toContainText("External SD");
  await expect(page.locator(".xml-row")).toContainText("ps2");
});

test("Internal 설정에는 PC 경로 입력칸이 없다(참고용 텍스트만)", async ({ page }) => {
  // Internal의 PC 경로는 Collection 경로 자체라 여기서 바꿔도 저장되지 않는다 -
  // 바꿀 수 있는 것처럼 입력칸을 주지 않는다.
  const internalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "INTERNAL" }) });
  await internalGroup.locator(".storage-settings-btn").click();
  await expect(page.locator(".storage-settings .storage-root")).toHaveCount(0);
  await expect(page.locator(".storage-settings .storage-root-readonly")).toBeVisible();
});
