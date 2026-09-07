// F2(파일명 변경) + Ctrl+C/V(metadata+media 복사) 회귀 테스트 (단위 6).
// mock API 모드로 실제 키보드 이벤트를 흘려서 검증한다 (자세한 배경은
// settings-and-dashboard.spec.js 상단 주석 참고).
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator("#sidebar .nav-item").first()).toBeVisible();
  // 기본 진입 화면은 ArchiveDB(masterdb) - F2/Ctrl+C/V가 동작하는 화면이다.
  await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toBeVisible();
});

test.describe("F2 파일명 변경", () => {
  test("단일 선택 후 F2 -> 새 이름 저장하면 목록에 반영된다", async ({ page }) => {
    await page.locator('[data-rom-key="snes|Super Mario World.zip"]').click();
    await page.keyboard.press("F2");

    const modal = page.locator(".modal-box", { hasText: "파일명 변경" });
    await expect(modal).toBeVisible();
    const input = modal.locator("input.field-input");
    await expect(input).toHaveValue("Super Mario World.zip");
    await input.fill("SMW Renamed.zip");
    await modal.getByRole("button", { name: "변경" }).click();

    await expect(page.locator("#toast.show")).toContainText("파일명이 변경되었습니다");
    await expect(page.locator('[data-rom-key="snes|SMW Renamed.zip"]')).toBeVisible();
  });

  test("다중 선택 상태에서는 F2가 아무 것도 열지 않는다", async ({ page }) => {
    await page.locator('[data-rom-key="snes|Super Mario World.zip"]').click();
    await page.keyboard.down("Control");
    await page.locator('[data-rom-key="snes|Zelda.zip"]').click();
    await page.keyboard.up("Control");
    await page.keyboard.press("F2");
    await expect(page.locator(".modal-box", { hasText: "파일명 변경" })).toHaveCount(0);
  });

  test("Escape로 취소하면 이름이 바뀌지 않는다", async ({ page }) => {
    await page.locator('[data-rom-key="snes|Zelda.zip"]').click();
    await page.keyboard.press("F2");
    const modal = page.locator(".modal-box", { hasText: "파일명 변경" });
    await modal.locator("input.field-input").fill("Should Not Apply.zip");
    await page.keyboard.press("Escape");
    await expect(modal).toHaveCount(0);
    await expect(page.locator('[data-rom-key="snes|Zelda.zip"]')).toBeVisible();
  });
});

test.describe("Ctrl+C / Ctrl+V metadata+media 복사", () => {
  test("복사 후 붙여넣기 시 확인창이 뜨고, 확인하면 덮어쓰기 완료 토스트가 뜬다", async ({ page }) => {
    await page.locator('[data-rom-key="snes|Super Mario World.zip"]').click();
    await page.keyboard.press("Control+c");
    await expect(page.locator("#toast.show")).toContainText("복사했습니다");

    await page.locator('[data-rom-key="snes|Zelda.zip"]').click();
    await page.keyboard.press("Control+v");
    const confirmBox = page.locator(".modal-box", { hasText: "Metadata + Media 덮어쓰기" });
    await expect(confirmBox).toBeVisible();
    await confirmBox.getByRole("button", { name: "확인" }).click();
    await expect(page.locator("#toast.show")).toContainText("덮어쓰기 완료");
  });

  test("Confirmations를 꺼두면 Ctrl+V가 확인창 없이 바로 실행된다", async ({ page }) => {
    await page.locator(".sidebar-settings-btn").click();
    const confirmToggle = page.locator(".settings-checkbox-row", { hasText: "Confirmations" }).locator("input[type=checkbox]");
    await confirmToggle.uncheck();
    await page.getByRole("button", { name: "설정 저장" }).click();
    await expect(page.locator("#toast.show")).toContainText("저장");
    // [GUI 정돈] Settings의 닫기(X) 버튼은 제거됨 - 메인 사이드바로 화면을 벗어난다.
    // (Settings 탭 목록에도 "ArchiveDB"라는 버튼이 있어 #sidebar로 범위를 좁힌다.)
    await page.locator("#sidebar").getByRole("button", { name: "ArchiveDB", exact: true }).click();

    await page.locator('[data-rom-key="snes|Super Mario World.zip"]').click();
    await page.keyboard.press("Control+c");
    await page.locator('[data-rom-key="snes|Zelda.zip"]').click();
    await page.keyboard.press("Control+v");

    await expect(page.locator(".modal-box", { hasText: "Metadata + Media 덮어쓰기" })).toHaveCount(0);
    await expect(page.locator("#toast.show")).toContainText("덮어쓰기 완료");
  });
});
