// 실제 파일시스템 E2E (Phase 7.12).
//
// tests_ui/의 62개는 목업 API 위에서 돈다. 화면 로직은 검증하지만 **"성공했습니다"라는
// 토스트가 떴다는 것과 실제로 파일이 그렇게 됐다는 것은 다르다.**
//
// 여기서는 실제 파이썬 Api에 HTTP로 붙어서 전체 사슬을 통과시킨다.
//
//     브라우저 -> api-client -> HTTP -> Api -> FileOperationEngine
//              -> 실제 파일 -> Cache -> 다시 화면
//
// 그리고 **검증은 화면이 아니라 디스크로 한다.** Node에서 fs로 직접 읽는다.
const fs = require("fs");
const path = require("path");
const { test, expect } = require("@playwright/test");

let ws;

test.beforeAll(async ({ request }) => {
  ws = await (await request.get("/__workspace")).json();
});

/** 실제 브릿지에 붙은 화면을 연다. 목업이면 즉시 실패시킨다. */
async function openReal(page) {
  await page.goto("/index.html?bridge=http");
  await expect
    .poll(() => page.evaluate(() => window.api && window.api.isMock()))
    .toBe(false);                       // 목업이면 이 파일은 아무 의미가 없다
  await expect(page.locator(".ctab").first()).toBeVisible();
}

/** 탭이 없으면 Collection 열기 창을 거쳐 연다 - 앱은 마지막에 열던 것만 복원한다. */
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

const targetRom = (n) => path.join(ws.targetRoot, "ps2", n);
const targetCover = (n) => path.join(ws.targetRoot, "downloaded_media", "ps2", "covers", n);
const sourceGamelist = () => path.join(ws.sourceRoot, "gamelists", "ps2", "gamelist.xml");

test.describe("실제 자료를 읽는다", () => {
  test("Collection을 열면 디스크에 있는 ROM이 목록에 뜬다", async ({ page }) => {
    await openReal(page);
    await openTab(page, "Source");
    await expect(page.locator(".lrow")).toHaveCount(2);
    await expect(page.locator(".lrow")).toContainText(["Final Fantasy X", "Metal Gear Solid 2"]);
  });

  test("목록의 제목은 실제 gamelist.xml에서 온 것이다", async ({ page }) => {
    // 화면에 보이는 값이 목업 상수가 아니라 파일에서 왔는지 확인한다.
    expect(fs.readFileSync(sourceGamelist(), "utf8")).toContain("Final Fantasy X");
    await openReal(page);
    await openTab(page, "Source");
    await expect(page.locator(".lrow").first()).toContainText("Final Fantasy X");
  });
});

test.describe("편집하면 실제 파일이 바뀐다", () => {
  test("장르를 고쳐 저장하면 gamelist.xml이 실제로 바뀐다", async ({ page }) => {
    await openReal(page);
    await openTab(page, "Source");
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();

    const genre = page.locator("#detail-panel .field-input").nth(2);
    await expect(genre).toBeVisible();
    await genre.fill("Japanese RPG");
    await page.locator("#detail-panel .btn", { hasText: "저장" }).click();
    await expect(page.locator("#toast")).toBeVisible();

    await expect
      .poll(() => fs.readFileSync(sourceGamelist(), "utf8").includes("Japanese RPG"),
            { timeout: 5000 })
      .toBe(true);
  });

  test("저장해도 우리가 모르는 태그는 파일에 남는다", async ({ page }) => {
    // Phase 7.9가 지킨 것 - 실제 저장 경로에서도 지켜지는지 화면을 통해 확인한다.
    await openReal(page);
    await openTab(page, "Source");
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();
    const genre = page.locator("#detail-panel .field-input").nth(2);
    await genre.fill("RPG 2");
    await page.locator("#detail-panel .btn", { hasText: "저장" }).click();
    await expect(page.locator("#toast")).toBeVisible();

    await expect.poll(() => {
      const xml = fs.readFileSync(sourceGamelist(), "utf8");
      return xml.includes("RPG 2") && xml.includes("playcount")
             && xml.includes("alternativeEmulator");
    }, { timeout: 5000 }).toBe(true);
  });
});

// Copy/Paste는 Gamelist에서 없앴다(QA 재검토 P1) - "Collection으로 보내기"
// (Archive -> Collection)가 Collection 사이에 항목을 옮기는 유일한 경로다. Plan
// Execute가 실제로 파일을 옮기는지는 그 경로로 확인한다.
test.describe("Plan Execute가 실제로 파일을 옮긴다", () => {
  test("Archive에서 보내기 → 실행하면 ROM과 커버가 실제로 생긴다", async ({ page }) => {
    expect(fs.existsSync(targetRom("FFX.iso"))).toBe(false);

    await openReal(page);
    await openTab(page, "Source");
    await page.locator("#filter-bar .btn", { hasText: "Archive에 수집" }).click();
    await expect(page.locator("#toast")).toContainText("수집 완료");

    // "보내기" 대상 선택 창은 이미 열려 있는 탭만 보여준다.
    await openTab(page, "Target");
    await page.locator(".ctab.archive").click();
    await expect(page.locator(".ctab.active")).toContainText("Archive");

    const ffxRow = page.locator(".lrow", { hasText: "Final Fantasy X" });
    await expect(ffxRow).toBeVisible({ timeout: 20000 });
    await ffxRow.locator(".lc-file").click();
    await expect(page.locator(".sb-left")).toContainText("Selected 1");

    await page.locator(".sb-actions .btn", { hasText: "Collection으로 보내기" }).click();
    await page.locator(".picker-row", { hasText: "Target" }).click();
    await expect(page.locator("#toast")).toBeVisible();

    await openTab(page, "Target");
    await expect(page.locator("#filter-bar .btn", { hasText: /^Apply \(/ })).toBeVisible();

    await page.locator("#filter-bar .btn", { hasText: /^Apply \(/ }).click();
    // Apply는 확인 모달을 한 번 거친다 - 실제 파일을 바꾸는 동작이기 때문이다.
    await page.locator(".modal-actions .btn.primary").click();
    await expect(page.locator("#toast")).toBeVisible();

    // **여기가 이 파일의 핵심이다.** 토스트가 아니라 디스크를 본다.
    await expect.poll(() => fs.existsSync(targetRom("FFX.iso")), { timeout: 15000 }).toBe(true);
    expect(fs.readFileSync(targetRom("FFX.iso"))).toEqual(
      fs.readFileSync(path.join(ws.sourceRoot, "ps2", "FFX.iso")));
    expect(fs.existsSync(targetCover("FFX.png"))).toBe(true);

    const xml = fs.readFileSync(path.join(ws.targetRoot, "gamelists", "ps2", "gamelist.xml"),
                                "utf8");
    expect(xml).toContain("FFX.iso");
    expect(xml).toContain("Final Fantasy X");
  });

  test("실행 결과가 다시 읽어들인 목록에도 나타난다", async ({ page }) => {
    await openReal(page);
    await openTab(page, "Target");
    await expect(page.locator(".lrow")).toContainText(["Final Fantasy X"]);
  });
});

test.describe("Cancel은 아무것도 바꾸지 않는다", () => {
  test("보내기 후 Plan을 취소하면 파일이 생기지 않는다", async ({ page }) => {
    const before = fs.readdirSync(path.join(ws.targetRoot, "ps2")).sort();

    await openReal(page);
    await openTab(page, "Source");
    // 이전 테스트에서 이미 수집했을 수 있으니 한 번 더 눌러도 안전해야 한다(멱등).
    await page.locator("#filter-bar .btn", { hasText: "Archive에 수집" }).click();
    await expect(page.locator("#toast")).toContainText("수집 완료");

    await openTab(page, "Target");
    await page.locator(".ctab.archive").click();
    await expect(page.locator(".ctab.active")).toContainText("Archive");

    const mgs2Row = page.locator(".lrow", { hasText: "Metal Gear Solid 2" });
    await expect(mgs2Row).toBeVisible({ timeout: 20000 });
    await mgs2Row.locator(".lc-file").click();
    await expect(page.locator(".sb-left")).toContainText("Selected 1");

    await page.locator(".sb-actions .btn", { hasText: "Collection으로 보내기" }).click();
    await page.locator(".picker-row", { hasText: "Target" }).click();
    await expect(page.locator("#toast")).toBeVisible();

    await openTab(page, "Target");
    await expect(page.locator("#filter-bar .btn", { hasText: /^Apply \(/ })).toBeVisible();

    // Plan 버리기는 목록 위 Cancel 버튼이다(예전에는 지우개 아이콘이었다).
    // 되돌릴 수 없는 동작이 아니지만 계산한 것을 버리는 것이라 한 번 확인한다.
    await page.locator("#filter-bar .btn", { hasText: "Cancel" }).click();
    await page.locator(".modal-actions .btn", { hasText: "확인" }).click();
    await expect(page.locator(".modal-actions")).toHaveCount(0);

    // **확인 창에서 취소했으면 디스크는 그대로여야 한다.**
    expect(fs.readdirSync(path.join(ws.targetRoot, "ps2")).sort()).toEqual(before);
  });
});

test.describe("Card 보기 - 실제 자료", () => {
  test("Card로 전환하면 실제 게임 수만큼 카드가 뜬다", async ({ page }) => {
    await openReal(page);
    await openTab(page, "Source");
    await expect(page.locator(".lrow")).toHaveCount(2);

    await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
    await expect(page.locator(".preview-card")).toHaveCount(2);
    await expect(page.locator(".preview-title")).toContainText(["Final Fantasy X"]);
  });
});

test.describe("Detail Media 확대(lightbox) - 실제 파일", () => {
  test("Cover를 누르면 실제 파일 데이터로 확대된 이미지가 뜬다", async ({ page }) => {
    const coverBytes = fs.readFileSync(
      path.join(ws.sourceRoot, "downloaded_media", "ps2", "covers", "FFX.png"));

    await openReal(page);
    await openTab(page, "Source");
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".lc-file").click();
    await expect(page.locator("#detail-panel")).toHaveClass(/open/);
    await page.locator(".detail-tab", { hasText: "Media" }).click();

    const cover = page.locator(".media-tile[title='Cover']");
    await expect(cover).toHaveClass(/clickable/);
    await cover.click();

    const lightboxImg = page.locator(".lightbox-img");
    await expect(lightboxImg).toBeVisible();
    const src = await lightboxImg.getAttribute("src");
    expect(src).toMatch(/^data:image\//);
    // 목업의 자리표시 그림이 아니라 **실제 커버 파일 바이트**여야 한다.
    const decoded = Buffer.from(src.split(",")[1], "base64");
    expect(decoded.equals(coverBytes)).toBe(true);

    await page.keyboard.press("Escape");
    await expect(page.locator(".lightbox-img")).toHaveCount(0);
  });
});

test.describe("외부에서 파일이 바뀌면 다시 읽어 반영한다", () => {
  test("탐색기로 ROM을 추가하고 새로고침하면 목록에 나온다", async ({ page }) => {
    fs.writeFileSync(path.join(ws.sourceRoot, "ps2", "Ico.iso"), Buffer.alloc(512, 7));

    await openReal(page);
    await openTab(page, "Source");
    await page.locator("#filter-bar .icon-btn[title='다시 스캔']").click();
    await expect(page.locator(".lrow", { hasText: "Ico" })).toBeVisible({ timeout: 20000 });
  });

  test("탐색기로 ROM을 지우고 새로고침하면 목록에서 빠진다", async ({ page }) => {
    fs.unlinkSync(path.join(ws.sourceRoot, "ps2", "Ico.iso"));

    await openReal(page);
    await openTab(page, "Source");
    await page.locator("#filter-bar .icon-btn[title='다시 스캔']").click();
    await expect(page.locator(".lrow", { hasText: "Ico" })).toHaveCount(0, { timeout: 20000 });
  });
});
