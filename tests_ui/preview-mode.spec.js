// 미리보기(상세 패널) 켜고 끄기 (P1, 코드 리뷰로 재설계됨).
//
// 예전에는 끄면 목록이 넓어지도록 패널 폭을 297px→44px로 접었다(탐색기의
// 미리보기 창을 본떴다). 그런데 코드 리뷰에서 이 방식 자체가 문제로 지적됐다 -
// 폭이 바뀌면 그 위 GameList Overview 줄(.cheader)까지 재배치되고, 좁아진
// 폭 안에서 Preview 아이콘의 세로 위치를 다시 계산하다가 아이콘이 패널 아래로
// 밀려나는 문제로 이어졌다. 그래서 이제는 **패널 폭이 항상 297px로 고정**이고,
// Preview를 끄면 `#detail-panel-inner`(Metadata/Media/ROM 탭 내용)만 사라진다.
// GameList 폭도 그대로다.
//
// renderDetailPanel()이 매번 S.previewOn을 직접 보고 켜진/꺼진 모습을 정하므로,
// 어디서 다시 그려도(탭 전환, 앱 재시작 복원 등) 상태가 어긋나지 않는다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const previewButton = (page) => page.locator("#detail-panel .detail-topspace .icon-btn[title*='미리보기']");
const listWidth = (page) => page.evaluate(() =>
  document.getElementById("list-wrap").getBoundingClientRect().width);
const panelWidth = (page) => page.evaluate(() =>
  document.getElementById("detail-panel").getBoundingClientRect().width);

test("꺼도 Detail 패널과 GameList 폭이 바뀌지 않는다", async ({ page }) => {
  const listBefore = await listWidth(page);
  const panelBefore = await panelWidth(page);
  await previewButton(page).click();
  await expect(page.locator("#detail-panel-inner")).toHaveCount(0);
  // 토글은 꺼진 상태에도 남아 있다 - 이게 없으면 다시 켤 방법이 없다.
  await expect(previewButton(page)).toBeVisible();
  expect(Math.abs((await listWidth(page)) - listBefore)).toBeLessThan(2);
  expect(Math.abs((await panelWidth(page)) - panelBefore)).toBeLessThan(2);
});

test("다시 켜면 탭 내용이 돌아온다", async ({ page }) => {
  await previewButton(page).click();
  await previewButton(page).click();
  await expect(page.locator("#detail-panel-inner")).toHaveCount(1);
});

test("꺼 둔 상태는 다시 그려도 유지된다", async ({ page }) => {
  await previewButton(page).click();
  await expect(page.locator("#detail-panel-inner")).toHaveCount(0);

  // 전체를 다시 그리는 동작(탭 전환)을 거쳐도 꺼진 상태여야 한다.
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".ctab.archive")).toHaveClass(/active/);
  await expect(page.locator("#detail-panel-inner")).toHaveCount(0);
});

test("꺼도 미리보기 아이콘은 GameList 상단 Chromium과 같은 높이에 그대로 있다", async ({ page }) => {
  const cheaderBox = await page.locator(".cheader").first().boundingBox();
  await previewButton(page).click();
  const btnBox = await previewButton(page).boundingBox();
  expect(Math.abs(btnBox.y - cheaderBox.y)).toBeLessThan(40);
});
