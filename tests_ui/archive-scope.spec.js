// "화면에서 고른 대상 == 실제 Archive에 들어간 대상" (P0).
//
// 예전에는 선택한 게임이 없으면 GUI가 `null`을 보냈고 백엔드가 그것을 "Collection
// 전체"로 해석했다. Navigation에서 MSX1을 고르고 수집을 누르면 화면에는 MSX1만
// 보이는데 Collection 전체가 Archive에 들어갔다.
//
// 여기서는 **화면이 실제로 무엇을 보냈는지**를 가로채서 확인한다. 토스트 문구만
// 보면 "전체 수집 완료"라고 적혀 있어도 그것이 맞는 말인지 알 수 없다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => {
  await openApp(page);
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

const ingestButton = (page) => page.locator("#archive-ingest-btn");

test("아무것도 고르지 않았으면 Collection 전체다", async ({ page }) => {
  await ingestButton(page).click();
  await expect.poll(() => page.__scopes.length).toBe(1);
  expect(page.__scopes[0]).toEqual({ kind: "all" });
});

test("Navigation에서 System을 고르면 그 System만 보낸다", async ({ page }) => {
  await page.locator(".nav-system", { hasText: "PS2" }).click();
  await ingestButton(page).click();
  await expect.poll(() => page.__scopes.length).toBe(1);
  expect(page.__scopes[0]).toEqual({ kind: "system", system: "ps2" });
});

test("게임을 고르면 그 게임만 보낸다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await ingestButton(page).click();
  await expect.poll(() => page.__scopes.length).toBe(1);
  expect(page.__scopes[0].kind).toBe("selected");
  expect(page.__scopes[0].romUids).toHaveLength(1);
});

test("게임 선택이 System 선택을 이긴다", async ({ page }) => {
  // 사용자가 마지막에 한 행동이 가장 구체적인 의도다.
  await page.locator(".nav-system", { hasText: "PS2" }).click();
  await page.locator(".lrow").first().click();
  await ingestButton(page).click();
  await expect.poll(() => page.__scopes.length).toBe(1);
  expect(page.__scopes[0].kind).toBe("selected");
});

test.describe("버튼이 대상을 미리 말해 준다", () => {
  test("기본은 Collection 전체", async ({ page }) => {
    await expect(ingestButton(page)).toContainText("Collection 전체");
  });

  test("System을 고르면 그 System을 가리킨다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await expect(ingestButton(page)).toContainText("PS2 전체");
  });

  test("게임을 고르면 그 개수를 가리킨다", async ({ page }) => {
    await page.locator(".lrow").first().click();
    await expect(ingestButton(page)).toContainText("선택한 1개");
  });

  test("버튼이 말한 것과 실제로 보낸 것이 같다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await expect(ingestButton(page)).toContainText("PS2 전체");
    await ingestButton(page).click();
    await expect.poll(() => page.__scopes.length).toBe(1);
    expect(page.__scopes[0].system).toBe("ps2");
  });

  test("대상이 바뀌어도 아이콘은 그대로다", async ({ page }) => {
    // 버그: 안에 span이 둘이라(아이콘 span이 먼저) querySelector("span")으로
    // 고르면 아이콘 span을 잡아 글자로 덮어썼다 - 아이콘이 사라지고 글자가
    // 두 번 나왔다. 이제는 .ingest-label로 정확히 짚는다.
    await page.locator(".lrow").first().click();
    await expect(ingestButton(page)).toContainText("선택한 1개");
    const icHtml = await ingestButton(page).locator(".ic").innerHTML();
    expect(icHtml).toContain("<svg");
    // 글자가 아이콘 span에도 새어 들어가지 않았다 - 라벨 span에만 있다.
    await expect(ingestButton(page).locator(".ingest-label")).toHaveText(/선택한 1개/);
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
  await ingestButton(page).click();
  await expect.poll(() => sawProgress).toBe(true);
});
