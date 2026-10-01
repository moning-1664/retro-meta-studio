// UI 상태 저장/복원의 두 가지 경쟁 상태 (Phase 7.20 QA 재검토).
//
// 리뷰에서 코드로 확인된 실제 버그 둘이다.
//
// 1. Collection을 A -> B -> A로 빠르게 오가면, B의 `get_ui_state` 응답이 늦게
//    도착해 이미 다시 열어 둔 A의 컬럼 폭/정렬을 덮어쓸 수 있었다.
// 2. 컬럼 폭을 바꾼 직후 창을 닫으면, 300ms debounce 타이머가 돌기 전에
//    `save_ui_state`가 나가지 않아 방금 바꾼 값이 사라졌다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

/** openApp()이 이미 Master Library(c1)를 열어 둔다 - Android ES-DE(c2)만 마저 연다. */
async function openBoth(page) {
  await page.locator(".ctab-add").click();
  await page.locator(".add-collection-history summary").click();
  await page.locator(".picker-row", { hasText: "Android ES-DE" }).click();
  await expect(page.locator(".ctab", { hasText: "Android ES-DE" })).toBeVisible();
}

test.describe("Collection 전환 race", () => {
  test("느리게 도착한 이전 Collection의 상태가 지금 보는 Collection을 덮지 않는다", async ({ page }) => {
    await openBoth(page);   // c1, c2 순서로 연다 - 지금 활성은 c2

    // c1의 get_ui_state만 인위적으로 늦춘다. c1은 폭 999로 저장돼 있다고 가정한다.
    await page.evaluate(() => {
      const original = window.api.getUiState;
      window.api.getUiState = (id) => {
        if (id === "c1") {
          return new Promise((resolve) => {
            setTimeout(() => resolve({ ok: true, data: { colWidths: { title: 999 } } }), 400);
          });
        }
        return original(id);
      };
    });

    // c1으로 갔다가(느린 응답이 시작됨) 바로 c2로 돌아온다.
    await page.locator(".ctab", { hasText: "Master Library" }).click();
    await page.locator(".ctab", { hasText: "Android ES-DE" }).click();

    // c1의 응답이 도착할 시간을 준다. 지금 활성은 c2이므로 999가 적용되면 안 된다.
    await page.waitForTimeout(600);

    const width = await page.evaluate(() => window.__debugColWidth
      ? window.__debugColWidth() : null);
    // 디버그 훅이 없다면 화면의 실제 컬럼 폭으로 확인한다.
    const headWidth = await page.locator("#list-head .lh-title").evaluate(
      (el) => el.getBoundingClientRect().width);
    expect(Math.round(headWidth)).not.toBe(999);
  });

  test("느린 Archive 응답 뒤에 Collection으로 돌아와도 Archive가 화면을 덮지 않는다", async ({ page }) => {
    await page.evaluate(() => {
      const original = window.api.archiveConfig;
      window.api.archiveConfig = () => new Promise((resolve) => {
        setTimeout(() => original().then(resolve), 500);
      });
    });
    await page.locator(".ctab.archive").click();
    await page.locator(".ctab", { hasText: "Master Library" }).click();
    await page.waitForTimeout(700);
    await expect(page.locator(".ctab", { hasText: "Master Library" })).toHaveClass(/active/);
    await expect(page.locator(".lrow").first()).toContainText("Final Fantasy X");
    await expect(page.locator("#toast")).not.toContainText("Collection을 찾을 수 없습니다");
  });
});

test.describe("종료 직전 저장 flush", () => {
  test("컬럼 폭을 바꾼 직후 닫아도 저장 요청이 나간다", async ({ page }) => {
    // openApp()이 이미 Master Library를 열어 둔다.
    //
    // **500ms처럼 넉넉한 timeout으로 "결국 저장됐는가"만 보면 이 버그를 못 잡는다** -
    // debounce가 300ms 뒤에 어차피 도니까 넉넉히 기다리면 고치기 전 코드도 통과해
    // 버린다. 대신 **순서**를 본다: 저장이 windowControl(실제 창을 닫는 호출)보다
    // 먼저 나갔는가. 순서는 브라우저 컨텍스트 안에서만 기록한다 - Node로 나갔다
    // 들어오는 IPC 왕복을 거치면 그 자체의 지연 때문에 순서가 흔들릴 수 있다.
    await page.evaluate(() => {
      window.__events = [];
      window.api.saveUiState = (id, state) => {
        window.__events.push("save:" + JSON.stringify(state.colWidths));
        return Promise.resolve({ ok: true, data: state });
      };
      // 창을 실제로 닫으면 테스트가 끝나 버리므로 windowControl을 가로채 관찰만 한다.
      window.api.windowControl = () => {
        window.__events.push("windowControl");
        return Promise.resolve({ ok: true, data: true });
      };
    });

    const handle = page.locator(".lh-title .col-resize");
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2, { steps: 4 });
    await page.mouse.up();

    // debounce 타이머(300ms)가 돌기 전에 즉시 닫기를 누른다.
    await page.locator(".win-btn.close").click();

    const events = await page.evaluate(() => window.__events);
    const saveIndex = events.findIndex((e) => e.startsWith("save:"));
    const closeIndex = events.indexOf("windowControl");
    expect(closeIndex).toBeGreaterThanOrEqual(0);
    expect(saveIndex).toBeGreaterThanOrEqual(0);
    // 저장이 창 닫기 호출보다 먼저 나가야 한다 - 나중에 나가면 이미 창이 닫힌 뒤라
    // 의미가 없다.
    expect(saveIndex).toBeLessThan(closeIndex);
  });
});

test.describe("Gamelist 선택 -> Detail race", () => {
  test("느리게 도착한 이전 선택의 상세가 지금 고른 게임을 덮지 않는다", async ({ page }) => {
    // **이건 화면만 틀리는 버그가 아니다.** 덮어쓴 S.detailState에는 이전 게임의
    // romUid가 그대로 남아, 사용자가 지금 고른 게임을 고친다고 믿고 누른 저장이
    // 엉뚱한 게임에 들어간다. 그래서 저장 대상까지 함께 본다.
    await page.evaluate(() => {
      const original = window.api.getRow;
      window.api.getRow = (cid, uid) => {
        const answer = original(cid, uid);
        // Final Fantasy X(romUid 1)의 응답만 늦춘다.
        if (uid !== 1) return answer;
        return new Promise((resolve) => { setTimeout(() => answer.then(resolve), 400); });
      };
    });

    // FFX를 고르고(느린 요청 시작) 곧바로 MGS2로 옮긴다.
    await page.locator(".lrow").first().locator(".lc-file").click();
    await page.locator(".lrow").nth(1).locator(".lc-file").click();
    await expect(page.locator(".title-input")).toHaveValue("Metal Gear Solid 2");

    // 늦은 FFX 응답이 도착할 시간을 준다. 그래도 화면은 MGS2여야 한다.
    await page.waitForTimeout(600);
    await expect(page.locator(".title-input")).toHaveValue("Metal Gear Solid 2");

    // 저장 대상도 MGS2(romUid 2)다 - 화면만 맞고 속이 FFX면 저장이 엉뚱한 곳에 들어간다.
    await page.evaluate(() => {
      window.__savedUid = null;
      const original = window.api.saveFields;
      window.api.saveFields = (cid, uid, fields) => {
        window.__savedUid = uid;
        return original(cid, uid, fields);
      };
    });
    await page.locator(".detail-footer .btn", { hasText: "저장" }).click();
    expect(await page.evaluate(() => window.__savedUid)).toBe(2);
  });
});

test.describe("Collection 경계", () => {
  test("Collection을 바꾸면 이전 선택이 넘어오지 않는다", async ({ page }) => {
    await openBoth(page);   // 지금 활성은 c2(Android ES-DE)

    // romUid는 Collection마다 새로 매겨지므로 두 Collection에서 값이 흔히 겹친다.
    // 선택이 남아 있으면 화면에 보이지도 않는 게임이 Archive 수집 대상이 된다.
    await page.locator(".lrow").first().click();
    await expect(page.locator("#status-bar")).toContainText("Selected 1");

    await page.locator(".ctab", { hasText: "Master Library" }).click();
    await expect(page.locator("#status-bar")).toContainText("Selected 1");
    await expect(page.locator(".detail-filename")).toContainText("FFX.iso");
  });
});
