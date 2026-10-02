// 탭을 오가도 보던 자리가 그대로이고, 앱을 다시 켜면 열어 둔 탭이 되살아난다(사용자 피드백).
//   - multi-collection에서 Collection을 왔다 갔다 하면 선택한 위치가 리셋됐다
//   - Dashboard를 보다 다른 Collection을 갔다 오면 System으로 돌아갔다
//   - 첫 Collection만 앱을 껐다 켜도 남고 두 번째부터는 사라졌다
//   - Collection 기본 이름이 (Pegasus처럼) ROM 폴더 이름("Roms")이 됐다
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

async function openSecondTab(page) {
  await page.locator(".ctab-add").click();
  await page.locator(".add-collection-history summary").click();
  await page.locator(".picker-row", { hasText: "Android ES-DE" }).click();
  await expect(page.locator(".ctab:not(.archive)")).toHaveCount(2);
}

test.describe("탭을 오갈 때", () => {
  test.beforeEach(async ({ page }) => { await openApp(page); });

  test("고른 게임이 그대로 돌아온다", async ({ page }) => {
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".lc-file").click();
    await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).locator(".lc-file").click({ modifiers: ["Control"] });
    await expect(page.locator("#status-bar")).toContainText("선택 2개");

    await openSecondTab(page);
    await expect(page.locator("#status-bar")).toContainText("선택 1개");
    await page.locator(".ctab", { hasText: "Master Library" }).click();
    await expect(page.locator("#status-bar")).toContainText("선택 2개");
  });

  test("탭으로 돌아오면 마지막으로 포커스한 게임의 상세도 복원한다", async ({ page }) => {
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".lc-file").click();
    await expect(page.locator("#detail-panel .detail-filename")).toContainText("FFX.iso");
    await openSecondTab(page);
    await page.locator(".ctab", { hasText: "Master Library" }).click();
    await expect(page.locator("#detail-panel .detail-filename")).toContainText("FFX.iso");
  });

  test("Dashboard를 보고 있던 탭은 Dashboard로 돌아온다", async ({ page }) => {
    await page.locator(".nav-bottom, #nav").getByText("Dashboard").first().click();
    await expect(page.locator("#center.dashboard-mode")).toBeVisible();

    await openSecondTab(page);
    await expect(page.locator("#center.dashboard-mode")).toHaveCount(0);
    await page.locator(".ctab", { hasText: "Master Library" }).click();
    await expect(page.locator("#center.dashboard-mode")).toBeVisible();
  });

  test("고른 System도 그대로다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "SNES" }).click();
    await expect(page.locator(".lrow")).toHaveCount(1);
    await openSecondTab(page);
    await page.locator(".ctab", { hasText: "Master Library" }).click();
    await expect(page.locator(".nav-system.active, .nav-row.active", { hasText: "SNES" })).toBeVisible();
    await expect(page.locator(".lrow")).toHaveCount(1);
  });
});

test.describe("앱을 다시 켤 때", () => {
  test("마지막에 열어 둔 탭을 모두 되살리고 보던 탭으로 돌아온다", async ({ page }) => {
    await page.addInitScript(() => {
      window.__RMS_MOCK_APP_SETTINGS = { session: { tabs: ["c1", "c2"], active: "c2" } };
    });
    await openApp(page);
    await expect(page.locator(".ctab:not(.archive)")).toHaveCount(2);
    await expect(page.locator(".ctab.active")).toContainText("Android ES-DE");
  });

  test("Restore open tabs를 끄면 첫 Collection만 연다", async ({ page }) => {
    await page.addInitScript(() => {
      window.__RMS_MOCK_APP_SETTINGS = {
        session: { tabs: ["c1", "c2"], active: "c2" }, collections: { restoreTabs: false } };
    });
    await openApp(page);
    await expect(page.locator(".ctab:not(.archive)")).toHaveCount(1);
    await expect(page.locator(".ctab.active")).toContainText("Master Library");
  });

  test("지워진 Collection은 건너뛴다", async ({ page }) => {
    await page.addInitScript(() => {
      window.__RMS_MOCK_APP_SETTINGS = { session: { tabs: ["gone", "c1"], active: "gone" } };
    });
    await openApp(page);
    await expect(page.locator(".ctab:not(.archive)")).toHaveCount(1);
  });

  test("탭을 열면 세션이 저장된다", async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      window.__saved = [];
      const original = window.api.saveAppSettings;
      window.api.saveAppSettings = (patch) => { window.__saved.push(patch); return original(patch); };
    });
    await openSecondTab(page);
    await expect.poll(() => page.evaluate(() =>
      window.__saved.some((p) => p.session && p.session.tabs.length === 2 && p.session.active === "c2"))).toBe(true);
  });
});

test.describe("Collection 기본 이름", () => {
  test("이름을 안 적으면 감지된 저장 형식 이름이 된다", async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      window.__created = [];
      const original = window.api.createCollection;
      window.api.createCollection = (...args) => { window.__created.push(args); return original(...args); };
    });
    await page.locator(".ctab-add").click();
    await expect(page.locator(".add-name-hint")).toContainText("저장 형식");
    await page.locator("#add-frontend").selectOption("pegasus");
    await expect(page.locator(".add-name-hint")).toContainText("Pegasus");
    // 이름 칸은 비워 둔 채 폴더만 고른다(목업의 "찾아보기"는 경로를 채워 준다).
    await page.locator(".modal-body .btn", { hasText: "찾아보기" }).first().click();
    await page.locator(".modal-actions .btn", { hasText: "Add" }).click();
    await expect.poll(() => page.evaluate(() => window.__created.length)).toBe(1);
    const [name, frontend] = await page.evaluate(() => window.__created[0]);
    // The selected mock folder contains ES-DE metadata; detection takes precedence.
    expect(frontend).toBe("es-de");
    expect(name).toBe("ES-DE");
  });
});
