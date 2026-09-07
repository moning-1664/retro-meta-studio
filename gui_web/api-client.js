/* ==========================================================================
   api-client.js
   window.pywebview.api를 감싸는 얇은 래퍼.
   - pywebview 환경(실제 앱)에서는 진짜 Python 백엔드를 호출한다.
   - 브라우저에서 index.html을 직접 열어 UI만 미리 볼 때는(pywebview 없음)
     인메모리 목업 데이터로 자동 폴백한다 (개발/디자인 검토용, 실제 배포판에서는
     항상 pywebview가 있으므로 이 목업 경로는 타지 않는다).
   ========================================================================== */

(function () {
  const hasBridge = () => typeof window.pywebview !== "undefined" && window.pywebview.api;

  function ok(data) { return Promise.resolve({ ok: true, data }); }
  function err(message) { return Promise.resolve({ ok: false, error: message }); }

  // ------------------------------------------------------------------
  // 목업 모드 (pywebview 없을 때만 사용) - api.py와 동일한 반환 형태를 흉내낸다.
  // ------------------------------------------------------------------
  const mock = {
    locals: [
      { id: "l1", label: "Local 1", frontend: "es-de", frontendLabel: "ES-DE", romPath: "D:\\Roms\\ES-DE\\", romCount: 3, status: "정상" },
      // [신규] Compare 리뷰 대응 테스트용 - 소스가 masterdb/l1 두 개뿐이면 "소스를
      // 바꿨을 때 System 필터가 무효화될 수 있음" 같은 시나리오를 재현할 수 없다.
      // snes가 아예 없는 소스(genesis만)를 하나 더 둬서 그 케이스를 검증한다.
      { id: "l2", label: "Local 2", frontend: "es-de", frontendLabel: "ES-DE", romPath: "D:\\Roms\\ES-DE2\\", romCount: 1, status: "정상" },
    ],
    masterdbRoot: "D:\\RetroMetadata\\MasterDB",
    games: [
      { romKey: "snes|Super Mario World.zip", system: "snes", file: "Super Mario World.zip", title: "Super Mario World", desc: "마리오가 요시와 함께 떠나는 최고의 모험.", genre: "Platform", status: "완료", local: "l1", missingMedia: false },
      { romKey: "snes|Zelda.zip", system: "snes", file: "Zelda.zip", title: "The Legend of Zelda", desc: "링크는 하이랄을 구해야 한다.", genre: "Action RPG", status: "부분", local: "l1", missingMedia: true },
      { romKey: "snes|Zelda (Alt).zip", system: "snes", file: "Zelda (Alt).zip", title: "The Legend of Zelda", desc: "링크는 하이랄을 구해야 한다. (대체판)", genre: "Action RPG", status: "부분", local: "l1", missingMedia: true },
      { romKey: "snes|Unknown.zip", system: "snes", file: "Unknown.zip", title: "", desc: "", genre: "", status: "누락", local: "l1", missingMedia: true },
    ],
    versions: {},
    settings: { lang: "ko", theme: "dark", saveInterval: 5, exportOptions: { korean_only_on_conflict: true, copy_media: true, copy_video: true, force_overwrite: false }, deferVideoMedia: true },
    backups: [],
    // [단위 8] 시스템별 유사롬 그룹 목업 - "Zelda.zip"/"Zelda (Alt).zip"이 이미 한 그룹으로 묶여있다고 가정.
    similarGroups: {
      snes: [{ groupId: 1, representative: "snes|Zelda.zip", members: [
        { romKey: "snes|Zelda.zip", title: "The Legend of Zelda", file: "Zelda.zip" },
        { romKey: "snes|Zelda (Alt).zip", title: "The Legend of Zelda", file: "Zelda (Alt).zip" },
      ] }],
    },
  };

  function mockDetail(romKey) {
    const g = mock.games.find((x) => x.romKey === romKey);
    if (!g) return null;
    if (!mock.versions[romKey]) {
      mock.versions[romKey] = [{
        id: "v1", label: "v1 (Default)", isDefault: true, source: g.local,
        fields: { name: g.title, desc: g.desc, genre: g.genre, developer: "", publisher: "", releasedate: "", region: "", players: "", rating: "" },
      }];
    }
    // [신규] sha256 - 하나만 캐시된 것으로 목업해서 "계산됨"/"계산 안 됨" 둘 다
    // Playwright에서 검증할 수 있게 한다(다른 롬은 캐시 없는 실사용 케이스를 흉내냄).
    const sha256 = romKey === "snes|Super Mario World.zip"
      ? "3ab7f1c9d4e2b6a05f8c1d9e2b4a6c8f0d1e3b5a7c9f1d3e5b7a9c1d3e5f7a9b"
      : null;
    return { romKey, system: g.system, file: g.file, versions: mock.versions[romKey], media: {}, sha256 };
  }

  const RMApi = {
    _mockMode: !hasBridge(),
    // [설정] Settings > General > Logging에서 켜면 모든 브릿지 호출을 콘솔에 남긴다.
    _loggingEnabled: false,

    _call(name, args) {
      if (this._loggingEnabled) console.debug("[api]", name, args);
      const resultPromise = hasBridge() ? window.pywebview.api[name](...args) : this._mockCall(name, args);
      if (this._loggingEnabled) {
        Promise.resolve(resultPromise).then((r) => console.debug("[api]", name, "->", r));
      }
      return resultPromise;
    },

    _mockCall(name, args) {
      switch (name) {
        case "list_locals": return ok(mock.locals);
        case "get_masterdb_info": return ok({ configured: true, root: mock.masterdbRoot, status: "정상", romCount: mock.games.length });
        case "list_masterdb_games": return ok(mock.games);
        case "scan_local": return ok({ stats: {}, status: "정상", games: mock.games, notImplemented: false });
        // [체감 속도, Scan 2단계] 1단계(job1)는 partial/followUpJobId가 붙은 결과를,
        // 2단계(job2, get_job_progress에서 job1이 조용히 이어붙임)는 최종 결과를
        // 낸다 - 진짜 2단계 흐름(runScanJobWithProgress의 followUpJobId 폴링)을
        // Playwright에서도 실제로 재현하기 위함.
        case "start_scan_local": return ok({ jobId: "mock-scan-job-1" });
        // [체감 속도, Export 3단계] "Export to GameListSet"/"Import from ArchiveDB"도
        // 커버->기타미디어->비디오 3단계로 나뉜다 - 진행률 바가 followUpJobId를 따라
        // (1/3)->(2/3)->(3/3)으로 실제로 이어지는지 Playwright에서도 재현한다.
        case "start_export_to_local": return ok({ jobId: "mock-export-job-1" });
        case "start_export_local_to_masterdb": return ok({ jobId: "mock-import-job-1" });
        case "get_job_progress": {
          const jobId = args[0];
          if (jobId === "mock-scan-job-1") {
            const partialGames = mock.games.map((g) => ({ ...g, mediaPending: true, status: "부분" }));
            return ok({ current: 1, total: 1, label: "(1/2) 메타데이터+커버: 완료", done: true,
              result: { stats: {}, status: "정상", games: partialGames, notImplemented: false, partial: true, followUpJobId: "mock-scan-job-2" }, error: null });
          }
          if (jobId === "mock-scan-job-2") {
            return ok({ current: 1, total: 1, label: "(2/2) 나머지 미디어: 완료", done: true,
              result: { stats: {}, status: "정상", games: mock.games, notImplemented: false }, error: null });
          }
          const exportChain = { "mock-export-job-1": "mock-export-job-2", "mock-export-job-2": "mock-export-job-3",
            "mock-import-job-1": "mock-import-job-2", "mock-import-job-2": "mock-import-job-3" };
          const exportLabels = { "mock-export-job-1": "(1/3) 메타데이터+커버", "mock-export-job-2": "(2/3) 기타 미디어",
            "mock-import-job-1": "(1/3) 메타데이터+커버", "mock-import-job-2": "(2/3) 기타 미디어" };
          if (exportChain[jobId]) {
            return ok({ current: 1, total: 1, label: `${exportLabels[jobId]}: 완료`, done: true,
              result: { stats: {}, status: "정상", games: mock.games, notImplemented: false, exported: 1, followUpJobId: exportChain[jobId] }, error: null });
          }
          if (jobId === "mock-export-job-3" || jobId === "mock-import-job-3") {
            return ok({ current: 1, total: 1, label: "(3/3) 비디오: 완료", done: true,
              result: { stats: {}, status: "정상", games: mock.games, notImplemented: false, exported: 1 }, error: null });
          }
          return ok({ current: 1, total: 1, label: "", done: true,
            // [수정] scan_local과 export류 job이 이 mock 하나를 같이 쓴다 - job 종류를
            // 구분 안 하니 양쪽 소비자가 다 읽을 수 있게 필드를 합쳐서 반환한다
            // (exported는 Import/Export 다이얼로그가 완료 토스트에 쓰는 값).
            result: { stats: {}, status: "정상", games: mock.games, notImplemented: false, exported: 1 }, error: null });
        }
        case "cancel_job": return ok(true);
        case "get_game_detail": return ok(mockDetail(args[0]));
        case "get_local_game_detail": return ok({ ...mockDetail(args[1]), readOnly: true });
        case "get_local_cover_thumbnail": return ok(null);
        case "get_cover_thumbnail": return ok(null);
        case "get_settings": return ok(mock.settings);
        case "get_version": return ok("0.4.0-mock");
        case "list_backups": return ok(mock.backups);
        case "get_dashboard_stats": return ok({ romCount: mock.games.length, missingRom: 1, missingMedia: 1, systems: [{ system: "snes", romCount: mock.games.length, mediaCount: 1, missing: 1 }] });
        case "list_compare_sources": return ok([{ id: "masterdb", label: "ArchiveDB" }, { id: "l1", label: "Local 1" }, { id: "l2", label: "Local 2" }]);
        case "compare_sources": {
          const [srcA, srcB] = args;
          // [신규] l2는 snes가 전혀 없고 genesis 하나뿐 - System 필터 무효화(리뷰
          // 항목 2)와 diff 행 hover 복사(리뷰 항목 3) 테스트가 이 조합을 쓴다.
          if (srcA === "l2" || srcB === "l2") {
            return ok([
              { system: "genesis", file: "Sonic.zip", matched: true, diff: true,
                left: { system: "genesis", filename: "Sonic.zip", title: "Sonic the Hedgehog (Left)", releasedate: "", korean: false },
                right: { system: "genesis", filename: "Sonic.zip", title: "Sonic the Hedgehog (Right)", releasedate: "", korean: false } },
            ]);
          }
          // [SHA256 Compare 컬럼] Mario는 양쪽 다 hash 캐시가 있는 것으로,
          // Zelda(왼쪽만 있음)는 아직 캐시가 없는 것으로 목업해서 "10자로 잘림"과
          // "-" 표시를 둘 다 테스트할 수 있게 한다.
          return ok([
            { system: "snes", file: "Super Mario World.zip", matched: true, diff: false,
              left: { system: "snes", filename: "Super Mario World.zip", title: "Super Mario World", releasedate: "", korean: false, sha256: "A3F91C82E7B4D65091AA2FDC5E6B7A8901234567890ABCDEF1234567890ABCD" },
              right: { system: "snes", filename: "Super Mario World.zip", title: "Super Mario World", releasedate: "", korean: false, sha256: "A3F91C82E7B4D65091AA2FDC5E6B7A8901234567890ABCDEF1234567890ABCD" } },
            { system: "snes", file: "Zelda.zip", matched: false, diff: false,
              left: { system: "snes", filename: "Zelda.zip", title: "The Legend of Zelda", releasedate: "", korean: false, sha256: null },
              right: null },
          ]);
        }
        case "compare_copy_row": return ok(true);
        case "compare_copy_rows": {
          const [, , , items] = args;
          return ok({ copied: items.length, total: items.length, failed: [] });
        }
        case "delete_masterdb_games": {
          const [romKeys, deleteMetadata, deleteRom] = args;
          const favoriteSkipped = romKeys.filter((k) => mock.games.find((g) => g.romKey === k && g.favorite)).length;
          const toDelete = romKeys.filter((k) => !mock.games.find((g) => g.romKey === k && g.favorite));
          if (deleteMetadata || deleteRom) mock.games = mock.games.filter((g) => !toDelete.includes(g.romKey));
          return ok({ deleted: toDelete.length, favoriteSkipped, errors: [] });
        }
        case "set_rom_favorite": {
          const [romKey, favorite] = args;
          const g = mock.games.find((x) => x.romKey === romKey);
          if (!g) return err("게임을 찾을 수 없습니다.");
          g.favorite = !!favorite;
          return ok({ romKey, favorite: g.favorite });
        }
        case "rename_masterdb_rom": {
          const [romKey, newFilename] = args;
          const g = mock.games.find((x) => x.romKey === romKey);
          if (!g) return err("게임을 찾을 수 없습니다.");
          if (mock.games.some((x) => x.romKey !== romKey && x.file === newFilename)) return err(`'${newFilename}' 이름의 ROM이 이미 존재합니다.`);
          const newKey = `${g.system}|${newFilename}`;
          g.file = newFilename; g.romKey = newKey;
          return ok({ romKey: newKey, filename: newFilename });
        }
        case "get_similar_rom_groups": return ok(mock.similarGroups[args[0]] || []);
        case "set_similar_group_representative": {
          const [groupId, romKey] = args;
          for (const groups of Object.values(mock.similarGroups)) {
            const g = groups.find((x) => x.groupId === groupId);
            if (g) { g.representative = romKey || null; return ok(true); }
          }
          return err("그룹을 찾을 수 없습니다.");
        }
        default:
          console.warn("[mock] 미구현 목업 호출:", name, args);
          return ok(true);
      }
    },

    pickFolder: (title) => RMApi._call("pick_folder", [title || ""]),
    getMasterdbInfo: () => RMApi._call("get_masterdb_info", []),
    setMasterdbPath: (path) => RMApi._call("set_masterdb_path", [path]),
    listLocals: () => RMApi._call("list_locals", []),
    checkLocalStructure: (romPath, metaPath, frontend) => RMApi._call("check_local_structure", [romPath, metaPath, frontend]),
    addLocal: (label, frontend, romPath, metaPath) => RMApi._call("add_local", [label, frontend, romPath, metaPath]),
    updateLocalPaths: (localId, romPath, metaPath) => RMApi._call("update_local_paths", [localId, romPath, metaPath]),
    deleteLocal: (localId) => RMApi._call("delete_local", [localId]),
    setLocalTargetCapacity: (localId, targetCapacityBytes) => RMApi._call("set_local_target_capacity", [localId, targetCapacityBytes]),
    scanLocal: (localId) => RMApi._call("scan_local", [localId]),
    resetMetadata: (localId) => RMApi._call("reset_metadata", [localId]),
    orphanCleanup: (localId) => RMApi._call("orphan_cleanup", [localId]),
    importLocalToMasterdb: (localId) => RMApi._call("import_local_to_masterdb", [localId]),
    startImportLocalToMasterdb: (localId, targetRomKeys) => RMApi._call("start_import_local_to_masterdb", [localId, targetRomKeys || null]),
    copyMasterdbGameData: (sourceKey, targetKey) => RMApi._call("copy_masterdb_game_data", [sourceKey, targetKey]),
    setRomFavorite: (romKey, favorite) => RMApi._call("set_rom_favorite", [romKey, favorite]),
    renameMasterdbRom: (romKey, newFilename) => RMApi._call("rename_masterdb_rom", [romKey, newFilename]),
    // [신규] 진행률 표시가 되는 백그라운드 job 버전
    startResetMetadata: (localId) => RMApi._call("start_reset_metadata", [localId]),
    startOrphanCleanup: (localId) => RMApi._call("start_orphan_cleanup", [localId]),
    startScanLocal: (localId) => RMApi._call("start_scan_local", [localId]),
    startExportLocalToMasterdb: (localId, mode, romKeys, mediaTypes) => RMApi._call("start_export_local_to_masterdb", [localId, mode, romKeys || null, mediaTypes || null]),
    checkExportDiskSpace: (localId, mode, romKeys) => RMApi._call("check_export_disk_space", [localId, mode, romKeys || null]),
    getJobProgress: (jobId) => RMApi._call("get_job_progress", [jobId]),
    cancelJob: (jobId) => RMApi._call("cancel_job", [jobId]),
    listMasterdbGames: () => RMApi._call("list_masterdb_games", []),
    getDashboardStats: (scope, fast) => RMApi._call("get_dashboard_stats", [scope, !!fast]),
    getHealthInfo: () => RMApi._call("get_health_info", []),
    deleteLocalGames: (localId, romKeys, deleteMetadata, deleteRom) => RMApi._call("delete_local_games", [localId, romKeys, deleteMetadata, deleteRom]),
    deleteMasterdbGames: (romKeys, deleteMetadata, deleteRom) => RMApi._call("delete_masterdb_games", [romKeys, deleteMetadata, deleteRom]),
    getSimilarRomSettings: () => RMApi._call("get_similar_rom_settings", []),
    saveSimilarRomSettings: (weights, threshold) => RMApi._call("save_similar_rom_settings", [weights, threshold]),
    startFindSimilarRoms: (system) => RMApi._call("start_find_similar_roms", [system]),
    getSimilarRomGroups: (system) => RMApi._call("get_similar_rom_groups", [system]),
    setSimilarGroupRepresentative: (groupId, romKey) => RMApi._call("set_similar_group_representative", [groupId, romKey || null]),
    getGameDetail: (romKey, lightweight) => RMApi._call("get_game_detail", [romKey, !!lightweight]),
    getLocalGameDetail: (localId, romKey, lightweight) => RMApi._call("get_local_game_detail", [localId, romKey, !!lightweight]),
    getGameMediaImage: (romKey, mediaType) => RMApi._call("get_game_media_image", [romKey, mediaType]),
    getLocalGameMediaImage: (localId, romKey, mediaType) => RMApi._call("get_local_game_media_image", [localId, romKey, mediaType]),
    saveLocalGameFields: (localId, romKey, fields) => RMApi._call("save_local_game_fields", [localId, romKey, fields]),
    getCoverThumbnail: (romKey) => RMApi._call("get_cover_thumbnail", [romKey]),
    getLocalCoverThumbnail: (localId, romKey) => RMApi._call("get_local_cover_thumbnail", [localId, romKey]),
    saveVersionFields: (romKey, versionId, fields) => RMApi._call("save_version_fields", [romKey, versionId, fields]),
    cloneVersion: (romKey, versionId) => RMApi._call("clone_version", [romKey, versionId]),
    setDefaultVersion: (romKey, versionId) => RMApi._call("set_default_version", [romKey, versionId]),
    deleteVersion: (romKey, versionId) => RMApi._call("delete_version", [romKey, versionId]),
    saveVersionDiff: (romKey, leftId, leftFields, rightId, rightFields) => RMApi._call("save_version_diff", [romKey, leftId, leftFields, rightId, rightFields]),
    saveMedia: (romKey, mediaType, base64Data, filename) => RMApi._call("save_media", [romKey, mediaType, base64Data, filename]),
    saveLocalMedia: (localId, romKey, mediaType, base64Data, filename) => RMApi._call("save_local_media", [localId, romKey, mediaType, base64Data, filename]),
    saveMediaFromUrl: (romKey, mediaType, url) => RMApi._call("save_media_from_url", [romKey, mediaType, url]),
    saveLocalMediaFromUrl: (localId, romKey, mediaType, url) => RMApi._call("save_local_media_from_url", [localId, romKey, mediaType, url]),
    exportToLocal: (localId, romKeys, mediaTypes, copyRom) => RMApi._call("export_to_local", [localId, romKeys || null, mediaTypes || null, !!copyRom]),
    startExportToLocal: (localId, romKeys, mediaTypes, copyRom) => RMApi._call("start_export_to_local", [localId, romKeys || null, mediaTypes || null, !!copyRom]),
    checkExportConflicts: (localId, romKeys) => RMApi._call("check_export_conflicts", [localId, romKeys || null]),
    getSettings: () => RMApi._call("get_settings", []),
    getVersion: () => RMApi._call("get_version", []),
    saveSettings: (lang, theme, saveInterval, exportOptions) => RMApi._call("save_settings", [lang, theme, saveInterval, exportOptions]),
    saveUiSettings: (startupPage, confirmDestructiveActions, loggingEnabled, defaultListView) =>
      RMApi._call("save_ui_settings", [startupPage, confirmDestructiveActions, loggingEnabled, defaultListView]),
    savePerformanceSettings: (deferVideoMedia) => RMApi._call("save_performance_settings", [deferVideoMedia]),
    doBackup: () => RMApi._call("do_backup", []),
    listBackups: () => RMApi._call("list_backups", []),
    restoreBackup: (filename) => RMApi._call("restore_backup", [filename]),
    listCompareSources: () => RMApi._call("list_compare_sources", []),
    compareSources: (sourceA, sourceB, system) => RMApi._call("compare_sources", [sourceA, sourceB, system || null]),
    compareCopyRow: (sourceA, sourceB, direction, system, filename) => RMApi._call("compare_copy_row", [sourceA, sourceB, direction, system, filename]),
    compareCopyRows: (sourceA, sourceB, direction, items) => RMApi._call("compare_copy_rows", [sourceA, sourceB, direction, items]),
    windowControl: (action) => RMApi._call("window_control", [action]),
    windowDragStart: () => RMApi._call("window_drag_start", []),
    windowResizeStart: (edge) => RMApi._call("window_resize_start", [edge]),
    diagnosticLog: (event, payload) => RMApi._call("diagnostic_log", [event, payload || {}]),
    getDiagnosticLogPath: () => RMApi._call("get_diagnostic_log_path", []),
  };

  window.RMApi = RMApi;
})();
