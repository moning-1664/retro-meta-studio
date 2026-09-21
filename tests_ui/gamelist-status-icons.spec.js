// Gamelist Status 컬럼 - ROM / Metadata / Media / Video 네 칸(사용자 결정 2026-09-17/20).
// 각 칸은 독립적이고 상태가 셋이다: ok(흰색, 다 있음) · partial(노란색, 일부만) · none(회색, 없음).
// **빨간색은 쓰지 않는다** - 없는 것이 오류는 아니다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const icon = (row, key) => row.locator(`.lc-status .status-icon[data-status='${key}']`);
const rowByFile = (page, file) => page.locator(".lrow", { hasText: file });

/** 목록 응답의 특정 행 수준 값을 덮어쓴다 - 공용 목업을 고치면 다른 spec이 깨진다. */
async function override(page, file, patch) {
  await page.evaluate(({ file, patch }) => {
    const original = window.api.listRows;
    window.api.listRows = async (id, q) => {
      const r = await original(id, q);
      if (r.ok) r.data.rows.forEach((row) => { if (row.file === file) Object.assign(row, patch); });
      return r;
    };
  }, { file, patch });
}

test("네 칸이 독립적으로 표시된다", async ({ page }) => {
  const ffx = rowByFile(page, "Final Fantasy X");
  await expect(ffx.locator(".lc-status .status-icon")).toHaveCount(4);
  await expect(ffx.locator(".lc-status .status-icon")).toHaveClass(
    [/lv-ok/, /lv-ok/, /lv-ok/, /lv-ok/]);
});

test("칸 순서는 ROM / Metadata / Media / Video다", async ({ page }) => {
  const ffx = rowByFile(page, "Final Fantasy X");
  const keys = await ffx.locator(".lc-status .status-icon").evaluateAll((els) => els.map((el) => el.dataset.status));
  expect(keys).toEqual(["rom", "metaLevel", "mediaLevel", "videoLevel"]);
});

test("없는 칸은 빨간색이 아니라 회색이다", async ({ page }) => {
  // 목업의 SMW는 Title만 있어 Metadata가 partial이다 - "없음"을 보려고 이 테스트 안에서만 바꾼다.
  await override(page, "SMW.sfc", { metaLevel: "none" });
  await page.locator(".nav-system", { hasText: "SNES" }).click();
  const smw = rowByFile(page, "Super Mario World");
  await expect(icon(smw, "metaLevel")).toHaveClass(/lv-none/);
  await expect(icon(smw, "mediaLevel")).toHaveClass(/lv-none/);
  await expect(icon(smw, "videoLevel")).toHaveClass(/lv-none/);
  // 빨간색(--danger)이 어디에도 쓰이지 않는다.
  const colors = await smw.locator(".status-icon").evaluateAll((els) => els.map((el) => getComputedStyle(el).color));
  const danger = await page.evaluate(() => {
    const probe = document.createElement("span");
    probe.style.color = "var(--danger)";
    document.body.appendChild(probe);
    const c = getComputedStyle(probe).color;
    probe.remove();
    return c;
  });
  colors.forEach((c) => expect(c).not.toBe(danger));
});

test("일부만 있으면 노란색이고 이유가 툴팁에 나온다", async ({ page }) => {
  await override(page, "MGS2.iso", { metaLevel: "partial", mediaLevel: "partial" });
  await page.locator(".nav-system", { hasText: "PS2" }).click();
  const mgs2 = rowByFile(page, "Metal Gear Solid 2");
  await expect(icon(mgs2, "metaLevel")).toHaveClass(/lv-partial/);
  await expect(icon(mgs2, "metaLevel")).toHaveAttribute("title", /Title 또는 Description/);
  await expect(icon(mgs2, "mediaLevel")).toHaveClass(/lv-partial/);
  await expect(icon(mgs2, "mediaLevel")).toHaveAttribute("title", /주요 미디어/);
  // 노란색은 색이 실제로 다르다.
  const [ok, partial] = await Promise.all([
    icon(rowByFile(page, "Final Fantasy X"), "rom").evaluate((el) => getComputedStyle(el).color),
    icon(mgs2, "mediaLevel").evaluate((el) => getComputedStyle(el).color),
  ]);
  expect(partial).not.toBe(ok);
});

test("영상만 없어도 그 칸만 회색이다", async ({ page }) => {
  await override(page, "FFX.iso", { videoLevel: "none" });
  await page.locator(".nav-system", { hasText: "PS2" }).click();
  const ffx = rowByFile(page, "Final Fantasy X");
  await expect(icon(ffx, "videoLevel")).toHaveClass(/lv-none/);
  await expect(icon(ffx, "mediaLevel")).toHaveClass(/lv-ok/);
});

test("ROM이 없으면 ROM 칸만 회색이고 나머지는 그대로다", async ({ page }) => {
  await override(page, "FFX.iso", { rom: "none", present: false });
  await page.locator(".nav-system", { hasText: "PS2" }).click();
  const ffx = rowByFile(page, "Final Fantasy X");
  await expect(icon(ffx, "rom")).toHaveClass(/lv-none/);
  await expect(icon(ffx, "metaLevel")).toHaveClass(/lv-ok/);
});
