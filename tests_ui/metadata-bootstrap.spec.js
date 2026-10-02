// gamelist 만들기는 **선택지이지 Collection을 여는 조건이 아니다.**
//
// 예전에는 Collection을 추가하는 길목에서 자동으로 "메타데이터가 없습니다"를 띄웠다.
// 두 가지가 잘못됐다.
//
//   1. ROM만 있는 Collection은 그 자체로 정상이다. 만들자마자 없다고 알리면 사용자는
//      무언가 잘못한 것처럼 느낀다.
//   2. ROM 폴더를 따로 지정한 System 때문에, 정상적인 ES-DE 폴더에서도 이 창이 떴다.
//
// [§4 개정] Collection 전체를 한 번에 대상으로 하는 HERO 아이콘은 없앴다(실사용
// 피드백 - "gamelist 만들기 아이콘은 없앤다") - Storage 그룹 우클릭으로 그 그룹의
// System들을 한 번에 만드는 길은 남아 있다. 아래 테스트는 그 길로 다시 부른다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

// mock의 metadata_status가 missing으로 주는 것은 snes/gba뿐이고, 그 둘은 기본
// fixture에서 INTERNAL Storage에 있다 - 그 그룹 머리를 우클릭한다.
// 우클릭하면 메뉴가 뜨고(사용자 결정 - 예전에는 곧바로 이 창이 떴다) 거기서 "gamelist 만들기"를 고른다.
const openViaInternalGroup = async (page) => {
  await page.locator(".nav-group-head", { hasText: "내부" }).click({ button: "right" });
  await page.locator(".ctx-menu .ctx-item", { hasText: "gamelist 만들기" }).click();
};

test.beforeEach(async ({ page }) => { await openApp(page); });

async function addCollection(page, name = "ROM만") {
  await page.locator(".ctab-add").click();
  await page.locator(".modal-body input[placeholder='예: Android ES-DE']").fill(name);
  await page.locator(".modal-body .btn", { hasText: "찾아보기" }).first().click();
  await modalButton(page, "Add").click();
}

test("Collection을 추가해도 메타데이터를 만들지 묻지 않는다", async ({ page }) => {
  await addCollection(page);
  // 모달이 남아 있지 않고 바로 그 Collection이 열린다.
  await expect(page.locator(".modal-title")).toHaveCount(0);
  await expect(page.locator(".ctab.active")).toContainText("ROM만");
});

test("추가하는 것만으로는 gamelist를 만들지 않는다", async ({ page }) => {
  let generated = 0;
  await page.exposeFunction("__countGenerate", () => { generated += 1; });
  await page.evaluate(() => {
    const original = window.api.generateMetadata;
    window.api.generateMetadata = (...args) => { window.__countGenerate(); return original(...args); };
  });

  await addCollection(page);
  await expect(page.locator(".ctab.active")).toContainText("ROM만");
  expect(generated).toBe(0);
});

test("Storage 그룹 우클릭으로 직접 부를 수 있다", async ({ page }) => {
  await openViaInternalGroup(page);
  await expect(page.locator(".modal-title")).toHaveText("gamelist 만들기");
});

test("무엇을 하는지와 무엇을 하지 않는지 함께 알린다", async ({ page }) => {
  await openViaInternalGroup(page);
  const hints = page.locator(".modal-hint");
  // 파일명만 넣는다는 것과, 추측해서 채우지 않는다는 것 둘 다 말해야 한다.
  await expect(hints.first()).toContainText("파일명");
  await expect(hints.first()).toContainText("추측");
  // 어느 System이 대상인지도 보여준다.
  await expect(hints.nth(1)).toContainText("snes");
});

test("'나중에'를 고르면 아무것도 만들지 않는다", async ({ page }) => {
  let generated = 0;
  await page.exposeFunction("__countGenerate", () => { generated += 1; });
  await page.evaluate(() => {
    const original = window.api.generateMetadata;
    window.api.generateMetadata = (...args) => { window.__countGenerate(); return original(...args); };
  });

  await openViaInternalGroup(page);
  await modalButton(page, "나중에").click();

  await expect(page.locator(".modal-title")).toHaveCount(0);
  expect(generated).toBe(0);
});

test("'gamelist 만들기'를 고르면 만들고 결과를 알려준다", async ({ page }) => {
  await openViaInternalGroup(page);
  await modalButton(page, "gamelist 만들기").click();

  await expect(page.locator("#toast")).toContainText("gamelist를 만들었습니다");
  await expect(page.locator("#toast")).toContainText("3개");
});
