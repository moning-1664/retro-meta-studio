// External Storage로 System을 드래그하면 Apply 전에도 Navigator가 목표 그룹
// 밑에 미리 보여줘야 한다(실사용 피드백: 드래그해도 화면이 그대로면 "드래그가
// 안 먹혔다"처럼 보였다). 그리고 지난 Apply에서 실패한 항목은 하단 "실패 N"
// 배지를 눌러 이유를 볼 수 있어야 한다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("System을 다른 Storage 그룹으로 드래그하면 Apply 전에도 그 그룹 밑에 보인다", async ({ page }) => {
  // 목업: snes는 Internal, ps2는 External SD 밑에 있다.
  const internalGroup = page.locator(".nav-group", { hasText: "INTERNAL" });
  const externalGroup = page.locator(".nav-group", { hasText: "EXTERNAL SD" });
  const snesRow = internalGroup.locator(".nav-system", { hasText: "SNES" });
  await expect(snesRow).toBeVisible();

  await snesRow.dragTo(externalGroup);

  // 드래그 직후(Apply 전)에도 External SD 그룹 밑에 나타나고, 이동 예정
  // 표시(pending-move)가 붙는다.
  const movedRow = externalGroup.locator(".nav-system", { hasText: "SNES" });
  await expect(movedRow).toBeVisible();
  await expect(movedRow).toHaveClass(/pending-move/);
});

test("실패 배지를 누르면 이유가 담긴 다이얼로그가 뜬다", async ({ page }) => {
  await page.evaluate(() => window.api.__setMockFailedEntries([
    { key: "storage_change|ps2", op: "storage_change", system: "ps2", filename: "ps2",
      status: "failed", error: "대상 Storage에 같은 이름의 파일이 2개 있습니다: FFX.iso 등" },
  ]));
  // Delete는 refreshPlan()을 거치는 기존 동작이라, 그걸 빌려 목업 상태를 다시 읽게 한다.
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Delete");

  const badge = page.locator(".sb-badge.danger");
  await expect(badge).toContainText("실패 1");
  await badge.click();

  await expect(page.locator(".modal-title")).toHaveText("실패한 항목");
  await expect(page.locator(".modal-body")).toContainText("같은 이름의 파일이 2개 있습니다");

  // "Plan에서 제거"를 누르면 배지가 사라진다.
  await page.locator(".conflict-row .btn", { hasText: "Plan에서 제거" }).click();
  await expect(page.locator(".sb-badge.danger")).toHaveCount(0);
});
