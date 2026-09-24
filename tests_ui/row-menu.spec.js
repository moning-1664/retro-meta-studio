// 게임 행 우클릭 메뉴.
//
// 예전엔 우클릭하자마자 삭제 확인(모달)이 떴다. 삭제는 여러 동작 중 하나라 오클릭
// 한 번이 곧바로 삭제로 이어졌다(사용자 요청) - 이제는 메뉴를 먼저 띄운다.
// Delete 상시 버튼은 여전히 없다(오클릭 위험, PENDING_DECISIONS.md).
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const rightClick = (page, text) => page.locator(".lrow", { hasText: text }).click({ button: "right" });
// 라벨이 정확히 같은 항목 - "삭제"가 "ROM 삭제"/"메타데이터 삭제"까지 잡으면 안 된다.
const menuItem = (page, label) => page.locator(".ctx-menu .ctx-item").filter({
  has: page.locator(".ctx-label", { hasText: new RegExp(`^${label}$`) }),
});

test("Delete 상시 버튼은 없다", async ({ page }) => {
  await expect(page.locator("#filter-bar", { hasText: "Delete" })).toHaveCount(0);
});

test("우클릭하면 삭제 확인이 아니라 메뉴가 뜬다", async ({ page }) => {
  await rightClick(page, "Final Fantasy X");
  await expect(page.locator(".ctx-menu")).toBeVisible();
  await expect(page.locator(".modal-title")).toHaveCount(0);
  await expect(page.locator(".ctx-title")).toHaveText("Final Fantasy X");
  await expect(menuItem(page, "Game 삭제")).toBeVisible();
  await expect(menuItem(page, "파일명 복사")).toBeVisible();
});

test("선택하지 않은 행을 우클릭하면 그 행 하나만 선택된다", async ({ page }) => {
  await rightClick(page, "Final Fantasy X");
  await expect(page.locator("#status-bar")).toContainText("Selected 1");
});

test("메뉴의 삭제를 고르면 삭제를 요청하고 메뉴를 닫는다", async ({ page }) => {
  const deleted = [];
  await page.exposeFunction("__deleted", (uids) => deleted.push(uids));
  await page.evaluate(() => {
    const original = window.api.planDelete;
    window.api.planDelete = (id, romUids) => { window.__deleted(romUids); return original(id, romUids); };
  });

  await rightClick(page, "Final Fantasy X");
  await menuItem(page, "Game 삭제").click();

  await expect(page.locator(".ctx-menu")).toHaveCount(0);
  await expect.poll(() => deleted.length).toBeGreaterThan(0);
  expect(deleted[0]).toHaveLength(1);
});

// 사용자 결정 - "삭제 / ROM 삭제 / 메타데이터 삭제"를 따로, 무엇이 지워지는지 알 수 있게.
test.describe("부분 삭제", () => {
  async function spy(page) {
    await page.evaluate(() => {
      window.__parts = [];
      const original = window.api.planDelete;
      window.api.planDelete = (id, uids, parts) => { window.__parts.push(parts); return original(id, uids, parts); };
    });
  }

  test("삭제 메뉴가 세 가지로 갈리고 무엇이 지워지는지 툴팁이 말한다", async ({ page }) => {
    await rightClick(page, "Final Fantasy X");
    await expect(menuItem(page, "Game 삭제")).toHaveAttribute("title", /ROM \+ 메타데이터 \+ 미디어/);
    await expect(menuItem(page, "ROM 삭제")).toHaveAttribute("title", /ROM 파일만/);
    await expect(menuItem(page, "메타데이터 삭제")).toHaveAttribute("title", /ROM은 남습니다/);
  });

  test("각 항목이 서로 다른 범위로 삭제를 요청한다", async ({ page }) => {
    await spy(page);
    await rightClick(page, "Final Fantasy X");
    await menuItem(page, "Game 삭제").click();
    await rightClick(page, "Final Fantasy X");
    await menuItem(page, "ROM 삭제").click();
    await rightClick(page, "Final Fantasy X");
    await menuItem(page, "메타데이터 삭제").click();
    await expect.poll(() => page.evaluate(() => window.__parts.length)).toBe(3);
    expect(await page.evaluate(() => window.__parts)).toEqual([
      ["rom", "metadata", "media", "video"], ["rom"], ["metadata", "media", "video"]]);
  });

  test("Status 아이콘을 우클릭하면 그 칸만 지우는 메뉴가 뜬다", async ({ page }) => {
    await spy(page);
    const ffx = page.locator(".lrow", { hasText: "Final Fantasy X" });
    await ffx.locator(".status-icon[data-status='mediaLevel']").click({ button: "right" });
    await expect(page.locator(".ctx-menu .ctx-item")).toHaveCount(1);       // 행 메뉴가 같이 뜨지 않는다
    await page.locator(".ctx-menu .ctx-item", { hasText: "미디어 삭제" }).click();
    await expect.poll(() => page.evaluate(() => window.__parts.length)).toBe(1);
    expect(await page.evaluate(() => window.__parts)).toEqual([["media"]]);
  });

  test("각 Status 아이콘이 자기 부분만 가리킨다", async ({ page }) => {
    await spy(page);
    const expected = { rom: "rom", metaLevel: "metadata", mediaLevel: "media", videoLevel: "video" };
    for (const [status, part] of Object.entries(expected)) {
      await page.locator(".lrow", { hasText: "Final Fantasy X" })
        .locator(`.status-icon[data-status='${status}']`).click({ button: "right" });
      await page.locator(".ctx-menu .ctx-item").click();
      await expect.poll(() => page.evaluate(() => window.__parts.length)).toBeGreaterThan(0);
      const last = await page.evaluate(() => window.__parts[window.__parts.length - 1]);
      expect(last).toEqual([part]);
    }
  });

  test("없는 칸(회색)의 삭제는 흐리게 막혀 있다", async ({ page }) => {
    await page.locator(".nav-system", { hasText: "SNES" }).click();
    await page.locator(".lrow", { hasText: "Super Mario World" })
      .locator(".status-icon[data-status='videoLevel']").click({ button: "right" });
    await expect(page.locator(".ctx-menu .ctx-item")).toBeDisabled();
  });
});

test("이미 여러 개를 선택한 상태로 그중 하나를 우클릭하면 선택 전체가 대상이다", async ({ page }) => {
  await page.locator(".lrow").nth(0).click();
  await page.locator(".lrow").nth(1).click({ modifiers: ["Control"] });
  await expect(page.locator("#status-bar")).toContainText("Selected 2");

  await page.locator(".lrow").nth(0).click({ button: "right" });
  await expect(page.locator(".ctx-title")).toContainText("2개 선택됨");
  await expect(menuItem(page, "파일명 2개 복사")).toBeVisible();
  // 선택이 그대로 유지된다 - 우클릭이 선택을 1개로 되돌리지 않는다.
  await expect(page.locator("#status-bar")).toContainText("Selected 2");
});

test("Esc와 바깥 클릭으로 닫힌다", async ({ page }) => {
  await rightClick(page, "Final Fantasy X");
  await page.keyboard.press("Escape");
  await expect(page.locator(".ctx-menu")).toHaveCount(0);

  await rightClick(page, "Final Fantasy X");
  await page.locator("#collection-header").click({ position: { x: 400, y: 20 } });
  await expect(page.locator(".ctx-menu")).toHaveCount(0);
});

test("메뉴의 즐겨찾기로 별표를 켜고 끈다", async ({ page }) => {
  const star = page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).locator(".fav-btn");
  await expect(star).toHaveText("☆");
  await rightClick(page, "Metal Gear Solid 2");
  await menuItem(page, "즐겨찾기에 추가").click();
  await expect(star).toHaveText("★");
});

// 게임 한 개 단위 "폴더 열기" - 실사용 피드백 §5. System 우클릭의 "폴더 열기"와
// 다른 점은 폴더가 아니라 **그 파일을 고른 채로** 연다는 것이다. mock 3행:
// FFX(전부 있음) / MGS2(메타데이터만 있음) / SMW(둘 다 없음, ROM만 있음).
test.describe("게임 한 개 단위 폴더 열기", () => {
  test("여러 개를 고른 채로는 보이지 않는다", async ({ page }) => {
    await page.locator(".lrow").nth(0).click();
    await page.locator(".lrow").nth(1).click({ modifiers: ["Control"] });
    await page.locator(".lrow").nth(0).click({ button: "right" });
    await expect(menuItem(page, "ROM 파일")).toHaveCount(0);
  });

  test("전부 있는 게임은 셋 다 눌린다", async ({ page }) => {
    const opened = [];
    await page.exposeFunction("__opened", (kind) => opened.push(kind));
    await page.evaluate(() => {
      const original = window.api.openRowFolder;
      window.api.openRowFolder = (id, uid, kind) => { window.__opened(kind); return original(id, uid, kind); };
    });
    await rightClick(page, "Final Fantasy X");
    for (const label of ["ROM 파일", "Metadata 파일", "Media 파일"]) {
      await expect(menuItem(page, label)).toBeEnabled();
    }
    await menuItem(page, "ROM 파일").click();
    await expect.poll(() => opened).toEqual(["rom"]);
  });

  test("없는 종류는 회색(비활성)이고 이유를 말한다", async ({ page }) => {
    // SMW는 메타데이터도 미디어도 없다.
    await rightClick(page, "Super Mario World");
    await expect(menuItem(page, "ROM 파일")).toBeEnabled();
    await expect(menuItem(page, "Metadata 파일")).toBeDisabled();
    await expect(menuItem(page, "Metadata 파일")).toHaveAttribute("title", "Metadata가 없습니다.");
    await expect(menuItem(page, "Media 파일")).toBeDisabled();
  });

  test("Archive 탭에는 이 메뉴가 없다(파일 배치 자체가 다르다)", async ({ page }) => {
    await page.locator(".ctab.archive").click();
    // Archive에 항목이 있으면 우클릭해 본다 - 없으면 이 검사는 자연히 넘어간다.
    const row = page.locator(".lrow").first();
    if (await row.count()) {
      await row.click({ button: "right" });
      await expect(menuItem(page, "ROM 파일")).toHaveCount(0);
    }
  });
});

// 실사용 버그 - "Replace로 다른 이름의 게임에 덮어썼는데 결과가 똑같다". 원인은 평범한
// Ctrl+V가 복사한 항목 자신의 자리로만 돌아가는 것이었다 - 파일명이 다른 대상에는 아예
// 닿지 않았다. "이 항목으로 붙여넣기 - 다른 파일명 지정"로 대상을 직접 지목한다.
test.describe("이 항목으로 붙여넣기 - 다른 파일명 지정", () => {
  test("복사한 게 없으면 눌러도 되지만 비활성은 아니다 - 결과가 API에서 걸러진다", async ({ page }) => {
    await rightClick(page, "Final Fantasy X");
    await expect(menuItem(page, "이 항목으로 붙여넣기 - 다른 파일명 지정")).toBeVisible();
  });

  test("정확히 하나를 복사했으면 target_map으로 이 행을 지목해서 붙인다", async ({ page }) => {
    const calls = [];
    await page.exposeFunction("__note", (args) => calls.push(args));
    await page.evaluate(() => {
      const original = window.api.paste;
      window.api.paste = (...args) => { window.__note(args); return original(...args); };
    });
    await rightClick(page, "Metal Gear Solid 2");
    await page.keyboard.press("Control+c");
    await rightClick(page, "Final Fantasy X");
    await menuItem(page, "이 항목으로 붙여넣기 - 다른 파일명 지정").click();

    await expect.poll(() => calls.length).toBe(1);
    const [, , , targetMap] = calls[0];
    expect(targetMap).toEqual({ "ps2|MGS2.iso": "ps2|FFX.iso" });
  });

  test("여러 개를 복사했으면 거절하고 새로 붙이지 않는다", async ({ page }) => {
    await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).click();
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).click({ modifiers: ["Control"] });
    await page.keyboard.press("Control+c");
    // 복사 뒤 다시 하나만 눌러 선택을 좁힌다 - "이 항목으로 붙여넣기 - 다른 파일명 지정"는 지금 고른
    // 행이 하나일 때만 켜지고(대상을 하나 지목하는 기능이다), 거절은 그 하나에
    // 클립보드가 여럿 들어있을 때 일어난다.
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();
    await rightClick(page, "Final Fantasy X");

    const calls = [];
    await page.exposeFunction("__pasted", (args) => calls.push(args));
    await page.evaluate(() => {
      const original = window.api.paste;
      window.api.paste = (...args) => { window.__pasted(args); return original(...args); };
    });
    await menuItem(page, "이 항목으로 붙여넣기 - 다른 파일명 지정").click();
    await expect(page.locator("#toast")).toContainText("하나만 복사했을 때만");
    expect(calls.length).toBe(0);
  });

  test("여러 행을 골랐으면 비활성이다(하나를 지목하는 기능이다)", async ({ page }) => {
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();
    await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).click({ modifiers: ["Control"] });
    // 이미 고른 행 중 하나를 우클릭해야 여러 개 선택이 유지된다(탐색기와 같다) -
    // 안 고른 행을 우클릭하면 그 한 행으로 선택이 다시 좁혀진다.
    await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).click({ button: "right" });
    await expect(page.locator("#status-bar")).toContainText("Selected 2");
    await expect(menuItem(page, "이 항목으로 붙여넣기 - 다른 파일명 지정")).toBeDisabled();
  });
});
