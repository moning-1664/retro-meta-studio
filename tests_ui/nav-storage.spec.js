// 좌측 내비게이션의 Storage 그룹 (Phase 7.19, GUI-18).
//
// 사용자 지적:
//   - External을 추가한 뒤 System을 드래그해도 추가되지 않는다
//   - 더블클릭하면 서브디렉터리처럼 접히고 펴지면 좋겠다
//
// 드롭을 받는 곳이 **그룹 머리글 한 줄뿐**이었다. 사람은 "그 그룹 안에" 놓지,
// 머리글 글자 위에 정확히 놓지 않는다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test.describe("접기 / 펴기", () => {
  test("머리글을 더블클릭하면 그 아래 System이 접힌다", async ({ page }) => {
    const group = page.locator(".nav-group").first();
    const before = await group.locator(".nav-system").count();
    expect(before).toBeGreaterThan(0);

    await group.locator(".nav-group-head").dblclick();
    await expect(group.locator(".nav-system")).toHaveCount(0);
  });

  test("다시 더블클릭하면 펴진다", async ({ page }) => {
    const group = page.locator(".nav-group").first();
    const before = await group.locator(".nav-system").count();
    await group.locator(".nav-group-head").dblclick();
    await group.locator(".nav-group-head").dblclick();
    await expect(group.locator(".nav-system")).toHaveCount(before);
  });

  test("접은 그룹만 접힌다", async ({ page }) => {
    // 목업은 Internal과 External 두 Storage를 준다.
    await expect(page.locator(".nav-group")).toHaveCount(2);
    const second = page.locator(".nav-group").nth(1);
    const secondBefore = await second.locator(".nav-system").count();

    await page.locator(".nav-group").first().locator(".nav-group-head").dblclick();
    await expect(page.locator(".nav-group").first().locator(".nav-system")).toHaveCount(0);
    await expect(second.locator(".nav-system")).toHaveCount(secondBefore);
  });
});

test.describe("System 끌어 옮기기", () => {
  test("System 행은 끌 수 있다", async ({ page }) => {
    await expect(page.locator(".nav-system").first()).toHaveAttribute("draggable", "true");
  });

  test("그룹 전체가 드롭을 받는다", async ({ page }) => {
    // 예전에는 머리글 한 줄만 받아서, 그룹 안에 떨어뜨리면 아무 일도 안 일어났다.
    const moved = [];
    await page.exposeFunction("__moved", (s, t) => moved.push([s, t]));
    await page.evaluate(() => {
      const original = window.api.moveSystem;
      window.api.moveSystem = (id, system, storageId) => {
        window.__moved(system, storageId); return original(id, system, storageId);
      };
      const orig2 = window.api.planStorageChange;
      window.api.planStorageChange = (id, system, storageId) => {
        window.__moved(system, storageId); return orig2(id, system, storageId);
      };
    });

    // 두 번째 그룹의 **본문**(머리글이 아닌 곳)에 떨어뜨린다.
    await page.evaluate(() => {
      const groups = document.querySelectorAll(".nav-group");
      const source = groups[1].querySelector(".nav-system") || groups[1];
      const target = groups[0];
      const data = new DataTransfer();
      data.setData("text/plain", JSON.stringify({
        system: source.textContent.trim().split(/\s+/)[0].toLowerCase(),
        from: "__other__",
      }));
      target.dispatchEvent(new DragEvent("drop", { dataTransfer: data, bubbles: true }));
    });

    await expect.poll(() => moved.length, { timeout: 3000 }).toBeGreaterThan(0);
  });

  test("같은 그룹 안으로 떨어뜨리면 아무 일도 없다", async ({ page }) => {
    const moved = [];
    await page.exposeFunction("__moved2", () => moved.push(1));
    await page.evaluate(() => {
      const orig = window.api.planStorageChange;
      window.api.planStorageChange = (...a) => { window.__moved2(); return orig(...a); };
    });
    await page.evaluate(() => {
      const group = document.querySelector(".nav-group");
      const id = group.querySelector(".nav-group-head").textContent;
      const data = new DataTransfer();
      // from을 그 그룹으로 두면 옮길 이유가 없다.
      data.setData("text/plain", JSON.stringify({ system: "ps2", from: "internal" }));
      group.dispatchEvent(new DragEvent("drop", { dataTransfer: data, bubbles: true }));
      void id;
    });
    await page.waitForTimeout(300);
    expect(moved).toHaveLength(0);
  });
});
