// System 관리 (stitch-v3 Phase 7) - 빈 System 숨기기, System 폴더 열기, 빈 System 삭제.
//
// 목업: ps2(2개, External SD) / snes(1개, Internal) / gba(0개, Internal).
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const navSystem = (page, name) => page.locator(".nav-system", { hasText: name });
const hideToggle = (page) => page.locator(".nav-eyebrow .nav-hide-empty");

test.describe("빈 System 숨기기", () => {
  test("기본은 모두 보이고, SYSTEMS 옆 버튼으로 빈 System을 숨긴다", async ({ page }) => {
    await expect(navSystem(page, "GBA")).toBeVisible();
    await hideToggle(page).click();
    await expect(navSystem(page, "GBA")).toHaveCount(0);
    await expect(navSystem(page, "PS2")).toBeVisible();
    await expect(hideToggle(page)).toHaveAttribute("aria-pressed", "true");
    await hideToggle(page).click();
    await expect(navSystem(page, "GBA")).toBeVisible();
  });

  test("SYSTEMS 제목 글자는 그대로다", async ({ page }) => {
    await expect(page.locator(".nav-eyebrow")).toHaveText("SYSTEMS");
  });

  test("값을 Settings에 저장한다", async ({ page }) => {
    await page.evaluate(() => {
      window.__saved = [];
      const original = window.api.saveAppSettings;
      window.api.saveAppSettings = (patch) => { window.__saved.push(patch); return original(patch); };
    });
    await hideToggle(page).click();
    await expect.poll(() => page.evaluate(() => window.__saved.length)).toBeGreaterThan(0);
    const saved = await page.evaluate(() => window.__saved.at(-1));
    expect(saved.navigation).toEqual({ hideEmptySystems: true });
  });

  test("지금 보고 있는 System은 비어 있어도 남긴다", async ({ page }) => {
    await navSystem(page, "GBA").click();
    await hideToggle(page).click();
    await expect(navSystem(page, "GBA")).toBeVisible();
    await page.locator(".nav-all").click();
    await expect(navSystem(page, "GBA")).toHaveCount(0);
  });

  test("Settings의 Collections 섹션에서도 바꿀 수 있다", async ({ page }) => {
    await page.locator(".nav-top .icon-btn[title='Settings']").click();
    await page.locator(".stg-nav-item[data-section='collections']").click();
    const row = page.locator(".stg-row[data-key='navigation.hideEmptySystems']");
    await expect(row).not.toHaveClass(/soon/);
    await row.locator(".stg-switch").click();
    await expect(navSystem(page, "GBA")).toHaveCount(0);
  });
});

test.describe("System 폴더 열기", () => {
  test("System 메뉴에 ROM / Metadata / Media 폴더 열기가 있다", async ({ page }) => {
    await navSystem(page, "PS2").click({ button: "right" });
    for (const label of ["ROM 폴더", "Metadata 폴더", "Media 폴더"]) {
      await expect(page.locator(".ctx-menu .ctx-item", { hasText: label })).toBeEnabled();
    }
  });

  test("누르면 그 System과 종류로 백엔드에 요청한다", async ({ page }) => {
    await page.evaluate(() => {
      window.__opened = [];
      window.api.openSystemFolder = async (id, system, kind) => {
        window.__opened.push([system, kind]); return { ok: true, data: { path: "x" } };
      };
    });
    await navSystem(page, "PS2").click({ button: "right" });
    await page.locator(".ctx-menu .ctx-item", { hasText: "Metadata 폴더" }).click();
    await expect.poll(() => page.evaluate(() => window.__opened)).toEqual([["ps2", "metadata"]]);
  });

  test("폴더가 없으면 오류를 알린다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.openSystemFolder = async () => ({ ok: false, error: "폴더가 없습니다: D:\\x" });
    });
    await navSystem(page, "PS2").click({ button: "right" });
    await page.locator(".ctx-menu .ctx-item", { hasText: "Media 폴더" }).click();
    await expect(page.locator(".toast-msg")).toHaveText(/폴더가 없습니다/);
  });
});

test.describe("빈 System 삭제", () => {
  const deleteItem = (page) => page.locator(".ctx-menu .ctx-item", { hasText: "System 삭제" });

  test("게임이 있는 System은 삭제 메뉴가 비활성이다", async ({ page }) => {
    await navSystem(page, "PS2").click({ button: "right" });
    await expect(deleteItem(page)).toBeDisabled();
    await expect(deleteItem(page)).toHaveAttribute("title", /게임이 있는 System/);
  });

  test("빈 System은 지울 폴더를 보여주고 확인하면 목록에서 빠진다", async ({ page }) => {
    await navSystem(page, "GBA").click({ button: "right" });
    await expect(deleteItem(page)).toBeEnabled();
    await deleteItem(page).click();
    await expect(page.locator(".modal-title")).toHaveText("GBA System 삭제");
    await expect(page.locator(".sysdel-target")).toHaveCount(2);
    await expect(page.locator(".sysdel-file").first()).toContainText("systeminfo.txt");
    await modalButton(page, "삭제").click();
    await expect(navSystem(page, "GBA")).toHaveCount(0);
    await expect(page.locator(".toast-msg")).toHaveText("GBA System을 삭제했습니다.");
  });

  test("취소하면 아무것도 지우지 않는다", async ({ page }) => {
    let removed = 0;
    await page.exposeFunction("__removed", () => { removed += 1; });
    await page.evaluate(() => {
      const original = window.api.removeSystem;
      window.api.removeSystem = (...args) => { window.__removed(); return original(...args); };
    });
    await navSystem(page, "GBA").click({ button: "right" });
    await deleteItem(page).click();
    await modalButton(page, "취소").click();
    await expect(navSystem(page, "GBA")).toBeVisible();
    expect(removed).toBe(0);
  });

  test("보고 있던 System을 지우면 All로 돌아간다", async ({ page }) => {
    await navSystem(page, "GBA").click();
    await navSystem(page, "GBA").click({ button: "right" });
    await deleteItem(page).click();
    await modalButton(page, "삭제").click();
    await expect(page.locator(".nav-all")).toHaveClass(/active/);
  });

  test("백엔드가 막으면 이유를 보여주고 삭제 버튼을 두지 않는다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.systemRemovalPreview = async (id, system) => ({ ok: true, data: {
        system, games: 0, targets: [], kept: [], blockers: ["Media 파일이 3개 남아 있습니다."] } });
    });
    await navSystem(page, "GBA").click({ button: "right" });
    await deleteItem(page).click();
    await expect(page.locator(".sysdel-blocker")).toHaveText("Media 파일이 3개 남아 있습니다.");
    await expect(modalButton(page, "삭제")).toHaveCount(0);
  });
});
