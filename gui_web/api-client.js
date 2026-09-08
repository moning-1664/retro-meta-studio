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
      storageId: "ext-1", hasMetadata: true, hasMedia: true, present: true },
    { romUid: 2, system: "ps2", file: "MGS2.iso", title: "Metal Gear Solid 2", size: 4300000000,
      storageId: "ext-1", hasMetadata: true, hasMedia: false, present: true },
    { romUid: 3, system: "snes", file: "SMW.sfc", title: "Super Mario World", size: 524288,
      storageId: "internal", hasMetadata: false, hasMedia: false, present: true },
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
  };

  const mockMatchLinks = {};

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
    get_row: (id, romUid) => {
      const r = mockRows.find((x) => x.romUid === romUid) || mockRows[0];
      return ok({ romUid: r.romUid, system: r.system, file: r.file, size: r.size, present: true,
                  sha256: null, media: r.hasMedia ? { Covers: "pending" } : {},
                  fields: { name: r.title, desc: "설명이 여기에 표시됩니다.", genre: "RPG",
                            developer: "Square", publisher: "Square Enix",
                            releasedate: "2001-07-19", region: "USA", players: "1", rating: "4.5" } });
    },
    get_media_image: () => ok(null),
    save_fields: (id, uid, fields) => ok({ title: fields.name || "" }),
    frontends: () => ok([
      { id: "es-de", label: "ES-DE" }, { id: "pegasus", label: "Pegasus" },
      { id: "launchbox", label: "LaunchBox" },
      { id: "emulationstation", label: "EmulationStation" },
    ]),
    adapter_actions: () => ok([{ id: "esde-custom-systems", label: "ES-DE XML 생성" }]),
    run_adapter_action: () => ok({ path: "D:\ES-DE\custom_systems\es_systems.xml",
                                  systems: ["ps2"], written: true }),
    plan_state: () => ok({ total: 0, added: 0, deleted: 0, moved: 0, addedBytes: 0, deletedBytes: 0,
                          delta: {}, marks: { rows: {}, systems: [] },
                          capacity: mockDetail.storages.map((s) => ({
                            storageId: s.id, label: s.label, actualBytes: s.actualBytes,
                            planBytes: s.actualBytes, deltaBytes: 0,
                            capacityBytes: s.capacityBytes, freeBytes: s.freeBytes,
                            over: false, overBytes: 0 })),
                          conflictEntries: [], failedEntries: [], clipboard: null }),
    archive_ingest: () => ok({ ingested: 0, revised: 0, unchanged: 0 }),
    archive_rows: () => ok({ rows: [], total: 0, offset: 0 }),
    archive_systems: () => ok([]),
    archive_detail: () => ok(null),
    archive_edit: () => ok({ revision: 1, changed: true }),
    archive_to_collection: () => ok({ updated: 0, planned: 0, skipped: [] }),
    plan_delete: () => ok({ deleted: 1 }),
    plan_resolve_conflict: () => ok({ resolution: "skip" }),
    plan_resolve_all_conflicts: () => ok({ resolved: 0 }),
    plan_storage_change: () => ok({ system: "ps2", bytes: 0 }),
    plan_clear: () => ok(true),
    copy_selection: () => ok({ count: 1, bytes: 0 }),
    paste: () => ok({ added: 1, skipped: [] }),
    validate_plan: () => ok({ ok: true, entries: [], capacity: [], blocked: false }),
    start_apply: () => ok({ jobId: "mock-job" }),
    start_scan: () => ok({ jobId: "mock-job" }),
    get_job_progress: () => ok({ current: 1, total: 1, label: "완료", done: true, result: {}, error: null }),
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
    move_system: (id, system, storageId) => {
      for (const s of mockDetail.storages) s.systems = s.systems.filter((x) => x.system !== system);
      const target = mockDetail.storages.find((s) => s.id === storageId);
      if (!target) return Promise.resolve({ ok: false, error: "없는 Storage" });
      target.systems.push({ system, count: mockRows.filter((r) => r.system === system).length });
      mockRows.forEach((r) => { if (r.system === system) r.storageId = storageId; });
      return ok(true);
    },
    plan_remove_entry: () => ok({ removed: 1 }),

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

    listCollections: () => call("list_collections"),
    createCollection: (name, frontend, rootPath, target, arch) =>
      call("create_collection", name, frontend, rootPath, target, arch),
    renameCollection: (id, name) => call("rename_collection", id, name),
    updateCollectionTarget: (id, target, arch, os) => call("update_collection_target", id, target, arch, os),
    deleteCollection: (id) => call("delete_collection", id),
    openCollection: (id) => call("open_collection", id),
    closeCollection: (id) => call("close_collection", id),
    collectionDetail: (id) => call("collection_detail", id),

    addExternalStorage: (id, label, rootPath) => call("add_external_storage", id, label, rootPath),
    removeStorage: (id, storageId) => call("remove_storage", id, storageId),
    moveSystem: (id, system, storageId) => call("move_system", id, system, storageId),

    listRows: (id, q) => call("list_rows", id, q.systems || null, q.storageIds || null,
                              q.search || null, q.order || "title", !!q.descending,
                              q.limit || 200, q.offset || 0),
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

    archiveIngest: (id, romUids) => call("archive_ingest", id, romUids || null),
    archiveRows: (q) => call("archive_rows", q.search || null, q.systems || null,
                             q.limit || 200, q.offset || 0),
    archiveSystems: () => call("archive_systems"),
    archiveDetail: (romIdentityId) => call("archive_detail", romIdentityId),
    archiveEdit: (romIdentityId, fields) => call("archive_edit", romIdentityId, fields),
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
    windowResize: (width, height) => call("window_resize", width, height),
  };
})();
