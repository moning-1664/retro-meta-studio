/**
 * Chromium 헤더를 펼쳐도 무너지면 안 되는 두 가지.
 *
 * 둘 다 실사용 피드백에서 나왔다. Hero 배경을 넣으면서 `.cheader` 자체를 키웠더니
 * (1) 헤더 줄이 커져서 옆의 Detail 패널이 통째로 아래로 밀렸고, (2) Navigator의
 * SYSTEMS 띠와 높이가 어긋나 구분선이 한 줄로 이어지지 않았다.
 *
 * 그래서 규칙은 이렇다 - **띠의 높이는 절대 변하지 않고(--header-row-h), 펼친
 * 내용은 목록 기둥 안(#collection-expanded)에 그린다.** 이 테스트가 그 규칙을 잡아둔다.
 */
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

const box = async (page, sel) => (await page.locator(sel).boundingBox()) || {};
const expand = (page) => page.locator(".cheader-right .icon-btn").last().click();

test.beforeEach(async ({ page }) => {
  await openApp(page);
  await page.locator(".nav-system", { hasText: "PS2" }).first().click();
});

test("헤더를 펼쳐도 Detail 패널은 제자리를 지킨다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  const before = await box(page, "#detail-panel");
  await expand(page);
  await expect(page.locator("#collection-expanded .cheader-expanded")).toBeVisible();
  expect((await box(page, "#detail-panel")).y).toBe(before.y);
});

test("헤더 띠 높이는 변하지 않는다 - Navigator SYSTEMS 띠와 맞춰야 한다", async ({ page }) => {
  const before = await box(page, ".cheader");
  const eyebrow = await box(page, ".nav-eyebrow");
  // 띠의 아래 경계선과 Navigator 띠의 시작이 1px(경계선) 안에서 만난다.
  expect(Math.abs(before.y + before.height - eyebrow.y)).toBeLessThanOrEqual(1);

  await expand(page);
  expect((await box(page, ".cheader")).height).toBe(before.height);
  expect((await box(page, ".nav-eyebrow")).y).toBe(eyebrow.y);
});

test("펼친 카드는 제목을 다시 쓰지 않는다 - 바로 위 띠에 이미 있다", async ({ page }) => {
  await expand(page);
  const card = page.locator("#collection-expanded");
  await expect(card).not.toContainText("PS2ES-DE");        // 제목 블록이 없다
  await expect(card.locator(".cheader-name")).toHaveCount(0);
  // 대신 숫자를 담는다.
  await expect(card).toContainText("Metadata 없음");
  await expect(card).toContainText("Media 없음");
});

test("접으면 카드가 사라진다", async ({ page }) => {
  await expand(page);
  await expect(page.locator("#collection-expanded .cheader-expanded")).toBeVisible();
  await expand(page);
  await expect(page.locator("#collection-expanded .cheader-expanded")).toHaveCount(0);
});
