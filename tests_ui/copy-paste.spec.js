// Ctrl+C/Ctrl+V - Gamelist에서 없앴던 것을 되살렸다(사용자 요청, Phase 이후).
// 병합 로직 자체는 이미 tests/test_metadata_only_paste.py가 검증하는 기존
// plan_add() + 충돌 해결 흐름을 그대로 쓴다 - 여기서는 키보드 단축키가
// 그 흐름을 실제로 부르는지만 확인한다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test.describe("복사/붙여넣기", () => {
  test("Ctrl+C는 선택한 항목으로 copy_selection을 부른다", async ({ page }) => {
    const calls = [];
    await page.exposeFunction("__note", (name, args) => calls.push({ name, args }));
    await page.evaluate(() => {
      const original = window.api.copySelection;
      window.api.copySelection = (id, uids) => { window.__note("copySelection", [id, uids]); return original(id, uids); };
    });

    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");

    await expect.poll(() => calls.length).toBeGreaterThan(0);
    expect(calls[0].name).toBe("copySelection");
    expect(calls[0].args[1]).toHaveLength(1);
  });

  test("선택 없이 Ctrl+C를 누르면 안내만 뜨고 호출되지 않는다", async ({ page }) => {
    const calls = [];
    await page.exposeFunction("__note", () => calls.push(1));
    await page.evaluate(() => {
      const original = window.api.copySelection;
      window.api.copySelection = (...a) => { window.__note(); return original(...a); };
    });

    await page.keyboard.press("Control+c");
    await expect(page.locator("#toast.show")).toBeVisible();
    expect(calls.length).toBe(0);
  });

  test("Ctrl+V는 paste를 부르고 목록을 새로고침한다", async ({ page }) => {
    const calls = [];
    await page.exposeFunction("__note", (id) => calls.push(id));
    await page.evaluate(() => {
      const original = window.api.paste;
      window.api.paste = (id) => { window.__note(id); return original(id); };
    });

    await page.keyboard.press("Control+v");

    await expect.poll(() => calls.length).toBeGreaterThan(0);
    await expect(page.locator("#toast.show")).toBeVisible();
  });

  test("입력 필드에 포커스가 있으면 목록 단축키로 새지 않는다", async ({ page }) => {
    // 실사용 확인: metadata 검색창 등에서 Ctrl+C/V는 텍스트 복사/붙여넣기여야 한다.
    await page.locator(".lrow").first().click();
    const calls = [];
    await page.exposeFunction("__note", () => calls.push(1));
    await page.evaluate(() => {
      const original = window.api.copySelection;
      window.api.copySelection = (...a) => { window.__note(); return original(...a); };
    });

    await page.locator("#filter-bar input[type=search], #filter-bar .search-input").first().focus().catch(() => {});
    const active = await page.evaluate(() => document.activeElement.tagName);
    if (active === "INPUT" || active === "TEXTAREA") {
      await page.keyboard.press("Control+c");
      expect(calls.length).toBe(0);
    }
  });
});
