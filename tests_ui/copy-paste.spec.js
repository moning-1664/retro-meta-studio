// Ctrl+C/Ctrl+V - Gamelist에서 없앴던 것을 되살렸다(사용자 요청, Phase 이후).
// 병합 로직 자체는 이미 tests/test_metadata_only_paste.py가 검증하는 기존
// plan_add() + 충돌 해결 흐름을 그대로 쓴다 - 여기서는 키보드 단축키가
// 그 흐름을 실제로 부르는지만 확인한다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("열린 설정창 뒤의 목록에 붙여넣기·삭제 단축키가 전달되지 않는다", async ({ page }) => {
  await page.locator(".lrow").first().click();
  await page.evaluate(() => {
    window.__backgroundWrites = [];
    window.api.paste = async () => { window.__backgroundWrites.push("paste"); return { ok: true, data: {} }; };
    window.api.deleteImmediate = async () => { window.__backgroundWrites.push("delete"); return { ok: true, data: {} }; };
  });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Settings", exact: true })).toBeVisible();
  await page.keyboard.press("Control+v");
  await page.keyboard.press("Delete");
  expect(await page.evaluate(() => window.__backgroundWrites)).toEqual([]);
  await expect(page.getByRole("dialog", { name: "Settings", exact: true })).toBeVisible();
});

test("Ctrl+F는 목록 검색 입력을 선택한다", async ({ page }) => {
  await page.keyboard.press("Control+f");
  await expect(page.locator(".search-input")).toBeFocused();
});

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

// 명령 자체가 방식을 정하므로 별도 모드 토글을 두지 않는다.
test.describe("붙여넣기 명령", () => {
  test("Plan 대기 버튼과 Paste 모드 토글은 보이지 않는다", async ({ page }) => {
    await page.setViewportSize({ width: 2400, height: 900 });
    await expect(page.locator("#filter-bar .toolbar-group-label")).toHaveCount(0);
    await expect(page.locator("#filter-bar button").filter({hasText: /^Apply$|^Cancel$/})).toHaveCount(0);
    await expect(page.locator("#filter-bar .paste-mode")).toHaveCount(0);
  });

  test("복사 전에는 붙여넣기가 숨겨지고 옵션은 하위 메뉴에 나온다", async ({ page }) => {
    await page.locator(".lrow").first().click({ button: "right" });
    const labels = page.locator(".ctx-menu .ctx-label");
    await expect(labels.filter({ hasText: /^붙여넣기$|^채우기$|^교체하기$/ })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Control+c");
    await page.locator(".lrow").first().click({ button: "right" });
    await page.locator(".ctx-submenu-trigger").first().click();
    await expect(page.locator(".ctx-menu .ctx-label").filter({ hasText: /^붙여넣기$|^채우기$|^교체하기$/ })).toHaveCount(3);
  });

  test("채우기는 patch를 보내고 기본 붙여넣기는 overwrite를 보낸다", async ({ page }) => {
    await page.evaluate(() => {
      window.__modes = [];
      const original = window.api.paste;
      window.api.paste = (id, mode) => { window.__modes.push(mode); return original(id, mode); };
    });
    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    await page.locator(".lrow").first().click({ button: "right" });
    await page.locator(".ctx-submenu-trigger").first().click();
    await page.locator(".ctx-menu .ctx-label", { hasText: /^채우기$/ }).click();
    await expect.poll(() => page.evaluate(() => window.__modes)).toEqual(["overwrite", "patch"]);
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

test("같은 파일명 충돌은 기존/대상을 보고 결정하며 확장해도 버튼이 보인다", async ({ page }) => {
  await page.evaluate(() => { window.__RMS_MOCK_IMMEDIATE_PASTE = true; });
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Control+c");
  await page.keyboard.press("Control+v");
  const modal = page.locator(".paste-conflict-card");
  await expect(modal).toBeVisible();
  await expect(modal.locator(".paste-conflict-side-label")).toHaveText(["기존", "대상"]);
  await modal.locator(".paste-conflict-expand").first().click();
  await expect(modal.locator(".paste-conflict-expanded.open")).toHaveCount(1);
  await expect(modal.locator(".modal-actions .btn", { hasText: "기존 게임 덮어쓰기" })).toBeVisible();
  await modal.locator(".modal-actions .btn", { hasText: "기존 게임 덮어쓰기" }).click();
  await expect.poll(() => page.evaluate(() => window.__RMS_MOCK_PASTE_DECISIONS?.decisions))
    .toEqual({ "ps2|FFX.iso": "overwrite" });
});


test("Ctrl+X는 잘라내기만 예약하고 붙여넣기 전에는 파일 작업을 요청하지 않는다", async ({page}) => {
  await page.evaluate(() => {
    window.__cutCalls = [];
    window.api.cutSelection = async (id, uids) => {window.__cutCalls.push([id, uids]); return {ok: true, data: {count: uids.length, cut: true}};};
    window.api.pasteExecute = async () => {throw new Error("cut deleted source too early");};
  });
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Control+x");
  await expect.poll(()=>page.evaluate(()=>window.__cutCalls.length)).toBe(1);
  await expect(page.locator("#toast")).toContainText("잘라냈습니다");
  await expect(page.locator(".lrow")).not.toHaveCount(0);
});

test("F2 이름 변경은 확장자를 남기고 확인 후 독립 작업으로 실행한다", async ({page}) => {
  await page.locator(".lrow").first().click();
  await page.keyboard.press("F2");
  await expect(page.locator(".modal-title")).toHaveText("이름 변경");
  await page.locator(".modal-body input").fill("Renamed.iso");
  await page.locator(".modal-actions .btn.primary").click();
  await expect(page.locator("#toast")).toContainText("이름을 변경했습니다");
  await expect(page.locator(".lrow").filter({hasText: "Renamed.iso"})).toBeVisible();
});

for (const withRom of [false, true]) {
  test(`충돌 ROM 비교 정보는 실제 교체에만 표시된다 (${withRom})`, async ({ page }) => {
    await page.evaluate((enabled) => {
      window.__RMS_MOCK_IMMEDIATE_PASTE = true;
      const original = window.api.paste;
      window.api.paste = async (...args) => {
        const result = await original(...args);
        if (enabled) for (const collision of result.data.collisions || []) {
          collision.romComparison = {
            existing: { size: 1234, modifiedAt: 1700000000000 },
            incoming: { size: 5678, modifiedAt: 1710000000000 },
          };
        }
        return result;
      };
    }, withRom);
    await page.locator(".lrow").first().click();
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    const modal = page.locator(".paste-conflict-card");
    await expect(modal).toBeVisible();
    await expect(modal.locator(".paste-conflict-rom")).toHaveCount(withRom ? 2 : 0);
    if (withRom) {
      const lines = modal.locator(".paste-conflict-rom");
      await expect(lines.first()).toContainText("ROM");
      expect(await lines.first().evaluate(el => getComputedStyle(el).whiteSpace)).toBe("nowrap");
    }
  });
}
