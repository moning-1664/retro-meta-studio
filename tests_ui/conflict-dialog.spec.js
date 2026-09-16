// 충돌 확인 다이얼로그(openConflictDialog, app.js) - 실사용 피드백(스크린샷 첨부):
// "충돌 확인 컨텍스트 창이 너무 촌스럽다" / "뭐가 겹치는 건지 text나 그림으로
// 표현할 방법 없나?"
//
// 예전엔 Collection 고르기용 `.picker-row`를 그대로 재활용한 한 줄짜리 텍스트였고,
// 한 게임에 ROM과 media가 동시에 충돌해도 **첫 번째 이유만 잘려서** 보였다. 지금은
// 충돌마다 종류(ROM/Media)와 기존↔새 파일 크기를 따로 보여준다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

/** __setMockConflictEntries로 채운 뒤 refreshPlan()을 거치는 기존 동작(Delete)을
 * 빌려 목업 상태를 다시 읽게 한다 - storage-move.spec.js의 실패 배지 테스트와 같은
 * 방식이다. */
async function serveConflicts(page, entries) {
  await page.evaluate((e) => window.api.__setMockConflictEntries(e), entries);
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Delete");
}

const ROM_CONFLICT = {
  key: "add|ps2|FFX.iso", op: "add", system: "ps2", filename: "FFX.iso", status: "conflict",
  conflicts: [{
    kind: "rom", reason: "크기가 다릅니다",
    sourceSize: 4600000000, destSize: 4400000000,
  }],
};

const MULTI_CONFLICT = {
  key: "add|ps2|MGS2.iso", op: "add", system: "ps2", filename: "MGS2.iso", status: "conflict",
  conflicts: [
    { kind: "rom", reason: "크기가 다릅니다", sourceSize: 4300000000, destSize: 4100000000 },
    { kind: "media", mediaType: "covers", reason: "크기는 같지만 같은 파일이라고 확신할 수 없습니다",
      sourceSize: 280000, destSize: 280000 },
  ],
};

test("충돌 배지를 누르면 종류·크기가 보이는 다이얼로그가 뜬다", async ({ page }) => {
  await serveConflicts(page, [ROM_CONFLICT]);
  const badge = page.locator(".sb-badge.warn");
  await expect(badge).toContainText("충돌 1");
  await badge.click();

  await expect(page.locator(".modal-title")).toHaveText("충돌 확인");
  const row = page.locator(".copy-conflict-row", { hasText: "FFX.iso" });
  await expect(row).toBeVisible();
  await expect(row.locator(".conflict-detail-kind")).toHaveText("ROM 파일");
  // 기존 4.1GB -> 새 파일 4.3GB - 크기 비교가 읽힌다(formatBytes는 1024 기준 GiB 표기).
  await expect(row.locator(".conflict-size.existing")).toContainText("4.1");
  await expect(row.locator(".conflict-size.incoming")).toContainText("4.3");
  await expect(row.locator(".conflict-detail-reason")).toHaveText("크기가 다릅니다");
});

test("한 게임에 ROM과 Media가 동시에 충돌해도 둘 다 보인다", async ({ page }) => {
  // 예전엔 entry.conflicts[0]만 읽어서 두 번째 충돌(media)이 조용히 가려졌다.
  await serveConflicts(page, [MULTI_CONFLICT]);
  await page.locator(".sb-badge.warn").click();

  const row = page.locator(".copy-conflict-row", { hasText: "MGS2.iso" });
  await expect(row.locator(".conflict-count-badge")).toHaveText("충돌 2개");
  const details = row.locator(".conflict-detail");
  await expect(details).toHaveCount(2);
  await expect(details.nth(0).locator(".conflict-detail-kind")).toHaveText("ROM 파일");
  await expect(details.nth(1).locator(".conflict-detail-kind")).toHaveText("Covers");
});

test("크기가 같은 충돌은 그렇다고 짚어 준다 - 다르다는 문구와 헷갈리지 않는다", async ({ page }) => {
  await serveConflicts(page, [MULTI_CONFLICT]);
  await page.locator(".sb-badge.warn").click();
  const mediaDetail = page.locator(".copy-conflict-row", { hasText: "MGS2.iso" }).locator(".conflict-detail").nth(1);
  await expect(mediaDetail.locator(".conflict-detail-reason")).toHaveClass(/same-size/);
  await expect(mediaDetail.locator(".conflict-detail-reason")).toContainText("크기는 같지만");
});

test("항목별 «메타데이터만»을 고르면 그 항목만 목록에서 빠진다", async ({ page }) => {
  await serveConflicts(page, [ROM_CONFLICT, MULTI_CONFLICT]);
  await page.locator(".sb-badge.warn").click();
  await expect(page.locator(".copy-conflict-row")).toHaveCount(2);

  const ffxRow = page.locator(".copy-conflict-row", { hasText: "FFX.iso" });
  await ffxRow.locator(".btn", { hasText: "메타데이터만" }).click();

  // 해결한 즉시 다이얼로그를 다시 열어 남은 것만 보여준다(app.js: closeModal() 후
  // openConflictDialog() 재호출).
  await expect(page.locator(".copy-conflict-row")).toHaveCount(1);
  await expect(page.locator(".copy-conflict-row")).toContainText("MGS2.iso");
});

test("항목별 «파일 덮어쓰기»도 그 항목만 처리하고 목록에서 뺀다", async ({ page }) => {
  await serveConflicts(page, [ROM_CONFLICT]);
  await page.locator(".sb-badge.warn").click();
  await page.locator(".copy-conflict-row").locator(".btn.danger-outline", { hasText: "파일 덮어쓰기" }).click();
  await expect(page.locator(".modal-title")).toHaveCount(0);   // 더 남은 충돌이 없어 다이얼로그가 안 열린다.
});

test("«모두 메타데이터만»은 확인 없이 즉시 전부 처리한다", async ({ page }) => {
  await serveConflicts(page, [ROM_CONFLICT, MULTI_CONFLICT]);
  await page.locator(".sb-badge.warn").click();
  await page.locator(".modal-actions .btn", { hasText: "모두 메타데이터만" }).click();
  await expect(page.locator(".sb-badge.warn")).toHaveCount(0);
});

test("«모두 덮어쓰기»는 되돌릴 수 없다고 한 번 더 확인한다", async ({ page }) => {
  await serveConflicts(page, [ROM_CONFLICT, MULTI_CONFLICT]);
  await page.locator(".sb-badge.warn").click();
  await page.locator(".modal-actions .btn.danger", { hasText: "모두 덮어쓰기" }).click();
  await expect(page.locator(".modal-text")).toContainText("되돌릴 수 없습니다");
  await modalButton(page, "확인").click();
  await expect(page.locator(".sb-badge.warn")).toHaveCount(0);
});

test("실패 다이얼로그(별개 화면)는 이번 변경의 영향을 받지 않는다", async ({ page }) => {
  // openConflictDialog()와 openFailedDialog()가 예전엔 .conflict-row 클래스를
  // 공유했다 - 이번에 충돌 쪽만 .copy-conflict-row로 이름을 바꿔 서로 다른 CSS를
  // 받게 했다. 실패 쪽이 여전히 정상 동작하는지 함께 본다.
  await page.evaluate(() => window.api.__setMockFailedEntries([
    { key: "add|ps2|X.iso", op: "add", system: "ps2", filename: "X.iso",
      status: "failed", error: "디스크에 쓸 수 없습니다" },
  ]));
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Delete");
  await page.locator(".sb-badge.danger").click();
  await expect(page.locator(".modal-title")).toHaveText("실패한 항목");
  await expect(page.locator(".conflict-row")).toHaveCount(1);
  await expect(page.locator(".copy-conflict-row")).toHaveCount(0);
});
