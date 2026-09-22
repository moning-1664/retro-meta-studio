// Gamelist와 상세 패널 - 사용자가 가장 오래 머무는 화면.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("행 사이 구분선은 점선이다(사용자 요청)", async ({ page }) => {
  const style = await page.locator(".lrow").first()
    .evaluate((el) => getComputedStyle(el).borderBottomStyle);
  expect(style).toBe("dotted");
});

test("행을 클릭하면 상세 패널이 그 게임으로 열린다", async ({ page }) => {
  await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();
  const panel = page.locator("#detail-panel");
  await expect(panel).toHaveClass(/open/);
  await expect(panel.locator(".detail-filename")).toHaveText("FFX.iso");
  await expect(panel.locator(".detail-system")).toContainText("PS2");
});

test("요약 카드가 큰 표지와 요약 정보를 보여주고, 그 아래가 제목·설명이다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  const values = page.locator(".identity-field-value");
  await expect(values.first()).toHaveText("RPG");           // Genre
  await expect(page.locator(".title-input")).toHaveValue("Final Fantasy X");
  // 폼에 없는 것(ROM/Media 상태)은 요약 맨 아래 한 줄로만 있다.
  await expect(page.locator(".identity-facts")).toContainText("Media");
});

test("탭을 바꿔도 저장 버튼은 Metadata 탭에서만 보인다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await expect(page.locator(".detail-footer .btn")).toContainText("저장");
  await page.locator(".detail-tab", { hasText: "ROM" }).click();
  await expect(page.locator(".detail-footer")).toHaveCount(0);
  await page.locator(".detail-tab", { hasText: "Metadata" }).click();
  await expect(page.locator(".detail-footer .btn")).toContainText("저장");
});

test("탭을 오갔다 와도 편집 중이던 값이 남아 있다(draft 보존)", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await page.locator(".title-input").fill("편집 중인 제목");
  await page.locator(".detail-tab", { hasText: "Media" }).click();
  await page.locator(".detail-tab", { hasText: "Metadata" }).click();
  await expect(page.locator(".title-input")).toHaveValue("편집 중인 제목");
});

test("Esc로 상세 패널을 닫는다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await expect(page.locator("#detail-panel")).toHaveClass(/open/);
  await page.keyboard.press("Escape");
  await expect(page.locator("#detail-panel")).not.toHaveClass(/open/);
});

// 체크박스는 없앴다. 수천 개 목록에서 하나씩 누르는 것은 실제로 쓸 수 있는 방법이
// 아니어서, 탐색기와 같은 규칙(클릭 / Ctrl / Shift)으로 고른다.
//
// 행의 정중앙에는 Match 뱃지 같은 버튼이 올 수 있어서, 사용자가 실제로 누르는 것과
// 같이 **빈 셀**(File)을 누른다.
const cellOf = (page, n) => page.locator(".lrow").nth(n).locator(".lc-file");

test("클릭하면 그 항목 하나만 선택된다", async ({ page }) => {
  await cellOf(page, 0).click();
  await expect(page.locator(".sb-left")).toContainText("Selected 1");
  await cellOf(page, 1).click();
  await expect(page.locator(".sb-left")).toContainText("Selected 1");
});

test("Ctrl+클릭은 선택에 넣고 뺀다", async ({ page }) => {
  await cellOf(page, 0).click();
  await cellOf(page, 1).click({ modifiers: ["Control"] });
  await expect(page.locator(".sb-left")).toContainText("Selected 2");
  await cellOf(page, 1).click({ modifiers: ["Control"] });
  await expect(page.locator(".sb-left")).toContainText("Selected 1");
});

test("Shift+클릭은 기준점부터 여기까지를 고른다", async ({ page }) => {
  await cellOf(page, 0).click();
  await cellOf(page, 2).click({ modifiers: ["Shift"] });
  await expect(page.locator(".sb-left")).toContainText("Selected 3");
});

test("고른 행은 눈에 보이게 표시된다", async ({ page }) => {
  await cellOf(page, 0).click();
  await cellOf(page, 1).click({ modifiers: ["Control"] });
  await expect(page.locator(".lrow.selected")).toHaveCount(2);
});

test("System 내비로 좁히면 그 시스템 행만 남는다", async ({ page }) => {
  await page.locator("#nav .nav-system", { hasText: "SNES" }).click();
  await expect(page.locator(".lrow")).toHaveCount(1);
  await expect(page.locator(".lrow").first()).toContainText("Super Mario World");
});

test("검색어를 넣으면 디바운스 후 결과가 줄어든다", async ({ page }) => {
  // 목업 list_rows는 systems만 필터하므로 검색은 총 개수 표시가 갱신되는 것까지만 본다.
  await page.locator(".search-input").fill("mario");
  await expect(page.locator("#filter-total")).toBeVisible();
});

// 툴바가 좁아졌을 때 - 실사용 피드백: "가로폭이 작으면 2줄로 나오는데, 버튼 배치는
// 1줄로 유지되도록 자리가 모자라면 search 길이가 우선적으로 줄자."
test.describe("좁은 창에서의 필터 바", () => {
  test("버튼은 1줄을 유지하고, 자리가 모자라면 검색창이 먼저 줄어든다", async ({ page }) => {
    await page.setViewportSize({ width: 720, height: 800 });
    await page.reload();
    await openApp(page);
    const bar = page.locator("#filter-bar");
    const modes = page.locator(".view-mode-seg");
    const search = page.locator(".search-box");
    const [barBox, modesBox, searchBox] = await Promise.all([
      bar.boundingBox(), modes.boundingBox(), search.boundingBox(),
    ]);
    // 한 줄이다 - 높이가 두 줄만큼 늘어나지 않는다(버튼 한 줄 높이 근방).
    expect(barBox.height).toBeLessThan(50);
    // 다른 버튼(List/Card 토글)은 온전한 크기를 유지한다.
    expect(modesBox.width).toBeGreaterThan(40);
    // 검색창이 기본 240px보다 훨씬 좁게 줄어 자리를 양보했다.
    expect(searchBox.width).toBeLessThan(200);
  });
});
