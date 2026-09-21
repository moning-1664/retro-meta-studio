// "화면에서 고른 대상 == 실제 Archive에 들어간 대상" (P0).
//
// 예전에는 선택한 게임이 없으면 GUI가 `null`을 보냈고 백엔드가 그것을 "Collection
// 전체"로 해석했다. Navigation에서 MSX1을 고르고 수집을 누르면 화면에는 MSX1만
// 보이는데 Collection 전체가 Archive에 들어갔다.
//
// 여기서는 **화면이 실제로 무엇을 보냈는지**를 가로채서 확인한다. 토스트 문구만
// 보면 "전체 수집 완료"라고 적혀 있어도 그것이 맞는 말인지 알 수 없다.
//
// [§4 개정] "Archive로" 버튼은 Detail 패널에서 HERO로 옮겨갔다(메타데이터 보내기
// 아이콘) - 누르면 우클릭 스타일 플로팅 메뉴가 뜨고, 거기서 "Archive"를 고른다.
// 대상 범위는 예전처럼 버튼 자체의 title이 아니라 그 메뉴의 부제(.ctx-sub)와
// Archive 항목의 title이 말한다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => {
  await openApp(page);
  // Archive는 저장할 디렉토리를 정한 뒤에만 수집한다(사용자 결정) - 여기서는 그 뒤의 범위 규칙을
  // 보는 것이므로 이미 정해 둔 상태로 시작한다. 정하기 전의 거절은 archive-versions.spec.js가 본다.
  await page.evaluate(() => window.api.saveArchiveConfig({ archiveDir: "D:\Archives" }));
  await page.exposeFunction("__ingest", (scope) => { page.__scopes.push(scope); });
  page.__scopes = [];
  await page.evaluate(() => {
    const original = window.api.startArchiveIngest;
    window.api.startArchiveIngest = (id, scope) => {
      window.__ingest(scope);
      return original(id, scope);
    };
  });
});

const sendIcon = (page) => page.locator("#collection-header .cheader-right .icon-btn[title*='메타데이터 보내기']");
const openSendMenu = async (page) => { await sendIcon(page).click(); };
const archiveMenuItem = (page) => page.locator(".ctx-menu .ctx-item", { hasText: "Archive" });
const ingestViaMenu = async (page) => { await openSendMenu(page); await archiveMenuItem(page).click(); };

test("아무것도 고르지 않았으면 Collection 전체다", async ({ page }) => {
  await ingestViaMenu(page);
  await expect.poll(() => page.__scopes.length).toBe(1);
  expect(page.__scopes[0]).toEqual({ kind: "all" });
});

test("Navigation에서 System을 고르면 그 System만 보낸다", async ({ page }) => {
  await page.locator(".nav-system", { hasText: "PS2" }).click();
  await ingestViaMenu(page);
  await expect.poll(() => page.__scopes.length).toBe(1);
  expect(page.__scopes[0]).toEqual({ kind: "system", system: "ps2" });
});

test("게임을 고르면 그 게임만 보낸다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await ingestViaMenu(page);
  await expect.poll(() => page.__scopes.length).toBe(1);
  expect(page.__scopes[0].kind).toBe("selected");
  expect(page.__scopes[0].romUids).toHaveLength(1);
});

test("게임 선택이 System 선택을 이긴다", async ({ page }) => {
  // 사용자가 마지막에 한 행동이 가장 구체적인 의도다.
  await page.locator(".nav-system", { hasText: "PS2" }).click();
  await page.locator(".lrow").first().click();
  await ingestViaMenu(page);
  await expect.poll(() => page.__scopes.length).toBe(1);
  expect(page.__scopes[0].kind).toBe("selected");
});

// 아이콘 자체는 어떤 상황에서도 그대로다(글자도 폭도 없다) - **대상은 메뉴를 열어야
// 보인다.** 메뉴의 부제와 Archive 항목의 title이 그 역할을 한다.
test.describe("메뉴가 대상을 말해 준다", () => {
  test("기본은 Collection 전체", async ({ page }) => {
    await openSendMenu(page);
    await expect(page.locator(".ctx-sub")).toContainText("Collection 전체");
  });

  test("System을 고르면 그 System을 가리킨다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await openSendMenu(page);
    await expect(page.locator(".ctx-sub")).toContainText("PS2 전체");
  });

  test("게임을 고르면 그 개수를 가리킨다", async ({ page }) => {
    await page.locator(".lrow").first().click();
    await openSendMenu(page);
    await expect(page.locator(".ctx-sub")).toContainText("선택한 1개");
  });

  test("메뉴가 말한 것과 실제로 보낸 것이 같다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await openSendMenu(page);
    await expect(page.locator(".ctx-sub")).toContainText("PS2 전체");
    await archiveMenuItem(page).click();
    await expect.poll(() => page.__scopes.length).toBe(1);
    expect(page.__scopes[0].system).toBe("ps2");
  });

  test("선택이 바뀌어도 아이콘 자체(모습·위치)는 그대로다", async ({ page }) => {
    // 라벨에 범위 이름을 넣으면 고를 때마다 버튼 폭이 출렁인다(사용자 피드백) -
    // 지금은 아이콘 하나뿐이라 그 문제 자체가 없다. 그래도 선택에 따라 다시
    // 그려지며 흔들리지 않는지는 확인해 둔다.
    const before = await sendIcon(page).boundingBox();
    await page.locator(".lrow").first().click();
    expect((await sendIcon(page).boundingBox()).width).toBe(before.width);
    const icHtml = await sendIcon(page).locator(".icon").innerHTML();
    expect(icHtml).toContain("<path");
  });
});

test("수집 중에는 진행 상황이 보인다", async ({ page }) => {
  // 게임 수만큼 DB 쓰기가 일어난다. 창이 멈춘 것처럼 보이면 안 된다.
  let sawProgress = false;
  await page.exposeFunction("__sawProgress", () => { sawProgress = true; });
  await page.evaluate(() => {
    const original = window.api.jobProgress;
    window.api.jobProgress = (jobId) => { window.__sawProgress(); return original(jobId); };
  });
  await ingestViaMenu(page);
  await expect.poll(() => sawProgress).toBe(true);
});
