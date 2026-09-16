// 레이아웃 띠와 기준선(사용자 결정, 2026-09).
// - Chrome보다 한 단계 톤 다운한 --chrome-sub: System 제목 띠, Dashboard, Detail 탭 바탕/패널, 선택 안 된 탭
// - Detail 윗부분(Archive 버튼 줄 + METADATA 머리)은 옆 GameList Chromium과 같은 색
// - System 제목 띠 아래 선 = Toolbar 아래 선, Detail 머리 아래 선 = 목록 머리글 아래 선
// - System 목록은 GameList와 같은 밝은 바탕
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

const bg = (page, sel) => page.locator(sel).first().evaluate((el) => getComputedStyle(el).backgroundColor);
const bottom = async (page, sel) => {
  const b = await page.locator(sel).first().boundingBox();
  return b.y + b.height;
};

for (const theme of ["stitch", "sfc", "md", "nes"]) {
  test.describe(`테마 ${theme}`, () => {
    test.beforeEach(async ({ page }) => {
      await openApp(page);
      await page.evaluate((t) => {
        if (t === "stitch") delete document.documentElement.dataset.theme;
        else document.documentElement.dataset.theme = t;
      }, theme);
      await page.locator(".lrow", { hasText: "FFX.iso" }).locator(".lc-file").click();
      await expect(page.locator(".detail-header")).toBeVisible();
    });

    test("속성 띠는 한 가지 신규색이고 Chromium과 다르다", async ({ page }) => {
      const sub = await bg(page, ".nav-eyebrow");
      expect(sub).not.toBe(await bg(page, "#collection-header"));
      // Navigator 최하단 띠는 Dashboard 버튼이 아니라 그것을 감싼 줄이다 -
      // Settings가 같은 줄로 내려오면서 배경을 감싸는 쪽이 들고 있다.
      expect(await bg(page, ".nav-bottom")).toBe(sub);
      expect(await bg(page, ".detail-tabs")).toBe(sub);
      expect(await bg(page, "#detail-panel")).toBe(sub);
      expect(await bg(page, ".detail-tab:not(.active)")).toBe(sub);
      expect(await bg(page, ".ctab:not(.active)")).toBe(sub);
    });

    test("Detail 윗부분은 옆 Chromium과 같은 색이고, 선택된 탭은 내용 카드와 같은 색이다", async ({ page }) => {
      const chrome = await bg(page, "#collection-header");
      expect(await bg(page, "#detail-top")).toBe(chrome);
      expect(await bg(page, ".detail-header")).toBe(chrome);
      expect(await bg(page, ".detail-tab.active")).toBe(await bg(page, ".detail-body"));
    });

    test("System 목록은 GameList와 같은 바탕이다", async ({ page }) => {
      expect(await bg(page, ".nav-scroll")).toBe(await bg(page, "#list-wrap"));
    });
  });
}

test.describe("기준선", () => {
  test.beforeEach(async ({ page }) => {
    await openApp(page);
    await page.locator(".lrow", { hasText: "FFX.iso" }).locator(".lc-file").click();
    await expect(page.locator(".detail-header")).toBeVisible();
  });

  test("System 제목 띠의 아래 선이 Toolbar 아래 선과 같다", async ({ page }) => {
    expect(Math.abs((await bottom(page, ".nav-eyebrow")) - (await bottom(page, "#filter-bar")))).toBeLessThanOrEqual(1);
    // 띠는 스크롤되지 않는다 - System이 많아도 제목은 제자리에 있다.
    expect(await page.evaluate(() => document.querySelector(".nav-scroll").contains(document.querySelector(".nav-eyebrow")))).toBe(false);
  });

  test("Detail 머리의 아래 선이 목록 머리글 아래 선과 같다 - 탭이 목록 첫 줄에서 시작한다", async ({ page }) => {
    expect(Math.abs((await bottom(page, ".detail-header")) - (await bottom(page, "#list-head")))).toBeLessThanOrEqual(1);
  });

  test("Detail 머리 띠는 윗줄과 같은 폭이라 오른쪽에 틈이 없다", async ({ page }) => {
    const top = await page.locator("#detail-top").boundingBox();
    const head = await page.locator(".detail-header").boundingBox();
    expect(Math.abs((head.x + head.width) - (top.x + top.width))).toBeLessThanOrEqual(1);
  });

  test("밀도를 바꿔도 두 기준선이 유지된다", async ({ page }) => {
    await page.evaluate(() => { document.documentElement.dataset.density = "normal"; });
    expect(Math.abs((await bottom(page, ".nav-eyebrow")) - (await bottom(page, "#filter-bar")))).toBeLessThanOrEqual(1);
    expect(Math.abs((await bottom(page, ".detail-header")) - (await bottom(page, "#list-head")))).toBeLessThanOrEqual(1);
  });

  test("System 제목 글씨가 예전(8px)보다 크다", async ({ page }) => {
    const size = await page.locator(".nav-eyebrow").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(size).toBeGreaterThanOrEqual(10);
  });

  test("Gamelist 머리글 글씨가 본문(게임 목록 행)만큼 크다(실사용 피드백 §5)", async ({ page }) => {
    // 글자 크기 슬라이더 작업 중에 9px로 줄어든 채 굳었다 - 본문보다 작으면 안 된다.
    const headSize = await page.locator("#list-head").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    const rowSize = await page.locator(".lrow").first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(headSize).toBeGreaterThanOrEqual(rowSize - 0.5);
  });
});

test.describe("버튼 크기", () => {
  test.beforeEach(async ({ page }) => { await openApp(page); });

  test("메타데이터 보내기/가져오기는 아이콘 하나뿐이고, 설명은 툴팁에 있다(§4·§6)", async ({ page }) => {
    // "Archive로"는 Detail에서 HERO로 옮겨오며 글자 라벨 버튼에서 아이콘 버튼이
    // 됐다 - 폭이 출렁이던 문제 자체가 없어졌다.
    const send = page.locator("#collection-header .cheader-right .icon-btn[title*='메타데이터 보내기']");
    await expect(send).toHaveAttribute("title", /Archive로/);
    expect((await send.boundingBox()).height).toBeLessThanOrEqual(24);
    const receive = page.locator("#collection-header .cheader-right .icon-btn[title*='메타데이터 가져오기']");
    await expect(receive).toHaveAttribute("title", /Archive에서/);
    expect((await receive.boundingBox()).height).toBeLessThanOrEqual(24);
  });

  test("Chromium과 Detail 윗부분의 아이콘 버튼은 24px 이하다", async ({ page }) => {
    for (const sel of ["#collection-header .cheader-right .icon-btn", "#detail-top .detail-preview-toggle .icon-btn"]) {
      const box = await page.locator(sel).first().boundingBox();
      expect(box.height, sel).toBeLessThanOrEqual(24);
    }
  });

  test("창 버튼(– □ ×)은 윈도우 크기로 크게 보인다", async ({ page }) => {
    const sizes = await page.locator("#window-controls .win-btn").evaluateAll((els) =>
      els.map((el) => parseFloat(getComputedStyle(el).fontSize)));
    sizes.forEach((s) => expect(s).toBeGreaterThanOrEqual(18));
    const box = await page.locator("#window-controls .win-btn").first().boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(46);
  });
});
