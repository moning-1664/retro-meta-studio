// Collection 탭 순서, 창 네 변 크기 조절, 복사 정책 Settings (stitch-v3 Phase 9).
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const tabNames = async (page) =>
  (await page.locator("#tabs-bar .ctab:not(.archive) .ctab-name").allTextContents()).map((t) => t.trim());

async function openSecondCollection(page) {
  await page.locator(".ctab-add").click();
  await page.locator(".add-collection-history summary").click();
  await page.locator(".picker-row", { hasText: "Android ES-DE" }).click();
  await expect.poll(() => tabNames(page)).toEqual(["Master Library", "Android ES-DE"]);
}

const tab = (page, name) => page.locator("#tabs-bar .ctab", { hasText: name });

test.describe("Collection 탭 순서", () => {
  test("탭을 끌어 다른 탭 앞에 놓으면 순서가 바뀌고 저장된다", async ({ page }) => {
    await openSecondCollection(page);
    await page.evaluate(() => {
      window.__saved = [];
      const original = window.api.saveAppSettings;
      window.api.saveAppSettings = (patch) => { window.__saved.push(patch); return original(patch); };
    });
    await tab(page, "Android ES-DE").dragTo(tab(page, "Master Library"), { targetPosition: { x: 6, y: 10 } });
    await expect.poll(() => tabNames(page)).toEqual(["Android ES-DE", "Master Library"]);
    await expect.poll(() => page.evaluate(() => window.__saved.length)).toBeGreaterThan(0);
    const saved = await page.evaluate(() => window.__saved.at(-1));
    expect(saved.collections.order).toEqual(["c2", "c1"]);
  });

  test("닫았다 다시 열어도 정한 자리로 돌아간다", async ({ page }) => {
    await openSecondCollection(page);
    await tab(page, "Android ES-DE").dragTo(tab(page, "Master Library"), { targetPosition: { x: 6, y: 10 } });
    await expect.poll(() => tabNames(page)).toEqual(["Android ES-DE", "Master Library"]);

    await tab(page, "Android ES-DE").locator(".ctab-close").click();
    await expect.poll(() => tabNames(page)).toEqual(["Master Library"]);
    await page.locator(".ctab-add").click();
    await page.locator(".add-collection-history summary").click();
    await page.locator(".picker-row", { hasText: "Android ES-DE" }).click();
    await expect.poll(() => tabNames(page)).toEqual(["Android ES-DE", "Master Library"]);
  });

  test("Archive 탭은 끌 수 없고 늘 맨 앞이다", async ({ page }) => {
    await openSecondCollection(page);
    await expect(page.locator("#tabs-bar .ctab.archive")).not.toHaveAttribute("draggable", "true");
    await tab(page, "Android ES-DE").dragTo(page.locator("#tabs-bar .ctab.archive"), { targetPosition: { x: 4, y: 10 } });
    await expect(page.locator("#tabs-bar .ctab").first()).toHaveClass(/archive/);
  });

  test("끈 뒤에도 탭을 누르면 그 Collection이 열린다", async ({ page }) => {
    await openSecondCollection(page);
    await tab(page, "Android ES-DE").dragTo(tab(page, "Master Library"), { targetPosition: { x: 6, y: 10 } });
    await tab(page, "Master Library").click();
    await expect(tab(page, "Master Library")).toHaveClass(/active/);
  });
});

test.describe("창 크기 조절 - 네 변과 네 모서리", () => {
  const spyBounds = async (page) => {
    await page.evaluate(() => {
      window.__bounds = [];
      window.__resize = [];
      window.api.windowSetBounds = async (x, y, w, h) => { window.__bounds.push({ x, y, w, h }); return { ok: true }; };
      window.api.windowResize = async (w, h) => { window.__resize.push({ w, h }); return { ok: true }; };
    });
    return page.evaluate(() => ({ x: window.screenX, y: window.screenY, w: window.outerWidth, h: window.outerHeight }));
  };
  const drag = async (page, selector, dx, dy) => {
    const box = await page.locator(selector).boundingBox();
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + dx, y + dy, { steps: 4 });
    await page.mouse.up();
  };

  test("오른쪽 아래 손잡이 말고도 일곱 곳에 손잡이가 있다", async ({ page }) => {
    const edges = await page.locator(".window-resize-grip").evaluateAll((els) => els.map((e) => e.dataset.edge));
    expect(edges.sort()).toEqual(["e", "n", "ne", "nw", "s", "sw", "w"]);
  });

  test("왼쪽 변을 끌면 오른쪽 끝은 그대로 두고 위치와 폭을 함께 바꾼다", async ({ page }) => {
    const start = await spyBounds(page);
    await drag(page, ".window-resize-grip.w", 100, 0);
    await expect.poll(() => page.evaluate(() => window.__bounds.length)).toBeGreaterThan(0);
    const last = await page.evaluate(() => window.__bounds.at(-1));
    expect(last.w).toBe(start.w - 100);
    expect(last.x).toBe(start.x + 100);
    expect(last.x + last.w).toBe(start.x + start.w);
    expect(last.y).toBe(start.y);
  });

  test("위 변은 최소 높이 아래로 줄지 않고, 아래 끝은 제자리다", async ({ page }) => {
    const start = await spyBounds(page);
    await drag(page, ".window-resize-grip.n", 0, 2000);
    await expect.poll(() => page.evaluate(() => window.__bounds.length)).toBeGreaterThan(0);
    const last = await page.evaluate(() => window.__bounds.at(-1));
    expect(last.h).toBe(640);
    expect(last.y + last.h).toBe(start.y + start.h);
  });

  test("오른쪽 변은 위치를 옮기지 않고 크기만 바꾼다", async ({ page }) => {
    const start = await spyBounds(page);
    await drag(page, ".window-resize-grip.e", -50, 0);
    await expect.poll(() => page.evaluate(() => window.__resize.length)).toBeGreaterThan(0);
    const last = await page.evaluate(() => window.__resize.at(-1));
    expect(last.w).toBe(Math.max(900, start.w - 50));
    expect(await page.evaluate(() => window.__bounds.length)).toBe(0);
  });
});

test.describe("Settings - Collection → Collection 복사 정책", () => {
  test("ROM/Media 복사와 충돌 처리를 바꾸면 저장된다", async ({ page }) => {
    await page.evaluate(() => {
      window.__saved = [];
      const original = window.api.saveAppSettings;
      window.api.saveAppSettings = (patch) => { window.__saved.push(patch); return original(patch); };
    });
    await page.locator(".nav-top .icon-btn[title='Settings']").click();
    await page.locator(".stg-nav-item[data-section='transfer']").click();
    const media = page.locator(".stg-row[data-key='transfer.includeMedia']");
    await expect(media).not.toHaveClass(/soon/);
    await media.locator(".stg-switch").click();
    await page.locator(".stg-row[data-key='transfer.conflict'] select").selectOption("skip");
    await expect.poll(async () => {
      const all = await page.evaluate(() => window.__saved);
      return Object.assign({}, ...all.map((p) => p.transfer || {}));
    }).toEqual({ includeMedia: false, conflict: "skip" });
  });
});
