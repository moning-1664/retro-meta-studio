// Detail 패널이 넉넉히 클 때(사용자 결정 - 850px) 나타나는 추가 정보.
//
// 예전엔 Description(.detail-body-desc-wrap)이 flex:1 1 auto라 남는 세로
// 공간을 전부 흡수해서, 창을 늘릴수록 설명만 한없이 길어졌다. 지금은 12줄에서
// 멈추고, 그렇게 남는 공간을 패널이 충분히 클 때만 Metadata 탭의 Screenshot/
// media 유무와 Media 탭의 Title/Description이 대신 채운다. 컨테이너 쿼리
// (#detail-panel-inner, min-height: 850px)로 처리하므로 뷰포트를 크게 잡아야
// 확인할 수 있다 - 그래서 이 파일을 따로 둔다(다른 파일의 기본 openApp보다
// 먼저 뷰포트를 키워야 한다).
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

const openFirstGame = async (page) => {
  await page.locator(".lrow").first().locator(".lc-file").click();
  await expect(page.locator("#detail-panel")).toHaveClass(/open/);
};

test.describe("좁은 창(기본) - 추가 정보는 숨어 있다", () => {
  test.beforeEach(async ({ page }) => { await openApp(page); });

  test("Metadata 탭에 Screenshot/media 정보가 없다", async ({ page }) => {
    await openFirstGame(page);
    await expect(page.locator(".detail-extra-media")).not.toBeVisible();
  });

  test("Media 탭에 Title/Description이 없다", async ({ page }) => {
    await openFirstGame(page);
    await page.locator(".detail-tab", { hasText: "Media" }).click();
    await expect(page.locator(".media-tab-identity")).not.toBeVisible();
  });
});

test.describe("넉넉히 큰 창(850px 이상) - 추가 정보가 나타난다", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 1100 });
    await openApp(page);
  });

  test("Metadata 탭 아래에 Screenshot과 media 유무 칩이 나온다", async ({ page }) => {
    await openFirstGame(page);
    const extra = page.locator(".detail-extra-media");
    await expect(extra).toBeVisible();
    await expect(extra.locator(".detail-extra-screenshot")).toBeVisible();
    // mediaFlagRow 재사용 - Video/Manual/FanArt 유무 칩.
    await expect(extra.locator(".media-flag-item")).toHaveCount(3);
  });

  test("Media 탭 맨 위에 Title, 그다음 Description이 순서대로 나온다", async ({ page }) => {
    await openFirstGame(page);
    await page.locator(".detail-tab", { hasText: "Media" }).click();
    const identity = page.locator(".media-tab-identity");
    await expect(identity).toBeVisible();
    await expect(identity.locator(".media-tab-title")).toHaveText("Final Fantasy X");
    // get_row 목업은 모든 행에 같은 desc를 하드코딩해서 준다.
    await expect(identity.locator(".media-tab-desc")).toHaveText("설명이 여기에 표시됩니다.");
    // 타이틀이 설명보다 앞선 형제여야 "타이틀 다음 설명" 순서다.
    const order = await identity.evaluate((el) => [...el.children].map((c) => c.className));
    expect(order[0]).toContain("media-tab-title");
    expect(order[1]).toContain("media-tab-desc");
    // Media 탭 본문에서도 media-tab-identity가 media-hero보다 먼저 와야
    // "상단에 출력"이라는 요청이 지켜진다.
    const bodyOrder = await page.locator(".detail-body.media-tab-body")
      .evaluate((el) => [...el.children].map((c) => c.className));
    expect(bodyOrder[0]).toContain("media-tab-identity");
  });

  test("Media 탭 Description이 없으면 '설명 없음'을 보여준다", async ({ page }) => {
    // mock의 get_row는 모든 행에 같은 desc를 하드코딩해서 준다 - 빈 값을
    // 직접 흉내 낸다.
    await page.evaluate(() => {
      const original = window.api.getRow;
      window.api.getRow = async (id, romUid) => {
        const r = await original(id, romUid);
        if (r.ok) r.data.fields = { ...r.data.fields, desc: "" };
        return r;
      };
    });
    await openFirstGame(page);
    await page.locator(".detail-tab", { hasText: "Media" }).click();
    await expect(page.locator(".media-tab-desc")).toHaveText("설명 없음");
  });
});
