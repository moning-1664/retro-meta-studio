// 목록/Detail 다듬기 (stitch-v3 Phase 6) - 실사용 피드백에서 온 것들이다.
//
//   - 스크롤하는 동안 File 컬럼이 넓어졌다가 멈추면 돌아온다.
//   - ROM 파일이 있는 행과 없는 행의 파일명이 구분되지 않는다.
//   - Description을 저장해도 목록에는 다른 System에 갔다 와야 보인다.
//   - Detail의 파일명을 드래그해서 Ctrl+C 해도 복사되지 않는다.
//   - Media 확대 이미지가 창 크기에 맞지 않는다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const openFirstGame = async (page) => {
  await page.locator(".lrow").first().locator(".lc-file").click();
  await expect(page.locator("#detail-panel")).toHaveClass(/open/);
};

/** 첫 페이지만 주고 나머지 페이지는 오지 않는 목록으로 바꾼 뒤 다시 읽힌다. */
async function serveFirstPageOnly(page, patchRows) {
  await page.evaluate((patchSource) => {
    const original = window.api.listRows;
    const patch = patchSource ? new Function("rows", patchSource) : null;
    window.api.listRows = async (id, q) => {
      if (q.offset > 0) return new Promise(() => {});
      const r = await original(id, q);
      if (patch) patch(r.data.rows);
      return { ok: true, data: { ...r.data, total: 400 } };
    };
  }, patchRows || null);
  await page.locator(".nav-system", { hasText: "SNES" }).click();
}

test.describe("아직 받지 않은 줄(자리표시)", () => {
  test("실제 행과 같은 컬럼 틀을 쓴다", async ({ page }) => {
    await serveFirstPageOnly(page);
    const placeholder = page.locator(".lrow.placeholder").first();
    await expect(placeholder).toBeVisible();
    const real = page.locator(".lrow:not(.placeholder)").first();
    const [a, b] = await Promise.all([
      real.evaluate((el) => el.style.gridTemplateColumns),
      placeholder.evaluate((el) => el.style.gridTemplateColumns),
    ]);
    expect(b).not.toBe("");
    expect(b).toBe(a);
  });

  test("File 칸의 폭이 실제 행과 같다", async ({ page }) => {
    await serveFirstPageOnly(page);
    const placeholderFile = page.locator(".lrow.placeholder").first().locator(".lc-file");
    await expect(placeholderFile).toBeVisible();
    const realBox = await page.locator(".lrow:not(.placeholder)").first().locator(".lc-file").boundingBox();
    const placeholderBox = await placeholderFile.boundingBox();
    expect(Math.round(placeholderBox.x)).toBe(Math.round(realBox.x));
    expect(Math.round(placeholderBox.width)).toBe(Math.round(realBox.width));
  });
});

test.describe("파일명 색 - ROM 파일이 있는지", () => {
  test("ROM이 있으면 제목과 같은 색이다", async ({ page }) => {
    const row = page.locator(".lrow").first();
    await expect(row.locator(".lc-file")).toHaveClass(/rom-present/);
    const [file, title] = await Promise.all([
      row.locator(".lc-file").evaluate((el) => getComputedStyle(el).color),
      row.locator(".lc-title").evaluate((el) => getComputedStyle(el).color),
    ]);
    expect(file).toBe(title);
  });

  test("ROM이 없으면 흐린 색이고 툴팁으로 알려준다", async ({ page }) => {
    await serveFirstPageOnly(page, "rows.forEach((r) => { r.present = false; });");
    const file = page.locator(".lrow:not(.placeholder)").first().locator(".lc-file");
    await expect(file).toHaveClass(/rom-missing/);
    await expect(file).toHaveAttribute("title", /ROM 파일 없음/);
    const [fileColor, titleColor] = await Promise.all([
      file.evaluate((el) => getComputedStyle(el).color),
      page.locator(".lrow:not(.placeholder)").first().locator(".lc-title")
        .evaluate((el) => getComputedStyle(el).color),
    ]);
    expect(fileColor).not.toBe(titleColor);
  });
});

test.describe("저장하면 목록에 바로 보인다", () => {
  test("설명", async ({ page }) => {
    await openFirstGame(page);
    await page.locator(".detail-body-desc-wrap textarea").fill("새로 적은 설명");
    await page.locator(".detail-footer .btn.primary").click();
    await expect(page.locator(".lrow").first().locator(".lc-desc")).toHaveText("새로 적은 설명");
  });

  test("Genre / Region", async ({ page }) => {
    await openFirstGame(page);
    await page.locator("#detail-panel div:has(> .field-label:has-text('장르')) > input").fill("Puzzle");
    await page.locator("#detail-panel div:has(> .field-label:has-text('지역')) > input").fill("jp");
    await page.locator(".detail-footer .btn.primary").click();
    const row = page.locator(".lrow").first();
    await expect(row.locator(".lc-genre")).toHaveText("Puzzle");
    await expect(row.locator(".lc-region")).toHaveText("jp");
  });
});

test.describe("Detail 파일명 복사", () => {
  test("글자를 골라 둔 Ctrl+C는 게임 복사로 가로채지 않는다", async ({ page }) => {
    await openFirstGame(page);
    const calls = await page.evaluate(() => {
      window.__copied = 0;
      window.api.copySelection = async () => { window.__copied += 1; return { ok: true, data: { count: 1 } }; };
      const el = document.querySelector(".detail-filename");
      const range = document.createRange();
      range.selectNodeContents(el);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      return window.__copied;
    });
    expect(calls).toBe(0);
    await page.keyboard.press("Control+c");
    await expect(page.locator(".toast-msg", { hasText: "복사했습니다" })).toHaveCount(0);
    expect(await page.evaluate(() => window.__copied)).toBe(0);
  });

  test("골라 둔 글자가 없으면 Ctrl+C는 여전히 게임 복사다", async ({ page }) => {
    await page.locator(".lrow").first().locator(".lc-file").click();
    await page.evaluate(() => {
      window.__copied = 0;
      window.getSelection().removeAllRanges();
      window.api.copySelection = async () => { window.__copied += 1; return { ok: true, data: { count: 1 } }; };
    });
    await page.keyboard.press("Control+c");
    await expect.poll(() => page.evaluate(() => window.__copied)).toBe(1);
  });

  test("옆 버튼으로 파일명을 복사한다", async ({ page }) => {
    await openFirstGame(page);
    await page.evaluate(() => {
      window.__clip = null;
      Object.defineProperty(navigator, "clipboard", {
        configurable: true, value: { writeText: async (t) => { window.__clip = t; } },
      });
    });
    const name = await page.locator(".detail-filename").textContent();
    await page.locator(".detail-copy").click();
    await expect.poll(() => page.evaluate(() => window.__clip)).toBe(name);
  });
});

test.describe("Media 확대가 창에 맞는다", () => {
  test("낮고 좁은 창에서도 이미지와 카드가 창 안에 있다", async ({ page }) => {
    await page.setViewportSize({ width: 820, height: 520 });
    await openFirstGame(page);
    await page.locator(".detail-tab", { hasText: "미디어" }).click();
    await page.locator(".media-tile[title='Cover']").click();
    const img = page.locator(".lightbox-img");
    await expect(img).toBeVisible();
    for (const box of [await img.boundingBox(), await page.locator(".lightbox-card").boundingBox()]) {
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(820);
      expect(box.y + box.height).toBeLessThanOrEqual(520);
    }
    const scrolls = await page.locator(".lightbox-body").evaluate((el) => el.scrollHeight > el.clientHeight + 1);
    expect(scrolls).toBe(false);
  });
});
