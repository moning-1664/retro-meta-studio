// External Storage 관리와 System 이동.
//
// 이 화면들은 목업에 해당 호출이 아예 없어서 그동안 검증 자체가 불가능했다
// (tests/test_wiring.py::test_mock_covers_every_call이 잡아낸 8건). 목업을 상태를
// 바꾸는 형태로 채운 뒤에야 아래가 의미를 갖는다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("내비는 Storage 그룹 없이 System만 보여준다", async ({ page }) => {
  // Storage는 용량·파일 작업을 위한 내부 개념이다. 사용자가 보는 것은 System이다.
  await expect(page.locator(".nav-group-name")).toHaveCount(0);
  await expect(page.locator(".nav-system")).toHaveCount(3);
});

test("External Storage를 추가해도 내비에 그룹이 생기지 않는다", async ({ page }) => {
  await page.locator(".nav-action", { hasText: "Add External Storage" }).click();
  await expect(page.locator(".modal-title")).toHaveText("External Storage 추가");

  // 경로 없이 누르면 경고만 뜬다.
  await modalButton(page, "추가").click();
  await expect(page.locator("#toast")).toContainText("경로를 입력하세요");

  await page.locator(".modal-body .field-row .field-input").fill("F:\ROMs");
  await modalButton(page, "추가").click();
  // 용량 표시(하단 상태바)는 Storage마다 하나씩 늘어난다 - 그쪽이 Storage의 자리다.
  await expect(page.locator(".sb-storage")).toHaveCount(3);
  await expect(page.locator(".nav-group")).toHaveCount(0);
});

test("Storage 정보는 System 메뉴에서 볼 수 있다", async ({ page }) => {
  await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
  await expect(page.locator(".modal-body")).toContainText("E:\\ROMs");
});
