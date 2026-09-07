// Compare 화면 - 좌우 정렬, 스크롤 동기화, System 필터 (GameList 개선 요청 대응).
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator("#sidebar .nav-item").first()).toBeVisible();
  // 사이드바 고정 "Compare" 메뉴는 없어졌다 - SOURCE 카드의 "▼ 비교" 버튼으로 진입한다.
  await page.locator("#context-bar .context-card-compare-btn").first().click();
  await expect(page.locator(".compare-lists")).toBeVisible();
});

test("왼쪽에만 있는 항목은 오른쪽에 자리표시 행이 들어가 같은 줄에 맞춰진다", async ({ page }) => {
  // mock 데이터: row 0 = Super Mario World(양쪽 모두), row 1 = Zelda(왼쪽만).
  const leftRows = page.locator(".compare-list-panel").nth(0).locator(".compare-list-row");
  const rightRows = page.locator(".compare-list-panel").nth(1).locator(".compare-list-row");
  await expect(leftRows).toHaveCount(2);
  await expect(rightRows).toHaveCount(2);
  await expect(rightRows.nth(1)).toHaveClass(/compare-row-placeholder/);
  await expect(leftRows.nth(1)).not.toHaveClass(/compare-row-placeholder/);
});

test("SHA256 컬럼 - 값이 있으면 앞 10자만, 없으면 '-'로 표시한다", async ({ page }) => {
  // mock 데이터: row 0 = Super Mario World(양쪽 다 SHA256 있음, 64자),
  // row 1 = Zelda(왼쪽만 있고, sha256은 null).
  const leftRows = page.locator(".compare-list-panel").nth(0).locator(".compare-list-row");
  const rightRows = page.locator(".compare-list-panel").nth(1).locator(".compare-list-row");

  // 앞 10자만 표시 - 64자 전체가 아니다.
  await expect(leftRows.nth(0).locator(".compare-row-sha256")).toHaveText("A3F91C82E7");
  await expect(rightRows.nth(0).locator(".compare-row-sha256")).toHaveText("A3F91C82E7");
  // 전체 64자 값은 title(hover)에 남아있어야 한다.
  await expect(leftRows.nth(0).locator(".compare-row-sha256")).toHaveAttribute(
    "title", "A3F91C82E7B4D65091AA2FDC5E6B7A8901234567890ABCDEF1234567890ABCD"
  );

  // SHA256이 없는(null) 행은 "-"로 표시된다.
  await expect(leftRows.nth(1).locator(".compare-row-sha256")).toHaveText("-");
});

test("Compare 화면에서도 사이드바에 SYSTEM이 표시된다", async ({ page }) => {
  await expect(page.locator("#sidebar .nav-section-label", { hasText: "SYSTEM" })).toBeVisible();
  await expect(page.locator("#sidebar").getByText("snes", { exact: false })).toBeVisible();
});

test("관계 필터(=)로 좁힌 상태에서 Ctrl+A는 필터 이전의 숨겨진 행까지 선택하지 않는다", async ({ page }) => {
  // [리뷰 반영] mock 데이터: row 0 = Super Mario World(양쪽 모두, "="), row 1 =
  // Zelda(왼쪽만, "≠/한쪽만"). 관계 필터를 "="로 좁히면 화면엔 Mario 1행만 남아야
  // 하고, 그 상태에서 Ctrl+A를 누르면 딱 그 1개만 선택돼야 한다 - 예전엔 Ctrl+A가
  // search/system만 반영하고 관계 필터/즐겨찾기는 무시해서, 화면엔 안 보이는
  // Zelda까지 선택된 채로 일괄 복사가 가능했다.
  await page.locator(".compare-rel-toggle button").nth(2).click(); // "="
  const leftRows = page.locator(".compare-list-panel").nth(0).locator(".compare-list-row");
  await expect(leftRows).toHaveCount(1);

  await page.keyboard.press("Control+a");
  await expect(page.locator(".compare-list-panel").nth(0).locator(".compare-list-row.selected")).toHaveCount(1);
  // 선택 개수는 ">" 버튼의 title에 반영된다 - 필터로 숨겨진 Zelda까지 선택 Set에
  // 들어가 있으면(버그) 화면엔 행이 1개뿐이라도 여기 "2개"로 새 나온다.
  const toRightBtn = page.locator(".compare-center-bulk-actions button").first();
  await expect(toRightBtn).toHaveAttribute("title", "선택한 1개를 오른쪽으로 복사");
});

test("비교 종료 버튼은 진입 직전 화면으로 돌아간다(하드코딩된 ArchiveDB가 아니라)", async ({ page }) => {
  // [리뷰 반영] Compare 화면 자체에 나가는 버튼이 없었다. beforeEach는 기본 화면
  // (masterdb)에서 진입하므로 여기선 일부러 GameListSet(Local 1)에서 진입해서,
  // "비교 종료"가 고정된 masterdb가 아니라 실제 진입 직전 화면(Local 1)으로
  // 돌아가는지 확인한다.
  await page.locator("#sidebar").getByRole("button", { name: "Local 1", exact: true }).click();
  await expect(page.locator("#context-bar")).toBeVisible();
  await page.locator("#context-bar .context-card-compare-btn").first().click();
  await expect(page.locator(".compare-lists")).toBeVisible();

  await page.locator(".compare-exit-btn").click();
  await expect(page.locator(".compare-lists")).toBeHidden();
  await expect(page.locator("#sidebar .nav-item-local.active")).toBeVisible();
});

test("선택된 행이 있으면 Esc 한 번은 선택만 해제하고, 선택이 없을 때 Esc를 누르면 비교를 종료한다", async ({ page }) => {
  await page.locator(".compare-list-panel").nth(0).locator(".compare-list-row").first().click();
  await expect(page.locator(".compare-list-row.selected")).toHaveCount(1);

  await page.keyboard.press("Escape");
  await expect(page.locator(".compare-list-row.selected")).toHaveCount(0);
  await expect(page.locator(".compare-lists")).toBeVisible(); // 아직 Compare 안에 있어야 함

  await page.keyboard.press("Escape");
  await expect(page.locator(".compare-lists")).toBeHidden();
});

test("왼쪽 목록을 스크롤하면 오른쪽도 같은 위치로 스크롤된다", async ({ page }) => {
  const leftList = page.locator(".compare-list").nth(0);
  const rightList = page.locator(".compare-list").nth(1);
  // 목록에 스크롤 가능한 여유가 없어도 scrollTop 대입 자체는 통과시키고, 동기화
  // 로직이 그 값을 그대로 반대쪽에 반영하는지만 검증한다.
  const leftScrollTop = await leftList.evaluate((el) => {
    el.scrollTop = 5;
    el.dispatchEvent(new Event("scroll"));
    return el.scrollTop;
  });
  const rightScrollTop = await rightList.evaluate((el) => el.scrollTop);
  expect(rightScrollTop).toBe(leftScrollTop);
});

// [리뷰 반영, 2026-09-02] 아래 4개는 다른 AI 리뷰가 지적한 P1 항목들에 대한
// 회귀 테스트다. beforeEach 진입 상태는 sourceA=Local 1, sourceB=ArchiveDB
// (둘 다 snes 행만 가짐) - Local 2("l2")는 snes가 전혀 없는 genesis 전용 목업이라
// "새 소스 조합에 없는 System" 시나리오와 "메타데이터가 다른(diff) 행" 시나리오를
// 재현하는 용도로 api-client.js 목업에 추가했다.

test("[리뷰 P1-1] 소스 변경 메뉴에서 반대편과 같은 소스는 disabled로 표시되고 선택할 수 없다", async ({ page }) => {
  const leftTitle = page.locator(".compare-list-title").nth(0);
  await leftTitle.locator(".compare-title-dropdown-btn").click();
  const menu = page.locator(".dropdown-menu");
  // 오른쪽에 이미 ArchiveDB가 선택돼 있으니, 왼쪽 메뉴에서 ArchiveDB는 disabled여야 한다.
  const archiveDbItem = menu.getByRole("button", { name: "ArchiveDB", exact: true });
  await expect(archiveDbItem).toBeDisabled();
  // Local 2는 반대편과 다른 소스이므로 그대로 선택 가능해야 한다.
  await expect(menu.getByRole("button", { name: "Local 2", exact: true })).toBeEnabled();
});

test("[리뷰 P1-2] 소스를 바꿔 새 조합에 없는 System을 필터링 중이면 자동으로 전체로 돌아간다", async ({ page }) => {
  const systemBtn = page.locator(".compare-filter-bar .dropdown > button").first();
  await systemBtn.click();
  await page.locator(".compare-filter-bar .dropdown-menu button", { hasText: "snes" }).click();
  await expect(systemBtn).toContainText("snes");

  // 오른쪽 소스를 snes가 전혀 없는 Local 2로 바꾼다.
  const rightTitle = page.locator(".compare-list-title").nth(1);
  await rightTitle.locator(".compare-title-dropdown-btn").click();
  await page.locator(".dropdown-menu").getByRole("button", { name: "Local 2", exact: true }).click();

  // "표시할 항목이 없습니다"로 조용히 막히는 대신 System 필터가 전체로 풀려야 한다.
  await expect(systemBtn).toContainText("전체");
  await expect(page.locator(".compare-empty", { hasText: "표시할 항목이 없습니다" })).toHaveCount(0);
});

test("[리뷰 P1-3] 메타데이터가 다른(≠) 행은 hover해야 </> 복사 버튼이 나타나고, 누르면 그 방향으로 복사된다", async ({ page }) => {
  const rightTitle = page.locator(".compare-list-title").nth(1);
  await rightTitle.locator(".compare-title-dropdown-btn").click();
  await page.locator(".dropdown-menu").getByRole("button", { name: "Local 2", exact: true }).click();

  const diffCell = page.locator(".compare-center-cell.diff");
  await expect(diffCell).toHaveCount(1);
  const toRightBtn = diffCell.locator(".compare-center-diff-btn").nth(1);
  await expect(toRightBtn).toBeHidden(); // 기본 상태에선 ≠ 문자만 보이고 버튼은 숨어있다.
  await diffCell.hover();
  await expect(toRightBtn).toBeVisible();
  await toRightBtn.click();
  await expect(page.locator("#toast")).toContainText("복사되었습니다");
});

test("[리뷰 P1/P2-6] Ctrl+A는 마지막으로 다루던 쪽만 전체 선택하고 반대쪽은 그대로 둔다", async ({ page }) => {
  // row 0(Super Mario World)만 양쪽에 다 있다 - 오른쪽 행을 먼저 클릭해 그쪽을
  // "마지막으로 다루던 쪽"으로 만든다.
  const rightRows = page.locator(".compare-list-panel").nth(1).locator(".compare-list-row");
  await rightRows.first().click();
  await expect(rightRows.first()).toHaveClass(/selected/);

  await page.keyboard.press("Control+a");
  // 예전엔 왼쪽/오른쪽을 동시에 전체 선택했다 - 왼쪽엔 Zelda(왼쪽만 있음)까지
  // 있어서, 고치기 전엔 여기서 왼쪽도 선택된 채로 나왔다.
  await expect(page.locator(".compare-list-panel").nth(0).locator(".compare-list-row.selected")).toHaveCount(0);
  await expect(page.locator(".compare-list-panel").nth(1).locator(".compare-list-row.selected")).toHaveCount(1);
});
