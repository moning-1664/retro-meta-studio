// RetroArch 실행 - RetroGameManager feature/retroarch-launch의 흐름을 이 앱 구조로 옮겼다.
// 목업 System: ps2(실행 검증 안 됨) / snes(SMW.sfc) / gba. 실제 프로세스 실행은 Python 테스트 몫이다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const row = (page, file) => page.locator(".lrow", { hasText: file });
const openSettingsEmulator = async (page) => {
  await page.locator(".settings-btn").click();
  await page.locator(".stg-nav-item[data-section='emulator']").click();
  await expect(page.locator(".stg-emulator .stg-row[data-key='emulator.retroarchPath']")).toBeVisible();
};
const configure = (page) => page.evaluate(() => window.api.setRetroarchPaths("C:\\RetroArch\\retroarch.exe", "C:\\RetroArch\\cores"));
const spyLaunch = (page) => page.evaluate(() => {
  window.__launched = [];
  const original = window.api.launchGame;
  window.api.launchGame = (id, uid) => { window.__launched.push(uid); return original(id, uid); };
});

test.describe("Settings > Emulator", () => {
  test("찾아보기로 실행 파일을 고르면 Core 폴더도 채워지고 System별 Core를 고를 수 있다", async ({ page }) => {
    await openSettingsEmulator(page);
    await page.locator(".stg-row[data-key='emulator.retroarchPath'] button").click();
    await expect(page.locator(".stg-row[data-key='emulator.coresDir'] input")).toHaveValue("C:\\RetroArch\\cores");
    const snes = page.locator(".stg-core-row[data-system='snes'] select");
    await expect(snes).toBeEnabled();
    await snes.selectOption("snes9x_libretro.dll");
    await expect.poll(() => page.evaluate(async () => (await window.api.retroarchSettings()).data.systemCores.snes))
      .toBe("snes9x_libretro.dll");
  });

  test("실행 검증 안 된 System은 표시된다", async ({ page }) => {
    await openSettingsEmulator(page);
    await expect(page.locator(".stg-core-row[data-system='ps2']")).toHaveClass(/unverified/);
    await expect(page.locator(".stg-core-row[data-system='snes']")).not.toHaveClass(/unverified/);
  });

  test("기본 Core 자동 채우기", async ({ page }) => {
    await configure(page);
    await openSettingsEmulator(page);
    await page.locator(".stg-core-fill").click();
    await expect(page.locator(".stg-core-row[data-system='snes'] select")).toHaveValue("snes9x_libretro.dll");
    await expect(page.locator(".stg-core-row[data-system='gba'] select")).toHaveValue("mgba_libretro.dll");
  });
});

test.describe("실행", () => {
  test("검증 안 된 System도 ROM이 있으면 실행 버튼을 제공한다", async ({ page }) => {
    await row(page, "FFX.iso").locator(".lc-file").click();
    await expect(page.locator(".detail-launch")).toBeEnabled();
  });

  test("RetroArch 경로가 없으면 안내하고 Settings를 연다", async ({ page }) => {
    await row(page, "SMW.sfc").locator(".lc-file").click();
    await page.locator(".detail-launch").click();
    await expect(page.locator(".toast-msg")).toContainText("RetroArch 경로를 지정");
    await expect(page.locator(".stg-emulator")).toBeVisible();
  });

  test("Core가 없으면 선택 창이 뜨고, 저장하면 이어서 실행한다", async ({ page }) => {
    await configure(page);
    await spyLaunch(page);
    await row(page, "SMW.sfc").locator(".lc-file").click();
    await page.locator(".detail-launch").click();
    await expect(page.locator(".core-reason")).toContainText("Core가 정해지지 않았습니다");
    await page.locator(".core-select").selectOption("snes9x_libretro.dll");
    await page.locator(".core-save").click();
    await expect(page.locator(".toast-msg")).toHaveText("RetroArch 실행을 요청했습니다.");
    await expect.poll(() => page.evaluate(() => window.__launched.length)).toBe(2);
    expect(await page.evaluate(async () => (await window.api.retroarchSettings()).data.systemCores.snes)).toBe("snes9x_libretro.dll");
  });

  test("Core 선택은 ROM 탭에 있고, 이 게임에만 지정하거나 해제한다", async ({ page }) => {
    await configure(page);
    await row(page, "SMW.sfc").locator(".lc-file").click();
    await expect(page.locator(".detail-core")).toHaveCount(0);   // Detail 머리의 옵션 버튼은 없앴다
    await page.locator(".detail-tab", { hasText: "ROM" }).click();
    const core = page.locator(".rom-core");
    await core.locator(".core-select").selectOption("mgba_libretro.dll");
    await core.locator(".core-scope-game").check();
    await core.locator(".core-save").click();
    await expect(page.locator(".toast-msg")).toHaveText("이 게임의 Core를 지정했습니다.");
    const settings = () => page.evaluate(async () => (await window.api.retroarchSettings()).data);
    let s = await settings();
    expect(s.gameCores["snes/SMW.sfc"]).toBe("mgba_libretro.dll");
    expect(s.systemCores.snes).toBeUndefined();

    await expect(core.locator(".core-scope-game")).toBeChecked();
    await core.locator(".core-clear").click();
    await expect(core.locator(".core-clear")).toHaveCount(0);
    s = await settings();
    expect(s.gameCores["snes/SMW.sfc"]).toBeUndefined();
  });

  test("검증 안 된 System도 Core를 선택할 수 있고 경고를 남긴다", async ({ page }) => {
    await configure(page);
    await row(page, "FFX.iso").locator(".lc-file").click();
    await page.locator(".detail-tab", { hasText: "ROM" }).click();
    await expect(page.locator(".rom-core")).toContainText("검증되지 않았습니다");
    await expect(page.locator(".rom-core .core-select")).toBeVisible();
  });

  test("행을 더블클릭하면 실행한다", async ({ page }) => {
    await configure(page);
    await page.evaluate(() => window.api.setSystemCore("snes", "snes9x_libretro.dll"));
    await spyLaunch(page);
    await row(page, "SMW.sfc").locator(".lc-file").dblclick();
    await expect(page.locator(".toast-msg")).toHaveText("RetroArch 실행을 요청했습니다.");
    expect(await page.evaluate(() => window.__launched)).toEqual([3]);
  });

  test("검증 안 된 System도 실행을 요청하고 설정 누락을 알린다", async ({ page }) => {
    await spyLaunch(page);
    await row(page, "FFX.iso").locator(".lc-file").dblclick();
    await expect(page.locator(".toast-msg")).toContainText("RetroArch 경로를 지정");
    expect(await page.evaluate(() => window.__launched)).toEqual([1]);
  });

  test("행 우클릭 메뉴에는 실행만 남기고 Core 선택은 제거했다", async ({ page }) => {
    await row(page, "SMW.sfc").click({ button: "right" });
    await expect(page.locator(".ctx-menu .ctx-item", { hasText: "RetroArch로 실행" })).toBeEnabled();
    await expect(page.locator(".ctx-menu .ctx-item", { hasText: "RetroArch Core 선택" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await row(page, "FFX.iso").click({ button: "right" });
    await expect(page.locator(".ctx-menu .ctx-item", { hasText: "RetroArch로 실행" })).toBeEnabled();
  });
});
