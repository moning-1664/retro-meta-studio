/* ==========================================================================
   api-client.js
   window.pywebview.api를 감싸는 얇은 래퍼.

   pywebview가 없을 때(브라우저에서 index.html을 직접 열어 화면만 확인할 때)는
   목업으로 폴백한다. 실제 앱에서는 항상 pywebview가 있으므로 이 경로는 타지 않는다.
   ========================================================================== */

(function () {
  const hasBridge = () => typeof window.pywebview !== "undefined" && window.pywebview.api;
  const ok = (data) => Promise.resolve({ ok: true, data });

  // ------------------------------------------------------------------
  // 목업 (디자인 확인용)
  // ------------------------------------------------------------------
  const mockCollections = [
    { id: "c1", name: "Master Library", frontend: "es-de", frontendLabel: "ES-DE",
      target: "windows", os: null, arch: "x64", rootPath: "D:\\ES-DE", systemCount: 2 },
    { id: "c2", name: "Android ES-DE", frontend: "es-de", frontendLabel: "ES-DE",
      target: "android", os: "android", arch: "arm64", rootPath: "E:\\ES-DE", systemCount: 2 },
  ];
  const mockRows = [
    { romUid: 1, system: "ps2", file: "FFX.iso", title: "Final Fantasy X", size: 4400000000,
      storageId: "ext-1", hasMetadata: true, hasMedia: true, present: true,
      desc: "스피라를 여행하는 소환사와 가드의 이야기.", region: "JP", rating: "4.5",
      genre: "RPG", favorite: true },
    { romUid: 2, system: "ps2", file: "MGS2.iso", title: "Metal Gear Solid 2", size: 4300000000,
      storageId: "ext-1", hasMetadata: true, hasMedia: false, present: true,
      desc: "빅 쉘에서 벌어지는 잠입 임무.", region: "USA", rating: "4.0",
      genre: "Action", favorite: false },
    { romUid: 3, system: "snes", file: "SMW.sfc", title: "Super Mario World", size: 524288,
      storageId: "internal", hasMetadata: false, hasMedia: false, present: true,
      desc: "", region: "", rating: "", genre: "", favorite: false },
  ];
  const mockDetail = {
    id: "c1", name: "Master Library", frontend: "es-de", frontendLabel: "ES-DE",
    target: "windows", arch: "x64", rootPath: "D:\\ES-DE", systemCount: 2, totalGames: 3,
    storages: [
      { id: "internal", kind: "internal", label: "Internal", rootPath: "D:\\ES-DE",
        actualBytes: 524288, capacityBytes: 512e9, freeBytes: 200e9,
        systems: [{ system: "snes", count: 1 }] },
      { id: "ext-1", kind: "external", label: "External SD", rootPath: "E:\\ROMs",
        actualBytes: 8700000000, capacityBytes: 512e9, freeBytes: 90e9,
        systems: [{ system: "ps2", count: 2 }] },
    ],
    // 좌측 내비게이션이 그리는 평평한 System 목록. 게임이 있는 것이 먼저, 없는 것이
    // 나중, 같으면 이름순 - Storage는 계층이 아니라 각 항목이 들고만 있다.
    systems: [
      { system: "ps2", count: 2, storageId: "ext-1" },
      { system: "snes", count: 1, storageId: "internal" },
      { system: "gba", count: 0, storageId: "internal" },
    ],
  };

  /** 목업에서 이 scope가 어떤 항목을 대상으로 삼는지. 실제 백엔드와 같은 규칙이다.
   *
   * UI 테스트가 "화면에서 고른 대상 == 실제 ingest 대상"을 확인할 수 있어야 하므로,
   * 목업도 개수만이 아니라 어떤 romUid가 들어갔는지 돌려준다.
   */
  function mockIngestUids(scope) {
    const kind = (scope && scope.kind) || "all";
    if (kind === "selected") return [...((scope && scope.romUids) || [])];
    if (kind === "system") {
      return mockRows.filter((r) => r.system === scope.system).map((r) => r.romUid);
    }
    return mockRows.map((r) => r.romUid);
  }

  function mockIngestCount(scope) {
    return mockIngestUids(scope).length;
  }

  let mockLastIngest = {};
  // Storage 이동을 Plan에 올렸을 때 Navigator가 미리 보여줄 수 있는지 테스트하기
  // 위한 상태(실사용 피드백: 드래그해도 화면이 그대로면 "안 먹었다"처럼 보였다).
  const mockPendingMoves = {};
  // "실패 N" 배지를 눌렀을 때 이유를 보여주는 다이얼로그를 테스트하기 위한 상태.
  // 테스트가 window.__setMockFailedEntries()로 채운다.
  let mockFailedEntries = [];

  const mockMatchLinks = {};
  const mockFavorites = {};
  const mockUiState = {};
  // Settings 화면 값(앱 전역). 실제로는 registry의 app_settings에 들어간다.
  const mockAppSettings = {};

  const mockCompare = { on: false, takenAt: 0 };
  const mockCompareRows = [
    { key: "ps2|Same.iso", system: "ps2", file: "Same.iso", title: "Same Game",
      size: 100, status: "same", mediaDiff: false, changedFields: [] },
    { key: "ps2|Conflict.iso", system: "ps2", file: "Conflict.iso", title: "Conflict Game",
      size: 200, status: "conflict", mediaDiff: false, changedFields: ["genre"] },
    { key: "ps2|OnlyBase.iso", system: "ps2", file: "OnlyBase.iso", title: "Only Base",
      size: 300, status: "only_a", mediaDiff: false, changedFields: [] },
    { key: "ps2|OnlyOther.iso", system: "ps2", file: "OnlyOther.iso", title: "Only Other",
      size: 400, status: "only_b", mediaDiff: false, changedFields: [] },
    { key: "ps2|MediaOnly.iso", system: "ps2", file: "MediaOnly.iso", title: "Media Only",
      size: 500, status: "same", mediaDiff: true, changedFields: [] },
  ];
  const mockCompareState = () => ({
    baseId: "c1", otherId: "c2", baseName: "Master Library", otherName: "Android ES-DE",
    counts: { all: 5, same: 2, conflict: 1, only_a: 1, only_b: 1, media: 1 },
    systems: ["ps2"], takenAt: mockCompare.takenAt,
  });

  const mock = {
    list_collections: () => ok(mockCollections),
    collection_detail: () => ok(mockDetail),
    open_collection: () => ok(mockDetail),
    close_collection: () => ok(true),
    list_rows: (id, systems) => {
      const rows = systems && systems.length ? mockRows.filter((r) => systems.includes(r.system)) : mockRows;
      return ok({ rows, total: rows.length, offset: 0 });
    },
    list_uids: (id, systems) => ok((systems && systems.length
      ? mockRows.filter((r) => systems.includes(r.system)) : mockRows).map((r) => r.romUid)),
    find_row_index: (id, prefix, after, systems) => {
      const rows = systems && systems.length ? mockRows.filter((r) => systems.includes(r.system)) : mockRows;
      const needle = String(prefix || "").toLowerCase();
      for (let k = 1; k <= rows.length; k += 1) {
        const i = (Math.max(-1, after) + k) % rows.length;
        if (rows[i].file.toLowerCase().startsWith(needle)) return ok(i);
      }
      return ok(-1);
    },
    get_row: (id, romUid) => {
      const r = mockRows.find((x) => x.romUid === romUid) || mockRows[0];
      return ok({ romUid: r.romUid, system: r.system, file: r.file, size: r.size, present: true,
                  sha256: null, favorite: !!mockFavorites[r.romUid] || !!r.favorite,
                  // media가 종류별로 있는 경우와 없는 경우를 함께 보여줘야 격자 배치를
                  // 확인할 수 있다. Video/Manual은 [v]로만 표시되는 종류다.
                  media: r.hasMedia
                    ? { Covers: "pending", Screenshots: "pending", Videos: "video://exists",
                        Manuals: "pending" }
                    : {},
                  fields: { name: r.title, desc: "설명이 여기에 표시됩니다.", genre: "RPG",
                            developer: "Square", publisher: "Square Enix",
                            releasedate: "2001-07-19", region: "USA", players: "1", rating: "4.5" } });
    },
    // 1x1 투명 PNG - Media 타일이 실제로 <img src>를 채우는지(lightbox 확대 포함)
    // 목업에서도 확인할 수 있게 진짜 data URI를 준다.
    get_media_image: () => ok(
      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="),
    save_fields: (id, uid, fields) => ok({ title: fields.name || "" }),
    frontends: () => ok([
      { id: "es-de", label: "ES-DE" }, { id: "pegasus", label: "Pegasus" },
      { id: "launchbox", label: "LaunchBox" },
      { id: "emulationstation", label: "EmulationStation" },
    ]),
    adapter_actions: () => ok([{ id: "esde-custom-systems", label: "ES-DE XML 생성" }]),
    run_adapter_action: () => ok({ path: "D:\ES-DE\custom_systems\es_systems.xml",
                                  systems: ["ps2"], written: true }),
    plan_state: () => ok({
                          total: Object.keys(mockPendingMoves).length + mockFailedEntries.length,
                          added: 0, deleted: 0, moved: Object.keys(mockPendingMoves).length,
                          addedBytes: 0, deletedBytes: 0,
                          delta: {}, marks: { rows: {}, systems: Object.keys(mockPendingMoves) },
                          capacity: mockDetail.storages.map((s) => ({
                            storageId: s.id, label: s.label, actualBytes: s.actualBytes,
                            planBytes: s.actualBytes, deltaBytes: 0,
                            capacityBytes: s.capacityBytes, freeBytes: s.freeBytes,
                            over: false, overBytes: 0 })),
                          conflictEntries: [], failedEntries: mockFailedEntries,
                          failed: mockFailedEntries.length, clipboard: null,
                          pendingMoves: { ...mockPendingMoves } }),
    start_archive_ingest: (id, scope) => {
      const count = mockIngestCount(scope);
      mockLastIngest = { ingested: count, revised: count, unchanged: 0,
                         scope: (scope && scope.kind) || "all",
                         ingestedRomUids: mockIngestUids(scope) };
      return ok({ jobId: "mock-archive-ingest", scope: mockLastIngest.scope, count });
    },
    archive_ingest_preview: (id, scope) => ok({
      kind: (scope && scope.kind) || "all",
      system: scope && scope.system,
      count: mockIngestCount(scope),
    }),
    get_archive_media_image: () => ok(null),
    archive_rows: () => ok({ rows: [], total: 0, offset: 0 }),
    archive_systems: () => ok([]),
    archive_detail: () => ok(null),
    archive_edit: () => ok({ revision: 1, changed: true }),
    archive_set_preferred: (id, recordId) => ok({ romIdentityId: id, recordId }),
    archive_clear_preferred: (id) => ok({ romIdentityId: id, recordId: null }),
    archive_to_collection: () => ok({ updated: 0, planned: 0, skipped: [] }),
    plan_delete: () => ok({ deleted: 1 }),
    plan_resolve_conflict: () => ok({ resolution: "skip" }),
    plan_resolve_all_conflicts: () => ok({ resolved: 0 }),
    plan_storage_change: (id, system, storageTo) => {
      mockPendingMoves[system] = storageTo;
      return ok({ system, bytes: 0 });
    },
    plan_clear: () => ok(true),
    copy_selection: () => ok({ count: 1, bytes: 0 }),
    paste: () => ok({ added: 1, skipped: [] }),
    validate_plan: () => ok({ ok: true, entries: [], capacity: [], blocked: false }),
    start_apply: () => ok({ jobId: "mock-job" }),
    start_scan: () => ok({ jobId: "mock-job" }),
    get_job_progress: (jobId) => ok({
      current: 1, total: 1, label: "완료", done: true, error: null,
      // Archive 수집은 결과의 개수를 화면이 그대로 읽는다. 빈 객체를 주면 목업에서만
      // "undefined개 수집"이 뜬다.
      result: jobId === "mock-archive-ingest" ? { ...mockLastIngest } : {},
    }),
    cancel_job: () => ok(true),
    pick_folder: () => ok("D:\\ES-DE"),
    window_control: () => ok(true),
    window_resize: () => ok(true),

    // --- 상태를 바꾸는 호출 ---------------------------------------------
    // GUI 테스트(tests_ui/)는 pywebview 없이 이 목업 위에서 돈다. 여기 없는 이름은
    // {ok:false}로 떨어져서, 그 화면은 "검증한 것처럼 보이지만 실제로는 오류 경로만"
    // 지나간다 (tests/test_wiring.py::test_mock_covers_every_call이 누락을 감시한다).
    // 그래서 ok(true)로 때우지 않고 목업 배열을 실제로 고친다 - 그래야 "이름을 바꾸면
    // 탭 제목도 바뀐다" 같은 것을 GUI 테스트가 확인할 수 있다.
    create_collection: (name, frontend, rootPath, target, arch) => {
      const created = {
        id: "c" + (mockCollections.length + 1), name, frontend: frontend || "es-de",
        frontendLabel: frontend === "es-de" ? "ES-DE" : frontend, target: target || "windows",
        os: null, arch: arch || "x64", rootPath: rootPath || "D:\New", systemCount: 0,
      };
      mockCollections.push(created);
      return ok(created);
    },
    rename_collection: (id, name) => {
      const c = mockCollections.find((x) => x.id === id);
      if (!c) return Promise.resolve({ ok: false, error: "없는 Collection" });
      c.name = name;
      if (mockDetail.id === id) mockDetail.name = name;
      return ok(true);
    },
    update_collection_target: (id, target, arch, os) => {
      const c = mockCollections.find((x) => x.id === id);
      if (!c) return Promise.resolve({ ok: false, error: "없는 Collection" });
      Object.assign(c, { target, arch, os: os || null });
      return ok(true);
    },
    delete_collection: (id) => {
      const i = mockCollections.findIndex((x) => x.id === id);
      if (i < 0) return Promise.resolve({ ok: false, error: "없는 Collection" });
      mockCollections.splice(i, 1);
      return ok(true);
    },
    add_external_storage: (id, label, rootPath) => {
      const storage = {
        id: "ext-" + (mockDetail.storages.length + 1), kind: "external",
        label: label || "External", rootPath: rootPath || "F:\ROMs",
        actualBytes: 0, capacityBytes: 256e9, freeBytes: 256e9, systems: [],
      };
      mockDetail.storages.push(storage);
      // 실제 bridge는 **storage id 문자열**을 돌려준다(`ok(storage_id)`). 목업이 객체를
      // 돌려주면 화면이 `r.data.id`를 읽는 코드로 바뀌었을 때 테스트만 통과하고 앱에서
      // 깨진다 - 실제 데이터로 돌려 보다 발견했다.
      return ok(storage.id);
    },
    remove_storage: (id, storageId) => {
      const i = mockDetail.storages.findIndex((s) => s.id === storageId);
      if (i < 0) return Promise.resolve({ ok: false, error: "없는 Storage" });
      if (mockDetail.storages[i].kind === "internal") {
        return Promise.resolve({ ok: false, error: "Internal Storage는 제거할 수 없습니다." });
      }
      mockDetail.storages.splice(i, 1);
      return ok(true);
    },
    system_removal_preview: (id, system, force) => {
      const sys = mockDetail.systems.find((x) => x.system === system);
      if (!sys) return Promise.resolve({ ok: false, error: "없는 System" });
      return ok({
        system, games: sys.count, kept: [],
        totalFiles: 2, totalBytes: 2048,
        blockers: sys.count && !force ? [`게임이 ${sys.count}개 있습니다. 게임이 없는 System만 삭제할 수 있습니다.`] : [],
        targets: [
          { kind: "rom", path: `D:\\ES-DE\\${system}`, isDir: true, fileCount: 1,
            files: [`D:\\ES-DE\\${system}\\systeminfo.txt`] },
          { kind: "metadata", path: `D:\\ES-DE\\gamelists\\${system}`, isDir: true, fileCount: 1,
            files: [`D:\\ES-DE\\gamelists\\${system}\\gamelist.xml`] },
        ],
      });
    },
    remove_system: (id, system, force) => {
      const sys = mockDetail.systems.find((x) => x.system === system);
      if (!sys) return Promise.resolve({ ok: false, error: "없는 System" });
      if (sys.count && !force) return Promise.resolve({ ok: false, error: "게임이 있는 System은 삭제할 수 없습니다." });
      mockDetail.systems = mockDetail.systems.filter((x) => x.system !== system);
      for (const s of mockDetail.storages) s.systems = s.systems.filter((x) => x.system !== system);
      mockDetail.systemCount = mockDetail.systems.length;
      for (let i = mockRows.length - 1; i >= 0; i -= 1) if (mockRows[i].system === system) mockRows.splice(i, 1);
      mockDetail.totalGames = mockRows.length;
      return ok({ system, removed: [], kept: [] });
    },
    window_set_bounds: () => ok(true),
    open_system_folder: (id, system, kind) => ok({ path: `D:\\ES-DE\\${kind}\\${system}` }),
    move_system: (id, system, storageId) => {
      for (const s of mockDetail.storages) s.systems = s.systems.filter((x) => x.system !== system);
      const target = mockDetail.storages.find((s) => s.id === storageId);
      if (!target) return Promise.resolve({ ok: false, error: "없는 Storage" });
      target.systems.push({ system, count: mockRows.filter((r) => r.system === system).length });
      mockRows.forEach((r) => { if (r.system === system) r.storageId = storageId; });
      return ok(true);
    },
    plan_remove_entry: (id, key) => {
      mockFailedEntries = mockFailedEntries.filter((e) => e.key !== key);
      return ok({ removed: 1 });
    },

    // Convert(§53). 미리보기는 "무엇을 잃는지"까지 말해야 의미가 있다.
    metadata_status: () => ok({
      systems: [{ system: "snes", hasMetadata: false, roms: 2 },
                { system: "gba", hasMetadata: false, roms: 1 }],
      missing: ["snes", "gba"], roms: 3,
    }),
    generate_metadata: () => ok({
      created: [{ system: "snes", games: 2 }, { system: "gba", games: 1 }], skipped: [],
    }),
    convert_preview: () => ok({
      sourceId: "c1", sourceName: "Master Library", sourceFrontend: "ES-DE",
      targetId: "c2", targetName: "Android ES-DE", targetFrontend: "Pegasus",
      games: 1284, metadata: 1284, media: 4821, droppedMedia: 96,
      unsupportedFields: 37, unsupportedFieldNames: ["region"],
      frontendSpecific: 112, systems: ["ps2", "snes"],
    }),
    start_convert: () => ok({ added: 1284, conflicts: 0, skipped: [] }),

    // Compare(§54-59). 목업은 상태를 들고 있다가 필터에 반응한다 - 필터 버튼이
    // 실제로 목록을 바꾸는지까지 GUI 테스트로 확인할 수 있어야 하기 때문이다.
    start_compare: (baseId, otherId) => {
      mockCompare.on = true;
      mockCompare.takenAt = Date.now() / 1000;
      return ok(mockCompareState());
    },
    compare_state: () => ok(mockCompare.on ? mockCompareState() : null),
    compare_rows: (status) => {
      if (!mockCompare.on) return Promise.resolve({ ok: false, error: "Compare Mode가 아닙니다." });
      const rows = mockCompareRows.filter((r) =>
        !status || status === "all" ? true : status === "media" ? r.mediaDiff : r.status === status);
      return ok({ rows, total: rows.length, offset: 0 });
    },
    compare_detail: (key) => {
      const row = mockCompareRows.find((r) => r.key === key) || mockCompareRows[0];
      const has = (side) => side === "left" ? row.status !== "only_b" : row.status !== "only_a";
      const side = (name, genre, size) => has(name) ? {
        romUid: 1, filename: row.file, title: row.title, size, present: true,
        mediaTypes: ["covers"], fields: { name: row.title, genre, desc: "설명" },
      } : null;
      return ok({
        key: row.key, system: row.system, file: row.file, status: row.status,
        changedFields: row.changedFields, mediaDiff: row.mediaDiff,
        baseName: "Master Library", otherName: "Android ES-DE",
        left: side("left", "RPG", row.size),
        right: side("right", row.changedFields.length ? "Action" : "RPG",
                    row.changedFields.length ? row.size + 50 : row.size),
      });
    },
    exit_compare: () => { mockCompare.on = false; return ok(true); },

    // Match(§45-49). 자동으로 붙는 것은 Exact뿐이라는 규칙을 목업에서도 지킨다 -
    // 여기서 autoMatch를 채워버리면 화면 쪽 "사용자가 골라야 한다"를 검증할 수 없다.
    match_counts: () => ok({ 2: 2 }),
    match_candidates: (id, romUid) => ok({
      source: { system: "ps2", filename: "MGS2.iso", title: "Metal Gear Solid 2", size: 4300000000 },
      candidates: [
        { romIdentityId: "ri-1", filename: "Metal Gear Solid 2 (Japan).iso",
          title: "Metal Gear Solid 2", region: "Japan", size: 4300000001,
          tier: "normalized", score: 85, linked: false,
          evidence: ["정규화 파일명 일치", "크기 다름"] },
        { romIdentityId: "ri-2", filename: "Metal Gear Solid 2 Substance.iso",
          title: "Metal Gear Solid 2: Substance", region: "USA", size: 4500000000,
          tier: "heuristic", score: 71.4, linked: false,
          evidence: ["제목 27점", "파일명 12점"] },
      ],
      linkedRomIdentityId: mockMatchLinks[romUid] || null,
      autoMatch: null,
    }),
    apply_match: (id, romUid, romIdentityId) => {
      mockMatchLinks[romUid] = romIdentityId;
      return ok({ romIdentityId, tier: "normalized", score: 85, manual: false });
    },
    clear_match: (id, romUid) => {
      const had = !!mockMatchLinks[romUid];
      delete mockMatchLinks[romUid];
      return ok({ cleared: had });
    },

    // 즐겨찾기와 화면 상태. 목업은 메모리에만 담는다 - GUI 테스트가 "눌렀을 때
    // 화면이 어떻게 되는가"를 보는 데는 그것으로 충분하고, 실제 파일에 적히는지는
    // tests_e2e가 실제 Api로 확인한다.
    set_favorite: (id, romUid, on) => {
      mockFavorites[romUid] = !!on;
      return ok({ romUid, favorite: !!on });
    },
    dashboard_stats: () => ok({
      collectionId: "c1", collectionName: mockDetail.name,
      totals: { games: 3, romCount: 3, romBytes: 8700524288, mediaCount: 4, mediaBytes: 3200000 },
      storages: [
        { id: "internal", label: "Internal", kind: "internal", romCount: 1, romBytes: 524288,
          mediaCount: 4, mediaBytes: 3200000, capacityBytes: 512e9, freeBytes: 200e9 },
        { id: "ext-1", label: "External SD", kind: "external", romCount: 2, romBytes: 8700000000,
          mediaCount: 0, mediaBytes: 0, capacityBytes: 512e9, freeBytes: 90e9 },
      ],
      systems: [
        { system: "ps2", storageId: "ext-1", mediaStorageId: "internal", games: 2, romCount: 2,
          romBytes: 8700000000, mediaCount: 3, mediaBytes: 3000000, missingMetadata: 0, missingMedia: 1 },
        { system: "snes", storageId: "internal", mediaStorageId: "internal", games: 1, romCount: 1,
          romBytes: 524288, mediaCount: 1, mediaBytes: 200000, missingMetadata: 1, missingMedia: 0 },
        { system: "gba", storageId: "internal", mediaStorageId: "internal", games: 0, romCount: 0,
          romBytes: 0, mediaCount: 0, mediaBytes: 0, missingMetadata: 0, missingMedia: 0 },
      ],
      health: { total: 3, present: 3, metadata: 2, media: 2, description: 2, cover: 1, complete: 1,
                missingRom: 0, missingMetadata: 1, missingMedia: 1, missingDescription: 1, missingCover: 2 },
    }),
    validate_collection: () => ok({ checked: 2, invalid: [] }),
    get_app_settings: () => ok(JSON.parse(JSON.stringify(mockAppSettings))),
    save_app_settings: (patch) => {
      Object.entries(patch || {}).forEach(([section, value]) => {
        mockAppSettings[section] = (value && typeof value === "object" && !Array.isArray(value))
          ? { ...(mockAppSettings[section] || {}), ...value } : value;
      });
      return ok(JSON.parse(JSON.stringify(mockAppSettings)));
    },
    get_ui_state: (id) => ok({ ...mockUiState }),
    save_ui_state: (id, state) => {
      Object.assign(mockUiState, state || {});
      return ok({ ...mockUiState });
    },
  };

  // E2E 테스트용 전송. `?bridge=http`로 열면 목업 대신 **실제 파이썬 Api**에
  // HTTP로 붙는다. 목업은 우리가 손으로 적은 모양이라 실제 반환과 어긋날 수 있고,
  // 무엇보다 실제 파일을 건드리지 않는다 - "화면이 성공이라고 말한 것"과 "실제로
  // 파일이 그렇게 됐는가"는 목업 위에서는 영원히 구별되지 않는다.
  //
  // 실제 앱에는 pywebview가 있으므로 이 경로를 타지 않는다.
  const httpBridge = () =>
    typeof location !== "undefined" && /[?&]bridge=http(&|$)/.test(location.search);

  function callHttp(name, args) {
    return fetch(`/__api/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    })
      .then((r) => r.json())
      .catch((e) => ({ ok: false, error: String(e) }));
  }

  function call(name, ...args) {
    if (!hasBridge()) {
      if (httpBridge()) return callHttp(name, args);
      const fn = mock[name];
      return fn ? fn(...args) : Promise.resolve({ ok: false, error: `목업에 없는 호출: ${name}` });
    }
    const fn = window.pywebview.api[name];
    if (!fn) return Promise.resolve({ ok: false, error: `브릿지에 없는 호출: ${name}` });
    return Promise.resolve(fn(...args)).catch((e) => ({ ok: false, error: String(e) }));
  }

  window.api = {
    isMock: () => !hasBridge() && !httpBridge(),
    // 테스트 전용 - "실패 N" 배지/다이얼로그를 목업으로 확인하기 위한 훅.
    __setMockFailedEntries: (entries) => { mockFailedEntries = entries || []; },

    listCollections: () => call("list_collections"),
    createCollection: (name, frontend, rootPath, target, arch, romPath, mediaPath) =>
      call("create_collection", name, frontend, rootPath, target, arch,
           romPath || null, mediaPath || null),
    renameCollection: (id, name) => call("rename_collection", id, name),
    updateCollectionTarget: (id, target, arch, os) => call("update_collection_target", id, target, arch, os),
    deleteCollection: (id) => call("delete_collection", id),
    openCollection: (id) => call("open_collection", id),
    closeCollection: (id) => call("close_collection", id),
    collectionDetail: (id) => call("collection_detail", id),

    addExternalStorage: (id, label, rootPath) => call("add_external_storage", id, label, rootPath),
    removeStorage: (id, storageId) => call("remove_storage", id, storageId),
    moveSystem: (id, system, storageId) => call("move_system", id, system, storageId),
    systemRemovalPreview: (id, system, force) => call("system_removal_preview", id, system, !!force),
    removeSystem: (id, system, force) => call("remove_system", id, system, !!force),
    openSystemFolder: (id, system, kind) => call("open_system_folder", id, system, kind),

    listRows: (id, q) => call("list_rows", id, q.systems || null, q.storageIds || null,
                              q.search || null, q.order || "title", !!q.descending,
                              q.limit || 200, q.offset || 0, !!q.favoritesOnly),
    // 목록 전체 기준 동작(Ctrl+A, 영문키 점프). 인자 순서는 listRows와 같다.
    listUids: (id, q) => call("list_uids", id, q.systems || null, q.storageIds || null,
                              q.search || null, q.order || "title", !!q.descending, !!q.favoritesOnly),
    findRowIndex: (id, q, prefix, after) => call("find_row_index", id, prefix, after,
                              q.systems || null, q.storageIds || null, q.search || null,
                              q.order || "title", !!q.descending, !!q.favoritesOnly),
    setFavorite: (id, romUid, on) => call("set_favorite", id, romUid, !!on),
    dashboardStats: (id) => call("dashboard_stats", id),
    validateCollection: (id) => call("validate_collection", id),
    getAppSettings: () => call("get_app_settings"),
    saveAppSettings: (patch) => call("save_app_settings", patch),
    getUiState: (id) => call("get_ui_state", id),
    saveUiState: (id, state) => call("save_ui_state", id, state),
    getRow: (id, romUid) => call("get_row", id, romUid),
    getMediaImage: (id, romUid, label, thumbnail) => call("get_media_image", id, romUid, label, !!thumbnail),
    saveFields: (id, romUid, fields) => call("save_fields", id, romUid, fields),

    planState: (id) => call("plan_state", id),
    planDelete: (id, romUids) => call("plan_delete", id, romUids),
    planStorageChange: (id, system, storageId) => call("plan_storage_change", id, system, storageId),
    planRemoveEntry: (id, key) => call("plan_remove_entry", id, key),
    planResolveConflict: (id, key, resolution) => call("plan_resolve_conflict", id, key, resolution),
    planResolveAllConflicts: (id, resolution) => call("plan_resolve_all_conflicts", id, resolution),
    planClear: (id) => call("plan_clear", id),
    copySelection: (id, romUids) => call("copy_selection", id, romUids),
    paste: (id) => call("paste", id),
    validatePlan: (id) => call("validate_plan", id),
    startApply: (id) => call("start_apply", id),

    // 대상은 **scope로만** 정한다. 예전에는 선택이 없으면 null을 보냈고 백엔드가
    // 그것을 "Collection 전체"로 해석해서, System 하나만 보고 있던 사용자가 전체를
    // Archive에 넣게 되었다.
    startArchiveIngest: (id, scope) => call("start_archive_ingest", id, scope),
    archiveIngestPreview: (id, scope) => call("archive_ingest_preview", id, scope),
    getArchiveMediaImage: (romIdentityId, label, thumbnail) =>
      call("get_archive_media_image", romIdentityId, label, !!thumbnail),
    archiveRows: (q) => call("archive_rows", q.search || null, q.systems || null,
                             q.limit || 200, q.offset || 0),
    archiveSystems: () => call("archive_systems"),
    archiveDetail: (romIdentityId) => call("archive_detail", romIdentityId),
    archiveEdit: (romIdentityId, fields) => call("archive_edit", romIdentityId, fields),
    archiveSetPreferred: (romIdentityId, recordId) =>
      call("archive_set_preferred", romIdentityId, recordId),
    archiveClearPreferred: (romIdentityId) =>
      call("archive_clear_preferred", romIdentityId),
    archiveToCollection: (id, ids) => call("archive_to_collection", id, ids),

    matchCandidates: (id, romUid) => call("match_candidates", id, romUid),
    matchCounts: (id, romUids) => call("match_counts", id, romUids),
    applyMatch: (id, romUid, romIdentityId) => call("apply_match", id, romUid, romIdentityId),
    clearMatch: (id, romUid) => call("clear_match", id, romUid),

    metadataStatus: (id) => call("metadata_status", id),
    generateMetadata: (id, systems) => call("generate_metadata", id, systems || null),

    convertPreview: (sourceId, targetId) => call("convert_preview", sourceId, targetId),
    startConvert: (sourceId, targetId) => call("start_convert", sourceId, targetId),

    startCompare: (baseId, otherId) => call("start_compare", baseId, otherId),
    compareState: () => call("compare_state"),
    compareRows: (q) => call("compare_rows", q.status || null, q.systems || null,
                             q.search || null, q.limit || 200, q.offset || 0),
    compareDetail: (key) => call("compare_detail", key),
    exitCompare: () => call("exit_compare"),

    startScan: (id, force) => call("start_scan", id, !!force),
    jobProgress: (jobId) => call("get_job_progress", jobId),
    cancelJob: (jobId) => call("cancel_job", jobId),

    frontends: () => call("frontends"),
    adapterActions: (id) => call("adapter_actions", id),
    runAdapterAction: (id, actionId) => call("run_adapter_action", id, actionId),
    pickFolder: (title) => call("pick_folder", title || ""),
    windowControl: (action) => call("window_control", action),
    windowSetBounds: (x, y, width, height) => call("window_set_bounds", x, y, width, height),
    windowResize: (width, height) => call("window_resize", width, height),
  };
})();
