// Gamelist 컬럼 - 이전 프로젝트에서 되찾아온 것들 (Phase 7.16).
//
// 이전 프로젝트(RetroGameManager / fix/ahnlab-mass-file-access)의 목록은
// **설명 위주**였고, Header로 정렬하고, 컬럼 폭을 끌어서 맞추고, 탐색기처럼
// 여러 개를 골랐다. 여기서는 그것이 다시 동작하는지 본다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const HEADERS = ["No.", "File", "Title", "Description", "Region", "Rating", "★", "Genre", "Status"];

test.describe("컬럼 구성", () => {
  test("이전 프로젝트의 아홉 개 컬럼이 그대로 있다", async ({ page }) => {
    const labels = await page.locator("#list-head .lh").allTextContents();
    expect(labels.map((t) => t.trim())).toEqual(HEADERS);
  });

  test("체크박스와 System 컬럼은 없다", async ({ page }) => {
    // 둘 다 사용자가 빼 달라고 한 것이다. 체크박스는 수천 개 목록에서 쓸 수 없고,
    // System은 좌측 내비게이션이 이미 말하고 있다.
    await expect(page.locator(".lrow input[type=checkbox]")).toHaveCount(0);
    await expect(page.locator("#list-head .lh-system")).toHaveCount(0);
  });

  test("행에 설명이 실제로 보인다", async ({ page }) => {
    // 목록만 훑어도 어떤 게임인지 알 수 있어야 한다 - 이것이 이전 목록의 핵심이었다.
    await expect(page.locator(".lrow").first().locator(".lc-desc"))
      .toContainText("스피라");
  });

  test("Description 컬럼이 가장 넓다", async ({ page }) => {
    const widths = await page.locator("#list-head").evaluate(
      (el) => getComputedStyle(el).gridTemplateColumns.split(" ").map(parseFloat));
    const desc = widths[HEADERS.indexOf("Description")];
    expect(Math.max(...widths)).toBeCloseTo(desc, 0);
  });

  test("헤더와 행의 컬럼 폭이 서로 맞는다", async ({ page }) => {
    const head = await page.locator("#list-head").evaluate(
      (el) => getComputedStyle(el).gridTemplateColumns);
    const row = await page.locator(".lrow").first().evaluate(
      (el) => getComputedStyle(el).gridTemplateColumns);
    expect(row).toBe(head);
  });
});

test.describe("Header 정렬", () => {
  test("한 번 누르면 오름차순 표시가 붙는다", async ({ page }) => {
    await page.locator(".lh-file").click();
    await expect(page.locator(".lh-file")).toHaveClass(/sorted/);
  });

  test("다시 누르면 내림차순으로 바뀐다", async ({ page }) => {
    const requests = [];
    await page.exposeFunction("__note", (d) => requests.push(d));
    await page.evaluate(() => {
      const original = window.api.listRows;
      window.api.listRows = (id, q) => { window.__note(!!q.descending); return original(id, q); };
    });

    await page.locator(".lh-file").click();
    await expect.poll(() => requests.length).toBeGreaterThan(0);
    await page.locator(".lh-file").click();
    await expect.poll(() => requests.at(-1)).toBe(true);
  });

  test("정렬 셀렉트와 방향 버튼은 없앴다", async ({ page }) => {
    // Header로 정렬하므로 따로 둘 이유가 없다.
    const titles = await page.locator("#filter-bar select").evaluateAll(
      (els) => els.map((e) => e.title));
    expect(titles).not.toContain("정렬");
  });

  test("No.와 ★는 정렬 대상이 아니다", async ({ page }) => {
    await page.locator(".lh-no").click();
    await expect(page.locator(".lh-no")).not.toHaveClass(/sorted/);
  });
});

test.describe("컬럼 폭 조절", () => {
  test("폭을 조절할 수 있는 컬럼에는 손잡이가 있다", async ({ page }) => {
    // No. / ★ / Status는 고정폭이라 손잡이가 없다.
    await expect(page.locator("#list-head .col-resize")).toHaveCount(HEADERS.length - 3);
    await expect(page.locator(".lh-no .col-resize")).toHaveCount(0);
  });

  test("끌면 그 컬럼이 넓어진다", async ({ page }) => {
    const widthOf = () => page.locator("#list-head").evaluate(
      (el) => parseFloat(getComputedStyle(el).gridTemplateColumns.split(" ")[1]));
    const before = await widthOf();

    const handle = page.locator(".lh-file .col-resize");
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2, { steps: 5 });
    await page.mouse.up();

    expect(await widthOf()).toBeGreaterThan(before + 40);
  });

  test("바꾼 폭을 저장한다", async ({ page }) => {
    const saved = [];
    await page.exposeFunction("__saved", (s) => saved.push(s));
    await page.evaluate(() => {
      const original = window.api.saveUiState;
      window.api.saveUiState = (id, state) => { window.__saved(state); return original(id, state); };
    });

    const handle = page.locator(".lh-title .col-resize");
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2, { steps: 4 });
    await page.mouse.up();

    // 앱을 닫아도 남아야 하므로 저장 요청이 나가야 한다.
    await expect.poll(() => saved.length, { timeout: 3000 }).toBeGreaterThan(0);
    expect(saved.at(-1).colWidths).toHaveProperty("title");
  });
});

test.describe("즐겨찾기", () => {
  test("행에서 바로 별표를 켜고 끌 수 있다", async ({ page }) => {
    const star = page.locator(".lrow").first().locator(".fav-btn");
    await expect(star).toHaveText("★");          // 목업의 첫 행은 즐겨찾기다
    await star.click();
    await expect(star).toHaveText("☆");
  });

  test("별표를 눌러도 상세 패널이 열리지 않는다", async ({ page }) => {
    await page.locator(".lrow").first().locator(".fav-btn").click();
    await expect(page.locator("#detail-panel")).not.toHaveClass(/open/);
  });

  test("즐겨찾기만 보기 버튼이 있다", async ({ page }) => {
    await expect(page.locator("#filter-bar .icon-btn[title*='즐겨찾기']")).toBeVisible();
  });
});

test.describe("툴바", () => {
  test("Plan 조작이 목록 위에 있다", async ({ page }) => {
    // 하단 상태바에 있으면 고른 항목과 멀어 보인다. Apply/Cancel은 한 그룹이다
    // (Auto Plan 토글은 실사용 시나리오가 확인되기 전까지 화면에서 뺐다).
    await expect(page.locator("#filter-bar .plan-actions .seg-btn", { hasText: "Apply" })).toBeVisible();
    await expect(page.locator("#filter-bar .plan-actions .seg-btn", { hasText: "Cancel" })).toBeVisible();
  });

  test("목록/카드 전환과 새로고침이 있다", async ({ page }) => {
    await expect(page.locator("#filter-bar .view-mode-seg .seg-btn")).toHaveCount(2);
    await expect(page.locator("#filter-bar .icon-btn[title='다시 스캔']")).toBeVisible();
  });
});
