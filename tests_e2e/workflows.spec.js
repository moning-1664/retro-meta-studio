// 핵심 workflow 실제 GUI E2E (Phase 7.21, QA 재검토 P0).
//
// `real-filesystem.spec.js`가 "이미 열려 있는 Collection을 조작하는 것"을 실제
// 파일로 검증한다면, 여기는 리뷰가 지적한 **아직 비어 있던 자리**를 채운다.
//
//   Import      - ROM과 Metadata가 서로 다른 폴더에 있는 실제 배치를 다이얼로그로
//   Archive     - Export -> Archive reload -> Media
//   Revision    - Archive -> Collection으로 보내기 -> 실제 파일
//   Storage     - System을 Internal에서 External로 드래그 -> 실제 이동
//
// 전부 화면의 토스트가 아니라 Node의 `fs`와 다시 읽은 목록으로 확인한다.
const fs = require("fs");
const path = require("path");
const { test, expect } = require("@playwright/test");

let ws;

test.beforeAll(async ({ request }) => {
  ws = await (await request.get("/__workspace")).json();
});

async function openReal(page) {
  await page.goto("/index.html?bridge=http");
  await expect
    .poll(() => page.evaluate(() => window.api && window.api.isMock()))
    .toBe(false);
  await expect(page.locator(".ctab").first()).toBeVisible();
}

async function openTab(page, name) {
  const tab = page.locator(".ctab", { hasText: name }).first();
  if ((await tab.count()) === 0) {
    await page.locator(".ctab-add").click();
    await page.locator(".add-collection-history summary").click();
    await page.locator(".picker-row", { hasText: name }).click();
  } else {
    await tab.click();
  }
  await expect(page.locator(".ctab.active")).toContainText(name, { timeout: 20000 });
}

// ======================================================================
// Import - ROM과 Metadata가 다른 폴더에 있다
// ======================================================================
test.describe("ES-DE Import", () => {
  test("Metadata 폴더와 ROM 폴더를 따로 지정해도 하나의 Collection이 된다", async ({ page }) => {
    await openReal(page);
    await openTab(page, "Source");

    await page.locator(".ctab-add").click();
    await expect(page.locator(".modal-title")).toHaveText("Collection 추가");

    // Metadata 디렉토리와 ROM 디렉토리는 각각 1급 필드다 - 어느 쪽을 넣어야 하는지
    // 사용자가 고민하지 않아도 되고, 둘 중 하나만 채워도 된다.
    await page.locator("#add-metadata-path").fill(ws.freshMetaRoot);
    await page.locator("#add-rom-path").fill(ws.freshRomsRoot);
    await page.locator(".modal-body input[placeholder='예: Android ES-DE']").fill("Fresh");
    await page.locator(".modal-actions .btn.primary", { hasText: "Add" }).click();

    // gba는 ROM만 있고 gamelist가 없다. 그래도 **가로막지 않는다** - ROM만 있는
    // System은 정상이고, gamelist를 미리 만드는 것은 나중에 고를 수 있는 선택지다.

    await expect(page.locator(".ctab.active")).toContainText("Fresh", { timeout: 20000 });

    // **핵심 검증**: 메타데이터 쪽의 snes와 ROM 쪽의 gba가 모두 좌측 내비에 있다.
    // (행 텍스트에 개수가 바로 붙어 "SNES1"처럼 보이므로 hasText로 부분 일치를 본다.)
    await expect(page.locator(".nav-system", { hasText: "SNES" })).toBeVisible({ timeout: 20000 });
    await expect(page.locator(".nav-system", { hasText: "GBA" })).toBeVisible({ timeout: 20000 });

    // Metadata가 실제로 ROM에 연결됐는지 - 목록에서 Zelda 제목을 확인한다.
    await expect(page.locator(".lrow", { hasText: "Zelda" })).toBeVisible({ timeout: 20000 });

    // Import는 아무것도 쓰지 않는다 - 원본 두 폴더가 그대로인지 확인한다.
    expect(fs.existsSync(path.join(ws.freshRomsRoot, "snes", "Zelda.sfc"))).toBe(true);
    expect(fs.existsSync(path.join(ws.freshMetaRoot, "gamelists", "snes", "gamelist.xml")))
      .toBe(true);
  });
});

// ======================================================================
// Archive - Export 후 다시 읽어도 Media가 보인다
// ======================================================================
test.describe("Collection -> Archive", () => {
  test("Archive에 수집하면 Archive 탭에서 media까지 보인다", async ({ page }) => {
    await openReal(page);
    await openTab(page, "Source");

    await page.locator("#collection-header .cheader-right .icon-btn[title*='메타데이터 보내기']").click();
    await page.locator(".ctx-menu .ctx-item", { hasText: "Archive" }).click();
    await expect(page.locator("#toast")).toContainText("수집 완료");

    await page.locator(".ctab.archive").click();
    await expect(page.locator(".ctab.active")).toContainText("Archive");

    const ffxRow = page.locator(".lrow", { hasText: "Final Fantasy X" });
    await expect(ffxRow).toBeVisible({ timeout: 20000 });
    // 목록의 Media 상태와 실제 Archive 복사본을 함께 확인한다.
    await expect(ffxRow.locator('[data-status="mediaLevel"]')).not.toHaveClass(/lv-none/);
    await expect.poll(() => fs.existsSync(path.join(
      ws.archiveRoot, "downloaded_media", "ps2", "covers", "FFX.png")),
    { timeout: 15000 }).toBe(true);
  });
});

// ======================================================================
// Archive -> Collection - 실제로 파일이 옮겨진다
// ======================================================================
test.describe("Archive -> Collection", () => {
  test("Revision을 골라 Collection으로 보내면 실제 파일이 생긴다", async ({ page }) => {
    const destRom = path.join(ws.targetRoot, "ps2", "MGS2.iso");
    expect(fs.existsSync(destRom)).toBe(false);

    await openReal(page);
    await openTab(page, "Source");
    // 이전 테스트에서 이미 수집했을 수 있으니 한 번 더 눌러도 안전해야 한다(멱등).
    await page.locator("#collection-header .cheader-right .icon-btn[title*='메타데이터 보내기']").click();
    await page.locator(".ctx-menu .ctx-item", { hasText: "Archive" }).click();
    await expect(page.locator("#toast")).toContainText("수집 완료");

    // "보내기" 대상 선택 창은 **이미 열려 있는 탭만** 보여준다 - Target을 미리
    // 열어 둬야 그 목록에 나타난다.
    await openTab(page, "Target");
    await page.locator(".ctab.archive").click();
    await expect(page.locator(".ctab.active")).toContainText("Archive");

    // MGS2는 target에 아직 없는 게임이다 - "보내기"가 Plan에 올려 파일을 옮겨야 한다.
    const mgs2Row = page.locator(".lrow", { hasText: "Metal Gear Solid 2" });
    await expect(mgs2Row).toBeVisible({ timeout: 20000 });
    await mgs2Row.locator(".lc-file").click();
    await expect(page.locator(".sb-left")).toContainText("Selected 1");

    await page.locator("#archive-send-btn").click();
    await page.locator(".picker-row", { hasText: "Target" }).click();
    await expect(page.locator("#toast")).toBeVisible();

    // Target으로 건너가서 Plan을 확정한다 - 새 게임은 파일을 옮겨야 하므로 Plan에 올라간다.
    await openTab(page, "Target");
    await expect(page.locator("#filter-bar .plan-actions .seg-btn", { hasText: "Apply" }))
      .toBeVisible({ timeout: 10000 });
    await page.locator("#filter-bar .plan-actions .seg-btn", { hasText: "Apply" }).click();
    await page.locator(".modal-actions .btn.primary").click();
    await expect(page.locator("#toast")).toBeVisible();

    // **여기가 핵심이다** - 화면이 아니라 디스크를 본다.
    await expect.poll(() => fs.existsSync(destRom), { timeout: 15000 }).toBe(true);
    expect(fs.readFileSync(destRom)).toEqual(
      fs.readFileSync(path.join(ws.sourceRoot, "ps2", "MGS2.iso")));

    const xml = fs.readFileSync(path.join(ws.targetRoot, "gamelists", "ps2", "gamelist.xml"),
                                "utf8");
    expect(xml).toContain("Metal Gear Solid 2");
  });
});

// ======================================================================
// Storage 이동 - System을 Internal에서 External로 드래그
// ======================================================================
test.describe("Storage 이동", () => {
  test("System 메뉴로 External로 옮기면 실제 파일이 이동한다", async ({ page }) => {
    const internalRom = path.join(ws.storageRoot, "snes", "Zelda.sfc");
    const externalRom = path.join(ws.storageExternalRoot, "snes", "Zelda.sfc");
    expect(fs.existsSync(internalRom)).toBe(true);
    expect(fs.existsSync(externalRom)).toBe(false);

    await openReal(page);
    await openTab(page, "Storagetest");

    // Navigation에는 Storage 그룹이 없다 - 사용자가 보는 것은 System 목록이다.
    // Storage 이동은 그 System의 우클릭 메뉴에서 한다.
    await page.locator(".nav-system", { hasText: "SNES" }).click({ button: "right" });
    await page.locator(".ctx-menu .ctx-item", { hasText: "SD" }).click();

    // Auto Plan이 켜져 있으므로 Plan에 올라간다 - Apply까지 눌러 확정한다.
    await expect(page.locator("#toast")).toContainText("이동을 Plan에 올렸습니다");
    await page.locator("#filter-bar .plan-actions .seg-btn", { hasText: "Apply" }).click();
    await page.locator(".modal-actions .btn.primary").click();
    await expect(page.locator("#toast")).toBeVisible();

    // **실제 파일이 옮겨졌는지가 핵심이다.**
    await expect.poll(() => fs.existsSync(externalRom), { timeout: 15000 }).toBe(true);
    await expect.poll(() => fs.existsSync(internalRom), { timeout: 15000 }).toBe(false);

    // 다시 읽어도(Reload) 같은 자리를 가리켜야 한다.
    await page.locator("#collection-header .cheader-right .icon-btn[title='다시 스캔']").click();
    const sdGroup = page.locator(".nav-group", {
      has: page.locator(".nav-group-name", { hasText: "SD" }),
    });
    await expect(sdGroup.locator(".nav-system", { hasText: "SNES" }))
      .toBeVisible({ timeout: 20000 });
  });
});

// ======================================================================
// ROM 유지 + Media overwrite 조합 - **더 이상 GUI로 재현하지 않는다.**
//
// Gamelist의 Copy/Paste를 없앴다(QA 재검토 P1, 2026-09-09) - Ctrl+C/Ctrl+V로 두
// Collection 사이에 항목을 옮기던 유일한 화면 경로가 사라졌다. 이 조합이 드러내던
// "메타데이터만"의 항목 단위 해상도 버그(app/plan/builder.py)는 여전히 실재하고
// tests/test_paste_media_overwrite_combo.py가 API 레벨로 계속 검증한다 - 다만 지금
// 화면에는 이걸 재현할 진입점이 없다.
// ======================================================================
