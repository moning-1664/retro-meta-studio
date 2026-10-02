// Archive의 [n] 뱃지 - 같은 ROM에 서로 다른 버전이 둘 이상이고 아직 고르지 않았을 때만.
// Collection에는 Matching이 없다(사용자 결정): 후보를 고르게 하지 않는다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

const ROWS = [
  { romUid: "rid1", romIdentityId: "rid1", system: "ps2", file: "MGS2.iso", title: "Metal Gear Solid 2",
    sources: 2, hasMetadata: true, hasMedia: true, present: true, size: 0, storageId: "archive",
    desc: "", region: "", genre: "", rating: "" },
  { romUid: "rid2", romIdentityId: "rid2", system: "ps2", file: "FFX.iso", title: "Final Fantasy X",
    sources: 1, hasMetadata: true, hasMedia: true, present: true, size: 0, storageId: "archive",
    desc: "", region: "", genre: "", rating: "" },
];

async function openArchive(page, conflicts = { rid1: 2 }) {
  await openApp(page);
  await page.evaluate(({ rows, conflicts }) => {
    let pending = { ...conflicts };
    window.api.archiveRows = () => Promise.resolve({ ok: true, data: { rows, total: rows.length, offset: 0 } });
    window.api.archiveConflicts = () => Promise.resolve({ ok: true, data: { ...pending } });
    window.api.archiveVersions = () => Promise.resolve({ ok: true, data: { romIdentityId: "rid1", versions: [
      { recordIds: [11], sources: ["a"], sourceNames: ["Master"], fields: { name: "MGS2", desc: "Version one" }, media: { covers: 2048 } },
      { recordIds: [12], sources: ["b"], sourceNames: ["Android"], fields: { name: "MGS2 Sons of Liberty", desc: "Version two" }, media: { screenshots: 4096 } },
    ] } });
    window.api.archiveChooseVersion = () => { pending = {}; return Promise.resolve({ ok: true, data: {} }); };
    window.api.archiveUids = () => Promise.resolve({ ok: true, data: rows.map((r) => r.romUid) });
    const bySystem = {};
    rows.forEach((r) => { bySystem[r.system] = (bySystem[r.system] || 0) + 1; });
    window.api.archiveSystems = () => Promise.resolve({ ok: true,
      data: Object.entries(bySystem).map(([system, count]) => ({ system, count })) });
  }, { rows: ROWS, conflicts });
  await page.evaluate((rows) => { window.ROWS_FOR_TEST = rows; }, ROWS);
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".lrow").first()).toBeVisible();
}

test("Archive Ctrl+Z uses Archive undo and refreshes its operation state", async ({ page }) => {
  await openArchive(page);
  await page.evaluate(() => {
    window.__archiveUndoCalls = [];
    window.api.operationState = async (id) => ({ok: true, data: {
      undoOperationId: id === "__archive__" ? "archive-undo-op" : null,
    }});
    window.api.pasteUndo = async (id) => {
      window.__archiveUndoCalls.push(id);
      return {ok: true, data: {jobId: "archive-undo-job"}};
    };
    window.api.getJobProgress = async () => ({ok: true, data: {done: true, error: null,
      current: 1, total: 1, result: {operationId: "archive-undo-op"}}});
  });
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Control+z");
  await expect.poll(() => page.evaluate(() => window.__archiveUndoCalls)).toEqual(["__archive__"]);
  await expect(page.locator(".lrow").first()).toBeVisible();
});

test("Archive Ctrl+Y dispatches Archive redo", async ({ page }) => {
  await openArchive(page);
  await page.evaluate(() => {
    window.__redoCalls=[];
    window.api.pasteRedo=async id => {window.__redoCalls.push(id);return {ok:true,data:{jobId:null}};};
  });
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Control+y");
  await expect.poll(() => page.evaluate(() => window.__redoCalls)).toEqual(["__archive__"]);
});

test("Collection 목록에는 [n] 뱃지가 없다", async ({ page }) => {
  await openApp(page);
  await expect(page.locator(".match-badge")).toHaveCount(0);
});

test("Archive에서 가져오기는 선택한 후보로 독립 충돌 미리보기를 만든다", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__archiveImportCalls = [];
    window.api.matchCandidates = () => Promise.resolve({ ok: true, data: {
      source: { system: "ps2", filename: "Translated.iso", title: "Translated" },
      candidates: [{ romIdentityId: "chosen-archive-id", filename: "Original.iso",
        title: "Original", score: 88, tier: "normalized", evidence: ["제목 유사"],
        fields: { name: "Original", desc: "Archive description", developer: "Test Studio",
          publisher: "Test Publisher", genre: "RPG", releasedate: "2001" },
        mediaTypes: ["covers"] }],
      linkedRomIdentityId: null,
    } });
    window.api.applyMatch = (...args) => {
      window.__archiveImportCalls.push(["match", ...args]);
      return Promise.resolve({ ok: true, data: {} });
    };
    window.api.operationPreview = (id, action, options) => {
      window.__archiveImportCalls.push(["import", id, options.ids]);
      return Promise.resolve({ok: true, data: {operationId: "archive-import-test", action,
        count: 1, undoable: true, skipped: [], collisions: [{key: "ps2|Translated.iso",
          system: "ps2", filename: "Translated.iso", existingRomUid: 1,
          existingTitle: "Translated", incomingTitle: "Original", existingFields: {}, incomingFields: {}}]}});
    };
  });
  await page.locator(".lrow").first().click({ button: "right" });
  await page.locator(".ctx-menu .ctx-item", { hasText: "다른 목록에서 메타데이터 가져오기" }).hover();
  await page.locator(".ctx-submenu .ctx-item").filter({ hasText: /^Archive$/ }).click();
  await expect(page.locator(".match-option")).toHaveCount(1);
  await expect(page.locator(".match-option .scrape-candidate-desc")).toHaveText("Archive description");
  await expect(page.locator(".match-option .scrape-candidate-facts")).toContainText("88%");
  await page.locator(".match-option").click();
  await modalButton(page, "가져오기").click();
  await expect.poll(() => page.evaluate(() => window.__archiveImportCalls.map((call) => call[0])))
    .toEqual(["import"]);
  await expect.poll(() => page.evaluate(() => window.__archiveImportCalls[0][2]))
    .toEqual(["chosen-archive-id"]);
  await expect(page.locator(".modal-title")).toHaveText("같은 이름의 게임");
  await expect(page.locator(".paste-conflict-card")).toContainText("Translated");
});

test("변경이 없는 가져오기는 실행하지 않고 제외 이유를 표시한다", async ({page}) => {
  await openApp(page);
  await page.evaluate(() => {
    window.api.archiveUids = async () => ({ok: true, data: [11, 12]});
    window.api.operationPreview = async () => ({ok: true, data: {count: 0, skipped: [
      {filename: "A.iso", reason: "원본 파일을 찾을 수 없습니다."}]}});
    window.api.pasteExecute = async () => {throw new Error("empty operation executed");};
  });
  await page.getByRole("button", {name: "다른 목록에서 메타데이터 가져오기", exact: true}).click();
  await page.getByRole("button", {name: "Archive"}).last().click();
  await expect(page.locator("#toast")).toContainText("원본 파일을 찾을 수 없습니다");
});

test("대량 가져오기도 한 독립 작업으로 실행하고 Plan을 만들지 않는다", async ({page}) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__executed = [];
    window.api.archiveUids = async () => ({ok: true, data: Array.from({length: 101}, (_,i)=>i)});
    window.api.operationPreview = async () => ({ok: true, data: {operationId: "bulk-import", count: 101,
      action: "archive-import", undoable: true, collisions: [], skipped: []}});
    window.api.pasteExecute = async (id) => {window.__executed.push(id); return {ok: true, data: {jobId: "mock-operation"}};};
  });
  await page.getByRole("button", {name: "다른 목록에서 메타데이터 가져오기", exact: true}).click();
  await page.getByRole("button", {name: "Archive"}).last().click();
  await expect.poll(() => page.evaluate(()=>window.__executed)).toEqual(["bulk-import"]);
  await expect(page.locator("#filter-bar .plan-actions")).toHaveCount(0);
});

test("Archive에서는 서로 다른 버전이 있는 행에만 뱃지가 붙는다", async ({ page }) => {
  await openArchive(page);
  await expect(page.locator(".match-badge")).toHaveCount(1);
  await expect(page.locator(".match-badge")).toHaveText("[2]");
  await expect(page.locator(".lrow", { has: page.locator(".match-badge") })).toContainText("Metal Gear Solid 2");
});

test("뱃지를 누르면 판단에 필요한 정보와 함께 버전이 나온다", async ({ page }) => {
  await openArchive(page);
  await page.locator(".match-badge").click();
  await expect(page.locator(".modal-title")).toHaveText("서로 다른 버전");
  const options = page.locator(".ver-dialog-card .revision-row");
  await expect(options).toHaveCount(2);
  await expect(options.nth(0)).toContainText("Version one");
  await expect(options.nth(0).locator(".revision-cover")).toBeVisible();
  await expect(options.nth(1)).toContainText("Version two");
  await expect(page.locator(".ver-dialog-card .revision-actions button")).toBeEnabled();
});

test("버전을 고르면 뱃지가 사라진다", async ({ page }) => {
  await openArchive(page);
  await page.locator(".match-badge").click();
  await page.locator(".ver-dialog-card .revision-row").nth(1).click();
  await page.locator(".ver-dialog-card .revision-actions button").click();
  await expect(page.locator(".match-badge")).toHaveCount(0);
});

test("saved preferred revision is selected and an equal grouped revision does not enable apply", async ({ page }) => {
  await openArchive(page);
  await page.evaluate(() => {
    const versions = window.api.archiveVersions;
    window.api.archiveVersions = async (...args) => {
      const result = await versions(...args);
      result.data.preferredRecordId = 12;
      result.data.versions[1].recordIds = [13, 12];
      return result;
    };
  });
  await page.locator('.match-badge').click();
  const cards = page.locator('.ver-dialog-card .revision-row');
  const apply = page.locator('.ver-dialog-card .revision-actions button');
  await expect(cards.nth(1)).toHaveAttribute('aria-checked', 'true');
  await expect(apply).toBeDisabled();
  await cards.nth(1).click();
  await expect(apply).toBeDisabled();
  await cards.nth(0).click();
  await expect(apply).toBeEnabled();
});

test("[P0] 버전을 고르면 Gamelist 줄도 같이 바뀐다", async ({ page }) => {
  // 실사용 P0 - "Revision을 하나 선택했는데 metadata에는 반영되는데 GameList에는
  // 반영이 안된다". 예전엔 renderListWindow()로 캐시를 다시 그리기만 해서, 고른
  // 값이 상세에만 보이고 목록의 제목/설명은 옛 값 그대로였다.
  await openArchive(page);
  await page.evaluate(() => {
    // 버전을 고르면 백엔드의 Effective 값이 바뀐다 - 목록 재조회가 그 값을 준다.
    let chosen = false;
    const base = ROWS_FOR_TEST;
    window.api.archiveChooseVersion = () => { chosen = true; return Promise.resolve({ ok: true, data: {} }); };
    window.api.archiveRows = (q) => {
      const rows = base.map((r) => (chosen && r.romIdentityId === "rid1"
        ? { ...r, title: "고른 버전의 제목", desc: "고른 버전의 설명" } : r));
      const wanted = q && q.romIdentityIds;
      const out = wanted ? rows.filter((r) => wanted.includes(r.romIdentityId)) : rows;
      return Promise.resolve({ ok: true, data: { rows: out, total: out.length, offset: 0 } });
    };
  });

  await expect(page.locator(".lrow", { hasText: "Metal Gear Solid 2" })).toBeVisible();
  await page.locator(".match-badge").click();
  await page.locator(".ver-dialog-card .revision-row").nth(1).click();
  await page.locator(".ver-dialog-card .revision-actions button").click();

  await expect(page.locator(".lrow", { hasText: "고른 버전의 제목" })).toBeVisible();
  await expect(page.locator(".lrow", { hasText: "Metal Gear Solid 2" })).toHaveCount(0);
});

test("Archive에서 다른 필드를 저장해도 비어 있던 필드를 CLEARED로 만들지 않는다", async ({ page }) => {
  await openArchive(page);
  await page.evaluate(() => {
    window.SAVED_ARCHIVE_FIELDS = null;
    window.api.archiveDetail = () => Promise.resolve({ ok: true, data: {
      romIdentityId: "rid1", system: "ps2", filename: "MGS2.iso",
      fields: { name: "MGS2", genre: "Action" }, media: [], sources: [], versions: [],
    } });
    window.api.archiveEdit = (_rid, fields) => {
      window.SAVED_ARCHIVE_FIELDS = fields;
      return Promise.resolve({ ok: true, data: { revision: 1, changed: true } });
    };
  });
  await page.locator(".lrow").first().click();
  await expect(page.locator(".detail-save")).toBeVisible();
  await page.locator(".title-input").fill("MGS2 Edited");
  await page.locator(".detail-save").click();
  await expect.poll(() => page.evaluate(() => window.SAVED_ARCHIVE_FIELDS)).toMatchObject({
    name: "MGS2 Edited", genre: "Action",
  });
  expect(await page.evaluate(() => Object.hasOwn(window.SAVED_ARCHIVE_FIELDS, "developer"))).toBe(false);
});

test("Detail의 Revision 탭에 버전들이 실제로 보인다", async ({ page }) => {
  // 실사용 버그 리포트 - 목록엔 [n] 뱃지가 붙는데, 그 항목을 열어 Revision 탭으로
  // 가면 늘 "수집된 Revision이 없습니다"만 보였다. 원인은 화면이 archive_detail()의
  // versions/preferredRecordId를 S.detailState로 옮기다가 빠뜨린 것이었다 -
  // 백엔드는 항상 제대로 계산해서 주고 있었다.
  await openArchive(page);
  await page.evaluate(() => {
    window.api.archiveDetail = () => Promise.resolve({ ok: true, data: {
      romIdentityId: "rid1", gameId: "g", system: "ps2", filename: "MGS2.iso", title: "Metal Gear Solid 2",
      fields: { name: "MGS2" }, frontendRaw: {}, sources: [], media: [],
      romSources: [], edited: false, preferredRecordId: null,
      versions: [
        { recordIds: [11], sources: ["a"], fields: { name: "MGS2", desc: "Version one" }, media: { covers: 2048 } },
        { recordIds: [12], sources: ["b"], fields: { name: "MGS2 Sons of Liberty", desc: "Version two" }, media: {} },
      ] } });
  });
  await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).locator(".lc-title").click();
  await page.locator(".detail-tab", { hasText: "Revision" }).click();
  await expect(page.locator(".empty-msg")).toHaveCount(0);
  const rows = page.locator(".revision-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("Version one");
  await expect(rows.nth(1)).toContainText("Sons of Liberty");
});

test("Archive ROM 탭에서 파일 존재 여부와 RetroArch Core를 보여준다", async ({ page }) => {
  await openArchive(page);
  await page.evaluate(() => {
    window.api.archiveDetail = () => Promise.resolve({ ok: true, data: {
      romIdentityId: "rid1", system: "ps2", filename: "MGS2.iso", fields: { name: "MGS2" },
      present: true, size: 4096, romSources: [{ abs_path: "C:/roms/MGS2.iso" }],
      media: [], sources: [], versions: [],
    } });
    window.api.retroarchGameInfo = () => Promise.resolve({ ok: true, data: {
      system: "ps2", file: "MGS2.iso", present: true, cores: ["pcsx2_libretro.dll"],
      systemCore: "pcsx2_libretro.dll", gameCore: null,
    } });
  });
  await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).locator(".lc-title").click();
  await page.locator(".detail-tab", { hasText: "ROM" }).click();
  await expect(page.locator(".rom-info")).toContainText("ROM 파일있음");
  await expect(page.locator(".rom-core")).toContainText("RetroArch Core");
  // PS2는 테스트 기본 Emulator 설정에서 아직 검증되지 않은 System이라 선택 UI 대신
  // 기존 launchBlockReason의 설명을 보여야 한다.
  await expect(page.locator(".rom-core")).toContainText("아직 검증되지 않았습니다");
});

test.describe("Revision 탭 - 무엇이 다른지 보여준다", () => {
  // 실사용 지적 두 가지: (1) 고른 판을 ★로 표시해 즐겨찾기와 헷갈린다,
  // (2) 판끼리 무엇이 달라서 다른 판인지 알 수 없다.
  const openRevisions = async (page) => {
    await openArchive(page);
    await page.evaluate(() => {
      window.api.archiveDetail = () => Promise.resolve({ ok: true, data: {
        romIdentityId: "rid1", gameId: "g", system: "ps2", filename: "MGS2.iso",
        title: "Metal Gear Solid 2", fields: { name: "MGS2" }, frontendRaw: {},
        sources: [], media: [], romSources: [], edited: false, preferredRecordId: null,
        versions: [
          { recordIds: [11], sources: ["c1"], updatedAt: 1758400000,
            fields: { name: "MGS2", desc: "같은 설명", developer: "Konami" },
            media: { covers: 2048 } },
          { recordIds: [12], sources: ["c2"], updatedAt: 1758300000,
            fields: { name: "MGS2 Sons of Liberty", desc: "같은 설명" },
            media: { covers: 2048, screenshots: 4096 } },
        ] } });
    });
    await page.locator(".lrow", { hasText: "Metal Gear Solid 2" }).locator(".lc-title").click();
    await page.locator(".detail-tab", { hasText: "Revision" }).click();
  };

  test("고른 판은 ★가 아니라 PREFERRED 배지로 알린다", async ({ page }) => {
    await openRevisions(page);
    // 별표는 Revision 목록에 없어야 한다 - 즐겨찾기와 다른 개념이다.
    await expect(page.locator(".revision-row .fav-btn")).toHaveCount(0);
    await expect(page.locator(".revision-actions .btn.primary")).toHaveText("선택");
    await expect(page.locator(".revision-badge")).toHaveCount(0);
  });

  test("Revision 카드를 고르면 강조하고 하단 선택 버튼을 활성화한다", async ({ page }) => {
    await openRevisions(page);
    const rows = page.locator(".revision-row");
    await rows.nth(1).locator(".scrape-candidate-title").click();
    await expect(rows.nth(1)).toHaveClass(/chosen/);
    await expect(rows.nth(0)).not.toHaveClass(/chosen/);
    await expect(page.locator(".revision-actions .btn.primary")).toBeEnabled();
    await expect(page.locator(".revision-row .scrape-fact-row").first()).toBeVisible();
  });

  test("값이 갈리는 필드만 강조해서 보여준다", async ({ page }) => {
    await openRevisions(page);
    const first = page.locator(".revision-row").first();
    await first.locator(".revision-expand").click();
    // Title은 판마다 달라서 강조된다.
    await expect(first.locator(".candidate-detail-field.changed", { hasText: "제목" })).toBeVisible();
    // Developer도 한쪽에만 있으니 다르다.
    await expect(first.locator(".candidate-detail-field.changed", { hasText: "개발사" })).toBeVisible();
    // 공통 설명도 표시하되 변경 강조는 하지 않는다.
    await expect(first.locator(".candidate-detail-field:not(.changed)", { hasText: "설명" })).toBeVisible();
  });

  test("어느 출처의 언제 판인지 보여준다", async ({ page }) => {
    await openRevisions(page);
    await expect(page.locator(".revision-when")).toHaveCount(0);
    await expect(page.locator(".revision-row").first().locator(".revision-source")).not.toBeEmpty();
  });

  test("미디어도 다른 것만 표시가 다르다", async ({ page }) => {
    await openRevisions(page);
    const first = page.locator(".revision-row").first();
    // Screenshot은 둘째 판에만 있으니 갈린다 - 첫 판에서는 없음(off) 표시.
    await expect(first.locator(".revision-chip.changed.off")).toHaveCount(1);
    // Cover는 둘 다 같은 크기라 강조하지 않는다.
    await expect(first.locator(".revision-chip:not(.changed)")).toHaveCount(1);
  });
});

test("Archive에서도 Ctrl+A로 전체를 고를 수 있다", async ({ page }) => {
  // archiveUids()는 이미 있었고(HERO의 "다른 목록에서 메타데이터 가져오기"가 쓴다) 테스트도 있었는데,
  // Ctrl+A만 "아직 지원하지 않습니다" 경고만 띄우고 실제로는 부르지 않고 있었다.
  await openArchive(page);
  await page.locator(".lrow").nth(0).click();
  await page.keyboard.press("Control+a");
  await expect(page.locator("#toast")).toContainText("2개를 선택");
  await expect(page.locator(".lrow.selected")).toHaveCount(2);
});

test("Archive에서 클릭·Ctrl+클릭 선택과 탭 복귀 후 선택 표시가 유지된다", async ({ page }) => {
  await openArchive(page);
  await page.locator(".lrow").first().click();
  await expect(page.locator(".lrow.selected")).toHaveCount(1);
  await page.locator(".lrow").nth(1).click({ modifiers: ["Control"] });
  await expect(page.locator(".lrow.selected")).toHaveCount(2);
  await page.locator(".ctab:not(.archive)").first().click();
  await page.locator(".ctab.archive").click();
  await expect(page.locator(".lrow.selected")).toHaveCount(2);
});

test("Archive 카드 보기에서도 Ctrl+클릭으로 고른 항목이 강조된다", async ({ page }) => {
  await openArchive(page);
  await page.locator(".view-mode-seg .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-card")).toHaveCount(2);
  await page.locator(".preview-card").first().click();
  await page.locator(".preview-card").nth(1).click({ modifiers: ["Control"] });
  await expect(page.locator(".preview-card.selected")).toHaveCount(2);
});

test.describe("Archive System 우클릭", () => {
  // 실사용 버그 리포트 - "System 우클릭 옵션들도 다 안 되던데(prefix 붙이기, 디렉토리
  // 이동 등)". 확인해보니 Archive의 System 목록에는 우클릭 자체가 안 걸려 있었다.
  // Storage 이동·System 이름 변경은 아직 Archive 전용 경로가 없다.
  const rightClickSystem = (page, name) => page.locator(".nav-system", { hasText: name }).click({ button: "right" });
  const menuItem = (page, label) => page.locator(".ctx-menu .ctx-item", { hasText: label });

  test("Archive System 메뉴의 지원 동작과 남은 제한을 구분한다", async ({ page }) => {
    await openArchive(page);
    await rightClickSystem(page, "PS2");
    await expect(menuItem(page, "언어 태그 적용")).toBeVisible();
    await expect(menuItem(page, "멀티 디스크 태그 적용")).toBeVisible();
    await expect(menuItem(page, "시스템 기록 제거…")).toBeVisible();
    await expect(menuItem(page, "Storage 옮기기")).toHaveCount(0);
    await expect(menuItem(page, "이름 바꾸기")).toHaveCount(0);
    await expect(menuItem(page, "미디어 정리")).toBeVisible();
  });

  test("System 붙여넣기는 기존 게임도 충돌 확인 대상으로 허용한다", async ({ page }) => {
    await openArchive(page);
    await page.evaluate(() => {
      window.api.archiveClipboardSystemTarget = (system) => Promise.resolve({ ok: true,
        data: { system, items: [{ title: "New Game", filename: "New.iso" }], duplicates: [] } });
      window.__pastedSystem = null;
      window.api.archivePaste = (_mode, _target, system, newOnly) => {
        window.__pastedSystem = { system, newOnly };
        return Promise.resolve({ ok: true, data: { pasted: 1, skipped: [], conflicts: [] } });
      };
    });
    await rightClickSystem(page, "PS2");
    await menuItem(page, "여기에 붙여넣기 (1개)").click();
    await expect.poll(() => page.evaluate(() => window.__pastedSystem))
      .toEqual({ system: "ps2", newOnly: false });
    await page.evaluate(() => {
      window.api.archiveClipboardSystemTarget = (system) => Promise.resolve({ ok: true,
        data: { system, items: [], duplicates: [{ title: "New Game", filename: "New.iso" }] } });
    });
    await rightClickSystem(page, "PS2");
    await expect(menuItem(page, "여기에 붙여넣기 (1개)")).toBeEnabled();
  });

  test("Archive System을 보고 Ctrl+V하면 그 System을 대상으로 붙인다", async ({ page }) => {
    await openArchive(page);
    await page.evaluate(() => {
      window.__archivePasteTarget = null;
      window.api.archivePaste = (_mode, _row, system, newOnly) => {
        window.__archivePasteTarget = { system, newOnly };
        return Promise.resolve({ ok: true, data: { pasted: 1, skipped: [], conflicts: [] } });
      };
    });
    await page.locator(".nav-system", { hasText: "PS2" }).click();
    await page.keyboard.press("Control+v");
    await expect.poll(() => page.evaluate(() => window.__archivePasteTarget))
      .toEqual({ system: "ps2", newOnly: false });
  });

  test("System 미디어 정리에서 종류를 골라 삭제한다", async ({ page }) => {
    await openArchive(page);
    await page.evaluate(() => {
      window.api.archiveMediaCleanupPreview = () => Promise.resolve({ ok: true, data: {
        types: [{ type: "covers", label: "Covers", count: 2, bytes: 20 },
                { type: "videos", label: "Videos", count: 1, bytes: 100 }],
      } });
      window.__removedTypes = null;
      window.api.archiveMediaDeleteSystem = (_system, types) => {
        window.__removedTypes = types;
        return Promise.resolve({ ok: true, data: { removed: 2, linkedKept: 0, failures: [] } });
      };
    });
    await rightClickSystem(page, "PS2");
    await menuItem(page, "미디어 정리").click();
    await page.locator(".media-clean-row", { hasText: "Covers" }).locator("input").check();
    await page.locator(".modal-actions .btn.danger").click();
    await expect.poll(() => page.evaluate(() => window.__removedTypes)).toEqual(["covers"]);
  });

  test("언어 태그 적용은 미리보기 후 Plan 없이 바로 적용된다", async ({ page }) => {
    await openArchive(page);
    await page.evaluate(() => {
      window.api.archiveTitleAffixPreview = () => Promise.resolve({ ok: true, data: {
        items: [{ romUid: "rid2", system: "ps2", filename: "FFX.iso",
                 oldTitle: "Final Fantasy X", newTitle: "EN_Final Fantasy X", changed: true }],
        changed: 1 } });
      window.__applied = null;
      window.api.archiveApplyTitleAffix = (system) => {
        window.__applied = system;
        return Promise.resolve({ ok: true, data: { applied: 1 } });
      };
    });
    await rightClickSystem(page, "PS2");
    await menuItem(page, "언어 태그 적용").click();
    await expect(page.locator(".modal-title")).toHaveText("Title Prefix/Postfix");
    await expect(page.locator(".modal-text")).toContainText("확인하면 바로 적용");
    await page.locator(".modal-actions .btn.primary", { hasText: "적용" }).click();
    await expect.poll(() => page.evaluate(() => window.__applied)).toBe("ps2");
    await expect(page.locator("#toast")).toContainText("1개를 바꿨습니다");
  });

  test("ROM 없는 항목 정리가 메뉴에 있고, 확인하면 정리한다", async ({ page }) => {
    await openArchive(page);
    await page.evaluate(() => {
      window.__cleaned = null;
      window.api.archiveOrphanPreview = (system) => Promise.resolve({ ok: true, data: {
        system, items: [{ romIdentityId: "rid9", filename: "Ghost.iso", title: "유령 항목" }] } });
      window.api.archiveCleanupOrphans = (system) => {
        window.__cleaned = system;
        return Promise.resolve({ ok: true, data: { deleted: 1 } });
      };
    });
    await rightClickSystem(page, "PS2");
    await menuItem(page, "ROM 없는 항목 정리").click();
    await expect(page.locator(".modal-text")).toContainText("실제 ROM/Media 파일은 지워지지 않습니다");
    await expect(page.locator(".sysdel-target")).toContainText("유령 항목");
    await page.locator(".modal-actions .btn.danger", { hasText: "정리" }).click();
    await expect.poll(() => page.evaluate(() => window.__cleaned)).toBe("ps2");
  });

  test("시스템 전체 지우기는 확인 후 archiveDeleteSystem을 부른다", async ({ page }) => {
    await openArchive(page);
    await page.evaluate(() => {
      window.__deletedSystem = null;
      window.api.archiveDeleteSystem = (system) => {
        window.__deletedSystem = system;
        return Promise.resolve({ ok: true, data: { deleted: 2 } });
      };
    });
    await rightClickSystem(page, "PS2");
    await menuItem(page, "시스템 기록 제거…").click();
    await expect(page.locator(".modal-text")).toContainText("실제 ROM/Media 파일은 지워지지 않습니다");
    await modalButton(page, "확인").click();
    await expect.poll(() => page.evaluate(() => window.__deletedSystem)).toBe("ps2");
  });
});

test("행 우클릭의 ROM 폴더 열기는 현재 ROM 위치를 연다", async ({ page }) => {
  await openArchive(page);
  await page.evaluate(() => {
    window.__opened = null;
    window.api.archiveRomFolder = (rid) => {
      window.__opened = rid;
      return Promise.resolve({ ok: true, data: { path: "D:\Roms\ps2" } });
    };
  });
  await page.locator(".lrow", { hasText: "Final Fantasy X" }).click({ button: "right" });
  await page.locator(".ctx-menu .ctx-item", { hasText: "폴더 열기" }).hover();
  await page.locator(".ctx-submenu .ctx-item", { hasText: "ROM 디렉터리" }).click();
  await expect.poll(() => page.evaluate(() => window.__opened)).toBe("rid2");
});

test("Archive Navigator에서도 Favorites 관점으로 볼 수 있다", async ({ page }) => {
  await openArchive(page);
  await expect(page.locator("#nav .nav-favorites")).toBeVisible();
  await page.locator("#nav .nav-favorites").click();
  await expect(page.locator("#nav .nav-favorites")).toHaveClass(/active/);
});

test("Archive 새로고침은 진행률을 보이고 취소 요청을 job에 전달한다", async ({ page }) => {
  await openArchive(page);
  await page.evaluate(() => {
    window.__refreshCancelled = null;
    window.api.startArchiveRefresh = () => Promise.resolve({ ok: true, data: { jobId: "slow-refresh" } });
    window.api.jobProgress = () => Promise.resolve({ ok: true, data: window.__refreshCancelled ? {
      current: 1, total: 10, label: "취소", done: true, error: "취소되었습니다.", cancelled: true,
    } : { current: 1, total: 10, label: "PS2", done: false, error: null } });
    window.api.cancelJob = (jobId) => {
      window.__refreshCancelled = jobId;
      return Promise.resolve({ ok: true, data: true });
    };
  });
  await page.keyboard.press("F5");
  await expect(page.locator(".job-progress-item")).toContainText("Archive 다시 읽는 중");
  await page.locator(".job-progress-cancel").click();
  await expect.poll(() => page.evaluate(() => window.__refreshCancelled)).toBe("slow-refresh");
});

test.describe("Archive 행 우클릭 - 삭제", () => {
  // 실사용 버그 리포트 - "복붙이나 삭제 편집이 구조적으로 불가능해?": 삭제 메뉴는
  // 보이는데 눌러도 Collection용 API를 그대로 불러 매번 에러였다. ROM/메타데이터를
  // 따로 지우는 구분(Collection 전용)이 없다는 것도 이 메뉴가 확인해 준다.
  const rightClickRow = (page, text) => page.locator(".lrow", { hasText: text }).click({ button: "right" });
  const menuItem = (page, label) => page.locator(".ctx-menu .ctx-item").filter({
    has: page.locator(".ctx-label", { hasText: new RegExp(`^${label}$`) }),
  });

  test("Archive 보관 ROM과 메타데이터를 별도로 삭제할 수 있다", async ({ page }) => {
    await openArchive(page);
    await rightClickRow(page, "Final Fantasy X");
    await expect(menuItem(page, "ROM 삭제")).toHaveCount(0);
    await expect(menuItem(page, "메타데이터 삭제")).toBeVisible();
    await expect(menuItem(page, "보관 ROM 파일 삭제")).toHaveCount(0);
    await expect(menuItem(page, "Archive 기록 제거")).toBeVisible();
  });

  test("메타데이터 삭제는 Archive API를 호출한다", async ({ page }) => {
    await openArchive(page);
    await page.evaluate(() => {
      window.__metadataIds = null;
      window.api.archiveMetadataDelete = (ids) => {
        window.__metadataIds = ids;
        return Promise.resolve({ ok: true, data: { cleared: ids.length, failures: [] } });
      };
    });
    await rightClickRow(page, "Final Fantasy X");
    await menuItem(page, "메타데이터 삭제").click();
    await modalButton(page, "확인").click();
    await expect.poll(() => page.evaluate(() => window.__metadataIds)).toEqual(["rid2"]);
  });

  test("확인하면 실제로 지워지고, 실제 파일은 그대로라고 알린다", async ({ page }) => {
    await openArchive(page);
    await page.evaluate(() => {
      window.__deleted = [];
      const original = window.api.archiveDelete;
      window.api.archiveDelete = (ids) => { window.__deleted.push(ids); return original(ids); };
    });
    await rightClickRow(page, "Final Fantasy X");
    await menuItem(page, "Archive 기록 제거").click();
    await expect(page.locator(".modal-text")).toContainText("실제 ROM/Media 파일은 지워지지 않습니다");
    await modalButton(page, "확인").click();
    await expect.poll(() => page.evaluate(() => window.__deleted.length)).toBeGreaterThan(0);
    expect(await page.evaluate(() => window.__deleted[0])).toEqual(["rid2"]);
    await expect(page.locator("#toast")).toContainText("실제 ROM/Media 파일은 그대로");
  });
});

test("Archive Status 아이콘 우클릭에도 종류별 메뉴가 열린다", async ({ page }) => {
  await openArchive(page);
  await page.locator(".lrow").first().locator(".status-icon[data-status='rom']")
    .click({ button: "right" });
  await expect(page.locator(".ctx-menu")).toBeVisible();
  await expect(page.locator(".ctx-menu .ctx-item", { hasText: "ROM 삭제" })).toBeVisible();
});

test("미디어를 우클릭하면 복사/붙여넣기 메뉴가 나온다", async ({ page }) => {
  await openArchive(page);
  await page.evaluate(() => {
    window.api.archiveDetail = () => Promise.resolve({ ok: true, data: {
      romIdentityId: "rid2", gameId: "g", system: "ps2", filename: "FFX.iso", title: "Final Fantasy X",
      fields: { name: "Final Fantasy X" }, frontendRaw: {}, sources: [], media: [{ media_type: "covers" }],
      romSources: [], edited: false, preferredRecordId: null } });
  });
  await page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".lc-title").click();
  await page.locator(".detail-tab", { hasText: "미디어" }).click();
  await page.locator(".media-tile.cover").click({ button: "right" });
  await expect(page.locator(".ctx-item", { hasText: "미디어 복사" })).toBeVisible();
  await expect(page.locator(".ctx-item", { hasText: "미디어 붙여넣기" })).toBeVisible();
});

test("Archive 설정 전에는 탭을 숨기고 Settings에서 생성할 수 있다", async ({ page }) => {
  await openApp(page, { archiveUnconfigured: true });
  await expect(page.locator(".ctab.archive")).toHaveCount(0);
  await page.locator("#btn-settings, [title='Settings'], .settings-btn").first().click();
  await page.locator(".stg-nav-item, .stg-tab", { hasText: "Archive" }).first().click();
  await expect(page.locator(".archive-mode")).toHaveValue("new");
  await expect(page.locator(".archive-frontend")).toBeVisible();
  await expect(page.locator(".archive-dir")).toBeVisible();
  await expect(page.locator(".archive-rom-dir")).toBeVisible();
  await expect(page.locator(".archive-media-internal")).toBeChecked();
});

test("저장하고 적용하면 설정을 보내고 적용 job을 시작한다", async ({ page }) => {
  await openApp(page, { archiveUnconfigured: true });
  await page.evaluate(() => {
    window.__calls = [];
    const save = window.api.saveArchiveConfig, apply = window.api.startArchiveApply;
    window.api.saveArchiveConfig = (p) => { window.__calls.push(["save", p]); return save(p); };
    window.api.startArchiveApply = () => { window.__calls.push(["apply"]); return apply(); };
  });
  await page.locator("#btn-settings, [title='Settings'], .settings-btn").first().click();
  await page.locator(".stg-nav-item, .stg-tab", { hasText: "Archive" }).first().click();
  await page.locator(".archive-dir").fill("D:\\Archives");
  await page.locator(".archive-frontend").selectOption("es-de");
  await page.locator(".archive-dir").blur();
  await expect(page.locator(".folder-detection").first()).toContainText("새 Archive");
  await page.locator(".archive-apply").click();
  await expect.poll(() => page.evaluate(() => window.__calls.length)).toBe(2);
  const calls = await page.evaluate(() => window.__calls);
  expect(calls[0][1]).toMatchObject({ frontend: "es-de", archiveDir: "D:\\Archives", mediaInternal: true });
  expect(calls[1]).toEqual(["apply"]);
});

test("Settings에도 같은 Archive 설정이 있다", async ({ page }) => {
  await openApp(page);
  await page.locator("#btn-settings, [title='Settings'], .settings-btn").first().click();
  await page.locator(".stg-nav-item, .stg-tab", { hasText: "Archive" }).first().click();
  await expect(page.locator(".archive-dir")).toBeVisible();
});

// 사용자 피드백 - "디렉토리 선택도 안했는데 export가 되고 있다. 디렉토리 선택 후 export 가능하도록".
test.describe("디렉토리를 정하기 전에는 보내지 않는다", () => {
  test("Archive로 보내기를 누르면 수집 대신 설정 창이 뜬다", async ({ page }) => {
    await openApp(page, { archiveUnconfigured: true });
    await page.evaluate(() => {
      window.__ingests = 0;
      const original = window.api.startArchiveIngest;
      window.api.startArchiveIngest = (...args) => { window.__ingests += 1; return original(...args); };
    });
    await page.locator("#collection-header .cheader-right .icon-btn[title*='Archive로 보내기']").click();
    await expect(page.locator(".modal-title")).toHaveText("Archive 설정");
    await expect(page.locator("#toast")).toContainText("디렉토리를 먼저 정하세요");
    expect(await page.evaluate(() => window.__ingests)).toBe(0);
  });

  test("디렉토리를 정한 뒤에는 수집 계획이 만들어진다", async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => window.api.saveArchiveConfig({ archiveDir: "D:\Archives" }));
    await page.evaluate(() => {
      window.__ingests = 0;
      const original = window.api.startArchiveIngest;
      window.api.startArchiveIngest = (...args) => { window.__ingests += 1; return original(...args); };
    });
    await page.locator("#collection-header .cheader-right .icon-btn[title*='Archive로 보내기']").click();
    await expect.poll(() => page.evaluate(() => window.__ingests)).toBe(1);
  });
});

// 사용자 결정 - "Media만 복붙하기". Archive는 즉시, Collection은 Plan을 거친다(바이트가 움직인다).
test("Collection에서도 미디어 한 장만 독립 적용한다", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__pasted = [];
    window.api.pasteExecute = async () => ({ok: true, data: {jobId: "mock-operation"}});
    window.api.mediaPaste = async (id, romUid, key, source) => {
      window.__pasted.push({ romUid, key, source });
      return { ok: true, data: { operationId: "media-test", action: "media", count: 1, undoable: true, collisions: [], skipped: [] } };
    };
  });
  await page.locator(".lrow", { hasText: "Final Fantasy X" }).locator(".lc-file").click();
  await page.locator(".detail-tab", { hasText: "미디어" }).click();
  await page.locator(".media-tile.cover").click({ button: "right" });
  await page.locator(".ctx-item", { hasText: "미디어 복사" }).click();
  await page.locator(".media-tile.cover").click({ button: "right" });
  await page.locator(".ctx-item", { hasText: "미디어 붙여넣기" }).click();
  await expect.poll(() => page.evaluate(() => window.__pasted.length)).toBe(1);
  expect((await page.evaluate(() => window.__pasted))[0].key).toBe("Covers");
  await expect(page.locator("#toast")).toContainText("붙여넣기");
});

// 사용자 결정 - "유사롬만 골라서 볼 수 있는 filter 옵션 추가".
test.describe("다른 버전이 있는 항목만 보기", () => {
  test("Archive 툴바에만 있고 눌러서 켜고 끈다", async ({ page }) => {
    await openApp(page);
    await expect(page.locator(".archive-conflicts-only")).toHaveCount(0);   // Collection에는 없다
    await page.locator(".ctab.archive").click();
    const btn = page.locator(".archive-conflicts-only");
    await expect(btn).toBeVisible();
    // 켜짐 표시는 "on" 클래스다 - 정규식 대신 classList로 본다(다른 클래스에 on이 섞여도 안전).
    const isOn = () => btn.evaluate((el) => el.classList.contains("on"));
    expect(await isOn()).toBe(false);
    await btn.click();
    await expect.poll(isOn).toBe(true);
    await btn.click();
    await expect.poll(isOn).toBe(false);
  });

  test("켜면 목록 조회에 그대로 전달된다", async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      window.__queries = [];
      const original = window.api.archiveRows;
      window.api.archiveRows = (q) => { window.__queries.push(!!q.conflictsOnly); return original(q); };
    });
    await page.locator(".ctab.archive").click();
    await expect.poll(() => page.evaluate(() => window.__queries.length)).toBeGreaterThan(0);
    await page.locator(".archive-conflicts-only").click();
    await expect.poll(() => page.evaluate(() =>
      window.__queries[window.__queries.length - 1])).toBe(true);
  });
});
