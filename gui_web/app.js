/* ==========================================================================
   app.js
   Retro Metadata Manager - 메인 애플리케이션 로직 (vanilla JS, 외부 의존성 없음)
   React 프로토타입(RetroMetadataManagerMockup.jsx)의 UI/UX를 그대로 이식.
   ========================================================================== */

(function () {
  const ic = window.RMIcons.svg;
  const api = window.RMApi;

  // ------------------------------------------------------------------
  // DOM 빌드 헬퍼 (텍스트는 항상 textNode로 넣어서 한글/특수문자 injection 문제 없음)
  // ------------------------------------------------------------------
  // [로고] "THE RETRO CABINET" 참고 디자인을 sidebar 폭(224px)에 맞춰 다듬은 컨트롤러 마크.
  // 기존 아이콘 세트와 동일하게 stroke=currentColor 방식이라 --accent 색을 그대로 물려받는다.
  const BRAND_LOGO_SVG = '<svg class="brand-logo-mark" width="30" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M8 6c-2-1.5-3-3 0-5"/>'
    + '<rect x="2" y="6" width="20" height="12" rx="6"/>'
    + '<line x1="7" y1="12" x2="11" y2="12"/><line x1="9" y1="10" x2="9" y2="14"/>'
    + '<circle cx="16" cy="13" r="1.1"/><circle cx="19" cy="10.3" r="1.1"/>'
    + '</svg>';

  function h(tag, props, children) {
    const el = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v == null) continue;
        if (k === "style" && typeof v === "object") Object.assign(el.style, v);
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
        else if (k === "class") el.className = v;
        else if (k === "html") el.innerHTML = v; // 아이콘 SVG 등 신뢰 가능한 정적 문자열에만 사용
        else if (k === "checked" || k === "disabled" || k === "value") el[k] = v;
        else el.setAttribute(k, v);
      }
    }
    (children || []).forEach((c) => {
      if (c == null) return;
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return el;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function icon(name, size) { return h("span", { html: ic(name, size) }); }

  // ------------------------------------------------------------------
  // 상태
  // ------------------------------------------------------------------
  const STATUS_META = {
    "완료": { color: "success", label: "Normal" },
    "부분": { color: "warning", label: "Partial" },
    "누락": { color: "danger", label: "Missing" },
    "정상": { color: "success", label: "Normal" },
    "경고": { color: "warning", label: "Warning" },
  };
  const STATUS_FILTERS = [
    { key: "normal", label: "Normal" },
    { key: "partial", label: "Partial" },
    { key: "missingRom", label: "Missing ROM" },
    { key: "missingMedia", label: "Missing Media" },
    { key: "duplicate", label: "유사롬 (Comparable ROM)" },
  ];
  const GRID_TEMPLATE_KEYS = ["file", "title", "desc", "region", "rating", "genre", "status"];
  // [수정] File 동일, Title +15%, Description +50%, Region/Rating 신규(78px), Genre도 78px로 축소
  const DEFAULT_COL_WIDTHS = { file: 190, title: 219, desc: 390, region: 78, rating: 60, genre: 78, status: 60 };
  const COL_MIN_WIDTH = 60;
  const NO_COL_WIDTH = 44;
  // [신규] Favorite 전용 열 - 기존엔 Rating 셀 안에 별 아이콘을 같이 욱여넣어서 그 열이
  // "Favorite"라는 헤더 텍스트를 쓰기엔 너무 좁았다. 별도 고정폭 열로 분리하고 헤더는
  // 텍스트 대신 별 글리프 하나만 써서 열 길이를 짧게 유지한다("No." 열처럼 리사이즈 불가).
  const FAV_COL_WIDTH = 30;

// [신규] 시스템 이름 정규화: ROM 디렉토리 이름을 기준으로 하되, ES-DE 표준(소문자 축약형)과
// 다르면 표준으로 교정한다. (예: SNES -> snes, PSX -> psx)
const SYSTEM_ALIAS_MAP = {
  snes: "snes", sfc: "snes", superfamicom: "snes",
  nes: "nes", famicom: "nes",
  psx: "psx", ps1: "psx", playstation: "psx",
  ps2: "ps2", playstation2: "ps2",
  genesis: "megadrive", megadrive: "megadrive", md: "megadrive",
  gba: "gba", gameboyadvance: "gba",
  gbc: "gbc", gameboycolor: "gbc",
  gb: "gb", gameboy: "gb",
  n64: "n64", nintendo64: "n64",
  msx1: "msx", msx: "msx",
};
function normalizeSystemName(raw) {
  if (!raw) return raw;
  const lower = String(raw).toLowerCase().replace(/[\s_-]/g, "");
  return SYSTEM_ALIAS_MAP[lower] || String(raw).toLowerCase();
}
  const FRONTENDS = ["ES-DE", "EmulationStation", "Pegasus", "LaunchBox", "Daijishō"];
  const SAME_DIR_FRONTENDS = new Set(["Pegasus", "Daijishō"]);
  const ES_STYLE_FRONTENDS = new Set(["ES-DE", "EmulationStation"]);

  const S = {
    view: "masterdb",
    settingsReturnView: "masterdb",
    locals: [],
    masterdb: { configured: false, root: "", romCount: 0 },
    games: [],
    // 화면 전환/재진입에서 Local 목록을 유지한다. 이전 버전은 참조만 있고 초기화가 없어 Local 재진입 시 예외가 발생했다.
    localGamesCache: Object.create(null),
    detailCache: Object.create(null),
    mediaImageCache: Object.create(null),
    selectedGame: null,
    // [신규] 탐색기 스타일 미리보기 토글 - 켜져 있어야만 선택 시 Metadata Panel이
    // 공간을 차지하며 열린다(꺼져 있으면 클릭해도 선택만 되고 패널은 안 뜸). 기존
    // 사용자 경험(선택하면 항상 패널이 열림)과 최대한 가깝게 기본값은 켜둔다 - 그래서
    // panelOpen도 같이 true로 시작해야 앱을 막 열었을 때 토글 버튼(켜짐 표시)과
    // 실제 패널 상태(빈 상태 안내 표시)가 서로 어긋나지 않는다.
    previewOn: true,
    panelOpen: true,
    search: "",
    selectedSystem: "all",
    statusFilter: new Set(["all"]),
    sortField: null,
    sortDir: "asc",
    viewMode: "list",
    colWidths: { ...DEFAULT_COL_WIDTHS },
    fontScale: 1,
    version: "",
    // [신규] 게임 삭제 - 다중선택(Ctrl+Click/Ctrl+Shift+Click) 대상 목록 + 삭제 대상 체크박스
    multiSelect: new Set(),
    multiSelectAnchor: null,
    deleteTargets: { metadata: true, rom: true },
    settings: { lang: "ko", theme: "dark", saveInterval: 5, exportOptions: {} },
    sidebarOpen: false,
    confirmState: null,
    addLocalOpen: false,
    verDiffState: null,
    groupSimilarRoms: false, // [단위 8] 유사롬 묶어보기 토글
    favoriteOnly: false, // [단위 9] 즐겨찾기만 보기 토글
    similarGroupsCache: {}, // { [system]: groups[] } - getSimilarRomGroups() 결과 캐시
    renameState: null, // [F2] { romKey, file, value, error }
    editLocalPathsState: null, // [Settings > GameListSet 경로 변경] { localId, label, romPath, metaPath, error }
    scanningLocalId: null, // 초기 스캔이 진행 중인 Local id - GameList 빈 목록 메시지를 "스캔 중"으로 대체
    toastTimer: null,
    openTick: 0,
    diagRenderSeq: 0,
    diagCoverSeq: 0,
    // [신규 v0.5 9단계] Compare 화면 상태
    compare: {
      sourceA: "", sourceB: "", rows: [], loading: false, loaded: false,
      // [신규] 단일 선택(selectedLeft/selectedRight)을 다중 선택 Set으로 대체 - 클릭
      // 한 개만 하면 Set 크기 1이 되어 기존 단일 선택과 동일하게 동작한다. 키는
      // db.make_rom_key와 동일한 "system|filename" 형식(compareRowKey() 참고).
      selectedLeftKeys: new Set(), selectedRightKeys: new Set(),
      leftAnchor: null, rightAnchor: null, search: "",
      // [신규] Ctrl+A가 "지금 어느 쪽을 다루고 있었는지" 판단하는 데 쓴다 - 행을
      // 클릭할 때마다 그 side로 갱신(handleCompareRowClick). 클릭 즉시 renderCompare()가
      // DOM을 다시 그려 포커스가 사라지므로, 실제 DOM 포커스 대신 이 상태값으로 추적한다.
      lastActiveSide: null,
      // [신규] GameList 필터바에서 가져온 개념들 + Compare 전용 관계 필터.
      viewMode: "list", favoriteOnly: false, relFilter: "all", // "all" | "diff" | "same"
      // [신규] Compare에 들어오기 직전 화면 - "비교 종료"가 여기로 돌아간다
      // (goView("masterdb")로 고정하면 GameListSet 화면에서 들어왔을 때도 항상
      // ArchiveDB로 튕겨나가서 부자연스럽다).
      returnView: null,
    },
  };

  // ------------------------------------------------------------------
  // Diagnostic build: all events are appended by Python to
  // <app>/logs/retro_manager_diagnostic.log. Logging must never affect UI.
  // ------------------------------------------------------------------
  const DIAG_VERBOSE = false;
  const DIAG_EVENTS = new Set(["WINDOW_ERROR", "UNHANDLED_REJECTION", "LIST_SELECTION", "MEDIA_SAVE", "MEDIA_SAVE_FAIL", "LOCAL_MEDIA_SAVE", "LOCAL_MEDIA_SAVE_FAIL", "EXPORT_ERROR", "IMPORT_ERROR"]);
  function diag(event, payload = {}) {
    if (!DIAG_VERBOSE && !DIAG_EVENTS.has(event)) return;
    try {
      const safe = { ...payload, view: S.view, selectedSystem: S.selectedSystem, viewMode: S.viewMode };
      api.diagnosticLog(event, safe).catch(() => {});
    } catch (_) {}
  }

  window.addEventListener("error", (e) => {
    diag("WINDOW_ERROR", { message: e.message, source: e.filename, line: e.lineno, col: e.colno, stack: e.error && e.error.stack ? String(e.error.stack) : "" });
  });
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason;
    diag("UNHANDLED_REJECTION", { reason: r && r.stack ? String(r.stack) : String(r) });
  });

  function gridTemplate() {
    return `${NO_COL_WIDTH}px ${S.colWidths.file}px ${S.colWidths.title}px ${S.colWidths.desc}px ${S.colWidths.region}px ${S.colWidths.rating}px ${FAV_COL_WIDTH}px ${S.colWidths.genre}px ${S.colWidths.status}px`;
  }

  // ------------------------------------------------------------------
  // Toast / Confirm
  // ------------------------------------------------------------------
  function showToast(msg, type) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.style.borderColor = `var(--${type === "warning" ? "warning" : type === "error" ? "danger" : "success"})`;
    el.classList.add("show");
    if (S.toastTimer) clearTimeout(S.toastTimer);
    S.toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  }

  function showConfirm(title, message, danger, onConfirm) {
    // Settings > General > Confirmations 가 꺼져 있으면 위험 작업도 확인창 없이 바로 실행.
    if (danger && S.settings && S.settings.confirmDestructiveActions === false) {
      onConfirm();
      return;
    }
    S.confirmState = { title, message, danger, onConfirm };
    renderModals();
  }
  function closeConfirm() { S.confirmState = null; renderModals(); }

  // ------------------------------------------------------------------
  // 데이터 로딩
  // ------------------------------------------------------------------
  async function loadLocals() {
    const r = await api.listLocals();
    if (r.ok) S.locals = r.data;
  }
  async function loadMasterdbInfo() {
    const r = await api.getMasterdbInfo();
    if (r.ok) S.masterdb = r.data;
  }
  async function loadGamesForView() {
    diag("LOAD_GAMES_START", { currentGames: S.games.length, cacheKeys: Object.keys(S.localGamesCache),
      cacheCounts: Object.fromEntries(Object.entries(S.localGamesCache).map(([k,v]) => [k, Array.isArray(v && v.games) ? v.games.length : -1])) });
    if (S.view === "masterdb") {
      const r = await api.listMasterdbGames();
      S.games = r.ok ? r.data : [];
      diag("LOAD_GAMES_MASTERDB_RESPONSE", { ok: !!r.ok, count: S.games.length, error: r.error || "" });
    } else if (S.view.startsWith("local-")) {
      const localId = S.view.replace("local-", "");
      const cached = S.localGamesCache[localId];
      S.games = cached && cached.loaded === true && Array.isArray(cached.games) ? cached.games : [];
      diag("LOAD_GAMES_LOCAL_CACHE", { localId, cachePresent: !!cached, count: S.games.length,
        hasCover: S.games.filter((g) => !!g.hasCover).length, missingRom: S.games.filter((g) => g.romMatched === false).length });
    }
    S.games = S.games.map((g) => ({ ...g, system: normalizeSystemName(g.system) }));
    diag("LOAD_GAMES_DONE", { count: S.games.length, hasCover: S.games.filter((g) => !!g.hasCover).length,
      systems: [...new Set(S.games.map((g) => g.system))] });
  }

  async function refreshAll() {
    await Promise.all([loadLocals(), loadMasterdbInfo()]);
    await loadGamesForView();
    renderAll();
  }

  // ------------------------------------------------------------------
  // 파생 데이터 (필터/정렬)
  // ------------------------------------------------------------------
  function matchesStatusFilter(g) {
    if (S.statusFilter.has("all")) return true;
    let ok = false;
    if (S.statusFilter.has("normal") && g.status === "완료") ok = true;
    if (S.statusFilter.has("partial") && g.status === "부분") ok = true;
    if (S.statusFilter.has("missingRom") && g.status === "누락") ok = true;
    if (S.statusFilter.has("missingMedia") && g.missingMedia) ok = true;
    if (S.statusFilter.has("duplicate") && g.duplicate) ok = true;
    return ok;
  }

  function getSystems() {
    const map = new Map();
    S.games.forEach((g) => map.set(g.system, (map.get(g.system) || 0) + 1));
    const list = [{ key: "all", label: "전체", count: S.games.length }];
    for (const [sys, count] of map) list.push({ key: sys, label: sys, count }); // ES-DE 표준(소문자) 그대로 표시
    return list;
  }

  // [신규] Compare 화면용 시스템 목록 - GameList와 달리 S.games가 아니라 현재 비교
  // 결과(c.rows, 두 소스를 합친 전체 system)에서 뽑는다. 사이드바의 GAME SYSTEMS를
  // 그대로 재사용해 "System 기반으로 비교 범위를 좁힌다"는 요청에 대응한다.
  function getCompareSystems() {
    const map = new Map();
    S.compare.rows.forEach((r) => map.set(r.system, (map.get(r.system) || 0) + 1));
    const list = [{ key: "all", label: "전체", count: S.compare.rows.length }];
    for (const [sys, count] of map) list.push({ key: sys, label: sys, count });
    return list;
  }

  function getSortedFilteredGames() {
    let list = S.games;
    if (S.selectedSystem !== "all") list = list.filter((g) => g.system === S.selectedSystem);
    if (S.search) {
      const q = S.search.toLowerCase();
      list = list.filter((g) => g.file.toLowerCase().includes(q) || (g.title || "").toLowerCase().includes(q));
    }
    list = list.filter(matchesStatusFilter);
    // [단위 9] 즐겨찾기만 보기
    if (S.favoriteOnly && S.view === "masterdb") list = list.filter((g) => g.favorite);
    // [단위 8] 유사롬 묶어보기: 그룹당 대표 1개만 남기고 나머지는 숨긴다.
    // representative가 지정 안 된 그룹은 첫 멤버를 임시 대표로 취급한다 (탐색 직후엔
    // start_find_similar_roms가 자동 대표를 지정하므로 실제로는 거의 발생하지 않는다).
    if (S.groupSimilarRoms && S.view === "masterdb") {
      const groups = S.similarGroupsCache[S.selectedSystem] || [];
      if (groups.length) {
        const hidden = new Set();
        const countByRep = {};
        groups.forEach((g) => {
          const rep = g.representative || (g.members[0] && g.members[0].romKey);
          if (!rep) return;
          g.members.forEach((m) => { if (m.romKey !== rep) hidden.add(m.romKey); });
          countByRep[rep] = g.members.length;
        });
        list = list.filter((g) => !hidden.has(g.romKey)).map((g) => (countByRep[g.romKey] ? { ...g, similarGroupCount: countByRep[g.romKey] } : g));
      }
    }
    if (S.sortField) {
      list = [...list].sort((a, b) => {
        const av = (a[S.sortField] || "").toString().toLowerCase();
        const bv = (b[S.sortField] || "").toString().toLowerCase();
        if (av < bv) return S.sortDir === "asc" ? -1 : 1;
        if (av > bv) return S.sortDir === "asc" ? 1 : -1;
        return 0;
      });
    }
    return list;
  }

  // ------------------------------------------------------------------
  // 사이드바
  // ------------------------------------------------------------------
  function compactNum(n) {
    n = n || 0;
    if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "K";
    return String(n);
  }

  // ------------------------------------------------------------------
  // [신규] Font-scale (Shift + 마우스 휠로 전체 화면 확대/축소)
  // CSS zoom 속성을 #app 컨테이너에 적용 - 폰트뿐 아니라 여백/버튼 크기까지 통째로
  // 비례 확대되므로, 모든 컴포넌트의 font-size를 개별적으로 calc() 처리할 필요가 없다.
  // WebView2(Chromium 기반)는 zoom을 안정적으로 지원한다.
  // ------------------------------------------------------------------
  const FONT_SCALE_MIN = 0.75;
  const FONT_SCALE_MAX = 1.5;
  const FONT_SCALE_STEP = 0.05;

  function applyFontScale() {
    // Do NOT use CSS zoom: it scales geometry, fixed hit areas and grids and therefore
    // changes the layout. Only typography is scaled through a CSS custom property.
    document.documentElement.style.setProperty("--font-scale", String(S.fontScale));
    // [수정] GameList 필터바와 Compare 필터바 둘 다 자기 자신의 "A 100%" 표시가
    // 있다 - 둘 중 어느 화면에서 Shift+휠로 조절하든 나머지 하나도 같이 갱신되게
    // id 하나가 아니라 같은 class를 가진 전부를 갱신한다.
    document.querySelectorAll(".font-scale-label").forEach((label) => { label.textContent = `A ${Math.round(S.fontScale * 100)}%`; });
  }

  function resetFontScale() {
    S.fontScale = 1;
    applyFontScale();
  }

  function adjustFontScale(delta) {
    S.fontScale = Math.min(FONT_SCALE_MAX, Math.max(FONT_SCALE_MIN, S.fontScale + delta));
    applyFontScale();
  }

  document.addEventListener("wheel", (e) => {
    if (!e.shiftKey) return;
    e.preventDefault();
    adjustFontScale(e.deltaY < 0 ? FONT_SCALE_STEP : -FONT_SCALE_STEP);
  }, { passive: false });

  // [수정] generic UI 아이콘(icons.js)의 카테고리 하나를 시스템별로 배정하는 "최후의
  // 폴백" 표일 뿐, 시스템 전용 아이콘을 제공하는 목록이 아니다 - 이름을 SYSTEM_ICONS에서
  // SYSTEM_ICON_FALLBACKS로 바꿔서 역할을 명확히 한다(RMSystemIconsRaster=전용 raster,
  // RMSystemIcons=전용 SVG, 이 표=그 둘 다 없을 때만 쓰는 범용 카테고리).
  const SYSTEM_ICON_FALLBACKS = {
    // 8bit/16bit 컴퓨터 - 키보드 형태
    msx:"keyboard", msx2:"keyboard", dos:"keyboard", windows:"keyboard",
    amiga:"keyboard", c64:"keyboard", atarist:"keyboard", zxspectrum:"keyboard",
    // 각진 패드(십자키+버튼 2개, 손잡이 없는 형태) 콘솔
    nes:"padRect", famicom:"padRect", mastersystem:"padRect",
    // 곡선형 패드(손잡이 + 버튼 4개) 콘솔
    snes:"gamepad", superfamicom:"gamepad", megadrive:"gamepad", genesis:"gamepad", pcengine:"gamepad",
    // 휴대용
    gb:"handheld", gbc:"handheld", gba:"handheld", nds:"handheld", n3ds:"handheld",
    psp:"handheld", psvita:"handheld", gamegear:"handheld", wonderswan:"handheld", switch:"handheld",
    // CD/디스크 기반
    psx:"disc", ps2:"disc", ps3:"disc", dreamcast:"disc", saturn:"disc", megacd:"disc", pcenginecd:"disc",
    // 리모컨형 콘솔
    wii:"remote", wiiu:"remote",
    // 게임패드형 콘솔(트리거/아날로그 위주 컨트롤러)
    n64:"console", gamecube:"console",
    ps4:"gamepad", ps5:"gamepad", xbox:"gamepad", xbox360:"gamepad", xboxone:"gamepad", xboxseries:"gamepad",
    // 조이스틱/아케이드 스틱 기반 - 홈 조이스틱과 아케이드 계열을 하나의 스틱 아이콘으로 통일
    atari2600:"joystick", jaguar:"joystick", colecovision:"joystick", intellivision:"joystick",
    arcade:"joystick", mame:"joystick", fbneo:"joystick", cps1:"joystick", cps2:"joystick", cps3:"joystick", neogeo:"joystick",
    // 에뮬레이터 프레임워크
    scummvm:"floppy",
  };
  // [신규] system-icons-raster.js 전용 PNG를 icons.js/system-icons.js보다 한 단계 더
  // 위에서 쓴다. <img> 하나만 그리면 테마가 바뀔 때마다 다시 렌더링해야 하므로,
  // light/dark 두 장을 같이 넣고 CSS로 한쪽만 보이게 한다(재렌더링 없이 [data-theme]
  // 전환만으로 아이콘도 같이 바뀜). alt는 비워둔다 - 옆 시스템명 텍스트/title 속성이
  // 이미 같은 정보를 주는 장식용 아이콘이라 스크린리더가 두 번 읽을 필요가 없다.
  function rasterIconPair(key, size) {
    const light = window.RMSystemIconsRaster.get(key, "light", size);
    const dark = window.RMSystemIconsRaster.get(key, "dark", size);
    return h("span", { class: "raster-icon-pair" }, [
      h("img", { class: "for-light", src: light, alt: "", width: size, height: size }),
      h("img", { class: "for-dark", src: dark, alt: "", width: size, height: size }),
    ]);
  }
  // [수정] systemIcon()/systemSquareIcon() 둘 다 각자 아이콘 lookup/폴백 정책을 따로
  // 갖고 있던 걸 여기 하나로 합쳤다 - 전엔 상세패널(systemIcon)이 raster 다음 곧장
  // generic 폴백으로 넘어가버려서 system-icons.js의 전용 SVG 티어를 건너뛰는 버그가
  // 있었다. 우선순위는 절대 순서를 바꾸지 않는다: raster -> 전용 SVG -> generic 폴백.
  //
  // key는 반드시 normalizeSystemName()을 거친다 - "SFC"/"PS1"처럼 별칭으로 들어온
  // 값을 단순 소문자 변환만 하면 canonical 키("snes"/"psx")와 어긋나서, 전용 아이콘이
  // 있는 시스템인데도 generic 폴백으로 새는 문제가 생긴다.
  function renderSystemIcon(key, opts) {
    opts = opts || {};
    const size = opts.size || 20;
    const className = opts.className || "";
    const k = normalizeSystemName(key) || "";
    const upper = k.toUpperCase();
    const withExtra = (extra) => (extra ? className + " " + extra : className);

    if (window.RMSystemIconsRaster && window.RMSystemIconsRaster.has(k)) {
      return h("span", { class: withExtra(opts.rasterClass), title: upper }, [rasterIconPair(k, size)]);
    }
    if (window.RMSystemIcons && window.RMSystemIcons.has(k)) {
      return h("span", { class: className, title: upper, html: window.RMSystemIcons.svg(k, size) });
    }
    return h("span", {
      class: withExtra(opts.fallbackClass),
      title: upper,
      html: ic(SYSTEM_ICON_FALLBACKS[k] || "console", size),
    });
  }
  // 호환용 wrapper - 사이드바(.sq-icon)와 상세패널(.system-icon)은 렌더링 컨텍스트가
  // 달라서 CSS 클래스/기본 크기만 다르게 주고, 실제 lookup/폴백 로직은 renderSystemIcon()
  // 하나로 통일했다. 기존 호출부(renderSidebar, detail 패널)를 그대로 유지하기 위해
  // 이름은 남겨둔다.
  function systemIcon(key, size) {
    return renderSystemIcon(key, { size: size || 22, className: "system-icon", rasterClass: "system-icon-raster" });
  }

  // [신규] 사이드바 전용 - 이름/키 기준 해시로 팔레트에서 색을 고정 배정한다("랜덤"이지만
  // 같은 이름은 항상 같은 색). GameListSet 행의 "|" 색상 바는 SFC 컨트롤러 4버튼
  // (A빨강/B노랑/X파랑/Y초록) 팔레트를, System 행의 정사각형은 더 넓은 구분용 팔레트를 쓴다.
  function hashColor(name, palette) {
    let hash = 0;
    const s = String(name || "");
    for (let i = 0; i < s.length; i++) hash = (hash * 31 + s.charCodeAt(i)) >>> 0;
    return palette[hash % palette.length];
  }
  const GAMELISTSET_BAR_PALETTE = ["#E4572E", "#F4C518", "#2E86DE", "#2FA84F"];
  function gamelistBarIcon(local) {
    // [수정] 초기 스캔이 진행 중인 GameListSet은 아직 상태/통계를 신뢰할 수 없으니
    // "스캔 중"임을 빨간색으로 명확히 보여준다 - 예전엔 스캔 여부가 색상 결정에
    // 전혀 반영되지 않아, 추가 직후엔 (진짜 상태와 무관한) hashColor가 그대로 나와
    // 사용자가 "왜 색이 이랬다 저랬다 하지?" 헷갈렸다.
    if (S.scanningLocalId === local.id) return h("span", { class: "bar-icon scanning", style: { background: "var(--danger)" } });
    // 상태(경고/오류)가 있으면 식별용 랜덤 색보다 상태 색을 우선 보여준다 - 문제가 있는
    // GameListSet을 색만 보고도 놓치지 않게 하기 위함.
    const color = local.status === "경고" ? "var(--warning)" : local.status === "오류" ? "var(--danger)"
      : hashColor(local.label, GAMELISTSET_BAR_PALETTE);
    return h("span", { class: "bar-icon", style: { background: color } });
  }
  // System 목록(사이드바) 아이콘 - renderSystemIcon()의 wrapper. 우선순위는
  // 1) system-icons-raster.js 전용 PNG  2) system-icons.js 전용 SVG
  // 3) icons.js 범용 카테고리(SYSTEM_ICON_FALLBACKS) 순으로 고정이며 바뀌지 않는다.
  function systemSquareIcon(key, size) {
    return renderSystemIcon(key, {
      size: size || 22,
      className: "sq-icon",
      rasterClass: "sq-icon-raster",
      fallbackClass: "sq-icon-fallback",
    });
  }
  // [테스트 전용] Playwright에서 별칭(SFC/PS1 등) -> normalizeSystemName -> raster/svg/
  // 폴백 우선순위로 이어지는 실제 체인을 모킹 없이 그대로 호출해보기 위한 최소 훅.
  // UI 동작에는 관여하지 않는다.
  window.__RMIconTestHooks = {
    normalizeSystemName,
    renderSystemIcon,
    systemIcon,
    systemSquareIcon,
    SYSTEM_ICON_FALLBACKS,
  };

  function renderSidebar() {
    const root = document.getElementById("sidebar");
    clear(root);

    // [로고] "THE RETRO CABINET" 참고 디자인 반영: 컨트롤러 마크 + "RETRO CABINET" 워드마크
    // + "Personal Retro Game Collection" 태그라인. 224px 사이드바 폭에 맞춰 THE/태그라인은
    // 작게 줄였다.
    const brand = h("div", { class: "brand" }, [
      h("div", { class: "flex items-center gap-2" }, [
        h("div", { class: "brand-icon", html: BRAND_LOGO_SVG }),
        h("div", { style: { minWidth: "0" } }, [
          h("div", { class: "brand-title-row" }, [
            h("div", { class: "brand-eyebrow" }, ["THE"]),
            h("div", { class: "brand-title" }, ["RETRO CABINET"]),
          ]),
          h("div", { class: "brand-tagline truncate" }, ["Personal Retro Game Collection"]),
          h("div", { class: "brand-version", id: "brand-version-label" }, [S.version ? `v${S.version}` : ""]),
        ]),
      ]),
    ]);
    root.appendChild(brand);

    // [수정] Settings 톱니바퀴를 사이드바 하단에서 좌측 상단(브랜드 바로 아래)으로
    // 이동 - 아이콘만 두고 텍스트 라벨은 생략한다(다른 nav-item과 달리 이 자리는
    // 좁고, 톱니바퀴 모양 자체로 이미 의미가 분명하다).
    const settingsBtn = h("button", { class: "sidebar-settings-btn", title: "Settings" }, [icon("settings", 14)]);
    settingsBtn.addEventListener("click", openSettings);
    root.appendChild(settingsBtn);

    function navItem(label, iconName, active, onClick, opts) {
      opts = opts || {};
      const btn = h("button", {
        class: "nav-item" + (active ? " active" : "") + (opts.small ? " small" : ""),
        onClick,
      });
      if (opts.dot) btn.appendChild(h("span", { class: "dot", style: { background: opts.dot } }));
      if (iconName) btn.appendChild(icon(iconName, opts.small ? 13 : 16));
      btn.appendChild(h("span", { class: "truncate", style: { flex: "1" } }, [label]));
      root.appendChild(btn);
      if (opts.tip) tip(btn, opts.tip);
      return btn;
    }

    // [순서/라벨 변경] Dashboard -> ArchiveDB(구 MasterDB) -> GameListSet(구 Local).
    // 내부 view key("masterdb", "local-*")와 백엔드 함수명은 그대로 유지 - GUI 라벨만 변경.
    // [신규] 각 버튼에 마우스를 올리면 간략한 설명(용도/용량)이 뜨는 툴팁을 붙인다.
    navItem("Dashboard", "dashboard", S.view === "dashboard", () => goView("dashboard"), { tip: "전체 현황 · 통계 요약" });

    // [수정] "지금 이 목록이 무엇에 대한 것인지" 헷갈리지 않도록, 소스(ArchiveDB/
    // GameListSet)와 System 필터 중 한 번에 하나만 강조(active)되게 한다 - 전엔
    // 화면만 보고 소스 행을 켰어서, System을 좁혀도 계속 켜진 채로 남아 두 군데가
    // 동시에 강조돼 보이는 문제가 있었다. 소스 행은 selectedSystem이 "전체"일 때만.
    root.appendChild(h("div", { class: "nav-section-label" }, ["ARCHIVEDB"]));
    // [제거] 사이드바 고정 "Compare" 메뉴는 삭제 - 이제 SOURCE 카드마다(ArchiveDB
    // 포함) 붙은 "▼ 비교" 버튼이 그 소스를 미리 지정한 채 Compare로 바로 진입시켜
    // 주는 게 유일한(그리고 더 나은) 입구다. Compare는 최소 두 소스가 있어야 의미가
    // 있는데, 그 조건이 성립할 땐 항상 카드가 최소 2개 떠 있어 입구가 없어지는
    // 경우는 없다.
    navItem("ArchiveDB", "database", S.view === "masterdb" && S.selectedSystem === "all", () => goView("masterdb"), { small: true, tip: "통합 보관소" });

    root.appendChild(h("div", { class: "nav-section-label" }, ["MY GAMELISTS"]));
    S.locals.forEach((l) => {
      const romCount = (l.stats && l.stats.rom_count) || l.romCount || 0;
      const sizeGB = (l.stats && l.stats.rom_size ? (l.stats.rom_size / 1e9) : (l.sizeGB || 0));
      // [수정] 예전엔 프론트엔드/ROM수/용량을 항상 보이는 둘째 줄로 표시했는데, 한 줄로
      // 줄이고 그 정보는 hover 툴팁으로 옮겼다(탐색기 스타일 - 이름만 보이게, 상세는 hover 시).
      // "|" 자리는 상태 dot 대신 GameListSet별 색상 바(이름 해시로 고정 배정)로 바꿨다.
      const btn = h("button", {
        class: "nav-item small nav-item-local" + (S.view === "local-" + l.id && S.selectedSystem === "all" ? " active" : ""),
        onClick: () => goView("local-" + l.id),
      }, [
        gamelistBarIcon(l),
        h("span", { class: "truncate" }, [l.label]),
      ]);
      tip(btn, `${l.frontendLabel || l.frontend} · ${compactNum(romCount)}개 게임 · ${sizeGB.toFixed(2)}GB` + (l.status && l.status !== "정상" ? ` · ${l.status}` : ""));
      root.appendChild(btn);
    });
    // IMPORTANT: this is the only GameListSet-add control. It belongs to Navigation and
    // must remain available even though the GameList top-right "+ Local" button is removed.
    const addLocalNav = h("button", {
      id: "nav-add-local",
      class: "nav-item small nav-add-local",
      onClick: () => openAddLocal(),
    }, [icon("plus", 13), h("span", { class: "truncate", style: { flex: "1" } }, ["GameListSet 추가"])]);
    tip(addLocalNav, "새 GameListSet 등록");
    root.appendChild(addLocalNav);

    if (S.view === "masterdb" || S.view.startsWith("local-")) {
      root.appendChild(h("div", { class: "nav-section-label" }, ["SYSTEM"]));
      getSystems().forEach((s) => {
        // "전체"는 필터가 없는 상태라 그 자체로는 강조하지 않는다 - 그 경우 위 소스
        // 행(ArchiveDB/GameListSet)이 대신 연결 대상이 된다.
        const btn = navItem(`${s.label} · ${s.count}`, null, s.key !== "all" && S.selectedSystem === s.key, () => { S.selectedSystem = s.key; renderSidebar(); renderListArea(); }, { small: true, tip: s.key !== "all" ? `${s.label} · ${s.count}개 게임` : "전체 시스템" });
        const text = btn.querySelector("span.truncate");
        if (text && s.key !== "all") { btn.insertBefore(systemSquareIcon(s.key), text); }
      });
    }
    // [신규] Compare 화면에서도 System 목록을 띄워, 그 시스템에 대해서만(또는 전체)
    // 비교하도록 범위를 좁힐 수 있게 한다.
    if (S.view === "compare") {
      root.appendChild(h("div", { class: "nav-section-label" }, ["SYSTEM"]));
      getCompareSystems().forEach((s) => {
        const btn = navItem(`${s.label} · ${s.count}`, null, S.selectedSystem === s.key, () => { S.selectedSystem = s.key; renderSidebar(); renderCompare(); }, { small: true, tip: s.key !== "all" ? `${s.label} · ${s.count}개 게임` : "전체 시스템" });
        const text = btn.querySelector("span.truncate");
        if (text && s.key !== "all") { btn.insertBefore(systemSquareIcon(s.key), text); }
      });
    }
    root.appendChild(h("div", { class: "nav-spacer" }));
  }

  async function goView(v) {
    const previousView = S.view;
    diag("GO_VIEW_START", { from: previousView, to: v, gamesBefore: S.games.length,
      localCacheCounts: Object.fromEntries(Object.entries(S.localGamesCache).map(([k,val]) => [k, Array.isArray(val && val.games) ? val.games.length : -1])) });
    S.view = v;
    S.sidebarOpen = false;
    S.selectedSystem = "all";
    // [수정] 화면을 옮기면 선택은 초기화되지만, 미리보기 토글이 켜져 있으면 패널
    // 공간 자체는 계속 예약된 채로(빈 상태 안내) 유지되어야 탐색기 방식(폴더를
    // 옮겨도 미리보기 창이 안 접힘)과 맞는다.
    S.panelOpen = S.previewOn;
    S.multiSelect.clear();
    S.multiSelectAnchor = null;
    S.selectedGame = null;
    detailState = null;

    // 먼저 현재 화면을 즉시 그린다. Local은 cache가 있으면 파일시스템을 전혀 건드리지 않는다.
    await loadGamesForView();
    renderAll();
    diag("GO_VIEW_AFTER_INITIAL_RENDER", { from: previousView, to: S.view, games: S.games.length });

    if (S.view.startsWith("local-")) {
      await ensureLocalScanned(currentLocalId());
    }
  }

  // Local 하나를 이번 세션에서 아직 스캔한 적이 없으면(초기 스캔), 백그라운드 job으로
  // 스캔을 실행해 S.localGamesCache/S.locals(stats)를 최신 상태로 만든다. GameList
  // 화면뿐 아니라 Dashboard도 이 함수를 통해서만 Local 통계를 얻는다 - Dashboard가
  // config.json에 남아있는(구버전 필드가 빠진) stats 스냅샷을 그대로 보여줘서
  // Metadata 개수/Media 용량이 0으로 나오던 문제를 근본적으로 없앴다.
  // [버그 수정] GameList 진입(goView)과 Dashboard가 같은 Local에 대해 거의 동시에
  // 이 함수를 부를 수 있다(둘 다 "아직 캐시가 없으면 스캔" 조건만 보고, 서로의
  // 존재를 모른다) - 그러면 같은 Local을 스캔하는 job이 두 번 시작되고, 한쪽이
  // 먼저 끝나 S.scanningLocalId를 null로 바꿔 화면이 "완료"로 바뀌었다가, 뒤이어
  // 나머지 한쪽도 끝나면서 그 사이 잠깐 지나간 렌더 타이밍에 따라 "스캔 중입니다"
  // 표시가 다시 나타났다 사라지는 것처럼 보일 수 있었다(리포트된 "왔다갔다" 증상).
  // 같은 localId에 대한 호출이 겹치면 새로 시작하지 않고 이미 진행 중인 Promise를
  // 그대로 같이 기다리게 한다.
  const _scanInFlight = {};
  // [P0-4] _scanInFlight는 ensureLocalScanned() 경로(GameList 진입/Dashboard)에만
  // 적용됐다 - handleRefresh()(새로고침 버튼)는 이걸 거치지 않고 매번
  // api.startScanLocal()을 직접 불렀으므로, Scan이 진행 중인 상태에서 새로고침을
  // 연타하면(또는 진입 스캔과 새로고침이 겹치면) 같은 Local에 대해 여러 개의
  // runScanJobWithProgress 폴링 체인이 동시에 떠서 진행률 바가 서로 경합하며
  // 깜빡일 수 있었다. 백엔드(start_scan_local의 _active_scan_jobs)가 실제 job
  // 중복 생성은 막아주지만, JS 쪽에서 폴링 체인 자체가 여러 개 도는 것까지는
  // 못 막는다 - 이 맵으로 같은 localId에 대한 호출이 겹치면 새 체인을 띄우지
  // 않고 이미 진행 중인 Promise를 그대로 같이 기다리게 한다.
  const _scanRunInFlight = {};
  function runScanForLocal(localId, title, onFullyDone) {
    if (_scanRunInFlight[localId]) {
      return _scanRunInFlight[localId].then((r) => { if (onFullyDone) onFullyDone(r); return r; });
    }
    const promise = (async () => {
      const job = await api.startScanLocal(localId);
      return runScanJobWithProgress(job, title, localId, onFullyDone);
    })().finally(() => { delete _scanRunInFlight[localId]; });
    _scanRunInFlight[localId] = promise;
    return promise;
  }
  function ensureLocalScanned(localId) {
    const cached = S.localGamesCache[localId];
    if (cached && cached.loaded === true && Array.isArray(cached.games)) return Promise.resolve();
    if (_scanInFlight[localId]) return _scanInFlight[localId];
    const promise = _ensureLocalScannedOnce(localId).finally(() => { delete _scanInFlight[localId]; });
    _scanInFlight[localId] = promise;
    return promise;
  }
  async function _ensureLocalScannedOnce(localId) {
    const isCurrentView = () => S.view === "local-" + localId;
    S.scanningLocalId = localId;
    // [수정] 사이드바의 GameListSet 색상바는 "스캔 중"을 빨간색으로 보여준다
    // (gamelistBarIcon 참고) - 이 함수는 GameList 진입뿐 아니라 Dashboard가 백그라운드로
    // 부를 때도 있어서(그때는 isCurrentView()가 false), 사이드바는 그 경우에도 항상
    // 최신 스캔 상태를 반영하도록 renderListArea()와 별개로 매번 갱신한다.
    renderSidebar();
    if (isCurrentView()) renderListArea();
    // [체감 속도, Scan 2단계] runScanJobWithProgress가 job1(그리고 뒤이은 follow-up)
    // 결과를 S.games/cache/렌더에 이미 반영해준다 - 여기서 games를 다시 캡처해
    // 별도로 S.games/renderAll()을 부르면, await loadLocals() 등으로 지연된 그
    // "예전(job1) 데이터 재적용"이 follow-up의 최신 렌더를 덮어쓰는 경합이 생긴다.
    // [Parent Job lifecycle 수정] 사이드바 "스캔 중" 빨간 표시(S.scanningLocalId)도
    // 2단계까지 실제로 다 끝난 뒤(onFullyDone)에만 내린다 - 1단계만 끝난 시점에
    // 내리면 2단계가 아직 백그라운드에서 도는 중인데도 완료로 보인다. 이 함수 자체는
    // (goView() 등이 await하므로) 예전처럼 1단계가 끝나는 즉시 반환한다 - 그래야
    // 화면 전환이 2단계를 기다리지 않는다는 "Scan 2단계"의 원래 취지가 유지된다.
    // [P0-4] runScanForLocal()을 거쳐서, 같은 Local에 대해 이미 진행 중인 Scan
    // chain이 있으면(예: Dashboard가 백그라운드로 이미 스캔을 시작해둔 경우)
    // 새 job/폴링 체인을 또 띄우지 않고 그 결과를 같이 기다린다.
    await runScanForLocal(localId, "GameListSet 초기 스캔 중입니다...", async (full) => {
      S.scanningLocalId = null;
      if (full.ok) {
        diag("LOCAL_SCAN_RESULT_TO_UI", { localId, games: (full.data.games || []).length,
          hasCover: (full.data.games || []).filter((g) => !!g.hasCover).length,
          missingRom: (full.data.games || []).filter((g) => g.romMatched === false).length,
          systems: [...new Set((full.data.games || []).map((g) => g.system))] });
        await loadLocals();
        renderSidebar();
        if (isCurrentView()) {
          renderAll();
          diag("LOCAL_SCAN_RENDER_DONE", { localId, games: S.games.length });
        }
      } else {
        showToast(full.error || "GameListSet 스캔 실패", "error");
        renderSidebar();
        if (isCurrentView()) renderListArea();
      }
    });
  }

  function openSettings() {
    S.settingsReturnView = S.view === "settings" ? "masterdb" : S.view;
    S.view = "settings";
    S.sidebarOpen = false;
    renderAll();
  }

  // ------------------------------------------------------------------
  // 필터바 (System/Status 드롭다운, 검색, List/Preview 토글)
  // ------------------------------------------------------------------
  let openDropdown = null;
  function closeDropdowns() { openDropdown = null; document.querySelectorAll(".dropdown-menu").forEach((m) => m.remove()); }
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".dropdown")) closeDropdowns();
  });

  function makeDropdown(buttonIconName, label, buildMenu) {
    const wrap = h("div", { class: "dropdown" });
    const btn = h("button", { class: "btn" }, [icon(buttonIconName, 13), h("span", {}, [label]), icon("chevronDown", 12)]);
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const existing = wrap.querySelector(".dropdown-menu");
      closeDropdowns();
      if (existing) return; // 토글: 이미 열려있었으면 닫기만 하고 끝
      const menu = h("div", { class: "dropdown-menu" });
      buildMenu(menu, () => closeDropdowns());
      wrap.appendChild(menu);
    });
    wrap.appendChild(btn);
    return wrap;
  }

  // [신규] overflow:hidden 조상(Compare 패널의 둥근 모서리 클리핑 등) 때문에 일반
  // .dropdown-menu(absolute)가 잘리는 자리에서 쓰는 변형 - document.body에 직접
  // 붙이고 버튼 좌표 기준 fixed로 띄운다. [P2 리뷰 반영] 이전엔 outside-click
  // 리스너 정리를 "다음 아무 클릭이나 한 번 더 일어나면 우연히 bubble 타이밍에
  // 정리된다"는 암묵적 동작에 기대고 있었다 - 실제로 새는 건 아니었지만(같은
  // 클릭이 document까지 bubble되며 자기 자신을 정리했음) 리팩터링하다 실수로
  // 깨지기 쉬운 구조였다. 이제 close()를 명시적으로 공유하고, 전역에 열린 메뉴를
  // 하나만 추적해서 다른 body-menu가 열리면 이전 것도 확실히 정리한다(부수 효과로,
  // 제목 드롭다운과 More 메뉴가 서로를 몰라 동시에 열려있을 수 있었던 것도 같이 고쳐짐).
  let openBodyMenuCloser = null;
  function openBodyMenu(anchorBtn, position, buildItems) {
    if (openBodyMenuCloser) openBodyMenuCloser();
    const menu = h("div", { class: "dropdown-menu", style: { position: "fixed", marginTop: "0", ...position } });
    const close = () => {
      menu.remove();
      document.removeEventListener("click", onOutside);
      if (openBodyMenuCloser === close) openBodyMenuCloser = null;
    };
    const onOutside = (ev) => { if (!menu.contains(ev.target) && ev.target !== anchorBtn) close(); };
    buildItems(menu, close);
    document.body.appendChild(menu);
    openBodyMenuCloser = close;
    setTimeout(() => document.addEventListener("click", onOutside), 0);
    return close;
  }

  // [신규] SOURCE 바 - Local/MasterDB 카드를 상단에 노출 (사용자 확인 하에 재도입 결정)
  function renderContextBar() {
    const root = document.getElementById("context-bar");
    clear(root);
    root.appendChild(h("span", { class: "context-bar-label" }, ["SOURCE"]));
    S.locals.forEach((l, idx) => {
      const romCount = Number((l.stats && l.stats.rom_count) || l.romCount || 0);
      const bytes = Number((l.stats && (l.stats.rom_size_bytes ?? l.stats.rom_size)) ?? l.romSize ?? 0);
      const sizeText = bytes ? `${(bytes / (1024 ** 3)).toFixed(1)}GB` : "0GB";
      const label = l.label || `LOCAL${idx + 1}`;
      const target = Number(l.target_capacity_bytes) || 0;
      const topRow = h("div", { class: "context-card-row" }, [icon("hardDrive", 12), h("span", { class: "truncate" }, [label])]);
      const subText = target > 0 ? `${sizeText} / ${(target / (1024 ** 3)).toFixed(1)}GB` : `${romCount.toLocaleString()} ROMs · ${sizeText}`;
      const card = h("div", {
        class: "context-card" + (S.view === "local-" + l.id ? " active" : "") + (target > 0 ? " has-capacity" : ""),
        title: label,
        tabIndex: 0,
        role: "button",
        onClick: () => goView("local-" + l.id),
        onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goView("local-" + l.id); } },
      }, [topRow, h("div", { class: "context-card-sub truncate" }, [subText])]);
      if (target > 0) {
        const pct = Math.min(100, Math.round((bytes / target) * 100));
        const track = h("div", { class: "context-card-capacity" });
        track.appendChild(h("div", { class: "context-card-capacity-fill" + (pct >= 100 ? " over" : ""), style: { width: Math.min(100, pct) + "%" } }));
        card.appendChild(track);
      }
      // [수정] 지금 보고 있는(활성) 소스 카드에는 비교 버튼을 안 보여준다 - 이미
      // "여기"에 있는 소스를 다시 비교 시작점으로 누르게 하는 건 혼란스럽고,
      // 소스가 이거 하나뿐인 상황(비교 대상이 없어 곧바로 오류)을 원천적으로 막는다.
      if (S.view !== "local-" + l.id) card.appendChild(compareEntryBtn(l.id, label));
      root.appendChild(card);
    });
    const romCount = Number(S.masterdb.romCount || 0);
    const romBytes = Number(S.masterdb.romSizeBytes || S.masterdb.rom_size_bytes || 0);
    const sizeText = romBytes ? `${(romBytes / (1024 ** 3)).toFixed(1)}GB` : "0GB";
    const mCard = h("div", {
      class: "context-card" + (S.view === "masterdb" ? " active" : ""),
      tabIndex: 0,
      role: "button",
      onClick: () => goView("masterdb"),
      onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goView("masterdb"); } },
    }, [
      h("div", { class: "context-card-row" }, [icon("database", 12), h("span", { class: "truncate" }, ["ArchiveDB"])]),
      h("div", { class: "context-card-sub truncate" }, [`${romCount.toLocaleString()} ROMs · ${sizeText}`]),
    ]);
    if (S.view !== "masterdb") mCard.appendChild(compareEntryBtn("masterdb", "ArchiveDB"));
    root.appendChild(mCard);
  }

  // SOURCE 카드 안의 "비교 진입" 버튼. 이 소스를 비교 화면의 왼쪽으로 지정하고 이동한다.
  // [수정] 아이콘이 chevronDown(▼)이라 "비교"라는 의미를 직접 전달하지 못한다는
  // 리뷰 지적 반영 - 좌우 화살표(⇄) 아이콘으로 교체해 "비교/전환"을 더 직접적으로
  // 나타낸다.
  function compareEntryBtn(sourceId, label) {
    const btn = h("button", { class: "context-card-compare-btn", title: `${label}와 비교` }, [icon("arrowLeftRight", 12)]);
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      S.compare.sourceA = sourceId;
      if (S.compare.sourceB === sourceId) S.compare.sourceB = "";
      S.compare.loaded = false;
      S.compare.selectedLeftKeys.clear();
      S.compare.selectedRightKeys.clear();
      // [신규] "비교 종료"가 돌아갈 곳 - 이미 Compare 안에 있는 상태에서 다른
      // 카드의 비교 버튼을 눌렀을 수도 있으니, 그럴 땐 기존 returnView를 유지한다.
      if (S.view !== "compare") S.compare.returnView = S.view;
      goView("compare");
    });
    return btn;
  }

  // [신규] Compare 화면의 명시적 종료 - 사이드바 ArchiveDB/GameListSet 항목을 눌러
  // 우회하는 것 말고, Compare 안에서 바로 나갈 수 있는 버튼/Esc가 없었다는 리뷰
  // 지적 반영. 진입 직전 화면으로 돌아가고(고정된 "masterdb"가 아니라), 선택
  // 상태는 초기화한다 - 다음에 다시 들어왔을 때 남아있던 체크가 뜬금없이 보이는
  // 것보다는 빈 상태로 시작하는 게 자연스럽다. sourceA/sourceB(비교 대상)는
  // 일부러 안 지운다 - 어차피 SOURCE 카드로 재진입하면 그쪽에서 다시 정해준다.
  function exitCompare() {
    const returnView = S.compare.returnView || "masterdb";
    S.compare.returnView = null;
    S.compare.selectedLeftKeys.clear();
    S.compare.selectedRightKeys.clear();
    S.compare.leftAnchor = null;
    S.compare.rightAnchor = null;
    S.compare.lastActiveSide = null;
    goView(returnView);
  }

  function renderFilterBar() {
    const root = document.getElementById("filter-bar");
    clear(root);

    // List/Preview 토글
    const toggle = h("div", { class: "view-toggle" });
    const listBtn = h("button", { class: S.viewMode === "list" ? "active" : "", title: "List 보기", onClick: () => { S.viewMode = "list"; renderListArea(); toggle.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", i === 0)); } }, [icon("layoutList", 13)]);
    const gridBtn = h("button", { class: S.viewMode === "preview" ? "active" : "", title: "Preview 보기", onClick: () => { S.viewMode = "preview"; renderListArea(); toggle.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", i === 1)); } }, [icon("layoutGrid", 13)]);
    toggle.appendChild(listBtn); toggle.appendChild(gridBtn);
    root.appendChild(toggle);

    const systems = getSystems();
    const curSys = systems.find((s) => s.key === S.selectedSystem) || systems[0];
    root.appendChild(makeDropdown("hardDrive", `${curSys.label} (${curSys.count})`, (menu) => {
      systems.forEach((s) => {
        const b = h("button", { class: s.key === S.selectedSystem ? "selected" : "" }, [`${s.label} (${s.count})`]);
        b.addEventListener("click", () => { S.selectedSystem = s.key; closeDropdowns(); renderFilterBar(); renderListArea(); });
        menu.appendChild(b);
      });
    }));

    const statusLabel = S.statusFilter.has("all") ? "상태: 전체" : `상태: ${S.statusFilter.size}개`;
    root.appendChild(makeDropdown("listFilter", statusLabel, (menu) => {
      const allBtn = h("button", { class: S.statusFilter.has("all") ? "selected" : "" }, ["전체"]);
      allBtn.addEventListener("click", () => { S.statusFilter = new Set(["all"]); renderFilterBar(); renderListArea(); });
      menu.appendChild(allBtn);
      STATUS_FILTERS.forEach((s) => {
        const label = h("label", {});
        const cb = h("input", { type: "checkbox", checked: S.statusFilter.has(s.key) });
        cb.addEventListener("change", () => {
          const next = new Set(S.statusFilter); next.delete("all");
          if (next.has(s.key)) next.delete(s.key); else next.add(s.key);
          S.statusFilter = next.size === 0 ? new Set(["all"]) : next;
          renderFilterBar(); renderListArea();
        });
        label.appendChild(cb); label.appendChild(document.createTextNode(s.label));
        menu.appendChild(label);
      });
    }));

    // [신규] 유사롬 찾기 - MasterDB 뷰에서 특정 시스템이 선택된 상태에서만 노출
    // (전체 시스템 한꺼번에 돌리면 느려서, 성능상 의도적으로 스코프를 좁힘)
    if (S.view === "masterdb" && S.selectedSystem !== "all") {
      const findBtn = h("button", { class: "btn" }, [icon("scale", 13), h("span", {}, ["유사롬 찾기"])]);
      findBtn.addEventListener("click", () => handleFindSimilarRoms(S.selectedSystem));
      root.appendChild(findBtn);
      const viewResultsBtn = h("button", { class: "btn" }, [icon("listFilter", 13), h("span", {}, ["결과 보기"])]);
      viewResultsBtn.addEventListener("click", () => openSimilarRomResults(S.selectedSystem));
      root.appendChild(viewResultsBtn);

      const groupLabel = h("label", { class: "similar-group-toggle" });
      const groupCb = h("input", { type: "checkbox", checked: S.groupSimilarRoms });
      groupCb.addEventListener("change", async (e) => {
        S.groupSimilarRoms = e.target.checked;
        if (S.groupSimilarRoms) await refreshSimilarGroupsCache(S.selectedSystem);
        renderListArea();
      });
      groupLabel.appendChild(groupCb);
      groupLabel.appendChild(h("span", {}, ["유사롬 묶기"]));
      root.appendChild(groupLabel);
    }

    // [단위 9] 즐겨찾기만 보기 - system 선택과 무관하게 ArchiveDB 화면 전체에서 항상 노출.
    if (S.view === "masterdb") {
      const favLabel = h("label", { class: "similar-group-toggle favorite-only-toggle", title: "즐겨찾기만 보기" });
      const favCb = h("input", { type: "checkbox", checked: S.favoriteOnly });
      favCb.addEventListener("change", (e) => { S.favoriteOnly = e.target.checked; renderListArea(); });
      favLabel.appendChild(favCb);
      favLabel.appendChild(icon("star", 12));
      favLabel.appendChild(h("span", {}, ["즐겨찾기"]));
      root.appendChild(favLabel);
    }

    const searchBox = h("div", { class: "searchbox", style: { flex: "1", maxWidth: "220px" } });
    searchBox.appendChild(icon("search", 12));
    const searchInput = h("input", { placeholder: "검색...", value: S.search });
    searchInput.addEventListener("input", (e) => { S.search = e.target.value; renderListArea(); });
    searchBox.appendChild(searchInput);
    root.appendChild(searchBox);

    const refreshBtn = h("button", { class: "btn" }, [icon("refresh", 13), h("span", {}, ["새로고침"])]);
    refreshBtn.addEventListener("click", handleRefresh);
    root.appendChild(refreshBtn);

    // [신규] 글자 크기 표시/초기화 버튼 (Shift+휠로 조절, 클릭하면 100%로 리셋)
    const fontScaleBtn = h("button", { class: "btn", title: "Shift + 마우스 휠로 글자 크기 조절" }, [
      h("span", { class: "font-scale-label" }, [`A ${Math.round(S.fontScale * 100)}%`]),
    ]);
    fontScaleBtn.addEventListener("click", resetFontScale);
    root.appendChild(fontScaleBtn);

    // [신규] 탐색기 스타일 미리보기 토글 - 필터바 맨 우측(우측 상단). 눌려있는 동안
    // Metadata Panel이 공간을 차지한다(선택 없으면 "선택된 항목이 없습니다"). 다시
    // 누르면 패널이 접히고, 이후 선택은 패널을 열지 않고 선택만 한다.
    const previewBtn = h("button", { class: "btn preview-toggle-btn" + (S.previewOn ? " active" : ""), title: S.previewOn ? "미리보기 끄기" : "미리보기 켜기" }, [icon("previewPane", 14), h("span", {}, ["미리보기"])]);
    previewBtn.addEventListener("click", togglePreview);
    root.appendChild(previewBtn);
  }

  // [단위 9] 즐겨찾기 토글 (별 클릭 또는 Space 키). ArchiveDB에서만 지원한다 - favorite는
  // SQLite-only 플래그라 GameListSet(원본 파일)에는 대응 개념이 없다.
  // [수정] 예전엔 백엔드 저장이 끝날 때까지 별 아이콘 UI를 안 바꾸고, 끝난 뒤에도
  // renderListArea()로 리스트 전체를 다시 그려서 클릭이 느리게 체감됐다(SQLite
  // targeted write 자체는 가벼운데, 그 왕복을 UI가 그대로 기다렸을 뿐). 클릭 즉시
  // 낙관적으로 별 아이콘만 patch하고(다중선택 patch와 같은 원리 - 리스트 전체를
  // 다시 만들지 않음), 저장은 뒤에서 진행해 실패하면 되돌린다.
  function applyFavoriteVisual(romKey, value) {
    document.querySelectorAll(`[data-rom-key="${CSS.escape(romKey)}"] .favorite-star`).forEach((btn) => {
      btn.classList.toggle("active", value);
      btn.title = value ? "즐겨찾기 해제" : "즐겨찾기로 지정";
    });
    if (detailState && detailState.romKey === romKey) { detailState.favorite = value; renderDetailPanel(); }
  }
  async function toggleGameFavorite(romKey, nextValue) {
    const g = S.games.find((x) => x.romKey === romKey);
    const prevValue = g ? !!g.favorite : false;
    if (g) g.favorite = nextValue;
    // "즐겨찾기만 보기" 필터가 켜져 있으면 이 토글로 행 자체가 리스트에 나타나거나
    // 사라져야 하므로 그때만 전체를 다시 그린다 - 그 외엔 별 아이콘만 patch한다.
    if (S.favoriteOnly && S.view === "masterdb") renderListArea();
    else applyFavoriteVisual(romKey, nextValue);

    const r = await api.setRomFavorite(romKey, nextValue);
    if (!r.ok) {
      showToast(r.error, "error");
      if (g) g.favorite = prevValue;
      if (S.favoriteOnly && S.view === "masterdb") renderListArea();
      else applyFavoriteVisual(romKey, prevValue);
    }
  }
  function favoriteStarButton(g) {
    const btn = h("button", {
      class: "favorite-star" + (g.favorite ? " active" : ""),
      title: g.favorite ? "즐겨찾기 해제" : "즐겨찾기로 지정",
    }, [icon("star", 13)]);
    btn.addEventListener("click", (e) => { e.stopPropagation(); toggleGameFavorite(g.romKey, !g.favorite); });
    return btn;
  }

  // ------------------------------------------------------------------
  // 게임 리스트 (List/Preview)
  // ------------------------------------------------------------------
  function statusDot(g) {
    const isEmpty = !g.title && !g.desc;
    if (isEmpty) return h("span", { style: { color: "var(--list-muted)" } }, ["-"]);
    const meta = STATUS_META[g.status] || { color: "muted", label: g.status };
    return h("span", { class: "status-dot-wrap" }, [
      h("span", { class: "status-dot", style: { background: `var(--${meta.color})` } }),
      h("span", { style: { color: "var(--list-text)" } }, [meta.label]),
    ]);
  }

  function renderListArea() {
    const container = document.getElementById("list-card-container");
    clear(container);

    // [신규] MasterDB가 아직 설정 안 된 상태에서 MasterDB 화면에 들어오면,
    // 빈 게임리스트 대신 "MasterDB 설정" 온보딩 화면을 보여준다.
    if (S.view === "masterdb" && !S.masterdb.configured) {
      container.appendChild(buildMasterdbOnboarding());
      const footlessCard = document.getElementById("detail-panel");
      if (footlessCard) footlessCard.classList.remove("open");
      return;
    }

    const list = getSortedFilteredGames();
    const renderSeq = ++S.diagRenderSeq;
    diag("RENDER_LIST", { renderSeq, totalGames: S.games.length, filteredGames: list.length,
      hasCoverTotal: S.games.filter((g) => !!g.hasCover).length, hasCoverFiltered: list.filter((g) => !!g.hasCover).length,
      multiSelect: S.multiSelect.size, selectedGame: S.selectedGame || "" });

    const card = h("div", { id: "list-card" });
    container.appendChild(card);

    if (S.viewMode === "preview") {
      const grid = h("div", { id: "preview-grid" });
      // [BUG FIX] 게임이 많을 때(예: 683개) 카드가 렌더링되는 순간 전부 동시에
      // 썸네일 API를 호출해서 브릿지가 과부하 걸리고 화면이 깨지던 문제.
      // IntersectionObserver로 실제 스크롤해서 화면에 보일 때만 낱개로 로딩한다.
      const localId = currentLocalId();
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const coverBox = entry.target;
          observer.unobserve(coverBox);
          const g = coverBox._game;
          if (!g || !g.hasCover) return;
          const thumbPromise = localId ? api.getLocalCoverThumbnail(localId, g.romKey) : api.getCoverThumbnail(g.romKey);
          thumbPromise.then((r) => {
            const seq = ++S.diagCoverSeq;
            if (seq <= 40 || !r.ok || !r.data) diag("CARD_COVER_RESULT", { seq, mode: "observer", localId: localId || "", romKey: g.romKey, hasCoverFlag: !!g.hasCover, ok: !!r.ok, dataPresent: !!r.data, error: r.error || "" });
            if (r.ok && r.data) {
              clear(coverBox);
              coverBox.appendChild(h("img", { src: r.data, alt: g.title || g.file }));
            }
          });
        });
      }, { root: null, rootMargin: "300px" });

      // 첫 화면은 Observer에만 의존하지 않고 먼저 소량만 로드한다. 685개 카드에서
      // 685개의 bridge 호출을 동시에 발생시키지 않으면서도 "ㅡ" 상태로 오래 남지 않게 한다.
      // Only preload the currently visible area. Do it in small parallel batches instead
      // of one-by-one bridge calls: the Python side now serves cached/resized thumbnails,
      // so a 1,000-card grid does not spend several seconds serializing full images.
      const eager = list.slice(0, 12);
      const loadCardCover = (g, mode) => {
        if (!g.hasCover) return Promise.resolve();
        const promise = localId ? api.getLocalCoverThumbnail(localId, g.romKey) : api.getCoverThumbnail(g.romKey);
        return promise.then((r) => {
          const seq = ++S.diagCoverSeq;
          const box = grid.querySelector(`[data-rom-key=\"${CSS.escape(g.romKey)}\"] .preview-cover`);
          if (seq <= 40 || !r.ok || !r.data) diag("CARD_COVER_RESULT", { seq, mode, localId: localId || "", romKey: g.romKey, hasCoverFlag: !!g.hasCover, ok: !!r.ok, dataPresent: !!r.data, boxFound: !!box, error: r.error || "" });
          if (r.ok && r.data && box) { clear(box); box.appendChild(h("img", { src: r.data, alt: g.title || g.file })); }
        });
      };
      const pumpEager = async () => {
        for (let i = 0; i < eager.length; i += 6) {
          await Promise.all(eager.slice(i, i + 6).map(g => loadCardCover(g, "eager")));
        }
      };

      list.forEach((g, i) => {
        const selected = S.selectedGame === g.romKey;
        const isMultiSelected = S.multiSelect.has(g.romKey);
        const coverBox = h("div", { class: "preview-cover" }, [icon("image", 26)]);
        coverBox._game = g;
        const item = h("button", { class: "preview-card" + (selected ? " selected" : "") + (isMultiSelected ? " multi-selected" : ""), "data-rom-key": g.romKey, onClick: (e) => handleRowClick(e, g, list, i), onMouseDown: (e) => startRowDragSelect(e, g, list, i) }, [
          coverBox,
          h("div", { class: "preview-title truncate", style: g.noMetadata ? { color: "var(--danger)", fontWeight: "600" } : null }, [
            S.view === "masterdb" ? favoriteStarButton(g) : null,
            g.title || g.file,
            g.similarGroupCount ? h("span", { class: "similar-group-badge" }, [`+${g.similarGroupCount - 1}`]) : null,
          ].filter(Boolean)),
        ]);
        grid.appendChild(item);
        if (g.hasCover) observer.observe(coverBox);
      });
      diag("PREVIEW_DOM_CREATED", { renderSeq, expectedCards: list.length, cardDomCount: grid.querySelectorAll(".preview-card").length,
        hasCoverFlagCount: list.filter((g) => !!g.hasCover).length, metadataOnlyCount: list.filter((g) => g.romMatched === false).length });
      pumpEager();
      if (list.length === 0) grid.appendChild(h("div", { class: "empty-msg" }, [S.scanningLocalId && S.scanningLocalId === currentLocalId() ? "스캔 중입니다..." : "조건에 맞는 게임이 없습니다."]));
      card.appendChild(grid);
      appendListFooter(card, list);
      return;
    }

    const scrollWrap = h("div", { id: "list-scroll" });
    const inner = h("div", { id: "list-inner" });
    scrollWrap.appendChild(inner);
    card.appendChild(scrollWrap);

    const cols = [
      { key: null, label: "No." }, { key: "file", label: "File" }, { key: "title", label: "Title" },
      { key: "desc", label: "Description" }, { key: "region", label: "Region" }, { key: "rating", label: "Rating" },
      { key: null, label: "★", fav: true }, { key: "genre", label: "Genre" }, { key: "status", label: "Status" },
    ];
    const header = h("div", { class: "grid-row grid-header", style: { gridTemplateColumns: gridTemplate() } });
    cols.forEach((c) => {
      const cell = h("div", { class: "grid-header-cell" + (S.sortField === c.key ? " sorted" : "") + (c.fav ? " fav-col" : "") }, [c.label]);
      if (c.key) {
        cell.addEventListener("click", () => {
          if (S.sortField === c.key) S.sortDir = S.sortDir === "asc" ? "desc" : "asc";
          else { S.sortField = c.key; S.sortDir = "asc"; }
          renderListArea();
        });
        if (S.sortField === c.key) cell.appendChild(icon(S.sortDir === "asc" ? "chevronUp" : "chevronDown", 11));
        const handle = h("div", { class: "col-resize-handle" });
        handle.addEventListener("mousedown", (e) => startColumnDrag(c.key, e));
        handle.addEventListener("click", (e) => e.stopPropagation());
        cell.appendChild(handle);
      }
      header.appendChild(cell);
    });
    inner.appendChild(header);

    list.forEach((g, i) => {
      const selected = S.selectedGame === g.romKey;
      const isMultiSelected = S.multiSelect.has(g.romKey);
      const row = h("div", {
        class: "grid-row grid-data-row" + (selected ? " selected" : "") + (isMultiSelected ? " multi-selected" : ""),
        "data-rom-key": g.romKey,
        style: { gridTemplateColumns: gridTemplate() },
        onClick: (e) => handleRowClick(e, g, list, i),
        onMouseDown: (e) => startRowDragSelect(e, g, list, i),
      }, [
        h("div", { class: "grid-cell no" }, [String(i + 1)]),
        h("div", { class: "grid-cell", style: g.noMetadata ? { color: "var(--danger)", fontWeight: "600" } : null }, [g.file]),
        h("div", { class: "grid-cell title" }, [
          g.title || "-",
          g.similarGroupCount ? h("span", { class: "similar-group-badge" }, [`+${g.similarGroupCount - 1}`]) : null,
        ].filter(Boolean)),
        h("div", { class: "grid-cell" }, [g.desc || "-"]),
        h("div", { class: "grid-cell" }, [g.region || "-"]),
        h("div", { class: "grid-cell" }, [g.rating ? String(g.rating) : "-"]),
        h("div", { class: "grid-cell fav-col" }, [S.view === "masterdb" ? favoriteStarButton(g) : null].filter(Boolean)),
        h("div", { class: "grid-cell" }, [g.genre || "-"]),
        h("div", { class: "grid-cell" }, [statusDot(g)]),
      ]);
      inner.appendChild(row);
    });
    if (list.length === 0) inner.appendChild(h("div", { class: "empty-msg" }, [S.scanningLocalId && S.scanningLocalId === currentLocalId() ? "스캔 중입니다..." : "조건에 맞는 게임이 없습니다."]));

    appendListFooter(card, list);
  }

  // [신규] 마우스 드래그로 범위 선택 (Windows 탐색기 스타일) - 수정키 없이 한 행을
  // 누른 채로 다른 행까지 끌면 그 사이 전체가 선택된다. 시작 행에서 움직임 없이
  // 그냥 놓으면(순수 클릭) 기존 handleRowClick의 클릭 동작이 그대로 실행되도록
  // suppressNextRowClick으로 "드래그였다"는 신호만 남긴다.
  let dragSelectState = null;
  let suppressNextRowClick = false;
  function startRowDragSelect(e, g, list, index) {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return; // 수정키 클릭은 기존 동작 그대로 둔다
    dragSelectState = { startIndex: index, list, moved: false };
    const onMove = (ev) => {
      if (!dragSelectState) return;
      const el = document.elementFromPoint(ev.clientX, ev.clientY);
      const rowEl = el && el.closest && el.closest("[data-rom-key]");
      if (!rowEl) return;
      const curIndex = dragSelectState.list.findIndex((x) => x.romKey === rowEl.dataset.romKey);
      if (curIndex < 0) return;
      if (curIndex !== dragSelectState.startIndex) dragSelectState.moved = true;
      if (!dragSelectState.moved) return;
      e.preventDefault();
      const [lo, hi] = curIndex < dragSelectState.startIndex ? [curIndex, dragSelectState.startIndex] : [dragSelectState.startIndex, curIndex];
      S.multiSelect = new Set(dragSelectState.list.slice(lo, hi + 1).map((x) => x.romKey));
      S.multiSelectAnchor = dragSelectState.list[dragSelectState.startIndex].romKey;
      updateMultiSelectVisual();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      if (dragSelectState && dragSelectState.moved) suppressNextRowClick = true;
      dragSelectState = null;
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  // [GUI 버그 수정] 다중선택할 때마다 renderListArea()로 리스트 전체를 다시 그려서,
  // 클릭할 때마다 화면 전체가 깜박였다(썸네일 재로드, 스크롤 위치 흔들림 포함).
  // 실제로 바뀌는 건 이번에 선택/해제된 행 몇 개의 클래스뿐이므로,
  // 전체 리스트를 다시 만들지 않고 그 부분만 직접 갱신한다.
  function updateMultiSelectVisual() {
    document.querySelectorAll(".preview-card, .grid-data-row").forEach((el) => {
      const key = el.dataset.romKey;
      if (key) el.classList.toggle("multi-selected", S.multiSelect.has(key));
    });
  }

  // [신규] 게임 리스트 키보드 네비게이션 (방향키/PageUp·Down/Home/End/Enter)
  // [신규] 게임 삭제용 다중선택 - Ctrl+Click(개별 토글), Ctrl+Shift+Click(범위 선택)
  function handleRowClick(e, g, list, index) {
    if (suppressNextRowClick) { suppressNextRowClick = false; return; }
    diag("LIST_SELECTION", { action: "click", romKey: g.romKey, index, ctrl: !!(e.ctrlKey || e.metaKey), shift: !!e.shiftKey, multiCountBefore: S.multiSelect.size });
    // [신규] Ctrl 없이 Shift만 누른 채 클릭 - 표준 파일탐색기 관례대로 마지막 선택
    // 지점부터 지금 클릭한 항목까지를 범위로 선택하고, 기존 선택은 대체한다
    // (Ctrl+Shift+Click은 기존 선택에 범위를 "추가"하는 것과 다름).
    if (e.shiftKey && !(e.ctrlKey || e.metaKey)) {
      const anchorKey = S.multiSelectAnchor || S.selectedGame;
      const anchorIdx = anchorKey ? list.findIndex((x) => x.romKey === anchorKey) : -1;
      if (anchorIdx >= 0) {
        const [lo, hi] = anchorIdx < index ? [anchorIdx, index] : [index, anchorIdx];
        S.multiSelect = new Set(list.slice(lo, hi + 1).map((x) => x.romKey));
      } else {
        S.multiSelect = new Set([g.romKey]);
        S.multiSelectAnchor = g.romKey;
      }
      updateMultiSelectVisual();
      return;
    }
    if (e.ctrlKey || e.metaKey) {
      if (e.shiftKey && S.multiSelectAnchor != null) {
        const anchorIdx = list.findIndex((x) => x.romKey === S.multiSelectAnchor);
        if (anchorIdx >= 0) {
          const [lo, hi] = anchorIdx < index ? [anchorIdx, index] : [index, anchorIdx];
          for (let i = lo; i <= hi; i++) S.multiSelect.add(list[i].romKey);
        }
      } else {
        if (S.multiSelect.has(g.romKey)) S.multiSelect.delete(g.romKey);
        else S.multiSelect.add(g.romKey);
        S.multiSelectAnchor = g.romKey;
      }
      updateMultiSelectVisual();
      return;
    }
    // 일반 클릭: 다중선택을 완전히 단일 선택으로 되돌린 뒤 즉시 repaint.
    // 이전에는 Set만 비우고 DOM을 다시 그리지 않아 기존 multi-selected 클래스가
    // 화면에 남아 "다중선택이 유지되는 것처럼" 보였다.
    if (S.multiSelect.size > 0) {
      S.multiSelect.clear(); S.multiSelectAnchor = null;
      renderListArea();
    }
    openDetail(g);
  }

  // [단순화] 항상 metadata + Rom을 함께 삭제한다. 이전에는 상단에 상시 노출되는
  // [ ]metadata [ ]Rom 체크박스 바가 있었는데, 거의 항상 둘 다 켜둔 채 쓰였고
  // 화면만 차지해서 제거했다 (사용자 요청).
  function executeDelete() {
    if (S.multiSelect.size === 0 && !S.selectedGame) return;
    const romKeys = S.multiSelect.size ? Array.from(S.multiSelect) : (S.selectedGame ? [S.selectedGame] : []);
    const localId = currentLocalId();
    const targets = [];
    if (S.deleteTargets.metadata) targets.push("metadata");
    if (S.deleteTargets.rom) targets.push("ROM 파일");
    showConfirm(
      "게임 삭제",
      `선택한 ${romKeys.length}개 게임의 ${targets.join(" + ")}을(를) 삭제합니다. 이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?`,
      true,
      async () => {
        closeConfirm();
        const r = localId
          ? await api.deleteLocalGames(localId, romKeys, S.deleteTargets.metadata, S.deleteTargets.rom)
          : await api.deleteMasterdbGames(romKeys, S.deleteTargets.metadata, S.deleteTargets.rom);
        if (r.ok) {
          const skipped = !localId && r.data && r.data.favoriteSkipped;
          showToast(
            skipped
              ? `삭제 완료 (즐겨찾기 ${skipped}개는 자동 제외됨)`
              : `삭제 완료 (${romKeys.length}개 대상 처리됨)`,
            "warning"
          );
          S.multiSelect.clear();
          S.multiSelectAnchor = null;
          romKeys.forEach((k) => { delete S.detailCache[`${localId || "masterdb"}|${k}`]; });

          // 삭제 직후 Refresh List를 다시 호출하지 않는다.
          // 10,000개 규모 Local에서 Delete -> 전체 스캔이 발생하면 매우 느리고,
          // 사용자가 요청한 "삭제 작업 자체는 즉시 반영" 동작과도 맞지 않는다.
          if (localId) {
            const deleted = new Set(romKeys);
            if (S.deleteTargets.rom) {
              S.games = S.games.filter((g) => !deleted.has(g.romKey));
            } else if (S.deleteTargets.metadata) {
              S.games = S.games.map((g) => deleted.has(g.romKey)
                ? { ...g, title: "", desc: "", status: "누락", missingMedia: true, noMetadata: true, hasCover: false }
                : g);
            }
            setLocalGamesCache(localId, S.games, true);
            const localInfo = S.locals.find((l) => l.id === localId);
            if (localInfo) localInfo.stats = { ...(localInfo.stats || {}), rom_count: S.games.length };
            await refreshMutationState();
          } else {
            if (S.deleteTargets.metadata) S.games = S.games.filter((g) => !romKeys.includes(g.romKey));
            if (S.deleteTargets.rom) S.games = S.games.map((g) => romKeys.includes(g.romKey) ? { ...g, status: "누락" } : g);
            await refreshMutationState();
          }
        } else {
          showToast(r.error, "error");
        }
      }
    );
  }

  function handleListKeyDown(e, list) {
    if (!list.length) return;
    const currentIndex = S.selectedGame ? list.findIndex((g) => g.romKey === S.selectedGame) : -1;
    let nextIndex = currentIndex < 0 ? 0 : currentIndex;

    if (S.viewMode === "preview") {
      const cards = Array.from(document.querySelectorAll("#preview-grid .preview-card"));
      // Determine the actual CSS grid column count from the rendered row positions.
      // Never infer it from width: fractional zoom/layout widths caused diagonal movement.
      let cols = 1;
      if (cards.length > 1) {
        const firstTop = cards[0].offsetTop;
        const firstRowCount = cards.findIndex((el) => el.offsetTop !== firstTop);
        cols = firstRowCount > 0 ? firstRowCount : cards.length;
      }
      if (e.key === "ArrowLeft") nextIndex = Math.max(0, nextIndex - 1);
      else if (e.key === "ArrowRight") nextIndex = Math.min(list.length - 1, nextIndex + 1);
      else if (e.key === "ArrowUp") nextIndex = Math.max(0, nextIndex - cols);
      else if (e.key === "ArrowDown") nextIndex = Math.min(list.length - 1, nextIndex + cols);
      else if (e.key === "PageDown") nextIndex = Math.min(list.length - 1, nextIndex + cols * 5);
      else if (e.key === "PageUp") nextIndex = Math.max(0, nextIndex - cols * 5);
      else if (e.key === "Home") nextIndex = 0;
      else if (e.key === "End") nextIndex = list.length - 1;
      else if (e.key === "Enter" && currentIndex >= 0) { openDetail(list[currentIndex], { forceShow: true }); e.preventDefault(); return; }
      else return;
    } else {
      if (e.key === "ArrowDown" || e.key === "ArrowRight") nextIndex = Math.min(list.length - 1, nextIndex + 1);
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") nextIndex = Math.max(0, nextIndex - 1);
      else if (e.key === "PageDown") nextIndex = Math.min(list.length - 1, nextIndex + 10);
      else if (e.key === "PageUp") nextIndex = Math.max(0, nextIndex - 10);
      else if (e.key === "Home") nextIndex = 0;
      else if (e.key === "End") nextIndex = list.length - 1;
      else if (e.key === "Enter" && currentIndex >= 0) { openDetail(list[currentIndex], { forceShow: true }); e.preventDefault(); return; }
      else return;
    }
    e.preventDefault();
    diag("LIST_SELECTION", { action: "keyboard", key: e.key, fromIndex: currentIndex, toIndex: nextIndex, romKey: list[nextIndex]?.romKey || "" });
    openDetail(list[nextIndex]);
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-rom-key="${CSS.escape(list[nextIndex].romKey)}"]`);
      if (el) el.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
  }

  function appendListFooter(card, list) {
    const footer = h("div", { class: "list-footer" }, [
      h("div", { class: "list-footer-summary" }, [`전체 ${list.length.toLocaleString()}개　|　선택 ${S.selectedGame ? 1 : 0}개`]),
    ]);
    const actions = h("div", { class: "list-footer-actions" });
    const leftBtns = h("div", { class: "flex gap-2", style: { flexWrap: "wrap" } });
    // [수정] CleanUp/Prune Data는 자주 안 쓰고 위험도도 있는 작업이라 "More ⋮"
    // 메뉴로 뺐다 - 남는 자리엔 새로고침/Export처럼 자주 쓰는 안전한 액션만 둔다.
    // 둘을 안에서도 구분: Prune Data(고아 metadata/media만 청소, 상대적으로 안전)는
    // 기본 스타일, CleanUp(이 GameListSet의 metadata/media를 통째로 초기화, 더
    // 파괴적)은 danger 색으로 다르게 표시한다.
    [
      ["refresh", "Refresh List (F5)", handleRefresh],
      ...(S.view === "masterdb" ? [["download", "Export to GameListSet", handleExportToLocal]] : [["upload", "Export to ArchiveDB", handleExport], ["download", "Import from ArchiveDB", handleImportFromMasterDB]]),
    ].forEach(([iconName, label, fn]) => {
      const b = h("button", { class: "btn light" }, [icon(iconName, 12.5), h("span", {}, [label])]);
      b.addEventListener("click", fn);
      leftBtns.appendChild(b);
    });
    const moreBtn = h("button", { class: "btn light", title: "CleanUp / Prune Data" }, [icon("moreHorizontal", 13)]);
    moreBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeDropdowns();
      const rect = moreBtn.getBoundingClientRect();
      openBodyMenu(moreBtn, { bottom: (window.innerHeight - rect.top + 6) + "px", left: rect.left + "px" }, (menu, close) => {
        const pruneBtn = h("button", {}, [icon("eraser", 12.5), h("span", {}, ["Prune Data"])]);
        pruneBtn.addEventListener("click", () => { close(); handlePrune(); });
        const cleanupBtn = h("button", { class: "danger-text" }, [icon("sparkles", 12.5), h("span", {}, ["CleanUp"])]);
        cleanupBtn.addEventListener("click", () => { close(); handleCleanup(); });
        menu.appendChild(pruneBtn);
        menu.appendChild(cleanupBtn);
      });
    });
    leftBtns.appendChild(moreBtn);
    actions.appendChild(leftBtns);
    actions.appendChild(h("div", { style: { fontSize: "calc(11px * var(--font-scale))", color: "var(--list-muted)" } }, [`Ready · 총 ${list.length.toLocaleString()}개 게임`]));
    footer.appendChild(actions);
    card.appendChild(footer);
  }

  function startColumnDrag(key, e) {
    const startX = e.clientX;
    const startWidth = S.colWidths[key];
    document.body.style.cursor = "col-resize";
    function onMove(ev) {
      const delta = ev.clientX - startX;
      S.colWidths[key] = Math.max(COL_MIN_WIDTH, startWidth + delta);
      const headerRow = document.querySelector(".grid-header");
      document.querySelectorAll(".grid-row").forEach((r) => (r.style.gridTemplateColumns = gridTemplate()));
    }
    function onUp() {
      document.body.style.cursor = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    e.preventDefault();
    e.stopPropagation();
  }

  // ------------------------------------------------------------------
  // [신규] 백그라운드 job 진행률 표시 + 폴링 공용 헬퍼
  // ------------------------------------------------------------------
  function showJobProgress(title, jobId) {
    const bar = document.getElementById("job-progress");
    bar.classList.add("show");
    bar.innerHTML = "";
    const titleRow = h("div", { class: "job-progress-title-row" });
    titleRow.appendChild(h("div", { class: "job-progress-title" }, [title]));
    if (jobId) {
      const cancelBtn = h("button", { class: "job-progress-cancel" }, ["취소"]);
      cancelBtn.addEventListener("click", () => {
        cancelBtn.disabled = true;
        cancelBtn.textContent = "취소 중...";
        api.cancelJob(jobId);
      });
      titleRow.appendChild(cancelBtn);
    }
    bar.appendChild(titleRow);
    const row = h("div", { class: "job-progress-row" });
    row.appendChild(h("div", { class: "job-progress-bar" }, [h("div", { class: "job-progress-bar-fill", id: "job-progress-bar-fill", style: { width: "0%" } })]));
    row.appendChild(h("div", { class: "job-progress-pct", id: "job-progress-pct" }, ["0%"]));
    bar.appendChild(row);
    bar.appendChild(h("div", { class: "job-progress-label", id: "job-progress-label" }, ["시작 중..."]));
  }
  function updateJobProgress(current, total, label) {
    const fillEl = document.getElementById("job-progress-bar-fill");
    const pctEl = document.getElementById("job-progress-pct");
    const labelEl = document.getElementById("job-progress-label");
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    if (fillEl) fillEl.style.width = pct + "%";
    if (pctEl) pctEl.textContent = `${pct}%`;
    if (labelEl) labelEl.textContent = label ? `${label} (${current}/${total})` : `${current}/${total}`;
  }
  function hideJobProgress() {
    document.getElementById("job-progress").classList.remove("show");
  }

  // [신규] Compare 행 복사처럼 background job이 아니라 단발 await 하나로 끝나는
  // 동작도, 다른 Import/Export와 똑같이 #job-progress를 보여줘야 "동작이 실제로
  // 일어나는 중"이라는 인식이 일관되게 유지된다. 실제 %는 알 수 없으니 줄무늬
  // 애니메이션(indeterminate)으로 표시하고, 끝나면 그대로 숨긴다.
  async function runIndeterminateProgress(promise, title) {
    showJobProgress(title, null);
    const fillEl = document.getElementById("job-progress-bar-fill");
    const pctEl = document.getElementById("job-progress-pct");
    const labelEl = document.getElementById("job-progress-label");
    if (fillEl) fillEl.classList.add("indeterminate");
    if (pctEl) pctEl.textContent = "";
    if (labelEl) labelEl.textContent = "진행 중...";
    try {
      return await promise;
    } finally {
      hideJobProgress();
    }
  }

  /**
   * jobId 하나만 진행률 바로 보여주며 끝날 때까지 폴링한다(체이닝 없음) - 다음
   * phase가 있어도(followUpJobId) 신경 쓰지 않고 이 job이 done되는 즉시 바를
   * 숨기고 반환한다. Scan처럼 "1단계만 빠르게 받고 나머지는 조용히" 흐름에서 쓴다.
   * 반환: Promise<{ok, data, error}>
   */
  function pollSingleJobWithProgress(jobId, title) {
    return new Promise((resolve) => {
      showJobProgress(title, jobId);
      const poll = async () => {
        const p = await api.getJobProgress(jobId);
        if (!p.ok) { hideJobProgress(); resolve({ ok: false, error: p.error }); return; }
        const job = p.data;
        updateJobProgress(job.current, job.total, job.label);
        if (job.done) {
          hideJobProgress();
          if (job.error) resolve({ ok: false, error: job.error });
          else resolve({ ok: true, data: job.result });
          return;
        }
        setTimeout(poll, 200);
      };
      poll();
    });
  }

  /**
   * startFnResult: api.startXxx() 호출 결과 { ok, data: { jobId } } 또는 { ok:false, error }
   * title: 진행률 바 상단에 표시할 제목
   * 반환: Promise<{ok, data, error}> - 모든 phase가 끝난 뒤 최종 결과
   *
   * [체감 속도, 다단계 job] 결과에 "followUpJobId"가 있으면(Export/Import의
   * 커버->기타미디어->비디오 3단계 등) 바를 숨기지 않고 그 다음 job으로 이어서
   * 폴링한다 - 사용자 눈엔 진행률 바 하나가 "(1/3)->(2/3)->(3/3)" 순서대로 넘어가는
   * 것처럼 보인다. followUpJobId가 없는 평범한 단일 job(CleanUp/Prune/유사롬 탐색
   * 등)은 예전과 동일하게 한 번만 폴링하고 끝난다.
   */
  async function runJobWithProgress(startFnResult, title) {
    if (!startFnResult.ok) return { ok: false, error: startFnResult.error };
    let jobId = startFnResult.data.jobId;
    for (;;) {
      const r = await pollSingleJobWithProgress(jobId, title);
      if (!r.ok || !r.data || !r.data.followUpJobId) return r;
      jobId = r.data.followUpJobId;
    }
  }

  // [체감 속도, Scan 2단계] 1단계/2단계 결과를 화면에 반영하는 로직을 한 곳에
  // 모아둔다 - runScanJobWithProgress가 1단계 결과에 곧바로 이걸 적용하고, 뒤이어
  // 2단계(follow-up)가 끝나면 같은 함수로 다시 적용한다. 예전엔 호출부(예:
  // _ensureLocalScannedOnce)가 job1의 결과를 캡처해 자기 나름대로 또 한 번
  // S.games/renderAll()을 부르고 있어서, 그 지연된(await loadLocals() 등을 거친)
  // "예전(partial) 데이터 재적용"이 follow-up의 최신 렌더를 덮어써버리는 경합이
  // 있었다 - 이제 호출부는 이 함수에만 위임하고 자기 나름의 games/render를 따로
  // 하지 않는다.
  function applyScanResultToUI(localId, data) {
    const games = (data.games || []).map((g) => ({ ...g, system: normalizeSystemName(g.system) }));
    setLocalGamesCache(localId, games, true);
    if (currentLocalId() === localId) {
      S.games = games;
      renderListArea();
    }
    return games;
  }

  /**
   * onFullyDone: [Parent Job lifecycle 수정] 1단계(job1)가 끝나면 목록은 바로
   * 보여주지만, "완료" 같은 마무리 처리(토스트 등)는 여기로 넘겨서 실제로 모든
   * phase(2단계까지 포함)가 끝난 뒤에만 부르게 한다 - 예전엔 호출부가 job1이
   * 끝나는 즉시(2단계가 아직 백그라운드에서 도는 중인데도) "Refresh 완료" 토스트를
   * 띄워서, 사용자에게 실제로는 안 끝난 걸 끝났다고 알리는 상태였다. defer가
   * 꺼져 있어 phase가 하나뿐이면 그 즉시 onFullyDone도 같이 불린다.
   *
   * [P0-2 수정] 예전엔 2단계를 진행률 바 없이 조용히(pollFollowUpJobSilently) 폴링
   * 했지만, 이건 "phase마다 독립적으로 0->100%인 progress bar 하나가 순서대로
   * 단계를 넘어간다"는 요구사항과 맞지 않는다 - phase 1이 끝났다고 바를 숨기면
   * 사용자는 2단계가 진행 중이라는 걸 전혀 알 수 없다. 이제 phase 1과 마찬가지로
   * pollSingleJobWithProgress로 2단계도 같은 바에서 계속 진행률을 보여준다(0%로
   * 리셋되는 게 정상 - 진행률 label에 "(2/2)"가 붙어 있어 새 단계임을 알 수 있다).
   * 목록 자체는 phase 1 완료 직후 이미 화면에 반영돼 있으므로(applyScanResultToUI),
   * 2단계가 도는 동안에도 GameList는 계속 사용 가능하다.
   */
  async function runScanJobWithProgress(startFnResult, title, localId, onFullyDone) {
    if (!startFnResult.ok) {
      const failed = { ok: false, error: startFnResult.error };
      if (onFullyDone) onFullyDone(failed);
      return failed;
    }
    const r = await pollSingleJobWithProgress(startFnResult.data.jobId, title);
    if (r.ok && r.data) {
      applyScanResultToUI(localId, r.data);
      if (r.data.followUpJobId) {
        const r2 = await pollSingleJobWithProgress(r.data.followUpJobId, title);
        if (r2.ok && r2.data) applyScanResultToUI(localId, r2.data);
        if (onFullyDone) onFullyDone(r2);
        return r2;
      } else if (onFullyDone) {
        onFullyDone(r);
      }
    } else if (onFullyDone) {
      onFullyDone(r);
    }
    return r;
  }

  // ------------------------------------------------------------------
  // 액션: Refresh / CleanUp / Prune / Export
  // ------------------------------------------------------------------
  function currentLocalId() { return S.view.startsWith("local-") ? S.view.replace("local-", "") : null; }

  // Local cache is the authoritative in-memory snapshot for view switching.
  // Never store S.games by reference: S.games is replaced whenever the view changes
  // (e.g. Local -> MasterDB), and accidental reuse of that array can make a Local
  // cache appear empty.  The explicit allowEmpty flag is used only after a real
  // Local mutation/refresh that legitimately results in zero games.
  function setLocalGamesCache(localId, games, allowEmpty = false) {
    if (!localId || !Array.isArray(games)) return false;
    if (!allowEmpty && games.length === 0) {
      const existing = S.localGamesCache[localId];
      if (existing && Array.isArray(existing.games) && existing.games.length > 0) return false;
    }
    S.localGamesCache[localId] = {
      games: games.map((g) => ({ ...g })),
      loaded: true,
      updatedAt: Date.now(),
    };
    diag("LOCAL_CACHE_SET", { localId, count: games.length, allowEmpty, sourceView: S.view });
    return true;
  }

  async function handleRefresh() {
    const localId = currentLocalId();
    if (localId) {
      // [체감 속도, Scan 2단계] S.games/cache/렌더는 runScanJobWithProgress가
      // job1과 뒤이은 follow-up 둘 다에 대해 이미 처리해준다. "완료" 토스트는
      // [Parent Job lifecycle 수정] 2단계까지 실제로 다 끝난 뒤(onFullyDone)에만
      // 띄운다 - 1단계만 끝난 시점에 완료라고 알리면 사용자가 오해할 수 있다.
      // onFullyDone이 성공/실패 모든 경로에서 정확히 한 번 불리므로 별도 처리는 없다.
      // [P0-4] runScanForLocal()을 거쳐서, Scan이 이미 진행 중일 때 새로고침을
      // 연타해도 같은 Local에 대해 폴링 체인이 여러 개 뜨지 않는다.
      await runScanForLocal(localId, "Refresh List", (full) => {
        if (full.ok) showToast("Refresh 완료 — 최신 상태입니다.");
        else showToast(full.error, "error");
      });
    } else {
      await loadGamesForView();
      renderListArea();
      showToast("Refresh 완료 — 최신 상태입니다.");
    }
  }

  function handleCleanup() {
    const localId = currentLocalId();
    if (!localId) { showToast("ArchiveDB 화면에서는 CleanUp을 사용할 수 없습니다. GameListSet을 선택하세요.", "warning"); return; }
    showConfirm("Reset Metadata (CleanUp)", "이 Local의 모든 metadata/media가 삭제됩니다. 계속하시겠습니까?", true, async () => {
      closeConfirm();
      const r = await runJobWithProgress(await api.startResetMetadata(localId), "CleanUp 진행 중");
      if (r.ok) { showToast("CleanUp 완료.", "warning"); await handleRefresh(); }
      else showToast(r.error, "error");
    });
  }

  function handlePrune() {
    const localId = currentLocalId();
    if (!localId) { showToast("ArchiveDB 화면에서는 Prune Data를 사용할 수 없습니다. GameListSet을 선택하세요.", "warning"); return; }
    showConfirm("Orphan Cleanup (Prune Data)", "ROM이 없는 고아 metadata/media를 삭제합니다. 계속하시겠습니까?", true, async () => {
      closeConfirm();
      const r = await runJobWithProgress(await api.startOrphanCleanup(localId), "Prune Data 진행 중");
      if (r.ok) { showToast(`Prune 완료 — ${r.data.removedCount}개 삭제됨.`, "warning"); await handleRefresh(); }
      else showToast(r.error, "error");
    });
  }

  function openMediaTransferPicker(title, localId, targetKeys) {
    const root = document.getElementById("modal-root"); clear(root);
    const overlay = h("div", { class: "modal-overlay" });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) clear(root); });
    const box = h("div", { class: "modal-box modal-w-md" });
    box.addEventListener("click", (e) => e.stopPropagation());
    box.appendChild(h("div", { class: "modal-title" }, [title]));
    box.appendChild(h("div", { class: "modal-message", style: { marginBottom: "10px" } }, ["가져올 Media 종류를 선택하세요."]));
    const defaults = (S.settings.exportOptions && S.settings.exportOptions.selected_media_types) || ["screenshots", "3dboxes", "covers", "marquees", "miximages", "wheel"];
    const types = [
      ["screenshots", "Screenshots"], ["3dboxes", "3DBoxes"], ["covers", "Covers"],
      ["marquees", "Marquees"], ["miximages", "MixImages"], ["wheel", "Wheel"]
    ];
    const checks = {};
    const grid = h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "7px 10px", marginBottom: "10px" } });
    types.forEach(([key, label]) => {
      const row = h("label", { class: "settings-checkbox-row", style: { margin: 0 } });
      const cb = h("input", { type: "checkbox", checked: defaults.includes(key) }); checks[key] = cb;
      row.appendChild(cb); row.appendChild(h("span", {}, [label])); grid.appendChild(row);
    });
    box.appendChild(grid);
    box.appendChild(h("hr", { style: { border: 0, borderTop: "1px solid var(--border)", margin: "8px 0" } }));
    const videoRow = h("label", { class: "settings-checkbox-row", style: { margin: "7px 0" } });
    const videoCb = h("input", { type: "checkbox", checked: defaults.includes("videos") });
    videoRow.appendChild(videoCb); videoRow.appendChild(h("span", {}, ["Videos"])); box.appendChild(videoRow);
    box.appendChild(h("hr", { style: { border: 0, borderTop: "1px solid var(--border)", margin: "8px 0" } }));
    const romRow = h("label", { class: "settings-checkbox-row", style: { margin: "7px 0" } });
    const romCb = h("input", { type: "checkbox", checked: !!S.settings.exportOptions.copy_rom });
    romRow.appendChild(romCb); romRow.appendChild(h("span", {}, ["ROMS"])); box.appendChild(romRow);
    const actions = h("div", { class: "modal-actions", style: { display: "flex", justifyContent: "flex-end", gap: "7px", marginTop: "12px" } });
    const cancel = h("button", { class: "btn" }, ["취소"]); cancel.addEventListener("click", () => clear(root));
    const go = h("button", { class: "btn primary" }, ["가져오기"]);
    go.addEventListener("click", async () => {
      const mediaTypes = types.filter(([key]) => checks[key].checked).map(([key]) => key);
      if (videoCb.checked) mediaTypes.push("videos");
      clear(root);
      if (title.startsWith("Import from ArchiveDB")) {
        const r = await runJobWithProgress(await api.startExportToLocal(localId, targetKeys, mediaTypes, romCb.checked), title + " 진행 중");
        if (r.ok) { showToast(`${title} 완료 — ${r.data.exported || 0}개`); await handleRefresh(); }
        else showToast(r.error, "error");
      } else {
        const r = await runJobWithProgress(await api.startExportToLocal(localId, targetKeys, mediaTypes, romCb.checked), title + " 진행 중");
        if (r.ok) { showToast(`${title} 완료 — ${r.data.exported || 0}개`); await refreshMutationState(); }
        else showToast(r.error, "error");
      }
    });
    actions.appendChild(cancel); actions.appendChild(go); box.appendChild(actions);
    overlay.appendChild(box); root.appendChild(overlay);
  }

  function handleExportToLocal() {
    if (S.view !== "masterdb") return;
    const system = S.selectedSystem === "all" ? null : S.selectedSystem;
    const targetKeys = system ? S.games.filter((g) => g.system === system).map((g) => g.romKey) : S.games.map((g) => g.romKey);
    if (!targetKeys.length) { showToast("Export할 게임이 없습니다.", "warning"); return; }
    const localRoot = document.getElementById("modal-root"); clear(localRoot);
    const overlay = h("div", { class: "modal-overlay" });
    const box = h("div", { class: "modal-box modal-w-sm" });
    box.appendChild(h("div", { class: "modal-title" }, [system ? `Export to GameListSet — ${system}` : "Export to GameListSet — 전체 시스템"]));
    S.locals.forEach((local) => {
      const b = h("button", { class: "export-mode-item" }, [h("div", { class: "export-mode-label" }, [local.label]), h("div", { class: "export-mode-desc" }, [local.frontendLabel || local.frontend])]);
      b.addEventListener("click", () => { clear(localRoot); openMediaTransferPicker(`Export to GameListSet → ${local.label}`, local.id, targetKeys); });
      box.appendChild(b);
    });
    const cancel = h("button", { class: "btn block-action" }, ["취소"]);
    cancel.addEventListener("click", () => clear(localRoot)); box.appendChild(cancel); overlay.appendChild(box); localRoot.appendChild(overlay);
  }

  async function handleImportFromMasterDB() {
    const localId = currentLocalId();
    if (!localId) { showToast("GameListSet을 선택하세요.", "warning"); return; }
    const system = S.selectedSystem === "all" ? null : S.selectedSystem;
    let targetKeys = null;
    if (system) {
      const mr = await api.listMasterdbGames();
      if (!mr.ok) { showToast(mr.error, "error"); return; }
      targetKeys = mr.data.filter(g => normalizeSystemName(g.system) === system).map(g => g.romKey);
    }
    openMediaTransferPicker(`Import from ArchiveDB → ${S.locals.find(l => l.id === localId)?.label || "GameListSet"}`, localId, targetKeys);
  }

  function handleExport() {
    const localId = currentLocalId();
    if (!localId) { showToast("ArchiveDB 화면에서는 'Export to GameListSet'을 사용하세요.", "warning"); return; }
    const system = S.selectedSystem === "all" ? null : S.selectedSystem;
    const targetKeys = system ? S.games.filter((g) => g.system === system).map((g) => g.romKey) : null;
    openExportToMasterdbPicker(localId, targetKeys, system);
  }

  // [단위 8] 유사롬 묶어보기 토글이 참조하는 캐시를 새로고침한다.
  async function refreshSimilarGroupsCache(system) {
    const r = await api.getSimilarRomGroups(system);
    if (r.ok) S.similarGroupsCache[system] = r.data;
    return r;
  }

  // [신규] 유사롬 찾기 실행 + 결과 보기
  async function handleFindSimilarRoms(system) {
    const r = await runJobWithProgress(await api.startFindSimilarRoms(system), `${system.toUpperCase()} 유사롬 탐색 중`);
    if (r.ok) {
      showToast(`유사롬 탐색 완료 — ${r.data.groups.length}개 그룹 발견`);
      if (S.groupSimilarRoms) { await refreshSimilarGroupsCache(system); renderListArea(); }
      openSimilarRomResults(system);
    } else {
      showToast(r.error, "error");
    }
  }

  async function openSimilarRomResults(system) {
    const r = await api.getSimilarRomGroups(system);
    const root = document.getElementById("modal-root");
    clear(root);
    const overlay = h("div", { class: "modal-overlay" });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) clear(root); });
    const box = h("div", { class: "modal-box modal-w-lg modal-scroll" });
    box.addEventListener("click", (e) => e.stopPropagation());
    box.appendChild(h("div", { class: "modal-title" }, [`${system.toUpperCase()} 유사롬 결과`]));

    if (!r.ok) {
      box.appendChild(h("p", { class: "modal-message" }, [r.error]));
    } else if (r.data.length === 0) {
      box.appendChild(h("p", { class: "modal-message" }, ["아직 결과가 없습니다. 먼저 '유사롬 찾기'를 실행하세요."]));
    } else {
      box.appendChild(h("p", { class: "modal-message" }, ["대표로 지정할 항목의 별표를 누르세요. 다시 누르면 해제됩니다."]));
      r.data.forEach((group, gi) => {
        const groupBox = h("div", { class: "similar-group" });
        groupBox.appendChild(h("div", { class: "similar-group-title" }, [`그룹 ${gi + 1} (${group.members.length}개)`]));
        group.members.forEach((m) => {
          const isRep = group.representative === m.romKey;
          const row = h("div", { class: "similar-group-member" + (isRep ? " is-representative" : "") });
          const star = h("button", {
            class: "icon-btn similar-rep-btn" + (isRep ? " active" : ""),
            title: isRep ? "대표 해제" : "대표로 지정",
          }, [icon("star", 13)]);
          star.addEventListener("click", async () => {
            const res = await api.setSimilarGroupRepresentative(group.groupId, isRep ? null : m.romKey);
            if (res.ok) {
              if (S.groupSimilarRoms) { await refreshSimilarGroupsCache(system); renderListArea(); }
              openSimilarRomResults(system);
            } else showToast(res.error, "error");
          });
          row.appendChild(star);
          row.appendChild(h("span", { class: "truncate", style: { flex: "1" } }, [m.title || m.file]));
          row.appendChild(h("span", { style: { color: "var(--muted)", fontSize: "calc(10px * var(--font-scale))" } }, [m.file]));
          groupBox.appendChild(row);
        });
        box.appendChild(groupBox);
      });
    }
    const closeBtn = h("button", { class: "btn block-action" }, ["닫기"]);
    closeBtn.addEventListener("click", () => clear(root));
    box.appendChild(closeBtn);
    overlay.appendChild(box);
    root.appendChild(overlay);
  }

  // [GUI 정돈] 예전엔 "Export MetaData / Export Roms / Export MetaData + Roms" 3개
  // 버튼 중 하나를 고르는 방식이었다 - Media 타입은 선택할 수 없이 항상 전부
  // 복사됐다. Settings > Media와 동일한 Metadata/Media/Rom 선택 대화상자로 통일한다.
  // 기본값은 Settings의 값을 불러오되, 여기서 바꾼 선택은 이번 1회 실행에만
  // 적용되고 Settings에는 저장되지 않는다(휘발성).
  function openExportToMasterdbPicker(localId, targetKeys, system) {
    const root = document.getElementById("modal-root");
    clear(root);
    const overlay = h("div", { class: "modal-overlay" });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) clear(root); });
    const box = h("div", { class: "modal-box modal-w-md" });
    box.addEventListener("click", (e) => e.stopPropagation());
    box.appendChild(h("div", { class: "modal-title" }, [system ? `Export to ArchiveDB — ${system}` : "Export to ArchiveDB — 전체 시스템"]));

    const opts = S.settings.exportOptions || {};
    // renderTransferCheckboxGroups가 이 배열을 checkbox change 때마다 in-place로
    // 갱신하므로(push/splice), 대화상자를 닫을 때 이 배열 자체가 최종 선택 결과다.
    // 원본 Settings 배열의 복사본이라 여기서 바꿔도 Settings 값은 그대로 유지된다.
    const selectedTypes = [...(opts.selected_media_types || ["screenshots", "3dboxes", "covers", "marquees", "miximages", "wheel"])];
    const romCb = h("input", { type: "checkbox", checked: !!opts.copy_rom });
    const romRow = h("label", { class: "settings-checkbox-row" }, [romCb, h("span", {}, ["Rom 실물 파일도 복사"])]);
    renderTransferCheckboxGroups(box, selectedTypes, { romRow });

    const actions = h("div", { class: "modal-actions" });
    const cancelBtn = h("button", { class: "btn" }, ["취소"]);
    cancelBtn.addEventListener("click", () => clear(root));
    const goBtn = h("button", { class: "btn primary" }, ["Export"]);
    goBtn.addEventListener("click", async () => {
      clear(root);
      const mode = romCb.checked ? "metadata_roms" : "metadata";
      await confirmAndRunExport(localId, mode, targetKeys, selectedTypes);
    });
    actions.appendChild(cancelBtn); actions.appendChild(goBtn);
    box.appendChild(actions);
    overlay.appendChild(box);
    root.appendChild(overlay);
  }

  async function confirmAndRunExport(localId, mode, targetKeys, mediaTypes) {
    const label = mode === "metadata_roms" ? "Export MetaData + Roms" : "Export MetaData";
    // ROM이 포함된 모드는 먼저 디스크 용량을 확인해서, 부족하면 확인창 단계에서부터 보여준다.
    let spaceNote = "";
    if (mode === "roms" || mode === "metadata_roms") {
      const space = await api.checkExportDiskSpace(localId, mode, targetKeys);
      if (space.ok) {
        const d = space.data;
        if (!d.ok) {
          showConfirm("디스크 용량 부족", `필요: ${d.requiredFormatted}, 여유: ${d.freeFormatted} — ${d.shortageFormatted}만큼 부족합니다. Export를 진행할 수 없습니다.`, true, () => closeConfirm());
          return;
        }
        spaceNote = ` (새로 복사할 용량: ${d.requiredFormatted}, 여유 공간: ${d.freeFormatted})`;
      }
    }
    showConfirm(label, `선택한 Media/Rom을 ArchiveDB에 반영합니다.${spaceNote}\n계속하시겠습니까?`, false, async () => {
      closeConfirm();
      const r = await runJobWithProgress(await api.startExportLocalToMasterdb(localId, mode, targetKeys, mediaTypes), label + " 진행 중");
      if (r.ok) {
        const parts = [];
        if (r.data.metadataResult) parts.push(`metadata 신규 ${r.data.metadataResult.imported}개, 중복 스킵 ${r.data.metadataResult.duplicates_skipped}개`);
        if (r.data.romsResult) parts.push(`ROM 복사 ${r.data.romsResult.copied}개, 이미 있어 건너뜀 ${r.data.romsResult.skipped}개`);
        showToast(`${label} 완료 — ${parts.join(" / ")}`);
      } else {
        showToast(r.error, "error");
      }
      await refreshMutationState();
    });
  }

  async function refreshMutationState() {
    // Any delete/export/import can change metadata/media. Drop detail/image caches so the
    // next selection reflects disk/DB immediately without requiring manual Refresh List.
    S.detailCache = Object.create(null);
    S.mediaImageCache = Object.create(null);
    detailState = null;
    await Promise.all([loadLocals(), loadMasterdbInfo()]);
    if (S.view === "masterdb") {
      const r = await api.listMasterdbGames();
      if (r.ok) S.games = r.data.map(g => ({ ...g, system: normalizeSystemName(g.system) }));
    } else if (currentLocalId()) {
      const cached = S.localGamesCache[currentLocalId()];
      if (cached && Array.isArray(cached.games)) S.games = cached.games;
    }
    renderAll();
  }

  // ------------------------------------------------------------------
  // 상세 패널
  // ------------------------------------------------------------------
  let detailState = null; // { romKey, versions, activeIdx, defaultIdx, tab, mediaType, pendingMedia }
  let clipboardRomKey = null;

  function updateListSelectionVisual() {
    document.querySelectorAll(".preview-card, .grid-data-row").forEach((el) => {
      const key = el.dataset.romKey;
      if (key) el.classList.toggle("selected", key === S.selectedGame);
    });
  }

  function renderDetailFromResponse(g, r) {
    if (!r || !r.ok) { showToast(r && r.error ? r.error : "상세 정보 오류", "error"); return; }
    const prevTab = detailState ? detailState.tab : "metadata";
    const prevMediaType = detailState ? detailState.mediaType : "Covers";
    detailState = {
      romKey: g.romKey, file: g.file, system: r.data.system || g.system, readOnly: false, favorite: !!g.favorite,
      versions: (r.data.versions || []).map((v) => ({ ...v })),
      activeIdx: Math.max(0, (r.data.versions || []).findIndex((v) => v.isDefault)),
      defaultIdx: Math.max(0, (r.data.versions || []).findIndex((v) => v.isDefault)),
      tab: prevTab, mediaType: prevMediaType,
      media: r.data.media || {}, pendingMedia: {}, draftFields: { ...(r.data.versions?.[Math.max(0, (r.data.versions || []).findIndex((v) => v.isDefault))]?.fields || {}) },
      // [신규] ROM 처음 복사 시 캐시된 SHA256 - 캐시가 없으면(구버전에서 이미 들어온
      // ROM 등) null, 패널에서 "계산 안 됨"으로 표시한다. Local(GameListSet) 미리보기
      // 응답에는 이 필드가 없으므로 undefined -> null로 정규화.
      sha256: r.data.sha256 || null,
    };
    renderDetailPanel();
  }

  // [수정] 탐색기 스타일 미리보기 토글 도입 - 게임을 고르는 것(selection)과 Metadata
  // Panel을 실제로 채우는 것(fetch+render)을 분리했다. previewOn이 꺼져 있으면
  // 선택만 하고 패널은 그대로 접힌 채로 둔다(Explorer의 미리보기 창 끔 상태와 동일).
  // opts.forceShow(Enter 키)는 토글이 꺼져 있어도 그 순간만은 강제로 켜서 보여준다.
  async function openDetail(g, opts) {
    opts = opts || {};
    S.selectedGame = g.romKey;
    S.openTick++;
    // 685/10000개 카드가 있을 때 게임 하나 클릭할 때마다 전체 Grid를 다시 만들지 않는다.
    updateListSelectionVisual();

    if (opts.forceShow && !S.previewOn) { S.previewOn = true; renderFilterBar(); }
    if (!S.previewOn) return;
    S.panelOpen = true;

    const localId = currentLocalId();
    const cacheKey = `${localId || "masterdb"}|${g.romKey}`;
    let r = S.detailCache[cacheKey];
    if (r) {
      renderDetailFromResponse(g, r);
      return;
    }
    // Local 화면에서도 실제 frontend metadata를 직접 읽는다.
    r = localId ? await api.getLocalGameDetail(localId, g.romKey, true) : await api.getGameDetail(g.romKey, true);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const cacheKey2 = `${localId || "masterdb"}|${g.romKey}`;
    S.detailCache[cacheKey2] = r;
    renderDetailFromResponse(g, r);
  }

  function closeDetail() {
    S.panelOpen = false;
    S.previewOn = false;
    renderFilterBar();
    renderDetailPanel();
    renderListArea();
  }

  // [신규] 필터바 우측 상단 미리보기 토글 버튼 - Explorer의 미리보기 창처럼 공간
  // 자체를 예약/해제한다. 켤 때 이미 선택된 게임이 있으면 즉시 그 내용을 보여주고,
  // 없으면 "선택된 항목이 없습니다" 빈 상태를 보여준다(renderDetailPanel이 처리).
  function togglePreview() {
    S.previewOn = !S.previewOn;
    S.panelOpen = S.previewOn;
    renderFilterBar();
    if (S.previewOn && S.selectedGame) {
      const g = S.games.find((x) => x.romKey === S.selectedGame);
      if (g && (!detailState || detailState.romKey !== g.romKey)) { openDetail(g); return; }
    }
    renderDetailPanel();
  }

  function renderDetailPanel() {
    const panel = document.getElementById("detail-panel");
    clear(panel);
    panel.classList.toggle("open", S.panelOpen);
    if (!S.panelOpen) return;
    if (!detailState || detailState.romKey !== S.selectedGame) {
      const inner = h("div", { id: "detail-panel-inner" });
      inner.appendChild(h("div", { class: "panel-empty-state" }, [
        icon("previewPane", 26),
        h("div", { class: "panel-empty-msg" }, ["선택된 항목이 없습니다"]),
      ]));
      panel.appendChild(inner);
      return;
    }

    // [수정] 폭 전환(width 0 -> pref) 중에 실제 콘텐츠가 같이 쪼그라들며 줄바꿈되지
    // 않도록, 항상 고정폭(--panel-pref)인 내부 래퍼에 그린다 - 바깥 #detail-panel은
    // overflow:hidden으로 그 폭만큼만 보여준다.
    const inner = h("div", { id: "detail-panel-inner" });
    panel.appendChild(inner);

    const header = h("div", { class: "detail-header" }, [
      h("div", { style: { minWidth: 0, flex: "1" } }, [
        h("div", { class: "detail-eyebrow" }, ["METADATA"]),
        h("div", { class: "detail-filename" }, [detailState.file]),
        // [수정] systemIcon()이 이제 내부적으로 normalizeSystemName()을 거치므로 여기서
        // 중복 호출할 필요가 없다.
        h("div", { class: "detail-system" }, [systemIcon(detailState.system || ""), String(detailState.system || "").toUpperCase()]),
      ]),
    ]);
    if (S.view === "masterdb") {
      header.appendChild(favoriteStarButton({ romKey: detailState.romKey, favorite: detailState.favorite }));
    }
    const closeBtn = h("button", { class: "icon-btn", title: "닫기 (Esc)" }, [icon("x", 13)]);
    closeBtn.addEventListener("click", closeDetail);
    header.appendChild(closeBtn);
    inner.appendChild(header);

    const tabs = h("div", { class: "detail-tabs" });
    ["metadata", "media"].forEach((tb) => {
      const t = h("button", { class: "detail-tab" + (detailState.tab === tb ? " active" : "") }, [tb === "metadata" ? "Metadata" : "Media"]);
      t.addEventListener("click", () => { captureMetadataDraft(); detailState.tab = tb; renderDetailPanel(); });
      tabs.appendChild(t);
    });
    inner.appendChild(tabs);

    const body = h("div", { class: "detail-body" });
    if (detailState.tab === "metadata") renderMetadataTab(body);
    else renderMediaTab(body);
    inner.appendChild(body);

    const footer = h("div", { class: "detail-footer" });
    const saveBtn = h("button", { class: "btn primary w-full" }, [icon("save", 13), h("span", {}, ["저장 (Ctrl+S)"])]);
    saveBtn.addEventListener("click", handleSaveDetail);
    footer.appendChild(saveBtn);
    inner.appendChild(footer);
  }

  const fieldRefs = {};
  function fieldGroup(iconName, label, key, value) {
    const wrap = h("div", {});
    wrap.appendChild(h("div", { class: "field-label" }, [icon(iconName, 10), label]));
    const input = h("input", { class: "field-input", value: value || "", disabled: detailState.readOnly });
    fieldRefs[key] = input;
    wrap.appendChild(input);
    return wrap;
  }

  // [SHA256 위치 이동] UI 표시용으로만 짧게 자른다 - 실제 전체 64자 hex 값은
  // 항상 detailState.sha256/API 응답에 그대로 유지되고, 여기서는 화면에 보여줄
  // 문자열만 만든다(비교/동일성 판단에 이 잘린 값을 쓰면 안 됨).
  function shortHash(hash, len) {
    if (!hash) return null;
    return hash.length > len ? hash.slice(0, len) + "…" : hash;
  }

  // [SHA256 위치 이동] 기존 identity-card 상단의 별도 줄 대신, 하단 field-grid에서
  // Players 옆 빈 칸을 채우는 읽기 전용 필드로 옮겼다 - input이 아니라 값을 그대로
  // 보여주기만 한다(No-Intro/Redump 대조용이라 수정할 이유가 없어 원래도 읽기
  // 전용이었다). 전체 64자 값은 title(hover)로 확인 가능하게 남겨둔다.
  function sha256FieldGroup() {
    const wrap = h("div", { class: "sha256-field" });
    wrap.appendChild(h("div", { class: "field-label" }, [icon("database", 10), "SHA256"]));
    const full = detailState.sha256 || "";
    const display = full ? shortHash(full, 16) : "계산 안 됨";
    wrap.appendChild(h("div", { class: "field-input field-static sha256-field-value", title: full || "" }, [display]));
    return wrap;
  }

  function captureMetadataDraft() {
    if (!detailState || !fieldRefs) return;
    detailState.draftFields = detailState.draftFields || {};
    Object.keys(fieldRefs).forEach((k) => { if (fieldRefs[k]) detailState.draftFields[k] = fieldRefs[k].value; });
  }

  function renderMetadataTab(body) {
    const v = detailState.versions[detailState.activeIdx];
    const draft = detailState.draftFields || v.fields || {};
    Object.keys(fieldRefs).forEach((k) => delete fieldRefs[k]);

    // [재구성] 상단 고정 영역: identity 요약 카드(대표이미지+6필드) + Title
    const topFixed = h("div", { class: "detail-body-fixed" });
    const identityCard = h("div", { class: "identity-card" });
    const coverThumb = h("div", { class: "identity-cover" });
    const coverMarker = detailState.media && detailState.media.Covers;
    if (coverMarker && String(coverMarker).startsWith("data:")) {
      coverThumb.appendChild(h("img", { src: coverMarker, alt: "Cover" }));
    } else if (coverMarker) {
      const coverImg = h("img", { alt: "Cover" });
      coverThumb.appendChild(coverImg);
      const localId = currentLocalId();
      const ck = `${localId || "masterdb"}|${detailState.romKey}|Covers`;
      if (S.mediaImageCache[ck]) coverImg.src = S.mediaImageCache[ck];
      else {
        (localId ? api.getLocalGameMediaImage(localId, detailState.romKey, "Covers") : api.getGameMediaImage(detailState.romKey, "Covers"))
          .then(r => { if (r.ok && r.data) { S.mediaImageCache[ck] = r.data; if (detailState.romKey) coverImg.src = r.data; } });
      }
    } else { coverThumb.appendChild(icon("image", 17)); }
    const summaryGrid = h("div", { class: "identity-grid" });
    [["Genre", v.fields.genre], ["Release", v.fields.releasedate], ["Players", v.fields.players],
     ["Region", v.fields.region], ["Developer", v.fields.developer], ["Publisher", v.fields.publisher]].forEach(([label, val]) => {
      summaryGrid.appendChild(h("div", { class: "identity-field" }, [
        h("div", { class: "identity-field-label" }, [label]),
        h("div", { class: "identity-field-value truncate" }, [val || "-"]),
      ]));
    });
    identityCard.appendChild(coverThumb);
    identityCard.appendChild(summaryGrid);
    topFixed.appendChild(identityCard);

    topFixed.appendChild(h("div", { class: "field-label" }, ["Title"]));
    const nameInput = h("input", { class: "field-input title-input", value: draft.name || "", disabled: detailState.readOnly });
    fieldRefs.name = nameInput;
    topFixed.appendChild(nameInput);
    body.appendChild(topFixed);

    // [재구성] Description: 남는 공간을 먼저 채우도록 flex:1 (요청 반영 - Cover 박스 제거로
    // 생긴 여유 공간을 Description이 우선적으로 흡수)
    const descWrap = h("div", { class: "detail-body-desc-wrap" });
    descWrap.appendChild(h("div", { class: "field-label" }, ["Description"]));
    const descInput = h("textarea", { class: "field-input", disabled: detailState.readOnly }, [v.fields.desc || ""]);
    descInput.value = draft.desc || "";
    fieldRefs.desc = descInput;
    descWrap.appendChild(descInput);
    body.appendChild(descWrap);

    // [재구성] 하단 고정 영역: 필드 그리드 + Version 관리 (Cover 박스는 제거함 - 상단
    // identity 카드에 이미 대표 이미지가 있어 중복이었음)
    const bottomFixed = h("div", { class: "detail-body-fixed" });
    const grid = h("div", { class: "field-grid" });
    grid.appendChild(fieldGroup("tag", "Genre", "genre", draft.genre));
    grid.appendChild(fieldGroup("building", "Developer", "developer", draft.developer));
    grid.appendChild(fieldGroup("building", "Publisher", "publisher", draft.publisher));
    grid.appendChild(fieldGroup("calendar", "Release", "releasedate", draft.releasedate));
    grid.appendChild(fieldGroup("globe", "Region", "region", draft.region));
    grid.appendChild(fieldGroup("star", "Rating", "rating", draft.rating));
    grid.appendChild(fieldGroup("users", "Players", "players", draft.players));
    // [SHA256 위치 이동] Players 옆(같은 행의 남는 칸)에 배치한다 - ArchiveDB에서만
    // 캐시되므로(_cache_rom_hash 참고) GameListSet 미리보기에서는 아예 숨긴다(항상
    // "계산 안 됨"만 보이는 죽은 필드를 만들지 않기 위함 - 기존 정책 그대로 유지).
    if (S.view === "masterdb") grid.appendChild(sha256FieldGroup());
    bottomFixed.appendChild(grid);

    // [수정] 읽기전용(Local 미리보기)일 땐 Version 관리 UI 자체가 의미 없으므로 숨김
    if (!detailState.readOnly) {
      bottomFixed.appendChild(h("div", { class: "field-label" }, ["Version"]));
      const sel = h("select", { class: "field-input" });
      detailState.versions.forEach((vv, i) => {
        const opt = h("option", { value: String(i) }, [`${vv.label}${i === detailState.defaultIdx ? " (Default)" : ""} · ${vv.source || ""}`]);
        if (i === detailState.activeIdx) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.addEventListener("change", (e) => { detailState.activeIdx = Number(e.target.value); renderDetailPanel(); });
      bottomFixed.appendChild(sel);

      const vbtns = h("div", { class: "version-row" });
      [
        ["copy", "복제", handleCloneVersion],
        ["check", "기본값", handleSetDefaultVersion],
        ["trash", "삭제", handleDeleteVersion],
        ["scale", "Ver Diff", openVerDiff],
      ].forEach(([iconName, label, fn]) => {
        const b = h("button", { class: "btn compact" }, [icon(iconName, 12.5)]);
        b.title = label;
        b.appendChild(h("span", {}, [label]));
        b.addEventListener("click", fn);
        vbtns.appendChild(b);
      });
      bottomFixed.appendChild(vbtns);
    }
    body.appendChild(bottomFixed);
  }

  function renderMediaTab(body) {
    body.classList.add("media-tab-body");
    // Compact no-scroll composition: Cover occupies the whole left half, Marquee upper-right,
    // MixImage lower-right. Screenshot/Wheel sit beneath it. Images are loaded one-by-one
    // through the bridge to avoid huge combined base64 payloads on media-heavy systems.
    const mediaMap = detailState.media || {};
    const pending = detailState.pendingMedia || {};
    const localId = currentLocalId();
    const stateRomKey = detailState.romKey;

    const ensureImage = async (img, guiKey) => {
      const marker = mediaMap[guiKey];
      if (!marker || marker === "video://exists") return;
      if (marker.startsWith && marker.startsWith("data:")) { img.src = marker; return; }
      const cacheKey = `${localId || "masterdb"}|${stateRomKey}|${guiKey}`;
      if (S.mediaImageCache[cacheKey]) { img.src = S.mediaImageCache[cacheKey]; return; }
      const r = localId
        ? await api.getLocalGameMediaImage(localId, stateRomKey, guiKey)
        : await api.getGameMediaImage(stateRomKey, guiKey);
      if (r.ok && r.data && detailState && detailState.romKey === stateRomKey) {
        S.mediaImageCache[cacheKey] = r.data;
        img.src = r.data;
      }
    };

    const item = (label, guiKey, cls="") => {
      const display = pending[guiKey] || mediaMap[guiKey] || null;
      const zone = h("div", { class: `media-tile ${cls}`.trim() });
      zone.appendChild(h("div", { class: "media-tile-label" }, [label, pending[guiKey] ? " · 저장 필요" : ""]));
      const preview = h("div", { class: "media-tile-preview" });
      if (guiKey === "Videos" && display) {
        preview.appendChild(h("div", { class: "dropzone-empty" }, [icon("upload", 18), "영상 등록됨"]));
      } else if (display) {
        const img = h("img", { alt: label });
        if (pending[guiKey] && String(pending[guiKey]).startsWith("data:")) img.src = pending[guiKey];
        preview.appendChild(img);
        if (!img.src) ensureImage(img, guiKey);
      } else {
        preview.appendChild(h("div", { class: "dropzone-empty" }, [icon("imageOff", 18), `${label} 없음`]));
      }
      zone.appendChild(preview);
      const input = h("input", { type: "file", accept: guiKey === "Videos" ? "video/*" : "image/*", style: { display: "none" } });
      input.addEventListener("change", e => { const f=e.target.files&&e.target.files[0]; if(f) handleMediaFile(guiKey,f); e.target.value=""; });
      zone.addEventListener("click", (e) => { if (e.target !== input) input.click(); });
      ["dragenter","dragover"].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); zone.classList.add("drag-over"); }));
      ["dragleave","drop"].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); zone.classList.remove("drag-over"); }));
      zone.addEventListener("drop", e => {
        const f = e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) { handleMediaFile(guiKey, f); return; }
        const uri = e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain");
        if (uri && /^https?:\/\//i.test(uri.trim())) handleMediaUrl(guiKey, uri.trim());
      });
      zone.appendChild(input);
      return zone;
    };

    const hero = h("div", { class: "media-quad-grid" });
    hero.appendChild(item("Cover", "Covers", "cover"));
    hero.appendChild(item("Marquee", "Marquees", "marquee"));
    hero.appendChild(item("MixImage", "Miximages", "miximage"));
    hero.appendChild(item("Wheel", "Wheel", "wheel"));
    body.appendChild(hero);

    const lower = h("div", { class: "media-lower-grid" });
    lower.appendChild(item("Screenshot", "Screenshots", "screenshot"));
    body.appendChild(lower);
    if (mediaMap.Videos || pending.Videos) body.appendChild(item("Video", "Videos", "video"));
  }

  async function handleMediaUrl(mediaType, url) {
    if (mediaType === "Videos") { showToast("영상 URL 드래그는 지원하지 않습니다. 파일을 사용해주세요.", "warning"); return; }
    try {
      const localId = currentLocalId();
      const r = localId
        ? await api.saveLocalMediaFromUrl(localId, detailState.romKey, mediaType, url)
        : await api.saveMediaFromUrl(detailState.romKey, mediaType, url);
      if (!r.ok) { showToast(r.error || "이미지 URL 저장 실패", "error"); return; }
      detailState.media[mediaType] = r.data.dataUri || r.data;
      S.mediaImageCache = Object.create(null);
      renderDetailPanel();
      showToast(`${mediaType} 이미지가 저장되었습니다.`);
    } catch (e) { showToast("이미지 URL 처리 실패", "error"); }
  }

  function handleMediaFile(mediaType, file) {
    const isVideo = mediaType === "Videos";
    const valid = isVideo ? file.type.startsWith("video/") : file.type.startsWith("image/");
    if (!valid) { showToast(isVideo ? "영상 파일만 지원됩니다." : "이미지 파일만 지원됩니다.", "warning"); return; }
    const reader = new FileReader();
    reader.onload = () => {
      // 영상은 data URI로 미리보기하지 않고(용량 문제) 존재 여부만 표시
      detailState.pendingMedia[mediaType] = isVideo ? "video://exists" : reader.result;
      detailState._pendingFile = detailState._pendingFile || {};
      detailState._pendingFile[mediaType] = { base64: reader.result.split(",")[1], filename: file.name };
      showToast(`${mediaType}이(가) 임시 적용되었습니다. 저장을 눌러야 실제 반영됩니다.`, "warning");
      renderDetailPanel();
    };
    reader.readAsDataURL(file);
  }

  async function handleSaveDetail() {
    if (!detailState) return;
    const v = detailState.versions[detailState.activeIdx];
    // [버그 수정] 저장 버튼은 탭과 무관하게 항상 metadata+media를 함께 저장해야 하는데
    // (HANDOFF.md 설계 원칙), 예전엔 여기서 모듈 전역 fieldRefs를 직접 읽었다. fieldRefs는
    // Metadata 탭이 렌더링될 때만 채워지고 게임을 바꿔도 초기화되지 않으므로, Media 탭에
    // 머문 채로(예: 자동/수동으로 다른 게임을 연 뒤) 이미지만 드래그하고 저장을 누르면
    // "이전에 열려 있던 다른 게임"의 낡은 title 입력값이 fieldRefs에 그대로 남아있다가
    // 지금 게임의 title을 덮어써버렸다 - "Media 저장 후 Title이 엉뚱한 값으로 바뀌고
    // 한 번 더 저장해야 정상화됨" 버그의 원인. detailState.draftFields는 게임을 열 때마다
    // 새로 만들어지고(renderDetailFromResponse) 탭 전환 시 captureMetadataDraft()로 항상
    // 최신 입력값이 반영되므로, 이걸 유일한 소스로 쓴다.
    if (detailState.tab === "metadata") captureMetadataDraft();
    const fields = { ...v.fields, ...(detailState.draftFields || {}) };
    if (currentLocalId()) {
      const r = await api.saveLocalGameFields(currentLocalId(), detailState.romKey, fields);
      if (!r.ok) { showToast(r.error, "error"); return; }
      v.fields = { ...fields };
      let mediaMsg = "";
      if (detailState._pendingFile) {
        for (const [mt, payload] of Object.entries(detailState._pendingFile)) {
          const mr = await api.saveLocalMedia(currentLocalId(), detailState.romKey, mt, payload.base64, payload.filename);
          if (!mr.ok) { showToast(mr.error || `${mt} 저장 실패`, "error"); return; }
          detailState.media[mt] = mr.data?.dataUri || detailState.media[mt];
          mediaMsg = " (이미지 포함)";
        }
        detailState._pendingFile = {}; detailState.pendingMedia = {};
      }
      S.games = S.games.map((g) => g.romKey === detailState.romKey ? { ...g, title: fields.name || "", desc: fields.desc || "", genre: fields.genre || "" } : g);
      setLocalGamesCache(currentLocalId(), S.games, true);
      delete S.detailCache[`${currentLocalId()}|${detailState.romKey}`];
      showToast("GameListSet metadata가 저장되었습니다." + mediaMsg);
      renderAll();
      return;
    }
    const r = await api.saveVersionFields(detailState.romKey, v.id, fields);
    if (!r.ok) { showToast(r.error, "error"); return; }
    v.fields = { ...fields };
    let mediaMsg = "";
    if (detailState._pendingFile) {
      for (const [mt, payload] of Object.entries(detailState._pendingFile)) {
        const mr = await api.saveMedia(detailState.romKey, mt, payload.base64, payload.filename);
        if (mr.ok) { detailState.media[mt] = mr.data.dataUri; mediaMsg = " (이미지 포함)"; }
      }
      detailState._pendingFile = {}; detailState.pendingMedia = {};
    }
    showToast("저장 완료" + mediaMsg);
    await loadGamesForView();
    renderListArea(); renderDetailPanel();
  }

  async function handleCloneVersion() {
    const v = detailState.versions[detailState.activeIdx];
    const r = await api.cloneVersion(detailState.romKey, v.id);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const detail = await api.getGameDetail(detailState.romKey);
    if (detail.ok) {
      detailState.versions = detail.data.versions;
      detailState.activeIdx = detailState.versions.findIndex((x) => x.id === r.data.newVersionId);
      renderDetailPanel();
      showToast("버전이 복제되었습니다.");
    }
  }

  async function handleSetDefaultVersion() {
    const v = detailState.versions[detailState.activeIdx];
    const r = await api.setDefaultVersion(detailState.romKey, v.id);
    if (!r.ok) { showToast(r.error, "error"); return; }
    detailState.versions.forEach((x, i) => (x.isDefault = i === detailState.activeIdx));
    detailState.defaultIdx = detailState.activeIdx;
    renderDetailPanel();
    await loadGamesForView(); renderListArea();
    showToast("기본 버전으로 설정되었습니다.");
  }

  function handleDeleteVersion() {
    if (detailState.versions.length <= 1) { showToast("최소 1개의 Version은 유지되어야 합니다.", "warning"); return; }
    const v = detailState.versions[detailState.activeIdx];
    showConfirm("Version 삭제", "이 Version을 삭제하시겠습니까?", true, async () => {
      closeConfirm();
      const r = await api.deleteVersion(detailState.romKey, v.id);
      if (!r.ok) { showToast(r.error, "error"); return; }
      const detail = await api.getGameDetail(detailState.romKey);
      if (detail.ok) {
        detailState.versions = detail.data.versions;
        detailState.activeIdx = 0;
        detailState.defaultIdx = detailState.versions.findIndex((x) => x.isDefault);
        renderDetailPanel();
      }
      await loadGamesForView(); renderListArea();
      showToast("버전이 삭제되었습니다.", "warning");
    });
  }

  // ------------------------------------------------------------------
  // Ver Diff 모달
  // ------------------------------------------------------------------
  function openVerDiff() {
    if (detailState.versions.length <= 1) { showToast("비교할 Version이 2개 이상이어야 합니다."); return; }
    S.verDiffState = {
      leftIdx: detailState.defaultIdx,
      rightIdx: detailState.versions.length - 1 === detailState.defaultIdx ? 0 : detailState.versions.length - 1,
    };
    renderModals();
  }

  // ------------------------------------------------------------------
  // Local 추가 모달
  // ------------------------------------------------------------------
  function openAddLocal() { S.addLocalOpen = true; renderModals(); }

  // [신규] MasterDB 미설정 시 온보딩 화면
  function buildMasterdbOnboarding() {
    const wrap = h("div", { id: "masterdb-onboarding" });
    wrap.appendChild(icon("database", 36));
    wrap.appendChild(h("div", { class: "onboarding-title" }, ["ArchiveDB가 아직 설정되지 않았습니다"]));
    wrap.appendChild(h("div", { class: "onboarding-desc" }, ["모든 GameListSet의 metadata를 모아서 관리할 중앙 저장소 폴더를 선택하세요."]));
    const btn = h("button", { class: "btn primary onboarding-btn" }, [icon("plus", 13), h("span", {}, ["+ ArchiveDB 추가"])]);
    btn.addEventListener("click", handleSetupMasterdb);
    wrap.appendChild(btn);
    return wrap;
  }

  async function handleSetupMasterdb() {
    try {
      const r = await api.pickFolder("ArchiveDB 저장 위치 선택 (Choose ArchiveDB Location)");
      if (!r.ok) { showToast(r.error, "error"); return; }
      if (!r.data) return; // 사용자가 취소
      const res = await api.setMasterdbPath(r.data);
      if (!res.ok) { showToast(res.error, "error"); return; }
      showToast("ArchiveDB가 설정되었습니다.");
      await loadMasterdbInfo();
      if (S.view === "masterdb") await loadGamesForView();
      renderAll();
    } catch (e) {
      console.error("ArchiveDB 설정 실패:", e);
      showToast("ArchiveDB 설정 중 오류가 발생했습니다.", "error");
    }
  }
  function closeAddLocal() { S.addLocalOpen = false; renderModals(); }

  // ------------------------------------------------------------------
  // 모달 전체 렌더 (Confirm / AddLocal / VerDiff)
  // ------------------------------------------------------------------
  function renderModals() {
    const root = document.getElementById("modal-root");
    clear(root);

    if (S.confirmState) {
      const cs = S.confirmState;
      const overlay = h("div", { class: "modal-overlay" });
      overlay.addEventListener("click", (e) => { if (e.target === overlay) closeConfirm(); });
      const box = h("div", { class: "modal-box modal-w-sm" });
      box.addEventListener("click", (e) => e.stopPropagation());
      box.appendChild(h("div", { class: "modal-title" }, [icon("triangleAlert", 16), cs.title]));
      box.appendChild(h("p", { class: "modal-message" }, [cs.message]));
      const actions = h("div", { class: "modal-actions" });
      const cancelBtn = h("button", { class: "btn" }, ["취소"]);
      cancelBtn.addEventListener("click", closeConfirm);
      const okBtn = h("button", { class: "btn primary" }, ["확인"]);
      if (cs.danger) okBtn.style.background = "var(--danger)";
      okBtn.addEventListener("click", cs.onConfirm);
      actions.appendChild(cancelBtn); actions.appendChild(okBtn);
      box.appendChild(actions);
      overlay.appendChild(box);
      root.appendChild(overlay);
    }

    if (S.addLocalOpen) root.appendChild(buildAddLocalModal());
    if (S.editLocalPathsState) root.appendChild(buildEditLocalPathsModal());
    if (S.verDiffState) root.appendChild(buildVerDiffModal());
    if (S.renameState) root.appendChild(buildRenameModal());
  }

  // ------------------------------------------------------------------
  // [F2] ArchiveDB ROM 파일명 변경 - 연결된 media 폴더까지 함께 이동된다 (rename_masterdb_rom).
  // 이름이 겹치면(디스크/DB 어느 쪽이든) 백엔드가 거부하므로 그대로 취소 처리한다.
  // ------------------------------------------------------------------
  function openRename(romKey, currentFilename) {
    S.renameState = { romKey, file: currentFilename, value: currentFilename, error: "" };
    renderModals();
  }
  function closeRename() { S.renameState = null; renderModals(); }

  function buildRenameModal() {
    const state = S.renameState;
    const overlay = h("div", { class: "modal-overlay" });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) closeRename(); });
    const box = h("div", { class: "modal-box modal-w-sm" });
    box.addEventListener("click", (e) => e.stopPropagation());
    box.appendChild(h("div", { class: "modal-title" }, ["파일명 변경"]));
    box.appendChild(h("div", { class: "field-label", style: { marginTop: "8px" } }, ["새 ROM 파일명"]));
    const input = h("input", { class: "field-input", value: state.value });
    box.appendChild(input);
    const errorBox = h("div", { style: { display: state.error ? "block" : "none", fontSize: "calc(11px * var(--font-scale))", color: "var(--danger)", marginTop: "6px" } }, [state.error]);
    box.appendChild(errorBox);
    box.appendChild(h("div", { class: "settings-row-desc", style: { marginTop: "6px" } }, ["같은 이름의 ROM이 이미 있으면 변경이 취소됩니다. 연결된 metadata/media는 함께 이동됩니다."]));

    async function commit() {
      const newName = input.value.trim();
      if (!newName || newName === state.file) { closeRename(); return; }
      const r = await api.renameMasterdbRom(state.romKey, newName);
      if (!r.ok) { state.error = r.error || "이름 변경에 실패했습니다."; renderModals(); return; }
      closeRename();
      delete S.detailCache[`masterdb|${state.romKey}`];
      if (S.selectedGame === state.romKey) S.selectedGame = r.data.romKey;
      await loadGamesForView(); renderListArea();
      showToast("파일명이 변경되었습니다.");
    }
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); commit(); }
      if (e.key === "Escape") { e.preventDefault(); closeRename(); }
    });

    const actions = h("div", { class: "modal-actions" });
    const cancelBtn = h("button", { class: "btn" }, ["취소"]);
    cancelBtn.addEventListener("click", closeRename);
    const okBtn = h("button", { class: "btn primary" }, ["변경"]);
    okBtn.addEventListener("click", commit);
    actions.appendChild(cancelBtn); actions.appendChild(okBtn);
    box.appendChild(actions);
    overlay.appendChild(box);
    setTimeout(() => { input.focus(); input.select(); }, 0);
    return overlay;
  }

  function buildAddLocalModal() {
    const state = { label: "", frontend: FRONTENDS[0], romPath: "", metaPath: "", error: "" };
    const overlay = h("div", { class: "modal-overlay" });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) closeAddLocal(); });
    const box = h("div", { class: "modal-box modal-w-md modal-scroll" });
    box.addEventListener("click", (e) => e.stopPropagation());
    box.appendChild(h("div", { class: "modal-title" }, ["GameListSet 추가"]));

    box.appendChild(h("div", { class: "field-label", style: { marginTop: "8px" } }, ["GameListSet 이름"]));
    const defaultLabel = `LOCAL ${S.locals.length + 1}`;
    const labelInput = h("input", { class: "field-input", placeholder: defaultLabel });
    box.appendChild(labelInput);

    box.appendChild(h("div", { class: "field-label", style: { marginTop: "10px" } }, ["Frontend"]));
    const feSelect = h("select", { class: "field-input" });
    FRONTENDS.forEach((f) => feSelect.appendChild(h("option", { value: f }, [f])));
    box.appendChild(feSelect);

    const metaLabelDiv = h("div", { class: "field-label", style: { marginTop: "10px" } }, ["Metadata / Media 경로"]);
    const metaHintDiv = h("div", { style: { fontSize: "calc(10px * var(--font-scale))", color: "var(--muted)", marginBottom: "4px" } }, [""]);
    box.appendChild(metaLabelDiv);
    box.appendChild(metaHintDiv);
    const metaRow = h("div", { class: "flex gap-2" });
    const metaInput = h("input", { class: "field-input", placeholder: "D:\\ES-DE" });
    const metaPickBtn = h("button", { class: "btn compact" }, [icon("folderOpen", 13)]);
    metaPickBtn.addEventListener("click", async () => {
      const r = await api.pickFolder("ES-DE gamelist / downloaded_media 경로 선택");
      if (r.ok && r.data) metaInput.value = r.data;
    });
    metaRow.appendChild(metaInput); metaRow.appendChild(metaPickBtn);
    box.appendChild(metaRow);

    box.appendChild(h("div", { class: "field-label", style: { marginTop: "10px" } }, ["ROM 경로 (선택사항)"]));
    const romRow = h("div", { class: "flex gap-2" });
    const romInput = h("input", { class: "field-input", placeholder: "D:\\Roms\\... (ES-DE는 비워도 됩니다)" });
    const romPickBtn = h("button", { class: "btn compact" }, [icon("folderOpen", 13)]);
    romPickBtn.addEventListener("click", async () => {
      const r = await api.pickFolder("ROM 경로 선택 (선택사항)");
      if (r.ok && r.data) romInput.value = r.data;
    });
    romRow.appendChild(romInput); romRow.appendChild(romPickBtn);
    box.appendChild(romRow);

    function syncSameDir() {
      const sameDir = SAME_DIR_FRONTENDS.has(feSelect.value);
      const isEs = ES_STYLE_FRONTENDS.has(feSelect.value);
      metaLabelDiv.textContent = isEs ? "ES-DE gamelist / downloaded_media 경로" : "Metadata / Media 경로";
      metaHintDiv.textContent = isEs ? "이 경로 아래 gamelists\\와 downloaded_media\\가 있어야 합니다. ROM 경로는 선택사항입니다." : sameDir ? "ROM 경로와 동일" : "";
      metaInput.disabled = sameDir; metaPickBtn.disabled = sameDir;
      if (sameDir) metaInput.value = romInput.value;
      romInput.disabled = false; romPickBtn.disabled = false;
    }
    feSelect.addEventListener("change", syncSameDir);
    syncSameDir();

    const errorBox = h("div", { style: { display: "none", fontSize: "calc(11.5px * var(--font-scale))", borderRadius: "6px", padding: "8px 10px", marginTop: "10px", background: "rgba(239,68,68,.1)", color: "var(--danger)" } });
    box.appendChild(errorBox);

    const actions = h("div", { class: "modal-actions" });
    const cancelBtn = h("button", { class: "btn" }, ["취소"]);
    cancelBtn.addEventListener("click", closeAddLocal);
    const submitBtn = h("button", { class: "btn primary" }, ["등록"]);
    submitBtn.addEventListener("click", async () => {
      // [요청 반영] 이름을 안 넣으면 에러 대신 placeholder(LOCAL N)를 그대로 이름으로 사용
      const label = labelInput.value.trim() || defaultLabel;
      const frontend = feSelect.value;
      const romPath = romInput.value.trim();
      const sameDir = SAME_DIR_FRONTENDS.has(frontend);
      const metaPath = sameDir ? romPath : metaInput.value.trim();
      if (frontend === "ES-DE") {
        if (!metaPath) { errorBox.textContent = "ES-DE gamelist / downloaded_media 경로를 지정해주세요."; errorBox.style.display = "block"; return; }
      } else {
        if (!romPath) { errorBox.textContent = "ROM 경로를 지정해주세요."; errorBox.style.display = "block"; return; }
        if (!sameDir && !metaPath) { errorBox.textContent = "Metadata / Media 경로를 지정해주세요."; errorBox.style.display = "block"; return; }
      }
      const r = await api.addLocal(label, frontend, romPath, metaPath);
      if (!r.ok) { errorBox.textContent = r.error; errorBox.style.display = "block"; return; }
      closeAddLocal();
      showToast(`${label} 등록됨`);
      await Promise.all([loadLocals(), loadMasterdbInfo()]);
      renderSidebar();

      // Local 추가 직후에는 새 Local을 즉시 선택하고 "초기 스캔"을 수행한다.
      // 기존에는 Local만 config에 추가한 뒤 현재 화면(MasterDB)을 그대로 유지했기 때문에
      // 0 ROMs가 표시되고, 사용자가 Refresh List를 눌러야만 목록이 나타났다.
      const added = S.locals.find((l) => l.id === r.data.id) || r.data;
      S.view = "local-" + added.id;
      S.selectedSystem = "all";
      S.games = [];
      S.panelOpen = S.previewOn;
      S.multiSelect.clear();
      S.scanningLocalId = added.id;
      renderAll();

      const job = await api.startScanLocal(added.id);
      // [체감 속도, Scan 2단계] S.games/cache/렌더는 runScanJobWithProgress가
      // job1과 뒤이은 follow-up 둘 다에 대해 이미 처리해준다 - 여기서 다시 games를
      // 캡처해 S.games를 덮어쓰면 await loadLocals() 등으로 지연된 그 재적용이
      // follow-up의 최신 렌더와 경합할 수 있다.
      // [Parent Job lifecycle 수정] "초기 스캔 완료" 토스트는 onFullyDone(2단계까지
      // 실제로 다 끝난 뒤)에만 띄운다 - 1단계만 끝난 시점에 완료라고 하면 오해를 준다.
      await runScanJobWithProgress(job, "GameListSet 초기 스캔 중입니다...", added.id, async (full) => {
        S.scanningLocalId = null;
        if (full.ok) {
          await loadLocals();
          await loadMasterdbInfo();
          renderAll();
          showToast(`${label} 초기 스캔 완료`);
        } else {
          showToast(full.error, "error");
          // [버그 수정] renderListArea()만 부르면 사이드바는 S.scanningLocalId가 이미
          // null로 바뀐 걸 반영하지 못해 "스캔 중" 빨간색 표시가 그대로 남는다.
          renderSidebar();
          renderListArea();
        }
      });
    });
    actions.appendChild(cancelBtn); actions.appendChild(submitBtn);
    box.appendChild(actions);

    overlay.appendChild(box);
    return overlay;
  }

  // [Settings > GameListSet 경로 변경] 기존 Local의 Metadata/ROM 경로를 다시 선택해서
  // 반영한다. buildAddLocalModal()과 달리 이름/Frontend는 바꾸지 않고 경로만 다룬다.
  function openEditLocalPaths(local) {
    S.editLocalPathsState = {
      localId: local.id, label: local.label,
      romPath: local.rom_path || "", metaPath: local.metadata_path || "", error: "",
    };
    renderModals();
  }
  function closeEditLocalPaths() { S.editLocalPathsState = null; renderModals(); }

  function buildEditLocalPathsModal() {
    const st = S.editLocalPathsState;
    const local = S.locals.find((l) => l.id === st.localId);
    const isEs = local && ES_STYLE_FRONTENDS.has(local.frontendLabel || local.frontend);
    const overlay = h("div", { class: "modal-overlay" });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) closeEditLocalPaths(); });
    const box = h("div", { class: "modal-box modal-w-md" });
    box.addEventListener("click", (e) => e.stopPropagation());
    box.appendChild(h("div", { class: "modal-title" }, [`${st.label} - 경로 변경`]));

    box.appendChild(h("div", { class: "field-label", style: { marginTop: "8px" } }, [isEs ? "ES-DE gamelist / downloaded_media 경로" : "Metadata / Media 경로"]));
    const metaRow = h("div", { class: "flex gap-2" });
    const metaInput = h("input", { class: "field-input", value: st.metaPath });
    const metaPickBtn = h("button", { class: "btn compact" }, [icon("folderOpen", 13)]);
    metaPickBtn.addEventListener("click", async () => {
      const r = await api.pickFolder("Metadata / Media 경로 선택");
      if (r.ok && r.data) metaInput.value = r.data;
    });
    metaRow.appendChild(metaInput); metaRow.appendChild(metaPickBtn);
    box.appendChild(metaRow);

    box.appendChild(h("div", { class: "field-label", style: { marginTop: "10px" } }, ["ROM 경로" + (isEs ? " (선택사항)" : "")]));
    const romRow = h("div", { class: "flex gap-2" });
    const romInput = h("input", { class: "field-input", value: st.romPath });
    const romPickBtn = h("button", { class: "btn compact" }, [icon("folderOpen", 13)]);
    romPickBtn.addEventListener("click", async () => {
      const r = await api.pickFolder("ROM 경로 선택");
      if (r.ok && r.data) romInput.value = r.data;
    });
    romRow.appendChild(romInput); romRow.appendChild(romPickBtn);
    box.appendChild(romRow);

    const errorBox = h("div", { style: { display: "none", fontSize: "calc(11.5px * var(--font-scale))", borderRadius: "6px", padding: "8px 10px", marginTop: "10px", background: "rgba(239,68,68,.1)", color: "var(--danger)" } });
    box.appendChild(errorBox);

    const actions = h("div", { class: "modal-actions" });
    const cancelBtn = h("button", { class: "btn" }, ["취소"]);
    cancelBtn.addEventListener("click", closeEditLocalPaths);
    const submitBtn = h("button", { class: "btn primary" }, ["확인"]);
    submitBtn.addEventListener("click", async () => {
      const metaPath = metaInput.value.trim();
      const romPath = romInput.value.trim();
      if (isEs && !metaPath) { errorBox.textContent = "ES-DE gamelist / downloaded_media 경로를 지정해주세요."; errorBox.style.display = "block"; return; }
      if (!isEs && !romPath) { errorBox.textContent = "ROM 경로를 지정해주세요."; errorBox.style.display = "block"; return; }
      const r = await api.updateLocalPaths(st.localId, romPath, metaPath);
      if (!r.ok) { errorBox.textContent = r.error; errorBox.style.display = "block"; return; }
      closeEditLocalPaths();
      showToast(`${st.label} 경로가 변경되었습니다.`);
      await loadLocals();
      renderSidebar(); renderSettings();
      if (S.view === "local-" + st.localId) { S.games = []; await loadGamesForView(); renderAll(); }
    });
    actions.appendChild(cancelBtn); actions.appendChild(submitBtn);
    box.appendChild(actions);

    overlay.appendChild(box);
    return overlay;
  }

  function buildVerDiffModal() {
    const vd = S.verDiffState;
    const overlay = h("div", { class: "modal-overlay" });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) { S.verDiffState = null; renderModals(); } });
    const box = h("div", { class: "modal-box verdiff-box" });
    box.addEventListener("click", (e) => e.stopPropagation());

    const header = h("div", { class: "flex items-center justify-between", style: { padding: "12px 16px", borderBottom: "1px solid var(--border)" } }, [
      h("span", { style: { fontWeight: "600", fontSize: "calc(13px * var(--font-scale))" } }, ["Version 비교 / 편집"]),
    ]);
    const closeBtn = h("button", {}, [icon("x", 16)]);
    closeBtn.addEventListener("click", () => { S.verDiffState = null; renderModals(); });
    header.appendChild(closeBtn);
    box.appendChild(header);

    const body = h("div", { class: "verdiff-body" });
    const colsWrap = h("div", { class: "verdiff-cols" });
    const editState = { left: {}, right: {} };

    function buildSide(side) {
      const idxKey = side === "left" ? "leftIdx" : "rightIdx";
      const col = h("div", { class: "verdiff-col" + (vd[idxKey] === detailState.defaultIdx ? " is-default" : "") });
      const sel = h("select", { class: "field-input", style: { marginBottom: "8px" } });
      detailState.versions.forEach((v, i) => {
        const opt = h("option", { value: String(i) }, [`v${i + 1}${i === detailState.defaultIdx ? " (Default)" : ""} · ${v.source || ""}`]);
        if (i === vd[idxKey]) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.addEventListener("change", (e) => { vd[idxKey] = Number(e.target.value); renderModals(); });
      col.appendChild(sel);

      const fields = detailState.versions[vd[idxKey]].fields;
      editState[side] = { ...fields };
      [["name", "제목"], ["desc", "설명"], ["genre", "장르"], ["developer", "개발사"], ["releasedate", "출시일"]].forEach(([key, label]) => {
        col.appendChild(h("div", { style: { fontSize: "calc(9.5px * var(--font-scale))", textTransform: "uppercase", color: "var(--muted)", marginTop: "8px", marginBottom: "2px" } }, [label]));
        const input = key === "desc" ? h("textarea", { class: "field-input", rows: 2 }, [fields[key] || ""]) : h("input", { class: "field-input", value: fields[key] || "" });
        if (key === "desc") input.value = fields[key] || "";
        input.addEventListener("input", (e) => { editState[side][key] = e.target.value; });
        col.appendChild(input);
      });

      const delBtn = h("button", { class: "btn danger block-action" }, [icon("trash", 12), h("span", {}, ["이 버전 삭제"])]);
      if (detailState.versions.length <= 1) delBtn.disabled = true;
      delBtn.addEventListener("click", async () => {
        if (detailState.versions.length <= 1) return;
        const v = detailState.versions[vd[idxKey]];
        const r = await api.deleteVersion(detailState.romKey, v.id);
        if (!r.ok) { showToast(r.error, "error"); return; }
        const detail = await api.getGameDetail(detailState.romKey);
        if (detail.ok) {
          detailState.versions = detail.data.versions;
          detailState.defaultIdx = detailState.versions.findIndex((x) => x.isDefault);
          vd.leftIdx = Math.min(vd.leftIdx, detailState.versions.length - 1);
          vd.rightIdx = Math.min(vd.rightIdx, detailState.versions.length - 1);
        }
        renderModals();
        renderDetailPanel();
        await loadGamesForView(); renderListArea();
        showToast("버전이 삭제되었습니다.", "warning");
      });
      col.appendChild(delBtn);
      return col;
    }

    colsWrap.appendChild(buildSide("left"));
    colsWrap.appendChild(buildSide("right"));
    body.appendChild(colsWrap);
    box.appendChild(body);

    const footer = h("div", { class: "modal-actions", style: { padding: "12px 16px", borderTop: "1px solid var(--border)", margin: 0 } });
    const cancelBtn = h("button", { class: "btn" }, ["취소"]);
    cancelBtn.addEventListener("click", () => { S.verDiffState = null; renderModals(); });
    const saveBtn = h("button", { class: "btn primary" }, ["저장"]);
    saveBtn.addEventListener("click", async () => {
      const leftV = detailState.versions[vd.leftIdx];
      const rightV = detailState.versions[vd.rightIdx];
      const r = await api.saveVersionDiff(detailState.romKey, leftV.id, editState.left, rightV.id, editState.right);
      if (!r.ok) { showToast(r.error, "error"); return; }
      S.verDiffState = null;
      const detail = await api.getGameDetail(detailState.romKey);
      if (detail.ok) detailState.versions = detail.data.versions;
      renderModals(); renderDetailPanel();
      await loadGamesForView(); renderListArea();
      showToast("Version 비교 내용이 저장되었습니다.");
    });
    footer.appendChild(cancelBtn); footer.appendChild(saveBtn);
    box.appendChild(footer);

    overlay.appendChild(box);
    return overlay;
  }

  // ------------------------------------------------------------------
  // Dashboard
  // ------------------------------------------------------------------
  let dashState = { tabKey: null };
  // [신규] 시스템별 고정 색상 팔레트 (막대그래프와 하단 테이블 라벨이 같은 색을 쓰도록,
  // 시스템 이름 기준으로 결정적으로 배정 - 매번 렌더링해도 같은 시스템은 항상 같은 색)
  const SYSTEM_COLOR_PALETTE = ["#8B5CF6", "#39D98A", "#FFB74D", "#FF647C", "#38BDF8", "#F472B6", "#A3E635", "#FB923C", "#22D3EE", "#C084FC"];
  function colorForSystem(name, allSystemNames) {
    const idx = allSystemNames.indexOf(name);
    return SYSTEM_COLOR_PALETTE[idx % SYSTEM_COLOR_PALETTE.length];
  }
  function formatBytes(n) {
    n = Number(n) || 0;
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i === 0 ? Math.round(n) : n.toFixed(2)) + " " + units[i];
  }

  const CAPACITY_SLIDER_MAX_GB = 4096; // 4TB, 직접입력 필드로는 이보다 큰 값도 입력 가능
  function renderCapacityDashPanel() {
    const panel = h("div", { class: "capacity-dash-panel" });
    panel.appendChild(h("div", { class: "capacity-dash-title" }, ["GameListSet 용량 현황"]));
    if (!S.locals.length) {
      panel.appendChild(h("div", { class: "capacity-dash-empty" }, ["등록된 GameListSet이 없습니다."]));
      return panel;
    }
    S.locals.forEach((l) => {
      const usedBytes = Number((l.stats && (l.stats.rom_size_bytes + (l.stats.media_size_bytes || 0))) || 0);
      const targetBytes = Number(l.target_capacity_bytes) || 0;
      const pct = targetBytes > 0 ? Math.min(100, Math.round((usedBytes / targetBytes) * 100)) : 0;
      const freeBytes = targetBytes > 0 ? Math.max(0, targetBytes - usedBytes) : 0;
      const overBytes = targetBytes > 0 ? Math.max(0, usedBytes - targetBytes) : 0;

      const item = h("div", { class: "capacity-dash-item" });
      item.appendChild(h("div", { class: "capacity-dash-item-head" }, [
        h("span", { class: "capacity-dash-item-name" }, [l.label]),
        h("span", { class: "capacity-dash-item-value" }, [
          targetBytes > 0 ? `${formatBytes(usedBytes)} / ${formatBytes(targetBytes)}` : `${formatBytes(usedBytes)} / 미설정`,
        ]),
      ]));
      const track = h("div", { class: "capacity-dash-track" });
      track.appendChild(h("div", { class: "capacity-dash-fill" + (pct >= 100 ? " over" : pct >= 90 ? " warn" : ""), style: { width: pct + "%" } }));
      item.appendChild(track);
      item.appendChild(h("div", { class: "capacity-dash-item-foot" }, [
        h("span", {}, [targetBytes > 0 ? `${pct}%` : "-"]),
        h("span", {}, [
          targetBytes > 0
            ? (overBytes > 0 ? `초과: ${formatBytes(overBytes)}` : `Free: ${formatBytes(freeBytes)}`)
            : "",
        ]),
      ]));

      // [Dashboard 정돈] 목표 용량 편집(슬라이더/숫자입력)은 Settings > GameListSet과
      // 중복이었다 - Dashboard는 이제 읽기 전용 요약만 보여주고, 편집은 Settings에서만 한다.
      panel.appendChild(item);
    });
    return panel;
  }

  async function renderDashboard() {
    const root = document.getElementById("dashboard-view");
    clear(root);
    const tabs = [...S.locals.map((l) => ({ key: "local-" + l.id, label: l.label })), { key: "masterdb", label: "ArchiveDB" }];
    if (!dashState.tabKey || !tabs.find((t) => t.key === dashState.tabKey)) dashState.tabKey = tabs[0] ? tabs[0].key : "masterdb";

    // [신규] Health 요약 한 줄
    const healthRow = h("div", { class: "dash-health" }, ["불러오는 중..."]);
    root.appendChild(healthRow);
    api.getHealthInfo().then((hr) => {
      clear(healthRow);
      if (hr.ok) {
        const hd = hr.data;
        healthRow.appendChild(h("span", {}, [`LOCAL: ${hd.localCount}/${hd.localMax}개 등록`]));
        healthRow.appendChild(h("span", { class: "dash-health-sep" }, ["|"]));
        healthRow.appendChild(h("span", {}, [`SERVER: ${hd.masterdbPath}`]));
      }
    });

    // [신규] Local별 목표 용량 현황 + 조절(슬라이더/직접입력) 패널
    root.appendChild(renderCapacityDashPanel());

    const tabRow = h("div", { class: "dash-tabs" });
    tabs.forEach((t) => {
      const b = h("button", { class: "dash-tab" + (t.key === dashState.tabKey ? " active" : "") }, [t.label]);
      b.addEventListener("click", () => { dashState.tabKey = t.key; renderDashboard(); });
      tabRow.appendChild(b);
    });
    root.appendChild(tabRow);

    const scope = dashState.tabKey === "masterdb" ? "masterdb" : dashState.tabKey.replace("local-", "");
    // [버그 수정] Dashboard가 이번 세션에서 한 번도 스캔되지 않은 Local을 보여줄 때,
    // config.json에 남아있던(구버전 스캔에서 저장된, metadata_count가 아예 없을 수도
    // 있는) stats 스냅샷을 그대로 썼다. 그 결과 실제로 metadata/media가 있는데도
    // Dashboard에는 0으로 나오는 경우가 있었다. GameList와 동일하게 백그라운드
    // job으로 실제 스캔을 한 번 실행해 stats를 최신화한 뒤 다시 그린다.
    if (scope !== "masterdb" && !(S.localGamesCache[scope] && S.localGamesCache[scope].loaded)) {
      ensureLocalScanned(scope).then(() => {
        if (S.view === "dashboard" && dashState.tabKey === "local-" + scope) renderDashboard();
      });
    }
    const r = await api.getDashboardStats(scope, true);
    const data = r.ok ? r.data : { romCount: 0, romSizeBytes: 0, metadataCount: 0, mediaSizeBytes: 0, missingRom: 0, missingMedia: 0, systems: [] };

    // [신규] 6개 지표 카드
    const metrics = h("div", { class: "metric-cards" });
    [
      ["gamepad", "전체 ROM 개수", data.romCount, "var(--accent)"],
      ["hardDriveDownload", "전체 ROM 크기", formatBytes(data.romSizeBytes), null],
      ["fileWarning", "전체 metadata 개수", data.metadataCount, null],
      ["image", "전체 media 크기", formatBytes(data.mediaSizeBytes), null],
      ["fileWarning", "Missing ROM", data.missingRom, "var(--danger)"],
      ["imageOff", "Missing Media", data.missingMedia, "var(--warning)"],
    ].forEach(([iconName, label, value, color]) => {
      metrics.appendChild(h("div", { class: "metric-card" }, [
        h("div", { class: "metric-card-label" }, [icon(iconName, 13), label]),
        h("div", { class: "metric-card-value" }, [String(value)]),
      ]));
    });
    root.appendChild(metrics);

    // [신규] 시스템별 가로 막대그래프 (전체 ROM+media 용량, 눈금 최대 20GB 고정, 시스템별 색상)
    const BAR_MAX_BYTES = 20 * 1024 * 1024 * 1024; // 20GB
    const systemNames = data.systems.map((s) => s.system);
    const totalBytes = data.systems.reduce((sum, s) => sum + (s.romSizeBytes || 0) + (s.mediaSizeBytes || 0), 0);
    const barWrap = h("div", { class: "capacity-bar-wrap" });
    const barRow = h("div", { class: "capacity-bar-row" });
    const bar = h("div", { class: "capacity-bar" });
    let accPct = 0;
    data.systems.forEach((s) => {
      const segBytes = (s.romSizeBytes || 0) + (s.mediaSizeBytes || 0);
      const pct = Math.min(100 - accPct, (segBytes / BAR_MAX_BYTES) * 100);
      if (pct > 0) {
        bar.appendChild(h("div", { class: "capacity-bar-seg", style: { width: pct + "%", backgroundColor: colorForSystem(s.system, systemNames) }, title: `${s.system}: ${formatBytes(segBytes)}` }));
        accPct += pct;
      }
    });
    barRow.appendChild(bar);
    barRow.appendChild(h("div", { class: "capacity-bar-total" }, [formatBytes(totalBytes)]));
    barWrap.appendChild(barRow);
    barWrap.appendChild(h("div", { class: "capacity-bar-scale" }, ["눈금 최대: 20 GB"]));
    root.appendChild(barWrap);

    root.appendChild(h("div", { class: "stats-table-title" }, ["시스템별 상세 통계"]));
    const table = h("table", { class: "stats-table" });
    const thead = h("thead", {}, [h("tr", {}, ["", "System", "ROM 수", "ROM 크기", "Media 크기", "상태"].map((th) => h("th", {}, [th])))]);
    table.appendChild(thead);
    const tbody = h("tbody");
    data.systems.forEach((s) => {
      const ok = s.missing === 0;
      tbody.appendChild(h("tr", {}, [
        h("td", { style: { width: "18px" } }, [h("span", { class: "system-color-dot", style: { backgroundColor: colorForSystem(s.system, systemNames) } })]),
        h("td", { style: { textTransform: "uppercase", fontWeight: "600" } }, [s.system]),
        h("td", {}, [String(s.romCount)]),
        h("td", {}, [formatBytes(s.romSizeBytes)]),
        h("td", {}, [formatBytes(s.mediaSizeBytes)]),
        h("td", {}, [h("span", { class: "status-dot-wrap" }, [h("span", { class: "status-dot", style: { background: ok ? "var(--success)" : "var(--warning)" } }), ok ? "정상" : `누락 ${s.missing}`])]),
      ]));
    });
    table.appendChild(tbody);
    root.appendChild(table);
  }

  // ------------------------------------------------------------------
  // Settings
  // [0.4.1.x 체계화] General/GameListSet/Metadata/Media/ArchiveDB/Interface/Advanced
  // 7개 카테고리로 재구성. 백엔드 로직이 없는 항목은 "Coming soon"으로 비활성 표시하고,
  // 실제로 값이 반영되는 항목만 조작 가능하게 둔다.
  // ------------------------------------------------------------------
  let settingsSection = "general";
  function settingsHeading(text) {
    return h("div", { style: { fontWeight: "600", fontSize: "calc(15px * var(--font-scale))", marginBottom: "16px" } }, [text]);
  }
  // [GUI 정돈] 설명을 화면에 항상 띄우는 대신, 컨트롤 위에 마우스를 올렸을 때만
  // 보여주는 hover 툴팁으로 전환한다. el에 data-tip을 붙여 그대로 반환한다.
  function tip(el, text) {
    if (text) el.setAttribute("data-tip", text);
    return el;
  }
  // 라벨 + 컨트롤 한 줄을 만들고, desc는 화면에 계속 보이는 텍스트 대신 그 줄에
  // 올렸을 때 뜨는 툴팁으로 붙인다.
  function settingsRow(label, controlEl, desc) {
    const row = h("div", { class: "settings-row" });
    row.appendChild(h("div", {}, [h("div", { class: "field-label" }, [label])]));
    row.appendChild(controlEl);
    return tip(row, desc);
  }
  function settingsComingSoon(label, desc) {
    return h("div", { class: "settings-row settings-row-disabled" }, [
      h("div", {}, [
        h("div", { class: "field-label" }, [label, h("span", { class: "settings-soon-badge" }, ["Coming soon"])]),
        desc ? h("div", { class: "settings-row-desc" }, [desc]) : null,
      ].filter(Boolean)),
    ]);
  }
  // MetaData(1) / Media(세부 7종) / Rom(1) 그룹 체크박스 - Settings 기본값과 Export/Import
  // 선택 대화상자(드래그앤드롭 이동 포함)가 동일한 레이아웃/키를 공유한다.
  // selectedMediaTypes: draft.exportOptions.selected_media_types 배열을 그대로 in-place 변경한다.
  function renderTransferCheckboxGroups(container, selectedMediaTypes, opts) {
    opts = opts || {};
    const mediaTypeList = [
      ["covers", "Covers"], ["miximages", "MixImages"], ["screenshots", "Screenshots"],
      ["3dboxes", "3DBoxes"], ["marquees", "Marquees"], ["wheel", "Wheel"], ["videos", "Video"],
    ];
    container.appendChild(h("div", { class: "settings-section-title" }, ["MetaData"]));
    if (opts.metadataRow) container.appendChild(opts.metadataRow);
    container.appendChild(h("div", { class: "settings-section-title", style: { marginTop: "14px" } }, ["Media"]));
    const mediaGrid = h("div", { class: "settings-checkbox-grid" });
    mediaTypeList.forEach(([key, label]) => {
      const row = h("label", { class: "settings-checkbox-row" });
      const cb = h("input", { type: "checkbox", checked: selectedMediaTypes.includes(key) });
      cb.addEventListener("change", (e) => {
        const idx = selectedMediaTypes.indexOf(key);
        if (e.target.checked && idx === -1) selectedMediaTypes.push(key);
        else if (!e.target.checked && idx !== -1) selectedMediaTypes.splice(idx, 1);
      });
      row.appendChild(cb); row.appendChild(h("span", {}, [label]));
      mediaGrid.appendChild(row);
    });
    container.appendChild(mediaGrid);
    if (opts.romRow) {
      container.appendChild(h("div", { class: "settings-section-title", style: { marginTop: "14px" } }, ["Rom"]));
      container.appendChild(opts.romRow);
    }
  }

  async function renderSettings() {
    const root = document.getElementById("settings-view");
    clear(root);
    initCustomTitlebar();
    const r = await api.getSettings();
    const cur = r.ok ? r.data : S.settings;
    const draft = {
      lang: cur.lang, theme: cur.theme, saveInterval: cur.saveInterval, exportOptions: { ...cur.exportOptions },
      startupPage: cur.startupPage || "dashboard",
      confirmDestructiveActions: cur.confirmDestructiveActions !== false,
      loggingEnabled: !!cur.loggingEnabled,
      defaultListView: cur.defaultListView || "list",
      deferVideoMedia: cur.deferVideoMedia !== false,
    };
    draft.exportOptions.selected_media_types = draft.exportOptions.selected_media_types || ["screenshots", "3dboxes", "covers", "marquees", "miximages", "wheel"];
    let simThreshold = 60;
    const simSettingsPromise = api.getSimilarRomSettings();

    async function saveAll() {
      const res = await api.saveSettings(draft.lang, draft.theme, draft.saveInterval, {
        koreanOnly: draft.exportOptions.korean_only_on_conflict, copyMedia: draft.exportOptions.copy_media,
        // [GUI 정돈] "Video도 복사"는 Media 그리드의 Video 체크박스(selected_media_types)와
        // 완전히 같은 걸 두 번 묻는 중복 컨트롤이었다 - UI에서 지우고, 실제 게이트는
        // selected_media_types 하나로 통일한다. copyVideo는 항상 true로 보내 두 번째
        // 게이트가 더 이상 아무것도 막지 않게 한다.
        copyVideo: true, forceOverwrite: draft.exportOptions.force_overwrite,
        selected_media_types: draft.exportOptions.selected_media_types, copyRom: !!draft.exportOptions.copy_rom,
      });
      const res2 = await api.saveUiSettings(draft.startupPage, draft.confirmDestructiveActions, draft.loggingEnabled, draft.defaultListView);
      await api.savePerformanceSettings(draft.deferVideoMedia);
      if (res.ok && res2.ok) {
        await api.saveSimilarRomSettings({}, simThreshold);
        applyTheme(draft.theme);
        S.settings = { ...S.settings, ...draft, confirmDestructiveActions: draft.confirmDestructiveActions };
        api._loggingEnabled = draft.loggingEnabled;
        showToast("설정이 저장되었습니다.");
      } else showToast((res.ok ? res2 : res).error || "저장 실패", "error");
    }
    function saveButton() {
      const btn = h("button", { class: "btn primary" }, [icon("save", 13), h("span", {}, ["설정 저장"])]);
      btn.addEventListener("click", saveAll);
      return btn;
    }

    // [GUI 정돈] 닫기(X) 버튼 제거 - 좌측 메인 사이드바(Dashboard/ArchiveDB/GameListSet
    // 등)가 Settings 화면에서도 항상 그대로 떠 있어서, 거기서 다른 메뉴를 누르면 이미
    // Settings를 벗어날 수 있다. 같은 기능을 하는 버튼이 두 군데 있을 필요가 없었다.
    const menu = h("div", { class: "settings-menu" });
    const menuTitle = h("div", { class: "settings-menu-title" }, [h("span", {}, ["Settings"])]);
    menu.appendChild(menuTitle);
    const sections = [
      ["general", "General"], ["gamelistset", "GameListSet"], ["metadata", "Metadata"],
      ["media", "Media"], ["archivedb", "ArchiveDB"], ["interface", "Interface"], ["advanced", "Advanced"],
    ];
    sections.forEach(([key, label]) => {
      const b = h("button", { class: settingsSection === key ? "active" : "" }, [label]);
      b.addEventListener("click", () => { settingsSection = key; renderSettings(); });
      menu.appendChild(b);
    });
    // [GUI 정돈] 예전엔 "설정 저장" 버튼이 탭마다(General/GameListSet/Metadata/Media)
    // 따로 붙어있어 일관성이 없었다. 하나로 합쳐 네비게이션 가장 아래 고정한다 -
    // 어느 탭에 있든 항상 같은 자리에서 저장할 수 있다.
    const footer = h("div", { class: "settings-menu-footer" }, [saveButton()]);
    menu.appendChild(footer);
    root.appendChild(menu);

    const content = h("div", { class: "settings-content" });
    root.appendChild(content);

    // ---------------- General ----------------
    if (settingsSection === "general") {
      content.appendChild(settingsHeading("General"));

      const langSel = h("select", { class: "field-input" }, []);
      [["ko", "한국어"], ["en", "English"]].forEach(([v, l]) => { const o = h("option", { value: v }, [l]); if (draft.lang === v) o.selected = true; langSel.appendChild(o); });
      langSel.addEventListener("change", (e) => (draft.lang = e.target.value));
      content.appendChild(settingsRow("Language", langSel, "메뉴/목록 헤더 등 주요 UI 문자열의 언어를 전환합니다. (저장을 눌러야 적용)"));

      const themeSel = h("select", { class: "field-input" });
      [["system", "시스템 설정"], ["dark", "Dark"], ["light", "Light"]].forEach(([v, l]) => { const o = h("option", { value: v }, [l]); if (draft.theme === v) o.selected = true; themeSel.appendChild(o); });
      themeSel.addEventListener("change", (e) => (draft.theme = e.target.value));
      content.appendChild(settingsRow("Theme", themeSel, "시스템 설정을 고르면 OS의 다크모드 여부를 따라갑니다."));

      const startupSel = h("select", { class: "field-input" });
      [["dashboard", "Dashboard"], ["archivedb", "ArchiveDB"]].forEach(([v, l]) => { const o = h("option", { value: v }, [l]); if (draft.startupPage === v) o.selected = true; startupSel.appendChild(o); });
      startupSel.addEventListener("change", (e) => (draft.startupPage = e.target.value));
      content.appendChild(settingsRow("Startup Page", startupSel, "프로그램을 시작할 때 처음 보여줄 화면입니다."));

      const confirmRow = tip(h("label", { class: "settings-checkbox-row" }), "삭제 등 되돌릴 수 없는 작업 전에 확인창을 표시합니다. 끄면 즉시 실행됩니다.");
      const confirmCb = h("input", { type: "checkbox", checked: draft.confirmDestructiveActions });
      confirmCb.addEventListener("change", (e) => (draft.confirmDestructiveActions = e.target.checked));
      confirmRow.appendChild(confirmCb);
      confirmRow.appendChild(h("span", {}, ["Confirmations"]));
      content.appendChild(confirmRow);

      const logRow = tip(h("label", { class: "settings-checkbox-row" }), "백엔드 호출 로그를 브라우저 개발자 콘솔에 출력합니다 (문제 재현 시 진단용).");
      const logCb = h("input", { type: "checkbox", checked: draft.loggingEnabled });
      logCb.addEventListener("change", (e) => (draft.loggingEnabled = e.target.checked));
      logRow.appendChild(logCb);
      logRow.appendChild(h("span", {}, ["Logging"]));
      content.appendChild(logRow);

      const intervalSel = h("select", { class: "field-input" });
      [[5, "5분"], [10, "10분"], [30, "30분"], [60, "1시간"], [0, "저장 안 함"]].forEach(([v, l]) => { const o = h("option", { value: String(v) }, [l]); if (draft.saveInterval === v) o.selected = true; intervalSel.appendChild(o); });
      intervalSel.addEventListener("change", (e) => (draft.saveInterval = Number(e.target.value)));
      content.appendChild(settingsRow("자동 저장 간격", intervalSel, '설정한 주기마다 config.json을 자동 저장합니다. "저장 안 함" 선택 시 종료할 때만 저장됩니다.'));
    }

    // ---------------- GameListSet (구 Local) ----------------
    if (settingsSection === "gamelistset") {
      content.appendChild(settingsHeading("GameListSet"));

      content.appendChild(h("div", { class: "settings-section-title" }, ["GameListSet Paths"]));
      S.locals.forEach((l) => {
        const row = h("div", { class: "local-mgmt-row" }, [h("span", { style: { fontSize: "calc(12px * var(--font-scale))" } }, [`${l.label} (${l.frontendLabel || l.frontend})`])]);
        const actions = h("div", { class: "flex gap-1" });
        const editBtn = tip(h("button", { class: "icon-btn" }, [icon("folderOpen", 13)]), "Metadata/ROM 경로를 다시 선택합니다.");
        editBtn.addEventListener("click", () => openEditLocalPaths(l));
        const delBtn = h("button", { class: "icon-btn icon-btn-danger" }, [icon("trash", 13)]);
        delBtn.addEventListener("click", () => {
          showConfirm("GameListSet 삭제", `'${l.label}'을(를) 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.`, true, async () => {
            closeConfirm();
            const r2 = await api.deleteLocal(l.id);
            if (r2.ok) {
              showToast(`${l.label} 삭제됨`, "warning");
              await loadLocals(); renderSidebar(); renderSettings();
              if (S.view === "local-" + l.id) goView("masterdb");
            } else showToast(r2.error, "error");
          });
        });
        actions.appendChild(editBtn); actions.appendChild(delBtn);
        row.appendChild(actions);
        content.appendChild(row);
        // [신규] 현재 경로 정보를 박스 안에 표시 - 예전엔 삭제 버튼만 있고 지금 어느
        // 경로를 보고 있는지 Settings에서 확인할 방법이 없었다.
        const info = h("div", { class: "local-path-info" }, [
          h("div", { class: "local-path-row" }, [h("span", { class: "local-path-key" }, ["Metadata Path"]), h("span", { class: "local-path-val" }, [l.metadata_path || "(미설정)"])]),
          h("div", { class: "local-path-row" }, [h("span", { class: "local-path-key" }, ["Rom Path"]), h("span", { class: "local-path-val" }, [l.rom_path || "(미설정)"])]),
        ]);
        content.appendChild(info);
      });

      content.appendChild(h("div", { class: "settings-section-title", style: { marginTop: "16px" } }, ["Target Capacity"]));
      S.locals.forEach((l) => {
        const row = h("div", { class: "settings-row" });
        const targetBytes = Number(l.target_capacity_bytes) || 0;
        const targetGB = targetBytes > 0 ? Math.round(targetBytes / (1024 ** 3)) : 0;
        const slider = h("input", {
          type: "range", min: "0", max: String(CAPACITY_SLIDER_MAX_GB), step: "10",
          value: String(Math.min(targetGB, CAPACITY_SLIDER_MAX_GB)), class: "capacity-dash-slider",
        });
        const numberInput = h("input", { type: "number", min: "0", step: "1", value: String(targetGB), class: "capacity-dash-number" });
        let saveTimer = null;
        const commit = (gbValue) => {
          const bytes = Math.max(0, Math.round(gbValue)) * (1024 ** 3);
          clearTimeout(saveTimer);
          saveTimer = setTimeout(async () => {
            const rr = await api.setLocalTargetCapacity(l.id, bytes > 0 ? bytes : null);
            if (rr.ok) { l.target_capacity_bytes = bytes > 0 ? bytes : null; showToast(`${l.label} 목표 용량 저장됨`); }
            else showToast(rr.error, "error");
          }, 400);
        };
        slider.addEventListener("input", () => { numberInput.value = slider.value; });
        slider.addEventListener("change", () => commit(Number(slider.value)));
        numberInput.addEventListener("input", () => { slider.value = String(Math.min(Number(numberInput.value) || 0, CAPACITY_SLIDER_MAX_GB)); });
        numberInput.addEventListener("change", () => commit(Number(numberInput.value) || 0));
        row.appendChild(h("div", {}, [h("div", { class: "field-label" }, [l.label])]));
        const line = h("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, [slider, numberInput, h("span", { style: { color: "var(--muted)", fontSize: "calc(11px * var(--font-scale))" } }, ["GB (0 = 제한 없음)"])]);
        row.appendChild(line);
        content.appendChild(tip(row, "Dashboard 상단 카드에도 같은 값 기준으로 용량 게이지가 표시됩니다."));
      });

      content.appendChild(h("div", { class: "settings-section-title", style: { marginTop: "16px" } }, ["Scan Interval"]));
      content.appendChild(settingsComingSoon("자동 스캔 주기", "현재는 Refresh List를 수동으로 눌러야 합니다. 백그라운드 자동 스캔은 아직 지원하지 않습니다."));

    }

    // ---------------- Metadata ----------------
    if (settingsSection === "metadata") {
      content.appendChild(settingsHeading("Metadata"));

      content.appendChild(h("div", { class: "settings-section-title" }, ["Similar ROM"]));
      const simRow = h("div", { class: "settings-row" });
      const simCol = h("div", { style: { flex: "1" } }, [h("div", { class: "field-label" }, ["유사 ROM 임계값"])]);
      const simLine = h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } });
      const simRange = h("input", { type: "range", min: "0", max: "100", step: "1", value: "60", style: { flex: "1" } });
      const simPct = h("span", { style: { width: "48px", textAlign: "right", fontWeight: "600" } }, ["60%"]);
      simRange.addEventListener("input", (e) => { simThreshold = Number(e.target.value); simPct.textContent = `${simThreshold}%`; });
      simLine.appendChild(simRange); simLine.appendChild(simPct); simCol.appendChild(simLine); simRow.appendChild(simCol);
      content.appendChild(simRow);
      simSettingsPromise.then((sr) => { if (sr.ok) { simThreshold = Number(sr.data.threshold) || 60; simRange.value = String(simThreshold); simPct.textContent = `${simThreshold}%`; } });

      content.appendChild(h("div", { class: "settings-section-title", style: { marginTop: "16px" } }, ["Title Normalization"]));
      content.appendChild(settingsComingSoon("타이틀 정규화 규칙", "지역 접미사/버전 표기 등을 자동 정리하는 규칙 편집기는 아직 없습니다."));
      content.appendChild(h("div", { class: "settings-section-title", style: { marginTop: "10px" } }, ["Region"]));
      content.appendChild(settingsComingSoon("지역 우선순위", "여러 지역 metadata가 있을 때 우선순위를 정하는 기능은 아직 없습니다."));
      content.appendChild(h("div", { class: "settings-section-title", style: { marginTop: "10px" } }, ["Metadata Priority"]));
      content.appendChild(settingsComingSoon("소스별 우선순위", "스크랩 소스별 metadata 우선순위 설정은 아직 없습니다."));

    }

    // ---------------- Media ----------------
    if (settingsSection === "media") {
      content.appendChild(settingsHeading("Media"));

      // [GUI 정돈] "Media도 복사"는 지금 당장 뭘 복사하는 동작이 아니라, Export/Import
      // 대화상자가 열릴 때 기본으로 켜져 있을지를 정하는 태깅일 뿐이다 - 이름을 그
      // 의미에 맞게 바꾼다.
      const copyMediaRow = tip(h("label", { class: "settings-checkbox-row" }), "Export/Import 대화상자를 열 때 Media 항목이 기본으로 켜져 있을지를 정합니다.");
      const copyMediaCb = h("input", { type: "checkbox", checked: !!draft.exportOptions.copy_media });
      copyMediaCb.addEventListener("change", (e) => (draft.exportOptions.copy_media = e.target.checked));
      copyMediaRow.appendChild(copyMediaCb);
      copyMediaRow.appendChild(h("span", {}, ["Media 기본 포함"]));

      // [GUI 정돈] "Video도 복사"는 바로 아래 Media 그리드의 Video 체크박스와 완전히
      // 같은 걸 두 번 묻는 중복 컨트롤이었다 - 제거하고 selected_media_types 하나로
      // 통일한다 (copy_video는 항상 true로 저장 - saveAll() 참고).
      const metaCbRow = h("label", { class: "settings-checkbox-row" });
      const metaCb = h("input", { type: "checkbox", checked: true, disabled: true, title: "Metadata는 항상 포함됩니다" });
      metaCbRow.appendChild(metaCb); metaCbRow.appendChild(h("span", {}, ["metadata (항상 포함)"]));

      const romCbRow = h("label", { class: "settings-checkbox-row" });
      const romCb = h("input", { type: "checkbox", checked: !!draft.exportOptions.copy_rom });
      romCb.addEventListener("change", (e) => (draft.exportOptions.copy_rom = e.target.checked));
      romCbRow.appendChild(romCb); romCbRow.appendChild(h("span", {}, ["Rom"]));

      renderTransferCheckboxGroups(content, draft.exportOptions.selected_media_types, { metadataRow: copyMediaRow, romRow: romCbRow });
    }

    // ---------------- ArchiveDB (구 MasterDB) ----------------
    if (settingsSection === "archivedb") {
      content.appendChild(settingsHeading("ArchiveDB"));

      content.appendChild(h("div", { class: "settings-section-title" }, ["Database Path"]));
      // [GUI 정돈] 라벨 없이 field-input이 전체 폭을 다 차지해서 경로가 길어질수록
      // 버튼과 멀어져 보였다. "DB Path :" 라벨 + 말줄임(ellipsis) 한 줄 + 버튼으로
      // 고정폭 레이아웃으로 정리한다.
      const dbPathRow = h("div", { class: "db-path-row" }, [h("div", { class: "field-label" }, ["DB Path"])]);
      const pathVal = tip(h("span", { class: "db-path-val" }, [S.masterdb.root || S.masterdb.path || "(미설정)"]), S.masterdb.root || S.masterdb.path || "(미설정)");
      const changePathBtn = h("button", { class: "btn" }, [icon("folderOpen", 13), h("span", {}, ["변경"])]);
      changePathBtn.addEventListener("click", async () => {
        const picked = await api.pickFolder("ArchiveDB 저장 위치 선택");
        if (!picked.ok || !picked.data) return;
        const rr = await api.setMasterdbPath(picked.data);
        if (rr.ok) { showToast("ArchiveDB 경로가 변경되었습니다."); await refreshAll(); renderSettings(); }
        else showToast(rr.error, "error");
      });
      dbPathRow.appendChild(pathVal);
      dbPathRow.appendChild(changePathBtn);
      content.appendChild(dbPathRow);

      content.appendChild(h("div", { class: "settings-section-title", style: { marginTop: "16px" } }, ["백업 / 복원"]));
      content.appendChild(h("p", { style: { color: "var(--muted)", fontSize: "calc(11.5px * var(--font-scale))", marginBottom: "12px" } }, ["백업은 실행 파일 위치의 backup\\ 폴더에 날짜/시각을 붙여 저장됩니다."]));
      const btnRow = h("div", { class: "flex gap-2", style: { marginBottom: "16px" } });
      const backupBtn = h("button", { class: "btn primary" }, [icon("hardDriveDownload", 13), h("span", {}, ["지금 백업"])]);
      backupBtn.addEventListener("click", async () => {
        const r2 = await api.doBackup();
        if (r2.ok) showToast(`백업 완료: ${r2.data.path}`);
        else showToast(r2.error, "error");
      });
      const restoreBtn = h("button", { class: "btn" }, [icon("hardDriveUpload", 13), h("span", {}, ["복원"])]);
      const listBox = h("div", { class: "backup-list hidden" });
      restoreBtn.addEventListener("click", async () => {
        listBox.classList.toggle("hidden");
        if (listBox.classList.contains("hidden")) return;
        clear(listBox);
        const r2 = await api.listBackups();
        if (r2.ok) {
          r2.data.forEach((name) => {
            const b = h("button", {}, [name]);
            b.addEventListener("click", () => {
              showConfirm("백업 복원", `'${name}'으로 현재 ArchiveDB를 덮어씁니다. 계속하시겠습니까?`, true, async () => {
                closeConfirm();
                const r3 = await api.restoreBackup(name);
                if (r3.ok) { showToast("복원 완료 — 재시작이 필요합니다.", "warning"); listBox.classList.add("hidden"); }
                else showToast(r3.error, "error");
              });
            });
            listBox.appendChild(b);
          });
        }
      });
      btnRow.appendChild(backupBtn); btnRow.appendChild(restoreBtn);
      content.appendChild(btnRow);
      content.appendChild(listBox);
    }

    // ---------------- Interface ----------------
    if (settingsSection === "interface") {
      content.appendChild(settingsHeading("Interface"));

      const previewSel = h("select", { class: "field-input" });
      [["list", "List"], ["preview", "Preview"]].forEach(([v, l]) => { const o = h("option", { value: v }, [l]); if (draft.defaultListView === v) o.selected = true; previewSel.appendChild(o); });
      previewSel.addEventListener("change", (e) => (draft.defaultListView = e.target.value));
      content.appendChild(settingsRow("Preview (기본 목록 보기)", previewSel, "GameListSet/ArchiveDB 화면에 처음 들어갔을 때의 기본 보기 방식입니다."));
    }

    // ---------------- Advanced ----------------
    if (settingsSection === "advanced") {
      content.appendChild(settingsHeading("Advanced"));

      const deferRow = tip(
        h("label", { class: "settings-checkbox-row" }),
        "Scan/Import/Export에서 비디오는 뒤로 미루고 커버+메타데이터부터 먼저 끝냅니다. 진행되는 동안 해당 GameListSet/ArchiveDB의 삭제·이름변경은 잠시 막히고, 메타데이터 편집은 그대로 가능합니다.",
      );
      const deferCb = h("input", { type: "checkbox", checked: draft.deferVideoMedia });
      deferCb.addEventListener("change", (e) => (draft.deferVideoMedia = e.target.checked));
      deferRow.appendChild(deferCb);
      deferRow.appendChild(h("span", {}, ["비디오 지연 복사로 체감 속도 올리기"]));
      content.appendChild(deferRow);
    }
  }

  // ------------------------------------------------------------------
  // Compare (v0.5 9단계): GameListSet 대 GameListSet, 또는 MasterDB 대 GameListSet
  // ROM 목록을 파일명 기준 2열로 나란히 비교한다 (Beyond Compare 스타일).
  // ------------------------------------------------------------------
  // [버그 수정] 이전엔 처음 조회한 결과를 세션 내내 캐싱해서, Compare를 연 뒤에
  // GameListSet을 추가/삭제해도 드롭다운에 반영되지 않았다. list_compare_sources()는
  // config에서 읽어오는 가벼운 호출이라 매번 새로 불러도 부담이 없다.
  async function ensureCompareSources() {
    const r = await api.listCompareSources();
    return r.ok ? r.data : [];
  }

  async function loadCompareRows() {
    const c = S.compare;
    c.loaded = true;
    if (!c.sourceA || !c.sourceB || c.sourceA === c.sourceB) { c.rows = []; renderCompare(); return; }
    c.loading = true;
    renderCompare();
    const r = await api.compareSources(c.sourceA, c.sourceB);
    c.loading = false;
    if (r.ok) {
      c.rows = r.data;
      // [버그 수정] 소스를 바꾸면 이전에 선택돼 있던 System 필터가 새 소스 조합에
      // 존재하지 않을 수 있다(예: PS2로 필터링 중 오른쪽 소스를 PS2가 없는
      // GameListSet으로 바꾸면 "표시할 항목이 없습니다"만 뜨고 원인을 알 수 없었다).
      // 새 결과에 없는 system이면 조용히 "전체"로 되돌린다.
      if (S.selectedSystem !== "all" && !c.rows.some((row) => row.system === S.selectedSystem)) {
        S.selectedSystem = "all";
      }
    } else { c.rows = []; showToast(r.error || "비교 실패", "error"); }
    renderCompare();
    // 사이드바의 GAME SYSTEMS 목록은 c.rows에서 뽑으므로, 새로 불러온 뒤 같이 갱신한다.
    renderSidebar();
  }

  // "system|filename" 형식 키 - db.make_rom_key와 동일한 규약(다중 선택 Set에 씀).
  function compareRowKey(entry) { return `${entry.system}|${entry.filename}`; }

  // [버그 수정] Ctrl+A가 이 필터링 로직을 renderLists() 안에서 따로 베껴 쓰고 있었는데,
  // 그때는 검색/시스템만 반영하고 관계 필터([*≠=])/즐겨찾기는 빠져 있었다 - 필터를
  // 걸어서 화면엔 3개만 보이는데 Ctrl+A를 누르면 필터 이전의 훨씬 많은 행이 전부
  // 선택되는 문제였다. renderLists()와 Ctrl+A 둘 다 이 함수 하나만 쓰게 만들어서,
  // 앞으로 필터가 추가돼도 Ctrl+A가 자동으로 따라가게 한다.
  function getFilteredCompareRows() {
    const c = S.compare;
    const q = c.search.trim().toLowerCase();
    let rows = q ? c.rows.filter((r) => r.file.toLowerCase().includes(q)) : c.rows;
    if (S.selectedSystem && S.selectedSystem !== "all") rows = rows.filter((r) => r.system === S.selectedSystem);
    if (c.relFilter === "same") rows = rows.filter((r) => r.matched && !r.diff);
    else if (c.relFilter === "diff") rows = rows.filter((r) => !r.matched || r.diff);
    if (c.favoriteOnly) rows = rows.filter((r) => (r.left && r.left.favorite) || (r.right && r.right.favorite));
    return rows;
  }

  // [신규] 가운데 열의 개별 행 화살표(빨간색) 클릭 - 그 행 하나만 즉시 복사한다.
  // 다중 선택 상태와는 무관하게 항상 그 행 자신만 대상으로 한다.
  async function copySingleCompareRow(entry, direction) {
    const c = S.compare;
    const r = await runIndeterminateProgress(
      api.compareCopyRow(c.sourceA, c.sourceB, direction, entry.system, entry.filename),
      `${entry.filename} 복사 중...`,
    );
    if (r.ok) {
      // [수정] metadata는 됐는데 media/ROM 중 일부가 실패한 "부분 성공"도 있을 수
      // 있다(예: 대상에 이미 같은 이름 ROM이 있어 ROM만 건너뜀) - 조용히 "복사되었습니다"로
      // 뭉개지 않고 경고로 표시한다.
      if (r.data && r.data.partial) {
        const detail = r.data.romConflicts ? " (ROM은 대상에 이미 있어 건너뜀)" : "";
        showToast(`일부만 복사되었습니다${detail}.`, "warning");
      } else {
        showToast("복사되었습니다.");
      }
      await loadCompareRows();
    } else {
      showToast(r.error || "복사 실패", "error");
    }
  }

  // [신규] 상단 >/< 버튼 - 다중 선택된 행을 한꺼번에 복사한다.
  async function copySelectedCompareRows(direction) {
    const c = S.compare;
    const keys = direction === "toRight" ? c.selectedLeftKeys : c.selectedRightKeys;
    if (!keys.size) return;
    const items = Array.from(keys).map((k) => {
      const sep = k.indexOf("|");
      return { system: k.slice(0, sep), filename: k.slice(sep + 1) };
    });
    const r = await runIndeterminateProgress(
      api.compareCopyRows(c.sourceA, c.sourceB, direction, items),
      `${items.length}개 항목 복사 중...`,
    );
    if (r.ok) {
      const { copied, total, failed } = r.data;
      if (failed.length) showToast(`${copied}/${total}개 복사됨 (${failed.length}개 실패: ${failed[0].filename} 등)`, "error");
      else showToast(`${copied}개 복사되었습니다.`);
      c.selectedLeftKeys.clear();
      c.selectedRightKeys.clear();
      c.leftAnchor = null;
      c.rightAnchor = null;
      await loadCompareRows();
    } else {
      showToast(r.error || "복사 실패", "error");
    }
  }

  // [신규] GameList의 다중 선택 클릭 규약(app.js의 행 클릭 핸들러, ~line 979)과
  // 최대한 똑같이 맞춘다: 그냥 클릭=단일 선택(같은 걸 다시 누르면 해제),
  // Ctrl/Cmd+클릭=토글 추가, Shift+클릭=anchor부터 범위 선택,
  // Ctrl+Shift+클릭=범위 추가(기존 선택 유지).
  function handleCompareRowClick(e, entry, side, orderedEntries) {
    const c = S.compare;
    c.lastActiveSide = side;
    const keys = side === "left" ? c.selectedLeftKeys : c.selectedRightKeys;
    const anchorField = side === "left" ? "leftAnchor" : "rightAnchor";
    const key = compareRowKey(entry);

    function rangeIndexes(anchorKey) {
      const anchorIdx = orderedEntries.findIndex((x) => compareRowKey(x) === anchorKey);
      const curIdx = orderedEntries.findIndex((x) => compareRowKey(x) === key);
      if (anchorIdx === -1 || curIdx === -1) return null;
      return anchorIdx < curIdx ? [anchorIdx, curIdx] : [curIdx, anchorIdx];
    }

    if (e.shiftKey && !(e.ctrlKey || e.metaKey)) {
      const range = c[anchorField] && rangeIndexes(c[anchorField]);
      if (range) {
        keys.clear();
        for (let i = range[0]; i <= range[1]; i++) keys.add(compareRowKey(orderedEntries[i]));
      } else {
        keys.clear(); keys.add(key); c[anchorField] = key;
      }
    } else if (e.ctrlKey || e.metaKey) {
      if (e.shiftKey && c[anchorField]) {
        const range = rangeIndexes(c[anchorField]);
        if (range) for (let i = range[0]; i <= range[1]; i++) keys.add(compareRowKey(orderedEntries[i]));
      } else {
        if (keys.has(key)) keys.delete(key); else keys.add(key);
        c[anchorField] = key;
      }
    } else {
      if (keys.size === 1 && keys.has(key)) keys.clear();
      else { keys.clear(); keys.add(key); }
      c[anchorField] = key;
    }
    renderCompare();
  }

  // [버그 수정] renderCompare()는 loadCompareRows() 안에서 await 없이 다시
  // 호출되는데(로딩 시작 시 한 번, 끝났을 때 한 번), 예전엔 root를 이 함수 맨
  // 앞(await 이전)에서 지웠다 - 두 호출이 겹치면 먼저 시작한 쪽이 나중에 끝나
  // 자기 내용을 다시 이어붙이면서 .compare-lists가 두 개 생기는 경합이 있었다.
  // render 세대(compareRenderSeq)를 매겨, await 이후 더 최신 호출이 이미
  // 시작됐으면 그 자리에서 조용히 멈추고 최신 호출만 실제로 그리게 한다.
  let compareRenderSeq = 0;
  async function renderCompare() {
    const mySeq = ++compareRenderSeq;
    const root = document.getElementById("compare-view");
    const c = S.compare;

    const sources = await ensureCompareSources();
    if (mySeq !== compareRenderSeq) return; // 그 사이 더 최신 renderCompare()가 시작됨
    clear(root);
    if (!c.sourceA && sources[0]) c.sourceA = sources[0].id;
    if (!c.sourceB && sources.find((s) => s.id !== c.sourceA)) c.sourceB = sources.find((s) => s.id !== c.sourceA).id;

    // [수정] 상단의 큰 소스 선택 폼 + 검색만 있던 헤더를, GameList 필터바와 최대한
    // 같은 순서/구성의 툴바로 바꾼다: [뷰 토글] [시스템] [즐겨찾기] [*≠=] [검색]
    // [새로고침] [A100%]. "상태"(완료/부분/누락) 드롭다운만 뺐다 - Compare 행에는
    // 그 개념 자체가 없고, 대신 그 역할을 [*≠=] 관계 필터가 한다. 소스 전환은
    // 여기서 select로 하지 않고 각 목록 제목 우측 끝의 작은 버튼(sourceTitleDropdown)
    // 으로 옮겼다(swap 버튼은 이미 두 목록 제목 사이 가운데(centerCol)에 있음).
    function clearCompareSelection() {
      c.selectedLeftKeys.clear(); c.selectedRightKeys.clear(); c.leftAnchor = null; c.rightAnchor = null; c.lastActiveSide = null;
    }
    function changeCompareSource(side, id) {
      if (side === "left") c.sourceA = id; else c.sourceB = id;
      c.loaded = false;
      clearCompareSelection();
      loadCompareRows();
    }
    // [신규] 목록 제목 바 우측 끝에 다는 작은 소스 전환 버튼 - 누르면 소스 목록을
    // 띄우는 작은 메뉴. compare-list-panel이 overflow:hidden(둥근 모서리 클리핑용)
    // 이라 그 안에 일반 absolute .dropdown-menu를 두면 잘려서, 메뉴는 body에
    // 직접 붙이고 위치는 버튼 좌표 기준 fixed로 계산한다.
    function sourceTitleDropdown(side, current) {
      // [버그 수정] 반대편에 이미 선택된 소스를 여기서 또 고를 수 있었다 - 고르면
      // "서로 다른 소스를 선택하세요"만 뜨고 비교가 비어버려서 혼란스러웠다.
      // 반대편 소스는 메뉴에서 disabled로 표시해 애초에 선택하지 못하게 막는다.
      const otherId = side === "left" ? c.sourceB : c.sourceA;
      const btn = h("button", { class: "icon-btn compare-title-dropdown-btn", title: "소스 변경" }, [icon("chevronDown", 12)]);
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        closeDropdowns();
        const rect = btn.getBoundingClientRect();
        openBodyMenu(btn, { top: (rect.bottom + 6) + "px", right: (window.innerWidth - rect.right) + "px" }, (menu, close) => {
          sources.forEach((s) => {
            const isOther = s.id === otherId;
            const b = h("button", {
              class: (s.id === current ? "selected" : "") + (isOther ? " disabled" : ""),
              disabled: isOther,
              title: isOther ? "같은 소스는 비교할 수 없습니다." : "",
            }, [s.label]);
            if (!isOther) b.addEventListener("click", () => { close(); changeCompareSource(side, s.id); });
            menu.appendChild(b);
          });
        });
      });
      return btn;
    }

    const filterBar = h("div", { class: "compare-filter-bar" });

    const exitBtn = h("button", { class: "btn compare-exit-btn", title: "비교를 마치고 이전 화면으로 돌아갑니다" }, [icon("chevronLeft", 13), h("span", {}, ["비교 종료"])]);
    exitBtn.addEventListener("click", exitCompare);
    filterBar.appendChild(exitBtn);

    const toggle = h("div", { class: "view-toggle" });
    const listBtn = h("button", { class: c.viewMode === "list" ? "active" : "", title: "List 보기", onClick: () => { c.viewMode = "list"; renderLists(); toggle.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", i === 0)); } }, [icon("layoutList", 13)]);
    const cardBtn = h("button", { class: c.viewMode === "card" ? "active" : "", title: "카드 보기", onClick: () => { c.viewMode = "card"; renderLists(); toggle.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", i === 1)); } }, [icon("layoutGrid", 13)]);
    toggle.appendChild(listBtn); toggle.appendChild(cardBtn);
    filterBar.appendChild(toggle);

    // [신규] GameList의 시스템 드롭다운과 동일한 컴포넌트(makeDropdown) 재사용 -
    // 사이드바 SYSTEM 목록과 같은 S.selectedSystem을 공유한다(둘 다 같은 상태를
    // 다른 진입점에서 바꾸는 것뿐이라 항상 서로 일치한다).
    const compareSystems = getCompareSystems();
    const curCompareSys = compareSystems.find((s) => s.key === S.selectedSystem) || compareSystems[0];
    const systemDropdown = makeDropdown("hardDrive", `${curCompareSys.label} (${curCompareSys.count})`, (menu) => {
      compareSystems.forEach((s) => {
        const b = h("button", { class: s.key === S.selectedSystem ? "selected" : "" }, [`${s.label} (${s.count})`]);
        b.addEventListener("click", () => { S.selectedSystem = s.key; closeDropdowns(); renderSidebar(); renderCompare(); });
        menu.appendChild(b);
      });
    });
    systemDropdown.querySelector("button").title = "특정 시스템으로 좁혀서 비교";
    filterBar.appendChild(systemDropdown);

    if (c.sourceA === "masterdb" || c.sourceB === "masterdb") {
      const favLabel = h("label", { class: "similar-group-toggle favorite-only-toggle", title: "왼쪽 또는 오른쪽 중 하나라도 즐겨찾기면 표시" });
      const favCb = h("input", { type: "checkbox", checked: c.favoriteOnly });
      favCb.addEventListener("change", (e) => { c.favoriteOnly = e.target.checked; renderLists(); });
      favLabel.appendChild(favCb);
      favLabel.appendChild(icon("star", 12));
      favLabel.appendChild(h("span", {}, ["즐겨찾기"]));
      filterBar.appendChild(favLabel);
    }

    // [신규] 관계 필터 - 전체 롬 / 메타데이터가 다르거나 한쪽에만 있는 롬만 /
    // 완전히 동일한 롬만. 즐겨찾기 바로 우측.
    const relToggle = h("div", { class: "view-toggle compare-rel-toggle" });
    const relOptions = [
      { key: "all", label: "전체 보기", char: "*" },
      { key: "diff", label: "다르거나 한쪽에만 있는 항목만", char: "≠" },
      { key: "same", label: "동일한 항목만", char: "=" },
    ];
    relOptions.forEach((opt) => {
      const btn = h("button", { class: c.relFilter === opt.key ? "active" : "", title: opt.label }, [opt.char]);
      btn.addEventListener("click", () => { c.relFilter = opt.key; renderLists(); relToggle.querySelectorAll("button").forEach((b) => b.classList.remove("active")); btn.classList.add("active"); });
      relToggle.appendChild(btn);
    });
    filterBar.appendChild(relToggle);

    // [수정] 검색을 우측으로 - GameList 필터바와 같은 순서(관계 필터 다음, 새로고침/
    // 줌 바로 앞)로 옮긴다. margin-left:auto로 여기부터 우측 정렬이 시작된다.
    const searchBox = h("div", { class: "searchbox compare-search-box" });
    searchBox.appendChild(icon("search", 12));
    const searchInput = h("input", { placeholder: "파일명 검색...", value: c.search });
    searchInput.addEventListener("input", (e) => { c.search = e.target.value; renderLists(); });
    searchBox.appendChild(searchInput);
    filterBar.appendChild(searchBox);

    // [신규] GameList와 동일한 새로고침/줌 버튼 - 새로고침은 compare 행을 다시 조회.
    const refreshBtn = h("button", { class: "btn", title: "두 소스를 다시 비교" }, [icon("refresh", 13), h("span", {}, ["새로고침"])]);
    refreshBtn.addEventListener("click", () => { c.loaded = false; loadCompareRows(); });
    filterBar.appendChild(refreshBtn);

    const fontScaleBtn = h("button", { class: "btn", title: "Shift + 마우스 휠로 글자 크기 조절" }, [
      h("span", { class: "font-scale-label" }, [`A ${Math.round(S.fontScale * 100)}%`]),
    ]);
    fontScaleBtn.addEventListener("click", resetFontScale);
    filterBar.appendChild(fontScaleBtn);

    root.appendChild(filterBar);

    function listHeader() {
      return h("div", { class: "compare-list-header" }, [
        h("div", { class: "compare-header-cell" }, ["FILE"]),
        h("div", { class: "compare-header-cell" }, ["TITLE"]),
        h("div", { class: "compare-header-cell" }, ["DESCRIPTION"]),
        h("div", { class: "compare-header-cell" }, ["SHA256"]),
      ]);
    }

    const lists = h("div", { class: "compare-lists" });
    const leftPanel = h("div", { class: "compare-list-panel" });
    const rightPanel = h("div", { class: "compare-list-panel" });
    const leftList = h("div", { class: "compare-list" });
    const rightList = h("div", { class: "compare-list" });
    // [신규] 카드 보기에선 FILE/TITLE/DESCRIPTION 컬럼 헤더가 의미 없으니 숨긴다
    // (renderLists()에서 viewMode에 맞춰 토글).
    const leftHeader = listHeader();
    const rightHeader = listHeader();
    leftPanel.appendChild(h("div", { class: "compare-list-title" }, [
      h("span", { class: "truncate" }, [sources.find((s) => s.id === c.sourceA)?.label || "왼쪽"]),
      sourceTitleDropdown("left", c.sourceA),
    ]));
    leftPanel.appendChild(leftHeader);
    leftPanel.appendChild(leftList);
    rightPanel.appendChild(h("div", { class: "compare-list-title" }, [
      h("span", { class: "truncate" }, [sources.find((s) => s.id === c.sourceB)?.label || "오른쪽"]),
      sourceTitleDropdown("right", c.sourceB),
    ]));
    rightPanel.appendChild(rightHeader);
    rightPanel.appendChild(rightList);

    // [수정] centerCol을 왼쪽/오른쪽 패널과 똑같이 3단으로 나눈다: 제목 높이엔
    // swap 버튼(가운데, "제목-제목" 사이라는 위치 자체가 좌우 전환이라는 의미를
    // 전달), 헤더 높이엔 다중 선택 일괄 복사 버튼(>/<), 그 아래는 행별 관계 열.
    const centerCol = h("div", { class: "compare-center-col" });
    const swapRow = h("div", { class: "compare-center-actions" });
    const swapBtn = h("button", { class: "icon-btn", title: "좌우 전환" }, [icon("refresh", 13)]);
    swapBtn.addEventListener("click", () => { const t = c.sourceA; c.sourceA = c.sourceB; c.sourceB = t; c.loaded = false; clearCompareSelection(); loadCompareRows(); });
    swapRow.appendChild(swapBtn);

    // [신규] "제목 < >  제목"보다 "제목 >  < 제목"이 더 직관적이다 - 왼쪽 버튼(>)이
    // 오른쪽으로, 오른쪽 버튼(<)이 왼쪽으로 향해서 각자 자기 옆 목록에서 반대쪽으로
    // 복사한다는 게 화살표 위치만 봐도 바로 읽힌다. 다중 선택된 행이 있을 때만
    // 활성화되고, 누르면 선택된 행 전체를 한꺼번에 복사한다(compareCopyRows).
    const bulkRow = h("div", { class: "compare-center-header compare-center-bulk-actions" });
    const toRightBtn = h("button", { class: "icon-btn", title: "왼쪽에서 선택한 항목을 오른쪽으로 복사" }, [icon("chevronRight", 13)]);
    const toLeftBtn = h("button", { class: "icon-btn", title: "오른쪽에서 선택한 항목을 왼쪽으로 복사" }, [icon("chevronLeft", 13)]);
    toRightBtn.addEventListener("click", () => copySelectedCompareRows("toRight"));
    toLeftBtn.addEventListener("click", () => copySelectedCompareRows("toLeft"));
    bulkRow.appendChild(toRightBtn);
    bulkRow.appendChild(toLeftBtn);

    const centerList = h("div", { class: "compare-center-list" });
    centerCol.appendChild(swapRow);
    centerCol.appendChild(bulkRow);
    centerCol.appendChild(centerList);

    lists.appendChild(leftPanel);
    lists.appendChild(centerCol);
    lists.appendChild(rightPanel);
    root.appendChild(lists);

    // [버그 수정] 왼쪽/오른쪽 스크롤이 서로 독립적이라 나란히 놓고 봐도 스크롤하면
    // 바로 어긋났다. 한쪽을 스크롤하면 다른 쪽(+가운데 심볼 열)도 같은 위치로
    // 맞춘다. scrollTop을 코드로 바꾸는 것도 scroll 이벤트를 다시 발생시키므로,
    // 재귀적으로 서로를 무한히 동기화하지 않도록 syncingScroll 플래그로 한쪽
    // 방향만 적용한다.
    let syncingScroll = false;
    function syncScroll(from, targets) {
      if (syncingScroll) return;
      syncingScroll = true;
      targets.forEach((to) => { to.scrollTop = from.scrollTop; });
      syncingScroll = false;
    }
    leftList.addEventListener("scroll", () => syncScroll(leftList, [rightList, centerList]));
    rightList.addEventListener("scroll", () => syncScroll(rightList, [leftList, centerList]));

    function listRow(entry, diff, matched, selected, side, orderedEntries) {
      const row = h("div", {
        class: "compare-list-row" + (selected ? " selected" : "") + (diff ? " diff" : "") + (matched ? " matched" : ""),
      });
      row.addEventListener("click", (e) => handleCompareRowClick(e, entry, side, orderedEntries));
      // [신규] ROM 실물이 없는(metadata-only) 항목은 파일명을 빨간색으로 표시한다.
      row.appendChild(h("span", { class: "compare-row-file truncate" + (entry.romMatched === false ? " missing-rom" : ""), title: entry.romMatched === false ? "ROM 실물 파일이 없습니다 (metadata만 있음)" : "" }, [entry.filename + (diff ? " [d]" : "")]));
      row.appendChild(h("span", { class: "compare-row-title truncate" }, [entry.title || "—"]));
      row.appendChild(h("span", { class: "compare-row-desc truncate" }, [entry.desc || ""]));
      // [Compare SHA256 컬럼] 표시는 앞 10자만 - 실제 전체 64자 값은 entry.sha256에
      // 그대로 있고, 여기서는 화면용 문자열만 자른다(동일성 비교에 이 값을 쓰면 안 됨).
      row.appendChild(h("span", { class: "compare-row-sha256 truncate", title: entry.sha256 || "" },
        [entry.sha256 ? entry.sha256.slice(0, 10) : "-"]));
      return row;
    }
    // [신규] 카드 보기 - 텍스트 3열 대신 커버 썸네일 + 파일명만 나란히. GameList의
    // preview-grid처럼 IntersectionObserver로 실제 스크롤해서 보일 때만 낱개
    // 로딩한다(한 행에 좌우 둘 다 있으면 최대 두 배 호출이라 더 중요함).
    const coverObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        coverObserver.unobserve(entry.target);
        const box = entry.target;
        const info = box._coverInfo;
        if (!info) return;
        const promise = info.sourceId === "masterdb" ? api.getCoverThumbnail(info.romKey) : api.getLocalCoverThumbnail(info.sourceId, info.romKey);
        promise.then((r) => {
          if (r.ok && r.data) { clear(box); box.appendChild(h("img", { src: r.data, alt: "" })); }
        });
      });
    }, { root: null, rootMargin: "200px" });

    function cardRow(entry, diff, matched, selected, side, orderedEntries, sourceId) {
      const row = h("div", {
        class: "compare-list-row compare-card-row" + (selected ? " selected" : "") + (diff ? " diff" : "") + (matched ? " matched" : ""),
      });
      row.addEventListener("click", (e) => handleCompareRowClick(e, entry, side, orderedEntries));
      const coverBox = h("div", { class: "compare-card-cover" }, [icon("image", 14)]);
      coverBox._coverInfo = { romKey: compareRowKey(entry), sourceId };
      coverObserver.observe(coverBox);
      row.appendChild(coverBox);
      row.appendChild(h("span", { class: "compare-row-file truncate" + (entry.romMatched === false ? " missing-rom" : ""), title: entry.romMatched === false ? "ROM 실물 파일이 없습니다 (metadata만 있음)" : "" }, [entry.filename]));
      return row;
    }
    // [버그 수정] 왼쪽에만 있거나 오른쪽에만 있는 항목이 있으면, 반대쪽 자리를
    // 비워두는 자리표시 행을 넣어 두 목록의 줄 수/순서를 항상 똑같이 맞춘다 -
    // 그래야 같은 파일이 왼쪽/오른쪽 목록에서 항상 같은 줄에 나란히 보인다.
    function placeholderRow() {
      const row = h("div", { class: "compare-list-row compare-row-placeholder" });
      row.appendChild(h("span", { class: "compare-row-file" }, ["—"]));
      return row;
    }

    // [수정] 행 하나의 좌/우 존재 여부로 관계 아이콘/색을 정한다: 둘 다 있고 내용도
    // 같으면 흰색 체크(=), 둘 다 있는데 metadata가 다르면 파란색(≠), 한쪽에만
    // 있으면 빨간색 화살표 - 이 화살표는 버튼이라 직접 눌러서 그 행 하나만 바로
    // 복사할 수 있고(누르면 반대쪽에도 생겨서 다음 렌더에는 흰색 =로 바뀐다).
    // [수정] 아이콘(체크/xCircle/화살표 아이콘) 대신, 필터바의 [*≠=] 버튼과 똑같은
    // 문자를 그대로 쓴다 - "v 아이콘이 왜 나오지?" 하고 헷갈렸던 것도 결국 필터
    // 버튼은 문자([*≠=])인데 행 쪽은 아이콘이라 서로 다른 언어를 쓰고 있었기 때문.
    function centerCell(r) {
      if (r.left && r.right) {
        if (!r.diff) {
          return h("div", { class: "compare-center-cell eq", title: "완전히 동일함" }, ["="]);
        }
        // [수정] ≠는 그동안 정보 표시일 뿐 아무 동작도 없었다 - ≠ 자체는 클릭하지
        // 않고, hover하면 양옆에 작은 </> 버튼이 나타나 그 방향으로 metadata를
        // 바로 복사할 수 있게 한다(기본 상태에선 ≠만 보여 시각적으로 조용함).
        const cell = h("div", { class: "compare-center-cell diff", title: "메타데이터가 다름" });
        const toLeftBtn = h("button", { class: "compare-center-diff-btn", title: "오른쪽 metadata를 왼쪽으로 복사" }, [icon("chevronLeft", 11)]);
        const symbol = h("span", { class: "compare-center-diff-symbol" }, ["≠"]);
        const toRightBtn = h("button", { class: "compare-center-diff-btn", title: "왼쪽 metadata를 오른쪽으로 복사" }, [icon("chevronRight", 11)]);
        toLeftBtn.addEventListener("click", (e) => { e.stopPropagation(); copySingleCompareRow(r.right, "toLeft"); });
        toRightBtn.addEventListener("click", (e) => { e.stopPropagation(); copySingleCompareRow(r.left, "toRight"); });
        cell.appendChild(toLeftBtn); cell.appendChild(symbol); cell.appendChild(toRightBtn);
        return cell;
      }
      const direction = r.left ? "toRight" : "toLeft";
      const entry = r.left || r.right;
      const cell = h("div", {
        class: "compare-center-cell arrow", role: "button", tabIndex: 0,
        title: r.left ? "오른쪽으로 복사" : "왼쪽으로 복사",
      }, [r.left ? "→" : "←"]);
      cell.addEventListener("click", () => copySingleCompareRow(entry, direction));
      cell.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copySingleCompareRow(entry, direction); } });
      return cell;
    }

    function renderLists() {
      clear(leftList); clear(rightList); clear(centerList);
      lists.classList.toggle("card-mode", c.viewMode === "card");
      leftHeader.classList.toggle("hidden", c.viewMode === "card");
      rightHeader.classList.toggle("hidden", c.viewMode === "card");

      if (c.loading) {
        leftList.appendChild(h("div", { class: "compare-empty" }, ["비교 중..."]));
        rightList.appendChild(h("div", { class: "compare-empty" }, ["비교 중..."]));
        toRightBtn.disabled = true; toLeftBtn.disabled = true;
        return;
      }
      if (!c.sourceA || !c.sourceB || c.sourceA === c.sourceB) {
        const msg = !c.sourceA || !c.sourceB ? "비교할 두 소스를 선택하세요." : "서로 다른 소스를 선택하세요.";
        leftList.appendChild(h("div", { class: "compare-empty" }, [msg]));
        rightList.appendChild(h("div", { class: "compare-empty" }, [msg]));
        toRightBtn.disabled = true; toLeftBtn.disabled = true;
        return;
      }

      const rows = getFilteredCompareRows();

      if (!rows.length) {
        leftList.appendChild(h("div", { class: "compare-empty" }, ["표시할 항목이 없습니다."]));
        rightList.appendChild(h("div", { class: "compare-empty" }, ["표시할 항목이 없습니다."]));
        toRightBtn.disabled = true; toLeftBtn.disabled = true;
        return;
      }

      // Shift 범위 선택 계산에 쓸, 현재 화면에 실제로 보이는 항목 순서(자리표시 제외).
      const leftEntries = rows.filter((r) => r.left).map((r) => r.left);
      const rightEntries = rows.filter((r) => r.right).map((r) => r.right);

      const rowFn = c.viewMode === "card" ? cardRow : listRow;
      rows.forEach((r) => {
        if (r.left) {
          const isSel = c.selectedLeftKeys.has(compareRowKey(r.left));
          leftList.appendChild(rowFn(r.left, r.diff, r.matched, isSel, "left", leftEntries, c.sourceA));
        } else {
          leftList.appendChild(placeholderRow());
        }
        if (r.right) {
          const isSel = c.selectedRightKeys.has(compareRowKey(r.right));
          rightList.appendChild(rowFn(r.right, r.diff, r.matched, isSel, "right", rightEntries, c.sourceB));
        } else {
          rightList.appendChild(placeholderRow());
        }
        centerList.appendChild(centerCell(r));
      });

      toRightBtn.disabled = c.selectedLeftKeys.size === 0;
      toLeftBtn.disabled = c.selectedRightKeys.size === 0;
      toRightBtn.title = c.selectedLeftKeys.size ? `선택한 ${c.selectedLeftKeys.size}개를 오른쪽으로 복사` : "왼쪽에서 선택한 항목을 오른쪽으로 복사";
      toLeftBtn.title = c.selectedRightKeys.size ? `선택한 ${c.selectedRightKeys.size}개를 왼쪽으로 복사` : "오른쪽에서 선택한 항목을 왼쪽으로 복사";
    }

    renderLists();
    if (c.sourceA && c.sourceB && c.sourceA !== c.sourceB && !c.loaded && !c.loading) {
      loadCompareRows();
    }
  }

  // ------------------------------------------------------------------
  // 테마
  // ------------------------------------------------------------------
  function applyTheme(mode) {
    let effective = mode;
    if (mode === "system") {
      effective = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    document.documentElement.setAttribute("data-theme", effective === "light" ? "light" : "dark");
  }

  // ------------------------------------------------------------------
  // 화면 전환 렌더링
  // ------------------------------------------------------------------
  function renderAll() {
    renderSidebar();
    const isListView = S.view === "masterdb" || S.view.startsWith("local-");
    document.getElementById("context-bar").classList.toggle("hidden", !isListView);
    document.getElementById("list-area").classList.toggle("hidden", !isListView);
    document.getElementById("filter-bar").classList.toggle("hidden", !isListView);
    document.getElementById("list-body").classList.toggle("hidden", !isListView);
    document.getElementById("detail-panel").classList.toggle("hidden", !isListView);
    document.getElementById("dashboard-view").classList.toggle("hidden", S.view !== "dashboard");
    document.getElementById("settings-view").classList.toggle("hidden", S.view !== "settings");
    document.getElementById("compare-view").classList.toggle("hidden", S.view !== "compare");

    if (isListView) { renderContextBar(); renderFilterBar(); renderListArea(); renderDetailPanel(); }
    if (S.view === "dashboard") renderDashboard();
    if (S.view === "settings") renderSettings();
    if (S.view === "compare") renderCompare();
  }

  // ------------------------------------------------------------------
  // 초기화
  // ------------------------------------------------------------------
  document.addEventListener("keydown", (e) => {
    if (e.key === "F5" && (S.view === "masterdb" || S.view.startsWith("local-"))) { e.preventDefault(); handleRefresh(); }
    if ((e.ctrlKey || e.metaKey) && e.key === "s" && S.panelOpen && detailState && !detailState.readOnly) { e.preventDefault(); handleSaveDetail(); }
    if (e.key === "Escape") {
      if (S.verDiffState) { S.verDiffState = null; renderModals(); }
      else if (S.confirmState) closeConfirm();
      else if (S.addLocalOpen) closeAddLocal();
      // [신규] auto-hide가 없어졌으니 열린 Metadata Panel을 Esc로 직접 닫을 수 있어야 한다
      // (예전엔 일정 시간 뒤 저절로 닫혔지만, 이제는 명시적으로 닫기 전까지 계속 열려 있음).
      // [버그 수정] S.panelOpen은 화면과 무관한 전역 플래그라 기본값 true가 그대로
      // 남아있으면 Compare에서 Esc를 눌러도 항상 이 분기로 먼저 빠져서 아래 Compare
      // 전용 처리(선택 해제/종료)가 전혀 실행되지 않았다 - list 화면에서만 적용한다.
      else if (S.panelOpen && S.view !== "compare") closeDetail();
      else if (S.view === "compare" && openBodyMenuCloser) openBodyMenuCloser();
      else if (S.view === "compare" && (S.compare.selectedLeftKeys.size || S.compare.selectedRightKeys.size)) {
        // 선택된 게 있으면 첫 Esc는 선택 해제만 한다 - 곧바로 화면을 나가버리면
        // "선택만 취소하려던" 흔한 경우에 너무 공격적이다. 선택이 없는 상태에서
        // 한 번 더 누르면(또는 처음부터 선택이 없었으면) 비교를 종료한다.
        S.compare.selectedLeftKeys.clear(); S.compare.selectedRightKeys.clear();
        S.compare.leftAnchor = null; S.compare.rightAnchor = null;
        renderCompare();
      }
      else if (S.view === "compare") exitCompare();
    }
    // [수정] Compare 화면에서 Ctrl+A - 예전엔 왼쪽/오른쪽을 항상 동시에 전체
    // 선택했는데, 그러면 한쪽만 복사할 생각으로 눌러도 반대쪽까지 통째로 선택돼
    // 직관적이지 않다는 지적을 반영해 "마지막으로 다루던(포커스된) 쪽" 하나만
    // 전체 선택하도록 바꾼다. 아직 아무 쪽도 다룬 적 없으면(방금 Compare에
    // 들어온 직후 등) 왼쪽을 기본으로 삼는다. 클릭 즉시 renderCompare()가 행
    // DOM을 다시 그려 실제 DOM 포커스는 남지 않으므로, handleCompareRowClick이
    // 갱신해두는 S.compare.lastActiveSide로 판단한다.
    if (S.view === "compare" && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
      const tagNow = (document.activeElement && document.activeElement.tagName) || "";
      if (tagNow !== "INPUT" && tagNow !== "TEXTAREA" && tagNow !== "SELECT") {
        e.preventDefault();
        const rows = getFilteredCompareRows();
        const side = S.compare.lastActiveSide === "right" ? "right" : "left";
        if (side === "right") {
          S.compare.selectedRightKeys = new Set(rows.filter((r) => r.right).map((r) => compareRowKey(r.right)));
        } else {
          S.compare.selectedLeftKeys = new Set(rows.filter((r) => r.left).map((r) => compareRowKey(r.left)));
        }
        renderCompare();
      }
    }
    // [BUG FIX] 방향키/PageUp·Down/Home/End가 안 먹히던 원인 - #list-scroll에 tabIndex는
    // 줬지만 실제로 .focus()를 호출하는 코드가 없어서 포커스가 그쪽에 간 적이 없었다.
    // 포커스에 의존하지 않는 전역 리스너로 옮긴다. 단, 입력창(input/textarea/select)에
    // 포커스가 있을 땐 그쪽 타이핑을 방해하면 안 되므로 건너뛴다.
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    const isTyping = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    const isListView = S.view === "masterdb" || S.view.startsWith("local-");
    if (!isTyping && isListView && (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "PageDown" || e.key === "PageUp" || e.key === "Home" || e.key === "End" || e.key === "Enter")) {
      const list = getSortedFilteredGames();
      handleListKeyDown(e, list);
    }
    // Ctrl+A selects every currently visible/filtered game. It intentionally does not
    // include games hidden by search/status/system filters.
    if (!isTyping && isListView && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
      e.preventDefault();
      const list = getSortedFilteredGames();
      S.multiSelect = new Set(list.map((g) => g.romKey));
      S.multiSelectAnchor = list.length ? list[0].romKey : null;
      renderListArea();
      return;
    }
    // MasterDB quick cleanup: Ctrl+C copies one game, Ctrl+V overwrites the selected target
    // with metadata + media from the copied game. This is intentionally single-selection only.
    if (!isTyping && isListView && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c" && S.view === "masterdb" && S.selectedGame && S.multiSelect.size === 0) {
      e.preventDefault(); clipboardRomKey = S.selectedGame; showToast("게임 metadata + media를 복사했습니다."); return;
    }
    if (!isTyping && isListView && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v" && S.view === "masterdb" && clipboardRomKey && S.selectedGame && clipboardRomKey !== S.selectedGame && S.multiSelect.size === 0) {
      e.preventDefault();
      showConfirm("Metadata + Media 덮어쓰기", "복사한 게임의 metadata와 media로 현재 게임을 덮어씁니다. 계속하시겠습니까?", true, async () => {
        closeConfirm();
        const r = await api.copyMasterdbGameData(clipboardRomKey, S.selectedGame);
        if (r.ok) { delete S.detailCache[`masterdb|${S.selectedGame}`]; await loadGamesForView(); renderListArea(); showToast("metadata + media 덮어쓰기 완료"); }
        else showToast(r.error, "error");
      });
      return;
    }
    // [단위 9][Space] 즐겨찾기 토글. 다중선택 시 "전부 아직 즐겨찾기가 아니면 전부 켜고,
    // 아니면(하나라도 이미 켜져 있으면) 전부 끈다" 방식의 일괄 토글.
    if (!isTyping && isListView && e.key === " " && S.view === "masterdb" && (S.multiSelect.size > 0 || S.selectedGame)) {
      e.preventDefault();
      const romKeys = S.multiSelect.size ? Array.from(S.multiSelect) : [S.selectedGame];
      const allFavorited = romKeys.every((k) => { const g = S.games.find((x) => x.romKey === k); return g && g.favorite; });
      const nextValue = !allFavorited;
      Promise.all(romKeys.map((k) => toggleGameFavorite(k, nextValue)));
      return;
    }
    // [F2] ArchiveDB에서 단일 선택된 ROM의 파일명 변경 (연결된 metadata/media 함께 이동).
    if (!isTyping && isListView && e.key === "F2" && S.view === "masterdb" && S.selectedGame && S.multiSelect.size === 0) {
      e.preventDefault();
      const g = getSortedFilteredGames().find((x) => x.romKey === S.selectedGame);
      if (g) openRename(g.romKey, g.file);
      return;
    }
    // [신규] Delete 키: 다중선택된 게임이 있으면 metadata+Rom을 함께 삭제
    if (!isTyping && isListView && e.key === "Delete" && (S.multiSelect.size > 0 || S.selectedGame)) {
      e.preventDefault();
      executeDelete();
    }
  });

  function initCustomTitlebar() { /* Native Windows title bar is used. */ }

  async function init() {
    diag("INIT_START", { bridge: typeof window.pywebview !== "undefined" && !!window.pywebview.api });
    const pathResult = await api.getDiagnosticLogPath().catch(() => null);
    if (pathResult && pathResult.ok) console.log("[RetroManager diagnostic log]", pathResult.data);
    const r = await api.getSettings();
    if (r.ok) {
      S.settings = r.data;
      applyTheme(r.data.theme);
      api._loggingEnabled = !!r.data.loggingEnabled;
      S.viewMode = r.data.defaultListView === "preview" ? "preview" : "list";
      if (r.data.startupPage === "dashboard") S.view = "dashboard";
    }
    const vr = await api.getVersion();
    if (vr.ok) S.version = vr.data;
    await refreshAll();
    diag("INIT_AFTER_REFRESH", { games: S.games.length, locals: S.locals.map((l) => ({ id: l.id, label: l.label })),
      masterdbConfigured: !!S.masterdb.configured, masterdbRomCount: S.masterdb.romCount || 0 });

    // 최초 실행/설정 초기화 상태에서는 반드시 MasterDB 경로 선택을 먼저 요청한다.
    // 기존에는 MasterDB 화면의 온보딩만 존재해서, 시작 시 native 폴더 선택창이 자동으로 뜨지 않았다.
    if (!S.masterdb.configured && RMApiIsNativeBridge()) {
      await handleSetupMasterdb();
    }
  }

  function RMApiIsNativeBridge() {
    return typeof window.pywebview !== "undefined" && !!window.pywebview.api;
  }

  // [BUG FIX] pywebview의 window.pywebview.api는 DOMContentLoaded보다 늦게 주입될 수 있다.
  // 이전엔 DOMContentLoaded 시점에 무조건 init()을 돌려서, 실제 브릿지가 아직 준비되기 전에
  // api-client.js가 목업 데이터로 폴백해버리는 경우가 있었다 (더미 Local, 가짜 MasterDB
  // 상태 등으로 보이던 문제의 근본 원인으로 추정). pywebviewready 이벤트를 기다리고,
  // 순수 브라우저(목업) 환경에서는 짧은 대기 후 폴백하도록 한다.
  let _appStarted = false;
  function startApp() {
    if (_appStarted) return;
    _appStarted = true;
    init();
  }
  window.addEventListener("pywebviewready", startApp);
  window.addEventListener("DOMContentLoaded", () => {
    if (typeof window.pywebview !== "undefined" && window.pywebview.api) { startApp(); return; }
    // pywebview 컨테이너 자체가 없으면(순수 브라우저 미리보기) 잠깐 기다렸다가 목업 모드로 시작
    setTimeout(() => { if (!_appStarted) startApp(); }, 400);
  });
})();
