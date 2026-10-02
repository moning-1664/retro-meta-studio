// Convert 미리보기 (스펙 §53).
//
// 이 화면의 존재 이유는 변환을 실행하는 것이 아니라 **실행 전에 무엇을 잃는지 보여주는
// 것**이다. Frontend 간 변환은 반드시 무언가를 잃으므로(§50-51), 그 숫자가 안 보이면
// 사용자는 판단할 수 없다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

// Convert 전용 메뉴는 없앴다(메뉴 정리 §6) - 탭 우클릭 -> "Collection 정보" 안의
// Convert 버튼이 지금의 유일한 진입점이다.
async function openConvertFromTab(page) {
  await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
  await page.locator(".ctx-menu .ctx-item", { hasText: "Collection 정보" }).click();
  await page.locator(".modal-body button", { hasText: "Convert" }).click();
}

/** 미리보기 이후 검증(손실 표, Plan 반영)은 대상을 어떻게 골랐는지와 무관하므로,
 * 여기서는 항상 "이미 있는 Collection으로"를 골라 기존 흐름을 그대로 쓴다. */
async function openConvertPreview(page) {
  await openConvertFromTab(page);
  await expect(page.locator(".modal-title")).toHaveText("변환");
  await page.locator(".convert-new-block input.field-input").fill("D:\\Converted");
  await modalButton(page, "다음").click();
  await expect(page.locator(".modal-title")).toHaveText("변환 미리보기");
}

test("Collection 정보에서 Convert를 시작한다", async ({ page }) => {
  await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
  await page.locator(".ctx-menu .ctx-item", { hasText: "Collection 정보" }).click();
  await expect(page.locator(".modal-body button", { hasText: "Convert" })).toBeVisible();
});

test("기본은 '새 Collection으로'이고, Frontend/폴더를 고르게 한다", async ({ page }) => {
  await openConvertFromTab(page);
  await expect(page.locator(".modal-body .seg-btn")).toHaveCount(0);
  await expect(page.locator(".convert-new-block select")).toBeVisible();
  await expect(page.locator(".convert-new-block input.field-input")).toBeVisible();
});

test("변환은 새 폴더만 선택하며 원본 보존을 알린다", async ({ page }) => {
  await openConvertFromTab(page);
  await expect(page.locator(".convert-existing-block, .modal-body .seg-btn")).toHaveCount(0);
  await expect(page.locator(".modal-hint").last()).toContainText("원본은 그대로");
});

test("'새 Collection으로'는 그 자리에서 Collection을 만들고 이어서 미리보기로 간다", async ({ page }) => {
  await openConvertFromTab(page);
  await page.locator(".convert-new-block select").selectOption("es-de");
  await page.locator(".convert-new-block input.field-input").fill("D:\\NewPegasus");
  await modalButton(page, "다음").click();
  await expect(page.locator(".modal-title")).toHaveText("변환 미리보기");
  await expect(page.locator(".convert-head")).toContainText("Master Library");
});

test("미리보기가 넘어가는 것과 잃는 것을 나눠 보여준다", async ({ page }) => {
  await openConvertPreview(page);

  await expect(page.locator(".convert-head")).toContainText("Master Library");
  await expect(page.locator(".convert-head")).toContainText("Pegasus");

  const moving = page.locator(".convert-table:not(.convert-losses) .convert-row");
  await expect(moving).toHaveCount(3);
  await expect(moving.nth(0)).toContainText("Games");
  await expect(moving.nth(0)).toContainText("1,284");
  await expect(moving.nth(2)).toContainText("미디어");

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
  await expect(page.locator("#filter-bar .plan-actions")).toHaveCount(0);
});

test("변환하기는 독립 미리보기로 진행하고 Plan 버튼을 만들지 않는다", async ({ page }) => {
  await openConvertPreview(page);
  await modalButton(page, "변환하기").click();

  await expect(page.locator("#filter-bar .plan-actions")).toHaveCount(0);
  // 변환 결과가 올라간 곳으로 이동해야 사용자가 다음 행동을 할 수 있다.
  await expect(page.locator(".ctab.active")).not.toContainText("Master Library");
});
