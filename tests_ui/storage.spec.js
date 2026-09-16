// External Storage 관리와 System 이동.
//
// 이 화면들은 목업에 해당 호출이 아예 없어서 그동안 검증 자체가 불가능했다
// (tests/test_wiring.py::test_mock_covers_every_call이 잡아낸 8건). 목업을 상태를
// 바꾸는 형태로 채운 뒤에야 아래가 의미를 갖는다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("External Storage가 있으면 내비가 Storage별로 그룹을 나눈다", async ({ page }) => {
  // 기본 mock 데이터에 이미 Internal + External SD(ext-1) 두 Storage가 있다.
  await expect(page.locator(".nav-group-name")).toHaveCount(2);
  await expect(page.locator(".nav-group-name").nth(0)).toHaveText("INTERNAL");
  await expect(page.locator(".nav-group-name").nth(1)).toHaveText("EXTERNAL SD");
  await expect(page.locator(".nav-system")).toHaveCount(3);
});

test("Add External Storage 버튼은 이미 External이 있으면 숨는다(사용자 결정)", async ({ page }) => {
  // 기본 mock에 이미 External SD(ext-1)가 있다 - 이 Collection은 External을
  // 하나만 쓴다고 본다. 더 필요하면 먼저 지우고 다시 추가한다.
  await expect(page.locator(".nav-action", { hasText: "Add External Storage" })).toHaveCount(0);
});

test("External Storage를 지우면 버튼이 다시 나타나고, 다시 추가하면 그룹이 늘어난다", async ({ page }) => {
  const externalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "EXTERNAL SD" }) });
  await externalGroup.locator(".storage-remove-btn").click();
  await modalButton(page, "확인").click();
  // External이 하나도 없으면 System 목록은 평평하다 - Storage 그룹 자체가 없다
  // ("System 목록은 기본적으로 평평하다").
  await expect(page.locator(".nav-group")).toHaveCount(0);
  await expect(page.locator(".nav-system")).toHaveCount(3);
  await expect(page.locator(".nav-action", { hasText: "Add External Storage" })).toBeVisible();

  await page.locator(".nav-action", { hasText: "Add External Storage" }).click();
  await expect(page.locator(".modal-title")).toHaveText("External Storage 추가");

  // 경로 없이 누르면 경고만 뜬다.
  await modalButton(page, "추가").click();
  await expect(page.locator("#toast")).toContainText("경로를 입력하세요");

  await page.locator(".modal-body .field-row .field-input").fill("F:\ROMs");
  await modalButton(page, "추가").click();
  await expect(page.locator(".nav-group")).toHaveCount(2);
});

test("Storage 정보는 System 메뉴에서 볼 수 있다", async ({ page }) => {
  await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
  // 메뉴 머리에 Storage 이름이 보이고, 실제 경로는 그 머리의 툴팁에 있다.
  await expect(page.locator(".ctx-sub")).toContainText("External SD");
  await expect(page.locator(".ctx-head")).toHaveAttribute("title", "E:\\ROMs");
});
