// Convert 미리보기 (스펙 §53).
//
// 이 화면의 존재 이유는 변환을 실행하는 것이 아니라 **실행 전에 무엇을 잃는지 보여주는
// 것**이다. Frontend 간 변환은 반드시 무언가를 잃으므로(§50-51), 그 숫자가 안 보이면
// 사용자는 판단할 수 없다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

async function openConvertPreview(page) {
  await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
  await page.locator(".ctx-menu .ctx-item", { hasText: "Convert" }).click();
  await expect(page.locator(".modal-title")).toHaveText("Convert");
  await modalButton(page, "다음").click();
  await expect(page.locator(".modal-title")).toHaveText("Convert 미리보기");
}

test("탭 우클릭에서 Convert를 시작한다", async ({ page }) => {
  await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
  await expect(page.locator(".ctx-menu .ctx-item", { hasText: "Convert" })).toBeVisible();
});

test("대상 Collection을 고르게 하고 원본 보존을 알린다", async ({ page }) => {
  await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
  await page.locator(".ctx-menu .ctx-item", { hasText: "Convert" }).click();

  // 자기 자신은 대상에 없어야 한다.
  const options = page.locator(".modal-body select option");
  await expect(options).toHaveCount(1);
  await expect(options).toContainText("Android ES-DE");
  await expect(page.locator(".modal-hint")).toContainText("원본은 그대로");
});

test("미리보기가 넘어가는 것과 잃는 것을 나눠 보여준다", async ({ page }) => {
  await openConvertPreview(page);

  await expect(page.locator(".convert-head")).toContainText("Master Library");
  await expect(page.locator(".convert-head")).toContainText("Pegasus");

  const moving = page.locator(".convert-table:not(.convert-losses) .convert-row");
  await expect(moving).toHaveCount(3);
  await expect(moving.nth(0)).toContainText("Games");
  await expect(moving.nth(0)).toContainText("1,284");
  await expect(moving.nth(2)).toContainText("Media");

  const losses = page.locator(".convert-losses .convert-row");
  await expect(losses).toHaveCount(3);
  await expect(losses.nth(0)).toContainText("Unsupported fields");
  await expect(losses.nth(0)).toContainText("37");
  await expect(losses.nth(2)).toContainText("Frontend-specific");
  await expect(losses.nth(2)).toContainText("112");
});

test("잃는 항목은 눈에 띄게 표시되고 어느 필드인지 알려준다", async ({ page }) => {
  await openConvertPreview(page);
  const lossy = page.locator(".convert-losses .convert-row.lossy");
  await expect(lossy).toHaveCount(3);
  await expect(lossy.nth(0)).toHaveAttribute("title", /region/);
});

test("미리보기 단계에서는 아직 아무것도 하지 않는다", async ({ page }) => {
  await openConvertPreview(page);
  await modalButton(page, "취소").click();
  await expect(page.locator(".modal-title")).toHaveCount(0);
  // Plan은 그대로다 - 툴바의 Apply가 여전히 비활성.
  await expect(page.locator("#filter-bar .plan-actions .seg-btn", { hasText: "Apply" })).toBeDisabled();
});

test("Plan에 올리면 대상 Collection으로 데려가고 Apply가 남았음을 알린다", async ({ page }) => {
  await openConvertPreview(page);
  await modalButton(page, "Plan에 올리기").click();

  await expect(page.locator("#toast")).toContainText("Plan에 올렸습니다");
  await expect(page.locator("#toast")).toContainText("Apply");
  // 변환 결과가 올라간 곳으로 이동해야 사용자가 다음 행동을 할 수 있다.
  await expect(page.locator(".ctab.active")).toContainText("Android ES-DE");
});
