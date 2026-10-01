// 좌측 내비게이션은 **External Storage를 실제로 추가하기 전까지는 System 목록이지
// Storage 계층이 아니다.**
//
// 예전에는 Storage를 항상 System의 부모 노드로 그렸다(접기/펴기, 그룹 사이
// Drag & Drop). 그런데 ES-DE에서 ROM 폴더를 따로 지정하면 그 폴더가 별도 Storage가
// 되면서, External Storage를 한 번도 안 써 본 사용자에게까지
//
//     INTERNAL
//      ├─ Famicom
//      └─ MSX
//     ROM
//      ├─ NES
//      └─ MSX1
//
// 처럼 요구한 적 없는 분류가 나타났다. 그래서 한동안 완전히 평평하게 없앴었다.
//
// 그런데 External Storage를 실제로 추가한 뒤에는 이야기가 다르다 - 그때부터는
// "이 System을 내부/외부 중 어디에 둘지"가 사용자가 직접 관리하는 결정이 되므로
// (드래그로 옮기고, ES-DE의 custom systems XML은 External만 대상으로 한다)
// Internal/External을 그룹으로 나눠 보여준다. 이 목업은 이미 External Storage
// (ext-1 "External SD")를 하나 갖고 있으므로, 아래 테스트는 전부 "그룹이 있는"
// 상태를 기준으로 한다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test.describe("External Storage가 있으면 Storage별로 묶인다", () => {
  test("Storage 그룹 머리글이 Storage 수만큼 있다", async ({ page }) => {
    // 목업: Internal + External SD.
    await expect(page.locator(".nav-group")).toHaveCount(2);
    await expect(page.locator(".nav-group-head")).toHaveCount(2);
  });

  test("System 행은 목업의 System 수와 같다", async ({ page }) => {
    // 목업은 ps2 / snes / gba 셋이고, 서로 다른 Storage에 흩어져 있다.
    await expect(page.locator(".nav-system")).toHaveCount(3);
  });

  test("같은 System이 두 번 나타나지 않는다", async ({ page }) => {
    const names = await page.locator(".nav-system .nav-label").allTextContents();
    expect(new Set(names).size).toBe(names.length);
  });

  test("Storage가 달라도 둘 다 화면에 있다", async ({ page }) => {
    const names = await page.locator(".nav-system .nav-label").allTextContents();
    // ps2는 External SD, snes는 Internal에 있다. 그룹은 나뉘어도 둘 다 보인다.
    expect(names).toContain("PS2");
    expect(names).toContain("SNES");
  });
});

test.describe("빈 System은 자기 그룹 안에서 뒤로 정렬될 뿐 따로 묶이지 않는다", () => {
  test("게임이 있는 System이 그룹 안에서 먼저 나온다", async ({ page }) => {
    // snes(1개)와 gba(0개)는 둘 다 Internal 그룹이다. gba가 나중이어야 한다.
    const internalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "INTERNAL" }) });
    const names = await internalGroup.locator(".nav-system .nav-label").allTextContents();
    expect(names).toEqual(["SNES", "GBA"]);
  });

  test("'Empty Systems' 같은 별도 묶음을 만들지 않는다", async ({ page }) => {
    // System 구역은 하나뿐이다 - 비었다는 사실은 개수(0)가 이미 말해 준다.
    await expect(page.locator(".nav-eyebrow-label")).toHaveCount(1);
    await expect(page.locator(".nav-eyebrow-label")).toHaveText("시스템");
  });

  test("빈 System도 목록에 남아 있다", async ({ page }) => {
    await expect(page.locator(".nav-system", { hasText: "GBA" })).toBeVisible();
  });
});

test.describe("Storage 이동은 System 우클릭 메뉴로", () => {
  test("System을 우클릭하면 그 System의 메뉴가 뜬다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
    await expect(page.locator(".ctx-title")).toHaveText("PS2");
  });

  test("지금 어느 Storage에 있는지 알려준다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
    await expect(page.locator(".ctx-sub")).toContainText("External SD");
  });

  test("다른 Storage를 고르면 이동을 요청한다", async ({ page }) => {
    const moved = [];
    await page.exposeFunction("__moved", (s, t) => moved.push([s, t]));
    await page.evaluate(() => {
      const original = window.api.operationPreview;
      window.api.operationPreview = (id, action, options) => {
        window.__moved(options.system, options.storageId); return original(id, action, options);
      };
    });

    await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
    await page.locator(".ctx-menu .ctx-item", { hasText: "Internal" }).click();
    await expect.poll(() => moved.length).toBeGreaterThan(0);
    expect(moved[0]).toEqual(["ps2", "internal"]);
  });

  test("자기가 이미 있는 Storage는 이동 후보로 내놓지 않는다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
    await expect(page.locator(".ctx-menu .ctx-item", { hasText: "Internal" })).toBeVisible();
    const targets = await page.locator(".ctx-menu .ctx-item .ctx-label").allTextContents();
    expect(targets).not.toContain("External SD");
  });
});

test.describe("Storage 이동은 드래그로도 된다", () => {
  test("System을 다른 Storage 그룹으로 끌어다 놓으면 이동을 요청한다", async ({ page }) => {
    const moved = [];
    await page.exposeFunction("__moved", (s, t) => moved.push([s, t]));
    await page.evaluate(() => {
      const original = window.api.operationPreview;
      window.api.operationPreview = (id, action, options) => {
        window.__moved(options.system, options.storageId); return original(id, action, options);
      };
    });

    const internalGroup = page.locator(".nav-group", { has: page.locator(".nav-group-name", { hasText: "INTERNAL" }) });
    await page.locator(".nav-system", { hasText: "PS2" }).dragTo(internalGroup);
    await expect.poll(() => moved.length).toBeGreaterThan(0);
    expect(moved[0]).toEqual(["ps2", "internal"]);
  });
});
