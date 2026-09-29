const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

async function serveConflicts(page, entries) {
  await page.evaluate((value) => window.api.__setMockConflictEntries(value), entries);
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Delete");
}

const MEDIA_CONFLICT = {
  key: "add|ps2|MGS2.iso", op: "add", system: "ps2", filename: "MGS2.iso",
  status: "conflict", origin: "archive", conflicts: [
    { kind: "media", mediaType: "covers", sourceSize: 280000, destSize: 240000,
      source: "archive-cover", dest: "current-cover" },
    { kind: "media", mediaType: "screenshots", sourceSize: 330000, destSize: 210000,
      source: "archive-screen", dest: "current-screen" },
  ],
};

test("충돌 창은 기존 버튼과 색을 쓰며 이미지 선택에 필요한 내용만 보여준다", async ({ page }) => {
  await serveConflicts(page, [MEDIA_CONFLICT]);
  await page.locator(".sb-badge.warn").click();
  await expect(page.locator(".modal-title")).toHaveText("충돌 확인");
  await expect(page.locator(".conflict-intro"))
    .toHaveText("각 파일에서 사용할 쪽을 고르세요. 최종 적용은 Plan 적용 시 합니다.");
  await expect(page.locator(".conflict-column-heads")).toContainText("현재 Collection");
  await expect(page.locator(".conflict-column-heads")).toContainText("Archive");
  await expect(page.locator(".conflict-preview")).toHaveCount(2);
  await expect(page.locator(".conflict-detail-sizes, .conflict-actions")).toHaveCount(0);
  await expect(page.locator(".modal-actions .btn")).toHaveCount(2);
  await expect(page.locator(".conflict-choice").first()).toHaveClass(/selected/);
});

test("각 그림을 독립적으로 고르고 선택 완료 후에도 다시 바꿀 수 있다", async ({ page }) => {
  await serveConflicts(page, [MEDIA_CONFLICT]);
  await page.locator(".sb-badge.warn").click();
  const pairs = page.locator(".conflict-preview");
  await pairs.nth(1).locator(".conflict-choice.incoming").click();
  await expect(pairs.nth(0).locator(".conflict-choice.existing")).toHaveClass(/selected/);
  await expect(pairs.nth(1).locator(".conflict-choice.incoming")).toHaveClass(/selected/);
  await page.locator(".modal-actions .btn.primary").click();
  await expect(page.locator(".sb-badge.success")).toContainText("선택 완료");
  await page.locator(".sb-badge.success").click();
  await expect(pairs.nth(1).locator(".conflict-choice.incoming")).toHaveClass(/selected/);
  await pairs.nth(0).locator(".conflict-choice.incoming").click();
  await page.locator(".modal-actions .btn.primary").click();
  await expect(page.locator(".sb-badge.success")).toBeVisible();
});

test("나중에는 Plan 선택을 저장하지 않는다", async ({ page }) => {
  await serveConflicts(page, [MEDIA_CONFLICT]);
  await page.locator(".sb-badge.warn").click();
  await page.locator(".modal-actions .btn", { hasText: "나중에" }).click();
  await expect(page.locator(".sb-badge.warn")).toBeVisible();
});

test("이미지를 눌러도 확대창 대신 선택 테두리만 바뀐다", async ({ page }) => {
  await serveConflicts(page, [MEDIA_CONFLICT]);
  await page.evaluate(() => {
    window.api.planConflictPreview = () => Promise.resolve({ ok: true, data: {
      existing: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      incoming: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    } });
  });
  await page.locator(".sb-badge.warn").click();
  const incoming = page.locator(".conflict-preview").first().locator(".conflict-choice.incoming");
  await expect(incoming.locator("img")).toBeVisible();
  await incoming.locator("img").click();
  await expect(incoming).toHaveClass(/selected/);
  await expect(page.locator(".lightbox-card")).toHaveCount(0);
});

test("ROM 충돌도 한 줄의 좌우 선택으로 처리한다", async ({ page }) => {
  const rom = { key: "add|ps2|FFX.iso", op: "add", system: "ps2", filename: "FFX.iso",
    status: "conflict", conflicts: [{ kind: "rom", sourceSize: 44, destSize: 40,
      source: "incoming-rom", dest: "existing-rom" }] };
  await serveConflicts(page, [rom]);
  await page.locator(".sb-badge.warn").click();
  await expect(page.locator(".conflict-choice.existing")).toContainText("현재 ROM");
  await expect(page.locator(".conflict-choice.incoming")).toContainText("가져올 ROM");
});

test("50건이 넘어도 선택 완료 후 남은 충돌을 계속 보여준다", async ({ page }) => {
  const entries = Array.from({ length: 53 }, (_, index) => ({
    ...MEDIA_CONFLICT,
    key: `add|ps2|Bulk${index}.iso`, filename: `Bulk${index}.iso`,
    conflicts: [{ ...MEDIA_CONFLICT.conflicts[0],
      source: `source-${index}`, dest: `dest-${index}` }],
  }));
  await serveConflicts(page, entries);
  await page.locator(".sb-badge.warn").click();
  await expect(page.locator(".copy-conflict-row")).toHaveCount(50);
  await expect(page.locator(".conflict-page-count")).toContainText("1–50 / 53건");
  await page.locator(".modal-actions .btn.primary").click();
  await expect(page.locator(".copy-conflict-row")).toHaveCount(3);
  await expect(page.locator(".conflict-filename").first()).toHaveText("Bulk50.iso");
  await page.locator(".modal-actions .btn.primary").click();
  await expect(page.locator(".sb-badge.success")).toContainText("선택 완료");
  await page.locator(".sb-badge.success").click();
  await expect(page.locator(".copy-conflict-row")).toHaveCount(50);
  await page.locator(".modal-actions .btn", { hasText: "다음", exact: true }).click();
  await expect(page.locator(".conflict-filename").first()).toHaveText("Bulk50.iso");
});

test("실패 다이얼로그는 충돌 화면 변경의 영향을 받지 않는다", async ({ page }) => {
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
