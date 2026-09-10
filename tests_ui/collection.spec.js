// Collection 추가/이름변경/제거와 External Storage - 목업이 상태를 실제로 바꾸므로
// "화면이 그 변화를 따라가는가"까지 확인할 수 있다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("+ 버튼을 누르면 바로 Collection 추가 화면이 뜨고, History에서 열린 것을 확인할 수 있다", async ({ page }) => {
  await page.locator(".ctab-add").click();
  await expect(page.locator(".modal-title")).toHaveText("Collection 추가");
  // History는 기본적으로 접혀 있다 - 펼쳐야 예전 목록이 보인다.
  await expect(page.locator(".add-collection-history .picker-row").first()).toBeHidden();
  await page.locator(".add-collection-history summary").click();
  const opened = page.locator(".picker-row", { hasText: "Master Library" });
  await expect(opened.locator(".picker-badge")).toHaveText("열림");
});

test("History에서 다른 Collection을 고르면 탭이 하나 더 열린다", async ({ page }) => {
  await expect(page.locator(".ctab:not(.archive)")).toHaveCount(1);
  await page.locator(".ctab-add").click();
  await page.locator(".add-collection-history summary").click();
  await page.locator(".picker-row", { hasText: "Android ES-DE" }).click();
  await expect(page.locator(".ctab:not(.archive)")).toHaveCount(2);
  await expect(page.locator(".ctab.active")).toContainText("Android ES-DE");
});

test("Metadata 디렉토리 하나만 있어도 추가되고, 이름은 폴더명으로 채워진다", async ({ page }) => {
  await page.locator(".ctab-add").click();
  await expect(page.locator(".modal-title")).toHaveText("Collection 추가");

  // 두 경로를 모두 비워둔 채 누르면 경고만 뜨고 모달이 닫히지 않아야 한다.
  await modalButton(page, "Add").click();
  await expect(page.locator("#toast")).toContainText("하나는 선택하세요");
  await expect(page.locator(".modal-title")).toHaveText("Collection 추가");

  // 찾아보기(목업 pick_folder)로 경로를 채우면 이름을 안 적어도 폴더명으로 채워져 추가된다.
  await page.locator(".modal-body .btn", { hasText: "찾아보기" }).first().click();
  await modalButton(page, "Add").click();

  // 메타데이터가 없다는 이유로 가로막지 않는다 - 바로 열린다.
  await expect(page.locator(".ctab.active")).toContainText("ES-DE");
});

test("탭 우클릭 -> 이름 변경이 탭 제목에 반영된다", async ({ page }) => {
  await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
  await page.locator(".modal-actions .btn", { hasText: "이름 변경" }).click();
  await page.locator(".modal-body .field-input").fill("이름 바꾼 컬렉션");
  await modalButton(page, "저장").click();
  await expect(page.locator(".ctab:not(.archive)").first()).toContainText("이름 바꾼 컬렉션");
});

test("탭 우클릭 -> 제거는 확인을 거친 뒤 탭을 닫는다", async ({ page }) => {
  await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
  await page.locator(".modal-actions .btn.danger", { hasText: "제거" }).click();
  await expect(page.locator(".modal-text")).toContainText("실제 파일은 삭제되지 않습니다");
  await modalButton(page, "확인").click();
  await expect(page.locator(".ctab:not(.archive)")).toHaveCount(0);
});
