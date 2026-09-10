// 미리보기(상세 패널) 켜고 끄기 (P1).
//
// 끄면 목록이 넓어져야 한다 - 탐색기의 미리보기 창과 같다. 상세를 안 보는 동안
// 화면 3분의 1을 빈 채로 둘 이유가 없다. 다만 **완전히 숨기지는 않는다** -
// Detail 패널 상단의 Preview 토글만 남긴 좁은 폭(.collapsed)으로 접는다.
// 완전히 숨기면(display:none) 그 토글도 같이 사라져서 다시 켤 방법이 없어진다
// (실사용 피드백).
//
// renderDetailPanel()이 매번 S.previewOn을 직접 보고 접힌/펼친 모습을 정하므로,
// 어디서 다시 그려도(탭 전환, 앱 재시작 복원 등) 상태가 어긋나지 않는다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const previewButton = (page) => page.locator("#detail-panel .detail-topspace .icon-btn[title*='미리보기']");
const listWidth = (page) => page.evaluate(() =>
  document.getElementById("list-wrap").getBoundingClientRect().width);

test("끄면 목록이 넓어지고, 패널은 완전히 숨지 않고 좁게 접힌다", async ({ page }) => {
  const before = await listWidth(page);
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).toHaveClass(/collapsed/);
  // 접힌 상태에도 다시 켤 토글은 남아 있다.
  await expect(previewButton(page)).toBeVisible();
  const after = await listWidth(page);
  expect(after).toBeGreaterThan(before + 200);
});

test("다시 켜면 원래 폭으로 돌아온다", async ({ page }) => {
  const before = await listWidth(page);
  await previewButton(page).click();
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).not.toHaveClass(/collapsed/);
  expect(Math.abs((await listWidth(page)) - before)).toBeLessThan(2);
});

test("꺼 둔 상태는 다시 그려도 유지된다", async ({ page }) => {
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).toHaveClass(/collapsed/);

  // 전체를 다시 그리는 동작(탭 전환)을 거쳐도 꺼진 상태여야 한다.
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".ctab.archive")).toHaveClass(/active/);
  await expect(page.locator("#detail-panel")).toHaveClass(/collapsed/);
});

test("꺼도 미리보기 아이콘은 GameList 상단 Chromium과 같은 높이에 그대로 있다", async ({ page }) => {
  // 실사용 피드백: 예전엔 .detail-topspace.compact가 height:100%로 늘어나면서
  // align-items:flex-end 때문에 아이콘이 접힌 패널의 맨 아래로 밀려났다.
  // GameList 위쪽(cheader)과 같은 자리에 고정되어야 한다 - 그 아래가 늘어나는
  // 것처럼 보여야지, 아이콘이 내려가면 안 된다.
  const cheaderBox = await page.locator(".cheader").first().boundingBox();
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).toHaveClass(/collapsed/);
  const btnBox = await previewButton(page).boundingBox();
  expect(Math.abs(btnBox.y - cheaderBox.y)).toBeLessThan(40);
});
