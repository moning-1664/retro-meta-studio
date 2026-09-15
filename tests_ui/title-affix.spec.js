// Title Prefix/Postfix 일괄 적용(사용자 결정) - Settings의 지역별 규칙, Gamelist/System 우클릭
// 메뉴, 미리보기 -> Plan -> Apply. 실제 계산(지역 분류/기존 장식 떼기/디스크 표시 보존)은
// tests/test_title_affix.py와 tests/test_title_affix_plan.py가 촘촘히 검증하고, 여기서는
// Settings 화면과 메뉴 흐름만 본다.
//
// 목업 게임: FFX.iso(ps2, region JP) / MGS2.iso(ps2, region USA) / SMW.sfc(snes, region "").
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

const REGION_INDEX = { kr: 0, en: 1, jp: 2, eu: 3, global: 4 };

const openMetadataSettings = async (page) => {
  await page.locator(".nav-top .icon-btn[title='Settings']").click();
  await page.locator(".stg-nav-item[data-section='metadata']").click();
  await expect(page.locator(".stg-title-affix")).toBeVisible();
};

/** Settings에서 한 구역을 켜고 Prefix/Postfix와 텍스트를 정한다. */
const configureRegion = async (page, bucket, { mode, text } = {}) => {
  await openMetadataSettings(page);
  const row = page.locator(".stg-title-affix-row").nth(REGION_INDEX[bucket]);
  await row.locator(".stg-switch").click();
  if (mode) await row.locator("select").selectOption(mode);
  if (text != null) {
    const input = row.locator(".stg-title-affix-text");
    await input.fill(text);
    await input.press("Tab");
  }
  // Settings 저장은 300ms 디바운스다(app.js updateSettings) - 실제로 저장될 때까지 기다린다.
  await page.waitForTimeout(400);
  await page.locator(".stg-close").click();
};

const rightClickRow = (page, text) => page.locator(".lrow", { hasText: text }).click({ button: "right" });
const menuItem = (page, label) => page.locator(".ctx-menu .ctx-item", { hasText: label });

test.beforeEach(async ({ page }) => { await openApp(page); });

test.describe("Settings > Metadata & Media > Title Prefix/Postfix", () => {
  test("기본은 5개 구역 모두 꺼져 있고, 텍스트/방식은 켜야 조작할 수 있다", async ({ page }) => {
    await openMetadataSettings(page);
    const rows = page.locator(".stg-title-affix-row");
    await expect(rows).toHaveCount(5);
    for (const bucket of Object.keys(REGION_INDEX)) {
      const row = rows.nth(REGION_INDEX[bucket]);
      await expect(row.locator("input[type=checkbox]")).not.toBeChecked();
      await expect(row.locator("select")).toBeDisabled();
      await expect(row.locator(".stg-title-affix-text")).toBeDisabled();
      await expect(row).toHaveClass(/off/);
    }
  });

  test("켜면 방식/텍스트 입력이 활성화된다", async ({ page }) => {
    await openMetadataSettings(page);
    const row = page.locator(".stg-title-affix-row").nth(REGION_INDEX.en);
    await row.locator(".stg-switch").click();
    await expect(row).not.toHaveClass(/off/);
    await expect(row.locator("select")).toBeEnabled();
    await expect(row.locator(".stg-title-affix-text")).toBeEnabled();
  });

  test("바꾼 값은 titleAffix 섹션 전체(그 구역)를 통째로 저장한다", async ({ page }) => {
    await page.evaluate(() => {
      window.__saved = [];
      const original = window.api.saveAppSettings;
      window.api.saveAppSettings = (patch) => { window.__saved.push(patch); return original(patch); };
    });
    await openMetadataSettings(page);
    const row = page.locator(".stg-title-affix-row").nth(REGION_INDEX.jp);
    await row.locator(".stg-switch").click();
    await row.locator("select").selectOption("postfix");
    const input = row.locator(".stg-title-affix-text");
    await input.fill("일본");
    await input.press("Tab");

    await expect.poll(() => page.evaluate(() => window.__saved.length)).toBeGreaterThan(0);
    const saved = await page.evaluate(() => window.__saved.reduce((acc, p) => ({ ...acc, ...p.titleAffix }), {}));
    // 세 번의 조작(켜기/방식/텍스트) 모두 그 구역의 완전한 모양으로 저장돼야 한다 -
    // 부분만 보내면 나머지가 지워진다(섹션 한 단계 깊이 병합).
    expect(saved.jp).toEqual({ enabled: true, mode: "postfix", text: "일본" });
  });
});

test.describe("Gamelist 우클릭 - 선택한 게임에 적용", () => {
  test("region이 안 맞으면 바뀔 게 없다고 알린다", async ({ page }) => {
    await rightClickRow(page, "Final Fantasy X");   // region JP, 아무 구역도 안 켜짐
    await menuItem(page, "Title Prefix/Postfix 적용…").click();
    await expect(page.locator(".toast-msg")).toContainText("바뀔 제목이 없습니다");
    await expect(page.locator(".modal-title")).toHaveCount(0);
  });

  test("미리보기에 예전/새 제목을 보여주고, 확인해야 Plan에 올라간다", async ({ page }) => {
    await configureRegion(page, "jp", { mode: "prefix", text: "JP" });
    await rightClickRow(page, "Final Fantasy X");
    await menuItem(page, "Title Prefix/Postfix 적용…").click();

    await expect(page.locator(".modal-title")).toHaveText("Title Prefix/Postfix");
    await expect(page.locator(".title-affix-old")).toHaveText("Final Fantasy X");
    await expect(page.locator(".title-affix-new")).toHaveText("JP_Final Fantasy X");

    await modalButton(page, "취소").click();
    await expect(page.locator(".modal-title")).toHaveCount(0);
    // 취소했으므로 아직 Plan에 없다 - 목록에 표시 마크가 없다.
    await expect(page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".status-mark.edit")).toHaveCount(0);

    await rightClickRow(page, "Final Fantasy X");
    await menuItem(page, "Title Prefix/Postfix 적용…").click();
    await modalButton(page, "Plan에 추가").click();
    await expect(page.locator(".toast-msg")).toContainText("Plan에 올렸습니다");
    await expect(page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".status-mark.edit")).toBeVisible();
  });

  test("여러 개를 선택하면 그 개수만큼 대상이 되고 메뉴에 개수가 보인다", async ({ page }) => {
    await configureRegion(page, "en", { mode: "prefix", text: "EN" });
    await page.locator(".lrow").nth(0).click();
    await page.locator(".lrow").nth(1).click({ modifiers: ["Control"] });
    await page.locator(".lrow").nth(0).click({ button: "right" });
    await expect(menuItem(page, "Title Prefix/Postfix 적용… (2개)")).toBeVisible();
    await menuItem(page, "Title Prefix/Postfix 적용… (2개)").click();
    // MGS2.iso(USA)만 en 규칙에 걸리고 FFX.iso(JP)는 안 걸린다.
    await expect(page.locator(".title-affix-row")).toHaveCount(1);
    await expect(page.locator(".title-affix-new")).toHaveText("EN_Metal Gear Solid 2");
  });
});

test.describe("System 우클릭 - 전체 일괄 적용", () => {
  const rightClickSystem = (page, name) => page.locator(".nav-system", { hasText: name }).click({ button: "right" });

  test("System 메뉴에 항목이 있고, 확인 후에만 Plan에 반영된다", async ({ page }) => {
    await configureRegion(page, "en", { mode: "prefix", text: "EN" });
    await rightClickSystem(page, "PS2");
    await menuItem(page, "Title Prefix/Postfix 일괄 적용…").click();
    await expect(page.locator(".modal-title")).toHaveText("Title Prefix/Postfix");
    // PS2에는 FFX.iso(JP)와 MGS2.iso(USA)가 있다 - en 규칙은 MGS2.iso 하나만 바꾼다.
    await expect(page.locator(".title-affix-row")).toHaveCount(1);
    await expect(page.locator(".modal-text")).toContainText("PS2");
    await expect(page.locator(".modal-text")).toContainText("1개");

    await modalButton(page, "Plan에 추가").click();
    await expect(page.locator(".toast-msg")).toContainText("1개를 Plan에 올렸습니다");
  });
});

test.describe("Apply로 실제 반영", () => {
  test("Plan에 올린 뒤 Apply하면 목록의 제목이 바뀌고 표시가 사라진다", async ({ page }) => {
    await configureRegion(page, "jp", { mode: "prefix", text: "JP" });
    await rightClickRow(page, "Final Fantasy X");
    await menuItem(page, "Title Prefix/Postfix 적용…").click();
    await modalButton(page, "Plan에 추가").click();

    const row = page.locator(".lrow", { hasText: "Final Fantasy X" });
    await expect(row.locator(".status-mark.edit")).toBeVisible();

    await page.locator("#filter-bar .plan-actions .seg-btn", { hasText: "Apply" }).click();
    // Apply는 항상 확인 대화상자를 먼저 보여준다(추가/삭제/이동/제목 변경 요약).
    await expect(page.locator(".modal-text")).toContainText("제목 변경 1");
    await page.locator(".modal-actions .btn.primary").click();

    await expect(page.locator(".lrow", { hasText: "JP_Final Fantasy X" })).toBeVisible();
    await expect(page.locator(".lrow", { hasText: "JP_Final Fantasy X" }).locator(".status-mark.edit")).toHaveCount(0);
  });
});
