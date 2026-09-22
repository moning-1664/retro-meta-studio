// 우선 정렬 - 실사용 피드백 §5.
//
// 예전 "상태 필터"(모든 상태/메타데이터 없음/미디어 없음/ROM 없음)는 currentQuery()가
// 값을 끝내 읽지 않아 실제로는 아무것도 걸러내지 못했다. 그 자리를 필터가 아니라
// **1차 정렬 기준**으로 바꿨다 - 있는 항목이 없는 항목보다 먼저 오고, 항목 수는
// 그대로다. 기본값은 Settings에서 정할 수 있다.
//
// mock 3행: FFX(메타데이터·미디어 있음) / MGS2(메타데이터 있음, 미디어 없음) /
// SMW(둘 다 없음).
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

const rowFiles = (page) => page.locator(".lrow .lc-file").allTextContents();
const prioritySelect = (page) => page.locator("#filter-bar .mini-select[title='우선 정렬']");

test.describe("기본 동작", () => {
  test.beforeEach(async ({ page }) => { await openApp(page); });

  test("툴바 순서는 LIST/CARD, Favorite, 우선정렬, Search다", async ({ page }) => {
    const bar = page.locator("#filter-bar");
    const order = await bar.evaluate((el) => [...el.children].map((c) =>
      c.className.split(" ")[0]));
    // seg(LIST/CARD) -> icon-btn(Favorite) -> mini-select(우선정렬) -> search-box
    expect(order.slice(0, 4)).toEqual(["seg", "icon-btn", "mini-select", "search-box"]);
  });

  test("전체보기가 기본이고, 옵션은 네 가지다", async ({ page }) => {
    await expect(prioritySelect(page)).toHaveValue("");
    const labels = await prioritySelect(page).locator("option").allTextContents();
    expect(labels).toEqual(["전체보기", "ROM 우선", "메타데이터 우선", "미디어 우선"]);
  });

  test("메타데이터 우선 - 메타데이터 없는 항목(SMW)이 뒤로 간다", async ({ page }) => {
    await prioritySelect(page).selectOption("metadata");
    const files = await rowFiles(page);
    expect(files.indexOf("SMW.sfc")).toBe(files.length - 1);
  });

  test("미디어 우선 - 미디어 있는 항목(FFX)이 앞으로 온다", async ({ page }) => {
    await prioritySelect(page).selectOption("media");
    const files = await rowFiles(page);
    expect(files[0]).toBe("FFX.iso");
  });

  test("전체보기로 되돌리면 원래 순서(제목순)로 돌아간다", async ({ page }) => {
    const original = await rowFiles(page);
    await prioritySelect(page).selectOption("metadata");
    await prioritySelect(page).selectOption("");
    expect(await rowFiles(page)).toEqual(original);
  });

  test("우선 정렬을 바꿔도 항목 수는 그대로다(필터가 아니다)", async ({ page }) => {
    const before = await page.locator(".lrow").count();
    await prioritySelect(page).selectOption("media");
    expect(await page.locator(".lrow").count()).toBe(before);
    await expect(page.locator("#filter-total")).toContainText(String(before));
  });

  test("화면이 보낸 값을 백엔드가 그대로 받는다", async ({ page }) => {
    const seen = [];
    await page.exposeFunction("__seenPriority", (p) => seen.push(p));
    await page.evaluate(() => {
      const original = window.api.listRows;
      window.api.listRows = (id, q) => { window.__seenPriority(q.priority); return original(id, q); };
    });
    await prioritySelect(page).selectOption("rom");
    await expect.poll(() => seen.includes("rom")).toBe(true);
  });

  test("Archive 탭에는 우선 정렬이 없다(present/hasMetadata가 항상 참이라 뜻이 없다)", async ({ page }) => {
    await page.locator(".ctab.archive").click();
    await expect(prioritySelect(page)).toHaveCount(0);
  });
});

test.describe("Settings의 기본값", () => {
  test("Settings에서 정한 기본값으로 Collection이 열린다", async ({ page }) => {
    await page.addInitScript(() => {
      window.__RMS_MOCK_APP_SETTINGS = { navigation: { defaultSortPriority: "media" } };
    });
    await openApp(page);
    await expect(prioritySelect(page)).toHaveValue("media");
    const files = await rowFiles(page);
    expect(files[0]).toBe("FFX.iso");
  });
});
