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
