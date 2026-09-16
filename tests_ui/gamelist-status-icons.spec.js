// Gamelist Status 컬럼 - 실사용 피드백: "Missing Rom/Media/Description/Cover가
// 아이콘으로 나오는게 낫겠음. 각 아이콘은 독립적으로 한 칸을 차지하고, 2개 이상
// 해당되어도 각 위치에 아이콘이 표기." 예전엔 우선순위가 있는 기호 하나만 보여서
// (·/△) 문제가 여러 개면 하나만 보이고 나머지는 가려졌다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const statusIcons = (row) => row.locator(".lc-status .status-icon");
const rowByFile = (page, file) => page.locator(".lrow", { hasText: file });

test("네 칸이 독립적으로 표시되고 문제 없는 항목은 하나도 빨갛지 않다", async ({ page }) => {
  const ffx = rowByFile(page, "Final Fantasy X");   // 목업에서 전부 있는 유일한 행.
  await expect(statusIcons(ffx)).toHaveCount(4);
  await expect(statusIcons(ffx)).toHaveClass([/^status-icon(?! missing)/, /^status-icon(?! missing)/,
    /^status-icon(?! missing)/, /^status-icon(?! missing)/]);
});

test("Media는 있고 Cover만 없는 조합도 그 칸만 따로 빨갛다", async ({ page }) => {
  // mockRows의 MGS2는 media 전체가 없다(media-video.spec.js가 그 값에 기대고
  // 있다) - "media는 있는데 cover만 없다"는 별개 조합이라 이 테스트 안에서만
  // listRows를 바꿔 끼운다. 공용 목업을 고치면 media-video 쪽이 깨진다.
  await page.evaluate(() => {
    const original = window.api.listRows;
    window.api.listRows = async (id, q) => {
      const r = await original(id, q);
      if (r.ok) r.data.rows.forEach((row) => {
        if (row.file === "MGS2.iso") { row.hasMedia = true; row.hasCover = false; }
      });
      return r;
    };
  });
  await page.locator(".nav-system", { hasText: "PS2" }).click();
  const mgs2 = rowByFile(page, "Metal Gear Solid 2");
  await expect(statusIcons(mgs2).nth(1)).not.toHaveClass(/missing/);   // media
  await expect(statusIcons(mgs2).nth(3)).toHaveClass(/missing/);       // cover
});

/** SMW 행(hasMetadata/hasMedia/hasCover 전부 false)에 present까지 false로 덮어
 * 쓴다 - mockRows의 SMW는 ROM은 있는 상태라, "네 개 다 없다"를 보려면 ROM까지
 * 없는 조합을 직접 만들어야 한다. */
async function serveSmwWithoutRom(page) {
  await page.evaluate(() => {
    const original = window.api.listRows;
    window.api.listRows = async (id, q) => {
      const r = await original(id, q);
      if (r.ok) r.data.rows.forEach((row) => { if (row.file === "SMW.sfc") row.present = false; });
      return r;
    };
  });
  await page.locator(".nav-system", { hasText: "SNES" }).click();
}

test("ROM/Media/Description/Cover가 전부 없으면 네 칸 다 빨갛다", async ({ page }) => {
  await serveSmwWithoutRom(page);
  const smw = rowByFile(page, "Super Mario World");
  const icons = statusIcons(smw);
  await expect(icons).toHaveCount(4);
  for (let i = 0; i < 4; i += 1) await expect(icons.nth(i)).toHaveClass(/missing/);
});

test("툴팁이 어느 항목이 없는지 말해준다", async ({ page }) => {
  await serveSmwWithoutRom(page);
  const smw = rowByFile(page, "Super Mario World");
  await expect(statusIcons(smw).nth(0)).toHaveAttribute("title", /ROM 없음/);
  await expect(statusIcons(smw).nth(2)).toHaveAttribute("title", /Description 없음/);
  await expect(statusIcons(smw).nth(3)).toHaveAttribute("title", /Cover 없음/);
});

test("Plan 표시(추가/삭제/편집 예정)가 있으면 네 칸 대신 그 표시 하나만 보인다", async ({ page }) => {
  // Plan 마크가 "지금 뭐가 없는지"보다 "곧 뭐가 바뀌는지"를 우선한다 - 기존 동작
  // 그대로다(statusMark의 Plan 우선순위). 목업의 plan_delete()는 삭제를 실제로
  // 기록하지 않는 stub이라(항상 { deleted: 1 }만 돌려준다) Delete 키로는 이
  // 경로를 재현할 수 없다 - plan-badge.spec.js와 같은 방식으로 planState를 직접
  // 바꿔 끼운다.
  const row = page.locator(".lrow").first();
  await page.evaluate(() => {
    const original = window.api.planState;
    window.api.planState = async (id) => {
      const r = await original(id);
      if (r.ok) r.data.marks = { rows: { "ps2|FFX.iso": "-" }, systems: [] };
      return r;
    };
  });
  // plan_delete() 목업은 stub이라 실제로는 아무것도 기록하지 않지만, 그 뒤에
  // refreshPlan()이 부르는 planState()는 방금 바꿔 끼운 값을 돌려준다 - 그걸로
  // 화면이 다시 그려지는지를 본다(plan-badge.spec.js와 같은 방식).
  await row.click();
  await page.keyboard.press("Delete");
  await expect(row.locator(".lc-status .status-mark.del")).toBeVisible();
  await expect(row.locator(".lc-status .status-icon")).toHaveCount(0);
});

test("Metadata 전용 Collection에서는 ROM 칸만 빨갛게 켜지지 않는다", async ({ page }) => {
  await page.evaluate(() => {
    const original = window.api.collectionDetail;
    window.api.collectionDetail = async (id) => {
      const r = await original(id);
      if (r.ok) r.data.metadataOnly = true;
      return r;
    };
  });
  await page.reload();
  await page.waitForSelector(".lrow");
  const smw = page.locator(".lrow", { hasText: "Super Mario World" });
  // SMW는 hasMedia/hasDescription/hasCover도 없다 - 그 칸들은 여전히 빨갛다.
  await expect(statusIcons(smw).nth(0)).not.toHaveClass(/missing/);   // ROM - metaOnly라 무시
  await expect(statusIcons(smw).nth(2)).toHaveClass(/missing/);       // description
});
