// Compare Mode (스펙 §54-59).
//
// 별도 화면이 아니라 **기존 Gamelist가 비교 모드로 바뀌는 것**이라는 점이 이 화면의
// 핵심이다. 그래서 여기서는 "비교 막대가 생기고, 같은 목록 자리가 비교 행으로 바뀌고,
// Exit하면 원래대로 돌아온다"를 확인한다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

/** 탭 우클릭 → 기준 지정 → 다른 탭 우클릭 → 비교 시작. */
async function startCompare(page) {
  // 비교하려면 탭이 둘 있어야 한다.
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

test("기준을 정하기 전에는 '비교' 항목이 나오지 않는다", async ({ page }) => {
  await page.locator(".ctab:not(.archive)").first().click({ button: "right" });
  await expect(page.locator(".ctx-menu .ctx-item", { hasText: "Compare 기준으로 지정" })).toBeVisible();
  await expect(page.locator(".ctx-menu .ctx-item", { hasText: "와 비교" })).toHaveCount(0);
});

test("비교를 시작하면 두 Collection 이름과 필터가 막대에 뜬다", async ({ page }) => {
  await startCompare(page);
  await expect(page.locator(".compare-eyebrow")).toHaveText("COMPARE");
  await expect(page.locator(".compare-title")).toContainText("Master Library");
  await expect(page.locator(".compare-title")).toContainText("Android ES-DE");
  await expect(page.locator(".compare-filter")).toHaveCount(6);
  await expect(page.locator(".compare-filter.active")).toContainText("All");
});

test("필터 버튼이 개수를 보여주고 목록을 실제로 좁힌다", async ({ page }) => {
  await startCompare(page);
  await expect(page.locator(".lrow")).toHaveCount(5);

  await page.locator(".compare-filter", { hasText: "Conflict" }).click();
  await expect(page.locator(".lrow")).toHaveCount(1);
  await expect(page.locator(".lrow").first()).toContainText("Conflict Game");

  await page.locator(".compare-filter", { hasText: "Only A" }).click();
  await expect(page.locator(".lrow").first()).toContainText("Only Base");

  await page.locator(".compare-filter", { hasText: "Media" }).click();
  await expect(page.locator(".lrow").first()).toContainText("Media Only");

  await page.locator(".compare-filter", { hasText: "All" }).click();
  await expect(page.locator(".lrow")).toHaveCount(5);
});

test("상태 기호가 행마다 다르게 붙는다", async ({ page }) => {
  await startCompare(page);
  await expect(page.locator(".lrow.s-only_a .status-mark.del")).toHaveCount(1);
  await expect(page.locator(".lrow.s-only_b .status-mark.add")).toHaveCount(1);
  await expect(page.locator(".lrow.s-conflict .status-mark.warn")).toHaveCount(1);
});

test("행을 고르면 좌우를 나란히 놓은 상세가 열린다", async ({ page }) => {
  await startCompare(page);
  await page.locator(".lrow", { hasText: "Conflict Game" }).click();

  const panel = page.locator("#detail-panel");
  await expect(panel).toHaveClass(/open/);
  await expect(panel.locator(".detail-eyebrow")).toHaveText("COMPARE");
  await expect(panel.locator(".cmp-side-name").nth(0)).toContainText("Master Library");
  await expect(panel.locator(".cmp-side-name").nth(1)).toContainText("Android ES-DE");

  // 다른 값만 강조된다 - 같은 값까지 칠하면 어디가 다른지 보이지 않는다.
  // (파일명/크기 표는 별도이므로 Metadata 표만 센다.)
  const changed = panel.locator(".cmp-table:not(.cmp-identity) .cmp-row.changed");
  await expect(changed).toHaveCount(1);
  await expect(changed).toContainText("Genre");
  await expect(changed).toContainText("RPG");
  await expect(changed).toContainText("Action");
});

test("한쪽에만 있는 항목은 그 사실을 먼저 알려준다", async ({ page }) => {
  await startCompare(page);
  await page.locator(".compare-filter", { hasText: "Only A" }).click();
  await page.locator(".lrow").first().click();
  await expect(page.locator(".cmp-side-name.absent")).toHaveCount(1);
  await expect(page.locator(".cmp-side-name.absent")).toContainText("Android ES-DE");
});

test("Exit Compare로 원래 Gamelist가 돌아온다", async ({ page }) => {
  await startCompare(page);
  await page.locator("#filter-bar .btn", { hasText: "Exit Compare" }).click();
  await expect(page.locator("#filter-bar.compare")).toHaveCount(0);
  await expect(page.locator(".search-input")).toBeVisible();
  await expect(page.locator(".lrow")).toHaveCount(3);
});

test("Compare는 읽기 전용이다 - 변경 버튼이 사라진다", async ({ page }) => {
  // Apply/Delete/메타데이터 보내기는 선택이 없어도 눌리거나 위험한 동작이라,
  // 남겨두면 비교 화면에서 그대로 변경이 일어난다. 메타데이터 보내기/가져오기는
  // HERO(#collection-header)에 있다(§4·§6 - Detail 패널의 "Archive로"에서 옮겨왔다).
  const sendIcon = page.locator("#collection-header .icon-btn[title*='메타데이터 보내기']");
  await expect(sendIcon).toBeVisible();
  await startCompare(page);
  await expect(sendIcon).toHaveCount(0);
  await expect(page.locator("#detail-top .detail-topspace")).toContainText("읽기 전용");
  await expect(page.locator(".sb-actions .btn")).toHaveCount(0);
});

test("Compare 중에는 Delete 단축키도 거절 안내를 낸다", async ({ page }) => {
  await startCompare(page);
  await page.locator(".lrow").first().click();      // 포커스를 목록에 둔다
  await page.keyboard.press("Escape");
  await page.keyboard.press("Delete");
  await expect(page.locator("#toast")).toContainText("Compare 중에는");
});

test("Compare 중에는 System을 끌어 옮길 수 없다", async ({ page }) => {
  await startCompare(page);
  await expect(page.locator(".nav-system").first()).not.toHaveAttribute("draggable", "true");
  await expect(page.locator(".nav-action", { hasText: "Add External Storage" })).toHaveCount(0);
});

test("스냅샷 시각과 Refresh를 보여준다", async ({ page }) => {
  await startCompare(page);
  await expect(page.locator(".compare-snapshot")).toContainText("Snapshot");
  const refresh = page.locator("#filter-bar .btn", { hasText: "Refresh" });
  await expect(refresh).toBeVisible();
  // 다시 찍어도 화면이 비교 상태를 유지해야 한다.
  await refresh.click();
  await expect(page.locator("#filter-bar.compare")).toBeVisible();
  await expect(page.locator(".lrow")).toHaveCount(5);
});

test("상세가 값 비교보다 먼저 파일명/크기를 보여준다", async ({ page }) => {
  await startCompare(page);
  await page.locator(".lrow", { hasText: "Conflict Game" }).click();
  const identity = page.locator(".cmp-identity .cmp-row");
  await expect(identity).toHaveCount(2);
  await expect(identity.nth(0)).toContainText("File");
  // 같은 이름인데 크기가 다르면 다른 덤프일 수 있다 - 다른 값으로 표시된다.
  await expect(identity.nth(1)).toContainText("Size");
  await expect(identity.nth(1)).toHaveClass(/changed/);
});
