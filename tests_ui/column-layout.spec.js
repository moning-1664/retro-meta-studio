// GameList 컬럼 순서/표시 (stitch-v3 Phase 8).
//
// 머리글 드래그, 머리글 우클릭 메뉴, Settings 편집기가 **같은 설정 하나**
// (Settings > gamelist)를 바꾼다. No.는 항상 맨 앞이고 Title은 숨길 수 없다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const HEADERS = ["No.", "File", "Title", "Description", "Region", "Rating", "★", "Genre", "Status"];
const headLabels = async (page) => (await page.locator("#list-head .lh").allTextContents()).map((t) => t.trim());
const rowCellClasses = (page) => page.locator(".lrow").first().evaluate(
  (el) => [...el.children].map((c) => [...c.classList].find((k) => k.startsWith("lc-") && k !== "lc-text")));
const templatesMatch = async (page) => {
  const head = await page.locator("#list-head").evaluate((el) => getComputedStyle(el).gridTemplateColumns);
  const row = await page.locator(".lrow").first().evaluate((el) => getComputedStyle(el).gridTemplateColumns);
  return head === row;
};
const menuItem = (page, label) => page.locator(".ctx-menu .ctx-item", { hasText: label });

test.describe("머리글 우클릭 - 컬럼 표시", () => {
  test("컬럼을 끄면 머리글과 행에서 함께 빠지고 폭이 맞는다", async ({ page }) => {
    await page.locator(".lh-region").click({ button: "right" });
    await expect(page.locator(".ctx-title")).toHaveText("GameList 컬럼");
    await menuItem(page, "Region").click();
    await expect(page.locator("#list-head .lh-region")).toHaveCount(0);
    await expect(page.locator(".lrow .lc-region")).toHaveCount(0);
    expect(await templatesMatch(page)).toBe(true);

    await page.locator("#list-head").click({ button: "right" });
    await menuItem(page, "Region").click();
    await expect(page.locator("#list-head .lh-region")).toHaveCount(1);
  });

  test("Title은 숨길 수 없다", async ({ page }) => {
    await page.locator("#list-head").click({ button: "right" });
    await expect(menuItem(page, "Title")).toBeDisabled();
  });

  test("설정으로 저장한다", async ({ page }) => {
    await page.evaluate(() => {
      window.__saved = [];
      const original = window.api.saveAppSettings;
      window.api.saveAppSettings = (patch) => { window.__saved.push(patch); return original(patch); };
    });
    await page.locator("#list-head").click({ button: "right" });
    await menuItem(page, "Genre").click();
    await expect.poll(() => page.evaluate(() => window.__saved.length)).toBeGreaterThan(0);
    const saved = await page.evaluate(() => window.__saved.at(-1));
    expect(saved.gamelist.hidden).toEqual(["genre"]);
  });
});

test.describe("머리글 드래그 - 컬럼 순서", () => {
  // 모든 머리글이 가로 스크롤 없이 보이게 한다 - 드래그 도중 스크롤이 생기면 놓는 좌표가 어긋난다.
  test.use({ viewport: { width: 2200, height: 900 } });

  test("Genre를 File 앞에 놓으면 머리글과 행이 같은 순서가 된다", async ({ page }) => {
    await page.locator(".lh-genre").dragTo(page.locator(".lh-file"), { targetPosition: { x: 4, y: 8 } });
    await expect.poll(() => headLabels(page)).toEqual(
      ["No.", "Genre", "File", "Title", "Description", "Region", "Rating", "★", "Status"]);
    expect((await rowCellClasses(page)).slice(0, 3)).toEqual(["lc-no", "lc-genre", "lc-file"]);
    expect(await templatesMatch(page)).toBe(true);
  });

  test("오른쪽 절반에 놓으면 그 뒤로 간다", async ({ page }) => {
    const target = page.locator(".lh-desc");
    const box = await target.boundingBox();
    await page.locator(".lh-file").dragTo(target, { targetPosition: { x: Math.round(box.width * 0.75), y: 8 } });
    await expect.poll(() => headLabels(page)).toEqual(
      ["No.", "Title", "Description", "File", "Region", "Rating", "★", "Genre", "Status"]);
  });

  test("No.는 끌 수 없고 늘 맨 앞이다", async ({ page }) => {
    await expect(page.locator(".lh-no")).toHaveAttribute("draggable", "false");
    await page.locator(".lh-title").dragTo(page.locator(".lh-no"), { targetPosition: { x: 2, y: 8 } });
    const labels = await headLabels(page);
    expect(labels[0]).toBe("No.");
  });

  test("끌어 옮겨도 정렬 클릭은 그대로 된다", async ({ page }) => {
    await page.locator(".lh-genre").dragTo(page.locator(".lh-file"), { targetPosition: { x: 4, y: 8 } });
    await page.locator(".lh-genre").click();
    await expect(page.locator(".lh-genre")).toHaveClass(/sorted/);
  });
});

test.describe("Settings - GameList Columns", () => {
  const openColumns = async (page) => {
    await page.locator(".settings-btn").click();
    await page.locator(".stg-nav-item[data-section='metadata']").click();
    await expect(page.locator(".stg-columns")).toBeVisible();
  };

  test("현재 순서대로 나열하고, No.와 Title은 끌 수 없다", async ({ page }) => {
    await openColumns(page);
    const ids = await page.locator(".stg-column-row").evaluateAll((rows) => rows.map((r) => r.dataset.column));
    expect(ids).toEqual(["no", "file", "title", "desc", "region", "rating", "fav", "genre", "status"]);
    await expect(page.locator(".stg-column-row[data-column='no'] input")).toBeDisabled();
    await expect(page.locator(".stg-column-row[data-column='title'] input")).toBeDisabled();
  });

  test("체크를 끄면 목록에서 바로 빠진다", async ({ page }) => {
    await openColumns(page);
    await page.locator(".stg-column-row[data-column='desc'] input").uncheck();
    await expect(page.locator("#list-head .lh-desc")).toHaveCount(0);
    await expect(page.locator(".stg-column-row[data-column='desc']")).toHaveClass(/off/);
  });

  test("☰ 손잡이를 끌어 순서를 바꾸고, 기본값으로 되돌린다", async ({ page }) => {
    await openColumns(page);
    await expect(page.locator(".stg-column-row .col-down, .stg-column-row .col-up")).toHaveCount(0);
    const grip = await page.locator(".stg-column-row[data-column='file'] .stg-column-grip").boundingBox();
    const title = page.locator(".stg-column-row[data-column='title']");
    const box = await title.boundingBox();
    await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 40, box.y + box.height * 0.8, { steps: 6 });
    await expect(title).toHaveClass(/drop-after/);
    await page.mouse.up();
    await expect.poll(() => headLabels(page)).toEqual(
      ["No.", "Title", "File", "Description", "Region", "Rating", "★", "Genre", "Status"]);
    await page.locator(".stg-column-row[data-column='desc'] input").uncheck();
    await page.locator(".stg-column-reset").click();
    await expect.poll(() => headLabels(page)).toEqual(HEADERS);
  });

  test("손잡이에 초점이 있으면 ↑↓ 키로 옮기고, No. 손잡이는 꺼져 있다", async ({ page }) => {
    await openColumns(page);
    await expect(page.locator(".stg-column-row[data-column='no'] .stg-column-grip")).toBeDisabled();
    await page.locator(".stg-column-row[data-column='file'] .stg-column-grip").focus();
    await page.keyboard.press("ArrowDown");
    await expect.poll(() => headLabels(page)).toEqual(
      ["No.", "Title", "File", "Description", "Region", "Rating", "★", "Genre", "Status"]);
    await expect(page.locator(".stg-column-row[data-column='file'] .stg-column-grip")).toBeFocused();
  });

  test("머리글 메뉴에서 Settings로 바로 간다", async ({ page }) => {
    await page.locator("#list-head").click({ button: "right" });
    await menuItem(page, "Settings에서 설정").click();
    await expect(page.locator(".stg-columns")).toBeVisible();
  });
});
