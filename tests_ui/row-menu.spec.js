// 게임 행 우클릭 메뉴 - Delete.
//
// 레이아웃 재검토에서 Delete 상시 버튼을 없앴다(오클릭 위험, PENDING_DECISIONS.md).
// 남은 진입점은 DEL 키와 이 우클릭 메뉴뿐이다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("Delete 상시 버튼은 없다", async ({ page }) => {
  await expect(page.locator("#filter-bar", { hasText: "Delete" })).toHaveCount(0);
});

test("행을 우클릭하면 그 게임 이름과 Delete가 뜬다", async ({ page }) => {
  await page.locator(".lrow", { hasText: "Final Fantasy X" }).click({ button: "right" });
  await expect(page.locator(".modal-title")).toHaveText("Final Fantasy X");
  await expect(page.locator(".modal-actions .btn", { hasText: "Delete" })).toBeVisible();
});

test("선택하지 않은 행을 우클릭하면 그 행 하나만 선택된다", async ({ page }) => {
  await page.locator(".lrow", { hasText: "Final Fantasy X" }).click({ button: "right" });
  await expect(page.locator("#status-bar")).toContainText("Selected 1");
});

test("Delete를 고르면 삭제를 요청하고 모달을 닫는다", async ({ page }) => {
  const deleted = [];
  await page.exposeFunction("__deleted", (uids) => deleted.push(uids));
  await page.evaluate(() => {
    const original = window.api.planDelete;
    window.api.planDelete = (id, romUids) => { window.__deleted(romUids); return original(id, romUids); };
  });

  await page.locator(".lrow", { hasText: "Final Fantasy X" }).click({ button: "right" });
  await page.locator(".modal-actions .btn", { hasText: "Delete" }).click();

  await expect(page.locator(".modal-title")).toHaveCount(0);
  await expect.poll(() => deleted.length).toBeGreaterThan(0);
  expect(deleted[0]).toHaveLength(1);
});

test("이미 여러 개를 선택한 상태로 그중 하나를 우클릭하면 선택 전체가 대상이다", async ({ page }) => {
  await page.locator(".lrow").nth(0).click();
  await page.locator(".lrow").nth(1).click({ modifiers: ["Control"] });
  await expect(page.locator("#status-bar")).toContainText("Selected 2");

  await page.locator(".lrow").nth(0).click({ button: "right" });
  await expect(page.locator(".modal-title")).toContainText("2개 선택됨");
  // 선택이 그대로 유지된다 - 우클릭이 선택을 1개로 되돌리지 않는다.
  await expect(page.locator("#status-bar")).toContainText("Selected 2");
});
