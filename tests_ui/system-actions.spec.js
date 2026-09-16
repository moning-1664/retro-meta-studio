// System 관리 (stitch-v3 Phase 7) - 빈 System 숨기기, System 폴더 열기, System 전체 삭제(두 번 묻기).
//
// 목업: ps2(2개, External SD) / snes(1개, Internal) / gba(0개, Internal).
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const navSystem = (page, name) => page.locator(".nav-system", { hasText: name });
// 토글은 맨 위 SYSTEMS 띠에 있다(실사용 피드백) - 그 아래 스크롤 안에 같은
// 뜻의 머리를 또 두지 않는다.
const hideToggle = (page) => page.locator(".nav-eyebrow .nav-hide-empty");

test.describe("빈 System 숨기기", () => {
  test("기본은 모두 보이고, SYSTEMS 옆 버튼으로 빈 System을 숨긴다", async ({ page }) => {
    await expect(navSystem(page, "GBA")).toBeVisible();
    await hideToggle(page).click();
    await expect(navSystem(page, "GBA")).toHaveCount(0);
    await expect(navSystem(page, "PS2")).toBeVisible();
    await expect(hideToggle(page)).toHaveAttribute("aria-pressed", "true");
    await hideToggle(page).click();
    await expect(navSystem(page, "GBA")).toBeVisible();
  });

  test("SYSTEMS 띠가 맨 위에 있다", async ({ page }) => {
    await expect(page.locator(".nav-eyebrow-label")).toHaveText("SYSTEMS");
  });

  test("값을 Settings에 저장한다", async ({ page }) => {
    await page.evaluate(() => {
      window.__saved = [];
      const original = window.api.saveAppSettings;
      window.api.saveAppSettings = (patch) => { window.__saved.push(patch); return original(patch); };
    });
    await hideToggle(page).click();
    await expect.poll(() => page.evaluate(() => window.__saved.length)).toBeGreaterThan(0);
    const saved = await page.evaluate(() => window.__saved.at(-1));
    expect(saved.navigation).toEqual({ hideEmptySystems: true });
  });

  test("지금 보고 있는 System은 비어 있어도 남긴다", async ({ page }) => {
    await navSystem(page, "GBA").click();
    await hideToggle(page).click();
    await expect(navSystem(page, "GBA")).toBeVisible();
    await page.locator(".nav-all").click();
    await expect(navSystem(page, "GBA")).toHaveCount(0);
  });

  test("Settings의 Collections 섹션에서도 바꿀 수 있다", async ({ page }) => {
    await page.locator(".settings-btn").click();
    await page.locator(".stg-nav-item[data-section='collections']").click();
    const row = page.locator(".stg-row[data-key='navigation.hideEmptySystems']");
    await expect(row).not.toHaveClass(/soon/);
    await row.locator(".stg-switch").click();
    await expect(navSystem(page, "GBA")).toHaveCount(0);
  });
});

test.describe("System 폴더 열기", () => {
  test("System 메뉴에 ROM / Metadata / Media 폴더 열기가 있다", async ({ page }) => {
    await navSystem(page, "PS2").click({ button: "right" });
    for (const label of ["ROM 폴더", "Metadata 폴더", "Media 폴더"]) {
      await expect(page.locator(".ctx-menu .ctx-item", { hasText: label })).toBeEnabled();
    }
  });

  test("누르면 그 System과 종류로 백엔드에 요청한다", async ({ page }) => {
    await page.evaluate(() => {
      window.__opened = [];
      window.api.openSystemFolder = async (id, system, kind) => {
        window.__opened.push([system, kind]); return { ok: true, data: { path: "x" } };
      };
    });
    await navSystem(page, "PS2").click({ button: "right" });
    await page.locator(".ctx-menu .ctx-item", { hasText: "Metadata 폴더" }).click();
    await expect.poll(() => page.evaluate(() => window.__opened)).toEqual([["ps2", "metadata"]]);
  });

  test("폴더가 없으면 오류를 알린다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.openSystemFolder = async () => ({ ok: false, error: "폴더가 없습니다: D:\\x" });
    });
    await navSystem(page, "PS2").click({ button: "right" });
    await page.locator(".ctx-menu .ctx-item", { hasText: "Media 폴더" }).click();
    await expect(page.locator(".toast-msg")).toHaveText(/폴더가 없습니다/);
  });
});

test.describe("System 전체 삭제 - 두 번 묻는다", () => {
  const deleteItem = (page) => page.locator(".ctx-menu .ctx-item", { hasText: "전체 삭제" });
  const openDelete = async (page, name) => {
    await navSystem(page, name).click({ button: "right" });
    await deleteItem(page).click();
    await expect(page.locator(".modal-title")).toHaveText(`${name} 전체 삭제`);
  };
  const spyRemove = async (page) => {
    await page.evaluate(() => {
      window.__removed = [];
      const original = window.api.removeSystem;
      window.api.removeSystem = (id, system, force) => { window.__removed.push([system, force]); return original(id, system, force); };
    });
  };

  test("메뉴 최하단에 빨간 [전체 삭제]가 있고 게임이 있어도 누를 수 있다", async ({ page }) => {
    await navSystem(page, "PS2").click({ button: "right" });
    const last = page.locator(".ctx-menu .ctx-item").last();
    await expect(last).toHaveText(/전체 삭제/);
    await expect(last).toHaveClass(/danger/);
    await expect(last).toBeEnabled();
    await expect(page.locator(".ctx-menu .ctx-item", { hasText: "System 삭제" })).toHaveCount(0);
  });

  test("경고와 지울 목록을 보여주고, 체크하기 전에는 확인 버튼이 꺼져 있다", async ({ page }) => {
    await openDelete(page, "PS2");
    await expect(page.locator(".sysdel-warning")).toContainText("되돌릴 수 없는 삭제입니다");
    await expect(page.locator(".sysdel-warning")).toContainText("게임 2개");
    await expect(page.locator(".sysdel-target")).toHaveCount(2);
    await expect(page.locator(".sysdel-ack")).toHaveText("확인하였습니다");
    await expect(modalButton(page, "확인")).toBeDisabled();
    await page.locator(".sysdel-ack-input").check();
    await expect(modalButton(page, "확인")).toBeEnabled();
    await page.locator(".sysdel-ack-input").uncheck();
    await expect(modalButton(page, "확인")).toBeDisabled();
  });

  test("체크하고 확인까지 누르면 지운다", async ({ page }) => {
    await spyRemove(page);
    await openDelete(page, "PS2");
    await page.locator(".sysdel-ack").click();
    await modalButton(page, "확인").click();
    await expect(navSystem(page, "PS2")).toHaveCount(0);
    await expect(page.locator(".toast-msg")).toHaveText("PS2 System을 삭제했습니다.");
    expect(await page.evaluate(() => window.__removed)).toEqual([["ps2", true]]);
    // 보고 있던 All 목록에서도 그 게임들이 빠진다.
    await expect(page.locator(".lrow")).toHaveCount(1);
  });

  test("취소하면 아무것도 지우지 않는다", async ({ page }) => {
    await spyRemove(page);
    await openDelete(page, "PS2");
    await page.locator(".sysdel-ack-input").check();
    await modalButton(page, "취소").click();
    await expect(page.locator(".modal-title")).toHaveCount(0);
    await expect(navSystem(page, "PS2")).toBeVisible();
    expect(await page.evaluate(() => window.__removed)).toEqual([]);
  });

  test("빈 System도 같은 절차로 지운다", async ({ page }) => {
    await openDelete(page, "GBA");
    await expect(modalButton(page, "확인")).toBeDisabled();
    await page.locator(".sysdel-ack-input").check();
    await modalButton(page, "확인").click();
    await expect(navSystem(page, "GBA")).toHaveCount(0);
  });

  test("보고 있던 System을 지우면 All로 돌아간다", async ({ page }) => {
    await navSystem(page, "GBA").click();
    await openDelete(page, "GBA");
    await page.locator(".sysdel-ack-input").check();
    await modalButton(page, "확인").click();
    await expect(page.locator(".nav-all")).toHaveClass(/active/);
  });

  test("백엔드가 막으면 이유만 보여주고 확인 버튼을 두지 않는다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.systemRemovalPreview = async (id, system) => ({ ok: true, data: {
        system, games: 0, targets: [], kept: [], totalFiles: 0, totalBytes: 0,
        blockers: ["이 저장소에서는 System 폴더를 지울 수 없습니다."] } });
    });
    await navSystem(page, "GBA").click({ button: "right" });
    await deleteItem(page).click();
    await expect(page.locator(".sysdel-blocker")).toHaveText("이 저장소에서는 System 폴더를 지울 수 없습니다.");
    await expect(modalButton(page, "확인")).toHaveCount(0);
  });
});

// ROM 없는 항목 정리 - System 우클릭 메뉴(사용자 결정, 2026-09). 삭제 자체는 새로 만들지
// 않고 기존 Plan 삭제(planDelete)를 그대로 쓴다 - 여기서는 화면 흐름만 확인한다.
test.describe("ROM 없는 항목 정리", () => {
  const cleanupItem = (page) => page.locator(".ctx-menu .ctx-item", { hasText: "ROM 없는 항목 정리" });
  const mockOrphans = (page, items) => page.evaluate((data) => {
    window.api.orphanMetadataPreview = async (id, system) => ({ ok: true, data: { system, items: data } });
  }, items);
  const spyPlanDelete = async (page) => {
    await page.evaluate(() => {
      window.__planDeleted = [];
      const original = window.api.planDelete;
      window.api.planDelete = (id, uids) => { window.__planDeleted.push(uids); return original(id, uids); };
    });
  };

  test("System 메뉴에 항목이 있다", async ({ page }) => {
    await navSystem(page, "PS2").click({ button: "right" });
    await expect(cleanupItem(page)).toBeEnabled();
  });

  test("정리할 항목이 없으면 안내만 뜨고 모달은 열리지 않는다", async ({ page }) => {
    await mockOrphans(page, []);
    await navSystem(page, "PS2").click({ button: "right" });
    await cleanupItem(page).click();
    await expect(page.locator(".toast-msg")).toHaveText("PS2에 정리할 항목이 없습니다.");
    await expect(page.locator(".modal-title")).toHaveCount(0);
  });

  test("항목이 있으면 목록을 보여주고, 확인하면 Plan에 올린다", async ({ page }) => {
    await mockOrphans(page, [{ romUid: 101, filename: "Ghost.iso", title: "Ghost Game" }]);
    await spyPlanDelete(page);
    await navSystem(page, "PS2").click({ button: "right" });
    await cleanupItem(page).click();
    await expect(page.locator(".modal-title")).toHaveText("PS2 - ROM 없는 항목 정리");
    await expect(page.locator(".sysdel-list")).toContainText("Ghost Game");
    await expect(page.locator(".sysdel-list")).toContainText("Ghost.iso");
    await modalButton(page, "삭제").click();
    await expect.poll(() => page.evaluate(() => window.__planDeleted)).toEqual([[101]]);
    // 기본값(Auto Plan 켜짐)에서는 아직 파일이 지워지지 않고 Plan에만 올라간다.
    await expect(page.locator(".toast-msg")).toHaveText("1개를 삭제 예정으로 표시했습니다.");
  });

  test("취소하면 아무것도 하지 않는다", async ({ page }) => {
    await mockOrphans(page, [{ romUid: 101, filename: "Ghost.iso", title: "Ghost Game" }]);
    await spyPlanDelete(page);
    await navSystem(page, "PS2").click({ button: "right" });
    await cleanupItem(page).click();
    await modalButton(page, "취소").click();
    await expect(page.locator(".modal-title")).toHaveCount(0);
    expect(await page.evaluate(() => window.__planDeleted)).toEqual([]);
  });

  test("여러 개 중 일부를 골라 지운다(전체가 아니라 목록 전부를 대상으로 한다)", async ({ page }) => {
    await mockOrphans(page, [
      { romUid: 101, filename: "Ghost.iso", title: "Ghost Game" },
      { romUid: 102, filename: "Phantom.iso", title: "Phantom Game" },
    ]);
    await spyPlanDelete(page);
    await navSystem(page, "PS2").click({ button: "right" });
    await cleanupItem(page).click();
    await expect(page.locator(".sysdel-target")).toHaveCount(2);
    await modalButton(page, "삭제").click();
    await expect.poll(() => page.evaluate(() => window.__planDeleted)).toEqual([[101, 102]]);
  });

  test("50개가 넘으면 나머지는 개수로만 알려준다", async ({ page }) => {
    const items = Array.from({ length: 60 }, (_, i) => ({ romUid: i, filename: `G${i}.iso`, title: `Game ${i}` }));
    await mockOrphans(page, items);
    await navSystem(page, "PS2").click({ button: "right" });
    await cleanupItem(page).click();
    await expect(page.locator(".sysdel-target")).toHaveCount(50);
    await expect(page.locator(".sysdel-file")).toContainText("외 10개");
  });

  test("백엔드 오류는 토스트로 알리고 모달을 열지 않는다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.orphanMetadataPreview = async () => ({ ok: false, error: "System을 찾을 수 없습니다." });
    });
    await navSystem(page, "PS2").click({ button: "right" });
    await cleanupItem(page).click();
    await expect(page.locator(".toast-msg")).toHaveText("System을 찾을 수 없습니다.");
    await expect(page.locator(".modal-title")).toHaveCount(0);
  });
});

// System 전체 미디어 정리 - System 우클릭 메뉴(사용자 결정, 2026-09). Cover/Screenshot/
// Video 등 media 종류를 체크박스로 골라 그 System 전체에서만 지운다.
test.describe("System 전체 미디어 정리", () => {
  const mediaItem = (page) => page.locator(".ctx-menu .ctx-item", { hasText: "System 전체 미디어 정리" });
  const mockTypes = (page, types) => page.evaluate((data) => {
    window.api.mediaCleanupPreview = async (id, system) => ({ ok: true, data: { system, types: data } });
  }, types);
  const spyCleanup = async (page) => {
    await page.evaluate(() => {
      window.__cleaned = [];
      window.api.mediaCleanup = (id, system, mediaTypes) => {
        window.__cleaned.push([system, mediaTypes]);
        return Promise.resolve({ ok: true, data: { removed: mediaTypes.length, failed: [] } });
      };
    });
  };

  test("System 메뉴에 항목이 있다", async ({ page }) => {
    await navSystem(page, "PS2").click({ button: "right" });
    await expect(mediaItem(page)).toBeEnabled();
  });

  test("정리할 media가 없으면 안내만 뜨고 모달은 열리지 않는다", async ({ page }) => {
    await mockTypes(page, []);
    await navSystem(page, "PS2").click({ button: "right" });
    await mediaItem(page).click();
    await expect(page.locator(".toast-msg")).toHaveText("PS2에 정리할 media가 없습니다.");
    await expect(page.locator(".modal-title")).toHaveCount(0);
  });

  test("타입별 개수·용량을 보여주고, 하나도 안 고르면 삭제 버튼이 꺼져 있다", async ({ page }) => {
    await mockTypes(page, [
      { type: "covers", label: "Covers", count: 3, bytes: 3000 },
      { type: "videos", label: "Videos", count: 1, bytes: 500000 },
    ]);
    await navSystem(page, "PS2").click({ button: "right" });
    await mediaItem(page).click();
    await expect(page.locator(".modal-title")).toHaveText("PS2 - 미디어 정리");
    await expect(page.locator(".media-clean-row")).toHaveCount(2);
    await expect(page.locator(".media-clean-row", { hasText: "Covers" })).toContainText("3개");
    await expect(modalButton(page, "삭제")).toBeDisabled();
  });

  test("체크한 타입만 골라서 지운다", async ({ page }) => {
    await mockTypes(page, [
      { type: "covers", label: "Covers", count: 3, bytes: 3000 },
      { type: "videos", label: "Videos", count: 1, bytes: 500000 },
    ]);
    await spyCleanup(page);
    await navSystem(page, "PS2").click({ button: "right" });
    await mediaItem(page).click();
    await page.locator(".media-clean-row", { hasText: "Videos" }).locator("input").check();
    await expect(modalButton(page, "삭제")).toBeEnabled();
    await modalButton(page, "삭제").click();
    await expect.poll(() => page.evaluate(() => window.__cleaned)).toEqual([["ps2", ["videos"]]]);
    await expect(page.locator(".toast-msg")).toHaveText("PS2에서 media 1개를 지웠습니다.");
  });

  test("여러 타입을 함께 고를 수 있다", async ({ page }) => {
    await mockTypes(page, [
      { type: "covers", label: "Covers", count: 3, bytes: 3000 },
      { type: "videos", label: "Videos", count: 1, bytes: 500000 },
    ]);
    await spyCleanup(page);
    await navSystem(page, "PS2").click({ button: "right" });
    await mediaItem(page).click();
    await page.locator(".media-clean-row", { hasText: "Covers" }).locator("input").check();
    await page.locator(".media-clean-row", { hasText: "Videos" }).locator("input").check();
    await modalButton(page, "삭제").click();
    await expect.poll(() => page.evaluate(() => window.__cleaned)).toEqual([["ps2", ["covers", "videos"]]]);
  });

  test("취소하면 아무것도 지우지 않는다", async ({ page }) => {
    await mockTypes(page, [{ type: "covers", label: "Covers", count: 3, bytes: 3000 }]);
    await spyCleanup(page);
    await navSystem(page, "PS2").click({ button: "right" });
    await mediaItem(page).click();
    await page.locator(".media-clean-row").locator("input").check();
    await modalButton(page, "취소").click();
    await expect(page.locator(".modal-title")).toHaveCount(0);
    expect(await page.evaluate(() => window.__cleaned)).toEqual([]);
  });

  test("일부 삭제 실패는 경고로 알린다", async ({ page }) => {
    await mockTypes(page, [{ type: "covers", label: "Covers", count: 2, bytes: 2000 }]);
    await page.evaluate(() => {
      window.api.mediaCleanup = async () => ({ ok: true, data: { removed: 1, failed: ["D:\\x\\a.png"] } });
    });
    await navSystem(page, "PS2").click({ button: "right" });
    await mediaItem(page).click();
    await page.locator(".media-clean-row").locator("input").check();
    await modalButton(page, "삭제").click();
    await expect(page.locator("#toast.warning .toast-msg")).toHaveText("PS2에서 media 1개를 지웠습니다. (1개 실패)");
  });

  test("백엔드 오류는 토스트로 알리고 모달을 열지 않는다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.mediaCleanupPreview = async () => ({ ok: false, error: "System을 찾을 수 없습니다." });
    });
    await navSystem(page, "PS2").click({ button: "right" });
    await mediaItem(page).click();
    await expect(page.locator(".toast-msg")).toHaveText("System을 찾을 수 없습니다.");
    await expect(page.locator(".modal-title")).toHaveCount(0);
  });
});
