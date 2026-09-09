// 같은 것을 가리켜야 하는 화면들이 실제로 같은 것을 가리키는가.
//
// 두 증상은 겉보기에 다르지만 원인이 하나였다 - **상태는 제대로 바뀌는데 그 상태를
// 그리는 쪽을 다시 그리지 않았다.**
//
//   - Navigation에서 System을 골라도 상단 System 필터는 이전 값 그대로였다.
//     `setScope()`가 `renderNav()`와 목록만 새로 그리고 `renderFilterBar()`를
//     부르지 않았다.
//
// (Auto Plan 토글 UI는 레이아웃 재검토에서 화면 밖으로 뺐다 - PENDING_DECISIONS.md.
// 이 파일이 잡던 그 버튼의 동기화 버그는 버튼 자체가 없어지며 같이 사라졌다.)
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
