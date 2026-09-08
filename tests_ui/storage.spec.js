// External Storage 관리와 System 이동.
//
// 이 화면들은 목업에 해당 호출이 아예 없어서 그동안 검증 자체가 불가능했다
// (tests/test_wiring.py::test_mock_covers_every_call이 잡아낸 8건). 목업을 상태를
// 바꾸는 형태로 채운 뒤에야 아래가 의미를 갖는다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("내비가 Storage 그룹과 그 아래 System을 함께 보여준다", async ({ page }) => {
  await expect(page.locator(".nav-group-name")).toHaveText(["INTERNAL", "EXTERNAL SD"]);
  await expect(page.locator(".nav-system")).toHaveCount(2);
});

test("External Storage를 추가하면 내비에 그룹이 하나 늘어난다", async ({ page }) => {
  await page.locator(".nav-action", { hasText: "Add External Storage" }).click();
  await expect(page.locator(".modal-title")).toHaveText("External Storage 추가");

  // 경로 없이 누르면 경고만 뜬다.
  await modalButton(page, "추가").click();
  await expect(page.locator("#toast")).toContainText("경로를 입력하세요");

  await page.locator(".modal-body .field-row .field-input").fill("F:\ROMs");
  await modalButton(page, "추가").click();
  await expect(page.locator(".nav-group")).toHaveCount(3);
  await expect(page.locator(".sb-storage")).toHaveCount(3);
});

test("Storage 그룹을 클릭하면 그 Storage로 목록이 좁혀진다", async ({ page }) => {
  await page.locator(".nav-group-head", { hasText: "EXTERNAL SD" }).click();
  await expect(page.locator(".nav-group-head.active")).toContainText("EXTERNAL SD");
});
