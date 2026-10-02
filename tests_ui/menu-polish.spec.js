// 메뉴/UX 용어 정리(사용자 결정, 2026-09) - Settings와 메뉴 이름이 난잡하다는 지적에
// 따라 이름을 바꾸고 몇 개를 추가/삭제했다. 백엔드 계산 자체는 각자의 파일이 촘촘히
// 검증하므로(tests/test_gameid.py의 DiscRetagTests 등), 여기서는 메뉴가 실제로 그
// 기능을 부르는지만 본다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

const menuItem = (page, label) => page.locator(".ctx-menu .ctx-item", { hasText: label });
const rightClickSystem = (page, name) => page.locator(".nav-system", { hasText: name }).click({ button: "right" });

test.beforeEach(async ({ page }) => { await openApp(page); });

test.describe("System 우클릭 메뉴", () => {
  test("머리에 System 아이콘이 붙는다", async ({ page }) => {
    await rightClickSystem(page, "PS2");
    await expect(page.locator(".ctx-title .sys-ic")).toBeVisible();
  });

  test("gamelist 만들기는 없앴다 - 애매한 항목이었다", async ({ page }) => {
    await rightClickSystem(page, "PS2");
    await expect(menuItem(page, "gamelist 만들기")).toHaveCount(0);
  });

  test("이름이 정리된 항목들이 보인다", async ({ page }) => {
    await rightClickSystem(page, "PS2");
    await expect(menuItem(page, "언어 태그 적용…")).toBeVisible();
    await expect(menuItem(page, "멀티 디스크 태그 적용…")).toBeVisible();
    await expect(menuItem(page, "미디어 정리…")).toBeVisible();
    await expect(menuItem(page, "시스템과 파일 삭제…")).toBeVisible();
    await expect(menuItem(page, "온라인에서 게임 정보 검색…")).toBeEnabled();
  });

  test("복사한 게임을 다른 System에 신규 추가한다", async ({ page }) => {
    const calls = [];
    await page.exposeFunction("__systemPaste", (args) => calls.push(args));
    await page.evaluate(() => {
      const original = window.api.paste;
      window.api.paste = (...args) => { window.__systemPaste(args); return original(...args); };
    });
    await page.locator(".nav-system", { hasText: "SNES" }).click();
    await page.locator(".lrow", { hasText: "Super Mario World" }).click();
    await page.keyboard.press("Control+c");
    await rightClickSystem(page, "PS2");
    const item = menuItem(page, "여기에 붙여넣기 (1개)");
    await expect(item).toBeEnabled();
    await expect(item).toHaveAttribute("title", /snes \/ Super Mario World/);
    await item.click();
    await expect.poll(() => calls.length).toBe(1);
    expect(calls[0][2]).toEqual({ snes: "ps2" });
    expect(calls[0][5]).toBe(false);
    expect(calls[0][6]).toBe(true);
  });

  test("같은 게임도 붙여넣기를 허용하고 충돌 미리보기로 처리한다", async ({ page }) => {
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();
    await page.keyboard.press("Control+c");
    await rightClickSystem(page, "PS2");
    await expect(menuItem(page, "여기에 붙여넣기 (1개)")).toBeEnabled();
  });

  test("여러 게임을 복사하면 hover 설명에 대상 목록을 보여준다", async ({ page }) => {
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();
    await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).click({ modifiers: ["Control"] });
    await page.keyboard.press("Control+c");
    await rightClickSystem(page, "SNES");
    const item = menuItem(page, "여기에 붙여넣기 (2개)");
    await expect(item).toBeEnabled();
    await expect(item).toHaveAttribute("title", /Final Fantasy X.*\n.*Metal Gear Solid 2/);
  });

});

test.describe("System 우클릭 - 멀티 디스크 태그 적용", () => {
  // 이 describe만 파일명에 Disc 표시를 심어 둔다 - 바깥 beforeEach보다 먼저 걸려야
  // 하므로 여기서 따로 openApp을 부른다.
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((files) => { window.__RMS_MOCK_FILES = files; }, { 1: "FFX (Disc 1).iso" });
    await openApp(page);
  });

  test("Disc 표시가 있는 파일만 미리보기에 올린다", async ({ page }) => {
    await rightClickSystem(page, "PS2");
    await menuItem(page, "멀티 디스크 태그 적용…").click();
    await expect(page.locator(".modal-title")).toHaveText("멀티 디스크 태그 적용");
    await expect(page.locator(".title-affix-row")).toHaveCount(1);
    await expect(page.locator(".title-affix-new")).toContainText("Disc 1");
  });
});

test.describe("상단 탭 - 갖다대기와 우클릭", () => {
  const tab = (page) => page.locator(".ctab:not(.archive)").first();

  test("갖다대면 롬 개수/총 용량/Metadata 경로가 뜬다", async ({ page }) => {
    await tab(page).hover();
    await expect.poll(() => tab(page).getAttribute("title")).toContain("롬 개수");
    const t = await tab(page).getAttribute("title");
    expect(t).toContain("총 용량");
    expect(t).toContain("메타데이터");
  });

  test("이름 변경/Convert 대신 'Collection 정보' 하나만 있다", async ({ page }) => {
    await tab(page).click({ button: "right" });
    await expect(menuItem(page, "이름 변경")).toHaveCount(0);
    await expect(menuItem(page, "Convert")).toHaveCount(0);
    await expect(menuItem(page, "Collection 정보")).toBeVisible();
  });

  test("Collection 정보 창은 Collection 추가와 같은 필드 구성이고 이름을 고칠 수 있다", async ({ page }) => {
    await tab(page).click({ button: "right" });
    await menuItem(page, "Collection 정보").click();
    await expect(page.locator(".modal-title")).toHaveText("Collection 정보");
    const nameInput = page.locator(".modal-body input.field-input").first();
    await nameInput.fill("New Name");
    await modalButton(page, "저장").click();
    await expect(tab(page)).toContainText("New Name");
  });

  test("Collection 정보 안에서 Convert로 들어갈 수 있다", async ({ page }) => {
    await tab(page).click({ button: "right" });
    await menuItem(page, "Collection 정보").click();
    await page.locator(".modal-body button", { hasText: "Convert" }).click();
    await expect(page.locator(".modal-title")).toHaveText("Convert");
  });

  test("Metadata 폴더를 바꾸면 재스캔 경고가 뜨고, 확인해야 반영된다", async ({ page }) => {
    await page.evaluate(() => {
      window.__paths = [];
      const original = window.api.updateCollectionPaths;
      window.api.updateCollectionPaths = (id, root, rom) => { window.__paths.push({ id, root, rom }); return original(id, root, rom); };
    });
    await tab(page).click({ button: "right" });
    await menuItem(page, "Collection 정보").click();
    const metaInput = page.locator(".modal-body .field-row input.field-input").first();
    await metaInput.fill("D:\\새폴더");
    await modalButton(page, "저장").click();
    await expect(page.locator(".modal-title")).toHaveText("폴더 변경");
    await expect(page.locator(".modal-text")).toContainText("다시 스캔");
    await expect(page.evaluate(() => window.__paths.length)).resolves.toBe(0);
    await modalButton(page, "확인").click();
    await expect.poll(() => page.evaluate(() => window.__paths.length)).toBe(1);
    expect(await page.evaluate(() => window.__paths[0].root)).toBe("D:\\새폴더");
  });

  test("이름/Target만 바꾸면 재스캔 경고 없이 바로 저장된다", async ({ page }) => {
    await tab(page).click({ button: "right" });
    await menuItem(page, "Collection 정보").click();
    await page.locator(".modal-body select").selectOption("windows");
    await modalButton(page, "저장").click();
    await expect(page.locator(".modal-title")).toHaveCount(0);
  });
});

test.describe("Gamelist 행 우클릭 메뉴", () => {
  const rightClickRow = (page, text) => page.locator(".lrow", { hasText: text }).click({ button: "right" });

  test("상세 보기는 없앴다", async ({ page }) => {
    await rightClickRow(page, "Final Fantasy X");
    await expect(menuItem(page, "상세 보기")).toHaveCount(0);
  });

  test("즐겨찾기는 '즐겨찾기에 추가'로 부른다", async ({ page }) => {
    await rightClickRow(page, "Metal Gear Solid 2");
    await expect(menuItem(page, "즐겨찾기에 추가")).toBeVisible();
  });

  test("메타데이터 스크랩을 시작할 수 있다", async ({ page }) => {
    await rightClickRow(page, "Final Fantasy X");
    await expect(menuItem(page, "온라인에서 게임 정보 검색…")).toBeEnabled();
  });
});
