// ROM만 있는 Collection과 Archive 수집 범위 - **실제 파일로** 확인한다.
//
// 목업은 이 둘에 답할 수 없다.
//
//   - "Metadata 칸을 비우고 ROM 폴더만 줘도 Collection이 열리는가"는 실제 디스크를
//     훑어 System을 찾아내야 알 수 있다.
//   - "MSX1만 골라 수집했는데 정말 MSX1만 들어갔는가"는 Archive DB에 실제로 무엇이
//     들어갔는지 봐야 알 수 있다. 토스트 문구는 증거가 아니다.
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

//: ROM만 있는 Collection의 이름. **테스트마다 새로 만들지 않는다** - 동시에 열 수
//  있는 Collection은 10개까지고(스펙 §2.2), 이 하네스는 Api 인스턴스 하나를 공유한다.
const ROM_ONLY = "RomOnly";

/** ROM만 있는 Collection을 연다. 없으면 그때 한 번 만든다.
 *
 * 만들 때 Metadata 칸은 비우고 ROM 폴더만 준다 - 그것이 이 파일의 검증 대상이다.
 */
async function openRomOnly(page) {
  const tab = page.locator(".ctab", { hasText: ROM_ONLY }).first();
  if (await tab.count()) {
    await tab.click();
    await expect(page.locator(".ctab.active")).toContainText(ROM_ONLY, { timeout: 30000 });
    return false;
  }

  await page.locator(".ctab-add").click();
  await expect(page.locator(".modal-title")).toHaveText("Collection 추가");

  // History에 이미 있으면(앞 테스트가 만든 것) 다시 만들지 않고 그것을 연다.
  await page.locator(".add-collection-history summary").click();
  const known = page.locator(".picker-row", { hasText: ROM_ONLY }).first();
  if (await known.count()) {
    await known.click();
    await expect(page.locator(".ctab.active")).toContainText(ROM_ONLY, { timeout: 30000 });
    return false;
  }

  await page.locator("#add-rom-path").fill(ws.bareRomsRoot);
  await page.locator(".modal-body input[placeholder='예: Android ES-DE']").fill(ROM_ONLY);
  await page.locator(".modal-actions .btn.primary", { hasText: "Add" }).click();
  await expect(page.locator(".ctab.active")).toContainText(ROM_ONLY, { timeout: 30000 });
  return true;
}

//: 이 파일이 만드는 ROM 폴더의 System들. Archive는 실행 전체에서 공유되므로
//  다른 spec이 넣은 항목(ps2 등)과 섞이지 않도록 여기서 걸러서 본다.
const OURS = ["msx1", "nes", "famicom"];

const archiveKeys = (page) => page.evaluate(async (ours) => {
  const r = await window.api.archiveRows({ limit: 500 });
  return r.data.rows
    .filter((x) => ours.includes(x.system))
    .map((x) => `${x.system}|${x.file}`)
    .sort();
}, OURS);

test.describe("ROM만 있는 Collection", () => {
  test("Metadata 없이 ROM 폴더만으로 만들어지고 열린다", async ({ page }) => {
    await openReal(page);
    const created = await openRomOnly(page);
    expect(created).toBe(true);   // 이 테스트가 실제로 만드는 쪽이어야 의미가 있다

    // 가로막는 안내가 없어야 한다 - ROM만 있는 것은 정상이다.
    await expect(page.locator(".modal-title")).toHaveCount(0);
  });

  test("ROM 폴더의 System이 모두 좌측 내비에 나온다", async ({ page }) => {
    await openReal(page);
    await openRomOnly(page);
    for (const system of ["MSX1", "NES", "FAMICOM"]) {
      await expect(page.locator(".nav-system", { hasText: system }))
        .toBeVisible({ timeout: 30000 });
    }
  });

  test("Storage 그룹이 System의 부모로 끼어들지 않는다", async ({ page }) => {
    await openReal(page);
    await openRomOnly(page);
    await expect(page.locator(".nav-group-head")).toHaveCount(0);
    // 특히 "ROM"이라는 이름의 그룹이 생기면 안 된다 - 예전에는 여기서 생겼다.
    await expect(page.locator(".nav-group-name", { hasText: "ROM" })).toHaveCount(0);
  });

  test("제목 자리에 파일명이 뜬 채로 목록이 보인다", async ({ page }) => {
    await openReal(page);
    await openRomOnly(page);
    await page.locator(".nav-system", { hasText: "MSX1" }).click();
    await expect(page.locator(".lrow", { hasText: "Aleste" }))
      .toBeVisible({ timeout: 30000 });
  });
});

test.describe("Archive 수집 범위 - 실제 결과", () => {
  test("System 하나만 골라 수집하면 그 System만 들어간다", async ({ page }) => {
    await openReal(page);
    await openRomOnly(page);

    await page.locator(".nav-system", { hasText: "MSX1" }).click();
    // 버튼이 대상을 미리 말한다 - 누르기 전에 확인할 수 있어야 한다.
    await expect(page.locator("#archive-ingest-btn")).toContainText("MSX1 전체");
    await page.locator("#archive-ingest-btn").click();
    await expect(page.locator("#toast")).toContainText("수집 완료", { timeout: 30000 });

    // **여기가 핵심이다.** Archive에 실제로 무엇이 들어갔는지 본다.
    // MSX1만 골랐으므로 nes/famicom은 아직 하나도 없어야 한다.
    expect(await archiveKeys(page)).toEqual(["msx1|Aleste.rom", "msx1|Nemesis.rom"]);
  });

  test("고른 게임만 수집하면 그 게임만 들어간다", async ({ page }) => {
    await openReal(page);
    await openRomOnly(page);

    await page.locator(".nav-system", { hasText: "NES" }).click();
    await expect(page.locator(".lrow").first()).toBeVisible({ timeout: 30000 });
    await page.locator(".lrow").first().click();
    await expect(page.locator("#archive-ingest-btn")).toContainText("선택한 1개");
    await page.locator("#archive-ingest-btn").click();
    await expect(page.locator("#toast")).toContainText("수집 완료", { timeout: 30000 });

    // 앞 테스트가 넣은 msx1 둘에 nes 하나만 더해져야 한다 - nes 전체가 아니다.
    const rows = await archiveKeys(page);
    expect(rows.filter((r) => r.startsWith("nes|"))).toHaveLength(1);
    expect(rows.filter((r) => r.startsWith("famicom|"))).toHaveLength(0);
  });

  test("아무것도 고르지 않으면 Collection 전체가 들어간다", async ({ page }) => {
    await openReal(page);
    await openRomOnly(page);

    await expect(page.locator("#archive-ingest-btn")).toContainText("Collection 전체");
    await page.locator("#archive-ingest-btn").click();
    await expect(page.locator("#toast")).toContainText("수집 완료", { timeout: 30000 });

    const rows = await archiveKeys(page);
    expect(rows).toHaveLength(6);   // msx1 2 + nes 3 + famicom 1
  });
});
