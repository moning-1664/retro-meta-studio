// 메타데이터 없는 Collection을 열 때의 안내 (Phase 7.8).
//
// ROM만 있는 폴더를 추가하면 **불러오기 전에** 묻는다. 스캔이 끝난 뒤에 물으면
// 사용자는 이미 "메타데이터 없는 목록"을 본 뒤라 무엇을 정하는 건지 알기 어렵다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

async function addCollection(page, name = "ROM만") {
  await page.locator(".ctab-add").click();
  await modalButton(page, "Import").click();
  await page.locator(".modal-body .field-input").first().fill(name);
  await page.locator(".modal-body .btn", { hasText: "찾아보기" }).first().click();
  await modalButton(page, "추가").click();
}

test("메타데이터가 없으면 만들지 물어본다", async ({ page }) => {
  await addCollection(page);
  await expect(page.locator(".modal-title")).toHaveText("메타데이터가 없습니다");
  await expect(page.locator(".modal-text")).toContainText("2개");
});

test("무엇을 하는지와 무엇을 하지 않는지 함께 알린다", async ({ page }) => {
  await addCollection(page);
  const hints = page.locator(".modal-hint");
  // 파일명만 넣는다는 것과, 추측해서 채우지 않는다는 것 둘 다 말해야 한다.
  await expect(hints.first()).toContainText("파일명");
  await expect(hints.first()).toContainText("추측");
  // 어느 System이 대상인지도 보여준다.
  await expect(hints.nth(1)).toContainText("snes");
});

test("'나중에'를 고르면 아무것도 만들지 않고 그대로 연다", async ({ page }) => {
  let generated = 0;
  await page.exposeFunction("__countGenerate", () => { generated += 1; });
  await page.evaluate(() => {
    const original = window.api.generateMetadata;
    window.api.generateMetadata = (...args) => { window.__countGenerate(); return original(...args); };
  });

  await addCollection(page);
  await modalButton(page, "나중에").click();

  await expect(page.locator(".modal-title")).toHaveCount(0);
  await expect(page.locator(".ctab.active")).toContainText("ROM만");
  expect(generated).toBe(0);
});

test("'gamelist 만들기'를 고르면 만들고 결과를 알려준다", async ({ page }) => {
  await addCollection(page);
  await modalButton(page, "gamelist 만들기").click();

  await expect(page.locator("#toast")).toContainText("gamelist를 만들었습니다");
  await expect(page.locator("#toast")).toContainText("3개");
  await expect(page.locator(".ctab.active")).toContainText("ROM만");
});

test("묻는 것은 Collection을 열기 전이다", async ({ page }) => {
  // 안내가 떠 있는 동안에는 아직 그 Collection 탭이 활성화되지 않아야 한다.
  await addCollection(page);
  await expect(page.locator(".modal-title")).toHaveText("메타데이터가 없습니다");
  await expect(page.locator(".ctab.active")).not.toContainText("ROM만");
});
