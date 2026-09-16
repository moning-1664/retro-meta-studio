// 게임 행 우클릭 메뉴.
//
// 예전엔 우클릭하자마자 삭제 확인(모달)이 떴다. 삭제는 여러 동작 중 하나라 오클릭
// 한 번이 곧바로 삭제로 이어졌다(사용자 요청) - 이제는 메뉴를 먼저 띄운다.
// Delete 상시 버튼은 여전히 없다(오클릭 위험, PENDING_DECISIONS.md).
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const rightClick = (page, text) => page.locator(".lrow", { hasText: text }).click({ button: "right" });
const menuItem = (page, label) => page.locator(".ctx-menu .ctx-item", { hasText: label });

test("Delete 상시 버튼은 없다", async ({ page }) => {
  await expect(page.locator("#filter-bar", { hasText: "Delete" })).toHaveCount(0);
});

test("우클릭하면 삭제 확인이 아니라 메뉴가 뜬다", async ({ page }) => {
  await rightClick(page, "Final Fantasy X");
  await expect(page.locator(".ctx-menu")).toBeVisible();
  await expect(page.locator(".modal-title")).toHaveCount(0);
  await expect(page.locator(".ctx-title")).toHaveText("Final Fantasy X");
  await expect(menuItem(page, "삭제")).toBeVisible();
  await expect(menuItem(page, "파일명 복사")).toBeVisible();
});

test("선택하지 않은 행을 우클릭하면 그 행 하나만 선택된다", async ({ page }) => {
  await rightClick(page, "Final Fantasy X");
  await expect(page.locator("#status-bar")).toContainText("Selected 1");
});

test("메뉴의 삭제를 고르면 삭제를 요청하고 메뉴를 닫는다", async ({ page }) => {
  const deleted = [];
  await page.exposeFunction("__deleted", (uids) => deleted.push(uids));
  await page.evaluate(() => {
    const original = window.api.planDelete;
    window.api.planDelete = (id, romUids) => { window.__deleted(romUids); return original(id, romUids); };
  });

  await rightClick(page, "Final Fantasy X");
  await menuItem(page, "삭제").click();

  await expect(page.locator(".ctx-menu")).toHaveCount(0);
  await expect.poll(() => deleted.length).toBeGreaterThan(0);
  expect(deleted[0]).toHaveLength(1);
});

test("이미 여러 개를 선택한 상태로 그중 하나를 우클릭하면 선택 전체가 대상이다", async ({ page }) => {
  await page.locator(".lrow").nth(0).click();
  await page.locator(".lrow").nth(1).click({ modifiers: ["Control"] });
  await expect(page.locator("#status-bar")).toContainText("Selected 2");

  await page.locator(".lrow").nth(0).click({ button: "right" });
  await expect(page.locator(".ctx-title")).toContainText("2개 선택됨");
  await expect(menuItem(page, "파일명 2개 복사")).toBeVisible();
  // 선택이 그대로 유지된다 - 우클릭이 선택을 1개로 되돌리지 않는다.
  await expect(page.locator("#status-bar")).toContainText("Selected 2");
});

test("Esc와 바깥 클릭으로 닫힌다", async ({ page }) => {
  await rightClick(page, "Final Fantasy X");
  await page.keyboard.press("Escape");
  await expect(page.locator(".ctx-menu")).toHaveCount(0);

  await rightClick(page, "Final Fantasy X");
  await page.locator("#collection-header").click({ position: { x: 400, y: 20 } });
  await expect(page.locator(".ctx-menu")).toHaveCount(0);
});

test("메뉴의 즐겨찾기로 별표를 켜고 끈다", async ({ page }) => {
  const star = page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).locator(".fav-btn");
  await expect(star).toHaveText("☆");
  await rightClick(page, "Metal Gear Solid 2");
  await menuItem(page, "즐겨찾기").click();
  await expect(star).toHaveText("★");
});

// 게임 한 개 단위 "폴더 열기" - 실사용 피드백 §5. System 우클릭의 "폴더 열기"와
// 다른 점은 폴더가 아니라 **그 파일을 고른 채로** 연다는 것이다. mock 3행:
// FFX(전부 있음) / MGS2(메타데이터만 있음) / SMW(둘 다 없음, ROM만 있음).
test.describe("게임 한 개 단위 폴더 열기", () => {
  test("여러 개를 고른 채로는 보이지 않는다", async ({ page }) => {
    await page.locator(".lrow").nth(0).click();
    await page.locator(".lrow").nth(1).click({ modifiers: ["Control"] });
    await page.locator(".lrow").nth(0).click({ button: "right" });
    await expect(menuItem(page, "ROM 파일")).toHaveCount(0);
  });

  test("전부 있는 게임은 셋 다 눌린다", async ({ page }) => {
    const opened = [];
    await page.exposeFunction("__opened", (kind) => opened.push(kind));
    await page.evaluate(() => {
      const original = window.api.openRowFolder;
      window.api.openRowFolder = (id, uid, kind) => { window.__opened(kind); return original(id, uid, kind); };
    });
    await rightClick(page, "Final Fantasy X");
    for (const label of ["ROM 파일", "Metadata 파일", "Media 파일"]) {
      await expect(menuItem(page, label)).toBeEnabled();
    }
    await menuItem(page, "ROM 파일").click();
    await expect.poll(() => opened).toEqual(["rom"]);
  });

  test("없는 종류는 회색(비활성)이고 이유를 말한다", async ({ page }) => {
    // SMW는 메타데이터도 미디어도 없다.
    await rightClick(page, "Super Mario World");
    await expect(menuItem(page, "ROM 파일")).toBeEnabled();
    await expect(menuItem(page, "Metadata 파일")).toBeDisabled();
    await expect(menuItem(page, "Metadata 파일")).toHaveAttribute("title", "Metadata가 없습니다.");
    await expect(menuItem(page, "Media 파일")).toBeDisabled();
  });

  test("Archive 탭에는 이 메뉴가 없다(파일 배치 자체가 다르다)", async ({ page }) => {
    await page.locator(".ctab.archive").click();
    // Archive에 항목이 있으면 우클릭해 본다 - 없으면 이 검사는 자연히 넘어간다.
    const row = page.locator(".lrow").first();
    if (await row.count()) {
      await row.click({ button: "right" });
      await expect(menuItem(page, "ROM 파일")).toHaveCount(0);
    }
  });
});
