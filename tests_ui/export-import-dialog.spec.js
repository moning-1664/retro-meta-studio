// Export to GameListSet / Import from ArchiveDB 대화상자 - 끝까지 눌러서 실제로
// 존재하지 않는 api 메서드를 호출하다 죽지 않는지 검증한다 (리뷰에서 지적된 P0:
// app.js가 api.startExportToLocal()을 호출하는데 api-client.js/api.py에 그 메서드
// 자체가 없어서, pywebview 실기에서는 버튼을 누르는 순간 죽었지만 이 흐름을 끝까지
// 눌러보는 Playwright 테스트가 없어서 지금까지 못 잡았던 문제).
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator("#sidebar .nav-item").first()).toBeVisible();
});

test("ArchiveDB 화면 - Export to GameListSet을 끝까지 눌러도 에러 없이 완료된다", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.locator("#sidebar").getByRole("button", { name: "ArchiveDB", exact: true }).click();
  await page.locator(".list-footer-actions button", { hasText: "Export to GameListSet" }).click();
  await expect(page.locator(".export-mode-item").first()).toBeVisible();
  await page.locator(".export-mode-item").first().click();

  // Media 선택 대화상자 - 기본값 그대로 "가져오기" 클릭.
  await expect(page.getByRole("button", { name: "가져오기" })).toBeVisible();
  await page.getByRole("button", { name: "가져오기" }).click();

  await expect(page.locator("#toast")).toBeVisible({ timeout: 5000 });
  expect(errors, `콘솔에 잡힌 페이지 에러: ${errors.join(", ")}`).toHaveLength(0);
});

test("GameListSet 화면 - Import from ArchiveDB를 끝까지 눌러도 에러 없이 완료된다", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.locator("#sidebar").getByRole("button", { name: "Local 1", exact: true }).click();
  await page.locator(".list-footer-actions button", { hasText: "Import from ArchiveDB" }).click();

  await expect(page.getByRole("button", { name: "가져오기" })).toBeVisible();
  await page.getByRole("button", { name: "가져오기" }).click();

  await expect(page.locator("#toast")).toBeVisible({ timeout: 5000 });
  expect(errors, `콘솔에 잡힌 페이지 에러: ${errors.join(", ")}`).toHaveLength(0);
});

// [체감 속도, Export 3단계] runJobWithProgress가 followUpJobId를 따라 실제로
// 1->2->3단계 job을 전부 이어서 폴링하는지 확인한다 - 1단계 job이 끝났을 때 바를
// 숨기고 곧바로 반환해버리면(과거 버그) 2/3단계는 아무도 폴링하지 않게 된다.
// job-progress가 순식간에 끝나는 mock 환경이라 진행률 바를 눈으로 붙잡는 대신,
// window.getJobProgress 호출 인자를 직접 스파이한다.
test("Export to GameListSet이 (1/3)->(2/3)->(3/3) 3개 job을 전부 이어서 폴링한다", async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator("#sidebar .nav-item").first()).toBeVisible();
  await page.evaluate(() => {
    window.__polledJobIds = [];
    const original = window.RMApi._call.bind(window.RMApi);
    window.RMApi._call = (name, args) => {
      if (name === "get_job_progress") window.__polledJobIds.push(args[0]);
      return original(name, args);
    };
  });

  await page.locator("#sidebar").getByRole("button", { name: "ArchiveDB", exact: true }).click();
  await page.locator(".list-footer-actions button", { hasText: "Export to GameListSet" }).click();
  await expect(page.locator(".export-mode-item").first()).toBeVisible();
  await page.locator(".export-mode-item").first().click();
  await expect(page.getByRole("button", { name: "가져오기" })).toBeVisible();
  await page.getByRole("button", { name: "가져오기" }).click();

  await expect(page.locator("#toast")).toBeVisible({ timeout: 5000 });
  const polledJobIds = await page.evaluate(() => window.__polledJobIds);
  expect(polledJobIds).toContain("mock-export-job-1");
  expect(polledJobIds).toContain("mock-export-job-2");
  expect(polledJobIds).toContain("mock-export-job-3");
});
