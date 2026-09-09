// 좌측 내비게이션은 **System 목록이지 Storage 계층이 아니다**.
//
// 예전에는 Storage를 System의 부모 노드로 그렸다(접기/펴기, 그룹 사이 Drag & Drop).
// 그런데 ES-DE에서 ROM 폴더를 따로 지정하면 그 폴더가 별도 Storage가 되면서 화면에
//
//     INTERNAL
//      ├─ Famicom
//      └─ MSX
//     ROM
//      ├─ NES
//      └─ MSX1
//
// 처럼 사용자가 요구한 적 없는 분류가 나타났다. Storage는 용량·볼륨·파일 작업을 위한
// 내부 개념이고, 사용자가 관리하는 단위는 System이다.
//
// Storage 이동 기능 자체는 없애지 않았다 - 들어가는 문만 System 우클릭 메뉴로 옮겼다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test.describe("System은 평평하게 보인다", () => {
  test("Storage 그룹 머리글이 아예 없다", async ({ page }) => {
    await expect(page.locator(".nav-group")).toHaveCount(0);
    await expect(page.locator(".nav-group-head")).toHaveCount(0);
  });

  test("System 행은 목업의 System 수와 같다", async ({ page }) => {
    // 목업은 ps2 / snes / gba 셋이고, 서로 다른 Storage에 흩어져 있다.
    await expect(page.locator(".nav-system")).toHaveCount(3);
  });

  test("같은 System이 두 번 나타나지 않는다", async ({ page }) => {
    const names = await page.locator(".nav-system .nav-label").allTextContents();
    expect(new Set(names).size).toBe(names.length);
  });

  test("Storage가 달라도 한 목록 안에 함께 있다", async ({ page }) => {
    const names = await page.locator(".nav-system .nav-label").allTextContents();
    // ps2는 External SD, snes는 Internal에 있다. 그래도 같은 목록이다.
    expect(names).toContain("PS2");
    expect(names).toContain("SNES");
  });
});

test.describe("빈 System은 뒤로 정렬될 뿐 따로 묶이지 않는다", () => {
  test("게임이 있는 System이 먼저 나온다", async ({ page }) => {
    const names = await page.locator(".nav-system .nav-label").allTextContents();
    // gba는 0개다. 마지막이어야 한다.
    expect(names[names.length - 1]).toBe("GBA");
  });

  test("'Empty Systems' 같은 별도 묶음을 만들지 않는다", async ({ page }) => {
    await expect(page.locator(".nav-eyebrow")).toHaveCount(1);
    await expect(page.locator(".nav-eyebrow")).toHaveText("SYSTEMS");
  });

  test("빈 System도 목록에 남아 있다", async ({ page }) => {
    await expect(page.locator(".nav-system", { hasText: "GBA" })).toBeVisible();
  });
});

test.describe("Storage 이동은 System 메뉴로", () => {
  test("System을 우클릭하면 그 System의 정보가 뜬다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
    await expect(page.locator(".modal-title")).toHaveText("PS2");
  });

  test("지금 어느 Storage에 있는지 알려준다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
    await expect(page.locator(".modal-body")).toContainText("External SD");
  });

  test("다른 Storage를 고르면 이동을 요청한다", async ({ page }) => {
    const moved = [];
    await page.exposeFunction("__moved", (s, t) => moved.push([s, t]));
    await page.evaluate(() => {
      const original = window.api.planStorageChange;
      window.api.planStorageChange = (id, system, storageId) => {
        window.__moved(system, storageId); return original(id, system, storageId);
      };
    });

    await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
    await page.locator(".picker-row", { hasText: "Internal" }).click();
    await expect.poll(() => moved.length).toBeGreaterThan(0);
    expect(moved[0]).toEqual(["ps2", "internal"]);
  });

  test("자기가 이미 있는 Storage는 이동 후보로 내놓지 않는다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click({ button: "right" });
    const targets = await page.locator(".picker-row .picker-name").allTextContents();
    expect(targets).not.toContain("External SD");
  });
});
