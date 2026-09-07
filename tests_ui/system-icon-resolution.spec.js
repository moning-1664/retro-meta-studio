// 시스템 아이콘 해석 체인(정규화 -> raster -> 전용 SVG -> generic 폴백) 회귀 테스트.
// app.js의 renderSystemIcon()/systemIcon()/systemSquareIcon()을 직접 호출해서 검증한다
// (window.__RMIconTestHooks는 app.js가 테스트 전용으로 노출하는 최소 훅 - UI 동작에는
// 관여하지 않는다). 데이터 구조만 보는 단위 테스트가 아니라, 실제 렌더러가 실제
// RMSystemIconsRaster/RMSystemIcons/SYSTEM_ICON_FALLBACKS를 거쳐 만든 DOM을 검사한다.
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await page.waitForFunction(() => !!window.__RMIconTestHooks);
});

// systemSquareIcon(key)가 반환한 엘리먼트를 body에 붙이고 id를 붙여 반환한다.
async function mountSquareIcon(page, id, key) {
  await page.evaluate(({ id, key }) => {
    const el = window.__RMIconTestHooks.systemSquareIcon(key);
    el.id = id;
    document.body.appendChild(el);
  }, { id, key });
}

test.describe("정규화(alias) -> 아이콘 lookup 연결", () => {
  test("SFC/sfc/SNES/snes가 모두 같은 canonical 키로 정규화된다", async ({ page }) => {
    const results = await page.evaluate(() => {
      const { normalizeSystemName } = window.__RMIconTestHooks;
      return ["SFC", "sfc", "SNES", "snes"].map(normalizeSystemName);
    });
    expect(results).toEqual(["snes", "snes", "snes", "snes"]);
  });

  test("SFC로 들어와도 SNES 전용 raster 아이콘이 선택된다(폴백으로 새지 않음)", async ({ page }) => {
    await mountSquareIcon(page, "probe-sfc", "SFC");
    await mountSquareIcon(page, "probe-snes", "snes");
    const sfcClass = await page.locator("#probe-sfc").getAttribute("class");
    const snesClass = await page.locator("#probe-snes").getAttribute("class");
    expect(sfcClass).toContain("sq-icon-raster");
    expect(sfcClass).not.toContain("sq-icon-fallback");
    expect(sfcClass).toBe(snesClass);
    const sfcSrc = await page.locator("#probe-sfc img.for-dark").getAttribute("src");
    const snesSrc = await page.locator("#probe-snes img.for-dark").getAttribute("src");
    expect(sfcSrc).toBe(snesSrc);
  });

  for (const alias of ["PS1", "PSX", "PlayStation", "psx"]) {
    test(`PS 별칭 "${alias}"이 psx 전용 raster 아이콘으로 연결된다`, async ({ page }) => {
      await mountSquareIcon(page, "probe-alias", alias);
      await mountSquareIcon(page, "probe-ref", "psx");
      const aliasSrc = await page.locator("#probe-alias img.for-dark").getAttribute("src");
      const refSrc = await page.locator("#probe-ref img.for-dark").getAttribute("src");
      expect(aliasSrc).toBe(refSrc);
    });
  }
});

test.describe("3단 우선순위(raster > 전용 SVG > generic 폴백)", () => {
  test("raster와 전용 SVG가 둘 다 있으면 raster가 선택된다", async ({ page }) => {
    const hasBoth = await page.evaluate(
      () => window.RMSystemIconsRaster.has("nes") && window.RMSystemIcons.has("nes")
    );
    expect(hasBoth).toBe(true); // 전제 확인: nes는 raster/SVG 둘 다 있는 키다.

    await mountSquareIcon(page, "probe-both", "nes");
    const cls = await page.locator("#probe-both").getAttribute("class");
    expect(cls).toContain("sq-icon-raster");
  });

  test("raster가 없고 전용 SVG만 있으면 SVG가 선택된다", async ({ page }) => {
    const result = await page.evaluate(() => {
      // 실제 raster 자산을 지우지 않고, has()만 이 키에 한해 false를 반환하도록 임시로
      // 감싼다 - renderSystemIcon()의 실제 분기 로직은 그대로 실행된다.
      const raster = window.RMSystemIconsRaster;
      const originalHas = raster.has;
      raster.has = (key) => (key === "nes" ? false : originalHas.call(raster, key));
      try {
        const el = window.__RMIconTestHooks.systemSquareIcon("nes");
        document.body.appendChild(el);
        return { cls: el.className, hasImg: !!el.querySelector("img"), hasSvg: !!el.querySelector("svg") };
      } finally {
        raster.has = originalHas;
      }
    });
    expect(result.cls).not.toContain("sq-icon-raster");
    expect(result.cls).not.toContain("sq-icon-fallback");
    expect(result.hasImg).toBe(false);
    expect(result.hasSvg).toBe(true);
  });

  test("raster/전용 SVG가 둘 다 없으면 generic 카테고리 폴백이 선택된다", async ({ page }) => {
    const result = await page.evaluate(() => {
      const raster = window.RMSystemIconsRaster;
      const svg = window.RMSystemIcons;
      const originalRasterHas = raster.has;
      const originalSvgHas = svg.has;
      raster.has = (key) => (key === "nes" ? false : originalRasterHas.call(raster, key));
      svg.has = (key) => (key === "nes" ? false : originalSvgHas.call(svg, key));
      try {
        const el = window.__RMIconTestHooks.systemSquareIcon("nes");
        document.body.appendChild(el);
        return { cls: el.className, hasSvg: !!el.querySelector("svg") };
      } finally {
        raster.has = originalRasterHas;
        svg.has = originalSvgHas;
      }
    });
    expect(result.cls).toContain("sq-icon-fallback");
    expect(result.hasSvg).toBe(true); // icons.js의 범용 카테고리(cartridge/padRect 등) SVG.
  });

  test("어떤 목록에도 없는 시스템은 예외 없이 기본 폴백을 그린다", async ({ page }) => {
    const result = await page.evaluate(() => {
      const el = window.__RMIconTestHooks.systemSquareIcon("완전히-미지의-시스템-9999");
      document.body.appendChild(el);
      return { cls: el.className, hasSvg: !!el.querySelector("svg") };
    });
    expect(result.hasSvg).toBe(true);
    expect(result.cls).toContain("sq-icon-fallback");
  });
});

test.describe("테마별 raster 아이콘 표시", () => {
  test("light 테마에서는 for-light만 보이고 for-dark는 숨는다", async ({ page }) => {
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
    await mountSquareIcon(page, "probe-theme-light", "nes");
    await expect(page.locator("#probe-theme-light img.for-light")).toBeVisible();
    await expect(page.locator("#probe-theme-light img.for-dark")).toBeHidden();
  });

  test("dark 테마에서는 for-dark만 보이고 for-light는 숨는다", async ({ page }) => {
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
    await mountSquareIcon(page, "probe-theme-dark", "nes");
    await expect(page.locator("#probe-theme-dark img.for-dark")).toBeVisible();
    await expect(page.locator("#probe-theme-dark img.for-light")).toBeHidden();
  });
});

test.describe("decorative alt 텍스트", () => {
  test("raster 아이콘의 img는 alt가 비어있다(시스템명은 title/텍스트가 이미 제공)", async ({ page }) => {
    await mountSquareIcon(page, "probe-alt", "nes");
    await expect(page.locator("#probe-alt img.for-light")).toHaveAttribute("alt", "");
    await expect(page.locator("#probe-alt img.for-dark")).toHaveAttribute("alt", "");
  });
});

test.describe("실제 사이드바 렌더링", () => {
  test("사이드바 System 목록에 raster 아이콘이 실제로 걸린다", async ({ page }) => {
    const src = await page
      .locator("#sidebar .nav-item .sq-icon img.for-dark[src]")
      .first()
      .getAttribute("src");
    expect(src).toBeTruthy();
    expect(src).toMatch(/^data:image\/png;base64,/);
  });
});
