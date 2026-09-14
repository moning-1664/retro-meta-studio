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

test.describe("미리보기 토글 (Detail 패널 상단, 레이아웃 재검토)", () => {
  const previewToggle = (page) => page.locator("#detail-top .detail-topspace .icon-btn[title*='미리보기']");

  test("토글 버튼이 Detail 패널 상단에 있다", async ({ page }) => {
    await expect(previewToggle(page)).toBeVisible();
  });

  test("끄면 아랫줄의 Detail 내용만 사라지고 윗줄 토글은 남는다", async ({ page }) => {
    // 윗줄(#detail-top)까지 사라지면 다시 켤 방법이 없다. 자세한 레이아웃 검증은
    // preview-mode.spec.js에 있다.
    await openFirstGame(page);
    await previewToggle(page).click();
    await expect(page.locator("#detail-panel")).toBeHidden();
    await expect(previewToggle(page)).toBeVisible();
  });

  test("끈 상태에서 행을 눌러도 패널이 열리지 않는다", async ({ page }) => {
    await previewToggle(page).click();
    await page.locator(".lrow").nth(1).locator(".lc-file").click();
    await expect(page.locator("#detail-panel")).toBeHidden();
    await expect(page.locator("#detail-panel-inner")).toHaveCount(0);
  });

  test("다시 켜면 돌아온다", async ({ page }) => {
    await previewToggle(page).click();
    await previewToggle(page).click();
    await expect(page.locator("#detail-panel")).toBeVisible();
    await expect(page.locator("#detail-panel-inner")).toHaveCount(1);
  });

  test("끄고 켠 상태를 저장한다", async ({ page }) => {
    const saved = [];
    await page.exposeFunction("__saved", (s) => saved.push(s));
    await page.evaluate(() => {
      const original = window.api.saveUiState;
      window.api.saveUiState = (id, s) => { window.__saved(s); return original(id, s); };
    });
    await previewToggle(page).click();
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
    // RetroArch 실행 버튼. 실행 흐름 자체는 retroarch.spec.js가 본다.
    await openFirstGame(page);
    await expect(page.locator("#detail-panel .detail-launch")).toBeVisible();
  });

  test("실행 검증 안 된 System(PS2)은 재생 버튼이 꺼져 있고 이유를 알려준다", async ({ page }) => {
    await openFirstGame(page);
    await expect(page.locator("#detail-panel .detail-launch")).toBeDisabled();
    await expect(page.locator("#detail-panel .detail-launch")).toHaveAttribute("title", /RetroArch/);
  });
});

test.describe("Detail Header - 닫기 버튼 없음 (레이아웃 재검토 §19-20)", () => {
  test("Detail 자체를 닫는 X 버튼은 없다", async ({ page }) => {
    // Detail은 선택된 게임을 보여주는 고정 영역이다 - 숨기려면 미리보기를
    // 꺼야 한다(Preview 토글), 개별 게임의 X로 닫는 길은 없앴다.
    await openFirstGame(page);
    await expect(page.locator("#detail-panel .icon-btn[title*='닫기']")).toHaveCount(0);
  });
});

test.describe("Detail 상단 빈 공간 (레이아웃 재검토 §18-19)", () => {
  // GameList의 Overview 줄과 같은 높이를 차지해서, 그 아래 제목/탭이 Toolbar와
  // 같은 선에서 시작한다. 왼쪽엔 Archive 이동, 오른쪽엔 Preview 토글이 있다 -
  // 게임을 고르기 전에도(빈 상태) 보인다.
  test("Detail Header가 GameList Toolbar와 같은 선에서 시작한다", async ({ page }) => {
    await openFirstGame(page);
    const filterBarTop = await page.locator("#filter-bar").evaluate((el) => el.getBoundingClientRect().top);
    const detailHeaderTop = await page.locator("#detail-panel .detail-header").evaluate(
      (el) => el.getBoundingClientRect().top);
    expect(Math.abs(filterBarTop - detailHeaderTop)).toBeLessThan(2);
  });

  test("게임을 고르기 전에도 Archive 이동 버튼과 Preview 토글이 보인다", async ({ page }) => {
    await expect(page.locator("#detail-top #archive-ingest-btn")).toBeVisible();
    await expect(page.locator("#detail-top .detail-preview-label")).toHaveText("미리보기");
  });

});

test.describe("Media 격자", () => {
  const openMedia = async (page) => {
    await openFirstGame(page);
    await page.locator(".detail-tab", { hasText: "Media" }).click();
  };

  test("ES-DE가 쓰는 media 종류를 전부 다룬다", async ({ page }) => {
    await openMedia(page);
    // 그림으로 보여주는 것과 유무만 말하는 것을 합치면 하나도 빠지지 않아야 한다.
    const tiles = await page.locator(".media-tile-label").allTextContents();
    const flags = await page.locator(".media-flag-label").allTextContents();
    const all = [...tiles, ...flags];
    ["Cover", "Marquee", "MixImage", "TitleScreen", "Screenshot",
     "3DBox", "BackCover", "PhysicalMedia", "Wheel",
     "Video", "Manual", "FanArt"].forEach((name) => {
      expect(all).toContain(name);
    });
  });

  test("Cover 오른쪽은 셋이다", async ({ page }) => {
    // 넷을 놓으니 난잡하고 각 칸이 너무 납작해졌다.
    await openMedia(page);
    await expect(page.locator(".media-hero-side .media-tile")).toHaveCount(3);
  });

  test("아래 한 줄은 넷이다", async ({ page }) => {
    await openMedia(page);
    await expect(page.locator(".media-rest .media-tile")).toHaveCount(4);
    const labels = await page.locator(".media-rest .media-tile-label").allTextContents();
    expect(labels).toEqual(["3DBox", "BackCover", "PhysicalMedia", "Wheel"]);
  });

  test("Cover 높이와 오른쪽 셋의 높이가 맞는다", async ({ page }) => {
    // 이것이 어긋나면 패널이 삐뚤어 보인다. 크기를 CSS가 못박아야 항상 맞는다.
    await openMedia(page);
    const cover = await page.locator(".media-tile.cover").evaluate(
      (e) => e.getBoundingClientRect().height);
    const side = await page.locator(".media-hero-side").evaluate(
      (e) => e.getBoundingClientRect().height);
    expect(Math.abs(cover - side)).toBeLessThan(2);
  });

  test("그림 비율이 달라도 상자 크기는 그대로다", async ({ page }) => {
    // 예전에는 이미지에 height:auto를 줘서 표지 비율이 곧 상자 높이였다. 그래서
    // 게임을 넘길 때마다 Cover 높이가 달라지고 아래 배치가 통째로 밀렸다.
    await openMedia(page);
    const sizes = () => page.evaluate(() => {
      const pick = (sel) => {
        const r = document.querySelector(sel).getBoundingClientRect();
        return [Math.round(r.width), Math.round(r.height)];
      };
      return { cover: pick(".media-tile.cover"), wide: pick(".media-tile.wide"),
               rest: pick(".media-rest") };
    });
    const first = await sizes();
    await page.locator(".lrow").nth(2).locator(".lc-file").click();
    await page.locator(".detail-tab", { hasText: "Media" }).click();
    expect(await sizes()).toEqual(first);
  });

  test("없는 media도 자리를 지킨다", async ({ page }) => {
    // Screenshot이 없으면 높이가 무너져 패널 배치가 흔들리던 문제. 크기는 슬롯마다
    // 다르지만(Cover는 크고 보조는 작다) **0이 되는 것은 없어야** 한다.
    await openMedia(page);
    const heights = await page.locator(".media-tile-preview").evaluateAll(
      (els) => els.map((e) => Math.round(e.getBoundingClientRect().height)));
    expect(Math.min(...heights)).toBeGreaterThan(0);
  });

  test("Cover와 Screenshot이 보조 media보다 크다", async ({ page }) => {
    // 이 둘이 그 게임을 알아보게 하는 주된 그림이다. 예전에는 열두 칸이 전부 같은
    // 16:9 타일이라 세로로 긴 표지가 타일 넓이의 절반도 못 썼다.
    await openMedia(page);
    const area = (sel) => page.locator(sel).first().evaluate((e) => {
      const r = e.getBoundingClientRect();
      return r.width * r.height;
    });
    const cover = await area(".media-tile.cover");
    const wide = await area(".media-tile.wide");
    const small = await area(".media-tile.small");
    expect(cover).toBeGreaterThan(small * 2);
    expect(wide).toBeGreaterThan(small * 2);
  });

  test("Cover는 왼쪽, 보조는 그 오른쪽에 있다", async ({ page }) => {
    await openMedia(page);
    const box = (sel) => page.locator(sel).first().evaluate((e) => e.getBoundingClientRect().x);
    expect(await box(".media-tile.cover")).toBeLessThan(await box(".media-hero-side .media-tile"));
  });

  test("Screenshot은 Cover 아래에 전체 폭으로 놓인다", async ({ page }) => {
    await openMedia(page);
    const rect = (sel) => page.locator(sel).first().evaluate((e) => {
      const r = e.getBoundingClientRect();
      return { top: r.top, width: r.width };
    });
    const hero = await rect(".media-hero");
    const wide = await rect(".media-tile.wide");
    expect(wide.top).toBeGreaterThan(hero.top);
    expect(Math.abs(wide.width - hero.width)).toBeLessThan(3);
  });

  test("자리는 어떤 media가 있든 그대로다", async ({ page }) => {
    // "있는 것부터 채운다"로 하면 게임을 넘길 때마다 Cover 자리에 Wheel이 오는 식으로
    // 배치가 출렁인다. 슬롯은 고정이어야 한다.
    await openMedia(page);
    const labels = () => page.locator(".media-tile-label").allTextContents();
    const first = await labels();
    await page.locator(".lrow").nth(2).locator(".lc-file").click();
    await page.locator(".detail-tab", { hasText: "Media" }).click();
    expect(await labels()).toEqual(first);
  });

  test("Media 탭은 잘리지 않고 스크롤된다", async ({ page }) => {
    // legacy style.css의 `.media-tab-body { overflow:hidden !important }` 때문에
    // 아래쪽 타일이 잘린 채 스크롤도 되지 않았다.
    await openMedia(page);
    const overflow = await page.locator(".media-tab-body").evaluate(
      (e) => getComputedStyle(e).overflowY);
    expect(overflow).not.toBe("hidden");
  });

  test("없을 때 «없음» 글자를 반복하지 않는다", async ({ page }) => {
    await openMedia(page);
    // 열두 개 타일에 "…없음"을 반복해 적으면 그것만 눈에 들어온다. 아이콘 하나로 족하다.
    await expect(page.locator(".media-tab-body")).not.toContainText("없음");
  });

  test("영상·설명서·FanArt는 유무만 표시한다", async ({ page }) => {
    // 영상은 실어 오기엔 크고 설명서는 PDF라 애초에 그릴 수 없다. FanArt는 자리를
    // 차지할 만큼 자주 보는 것이 아니다(사용자 결정).
    await openMedia(page);
    const video = page.locator(".media-flag-item", { hasText: "Video" });
    await expect(video.locator(".media-flag")).toHaveText("v");
    await expect(video).toHaveClass(/on/);
  });

  test("없으면 x로 말한다", async ({ page }) => {
    await openMedia(page);
    await page.locator(".lrow").nth(2).locator(".lc-file").click();
    await page.locator(".detail-tab", { hasText: "Media" }).click();
    const marks = await page.locator(".media-flag").allTextContents();
    expect(marks.every((m) => m === "x")).toBe(true);
    await expect(page.locator(".media-flag-item.on")).toHaveCount(0);
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

  test("큰 이미지를 다시 누르면 닫힌다", async ({ page }) => {
    // 확대해서 본 다음에 하는 일은 닫는 것뿐이고, 그때 손이 가 있는 곳은 그 이미지
    // 위다. 버튼을 찾아 눈을 옮기게 할 이유가 없다.
    await openMedia(page);
    await page.locator(".media-tile[title='Cover']").click();
    await expect(page.locator(".lightbox-img")).toBeVisible();
    await page.locator(".lightbox-img").click();
    await expect(page.locator(".lightbox-img")).toHaveCount(0);
  });

  test("별도의 닫기 버튼은 두지 않는다", async ({ page }) => {
    await openMedia(page);
    await page.locator(".media-tile[title='Cover']").click();
    await expect(page.locator(".lightbox-card .modal-actions .btn")).toHaveCount(0);
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
