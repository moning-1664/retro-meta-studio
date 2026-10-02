// Navigator 상하단 고정 영역 - App Title(위) / Add External·Dashboard·Settings(아래).
//
// 사용자 요청으로 위치를 바꿨다: App Title은 GameList 상단 Chromium(.cheader)과
// 세로로 나란히 보이도록 최상단으로, Dashboard는 그 자리(최하단)로 옮겼다.
// Settings는 로고가 상단 띠를 채우면서 Dashboard 옆(최하단)으로 내려왔다.
//
// System 목록만 스크롤한다(레이아웃 재검토 §5) - 그래서 이 넷은 #nav-scroll
// 바깥(형제)에 있어야 한다. 안에 있으면 System이 늘어날 때 같이 밀려난다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("Dashboard/Add External/App Title/Settings는 스크롤 영역 밖에 있다", async ({ page }) => {
  const outside = async (selector) => page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const scroll = document.querySelector(".nav-scroll");
    return !!el && !scroll.contains(el);
  }, selector);

  expect(await outside(".nav-dashboard")).toBe(true);
  expect(await outside(".nav-top")).toBe(true);
  expect(await outside(".settings-btn")).toBe(true);

  // Add External Storage는 이미 External이 있으면 숨는다(사용자 결정) - 기본
  // mock이 그 상태라 먼저 지워야 이 버튼이 보인다.
  await page.locator(".storage-remove-btn").click();
  await page.locator(".modal-actions .btn", { hasText: "확인" }).click();
  await expect(page.locator(".nav-action", { hasText: "Add External" })).toBeVisible();
  expect(await outside(".nav-action")).toBe(true);
  expect(await outside(".nav-add-system")).toBe(true);
});

test("Dashboard를 누르면 Dashboard 화면으로 바뀐다", async ({ page }) => {
  // 자세한 동작은 dashboard.spec.js에 있다.
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#dashboard-view .dsb-title")).toBeVisible();
});

test("App Title이 Navigator 상단에 있고 GameList 상단 Chromium과 나란하다", async ({ page }) => {
  // 제목은 **글자다**(사용자 결정 - 구워 둔 그림은 열화가 심했다). 읽어 주는 이름은 aria-label이 맡는다.
  await expect(page.locator(".nav-app-title-name")).toHaveAttribute("aria-label", "RetroMeta Studio");
  await expect(page.locator(".nav-app-title-name")).toContainText("RetroMeta");
  const navTop = await page.locator(".nav-top").boundingBox();
  const cheader = await page.locator(".cheader").first().boundingBox();
  // 정확히 같은 픽셀일 필요는 없다 - 위쪽 시작 지점이 비슷한 높이에 있으면 된다.
  expect(Math.abs(navTop.y - cheader.y)).toBeLessThan(12);
});

test("Dashboard가 Navigator 최하단에 있다", async ({ page }) => {
  const dashboardBox = await page.locator(".nav-dashboard").boundingBox();
  const navBox = await page.locator("#nav").boundingBox();
  expect(dashboardBox.y + dashboardBox.height).toBeGreaterThan(navBox.y + navBox.height - 60);
});

test("Settings를 누르면 Settings 화면이 열린다", async ({ page }) => {
  // 자세한 동작은 settings.spec.js에 있다.
  await page.locator(".settings-btn").click();
  await expect(page.locator(".stg-title")).toHaveText("설정");
});

// 실사용 피드백 §8 + 로고 개편(사용자 결정).
test.describe("App Title / Settings 자리와 크기", () => {
  // 사용자 결정 - 제목은 글자로 그리고(그림은 열화), R/M/S와 i의 꼭지에 빨/노/녹/파를 넣는다.
  test("제목은 그림이 아니라 글자이고, R/M/S와 i의 꼭지에 네 가지 색이 들어간다", async ({ page }) => {
    const title = page.locator(".nav-app-title-name");
    await expect(title.locator("img")).toHaveCount(0);
    const colors = await title.evaluate((el) => {
      const get = (sel) => getComputedStyle(el.querySelector(sel)).color;
      return { r: get(".apt-r"), m: get(".apt-m"), s: get(".apt-s"),
               dot: getComputedStyle(el.querySelector(".apt-i"), "::after").backgroundColor,
               ink: getComputedStyle(el).color };
    });
    // 넷이 서로 다른 색이고, 본문 글자색과도 다르다.
    const four = [colors.r, colors.m, colors.s, colors.dot];
    expect(new Set(four).size).toBe(4);
    four.forEach((c) => expect(c).not.toBe(colors.ink));
  });

  test("밝은 테마에서도 읽히도록 두꺼운 외곽선을 두른다", async ({ page }) => {
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "sfc"));
    const stroke = await page.locator(".nav-app-title-name").evaluate((el) => {
      const cs = getComputedStyle(el);
      return { width: parseFloat(cs.webkitTextStrokeWidth), order: cs.paintOrder };
    });
    expect(stroke.width).toBeGreaterThanOrEqual(1);
    // 외곽선을 글자 아래에 깔지 않으면 획이 외곽선에 먹힌다.
    expect(stroke.order).toContain("stroke");
  });

  test("부제가 제목 아래에 작게 붙는다", async ({ page }) => {
    const sub = page.locator(".nav-app-subtitle");
    await expect(sub).toHaveText("Retro Game Metadata Editor");
    const [title, subtitle] = await Promise.all([
      page.locator(".nav-app-title-name").boundingBox(), sub.boundingBox()]);
    expect(subtitle.y).toBeGreaterThan(title.y);                       // 제목 아래
    // 훨씬 작게 - 상자 높이가 아니라 글자 크기로 잰다(상자는 줄 높이에 따라 달라진다).
    const fontSize = (locator) => locator.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    const [titleFont, subFont] = await Promise.all([
      fontSize(page.locator(".nav-app-title-name")), fontSize(sub)]);
    expect(subFont).toBeLessThan(titleFont * 0.7);
  });

  test("아이콘·제목·부제가 Navigator 칸을 벗어나지 않는다", async ({ page }) => {
    const [nav, icon, title, sub] = await Promise.all([
      page.locator(".nav-top").boundingBox(), page.locator(".nav-app-icon").boundingBox(),
      page.locator(".nav-app-title-name").boundingBox(), page.locator(".nav-app-subtitle").boundingBox()]);
    for (const box of [icon, title, sub]) {
      expect(box.x).toBeGreaterThanOrEqual(nav.x);
      expect(box.x + box.width).toBeLessThanOrEqual(nav.x + nav.width + 1);
      expect(box.y).toBeGreaterThanOrEqual(nav.y - 1);
      expect(box.y + box.height).toBeLessThanOrEqual(nav.y + nav.height + 1);
    }
    // 아이콘은 제목+부제를 합친 높이를 넘지 않는다(사용자 결정 - 너무 크지 않게).
    expect(icon.height).toBeLessThanOrEqual((sub.y + sub.height) - title.y);
  });

  // 사용자 결정 - "앱 타이틀을 가로로 6등분해서 좌측 한칸은 아이콘, 우측 한칸을 비우고
  // 나머지 66% 크기로 타이틀을 1줄로 배치. 아이콘은 좌측 한칸의 절반 크기 정사각형".
  // 그 뒤 사용자 결정(번복 세 번) - 처음엔 "타이틀만 가로 길이를 20% 늘려라", 그다음엔
  // "가로폭이 갑자기 커졌다, 가로폭만 원래대로 20% 줄여라(세로는 유지)"(가로 0.96), 마지막엔
  // "제목이 여전히 크다, 높이/길이 각각 5% 줄이고 재배치"(가로 0.912, 세로 1.14 - 비율은
  // 유지한 채 둘 다 5%씩 준다). 부제는 처음부터 그대로 네 칸이고, 제목만
  // transform-origin: left로 가로가 줄어 오른쪽 빈 칸을 그만큼 덜 먹는다.
  test("brand title and version fit beside the icon", async ({ page }) => {
    const [nav, icon, title, version] = await Promise.all([
      page.locator(".nav-app-title").boundingBox(), page.locator(".nav-app-icon").boundingBox(),
      page.locator(".nav-app-title-name").boundingBox(), page.locator(".nav-app-version").boundingBox(),
    ]);
    expect(icon.height).toBeCloseTo(icon.width, 0);
    expect(title.x).toBeGreaterThan(icon.x + icon.width);
    expect(version.y).toBeGreaterThanOrEqual(title.y + title.height - 1);
    expect(version.x + version.width).toBeLessThanOrEqual(nav.x + nav.width + 1);
  });

  test("제목은 한 줄이고 그 칸을 넘지 않는다", async ({ page }) => {
    const title = page.locator(".nav-app-title-name");
    expect(await title.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("nowrap");
    // 한 줄 - 글자 높이가 한 줄 높이를 크게 넘지 않는다.
    const box = await title.boundingBox();
    const fontSize = await title.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(box.height).toBeLessThan(fontSize * 1.6);
    // 네 칸을 조금 넘치는 만큼은 비워 둔 오른쪽 한 칸이 받아 준다 - 다만 Navigator 밖으로는
    // 나가지 않는다(글자가 잘리면 안 된다).
    const [nav, text] = await Promise.all([
      page.locator("#nav").boundingBox(),
      title.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return { x: r.x, width: el.scrollWidth };
      }),
    ]);
    expect(text.x + text.width).toBeLessThanOrEqual(nav.x + nav.width);
  });

  test("App Title이 줄 안에서 세로 가운데다", async ({ page }) => {
    const navTop = await page.locator(".nav-top").evaluate((el) => getComputedStyle(el).alignItems);
    expect(navTop).toBe("center");
  });

  test("Settings는 Navigator 최하단 Dashboard 줄에 있다", async ({ page }) => {
    // 로고가 상단 띠를 채우면서 톱니가 여기로 내려왔다(사용자 결정).
    await expect(page.locator(".nav-top .settings-btn")).toHaveCount(0);
    await expect(page.locator(".nav-bottom .settings-btn")).toBeVisible();
    const [dash, settings] = await Promise.all([
      page.locator(".nav-dashboard").boundingBox(),
      page.locator(".settings-btn").boundingBox(),
    ]);
    expect(settings.x).toBeGreaterThan(dash.x);            // Dashboard 오른쪽
    expect(Math.abs((settings.y + settings.height / 2) - (dash.y + dash.height / 2))).toBeLessThan(6);
  });

  test("Settings 아이콘 패딩이 다른 조용한 도구 버튼과 같다", async ({ page }) => {
    // HERO의 메타데이터 보내기와 같은 3px(레이아웃 재검토 계약).
    const settingsPad = await page.locator(".settings-btn")
      .evaluate((el) => getComputedStyle(el).padding);
    const heroPad = await page.locator("#collection-header .cheader-right .icon-btn").first()
      .evaluate((el) => getComputedStyle(el).padding);
    expect(settingsPad).toBe(heroPad);
  });
});

// Archive/App Title 대표 아이콘(실사용 피드백 - "인베이더 마크보다 롬팩 그림이
// 낫다" / "ARCHIVE는 인베이더 그림보다 DB 아이콘"). App Title은 사용자가 만든
// 카트리지 그림(app-icon.png)을, Archive는 lucide 스타일 database 아이콘을 쓴다.
test.describe("Archive/App Title 아이콘", () => {
  test("App Title은 카트리지 그림(app-icon.png)을 쓴다 - 제목+부제 높이에 맞춘다", async ({ page }) => {
    const img = page.locator(".nav-app-title .nav-app-icon");
    await expect(img).toHaveAttribute("src", /app-icon\.png$/);
    await expect.poll(() => img.evaluate((el) => el.complete && el.naturalWidth)).toBeGreaterThan(0);
  });

  test("Archive 탭은 database 아이콘(원기둥 모양)을 쓴다", async ({ page }) => {
    // database 아이콘은 ellipse + path 획으로 이루어진다 - 칠한 사각형(rect)인
    // 인베이더 픽셀과 이걸로 구분한다.
    const svg = page.locator(".ctab.archive .icon");
    await expect(svg.locator("ellipse")).toHaveCount(1);
    await expect(svg.locator("rect")).toHaveCount(0);
  });
});
