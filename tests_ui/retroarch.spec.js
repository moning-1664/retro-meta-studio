// RetroArch 실행 - RetroGameManager feature/retroarch-launch의 흐름을 이 앱 구조로 옮겼다.
// 목업 System: ps2(실행 검증 안 됨) / snes(SMW.sfc) / gba. 실제 프로세스 실행은 Python 테스트 몫이다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const row = (page, file) => page.locator(".lrow", { hasText: file });
const openSettingsEmulator = async (page) => {
  await page.locator(".nav-top .icon-btn[title='Settings']").click();
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
  test("검증 안 된 System(PS2)은 Detail 실행 버튼이 꺼져 있다", async ({ page }) => {
    await row(page, "FFX.iso").locator(".lc-file").click();
    await expect(page.locator(".detail-launch")).toBeDisabled();
    await expect(page.locator(".detail-launch")).toHaveAttribute("title", /검증되지 않았습니다/);
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

  test("이 게임에만 Core를 지정할 수 있고 해제도 된다", async ({ page }) => {
    await configure(page);
    await row(page, "SMW.sfc").locator(".lc-file").click();
    await page.locator(".detail-core").click();
    await page.locator(".core-select").selectOption("mgba_libretro.dll");
    await page.locator(".core-scope-game").check();
    await page.locator(".core-save").click();
    let s = await page.evaluate(async () => (await window.api.retroarchSettings()).data);
    expect(s.gameCores["snes/SMW.sfc"]).toBe("mgba_libretro.dll");
    expect(s.systemCores.snes).toBeUndefined();

    await page.locator(".detail-core").click();
    await expect(page.locator(".core-scope-game")).toBeChecked();
    await modalButton(page, "게임 지정 해제").click();
    s = await page.evaluate(async () => (await window.api.retroarchSettings()).data);
    expect(s.gameCores["snes/SMW.sfc"]).toBeUndefined();
  });

  test("행을 더블클릭하면 실행한다", async ({ page }) => {
    await configure(page);
    await page.evaluate(() => window.api.setSystemCore("snes", "snes9x_libretro.dll"));
    await spyLaunch(page);
    await row(page, "SMW.sfc").locator(".lc-file").dblclick();
    await expect(page.locator(".toast-msg")).toHaveText("RetroArch 실행을 요청했습니다.");
    expect(await page.evaluate(() => window.__launched)).toEqual([3]);
  });

  test("검증 안 된 System 행은 더블클릭해도 실행하지 않고 이유를 알린다", async ({ page }) => {
    await spyLaunch(page);
    await row(page, "FFX.iso").locator(".lc-file").dblclick();
    await expect(page.locator(".toast-msg")).toContainText("검증되지 않았습니다");
    expect(await page.evaluate(() => window.__launched)).toEqual([]);
  });

  test("행 우클릭 메뉴에서도 실행과 Core 선택을 한다", async ({ page }) => {
    await row(page, "SMW.sfc").click({ button: "right" });
    await expect(page.locator(".ctx-menu .ctx-item", { hasText: "RetroArch로 실행" })).toBeEnabled();
    await expect(page.locator(".ctx-menu .ctx-item", { hasText: "RetroArch Core 선택" })).toBeEnabled();
    await page.keyboard.press("Escape");
    await row(page, "FFX.iso").click({ button: "right" });
    await expect(page.locator(".ctx-menu .ctx-item", { hasText: "RetroArch로 실행" })).toBeDisabled();
  });
});
