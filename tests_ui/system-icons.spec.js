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

test("System을 고르면 Collection 헤더 배경에 그 System 그림이 깔린다", async ({ page }) => {
  // 아이콘 상자(26px)는 콘솔 포인트 색 바로 바뀌었다(사용자 결정) - System 그림은
  // 배경 워터마크로 남는다. 같은 아이콘 팩을 쓰므로 파일 해석 경로는 그대로다.
  await page.locator(".nav-system", { hasText: "GBA" }).click();
  const art = page.locator(".cheader .cheader-art .sys-ic");
  await expect(art.locator("img.sys-raster")).toHaveAttribute("src", /gba\.png$/);
  const box = await art.boundingBox();
  expect(Math.round(box.width)).toBe(62);
  // 제목 옆에는 콘솔 색 바가 선다.
  await expect(page.locator(".cheader .cheader-bar")).toBeVisible();
  await expect(page.locator(".cheader .cheader-icon")).toHaveCount(0);
});

// HERO(.cheader-art)의 System 색 배경이 Detail 쪽 경계에서 뚝 끊겨 보였다
// (실사용 피드백 - "hero와 detail 사이는 끊어져 보인다"). 공통 조상(#header-row)에
// 같은 색 변수를 둬서 .detail-topspace의 그라데이션이 이어받게 했다.
//
// **#detail-top 자체가 아니라 .detail-topspace를 봐야 한다.** #detail-top의
// 배경은 그 안을 꽉 채우는 자식 .detail-topspace(불투명한 단색)에 완전히
// 가려져서 화면에 전혀 안 보인다 - 처음엔 #detail-top에 그라데이션을 줬다가
// 실사용에서 "적용 안 됐다"고 확인받고서야 이 사실을 발견했다. #detail-top의
// backgroundImage만 확인하면 "CSS는 계산됐다"는 것만 보고 "실제로 안 보인다"는
// 진짜 문제를 놓친다.
test("System을 고르면 Detail 쪽까지 같은 색 그라데이션이 이어진다", async ({ page }) => {
  const headerRow = page.locator("#header-row");
  await expect(headerRow).not.toHaveClass(/has-sys-art/);
  const plainBg = await page.locator(".detail-topspace").evaluate((el) => getComputedStyle(el).backgroundImage);
  expect(plainBg).toBe("none");   // System을 안 골랐으면 그냥 단색이다.

  await page.locator(".nav-system", { hasText: "GBA" }).click();
  await expect(headerRow).toHaveClass(/has-sys-art/);
  const sysBase = await headerRow.evaluate((el) => el.style.getPropertyValue("--sys-base"));
  const sysPoint = await headerRow.evaluate((el) => el.style.getPropertyValue("--sys-point"));
  expect(sysBase).not.toBe("");
  expect(sysPoint).not.toBe("");
  const taintedBg = await page.locator(".detail-topspace").evaluate((el) => getComputedStyle(el).backgroundImage);
  expect(taintedBg).toContain("gradient");

  // "All Games"로 돌아가면 얼룩 없이 원래대로다.
  await page.locator(".nav-all").click();
  await expect(headerRow).not.toHaveClass(/has-sys-art/);
  const clearedBg = await page.locator(".detail-topspace").evaluate((el) => getComputedStyle(el).backgroundImage);
  expect(clearedBg).toBe("none");
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
