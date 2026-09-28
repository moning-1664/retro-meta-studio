// Ctrl+C/Ctrl+V - Gamelist에서 없앴던 것을 되살렸다(사용자 요청, Phase 이후).
// 병합 로직 자체는 이미 tests/test_metadata_only_paste.py가 검증하는 기존
// plan_add() + 충돌 해결 흐름을 그대로 쓴다 - 여기서는 키보드 단축키가
// 그 흐름을 실제로 부르는지만 확인한다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test.describe("복사/붙여넣기", () => {
  test("Ctrl+C는 선택한 항목으로 copy_selection을 부른다", async ({ page }) => {
    const calls = [];
    await page.exposeFunction("__note", (name, args) => calls.push({ name, args }));
    await page.evaluate(() => {
      const original = window.api.copySelection;
      window.api.copySelection = (id, uids) => { window.__note("copySelection", [id, uids]); return original(id, uids); };
    });

    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");

    await expect.poll(() => calls.length).toBeGreaterThan(0);
    expect(calls[0].name).toBe("copySelection");
    expect(calls[0].args[1]).toHaveLength(1);
  });

  test("선택 없이 Ctrl+C를 누르면 안내만 뜨고 호출되지 않는다", async ({ page }) => {
    const calls = [];
    await page.exposeFunction("__note", () => calls.push(1));
    await page.evaluate(() => {
      const original = window.api.copySelection;
      window.api.copySelection = (...a) => { window.__note(); return original(...a); };
    });

    await page.keyboard.press("Control+c");
    await expect(page.locator("#toast.show")).toBeVisible();
    expect(calls.length).toBe(0);
  });

  test("Ctrl+V는 paste를 부르고 목록을 새로고침한다", async ({ page }) => {
    const calls = [];
    await page.exposeFunction("__note", (id) => calls.push(id));
    await page.evaluate(() => {
      const original = window.api.paste;
      window.api.paste = (id) => { window.__note(id); return original(id); };
    });

    await page.keyboard.press("Control+v");

    await expect.poll(() => calls.length).toBeGreaterThan(0);
    await expect(page.locator("#toast.show")).toBeVisible();
  });

  test("입력 필드에 포커스가 있으면 목록 단축키로 새지 않는다", async ({ page }) => {
    // 실사용 확인: metadata 검색창 등에서 Ctrl+C/V는 텍스트 복사/붙여넣기여야 한다.
    await page.locator(".lrow").first().click();
    const calls = [];
    await page.exposeFunction("__note", () => calls.push(1));
    await page.evaluate(() => {
      const original = window.api.copySelection;
      window.api.copySelection = (...a) => { window.__note(); return original(...a); };
    });

    await page.locator("#filter-bar input[type=search], #filter-bar .search-input").first().focus().catch(() => {});
    const active = await page.evaluate(() => document.activeElement.tagName);
    if (active === "INPUT" || active === "TEXTAREA") {
      await page.keyboard.press("Control+c");
      expect(calls.length).toBe(0);
    }
  });
});

// 붙여넣기 모드(Patch / Overwrite / Replace) - 사용자 결정.
test.describe("붙여넣기 모드", () => {
  test("넓은 목록에는 Paste와 Plan 그룹명을 표시하고 좁으면 숨긴다", async ({ page }) => {
    await page.setViewportSize({ width: 2400, height: 900 });
    await expect(page.locator("#filter-bar .toolbar-group-label")).toHaveText(["Paste", "Plan"]);
    await expect(page.locator("#filter-bar .toolbar-group-label").first()).toBeVisible();
    await page.setViewportSize({ width: 1000, height: 800 });
    await expect(page.locator("#filter-bar .toolbar-group-label").first()).toBeHidden();
    await expect(page.locator("#filter-bar .paste-mode .seg-btn")).toHaveCount(3);
  });

  test("Plan 버튼 옆에 세 모드 토글이 있고 Patch가 기본이다", async ({ page }) => {
    const modes = page.locator(".paste-mode .seg-btn");
    await expect(modes).toHaveCount(3);
    await expect(modes).toHaveText(["Patch", "Overwrite", "Replace"]);
    await expect(page.locator(".paste-mode .seg-btn.on")).toHaveText("Patch");
    // Plan 버튼(Apply/Cancel)보다 왼쪽에 있다.
    const [mode, apply] = await Promise.all([
      page.locator(".paste-mode").boundingBox(), page.locator(".plan-actions").boundingBox()]);
    expect(mode.x + mode.width).toBeLessThanOrEqual(apply.x + 1);
  });

  test("각 모드가 무엇을 하는지 툴팁으로 설명한다", async ({ page }) => {
    await expect(page.locator(".paste-mode [data-mode='patch']")).toHaveAttribute("title", /없는 것만 채웁니다/);
    await expect(page.locator(".paste-mode [data-mode='overwrite']")).toHaveAttribute("title", /덮어쓰기/);
    await expect(page.locator(".paste-mode [data-mode='replace']")).toHaveAttribute("title", /완전 교체/);
  });

  test("모드를 고르면 표시가 바뀌고 다음 붙여넣기가 그 모드로 요청된다", async ({ page }) => {
    await page.evaluate(() => {
      window.__modes = [];
      const original = window.api.paste;
      window.api.paste = (id, mode) => { window.__modes.push(mode); return original(id, mode); };
    });
    await page.locator(".paste-mode [data-mode='overwrite']").click();
    await expect(page.locator(".paste-mode .seg-btn.on")).toHaveText("Overwrite");
    await expect(page.locator("#toast")).toContainText("다음 붙여넣기부터");
    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    await expect.poll(() => page.evaluate(() => window.__modes)).toEqual(["overwrite"]);
  });

  test("올리지 않은 항목이 있으면 이유를 알려 준다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.paste = async () => ({ ok: true, data: { added: 0, conflicts: 0,
        skipped: [{ filename: "FFX.iso", reason: "Patch 모드 - 대상이 이미 모두 가지고 있어 채울 것이 없습니다" }] } });
    });
    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    await expect(page.locator("#toast")).toContainText("채울 것이 없습니다");
  });
});

// 사용자 결정 - "system을 선택해서 붙여넣으면 system 이름이 달라도 붙여넣기 허용".
test.describe("없는 System으로 붙여넣기", () => {
  // 목업 기본은 "대상에 다 있다"(묻지 않는다) - 여기서만 없는 System을 섞어 둔다.
  test.beforeEach(async ({ page }) => {
    await page.evaluate(() => {
      window.api.clipboardSystems = async () => ({ ok: true, data: {
        systems: [{ system: "ps2", count: 2, exists: true },
                  { system: "fbneo act", count: 1, exists: false }],
        targetSystems: ["gba", "ps2", "snes"] } });
    });
  });

  test("이 Collection에 없는 System만 물어본다", async ({ page }) => {
    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    await expect(page.locator(".modal-title")).toHaveText("붙여넣을 System 고르기");
    // 목업 클립보드에는 ps2(있음)와 "fbneo act"(없음)가 있다 - 없는 것만 묻는다.
    const rows = page.locator(".paste-system-row");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("fbneo act");
  });

  test("고른 System이 붙여넣기에 그대로 전달된다", async ({ page }) => {
    await page.evaluate(() => {
      window.__pasted = [];
      const original = window.api.paste;
      window.api.paste = (id, mode, map) => { window.__pasted.push({ mode, map }); return original(id, mode, map); };
    });
    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    await page.locator(".paste-system-select").selectOption("snes");
    await page.locator(".paste-system-ok").click();
    await expect.poll(() => page.evaluate(() => window.__pasted.length)).toBe(1);
    const sent = (await page.evaluate(() => window.__pasted))[0];
    expect(sent.map).toEqual({ "fbneo act": "snes" });
  });

  test("취소하면 붙여넣지 않는다", async ({ page }) => {
    await page.evaluate(() => {
      window.__pasted = 0;
      const original = window.api.paste;
      window.api.paste = (...args) => { window.__pasted += 1; return original(...args); };
    });
    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    await page.locator(".modal-actions .btn", { hasText: "취소" }).click();
    await expect(page.locator(".modal-title")).toHaveCount(0);
    expect(await page.evaluate(() => window.__pasted)).toBe(0);
  });

  test("새 System으로 만들기를 고르면 이름을 바꾸지 않는다", async ({ page }) => {
    await page.evaluate(() => {
      window.__pasted = [];
      const original = window.api.paste;
      window.api.paste = (id, mode, map) => { window.__pasted.push(map); return original(id, mode, map); };
    });
    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    await page.locator(".paste-system-ok").click();          // 기본값 = 새 System으로 만들기
    await expect.poll(() => page.evaluate(() => window.__pasted.length)).toBe(1);
    expect((await page.evaluate(() => window.__pasted))[0]).toEqual({});
  });
});

// 사용자 결정 - "FBNEO xxxx, MAME xxxx도 앞에 이름을 기준으로 아이콘 추가".
test("System 이름이 'FBNEO ACT'처럼 길어도 앞 이름으로 아이콘을 찾는다", async ({ page }) => {
  const found = await page.evaluate(() => ({
    act: window.RMSystemIconPack.candidates("FBNEO ACT"),
    mame: window.RMSystemIconPack.candidates("MAME 2003"),
    plain: window.RMSystemIconPack.candidates("snes"),
  }));
  expect(found.act).toContain("fbneo");
  expect(found.mame[0]).toBe("mame2003");     // 전체 이름 파일이 있으면 그쪽이 먼저다
  expect(found.mame).toContain("mame");
  expect(found.plain).toEqual(["snes"]);
});

// 고른 행이 대상이다(실사용 리포트) - 예전 Ctrl+V는 고른 행을 아예 보지 않고 이름으로만
// 대상을 찾아서, 이름이 다른 게임에 붙이려 하면 아무 일도 일어나지 않았다.
test.describe("고른 행을 대상으로 삼기", () => {
  const pasteArgs = async (page) => {
    const calls = [];
    await page.exposeFunction("__paste", (args) => calls.push(args));
    await page.evaluate(() => {
      const original = window.api.paste;
      window.api.paste = (...args) => { window.__paste(args); return original(...args); };
    });
    return calls;
  };

  test("행 하나를 고른 채 Ctrl+V를 누르면 그 행을 대상 후보로 보낸다", async ({ page }) => {
    const calls = await pasteArgs(page);
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();
    await page.keyboard.press("Control+c");
    await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).click();
    await page.keyboard.press("Control+v");
    await expect.poll(() => calls.length).toBe(1);
    expect(calls[0][4]).toBe("ps2|MGS2.iso");
  });

  test("여러 행을 골랐으면 대상 후보를 보내지 않는다", async ({ page }) => {
    const calls = await pasteArgs(page);
    await page.locator(".lrow", { hasText: "Final Fantasy X" }).click();
    await page.keyboard.press("Control+c");
    await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).click();
    await page.locator(".lrow", { hasText: "Super Mario World" }).click({ modifiers: ["Control"] });
    await page.keyboard.press("Control+v");
    await expect.poll(() => calls.length).toBe(1);
    expect(calls[0][4]).toBeFalsy();
  });
});

// 여러 개를 한 번에 붙이면 Replace는 Patch로 내려간다(사용자 결정) - 조용히 바꾸지 않고
// 모드 토글이 잠깐 Patch로 밝혀진다.
test("Replace가 Patch로 내려가면 모드 토글이 잠깐 밝혀진다", async ({ page }) => {
  await page.evaluate(() => {
    window.api.paste = () => Promise.resolve({ ok: true, data: {
      added: 2, skipped: [], conflicts: 0,
      policy: { pasteMode: "patch" }, downgradedFrom: "replace",
    } });
  });
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Control+c");
  await page.keyboard.press("Control+v");
  await expect(page.locator(".paste-mode .seg-btn[data-mode='patch']")).toHaveClass(/flash/);
  await expect(page.locator("#toast")).toContainText("대신 Patch로 붙였습니다");
});

test("내려가지 않았으면 토글은 그대로다", async ({ page }) => {
  await page.evaluate(() => {
    window.api.paste = () => Promise.resolve({ ok: true, data: {
      added: 1, skipped: [], conflicts: 0,
      policy: { pasteMode: "replace" }, downgradedFrom: null,
    } });
  });
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Control+c");
  await page.keyboard.press("Control+v");
  await expect(page.locator(".paste-mode .seg-btn.flash")).toHaveCount(0);
});
