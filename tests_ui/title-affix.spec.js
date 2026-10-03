// Title Prefix/Postfix 일괄 적용(사용자 결정) - Settings의 지역별 규칙, Gamelist/System 우클릭
// 메뉴, 미리보기 -> Plan -> Apply. 실제 계산(지역 분류/기존 장식 떼기/디스크 표시 보존)은
// tests/test_title_affix.py와 tests/test_title_affix_plan.py가 촘촘히 검증하고, 여기서는
// Settings 화면과 메뉴 흐름만 본다.
//
// 구역은 **파일명의 지역 태그**로 정한다(사용자 결정) - 목업 기본 파일명에는 태그가 없으므로
// __RMS_MOCK_FILES로 붙여 준다: FFX(K, 한국) / MGS2(U, 영어권) / SMW(태그 없음 = 미분류).
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

const TAGGED_FILES = { 1: "FFX (K).iso", 2: "MGS2 (U).iso", 3: "SMW.sfc" };

const REGION_INDEX = { kr: 0, en: 1, jp: 2, eu: 3, global: 4 };

const openMetadataSettings = async (page) => {
  await page.locator(".settings-btn").click();
  await page.locator(".stg-nav-item[data-section='tags']").click();
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

test.beforeEach(async ({ page }) => {
  await page.addInitScript((files) => { window.__RMS_MOCK_FILES = files; }, TAGGED_FILES);
  await openApp(page);
});

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

    // 세 번의 조작(켜기/방식/텍스트) 모두 그 구역의 완전한 모양으로 저장돼야 한다 -
    // 부분만 보내면 나머지가 지워진다(섹션 한 단계 깊이 병합).
    await expect.poll(() => page.evaluate(() => window.__saved.reduce((acc, p) =>
      ({ ...acc, ...p.titleAffix }), {}).jp)).toEqual({ enabled: true, mode: "postfix", text: "일본" });
  });
});

test.describe("Gamelist 우클릭 - 선택한 게임에 적용", () => {
  test("바뀔 게 없으면 메뉴 항목 자체가 흐리게 나온다 - 눌러도 아무 일도 없다", async ({ page }) => {
    await rightClickRow(page, "Final Fantasy X");   // FFX (K).iso, 아무 구역도 안 켜짐
    const item = menuItem(page, "제목 앞·뒤 태그 적용…");
    await expect(item).toHaveCount(0);
  });

  test("미리보기에 예전/새 제목을 보여주고, 확인해야 Plan에 올라간다", async ({ page }) => {
    await configureRegion(page, "kr", { mode: "prefix", text: "KR" });
    await rightClickRow(page, "Final Fantasy X");
    await menuItem(page, "제목 앞·뒤 태그 적용…").click();

    await expect(page.locator(".modal-title")).toHaveText("Title Prefix/Postfix");
    await expect(page.locator(".title-affix-old")).toHaveText("Final Fantasy X");
    await expect(page.locator(".title-affix-new")).toHaveText("KR_Final Fantasy X");

    await modalButton(page, "취소").click();
    await expect(page.locator(".modal-title")).toHaveCount(0);
    // 취소했으므로 아직 Plan에 없다 - 목록에 표시 마크가 없다.
    await expect(page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".status-mark.edit")).toHaveCount(0);

    await rightClickRow(page, "Final Fantasy X");
    await menuItem(page, "제목 앞·뒤 태그 적용…").click();
    await modalButton(page, "적용").click();
    await expect(page.locator(".toast-msg")).toContainText("제목 변경");
    await expect(page.locator(".lrow", { hasText: "KR_Final Fantasy X" })).toBeVisible();
  });

  test("여러 개를 선택하면 그 개수만큼 대상이 되고 메뉴에 개수가 보인다", async ({ page }) => {
    await configureRegion(page, "en", { mode: "prefix", text: "EN" });
    await page.locator(".lrow").nth(0).click();
    await page.locator(".lrow").nth(1).click({ modifiers: ["Control"] });
    await page.locator(".lrow").nth(0).click({ button: "right" });
    await expect(menuItem(page, "제목 앞·뒤 태그 적용… (2개)")).toBeVisible();
    await menuItem(page, "제목 앞·뒤 태그 적용… (2개)").click();
    // MGS2 (U).iso만 en 규칙에 걸리고 FFX (K).iso는 안 걸린다.
    await expect(page.locator(".title-affix-row")).toHaveCount(1);
    await expect(page.locator(".title-affix-new")).toHaveText("EN_Metal Gear Solid 2");
  });
});

test.describe("System 우클릭 - 전체 일괄 적용", () => {
  const rightClickSystem = (page, name) => page.locator(".nav-system", { hasText: name }).click({ button: "right" });

  test("System 메뉴에 항목이 있고, 확인 후에만 Plan에 반영된다", async ({ page }) => {
    await configureRegion(page, "en", { mode: "prefix", text: "EN" });
    await rightClickSystem(page, "PS2");
    await menuItem(page, "언어 태그 적용…").click();
    await expect(page.locator(".modal-title")).toHaveText("Title Prefix/Postfix");
    // PS2에는 FFX (K).iso와 MGS2 (U).iso가 있다 - en 규칙은 MGS2 하나만 바꾼다.
    await expect(page.locator(".title-affix-row")).toHaveCount(1);
    await expect(page.locator(".modal-text")).toContainText("PS2");
    await expect(page.locator(".modal-text")).toContainText("1개");

    await modalButton(page, "적용").click();
    await expect(page.locator(".toast-msg")).toContainText("제목 변경");
  });

  test("아무 구역도 안 켜져 있으면 System 메뉴 항목도 흐리게 나온다", async ({ page }) => {
    await rightClickSystem(page, "PS2");
    await expect(menuItem(page, "언어 태그 적용…")).toBeDisabled();
  });

  test("게임이 없는 System은 API를 부르지 않고 바로 흐리게 나온다", async ({ page }) => {
    await configureRegion(page, "en", { mode: "prefix", text: "EN" });
    await page.evaluate(() => {
      window.__previewCalls = 0;
      const original = window.api.titleAffixPreview;
      window.api.titleAffixPreview = (...a) => { window.__previewCalls += 1; return original(...a); };
    });
    await rightClickSystem(page, "GBA");   // 목업에서 게임 0개
    await expect(menuItem(page, "언어 태그 적용…")).toBeDisabled();
    expect(await page.evaluate(() => window.__previewCalls)).toBe(0);
  });
});

test.describe("태그가 없는 파일 - 미분류(사용자 결정)", () => {
  test("파일명에 지역 태그가 없으면 모든 구역을 켜도 대상이 아니다", async ({ page }) => {
    await configureRegion(page, "global", { mode: "postfix", text: "WORLD" });
    await rightClickRow(page, "Super Mario World");   // SMW.sfc - 태그 없음
    await expect(menuItem(page, "제목 앞·뒤 태그 적용…")).toHaveCount(0);
  });
});

test.describe("공유 계산 모듈(gui_web/title-affix.js)", () => {
  // 실제 계산은 app/title_affix.py의 단위 테스트가 촘촘히 본다 - 여기서는 화면(목업,
  // 메뉴 비활성화 판단)이 쓰는 JS 이식이 같은 결과를 내는지만 스팟 체크한다.
  test("단어 없는 디스크 표시(2/2)를 지역 장식과 분리해서 보존한다", async ({ page }) => {
    const r = await page.evaluate(() => window.RMSTitleAffix.compute(
      "[EU] Chrono Trigger (2/2)", "Chrono (K) (2 of 2).iso",
      { kr: { enabled: true, mode: "prefix", text: "KR" } }));
    expect(r).toEqual({ oldTitle: "[EU] Chrono Trigger (2/2)", newTitle: "KR_Chrono Trigger (Disk 2 of 2)",
      changed: true, regionBucket: "kr", regionBuckets: ["kr"], diskMarker: "(Disk 2 of 2)" });
  });

  test("파일명의 태그로 구역을 정하고, 태그가 없으면 미분류다", async ({ page }) => {
    const seen = await page.evaluate(() => [
      window.RMSTitleAffix.classifyRegion("Game (K).iso"),
      window.RMSTitleAffix.classifyRegion("Game_k.gba"),
      window.RMSTitleAffix.classifyRegion("global_Game.bin"),
      window.RMSTitleAffix.classifyRegion("Chrono Trigger.sfc"),
      window.RMSTitleAffix.classifyRegion("Global Defense.iso"),
    ]);
    expect(seen).toEqual(["kr", "kr", "global", null, null]);
  });
});

test.describe("Apply로 실제 반영", () => {
  test("확인하면 제목이 직접 반영되고 별도 Apply 버튼은 없다", async ({ page }) => {
    await configureRegion(page, "kr", { mode: "prefix", text: "KR" });
    await rightClickRow(page, "Final Fantasy X");
    await menuItem(page, "제목 앞·뒤 태그 적용…").click();
    await modalButton(page, "적용").click();

    await expect(page.locator(".lrow", { hasText: "KR_Final Fantasy X" })).toBeVisible();
    await expect(page.locator(".lrow", { hasText: "KR_Final Fantasy X" }).locator(".status-mark.edit")).toHaveCount(0);
  });
});

// 화면의 계산(RMSTitleAffix)은 app/title_affix.py와 같은 결과를 내야 한다 - 메뉴 활성 판단과 목업이 쓴다.
test.describe("공백과 여러 지역 (화면 쪽 계산이 Python과 같다)", () => {
  const compute = (page, title, filename, config) =>
    page.evaluate(([t, f, c]) => window.RMSTitleAffix.compute(t, f, c), [title, filename, config]);
  const on = (mode, text) => ({ enabled: true, mode, text });

  test("문구 앞뒤 공백을 지우지 않는다", async ({ page }) => {
    await openApp(page);
    expect((await compute(page, "Game", "Game (KR).iso", { kr: on("postfix", " (KR)") })).newTitle).toBe("Game (KR)");
    expect((await compute(page, "Game", "Game (KR).iso", { kr: on("prefix", "(KR) ") })).newTitle).toBe("(KR) Game");
  });

  test("(Japan, Europe)는 두 지역이고 같은 괄호는 하나로 합쳐진다", async ({ page }) => {
    await openApp(page);
    const cfg = { jp: on("postfix", " [JP]"), eu: on("postfix", " [EU]") };
    const r = await compute(page, "Zelda", "Zelda (Japan, Europe).zip", cfg);
    expect(r.regionBuckets).toEqual(["jp", "eu"]);
    expect(r.newTitle).toBe("Zelda [JP,EU]");
  });

  test("언어 목록 (En,Fr,De)는 지역이 아니다", async ({ page }) => {
    await openApp(page);
    const r = await compute(page, "Game", "Game (En,Fr,De).zip", { en: on("prefix", "EN_") });
    expect(r.regionBuckets).toEqual([]);
    expect(r.changed).toBe(false);
  });
});
