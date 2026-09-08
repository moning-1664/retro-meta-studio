// Match 후보 UI (스펙 §45-49).
//
// 이 화면에서 가장 중요한 것은 "무엇이 일어나는가"가 아니라 **무엇이 일어나지 않는가**다:
// 후보가 있어도 자동으로는 절대 붙지 않고, 사용자가 고르고 Apply를 눌러야 한다(§49).
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("후보가 있는 행에만 [n] 뱃지가 붙는다", async ({ page }) => {
  const badge = page.locator(".match-badge");
  await expect(badge).toHaveCount(1);
  await expect(badge).toHaveText("[2]");
  // 뱃지가 붙은 행은 목업이 지정한 romUid 2번(MGS2)이다.
  await expect(page.locator(".lrow", { has: badge })).toContainText("Metal Gear Solid 2");
});

test("뱃지를 눌러도 상세 패널이 열리지 않고 후보 목록만 뜬다", async ({ page }) => {
  await page.locator(".match-badge").click();
  await expect(page.locator(".modal-title")).toHaveText("Possible Matches");
  // 행 클릭으로 오해되어 상세 패널까지 열리면 안 된다(뱃지가 stopPropagation 한다).
  await expect(page.locator("#detail-panel")).not.toHaveClass(/open/);
});

test("후보 목록이 티어와 점수를 함께 보여준다", async ({ page }) => {
  await page.locator(".match-badge").click();
  const options = page.locator(".match-option");
  await expect(options).toHaveCount(2);
  await expect(options.nth(0)).toContainText("이름 일치");
  await expect(options.nth(0)).toContainText("85%");
  await expect(options.nth(1)).toContainText("유사");
  await expect(page.locator(".match-source")).toContainText("Metal Gear Solid 2");
});

test("아무것도 고르지 않으면 Apply Match를 누를 수 없다", async ({ page }) => {
  await page.locator(".match-badge").click();
  const apply = page.locator(".modal-actions .btn", { hasText: "Apply Match" });
  await expect(apply).toBeDisabled();
  await page.locator(".match-option").first().click();
  await expect(apply).toBeEnabled();
});

test("고르고 Apply하면 확정되고 그 행의 뱃지가 사라진다", async ({ page }) => {
  await page.locator(".match-badge").click();
  await page.locator(".match-option").first().click();
  await page.locator(".modal-actions .btn", { hasText: "Apply Match" }).click();

  await expect(page.locator("#toast")).toContainText("Match를 확정했습니다");
  await expect(page.locator(".match-badge")).toHaveCount(0);
});

test("Cancel은 아무것도 남기지 않는다", async ({ page }) => {
  await page.locator(".match-badge").click();
  await page.locator(".match-option").first().click();
  await page.locator(".modal-actions .btn", { hasText: "Cancel" }).click();
  await expect(page.locator(".modal-title")).toHaveCount(0);
  await expect(page.locator(".match-badge")).toHaveCount(1);
});

test("확정한 뒤 목록을 다시 그리면 Match 해제가 나타난다", async ({ page }) => {
  await page.locator(".match-badge").click();
  await page.locator(".match-option").first().click();
  await page.locator(".modal-actions .btn", { hasText: "Apply Match" }).click();
  await expect(page.locator(".match-badge")).toHaveCount(0);

  // 정렬을 바꾸면 목록을 다시 불러오고 뱃지 개수도 다시 계산된다.
  await page.locator(".mini-select").selectOption("filename");
  await expect(page.locator(".match-badge")).toHaveCount(1);

  await page.locator(".match-badge").click();
  await expect(page.locator(".modal-actions .btn.danger", { hasText: "Match 해제" })).toBeVisible();
  // 확정해 둔 후보가 이미 선택된 상태로 열려야 한다.
  await expect(page.locator(".match-option.chosen")).toHaveCount(1);
});
