// System 아이콘 팩 연결 - `system-icons-50/<system>.png` 파일명으로 매칭하고, 없으면 기존
// SVG → 범용 아이콘으로 넘어간다(gui_web/system-icons-pack.js, app.js systemIcon()).
// 목업 System: ps2 / snes / gba - 셋 다 PNG가 있다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const navIcon = (page, name) => page.locator(".nav-system", { hasText: name }).locator(".sys-ic");

test("Navigator의 System 아이콘은 그 System 이름의 PNG를 쓴다", async ({ page }) => {
  const img = navIcon(page, "PS2").locator("img.sys-raster");
  await expect(img).toHaveAttribute("src", /system-icons-50\/ps2\.png$/);
  await expect.poll(() => img.evaluate((el) => el.complete && el.naturalWidth)).toBeGreaterThan(0);
});

test("Navigator 아이콘 자리는 18px이고 행 높이를 바꾸지 않는다", async ({ page }) => {
  const rowBefore = await page.locator(".nav-all").boundingBox();
  const box = await navIcon(page, "SNES").boundingBox();
  expect(Math.round(box.width)).toBe(18);
  expect(Math.round(box.height)).toBe(18);
  const sysRow = await page.locator(".nav-system", { hasText: "SNES" }).boundingBox();
  expect(Math.round(sysRow.height)).toBe(Math.round(rowBefore.height));
});

test("System을 고르면 Collection 헤더에 26px 아이콘이 나온다", async ({ page }) => {
  await page.locator(".nav-system", { hasText: "GBA" }).click();
  const ic = page.locator(".cheader-icon .sys-ic");
  await expect(ic.locator("img.sys-raster")).toHaveAttribute("src", /gba\.png$/);
  const box = await ic.boundingBox();
  expect(Math.round(box.width)).toBe(26);
});

test("이름 후보: 구분자·별칭·지역 접미사를 거쳐 기존 파일명에 닿는다", async ({ page }) => {
  const cands = await page.evaluate(() => ({
    ps2: window.RMSystemIconPack.candidates("PlayStation 2"),
    mame: window.RMSystemIconPack.candidates("mame2003plus"),
    n64dd: window.RMSystemIconPack.candidates("n64dd"),
    jp: window.RMSystemIconPack.candidates("pcengine_jp"),
  }));
  expect(cands.ps2).toContain("ps2");
  expect(cands.mame).toContain("mame2003");
  expect(cands.n64dd).toContain("n64");
  expect(cands.jp).toContain("pcengine");
});

test("PNG가 없으면 기존 SVG나 범용 아이콘으로 넘어간다", async ({ page }) => {
  await page.evaluate(() => { window.RMSystemIconPack.base = "no-such-icon-dir/"; });
  // 다시 그리게 한다 - System을 고르면 Navigator가 새로 만들어진다.
  await page.locator(".nav-system", { hasText: "SNES" }).click();
  const ic = navIcon(page, "PS2");
  await expect(ic.locator("img")).toHaveCount(0);
  await expect(ic.locator("svg")).toHaveCount(1);
});
