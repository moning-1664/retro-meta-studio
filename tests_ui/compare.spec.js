// Compare Mode (스펙 §54-59, 사용자 결정 2026-09-17 ~ 09-20).
//
// 별도 화면이 아니라 **기존 Gamelist가 비교 모드로 바뀌는 것**이 핵심이다. 그래서 여기서는
// "비교 막대가 한 줄로 생기고, 가운데가 좌/우 짝의 목록이 되고, 양옆에 Detail이 하나씩 열리고,
// Exit하면 원래대로 돌아온다"를 확인한다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

/** 탭 우클릭 → 기준 지정 → 다른 탭 우클릭 → 비교 시작. */
async function startCompare(page) {
  await page.locator(".ctab-add").click();
  await page.locator(".add-collection-history summary").click();
  await page.locator(".picker-row", { hasText: "Android ES-DE" }).click();
  await expect(page.locator(".ctab:not(.archive)")).toHaveCount(2);

  await page.locator(".ctab", { hasText: "Master Library" }).click({ button: "right" });
  await page.locator(".ctx-menu .ctx-item", { hasText: "Compare 기준으로 지정" }).click();
  await expect(page.locator("#toast")).toContainText("비교 기준으로 지정");

  await page.locator(".ctab", { hasText: "Android ES-DE" }).click({ button: "right" });
  await page.locator(".ctx-menu .ctx-item", { hasText: "와 비교" }).click();
  await expect(page.locator("#filter-bar.compare")).toBeVisible();
}

/** 이름 칸을 눌러 상세를 연다 - 가운데 연산자 칸은 누르면 Plan으로 보내기 때문이다. */
const openDetail = (page, text) =>
  page.locator(".lrow", { hasText: text }).locator(".lc-srcTitle, .lc-dstTitle").first().click();

test("기준을 정하기 전에는 '비교' 항목이 나오지 않는다", async ({ page }) => {
  await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
  await expect(page.locator(".ctx-menu .ctx-item", { hasText: "Compare 기준으로 지정" })).toBeVisible();
  await expect(page.locator(".ctx-menu .ctx-item", { hasText: "와 비교" })).toHaveCount(0);
});

test.describe("상단 막대", () => {
  test("한 줄이고, 어느 Collection끼리인지와 Snapshot은 적지 않는다", async ({ page }) => {
    await startCompare(page);
    const bar = page.locator("#filter-bar.compare");
    await expect(bar.locator(".compare-select")).toBeVisible();
    await expect(bar.locator(".cmp-group-btn")).toHaveCount(3);
    await expect(bar.locator(".cmp-tool")).toHaveCount(2);
    await expect(bar.locator(".cmp-exit")).toBeVisible();
    await expect(bar).not.toContainText("Snapshot");
    await expect(bar).not.toContainText("Master Library");
    // 한 줄: 모든 컨트롤의 세로 위치가 겹친다.
    const tops = await bar.locator(".compare-select, .cmp-group, .cmp-tool, .cmp-exit")
      .evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)));
    expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(3);
  });

  test("Exit Compare는 오른쪽 끝에 붙고 글자는 가운데다", async ({ page }) => {
    await startCompare(page);
    const exit = page.locator(".cmp-exit");
    const bar = await page.locator("#filter-bar").boundingBox();
    const box = await exit.boundingBox();
    expect(bar.x + bar.width - (box.x + box.width)).toBeLessThan(24);
    expect(await exit.evaluate((el) => getComputedStyle(el).justifyContent)).toBe("center");
  });

  test("드롭다운과 아이콘 그룹이 목록을 실제로 좁힌다", async ({ page }) => {
    await startCompare(page);
    await expect(page.locator(".lrow")).toHaveCount(5);

    await page.locator(".compare-select").selectOption("conflict");
    await expect(page.locator(".lrow")).toHaveCount(2);
    await page.locator(".compare-select").selectOption("only_a");
    await expect(page.locator(".lrow").first()).toContainText("Only Base");
    await page.locator(".compare-select").selectOption("media");
    await expect(page.locator(".lrow").first()).toContainText("Media Only");

    await page.locator(".cmp-group-btn.g-same").click();     // =
    await expect(page.locator(".lrow")).toHaveCount(1);
    await page.locator(".cmp-group-btn.g-diff").click();     // ≠ > <
    await expect(page.locator(".lrow")).toHaveCount(4);
    await page.locator(".cmp-group-btn.g-all").click();      // *
    await expect(page.locator(".lrow")).toHaveCount(5);
  });

  test("Swap은 기준과 상대를 바꿔 다시 비교한다", async ({ page }) => {
    await startCompare(page);
    await page.evaluate(() => {
      window.__cmp = [];
      const original = window.api.startCompare;
      window.api.startCompare = (a, b) => { window.__cmp.push([a, b]); return original(a, b); };
    });
    await page.locator(".cmp-tool", { hasText: "Swap" }).click();
    await expect.poll(() => page.evaluate(() => window.__cmp.length)).toBe(1);
    const [[base, other]] = await page.evaluate(() => window.__cmp);
    expect([base, other]).toEqual(["c2", "c1"]);
    await expect(page.locator("#filter-bar.compare")).toBeVisible();
  });

  test("새로고침으로 다시 비교해도 비교 상태가 유지된다", async ({ page }) => {
    await startCompare(page);
    await page.locator(".cmp-tool", { hasText: "새로고침" }).click();
    await expect(page.locator("#filter-bar.compare")).toBeVisible();
    await expect(page.locator(".lrow")).toHaveCount(5);
  });
});

test.describe("가운데 Gamelist", () => {
  test("좌/우 각자의 File | Title과 연산자가 한 행에 나온다", async ({ page }) => {
    await startCompare(page);
    const heads = await page.locator("#list-head .lh").allInnerTexts();
    expect(heads).toEqual(["No.", "File", "Title", "", "File", "Title"]);
    // 짝이 이름 정규화로 맺어져 파일명이 서로 다른 행 - 양쪽에 같은 값이 찍히면 안 된다.
    const row = page.locator(".lrow", { hasText: "Media Only" });
    await expect(row.locator(".lc-srcFile")).toHaveText("MediaOnly.iso");
    await expect(row.locator(".lc-dstFile")).toHaveText("MediaOnly (USA).iso");
    await expect(row.locator(".lc-srcTitle")).toContainText("Media Only");
    await expect(row.locator(".lc-dstTitle")).toContainText("Media Only (USA)");
  });

  test("연산자: = ≠ > < 가 행마다 다르게 붙는다", async ({ page }) => {
    await startCompare(page);
    await expect(page.locator(".lrow.s-same .cmp-op.same")).toHaveText("=");
    await expect(page.locator(".lrow.s-only_a .cmp-op.one-side")).toHaveText(">");
    await expect(page.locator(".lrow.s-only_b .cmp-op.one-side")).toHaveText("<");
    await expect(page.locator(".lrow.s-conflict").first().locator(".cmp-op-symbol")).toHaveText("≠");
    // 미디어만 다른 행도 ≠다.
    await expect(page.locator(".lrow", { hasText: "Media Only" }).locator(".cmp-op-symbol")).toHaveText("≠");
  });

  test("ROM이 없는 쪽 칸은 비어 있다", async ({ page }) => {
    await startCompare(page);
    const only = page.locator(".lrow.s-only_a");
    await expect(only.locator(".lc-dstFile")).toHaveClass(/cmp-absent/);
    await expect(only.locator(".lc-dstTitle")).toHaveClass(/cmp-absent/);
    await expect(only.locator(".lc-srcFile")).not.toHaveClass(/cmp-absent/);
  });

  test("행이 헤더와 같은 컬럼 폭을 쓴다 - 글자가 겹치지 않는다", async ({ page }) => {
    await startCompare(page);
    const headCells = page.locator("#list-head .lh");
    const rowCells = page.locator(".lrow").first().locator(".lc");
    await expect(headCells).toHaveCount(await rowCells.count());
    const [headBoxes, rowBoxes] = await Promise.all([
      headCells.evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().x))),
      rowCells.evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().x))),
    ]);
    expect(rowBoxes).toEqual(headBoxes);
    expect(new Set(rowBoxes).size).toBe(rowBoxes.length);
  });

  test("창을 늘리면 목록이 넓어진다 - Detail이 아니라", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await startCompare(page);
    await openDetail(page, "Conflict Game");
    const measure = async () => ({
      list: (await page.locator("#list-window").boundingBox()).width,
      left: (await page.locator("#compare-left").boundingBox()).width,
      right: (await page.locator("#detail-panel").boundingBox()).width,
    });
    const narrow = await measure();
    await page.setViewportSize({ width: 1700, height: 800 });
    await expect.poll(async () => (await measure()).list).toBeGreaterThan(narrow.list + 200);
    const wide = await measure();
    expect(wide.left).toBe(narrow.left);
    expect(wide.right).toBe(narrow.right);
  });

  test("좌/우 Detail은 297px보다 15% 좁다", async ({ page }) => {
    await startCompare(page);
    await openDetail(page, "Conflict Game");
    expect(Math.round((await page.locator("#compare-left").boundingBox()).width)).toBe(252);
    expect(Math.round((await page.locator("#detail-panel").boundingBox()).width)).toBe(252);
  });
});

test.describe("연산자로 Plan에 올리기", () => {
  async function spy(page) {
    await page.evaluate(() => {
      window.__copied = [];
      const original = window.api.compareCopyRow;
      window.api.compareCopyRow = (key, direction, metadataOnly) => {
        window.__copied.push({ key, direction, metadataOnly });
        return original(key, direction, metadataOnly);
      };
    });
  }

  test("> 는 ROM+메타데이터를 오른쪽 Plan에 올린다", async ({ page }) => {
    await startCompare(page);
    await spy(page);
    await page.locator(".lrow.s-only_a .cmp-op.one-side").click();
    await expect(page.locator("#toast")).toContainText("Plan에 올렸습니다");
    expect(await page.evaluate(() => window.__copied))
      .toEqual([{ key: "ps2|OnlyBase.iso", direction: "toRight", metadataOnly: false }]);
    // 눌러도 상세가 열리지 않는다.
    await expect(page.locator("#detail-panel")).not.toHaveClass(/open/);
  });

  test("< 는 왼쪽으로 보낸다", async ({ page }) => {
    await startCompare(page);
    await spy(page);
    await page.locator(".lrow.s-only_b .cmp-op.one-side").click();
    expect(await page.evaluate(() => window.__copied))
      .toEqual([{ key: "ps2|OnlyOther.iso", direction: "toLeft", metadataOnly: false }]);
  });

  test("≠ 는 평소엔 기호만 보이고 hover하면 양옆 화살표가 나와 메타데이터만 보낸다", async ({ page }) => {
    await startCompare(page);
    await spy(page);
    const row = page.locator(".lrow.s-conflict", { hasText: "Conflict Game" });
    await expect(row.locator(".cmp-op-arrow").first()).toBeHidden();
    await row.hover();
    await expect(row.locator(".cmp-op-arrow")).toHaveCount(2);
    await expect(row.locator(".cmp-op-arrow").first()).toBeVisible();
    await row.locator(".cmp-op-arrow").nth(1).click();                    // 오른쪽 화살표
    expect(await page.evaluate(() => window.__copied))
      .toEqual([{ key: "ps2|Conflict.iso", direction: "toRight", metadataOnly: true }]);
  });

  test("Plan에 올린 행은 다시 누르지 않도록 표시가 바뀐다", async ({ page }) => {
    await startCompare(page);
    await page.locator(".lrow.s-only_a .cmp-op.one-side").click();
    await expect(page.locator(".lrow.s-only_a .cmp-op.planned")).toBeVisible();
    await expect(page.locator(".lrow.s-only_a .cmp-op.one-side")).toHaveCount(0);
  });
});

test.describe("좌/우 Detail", () => {
  test("행을 고르면 양옆에 Detail이 하나씩 열리고 각자의 Collection 이름이 머리에 있다", async ({ page }) => {
    await startCompare(page);
    await openDetail(page, "Conflict Game");
    await expect(page.locator("#compare-left .detail-eyebrow")).toHaveText("Master Library");
    await expect(page.locator("#detail-panel .detail-eyebrow")).toHaveText("Android ES-DE");
  });

  test("다른 값만 노란색으로 표시된다", async ({ page }) => {
    await startCompare(page);
    await openDetail(page, "Conflict Game");
    for (const side of ["#compare-left", "#detail-panel"]) {
      const changed = page.locator(`${side} .cmp-card.changed`);
      await expect(changed).toHaveCount(1);
      await expect(changed).toContainText("Genre");
    }
    await expect(page.locator("#compare-left .cmp-card.changed")).toContainText("RPG");
    await expect(page.locator("#detail-panel .cmp-card.changed")).toContainText("Action");
  });

  test("탭을 누르면 반대쪽도 같이 바뀐다", async ({ page }) => {
    await startCompare(page);
    await openDetail(page, "Conflict Game");
    await page.locator("#compare-left .detail-tab", { hasText: "Media" }).click();
    await expect(page.locator("#detail-panel .detail-tab.active")).toHaveText("Media");
    await page.locator("#detail-panel .detail-tab", { hasText: "ROM" }).click();
    await expect(page.locator("#compare-left .detail-tab.active")).toHaveText("ROM");
    await expect(page.locator("#compare-left .cmp-block", { hasText: "File" })).toBeVisible();
  });

  test("Metadata: Description은 12줄로 고정하고 카드는 한 줄에 둘이다", async ({ page }) => {
    await startCompare(page);
    await openDetail(page, "Conflict Game");
    const desc = page.locator("#compare-left .cmp-desc");
    expect(await desc.evaluate((el) => getComputedStyle(el).webkitLineClamp)).toBe("12");
    const cols = await page.locator("#compare-left .cmp-cards")
      .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
    expect(cols).toBe(2);
    // 아래에 Cover(세로)와 Screenshot(가로)이 나란히 있다. TitleScreen은 없다.
    await expect(page.locator("#compare-left .cmp-media-pair .cmp-tile")).toHaveCount(2);
    await expect(page.locator("#compare-left .cmp-media-pair")).not.toContainText("TitleScreen");
  });

  test("Media: cover / screenshot / marquee+mixImage+3dbox 순이고 비율이 고정이다", async ({ page }) => {
    await startCompare(page);
    await openDetail(page, "Conflict Game");
    await page.locator("#compare-left .detail-tab", { hasText: "Media" }).click();
    const rows = page.locator("#compare-left .cmp-media-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0).locator(".cmp-tile")).toHaveCount(1);
    await expect(rows.nth(1).locator(".cmp-tile")).toHaveCount(1);
    await expect(rows.nth(2).locator(".cmp-tile")).toHaveCount(3);
    const ratio = async (locator) => locator.evaluate((el) => {
      const r = el.getBoundingClientRect(); return Math.round((r.width / r.height) * 100) / 100;
    });
    expect(await ratio(rows.nth(0).locator(".cmp-tile-box"))).toBeCloseTo(0.75, 1);   // 3:4 세로
    expect(await ratio(rows.nth(1).locator(".cmp-tile-box"))).toBeCloseTo(1.33, 1);   // 4:3 가로
    for (let i = 0; i < 3; i += 1) {
      expect(await ratio(rows.nth(2).locator(".cmp-tile-box").nth(i))).toBeCloseTo(1, 1); // 1:1
    }
  });

  test("미디어만 다른 행은 그 미디어에 노란 테두리가 붙는다", async ({ page }) => {
    await startCompare(page);
    await openDetail(page, "Media Only");
    await page.locator("#compare-left .detail-tab", { hasText: "Media" }).click();
    await expect(page.locator("#compare-left .cmp-tile.changed")).toHaveCount(1);
    await expect(page.locator("#compare-left .cmp-tile.changed")).toContainText("Cover");
  });

  test("한쪽에 ROM이 없으면 그 쪽 Detail이 그 사실을 알려 준다", async ({ page }) => {
    await startCompare(page);
    await page.locator(".compare-select").selectOption("only_a");
    await openDetail(page, "Only Base");
    await expect(page.locator("#detail-panel .cmp-absent-note")).toBeVisible();
    await expect(page.locator("#compare-left .cmp-absent-note")).toHaveCount(0);
  });
});

test("Exit Compare로 원래 Gamelist가 돌아온다", async ({ page }) => {
  await startCompare(page);
  await openDetail(page, "Conflict Game");
  await page.locator(".cmp-exit").click();
  await expect(page.locator("#filter-bar.compare")).toHaveCount(0);
  await expect(page.locator(".search-input")).toBeVisible();
  await expect(page.locator(".lrow")).toHaveCount(3);
  await expect(page.locator("#compare-left")).toBeHidden();
});

test("Compare는 읽기 전용이다 - 변경 버튼이 사라진다", async ({ page }) => {
  const sendIcon = page.locator("#collection-header .icon-btn[title*='메타데이터 보내기']");
  await expect(sendIcon).toBeVisible();
  await startCompare(page);
  await expect(sendIcon).toHaveCount(0);
  await expect(page.locator("#detail-top .detail-topspace")).toContainText("읽기 전용");
  await expect(page.locator(".sb-actions .btn")).toHaveCount(0);
});

test("Compare 중에는 Delete 단축키도 거절 안내를 낸다", async ({ page }) => {
  await startCompare(page);
  await openDetail(page, "Conflict Game");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Delete");
  await expect(page.locator("#toast")).toContainText("Compare 중에는");
});

test("Compare 중에는 System을 끌어 옮길 수 없다", async ({ page }) => {
  await startCompare(page);
  await expect(page.locator(".nav-system").first()).not.toHaveAttribute("draggable", "true");
  await expect(page.locator(".nav-action", { hasText: "Add External Storage" })).toHaveCount(0);
});
