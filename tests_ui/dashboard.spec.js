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

// Storage target Slider - 32G~8T의 10단계에만 자석처럼 붙는다(사용자 결정). 숫자 입력/
// ▲▼ 버튼과 값을 공유하지만, 기존 Storage Usage 계산(사용량 막대·표)에는 영향을 주지 않는다.
test.describe("Storage target Slider", () => {
  const row = (page) => page.locator(".dsb-target[data-storage='internal']");
  const slider = (page) => row(page).locator(".dsb-target-slider");
  const input = (page) => row(page).locator(".dsb-target-input");
  const sliderValue = (page) => row(page).locator(".dsb-slider-value");

  const setTarget = async (page, text) => {
    await input(page).fill(text);
    await input(page).press("Enter");
  };

  test("텍스트로 512 GB를 정하면 Slider가 그 단계로 옮겨간다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "512 GB");
    // SNAP = [32,64,128,256,512]GB, 1,2,3,4,8TB - 512GB는 인덱스 4다.
    await expect(slider(page)).toHaveAttribute("value", "4");
    await expect(sliderValue(page)).toHaveText("512 GB");
  });

  test("Slider를 옮기면 숫자 입력/미리보기가 같은 값을 보여준다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "512 GB");
    await slider(page).focus();
    await page.keyboard.press("ArrowRight");   // 512GB -> 1TB
    await expect(sliderValue(page)).toHaveText("1 TB");
    await expect(input(page)).toHaveValue("1 TB");
    await expect(slider(page)).toHaveAttribute("value", "5");
  });

  test("Slider 값은 Collection ui_state에 저장된다", async ({ page }) => {
    const saved = [];
    await page.exposeFunction("__sliderSaved", (s) => saved.push(s));
    await page.evaluate(() => {
      const original = window.api.saveUiState;
      window.api.saveUiState = (id, s) => { window.__sliderSaved(s); return original(id, s); };
    });
    await openDashboard(page);
    await setTarget(page, "512 GB");
    await slider(page).focus();
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => saved.filter((s) => s.dashboardTargets).length).toBeGreaterThan(0);
    expect(saved.at(-1).dashboardTargets.internal).toBe(1024 ** 4);
  });

  test("최댓값은 8TB고 그 이상으로 넘어가지 않는다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "4 TB");
    await slider(page).focus();
    await page.keyboard.press("ArrowRight");   // 4TB -> 8TB (마지막 단계)
    await expect(sliderValue(page)).toHaveText("8 TB");
    await page.keyboard.press("ArrowRight");   // 더 눌러도 8TB에 머문다
    await expect(sliderValue(page)).toHaveText("8 TB");
    await expect(input(page)).toHaveValue("8 TB");
  });

  test("▲/▼ 버튼도 같은 10단계 위를 다음/이전으로 움직인다(임의 증분이 아니다)", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "128 GB");
    await row(page).locator(".dsb-spin", { hasText: "▲" }).click();
    await expect(input(page)).toHaveValue("256 GB");
    await expect(slider(page)).toHaveAttribute("value", "3");
    await row(page).locator(".dsb-spin", { hasText: "▼" }).click();
    await expect(input(page)).toHaveValue("128 GB");
    await expect(slider(page)).toHaveAttribute("value", "2");
  });

  test("목록에 없는 값(600 GB)에서 ▲를 누르면 바로 위 단계로 붙는다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "600 GB");
    await expect(input(page)).toHaveValue("600 GB");   // 512GB 근처지만 허용 오차 밖이라 그대로 유지
    await row(page).locator(".dsb-spin", { hasText: "▲" }).click();
    await expect(input(page)).toHaveValue("1 TB");
  });

  test("Slider와 ▲▼는 사용량 막대·System 표 숫자를 바꾸지 않는다", async ({ page }) => {
    await openDashboard(page);
    const usageBefore = await page.locator(".dsb-tiles").textContent();
    const tableBefore = await page.locator(".dsb-table tbody").textContent();
    await setTarget(page, "512 GB");
    await slider(page).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.locator(".dsb-tiles")).toHaveText(usageBefore);
    await expect(page.locator(".dsb-table tbody")).toHaveText(tableBefore);
  });
});
