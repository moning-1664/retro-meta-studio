// Detail 패널 - 이전 프로젝트에서 되찾아온 것들 (Phase 7.17).
//
// 사용자가 짚은 것들이다.
//   - 미리보기 토글이 사라졌다. 끄면 목록이 그 자리까지 넓어져야 한다.
//   - Favorite과 재생 버튼이 사라졌다.
//   - Screenshot이 없으면 상하폭이 무너져 배치가 깨진다.
//   - 설명서/실물매체/타이틀화면 등이 아예 없다.
//   - "xxx 없음"을 종류마다 반복해서 적는다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

/** 행 가운데에는 버튼이 올 수 있어 빈 셀을 누른다. */
const openFirstGame = async (page) => {
  await page.locator(".lrow").first().locator(".lc-file").click();
  await expect(page.locator("#detail-panel")).toHaveClass(/open/);
};

test.describe("미리보기 토글", () => {
  test("토글 버튼이 툴바에 있다", async ({ page }) => {
    await expect(page.locator("#filter-bar .icon-btn[title*='미리보기']")).toBeVisible();
  });

  test("끄면 상세 패널이 자리를 비운다", async ({ page }) => {
    await openFirstGame(page);
    await page.locator("#filter-bar .icon-btn[title='미리보기 끄기']").click();
    await expect(page.locator("#detail-panel")).toHaveClass(/hidden/);
  });

  test("끈 상태에서 행을 눌러도 패널이 열리지 않는다", async ({ page }) => {
    await page.locator("#filter-bar .icon-btn[title='미리보기 끄기']").click();
    await page.locator(".lrow").nth(1).locator(".lc-file").click();
    await expect(page.locator("#detail-panel")).toHaveClass(/hidden/);
  });

  test("다시 켜면 돌아온다", async ({ page }) => {
    await page.locator("#filter-bar .icon-btn[title='미리보기 끄기']").click();
    await page.locator("#filter-bar .icon-btn[title='미리보기 켜기']").click();
    await expect(page.locator("#detail-panel")).not.toHaveClass(/hidden/);
  });

  test("끄고 켠 상태를 저장한다", async ({ page }) => {
    const saved = [];
    await page.exposeFunction("__saved", (s) => saved.push(s));
    await page.evaluate(() => {
      const original = window.api.saveUiState;
      window.api.saveUiState = (id, s) => { window.__saved(s); return original(id, s); };
    });
    await page.locator("#filter-bar .icon-btn[title='미리보기 끄기']").click();
    await expect.poll(() => saved.length, { timeout: 3000 }).toBeGreaterThan(0);
    expect(saved.at(-1).previewOn).toBe(false);
  });
});

test.describe("Favorite / Play", () => {
  test("상세 헤더에 별표가 있다", async ({ page }) => {
    await openFirstGame(page);
    await expect(page.locator("#detail-panel .fav-btn")).toBeVisible();
  });

  test("별표를 누르면 목록의 별표도 함께 바뀐다", async ({ page }) => {
    // 둘이 다르면 어느 쪽이 맞는지 알 수 없다.
    await openFirstGame(page);
    const listStar = page.locator(".lrow").first().locator(".fav-btn");
    const detailStar = page.locator("#detail-panel .fav-btn");
    const before = await listStar.textContent();

    await detailStar.click();
    await expect(detailStar).not.toHaveText(before);
    await expect(listStar).toHaveText(await detailStar.textContent());
  });

  test("재생 버튼이 남아 있다", async ({ page }) => {
    // 아직 RetroArch에 연결되지 않았지만 자리는 지킨다.
    await openFirstGame(page);
    await expect(page.locator("#detail-panel .icon-btn[title*='실행']")).toBeVisible();
  });

  test("재생을 누르면 아직이라고 말한다", async ({ page }) => {
    await openFirstGame(page);
    await page.locator("#detail-panel .icon-btn[title*='실행']").click();
    await expect(page.locator("#toast")).toContainText("RetroArch");
  });
});

test.describe("Media 격자", () => {
  const openMedia = async (page) => {
    await openFirstGame(page);
    await page.locator(".detail-tab", { hasText: "Media" }).click();
  };

  test("ES-DE가 쓰는 media 종류를 전부 보여준다", async ({ page }) => {
    await openMedia(page);
    const labels = await page.locator(".media-tile-label").allTextContents();
    // 예전에 빠져 있던 것들이다.
    ["TitleScreen", "PhysicalMedia", "BackCover", "FanArt", "Manual"].forEach((name) => {
      expect(labels).toContain(name);
    });
  });

  test("없는 media도 자리를 지킨다", async ({ page }) => {
    // Screenshot이 없으면 높이가 무너져 패널 배치가 흔들리던 문제.
    await openMedia(page);
    const heights = await page.locator(".media-tile-preview").evaluateAll(
      (els) => els.map((e) => Math.round(e.getBoundingClientRect().height)));
    expect(Math.min(...heights)).toBeGreaterThan(0);
    expect(new Set(heights).size).toBe(1);   // 있든 없든 같은 높이
  });

  test("타일은 16:9를 지킨다", async ({ page }) => {
    await openMedia(page);
    const ratio = await page.locator(".media-tile-preview").first().evaluate((e) => {
      const r = e.getBoundingClientRect();
      return r.width / r.height;
    });
    expect(ratio).toBeGreaterThan(1.6);
    expect(ratio).toBeLessThan(1.9);
  });

  test("없을 때 «없음» 글자를 반복하지 않는다", async ({ page }) => {
    await openMedia(page);
    // 열두 개 타일에 "…없음"을 반복해 적으면 그것만 눈에 들어온다. 아이콘 하나로 족하다.
    await expect(page.locator(".media-grid")).not.toContainText("없음");
  });

  test("영상과 설명서는 [v]로만 표시한다", async ({ page }) => {
    // 영상은 실어 오기엔 크고 설명서는 PDF라 애초에 그릴 수 없다.
    await openMedia(page);
    const video = page.locator(".media-tile.file-slot", { hasText: "Video" });
    await expect(video.locator(".media-flag")).toHaveText("v");
  });

  test("없는 파일 슬롯은 표시가 비어 있다", async ({ page }) => {
    await openMedia(page);
    await page.locator(".lrow").nth(2).locator(".lc-file").click();
    await page.locator(".detail-tab", { hasText: "Media" }).click();
    await expect(page.locator(".media-tile.file-slot .media-flag.on")).toHaveCount(0);
  });
});

test.describe("Media 확대(lightbox)", () => {
  const openMedia = async (page) => {
    await openFirstGame(page);
    await page.locator(".detail-tab", { hasText: "Media" }).click();
  };

  test("그림이 있는 타일을 누르면 확대된 이미지가 뜬다", async ({ page }) => {
    await openMedia(page);
    const cover = page.locator(".media-tile[title='Cover']");
    await expect(cover).toHaveClass(/clickable/);
    await cover.click();
    await expect(page.locator(".lightbox-img")).toBeVisible();
  });

  test("ESC로 닫힌다", async ({ page }) => {
    await openMedia(page);
    await page.locator(".media-tile[title='Cover']").click();
    await expect(page.locator(".lightbox-img")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".lightbox-img")).toHaveCount(0);
  });

  test("바깥 영역을 누르면 닫힌다", async ({ page }) => {
    await openMedia(page);
    await page.locator(".media-tile[title='Cover']").click();
    await expect(page.locator(".lightbox-img")).toBeVisible();
    await page.locator(".modal-overlay").click({ position: { x: 5, y: 5 } });
    await expect(page.locator(".lightbox-img")).toHaveCount(0);
  });

  test("닫기 버튼으로 닫힌다", async ({ page }) => {
    await openMedia(page);
    await page.locator(".media-tile[title='Cover']").click();
    await page.locator(".modal-actions .btn", { hasText: "닫기" }).click();
    await expect(page.locator(".lightbox-img")).toHaveCount(0);
  });

  test("빈 타일은 눌러도 확대되지 않는다", async ({ page }) => {
    await openMedia(page);
    const empty = page.locator(".media-tile.empty").first();
    await empty.click();
    await expect(page.locator(".lightbox-img")).toHaveCount(0);
  });
});

test.describe("Description", () => {
  test("기본 높이가 열 줄쯤이다", async ({ page }) => {
    // 남는 공간을 전부 흡수하면 설명이 긴 게임에서 아래 필드가 화면 밖으로 밀린다.
    await openFirstGame(page);
    const rows = await page.locator(".detail-body-desc-wrap textarea").getAttribute("rows");
    expect(Number(rows)).toBe(10);
  });
});

test.describe("ROM 탭", () => {
  test("새로 생긴 ROM 탭은 그대로 둔다", async ({ page }) => {
    await openFirstGame(page);
    await expect(page.locator(".detail-tab", { hasText: "ROM" })).toBeVisible();
  });
});
