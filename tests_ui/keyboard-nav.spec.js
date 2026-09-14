// 목록 키보드 동작 - F5, ↑/↓, Shift+↑/↓, 영문키 점프, Ctrl+A.
//
// 목업의 목록: FFX.iso / MGS2.iso / SMW.sfc (이 순서).
// 영문키 점프와 Ctrl+A는 화면에 그려진 행이 아니라 목록 전체를 대상으로 백엔드에
// 묻는다(tests/test_list_navigation.py가 순서를 검증한다) - 여기서는 그 경로를 타는지 본다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const selectedFile = (page) => page.locator(".lrow.selected .lc-file").allTextContents();

test("↓는 스크롤이 아니라 다음 게임을 고른다", async ({ page }) => {
  await page.locator(".lrow").nth(0).click();
  await page.keyboard.press("ArrowDown");
  await expect.poll(() => selectedFile(page)).toEqual(["MGS2.iso"]);
  await expect(page.locator("#detail-panel .detail-filename")).toHaveText("MGS2.iso");
});

test("↑는 이전 게임을 고르고, 맨 위에서는 그대로다", async ({ page }) => {
  await page.locator(".lrow").nth(1).click();
  await page.keyboard.press("ArrowUp");
  await expect.poll(() => selectedFile(page)).toEqual(["FFX.iso"]);
  await page.keyboard.press("ArrowUp");
  await expect.poll(() => selectedFile(page)).toEqual(["FFX.iso"]);
});

test("Shift+↓는 선택을 넓힌다", async ({ page }) => {
  await page.locator(".lrow").nth(0).click();
  await page.keyboard.press("Shift+ArrowDown");
  await page.keyboard.press("Shift+ArrowDown");
  await expect(page.locator("#status-bar")).toContainText("Selected 3");
});

test("영문키는 그 글자로 시작하는 파일로 가고, 목록 전체를 백엔드에 묻는다", async ({ page }) => {
  const asked = [];
  await page.exposeFunction("__asked", (prefix, after) => asked.push([prefix, after]));
  await page.evaluate(() => {
    const original = window.api.findRowIndex;
    window.api.findRowIndex = (id, q, prefix, after) => { window.__asked(prefix, after); return original(id, q, prefix, after); };
  });
  await page.locator(".lrow").nth(0).click();
  await page.keyboard.press("s");
  await expect.poll(() => selectedFile(page)).toEqual(["SMW.sfc"]);
  expect(asked[0]).toEqual(["s", 0]);
});

test("같은 글자가 더 없으면 처음부터 다시 찾는다", async ({ page }) => {
  await page.locator(".lrow").nth(2).click();
  await page.keyboard.press("f");
  await expect.poll(() => selectedFile(page)).toEqual(["FFX.iso"]);
});

test("그 글자로 시작하는 파일이 없으면 알려준다", async ({ page }) => {
  await page.locator(".lrow").nth(0).click();
  await page.keyboard.press("z");
  await expect(page.locator("#toast")).toContainText("Z");
  await expect.poll(() => selectedFile(page)).toEqual(["FFX.iso"]);
});

test("검색창에 입력하는 글자는 점프로 가로채지 않는다", async ({ page }) => {
  await page.locator(".lrow").nth(0).click();
  await page.locator(".search-input").click();
  await page.keyboard.type("s");
  await expect(page.locator(".search-input")).toHaveValue("s");
});

test("Ctrl+A는 목록 전체를 고른다", async ({ page }) => {
  await page.locator(".lrow").nth(0).click();
  await page.keyboard.press("Control+a");
  await expect(page.locator("#status-bar")).toContainText("Selected 3");
  await expect(page.locator("#toast")).toContainText("3개를 선택");
});

test("F5는 페이지를 새로고침하지 않고 지금 Collection을 다시 스캔한다", async ({ page }) => {
  const scans = [];
  await page.exposeFunction("__scanned", (id) => scans.push(id));
  await page.evaluate(() => {
    window.__notReloaded = true;
    const original = window.api.startScan;
    window.api.startScan = (id, force) => { window.__scanned(id); return original(id, force); };
  });
  await page.keyboard.press("F5");
  await expect.poll(() => scans.length).toBeGreaterThan(0);
  expect(await page.evaluate(() => window.__notReloaded)).toBe(true);
});
