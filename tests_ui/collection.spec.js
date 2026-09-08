// Collection 추가/이름변경/제거와 External Storage - 목업이 상태를 실제로 바꾸므로
// "화면이 그 변화를 따라가는가"까지 확인할 수 있다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("+ 버튼이 Collection 열기 목록을 띄우고 열린 것은 '열림'으로 표시한다", async ({ page }) => {
  await page.locator(".ctab-add").click();
  await expect(page.locator(".modal-title")).toHaveText("Collection 열기");
  const opened = page.locator(".picker-row", { hasText: "Master Library" });
  await expect(opened.locator(".picker-badge")).toHaveText("열림");
});

test("목록에서 다른 Collection을 고르면 탭이 하나 더 열린다", async ({ page }) => {
  await expect(page.locator(".ctab:not(.archive)")).toHaveCount(1);
  await page.locator(".ctab-add").click();
  await page.locator(".picker-row", { hasText: "Android ES-DE" }).click();
  await expect(page.locator(".ctab:not(.archive)")).toHaveCount(2);
  await expect(page.locator(".ctab.active")).toContainText("Android ES-DE");
});

test("새 Collection 추가는 이름과 폴더가 둘 다 있어야 진행된다", async ({ page }) => {
  await page.locator(".ctab-add").click();
  await modalButton(page, "새 Collection 추가").click();
  await expect(page.locator(".modal-title")).toHaveText("새 Collection");

  // 폴더를 비워둔 채 누르면 경고만 뜨고 모달이 닫히지 않아야 한다.
  await page.locator(".modal-body .field-input").first().fill("이름만 있음");
  await modalButton(page, "추가").click();
  await expect(page.locator("#toast")).toContainText("이름과 폴더");
  await expect(page.locator(".modal-title")).toHaveText("새 Collection");

  // 찾아보기(목업 pick_folder)로 경로를 채우면 추가된다.
  await page.locator(".modal-body .btn", { hasText: "찾아보기" }).click();
  await modalButton(page, "추가").click();

  // 메타데이터가 없는 Collection이면 만들지 먼저 묻는다(§Phase 7.8) - 그 안내를
  // 지나야 탭이 열린다.
  await modalButton(page, "나중에").click();
  await expect(page.locator(".ctab.active")).toContainText("이름만 있음");
});

test("탭 우클릭 -> 이름 변경이 탭 제목에 반영된다", async ({ page }) => {
  await page.locator(".ctab").first().click({ button: "right" });
  await page.locator(".modal-actions .btn", { hasText: "이름 변경" }).click();
  await page.locator(".modal-body .field-input").fill("이름 바꾼 컬렉션");
  await modalButton(page, "저장").click();
  await expect(page.locator(".ctab").first()).toContainText("이름 바꾼 컬렉션");
});

test("탭 우클릭 -> 제거는 확인을 거친 뒤 탭을 닫는다", async ({ page }) => {
  await page.locator(".ctab").first().click({ button: "right" });
  await page.locator(".modal-actions .btn.danger", { hasText: "제거" }).click();
  await expect(page.locator(".modal-text")).toContainText("실제 파일은 삭제되지 않습니다");
  await modalButton(page, "확인").click();
  await expect(page.locator(".ctab:not(.archive)")).toHaveCount(0);
});
