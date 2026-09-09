// 같은 것을 가리켜야 하는 화면들이 실제로 같은 것을 가리키는가.
//
// 두 증상은 겉보기에 다르지만 원인이 하나였다 - **상태는 제대로 바뀌는데 그 상태를
// 그리는 쪽을 다시 그리지 않았다.**
//
//   - Navigation에서 System을 골라도 상단 System 필터는 이전 값 그대로였다.
//     `setScope()`가 `renderNav()`와 목록만 새로 그리고 `renderFilterBar()`를
//     부르지 않았다.
//   - Auto Plan을 끄겠다고 확인해도 버튼은 켜진 채였다. `toggleAutoPlan()`이
//     `renderStatusBar()`만 불렀는데 버튼은 `renderPlanActions()`가 만든다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const systemFilter = (page) => page.locator("#filter-bar select").first();

test.describe("Navigation ↔ System 필터", () => {
  test("System을 고르면 상단 필터도 같은 값이 된다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await expect(systemFilter(page)).toHaveValue("ps2");
  });

  test("다른 System으로 옮기면 필터도 따라온다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await expect(systemFilter(page)).toHaveValue("ps2");
    await page.locator(".nav-system", { hasText: "SNES" }).click();
    await expect(systemFilter(page)).toHaveValue("snes");
  });

  test("All로 돌아오면 필터도 비워진다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await page.locator(".nav-all").click();
    await expect(systemFilter(page)).toHaveValue("");
  });

  test("상단 필터로 고른 것도 Navigation에 반영된다", async ({ page }) => {
    await systemFilter(page).selectOption("snes");
    await expect(page.locator(".nav-system.active")).toContainText("SNES");
  });

  test("System을 바꾸면 이전 선택이 남지 않는다", async ({ page }) => {
    await page.locator(".lrow").first().click();
    await expect(page.locator("#status-bar")).toContainText("Selected 1");
    await page.locator(".nav-system", { hasText: "SNES" }).click();
    // 보이지도 않는 게임이 선택된 채로 남으면 Archive 수집이 그것을 대상으로 삼는다.
    await expect(page.locator("#status-bar")).toContainText("Selected 0");
  });
});

test.describe("Auto Plan", () => {
  const autoButton = (page) => page.locator("#filter-bar .btn", { hasText: "Auto Plan" });

  test("기본은 켜져 있다", async ({ page }) => {
    await expect(autoButton(page)).toContainText("✓ Auto Plan");
  });

  test("확인을 누르면 버튼 표시가 꺼진다", async ({ page }) => {
    await autoButton(page).click();
    await expect(page.locator(".modal-title")).toHaveText("Auto Plan 끄기");
    await modalButton(page, "확인").click();
    await expect(autoButton(page)).toContainText("Auto Plan OFF");
  });

  test("표시만이 아니라 동작이 바뀐다", async ({ page }) => {
    // Auto Plan의 실제 의미는 "System 이동을 Plan에 올려두기만 하는가, 바로
    // 적용하는가"다. 버튼 글자가 아니라 그 분기를 확인한다.
    //
    // 목업의 Plan은 언제나 비어 있으므로 실제 적용까지 가지는 않는다. 그래도 Auto
    // Plan을 끄면 이동이 "Plan에 올렸습니다"에서 멈추지 않고 적용 경로로 넘어가고,
    // 그 경로가 빈 Plan을 만나 다른 말을 한다 - 분기가 실제로 바뀌었다는 증거다.
    const move = async () => {
      await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
      await page.locator(".picker-row", { hasText: "Internal" }).click();
    };

    await move();
    await expect(page.locator("#toast")).toContainText("Plan에 올렸습니다");

    await autoButton(page).click();
    await modalButton(page, "확인").click();
    await move();
    await expect(page.locator("#toast")).not.toContainText("Plan에 올렸습니다");
  });

  test("취소하면 켜진 상태가 그대로다", async ({ page }) => {
    await autoButton(page).click();
    await modalButton(page, "취소").click();
    await expect(autoButton(page)).toContainText("✓ Auto Plan");
  });

  test("끈 뒤 다시 누르면 켜진다", async ({ page }) => {
    await autoButton(page).click();
    await modalButton(page, "확인").click();
    await expect(autoButton(page)).toContainText("Auto Plan OFF");
    await autoButton(page).click();
    await expect(autoButton(page)).toContainText("✓ Auto Plan");
  });
});

test.describe("Archive 탭 새로고침", () => {
  test("Archive에서 새로고침해도 Collection 스캔을 부르지 않는다", async ({ page }) => {
    // Archive는 Collection이 아니다 - Registry에 없으므로 스캔을 걸면 백엔드가
    // "Collection을 찾을 수 없습니다"로 답한다. 예전에는 새로고침이 탭 종류를
    // 가리지 않고 startScan(S.activeId)를 불렀다.
    let scans = 0;
    await page.exposeFunction("__scan", () => { scans += 1; });
    await page.evaluate(() => {
      const original = window.api.startScan;
      window.api.startScan = (id, force) => { window.__scan(); return original(id, force); };
    });

    await page.locator(".ctab.archive").click();
    await expect(page.locator(".ctab.archive")).toHaveClass(/active/);
    await page.locator("#filter-bar .icon-btn[title='다시 스캔']").click();

    await expect(page.locator("#toast")).not.toContainText("찾을 수 없습니다");
    expect(scans).toBe(0);
  });

  test("Collection 탭에서는 그대로 스캔한다", async ({ page }) => {
    let scans = 0;
    await page.exposeFunction("__scan", () => { scans += 1; });
    await page.evaluate(() => {
      const original = window.api.startScan;
      window.api.startScan = (id, force) => { window.__scan(); return original(id, force); };
    });

    await page.locator("#filter-bar .icon-btn[title='다시 스캔']").click();
    await expect.poll(() => scans).toBe(1);
  });
});
