// GameList 다중선택 - 마우스 드래그 범위선택 + 화면 깜빡임 없는 갱신 (단위 GameList 개선).
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toBeVisible();
});

test("행을 누른 채 다른 행까지 드래그하면 그 사이 전체가 선택된다", async ({ page }) => {
  const rows = page.locator(".grid-data-row[data-rom-key]");
  const first = rows.nth(0);
  const third = rows.nth(2);
  const firstBox = await first.boundingBox();
  const thirdBox = await third.boundingBox();

  await page.mouse.move(firstBox.x + 10, firstBox.y + firstBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(thirdBox.x + 10, thirdBox.y + thirdBox.height / 2, { steps: 5 });
  await page.mouse.up();

  await expect(page.locator(".grid-data-row.multi-selected")).toHaveCount(3);
});

test("드래그 없이 단순 클릭이면 기존처럼 상세 패널이 열린다", async ({ page }) => {
  await page.locator('[data-rom-key="snes|Super Mario World.zip"]').click();
  await expect(page.locator(".grid-data-row.selected")).toHaveCount(1);
  await expect(page.locator(".grid-data-row.multi-selected")).toHaveCount(0);
});

test("Shift만 누른 채 클릭하면 이전 선택부터 범위 전체가 선택된다 (Ctrl 불필요)", async ({ page }) => {
  const rows = page.locator(".grid-data-row[data-rom-key]");
  await rows.nth(0).click();
  await rows.nth(2).click({ modifiers: ["Shift"] });
  await expect(page.locator(".grid-data-row.multi-selected")).toHaveCount(3);
});
