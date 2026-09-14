// 미리보기(상세 패널) 켜고 끄기.
//
// Detail은 두 줄로 나뉜다(사용자 요청):
//   - 윗줄 #detail-top : GameList 상단 줄과 나란한 자리. Archive 이동 + 미리보기 토글.
//                        Preview를 꺼도 **그대로 남는다** - 사라지면 다시 켤 방법이 없다.
//   - 아랫줄 #detail-panel : Toolbar 줄부터 아래의 Detail 내용. Preview를 끄면 이것만
//                        빠지고, 그 폭을 목록이 쓴다.
//
// 이전 두 시도는 둘 다 틀렸다: 패널 전체를 44px로 접었을 때는 윗줄의 GameList 헤더까지
// 폭이 바뀌어 재배치됐고, 폭을 그대로 뒀을 때는 목록이 전혀 넓어지지 않았다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const previewButton = (page) => page.locator("#detail-top .detail-topspace .icon-btn[title*='미리보기']");
const widthOf = (page, id) => page.evaluate((i) =>
  document.getElementById(i).getBoundingClientRect().width, id);

test("끄면 Detail 내용 기둥만 빠지고 그 폭만큼 목록이 넓어진다", async ({ page }) => {
  const listBefore = await widthOf(page, "list-wrap");
  const panelWidth = await widthOf(page, "detail-panel");
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).toBeHidden();
  expect(await widthOf(page, "list-wrap")).toBeGreaterThan(listBefore + panelWidth - 4);
});

test("꺼도 윗줄(GameList 헤더 + 미리보기 토글)은 폭도 자리도 그대로다", async ({ page }) => {
  const headerBefore = await widthOf(page, "collection-header");
  const topBefore = await page.locator("#detail-top").boundingBox();
  await previewButton(page).click();
  await expect(previewButton(page)).toBeVisible();
  expect(Math.abs((await widthOf(page, "collection-header")) - headerBefore)).toBeLessThan(2);
  const topAfter = await page.locator("#detail-top").boundingBox();
  expect(Math.abs(topAfter.x - topBefore.x)).toBeLessThan(2);
  expect(Math.abs(topAfter.y - topBefore.y)).toBeLessThan(2);
});

test("다시 켜면 Detail 내용이 돌아온다", async ({ page }) => {
  const listBefore = await widthOf(page, "list-wrap");
  await previewButton(page).click();
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).toBeVisible();
  expect(Math.abs((await widthOf(page, "list-wrap")) - listBefore)).toBeLessThan(2);
});

test("'미리보기' 글자를 눌러도 켜고 끈다", async ({ page }) => {
  await page.locator("#detail-top .detail-preview-label").click();
  await expect(page.locator("#detail-panel")).toBeHidden();
  await page.locator("#detail-top .detail-preview-label").click();
  await expect(page.locator("#detail-panel")).toBeVisible();
});

test("꺼 둔 상태는 다시 그려도 유지된다", async ({ page }) => {
  await previewButton(page).click();
  await expect(page.locator("#detail-panel")).toBeHidden();

  // 전체를 다시 그리는 동작(탭 전환)을 거쳐도 꺼진 상태여야 한다.
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".ctab.archive")).toHaveClass(/active/);
  await expect(page.locator("#detail-panel")).toBeHidden();
});

test("Navigator 제목, GameList 헤더, Detail 윗줄의 아래 구분선이 한 줄이다", async ({ page }) => {
  // Collection을 열었을 때(헤더 3줄) 기준으로 맞춘다(사용자 요청).
  const bottom = async (sel) => {
    const b = await page.locator(sel).first().boundingBox();
    return Math.round(b.y + b.height);
  };
  const nav = await bottom(".nav-top");
  expect(Math.abs((await bottom("#collection-header")) - nav)).toBeLessThanOrEqual(1);
  expect(Math.abs((await bottom("#detail-top .detail-topspace")) - nav)).toBeLessThanOrEqual(1);
});
