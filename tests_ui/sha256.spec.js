// SHA256 표시 회귀 테스트 (2026-09-02 리뷰 반영, 이후 위치 이동 반영) - ROM이
// ArchiveDB로 처음 복사될 때 캐시된 SHA256을 상세 패널에 보여준다. 캐시가
// 없으면(구버전에서 이미 들어온 ROM 등) "계산 안 됨"으로 표시하고,
// GameListSet(Local) 미리보기에서는 애초에 캐시할 곳이 없으므로 필드 자체를
// 숨긴다.
//
// [SHA256 위치 이동] 예전엔 identity-card 위쪽 별도 줄(.identity-sha256)에
// 전체 64자를 그대로 보여줬다 - 이제 하단 field-grid의 Players 옆 칸
// (.sha256-field)으로 옮기고, 화면에는 앞 16자만 잘라서 보여준다(전체 값은
// title 속성/detailState.sha256에 그대로 유지됨).
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator("#sidebar .nav-item").first()).toBeVisible();
  await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toBeVisible();
});

test("ArchiveDB에서 SHA256이 캐시된 롬은 Player 옆 칸에 짧게 잘린 해시 값을 보여준다", async ({ page }) => {
  await page.locator('[data-rom-key="snes|Super Mario World.zip"]').click();
  await page.keyboard.press("Enter");

  // 상단(identity-card)에는 더 이상 SHA256이 중복 표시되지 않아야 한다.
  await expect(page.locator(".identity-sha256")).toHaveCount(0);

  const sha256Field = page.locator(".sha256-field");
  await expect(sha256Field).toBeVisible();
  const valueEl = sha256Field.locator(".sha256-field-value");
  // 화면 표시는 앞 16자 + "…"로 잘려야 한다 - 전체 64자를 그대로 보여주면 안 됨.
  await expect(valueEl).toHaveText("3ab7f1c9d4e2b6a0…");
  // 전체 64자 값은 title(hover)에 그대로 남아있어야 한다.
  await expect(valueEl).toHaveAttribute(
    "title",
    "3ab7f1c9d4e2b6a05f8c1d9e2b4a6c8f0d1e3b5a7c9f1d3e5b7a9c1d3e5f7a9b"
  );
});

test("캐시가 없는 롬은 '계산 안 됨'으로 표시한다", async ({ page }) => {
  await page.locator('[data-rom-key="snes|Zelda.zip"]').click();
  await page.keyboard.press("Enter");
  const sha256Field = page.locator(".sha256-field");
  await expect(sha256Field).toBeVisible();
  await expect(sha256Field.locator(".sha256-field-value")).toHaveText("계산 안 됨");
});

test("GameListSet(Local) 미리보기에서는 SHA256 필드 자체가 안 보인다", async ({ page }) => {
  await page.locator("#sidebar").getByRole("button", { name: "Local 1", exact: true }).click();
  await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toBeVisible();
  await page.locator('[data-rom-key="snes|Super Mario World.zip"]').click();
  await page.keyboard.press("Enter");
  await expect(page.locator(".identity-card")).toBeVisible();
  await expect(page.locator(".identity-sha256")).toHaveCount(0);
  await expect(page.locator(".sha256-field")).toHaveCount(0);
});
