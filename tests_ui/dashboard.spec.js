// Collection Dashboard - Navigator의 Dashboard가 중앙 영역을 바꾼다(사용자 결정: 전환 방식 유지).
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const openDashboard = async (page) => {
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#dashboard-view .dsb-title")).toBeVisible();
};

test("Dashboard를 누르면 목록 대신 Dashboard가 보인다", async ({ page }) => {
  await openDashboard(page);
  await expect(page.locator("#list-wrap")).toBeHidden();
  await expect(page.locator("#collection-header")).toBeHidden();
  await expect(page.locator(".nav-dashboard")).toHaveClass(/active/);
  await expect(page.locator(".dsb-title")).toHaveText("Master Library");
  await expect(page.locator(".dsb-tile").first()).toContainText("Games");
});

test("다시 누르면 목록으로 돌아간다", async ({ page }) => {
  await openDashboard(page);
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#list-wrap")).toBeVisible();
  await expect(page.locator("#dashboard-view")).toBeHidden();
});

test("사용량 막대에는 범례가 함께 있다(색만으로 구분하지 않는다)", async ({ page }) => {
  await openDashboard(page);
  const segments = await page.locator(".dsb-seg").count();
  expect(segments).toBeGreaterThan(1);
  await expect(page.locator(".dsb-legend-item")).toHaveCount(segments);
});

test("System 표의 행을 누르면 그 System의 목록으로 간다", async ({ page }) => {
  await openDashboard(page);
  await page.locator(".dsb-table tbody tr[data-system='snes']").click();
  await expect(page.locator("#list-wrap")).toBeVisible();
  await expect(page.locator(".cheader-name")).toHaveText("Master Library (SNES)");
});

test("System 표는 머리글로 정렬된다", async ({ page }) => {
  await openDashboard(page);
  await page.locator(".dsb-sort", { hasText: "System" }).click();
  const first = await page.locator(".dsb-table tbody tr").first().getAttribute("data-system");
  expect(first).toBe("gba");
});

test("Validate Collection은 결과를 알려준다", async ({ page }) => {
  await openDashboard(page);
  await page.locator(".dsb-validate").click();
  await expect(page.locator(".dsb-validation")).toContainText("문제 없음");
});

test("목표 용량을 바꾸면 그 Collection의 화면 상태로 저장된다", async ({ page }) => {
  const saved = [];
  await page.exposeFunction("__saved", (s) => saved.push(s));
  await page.evaluate(() => {
    const original = window.api.saveUiState;
    window.api.saveUiState = (id, s) => { window.__saved(s); return original(id, s); };
  });
  await openDashboard(page);
  const input = page.locator(".dsb-target[data-storage='internal'] .dsb-target-input");
  await input.fill("1 TB");
  await input.press("Enter");
  await expect.poll(() => saved.filter((s) => s.dashboardTargets).length).toBeGreaterThan(0);
  expect(saved.at(-1).dashboardTargets.internal).toBe(1024 ** 4);
  await expect(page.locator(".dsb-target[data-storage='internal'] .dsb-target-input")).toHaveValue("1 TB");
});

test("Archive 탭에서는 Dashboard를 열지 않고 이유를 알려준다", async ({ page }) => {
  await page.locator(".ctab.archive").click();
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#toast")).toContainText("Collection 탭");
  await expect(page.locator("#dashboard-view")).toBeHidden();
});
