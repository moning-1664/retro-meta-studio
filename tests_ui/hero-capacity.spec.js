// HERO(Chromium 헤더)의 용량 그래프 - 실사용 피드백 §4.
//
// - ROM/Metadata(System 정보)와 Internal/External(Collection 정보) 사이를 |로
//   나누고, 두 그룹의 숫자 자리를 고정해 자리가 밀리지 않게 한다.
// - Internal/External 배지 밑에 목표 대비 사용률을 5단계 색(파랑>녹색>노랑>주황>
//   빨강)으로 보여준다. 목표는 Dashboard에서 정한다.
// - 목표를 넘으면 배지 뒤에 경고 아이콘이 뜬다.
// - Dashboard에서 목표를 바꾸면 HERO도 그 자리에서 바로 따라간다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const openDashboard = async (page) => {
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#dashboard-view .dsb-title")).toBeVisible();
};

const setTarget = async (page, storageId, bytes) => page.evaluate(
  ({ storageId, bytes }) => window.api.saveUiState("c1", { dashboardTargets: { [storageId]: bytes } }),
  { storageId, bytes });

// 이미 활성인 탭을 다시 눌러도 selectTab()은 아무 일도 하지 않는다(no-op 가드) -
// ui_state를 직접 바꾼 뒤 반영시키려면 다른 탭으로 갔다가 되돌아와야 한다.
const reopenToPickUpUiState = async (page) => {
  await page.locator(".ctab.archive").click();
  await page.locator(".ctab", { hasText: "Master Library" }).click();
};

test("ROM/Metadata와 Internal/External 사이에 | 구분선이 있다", async ({ page }) => {
  await expect(page.locator(".cheader-stats-divider")).toHaveText("|");
});

test("목표를 정하지 않은 Storage는 무채색이다(넘었다고 말할 수 없다)", async ({ page }) => {
  const badge = page.locator(".cheader-storage", { hasText: "내부" });
  await expect(badge).toHaveClass(/level-none/);
  await expect(badge.locator(".cheader-storage-warn")).not.toHaveClass(/on/);
});

test("목표를 넉넉히 넘겨 잡으면 여유(파랑) 단계다", async ({ page }) => {
  // External(ext-1) actualBytes는 mock에서 8.7GB다. 목표를 100GB로 넉넉히 잡는다.
  await setTarget(page, "ext-1", 100 * 1024 ** 3);
  await reopenToPickUpUiState(page);
  const badge = page.locator(".cheader-storage", { hasText: "외부" });
  await expect(badge).toHaveClass(/level-blue/);
  await expect(badge.locator(".cheader-storage-warn")).not.toHaveClass(/on/);
});

test("목표를 넘으면 빨강 단계 + 경고 아이콘이 뜬다", async ({ page }) => {
  // 목표를 실사용량보다 작게 잡아 강제로 넘긴다.
  await setTarget(page, "ext-1", 1 * 1024 ** 3);   // 1GB < 8.7GB
  await reopenToPickUpUiState(page);
  const badge = page.locator(".cheader-storage", { hasText: "외부" });
  await expect(badge).toHaveClass(/level-over/);
  await expect(badge.locator(".cheader-storage-warn")).toHaveClass(/on/);
  await expect(badge.locator(".cheader-storage-warn .icon")).toBeVisible();
});

test("Dashboard에서 목표를 바꾸면 HERO도 그 자리에서 따라간다", async ({ page }) => {
  const badge = page.locator(".cheader-storage", { hasText: "외부" });
  await expect(badge).toHaveClass(/level-none/);

  await openDashboard(page);
  const row = page.locator(".dsb-target[data-storage='ext-1']");
  const input = row.locator(".dsb-target-input");
  await input.fill("1 GB");
  await input.press("Enter");

  // Dashboard를 닫고 목록으로 돌아가지 않아도(같은 탭 안이라) HERO(#collection-header)는
  // 이미 갱신돼 있어야 한다 - renderHeader()를 즉시 다시 부르기 때문이다.
  await expect(badge).toHaveClass(/level-over/);
});

test("펼친 정보의 Capacity는 목표를 정하면 그 값으로, 라벨도 Target으로 바뀐다", async ({ page }) => {
  await setTarget(page, "ext-1", 10 * 1024 ** 3);
  await reopenToPickUpUiState(page);
  await page.locator("#collection-header .icon-btn[title='펼치기']").click();
  const box = page.locator(".storage-box", { hasText: "외부 SD" });
  const capacityRow = box.locator(".health-row", { hasText: "Target" });
  await expect(capacityRow).toBeVisible();
  await expect(capacityRow).toContainText("10");
  await expect(box.locator(".health-row", { hasText: "Capacity" })).toHaveCount(0);
});

test("펼친 정보의 그래프도 같은 5단계 색을 쓴다", async ({ page }) => {
  await setTarget(page, "ext-1", 1 * 1024 ** 3);
  await reopenToPickUpUiState(page);
  await page.locator("#collection-header .icon-btn[title='펼치기']").click();
  const box = page.locator(".storage-box", { hasText: "외부 SD" });
  await expect(box.locator(".storage-bar")).toHaveClass(/level-over/);
});

// 실사용 피드백 - "Internal/External의 Free용량이 Target-Actual이 아니라 그냥
// 하드용량임". ext-1은 목업에서 actualBytes 8.7GB(8,700,000,000B), 물리
// freeBytes 90e9B(=83.8GiB). formatBytes()는 1024 기준이라 GB 표기는 GiB다.
test.describe("펼친 정보의 Free는 목표를 정하면 물리 디스크가 아니라 목표 기준이다", () => {
  test("목표 - 사용량이 물리 여유보다 작으면 그 값을 쓴다", async ({ page }) => {
    await setTarget(page, "ext-1", 20 * 1024 ** 3);   // 20GiB - 8.7GB ≈ 11.9GiB
    await reopenToPickUpUiState(page);
    await page.locator("#collection-header .icon-btn[title='펼치기']").click();
    const box = page.locator(".storage-box", { hasText: "외부 SD" });
    await expect(box.locator(".health-row", { hasText: "Free" })).toContainText("11.9 GB");
  });

  test("목표 - 사용량이 물리 여유보다 크면 물리 여유로 잘린다(실제로 그만큼밖에 못 채운다)", async ({ page }) => {
    await setTarget(page, "ext-1", 200 * 1024 ** 3);   // 목표 기준 계산은 191.9GiB, 물리 여유(83.8GiB)가 더 작다
    await reopenToPickUpUiState(page);
    await page.locator("#collection-header .icon-btn[title='펼치기']").click();
    const box = page.locator(".storage-box", { hasText: "외부 SD" });
    await expect(box.locator(".health-row", { hasText: "Free" })).toContainText("83.8 GB");
  });

  test("목표를 정하지 않았으면 예전처럼 물리 디스크 여유 용량이다", async ({ page }) => {
    await page.locator("#collection-header .icon-btn[title='펼치기']").click();
    const box = page.locator(".storage-box", { hasText: "외부 SD" });
    await expect(box.locator(".health-row", { hasText: "Free" })).toContainText("83.8 GB");
  });
});

test("하단 Status Bar의 Storage 칩을 눌러 보는 Health 모달도 같은 규칙을 쓴다", async ({ page }) => {
  await setTarget(page, "ext-1", 20 * 1024 ** 3);
  await reopenToPickUpUiState(page);
  await page.locator(".sb-storage", { hasText: "외부" }).click();
  const modal = page.locator(".modal-body");
  await expect(modal.locator(".health-row", { hasText: "Target" })).toContainText("20.0 GB");
  await expect(modal.locator(".health-row", { hasText: "Free" })).toContainText("11.9 GB");
});
