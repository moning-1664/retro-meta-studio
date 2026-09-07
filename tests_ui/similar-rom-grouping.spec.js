// 유사롬 묶어보기 토글 회귀 테스트 (단위 8). mock 모드는 "snes" 시스템에
// Zelda.zip / Zelda (Alt).zip이 이미 한 그룹으로 묶여있고 대표가 Zelda.zip인 상태로
// 시드되어 있다 (api-client.js의 mock.similarGroups 참고).
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator("#sidebar .nav-item").first()).toBeVisible();
  // 시스템 드롭다운에서 snes를 선택해야 '유사롬 묶기' 토글이 노출된다 (all에서는 숨김).
  await page.locator(".filter-bar .dropdown > button, #filter-bar .dropdown > button").first().click();
});

test.describe("유사롬 묶어보기", () => {
  test("시스템을 선택하면 유사롬 묶기 토글이 나타난다", async ({ page }) => {
    await page.locator("#filter-bar .dropdown-menu").getByRole("button", { name: "snes (4)" }).click();
    await expect(page.locator(".similar-group-toggle", { hasText: "유사롬 묶기" })).toBeVisible();
  });

  test("토글을 켜면 그룹의 비대표 멤버가 목록에서 사라지고 대표에 개수 뱃지가 붙는다", async ({ page }) => {
    await page.locator("#filter-bar .dropdown-menu").getByRole("button", { name: "snes (4)" }).click();
    await expect(page.locator('[data-rom-key="snes|Zelda (Alt).zip"]')).toBeVisible();

    await page.locator(".similar-group-toggle", { hasText: "유사롬 묶기" }).locator("input[type=checkbox]").check();

    await expect(page.locator('[data-rom-key="snes|Zelda.zip"]')).toBeVisible();
    await expect(page.locator('[data-rom-key="snes|Zelda (Alt).zip"]')).toHaveCount(0);
    await expect(page.locator('[data-rom-key="snes|Zelda.zip"] .similar-group-badge')).toContainText("+1");

    // 그룹과 무관한 게임은 그대로 보인다.
    await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toBeVisible();
  });

  test("토글을 끄면 숨겼던 멤버가 다시 보인다", async ({ page }) => {
    await page.locator("#filter-bar .dropdown-menu").getByRole("button", { name: "snes (4)" }).click();
    const toggle = page.locator(".similar-group-toggle", { hasText: "유사롬 묶기" }).locator("input[type=checkbox]");
    await toggle.check();
    await expect(page.locator('[data-rom-key="snes|Zelda (Alt).zip"]')).toHaveCount(0);
    await toggle.uncheck();
    await expect(page.locator('[data-rom-key="snes|Zelda (Alt).zip"]')).toBeVisible();
  });

  test("결과 보기 모달에서 대표를 바꾸면 묶어보기 목록에도 반영된다", async ({ page }) => {
    await page.locator("#filter-bar .dropdown-menu").getByRole("button", { name: "snes (4)" }).click();
    await page.locator(".similar-group-toggle", { hasText: "유사롬 묶기" }).locator("input[type=checkbox]").check();
    await expect(page.locator('[data-rom-key="snes|Zelda.zip"]')).toBeVisible();

    await page.getByRole("button", { name: "결과 보기" }).click();
    const modal = page.locator(".modal-box", { hasText: "유사롬 결과" });
    await expect(modal).toBeVisible();
    // 아직 대표가 아닌 멤버(Zelda (Alt).zip)의 별표를 눌러 대표로 바꾼다.
    const altRow = modal.locator(".similar-group-member", { hasText: "Zelda (Alt).zip" });
    await altRow.locator(".similar-rep-btn").click();
    await modal.getByRole("button", { name: "닫기" }).click();

    await expect(page.locator('[data-rom-key="snes|Zelda (Alt).zip"]')).toBeVisible();
    await expect(page.locator('[data-rom-key="snes|Zelda.zip"]')).toHaveCount(0);
  });
});
