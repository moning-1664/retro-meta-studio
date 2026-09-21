// Archive의 [n] 뱃지 - 같은 ROM에 서로 다른 버전이 둘 이상이고 아직 고르지 않았을 때만.
// Collection에는 Matching이 없다(사용자 결정): 후보를 고르게 하지 않는다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

const ROWS = [
  { romUid: "rid1", romIdentityId: "rid1", system: "ps2", file: "MGS2.iso", title: "Metal Gear Solid 2",
    sources: 2, hasMetadata: true, hasMedia: true, present: true, size: 0, storageId: "archive",
    desc: "", region: "", genre: "", rating: "" },
  { romUid: "rid2", romIdentityId: "rid2", system: "ps2", file: "FFX.iso", title: "Final Fantasy X",
    sources: 1, hasMetadata: true, hasMedia: true, present: true, size: 0, storageId: "archive",
    desc: "", region: "", genre: "", rating: "" },
];

async function openArchive(page, conflicts = { rid1: 2 }) {
  await openApp(page);
  await page.evaluate(({ rows, conflicts }) => {
    let pending = { ...conflicts };
    window.api.archiveRows = () => Promise.resolve({ ok: true, data: { rows, total: rows.length, offset: 0 } });
    window.api.archiveConflicts = () => Promise.resolve({ ok: true, data: { ...pending } });
    window.api.archiveVersions = () => Promise.resolve({ ok: true, data: { romIdentityId: "rid1", versions: [
      { recordIds: [11], sources: ["a"], sourceNames: ["Master"], fields: { name: "MGS2", desc: "Version one" }, media: { covers: 2048 } },
      { recordIds: [12], sources: ["b"], sourceNames: ["Android"], fields: { name: "MGS2 Sons of Liberty", desc: "Version two" }, media: { screenshots: 4096 } },
    ] } });
    window.api.archiveChooseVersion = () => { pending = {}; return Promise.resolve({ ok: true, data: {} }); };
  }, { rows: ROWS, conflicts });
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".lrow").first()).toBeVisible();
}

test("Collection 목록에는 [n] 뱃지가 없다", async ({ page }) => {
  await openApp(page);
  await expect(page.locator(".match-badge")).toHaveCount(0);
});

test("Archive에서는 서로 다른 버전이 있는 행에만 뱃지가 붙는다", async ({ page }) => {
  await openArchive(page);
  await expect(page.locator(".match-badge")).toHaveCount(1);
  await expect(page.locator(".match-badge")).toHaveText("[2]");
  await expect(page.locator(".lrow", { has: page.locator(".match-badge") })).toContainText("Metal Gear Solid 2");
});

test("뱃지를 누르면 판단에 필요한 정보와 함께 버전이 나온다", async ({ page }) => {
  await openArchive(page);
  await page.locator(".match-badge").click();
  await expect(page.locator(".modal-title")).toHaveText("서로 다른 버전");
  const options = page.locator(".match-option");
  await expect(options).toHaveCount(2);
  await expect(options.nth(0)).toContainText("Version one");
  await expect(options.nth(0)).toContainText("Cover");
  await expect(options.nth(1)).toContainText("Version two");
  await expect(page.locator("#detail-panel")).not.toHaveClass(/open/);
});

test("버전을 고르면 뱃지가 사라진다", async ({ page }) => {
  await openArchive(page);
  await page.locator(".match-badge").click();
  await page.locator(".match-option").nth(1).click();
  await expect(page.locator(".match-badge")).toHaveCount(0);
});

test("미디어를 우클릭하면 복사/붙여넣기 메뉴가 나온다", async ({ page }) => {
  await openArchive(page);
  await page.evaluate(() => {
    window.api.archiveDetail = () => Promise.resolve({ ok: true, data: {
      romIdentityId: "rid2", gameId: "g", system: "ps2", filename: "FFX.iso", title: "Final Fantasy X",
      fields: { name: "Final Fantasy X" }, frontendRaw: {}, sources: [], media: [{ media_type: "covers" }],
      romSources: [], edited: false, preferredRecordId: null } });
  });
  await page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".lc-title").click();
  await page.locator(".detail-tab", { hasText: "Media" }).click();
  await page.locator(".media-tile.cover").click({ button: "right" });
  await expect(page.locator(".ctx-item", { hasText: "미디어 복사" })).toBeVisible();
  await expect(page.locator(".ctx-item", { hasText: "미디어 붙여넣기" })).toBeVisible();
});

test("Archive 설정이 없으면 빈 화면에 [Archive 설정] 버튼이 나온다", async ({ page }) => {
  await openApp(page);
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".archive-empty")).toContainText("어디에 어떤 형식");
  await page.locator(".archive-setup").click();
  await expect(page.locator(".modal-title")).toHaveText("Archive 설정");
  await expect(page.locator(".archive-frontend")).toBeVisible();
  await expect(page.locator(".archive-dir")).toBeVisible();
  await expect(page.locator(".archive-rom-dir")).toBeVisible();
  await expect(page.locator(".archive-media-internal")).toBeChecked();
});

test("저장하고 적용하면 설정을 보내고 적용 job을 시작한다", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__calls = [];
    const save = window.api.saveArchiveConfig, apply = window.api.startArchiveApply;
    window.api.saveArchiveConfig = (p) => { window.__calls.push(["save", p]); return save(p); };
    window.api.startArchiveApply = () => { window.__calls.push(["apply"]); return apply(); };
  });
  await page.locator(".ctab.archive").click();
  await page.locator(".archive-setup").click();
  await page.locator(".archive-dir").fill("D:\Archives");
  await page.locator(".archive-apply").click();
  await expect.poll(() => page.evaluate(() => window.__calls.length)).toBe(2);
  const calls = await page.evaluate(() => window.__calls);
  expect(calls[0][1]).toMatchObject({ frontend: "es-de", archiveDir: "D:\Archives", mediaInternal: true });
  expect(calls[1]).toEqual(["apply"]);
});

test("Settings에도 같은 Archive 설정이 있다", async ({ page }) => {
  await openApp(page);
  await page.locator("#btn-settings, [title='Settings'], .settings-btn").first().click();
  await page.locator(".stg-nav-item, .stg-tab", { hasText: "Archive" }).first().click();
  await expect(page.locator(".archive-dir")).toBeVisible();
});

// 사용자 피드백 - "디렉토리 선택도 안했는데 export가 되고 있다. 디렉토리 선택 후 export 가능하도록".
test.describe("디렉토리를 정하기 전에는 보내지 않는다", () => {
  test("Archive로 보내기를 누르면 수집 대신 설정 창이 뜬다", async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      window.__ingests = 0;
      const original = window.api.startArchiveIngest;
      window.api.startArchiveIngest = (...args) => { window.__ingests += 1; return original(...args); };
    });
    await page.locator("#collection-header .cheader-right .icon-btn[title*='메타데이터 보내기']").click();
    await page.locator(".ctx-menu .ctx-item", { hasText: "Archive" }).click();
    await expect(page.locator(".modal-title")).toHaveText("Archive 설정");
    await expect(page.locator("#toast")).toContainText("디렉토리를 먼저 정하세요");
    expect(await page.evaluate(() => window.__ingests)).toBe(0);
  });

  test("디렉토리를 정한 뒤에는 수집이 실행된다", async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => window.api.saveArchiveConfig({ archiveDir: "D:\Archives" }));
    await page.evaluate(() => {
      window.__ingests = 0;
      const original = window.api.startArchiveIngest;
      window.api.startArchiveIngest = (...args) => { window.__ingests += 1; return original(...args); };
    });
    await page.locator("#collection-header .cheader-right .icon-btn[title*='메타데이터 보내기']").click();
    await page.locator(".ctx-menu .ctx-item", { hasText: "Archive" }).click();
    await expect.poll(() => page.evaluate(() => window.__ingests)).toBe(1);
  });
});

// 사용자 결정 - "Media만 복붙하기". Archive는 즉시, Collection은 Plan을 거친다(바이트가 움직인다).
test("Collection에서도 미디어 한 장만 붙여넣을 수 있다 - Plan으로 간다", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__pasted = [];
    window.api.mediaPaste = async (id, romUid, key, source) => {
      window.__pasted.push({ romUid, key, source });
      return { ok: true, data: { added: 1, skipped: [], conflicts: 0 } };
    };
  });
  await page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".lc-file").click();
  await page.locator(".detail-tab", { hasText: "Media" }).click();
  await page.locator(".media-tile.cover").click({ button: "right" });
  await page.locator(".ctx-item", { hasText: "미디어 복사" }).click();
  await page.locator(".media-tile.cover").click({ button: "right" });
  await page.locator(".ctx-item", { hasText: "미디어 붙여넣기" }).click();
  await expect.poll(() => page.evaluate(() => window.__pasted.length)).toBe(1);
  expect((await page.evaluate(() => window.__pasted))[0].key).toBe("Covers");
  await expect(page.locator("#toast")).toContainText("Plan에 올렸습니다");
});
