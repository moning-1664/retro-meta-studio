// Settings 화면 (settings.js + app.js).
//
// 구성은 ui/stitch-v2-redesign의 Settings를 따른다. 차이는 - 값의 주인이 app.js이고
// 백엔드(registry)에 저장되며, 아직 기능이 없는 항목은 "준비 중"으로 막혀 있다는 것.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const openSettings = async (page, section = "appearance") => {
  await page.locator(".settings-btn").click();
  await expect(page.locator(".stg-panel")).toBeVisible();
  await page.locator(`.stg-nav-item[data-section='${section}']`).click();
};
const row = (page, key) => page.locator(`.stg-row[data-key='${key}']`);

test("Navigator의 Settings 버튼으로 열리고 Esc로 닫힌다", async ({ page }) => {
  await openSettings(page);
  await expect(page.locator(".stg-nav-item")).toHaveCount(9);
  await page.keyboard.press("Escape");
  await expect(page.locator(".stg-panel")).toHaveCount(0);
});

// 좌측 하단 확인 버튼(실사용 결정) - ×만으로 닫는 것보다 또렷하다. 값은 이미
// 즉시 적용돼 있으므로(라이브 미리보기), 이 버튼이 하는 일은 아직 안 나간
// 저장을 그 자리에서 흘려보내고 닫는 것이다.
test("좌측 하단 확인 버튼으로 닫힌다", async ({ page }) => {
  await openSettings(page);
  await expect(page.locator(".stg-confirm")).toHaveText("확인");
  await page.locator(".stg-confirm").click();
  await expect(page.locator(".stg-panel")).toHaveCount(0);
});

test("확인 버튼의 글자는 가운데 정렬이다(실사용 피드백)", async ({ page }) => {
  // .btn은 기본이 왼쪽 정렬이라, min-width로 상자를 글자보다 넓게 잡으면
  // 글자가 왼쪽에 붙어 보였다.
  await openSettings(page);
  const justify = await page.locator(".stg-confirm").evaluate((el) => getComputedStyle(el).justifyContent);
  expect(justify).toBe("center");
});

test("확인을 누르면 debounce를 기다리지 않고 그 자리에서 저장한다", async ({ page }) => {
  const saved = [];
  await page.exposeFunction("__saved", (p) => saved.push(p));
  await page.evaluate(() => {
    const original = window.api.saveAppSettings;
    window.api.saveAppSettings = (p) => { window.__saved(p); return original(p); };
  });
  await openSettings(page);
  await row(page, "appearance.theme").locator("select").selectOption("sfc");
  // 저장 debounce(300ms)가 돌기 전에 바로 확인을 누른다.
  await page.locator(".stg-confirm").click();
  expect(saved.length).toBeGreaterThan(0);
  expect(saved.at(-1).appearance.theme).toBe("sfc");
});

test("테마를 바꾸면 즉시 화면에 반영되고 백엔드에 저장된다", async ({ page }) => {
  const saved = [];
  await page.exposeFunction("__saved", (p) => saved.push(p));
  await page.evaluate(() => {
    const original = window.api.saveAppSettings;
    window.api.saveAppSettings = (p) => { window.__saved(p); return original(p); };
  });
  await openSettings(page);
  await row(page, "appearance.theme").locator("select").selectOption("sfc");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "sfc");
  await expect.poll(() => saved.length, { timeout: 3000 }).toBeGreaterThan(0);
  expect(saved.at(-1).appearance.theme).toBe("sfc");
});

test("밀도를 Normal로 바꾸면 목록 줄이 높아진다", async ({ page }) => {
  const height = () => page.locator(".lrow").first().evaluate((el) => el.getBoundingClientRect().height);
  expect(await height()).toBe(26);
  await openSettings(page);
  await row(page, "appearance.density").locator("select").selectOption("normal");
  await expect.poll(height).toBe(30);
});

test("Ctrl + 휠로 UI 크기를 바꾼다", async ({ page }) => {
  const scale = () => page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--font-scale").trim());
  await page.locator("#list-scroll").hover();
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -100);
  await page.keyboard.up("Control");
  await expect.poll(scale).toBe("1.05");
  await expect(page.locator("#toast")).toContainText("105%");
});

test("Shift + 휠은 UI 크기를 바꾸지 않는다(가로 스크롤 키)", async ({ page }) => {
  await page.locator("#list-scroll").hover();
  await page.keyboard.down("Shift");
  await page.mouse.wheel(0, -100);
  await page.keyboard.up("Shift");
  const scale = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--font-scale").trim());
  expect(["", "1"]).toContain(scale);
});

test("아직 기능이 없는 항목은 '준비 중'이고 조작할 수 없다", async ({ page }) => {
  await openSettings(page, "general");
  const startup = row(page, "general.startup");
  await expect(startup).toHaveClass(/soon/);
  await expect(startup.locator(".stg-soon")).toHaveText("준비 중");
  await expect(startup.locator("select")).toBeDisabled();
});

test("Language는 이제 준비 중이 아니고 다섯 언어를 고를 수 있다", async ({ page }) => {
  await openSettings(page, "general");
  const language = row(page, "general.language");
  await expect(language).not.toHaveClass(/soon/);
  await expect(language.locator("select")).toBeEnabled();
  await expect(language.locator("select option")).toHaveCount(5);
});

test("화면 설정 초기화는 테마를 기본값으로 되돌린다", async ({ page }) => {
  await openSettings(page);
  await row(page, "appearance.theme").locator("select").selectOption("nes");
  await page.locator(".stg-nav-item[data-section='advanced']").click();
  await row(page, "advanced.reset").locator("button").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "stitch");
});
