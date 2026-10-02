// 같은 것을 가리켜야 하는 화면들이 실제로 같은 것을 가리키는가.
//
// (상단 System 필터 드롭다운은 레이아웃 재검토에서 없앴다 - Navigator가 항상
// 옆에 붙어 있고 Header가 이미 크게 System 이름을 보여주므로, 같은 것을 고르는
// 두 번째 컨트롤이 필요 없었다. 그 필터와 Navigation을 동기화하던 테스트도
// 컨트롤과 함께 없앴다.)
//
// (Auto Plan 토글 UI도 레이아웃 재검토에서 화면 밖으로 뺐다 - PENDING_DECISIONS.md.
// 그 버튼의 동기화 버그를 잡던 테스트도 버튼 자체가 없어지며 같이 사라졌다.)
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("System을 바꾸면 이전 선택이 남지 않는다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await expect(page.locator("#status-bar")).toContainText("선택 1개");
  await page.locator(".nav-system", { hasText: "SNES" }).click();
  // 보이지도 않는 게임이 선택된 채로 남으면 Archive 수집이 그것을 대상으로 삼는다.
  await expect(page.locator("#status-bar")).toContainText("선택 1개");
  await expect(page.locator(".lrow.selected .lc-file")).toContainText("SMW.sfc");
  await expect(page.locator(".detail-filename")).toContainText("SMW.sfc");
});

test.describe("Navigation ↔ Overview 헤더", () => {
  // Overview 헤더가 항상 Collection 이름만 보여주면, 지금 어떤 System을 보고
  // 있는지 알려면 다시 Navigator를 봐야 했다(레이아웃 재검토).
  test("System을 고르면 Overview가 'Collection (System)'과 개수를 보여준다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await expect(page.locator(".cheader-name")).toHaveText("PlayStation 2 · Master Library");
    // 숫자 앞에 작은 아이콘이 붙고, Metadata 개수도 함께 보여준다.
    await expect(page.locator(".cheader-stats")).toContainText("2 ROM");
    await expect(page.locator(".cheader-stats")).toContainText("1 메타데이터");
  });

  test("All로 돌아오면 Collection 이름으로 돌아온다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await expect(page.locator(".cheader-name")).toHaveText("PlayStation 2 · Master Library");
    await page.locator(".nav-all").click();
    await expect(page.locator(".cheader-name")).toHaveText("Master Library");
    await expect(page.locator(".cheader-stats")).toContainText("3 ROM");
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
    await page.locator("#collection-header .icon-btn[title='다시 스캔']").click();

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

    await page.locator("#collection-header .icon-btn[title='다시 스캔']").click();
    await expect.poll(() => scans).toBe(1);
  });
});
