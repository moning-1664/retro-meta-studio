/* ==========================================================================
   app.js — RetroMeta Studio

   화면 구성은 스펙 §72/§93을 따른다.
     상단   Collection 탭
     좌측   ALL / INTERNAL / EXTERNAL 시스템 트리
     중앙   Collection 헤더 + Gamelist(가상 스크롤)
     우측   Metadata / Media / ROM 상세 패널  ← 이전 프로젝트 구현을 그대로 유지
     하단   선택/용량/작업 바

   Gamelist는 전체 목록을 메모리에 올리지 않는다. 화면에 보이는 구간만 백엔드에
   요청하고, 정렬·필터·검색·페이징은 전부 SQL이 처리한다.
   ========================================================================== */

(function () {
  "use strict";

  // 줄 높이. 이전 프로젝트는 26px였다(34는 한 화면에 너무 적게 들어간다). 이제는
  // Settings > UI Density가 정한다 - CSS 토큰 --row-h를 applyAppearance()가 읽어 온다.
  // 가상 스크롤 계산이 모두 이 값을 쓰므로 CSS의 줄 높이와 반드시 같아야 한다.
  let ROW_HEIGHT = 26;

  // Gamelist 컬럼. 이전 프로젝트에서 실제로 쓰던 구성이다 - 제목이 아니라 **설명**이
  // 가장 넓다. 목록만 훑어도 어떤 게임인지 알 수 있어야 하기 때문이다.
  //
  // `key`가 없는 컬럼(No., ★)은 정렬도 폭 조절도 하지 않는다.
  const COLUMNS = [
    { id: "no", label: "No.", width: 23, fixed: true },
    { id: "file", label: "File", key: "filename", width: 190 },
    { id: "title", label: "Title", key: "title", width: 220 },
    { id: "desc", label: "Description", key: "desc", width: 390 },
    { id: "region", label: "Region", key: "region", width: 78 },
    { id: "rating", label: "Rating", key: "rating", width: 66 },
    { id: "fav", label: "★", key: "favorite", width: 30, fixed: true },
    { id: "genre", label: "Genre", key: "genre", width: 120 },
    { id: "status", label: "Status", width: 62, fixed: true },
  ];
  const COL_MIN_WIDTH = 50;
  const DEFAULT_COL_WIDTHS = Object.fromEntries(COLUMNS.map((c) => [c.id, c.width]));

  /** 컬럼 폭의 합. 목록이 이보다 좁은 화면에 놓이면 좌우로 스크롤해야 한다. */
  function totalColumnWidth() {
    return visibleColumns().reduce((sum, col) => sum + (S.colWidths[col.id] || col.width), 0) + 16;
  }

  function gridTemplate() {
    return visibleColumns().map((c) => `${S.colWidths[c.id] || c.width}px`).join(" ");
  }

  // ---- 컬럼 순서/표시 ------------------------------------------------------
  // **앱 전체 설정**(Settings > gamelist)이다 - Collection마다 다르게 둘 이유가 없고,
  // 폭은 화면 크기와 데이터에 따라 달라서 지금처럼 Collection별 ui_state에 남긴다.
  // No.는 항상 맨 앞이고 Title은 숨길 수 없다(무엇의 목록인지 알 수 없게 된다).
  const COLUMN_BY_ID = Object.fromEntries(COLUMNS.map((c) => [c.id, c]));
  const LOCKED_COLUMNS = new Set(["no", "title"]);

  function columnName(col) {
    return col.id === "fav" ? "★ Favorite" : col.label;
  }

  /** 저장된 순서/숨김을 현재 컬럼 정의에 맞춰 푼다. 모르는 id는 버리고, 새로 생긴
   * 컬럼은 뒤에 붙인다 - 설정이 옛 버전에서 왔어도 목록이 깨지지 않는다. */
  function columnLayout() {
    const conf = (S.settings && S.settings.gamelist) || {};
    const order = (Array.isArray(conf.order) ? conf.order : [])
      .filter((id, i, all) => COLUMN_BY_ID[id] && id !== "no" && all.indexOf(id) === i);
    COLUMNS.forEach((c) => { if (c.id !== "no" && !order.includes(c.id)) order.push(c.id); });
    const hidden = new Set((Array.isArray(conf.hidden) ? conf.hidden : [])
      .filter((id) => COLUMN_BY_ID[id] && !LOCKED_COLUMNS.has(id)));
    return { order: ["no", ...order], hidden };
  }

  function visibleColumns() {
    const { order, hidden } = columnLayout();
    return order.filter((id) => !hidden.has(id)).map((id) => COLUMN_BY_ID[id]);
  }

  function saveColumnLayout(order, hidden) {
    updateSettings("gamelist", { order: order.filter((id) => id !== "no"), hidden: [...hidden] });
  }

  function toggleColumn(id, visible) {
    if (LOCKED_COLUMNS.has(id)) return;
    const { order, hidden } = columnLayout();
    if (visible) hidden.delete(id); else hidden.add(id);
    saveColumnLayout(order, hidden);
  }

  /** id를 targetId 앞(after면 뒤)으로 옮긴다. No. 앞으로는 못 간다. */
  function moveColumn(id, targetId, after) {
    if (id === "no" || id === targetId || !COLUMN_BY_ID[id]) return;
    const { order, hidden } = columnLayout();
    const rest = order.filter((x) => x !== id);
    const at = targetId === "no" ? 1 : rest.indexOf(targetId) + (after ? 1 : 0);
    rest.splice(Math.max(1, at), 0, id);
    saveColumnLayout(rest, hidden);
  }

  function moveColumnBy(id, delta) {
    const { order } = columnLayout();
    const j = order.indexOf(id) + delta;
    if (id === "no" || j < 1 || j >= order.length) return;
    moveColumn(id, order[j], delta > 0);
  }

  function resetColumns() {
    updateSettings("gamelist", { order: [], hidden: [] });
  }

  /** 행 텍스트를 말줄임(...)으로 자르는 안쪽 span.
   *
   * `.lc`가 `display:flex`라서 `overflow`/`text-overflow`를 그 div에 바로 주면
   * 안 먹는다(flex 컨테이너 자신에는 text-overflow가 적용되지 않는다) - 그래서
   * 글자가 잘리지도, "..."도 안 붙은 채 옆 컬럼 위로 그대로 흘러넘쳤다(실사용
   * 피드백: "File/Title/Description 사이에 아무 제약이 없어서 글씨가 이어진
   * 것처럼 보인다"). 텍스트만 감싸는 안쪽 span에 그 속성을 주고, flex item
   * 기본값(min-width:auto)이 줄어드는 것을 막지 않도록 min-width:0도 준다. */
  function truncSpan(text) {
    return h("span", { class: "lc-text" }, [text]);
  }
  const PAGE_SIZE = 200;
  const OVERSCAN = 8;
  const MAX_TABS = 10;

  // ------------------------------------------------------------------
  // DOM 헬퍼
  // ------------------------------------------------------------------
  function h(tag, props, children) {
    const el = document.createElement(tag);
    if (props) {
      Object.entries(props).forEach(([k, v]) => {
        if (v === undefined || v === null || v === false) return;
        if (k === "class") el.className = v;
        else if (k === "html") el.innerHTML = v;
        else if (k === "style") Object.assign(el.style, v);
        else if (k === "dataset") Object.entries(v).forEach(([dk, dv]) => (el.dataset[dk] = dv));
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
        else el.setAttribute(k, v === true ? "" : v);
      });
    }
    (children || []).forEach((c) => {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return el;
  }
  const clear = (el) => { while (el && el.firstChild) el.removeChild(el.firstChild); };
  const $ = (id) => document.getElementById(id);
  const icon = (name, size) => h("span", { class: "ic", html: window.RMIcons.svg(name, size || 13) });

  function systemIcon(name, size) {
    const key = String(name || "").toLowerCase();
    if (window.RMSystemIcons && window.RMSystemIcons.has(key)) {
      return h("span", { class: "sys-ic", html: window.RMSystemIcons.svg(key, size || 14) });
    }
    return icon("cartridge", size || 13);
  }

  function formatBytes(n) {
    if (!n) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = Number(n), i = 0;
    while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
    return `${value >= 100 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
  }
  const formatCount = (n) => Number(n || 0).toLocaleString();

  // ------------------------------------------------------------------
  // 상태
  // ------------------------------------------------------------------
  // ------------------------------------------------------------------
  // 앱 전역 설정 (Settings 화면, settings.js)
  // ------------------------------------------------------------------
  const DEFAULT_SETTINGS = {
    appearance: { theme: "stitch", density: "compact", scale: 100, previewDefault: true },
    navigation: { hideEmptySystems: false },
    gamelist: { order: [], hidden: [] },
    collections: { order: [] },
    transfer: { includeRom: true, includeMedia: true, conflict: "ask",
                unmatchedRomMode: "skip", unmatchedRomMetadata: true, unmatchedRomMedia: true, unmatchedRomVideo: true },
  };
  const APPEARANCE_CACHE_KEY = "rms.appearance";

  function mergeSettings(stored) {
    const merged = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
    Object.entries(stored || {}).forEach(([section, value]) => {
      merged[section] = (value && typeof value === "object" && !Array.isArray(value))
        ? { ...(merged[section] || {}), ...value } : value;
    });
    return merged;
  }

  /** 테마·밀도·크기를 <html>에 반영한다. 줄 높이가 바뀌었으면 true.
   *
   * 백엔드 설정이 오기 전에도 마지막 값으로 먼저 칠하려고 localStorage에 사본을 둔다 -
   * 사본은 첫 화면 깜빡임을 줄이는 용도일 뿐이고, 설정의 주인은 registry다. */
  function applyAppearance(appearance) {
    const a = { ...DEFAULT_SETTINGS.appearance, ...(appearance || {}) };
    const html = document.documentElement;
    html.dataset.theme = a.theme;
    html.dataset.density = a.density;
    html.style.setProperty("--font-scale", String(a.scale / 100));
    try { localStorage.setItem(APPEARANCE_CACHE_KEY, JSON.stringify(a)); } catch (_) { /* 저장소를 못 쓰는 환경 */ }
    const rowH = parseFloat(getComputedStyle(html).getPropertyValue("--row-h")) || 26;
    if (rowH === ROW_HEIGHT) return false;
    ROW_HEIGHT = rowH;
    return true;
  }

  // 첫 화면부터 마지막 테마로 그린다 - 백엔드 응답을 기다리면 기본 테마가 잠깐 보인다.
  try { applyAppearance(JSON.parse(localStorage.getItem(APPEARANCE_CACHE_KEY) || "null")); } catch (_) { /* 사본 없음 */ }

  const S = {
    settings: mergeSettings(null),
    // 중앙 영역: "list"(헤더+목록+Detail) 또는 "dashboard"(Navigator의 Dashboard).
    view: "list",
    collections: [],
    tabs: [],            // 열려 있는 Collection id (최대 10, 스펙 §2.2)
    activeId: null,
    detail: {},          // collectionId -> collection_detail 응답
    scope: {},           // collectionId -> {kind:"all"|"storage"|"system", id}
    headerExpanded: false,
    search: "",
    order: "title",
    descending: false,
    favoritesOnly: false,
    viewMode: "list",          // "list" | "card"
    statusFilter: "all",       // all | metadata | media | missing
    // 컬럼 폭은 사용자가 맞춰 놓는 것이라 Collection별로 기억한다(`ui_state`).
    colWidths: { ...DEFAULT_COL_WIDTHS },
    // Shift+Click 범위 선택의 기준점. 마지막으로 "그냥 누른" 행이다.
    selectAnchor: null,
    previewOn: true,
    // 이미 받아 온 카드 표지. 같은 카드를 다시 그릴 때 브릿지를 다시 거치지 않는다.
    coverCache: new Map(), // `${collectionId}|${romUid}` -> data URI
    // 가상 스크롤
    rowCache: new Map(), // index -> row
    loadedPages: new Set(),
    total: 0,
    queryToken: 0,
    selected: new Set(),
    // romUid -> Match 후보 개수. Gamelist 뱃지(§49)용이며, 화면에 들어온 행에
    // 대해서만 채운다 - 목록 전체를 미리 계산하면 스크롤이 느려진다.
    matchCounts: {},
    focused: null,       // 선택된 romUid (상세 패널 대상)
    detailState: null,
    // Plan은 세션 한정이다(결정 D2). 백엔드 메모리에만 있고 여기서는 요약만 들고 있다.
    plan: null,
    // Auto Plan이 켜져 있으면 복사/삭제/이동이 Plan으로 들어간다(스펙 §26).
    // 끄면 같은 동작이 확인 후 즉시 실행된다.
    autoPlan: true,
    // Compare Mode(§54-59). compare가 있으면 Gamelist가 비교 목록으로 바뀐다.
    // compareBase는 "기준으로 지정"만 해두고 아직 상대를 안 고른 중간 상태다.
    // 이 Collection의 Frontend가 제공하는 고유 기능(§22).
    adapterActions: [],
    compare: null,
    compareBase: null,
    compareFilter: "all",
  };

  //: Archive는 Collection이 아니지만 같은 Gamelist/Detail UI를 쓴다(스펙 §43).
  //  별도 화면을 만들지 않고 특수한 탭 id 하나로 취급한다.
  const ARCHIVE_ID = "archive";
  const isArchive = () => S.activeId === ARCHIVE_ID;

  const MEDIA_LABEL = {
    "3dboxes": "3DBoxes", backcovers: "BackCovers", covers: "Covers", fanart: "FanArt",
    manuals: "Manuals", marquees: "Marquees", miximages: "Miximages",
    physicalmedia: "PhysicalMedia", screenshots: "Screenshots",
    titlescreens: "TitleScreens", videos: "Videos", wheel: "Wheel",
  };

  const activeDetail = () => S.detail[S.activeId] || null;
  const activeScope = () => S.scope[S.activeId] || { kind: "all" };

  function currentQuery() {
    const scope = activeScope();
    const query = {
      search: S.search, order: S.order, descending: S.descending,
      favoritesOnly: !!S.favoritesOnly,
    };
    if (scope.kind === "system") query.systems = [scope.id];
    else if (scope.kind === "storage") query.storageIds = [scope.id];
    return query;
  }

  // --------------------------------------------------------------------
  // 화면 상태 기억하기 (컬럼 폭 / 정렬)
  // --------------------------------------------------------------------
  // 사용자가 맞춰 놓은 것은 앱을 닫아도 남아야 한다. Collection마다 따로 기억한다 -
  // System 구성이 다르면 보고 싶은 폭도 다르다.
  async function loadUiState(collectionId) {
    S.colWidths = { ...DEFAULT_COL_WIDTHS };
    if (!collectionId || collectionId === ARCHIVE_ID) return;
    const r = await api.getUiState(collectionId);
    // Collection을 빠르게 A -> B -> A로 오가면 B의 응답이 늦게 도착해 다시 열어 둔
    // A의 상태를 덮어쓸 수 있다. 응답이 왔을 때 여전히 이 Collection을 보고 있을
    // 때만 반영한다 - selectTab/openTab이 요청 시작 시점에 S.activeId를 이미
    // 그 값으로 맞춰 두므로, 이후 활성 탭이 바뀌었다면 이 응답은 낡은 것이다.
    if (S.activeId !== collectionId) return;
    if (!r.ok || !r.data) return;
    if (r.data.colWidths) S.colWidths = { ...DEFAULT_COL_WIDTHS, ...r.data.colWidths };
    if (r.data.sort) { S.order = r.data.sort.key || S.order; S.descending = !!r.data.sort.desc; }
    // 한 번도 끄고 켠 적 없는 Collection은 Settings의 "Preview by default"를 따른다.
    S.previewOn = typeof r.data.previewOn === "boolean"
      ? r.data.previewOn : S.settings.appearance.previewDefault !== false;
    // 보기 방식도 기억한다. 이것이 빠져 있어서 Card로 보던 사용자가 앱을 다시 열면
    // 언제나 List로 시작했다 - "재시작하면 Card가 한참 뒤에 나온다"의 정체는 사실
    // "Card 상태가 저장되지 않았다"였다.
    if (r.data.viewMode === "card" || r.data.viewMode === "list") S.viewMode = r.data.viewMode;
  }

  let uiStateTimer = null;
  let pendingUiStateFlush = null;   // 아직 안 나간 저장 요청 - 종료 직전에 즉시 보낸다
  function saveUiState() {
    if (!S.activeId || S.activeId === ARCHIVE_ID) return;
    clearTimeout(uiStateTimer);   // 끄는 동안 매 픽셀마다 저장하지 않는다
    const id = S.activeId;
    const payload = {
      colWidths: { ...S.colWidths },
      sort: { key: S.order, desc: !!S.descending },
      previewOn: S.previewOn !== false,
      viewMode: S.viewMode,
    };
    pendingUiStateFlush = () => api.saveUiState(id, payload);
    uiStateTimer = setTimeout(() => {
      pendingUiStateFlush = null;
      api.saveUiState(id, payload);
    }, 300);
  }

  /** 종료 직전에 아직 안 나간 저장을 즉시 보낸다. 안 그러면 컬럼 폭을 조절한 직후
   * 창을 닫을 때 debounce 타이머가 실행되기 전에 앱이 종료되어 그 변경이 사라진다. */
  async function flushPendingUiState() {
    if (Object.keys(pendingSettings).length) {
      clearTimeout(settingsTimer);
      const settings = pendingSettings;
      pendingSettings = {};
      await api.saveAppSettings(settings);
    }
    if (!pendingUiStateFlush) return;
    clearTimeout(uiStateTimer);
    const send = pendingUiStateFlush;
    pendingUiStateFlush = null;
    await send();
  }

  async function loadAppSettings() {
    const r = await api.getAppSettings();
    S.settings = mergeSettings(r.ok ? r.data : null);
    // 줄 높이나 컬럼 배치가 기본값과 다르면 이미 그린 목록을 다시 맞춘다.
    applyAppearance(S.settings.appearance);
    refreshListGeometry();
  }

  let settingsTimer = null;
  let pendingSettings = {};
  /** Settings 값을 바꾼다. 화면에는 즉시 반영하고 저장은 모았다가 한 번에 보낸다 -
   * Ctrl+휠이나 슬라이더는 초당 수십 번 바뀐다. */
  function updateSettings(section, patch) {
    S.settings[section] = { ...(S.settings[section] || {}), ...patch };
    pendingSettings[section] = { ...(pendingSettings[section] || {}), ...patch };
    if (section === "appearance" && applyAppearance(S.settings.appearance)) refreshListGeometry();
    if (section === "navigation") renderNav();
    if (section === "gamelist") refreshListGeometry();
    clearTimeout(settingsTimer);
    settingsTimer = setTimeout(() => {
      const send = pendingSettings;
      pendingSettings = {};
      api.saveAppSettings(send);
    }, 300);
  }

  /** 줄 높이가 바뀌면 가상 스크롤의 전체 높이와 보이는 구간을 다시 계산한다. */
  function refreshListGeometry() {
    if (!S.activeId) return;
    renderListHead();
    renderListWindow();
  }

  function openSettings(sectionId) {
    window.RMSSettings.open({
      h, icon, section: sectionId,
      get: () => S.settings,
      update: updateSettings,
      reset: () => updateSettings("appearance", { ...DEFAULT_SETTINGS.appearance }),
      renderColumns: columnSettingsEditor,
    });
  }

  /** Settings > Metadata & Media > GameList Columns. 머리글 드래그/우클릭과 같은 값을 바꾼다. */
  function columnSettingsEditor() {
    const wrap = h("div", { class: "stg-columns" });
    const draw = () => {
      clear(wrap);
      const { order, hidden } = columnLayout();
      order.forEach((id, i) => {
        const col = COLUMN_BY_ID[id];
        const locked = LOCKED_COLUMNS.has(id);
        const check = h("input", { type: "checkbox", disabled: locked });
        check.checked = !hidden.has(id);
        check.addEventListener("change", () => { toggleColumn(id, check.checked); draw(); });
        const up = h("button", { class: "icon-btn col-up", title: "앞으로", disabled: id === "no" || i <= 1 },
          [icon("chevronUp", 11)]);
        up.addEventListener("click", () => { moveColumnBy(id, -1); draw(); });
        const down = h("button", { class: "icon-btn col-down", title: "뒤로",
          disabled: id === "no" || i === order.length - 1 }, [icon("chevronDown", 11)]);
        down.addEventListener("click", () => { moveColumnBy(id, 1); draw(); });
        wrap.appendChild(h("div", { class: "stg-column-row" + (hidden.has(id) ? " off" : ""), "data-column": id }, [
          h("label", { class: "stg-column-name" }, [check, h("span", {}, [columnName(col)])]),
          locked ? h("span", { class: "stg-column-note" }, [id === "no" ? "항상 맨 앞" : "항상 표시"]) : null,
          h("div", { class: "stg-column-move" }, [up, down]),
        ]));
      });
      const reset = h("button", { class: "btn compact stg-column-reset" }, ["기본값으로"]);
      reset.addEventListener("click", () => { resetColumns(); draw(); });
      wrap.appendChild(h("div", { class: "stg-column-actions" }, [
        h("span", { class: "stg-help" }, ["목록 머리글을 끌어 순서를 바꾸고, 우클릭으로 표시할 컬럼을 고를 수도 있습니다."]),
        reset,
      ]));
    };
    draw();
    return wrap;
  }

  // ------------------------------------------------------------------
  // 토스트 / 확인창
  // ------------------------------------------------------------------
  function showToast(message, type) {
    const el = $("toast");
    clear(el);
    el.className = "show " + (type || "info");
    el.appendChild(h("div", { class: "toast-msg" }, [message]));
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => { el.className = ""; }, 3200);
  }

  function closeModal() { clear($("modal-root")); }

  function showModal(title, bodyEl, actions) {
    const root = $("modal-root");
    clear(root);
    const card = h("div", { class: "modal-card" }, [
      h("div", { class: "modal-title" }, [title]),
      bodyEl,
      h("div", { class: "modal-actions" }, actions),
    ]);
    const overlay = h("div", { class: "modal-overlay" }, [card]);
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) closeModal(); });
    root.appendChild(overlay);
    return card;
  }

  /** Media 타일을 누르면 확대해 보여준다. showModal을 그대로 쓴다 - ESC와 바깥
   * 클릭으로 닫히는 동작을 새로 만들 필요가 없다(모달 공통 처리에 이미 있다).
   *
   * **큰 이미지를 다시 누르면 닫힌다.** 확대해서 본 다음에 하는 일은 닫는 것뿐이고,
   * 그때 손이 가 있는 곳은 그 이미지 위다. 버튼을 찾아 눈을 옮기게 할 이유가 없어서
   * 별도의 "닫기" 버튼은 두지 않는다(ESC와 바깥 클릭도 그대로 된다).
   */
  function openMediaLightbox(img, label) {
    if (!img || !img.src) return;
    const large = h("img", { src: img.src, alt: label, class: "lightbox-img" });
    large.addEventListener("click", closeModal);
    const body = h("div", { class: "modal-body lightbox-body" }, [large]);
    const card = showModal(label, body, []);
    card.classList.add("lightbox-card");
  }

  function showConfirm(title, message, danger, onConfirm) {
    const body = h("div", { class: "modal-body" }, [h("div", { class: "modal-text" }, [message])]);
    showModal(title, body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn " + (danger ? "danger" : "primary"),
        onClick: () => { closeModal(); onConfirm(); } }, ["확인"]),
    ]);
  }

  // ------------------------------------------------------------------
  // 작업 진행률
  // ------------------------------------------------------------------
  function showJobProgress(title, jobId) {
    const bar = $("job-progress");
    bar.classList.add("show");
    clear(bar);
    const titleRow = h("div", { class: "job-progress-title-row" }, [
      h("div", { class: "job-progress-title" }, [title]),
    ]);
    if (jobId) {
      const cancel = h("button", { class: "job-progress-cancel" }, ["취소"]);
      cancel.addEventListener("click", () => { cancel.disabled = true; api.cancelJob(jobId); });
      titleRow.appendChild(cancel);
    }
    bar.appendChild(titleRow);
    bar.appendChild(h("div", { class: "job-progress-row" }, [
      h("div", { class: "job-progress-bar" }, [
        h("div", { class: "job-progress-bar-fill", id: "job-progress-bar-fill", style: { width: "0%" } })]),
      h("div", { class: "job-progress-pct", id: "job-progress-pct" }, ["0%"]),
    ]));
    bar.appendChild(h("div", { class: "job-progress-label", id: "job-progress-label" }, ["시작 중..."]));
  }

  function updateJobProgress(current, total, label) {
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    const fill = $("job-progress-bar-fill"), pctEl = $("job-progress-pct"), labelEl = $("job-progress-label");
    if (fill) fill.style.width = pct + "%";
    if (pctEl) pctEl.textContent = pct + "%";
    if (labelEl) labelEl.textContent = label ? `${label} (${current}/${total})` : `${current}/${total}`;
  }

  const hideJobProgress = () => $("job-progress").classList.remove("show");

  function pollJob(jobId, title) {
    return new Promise((resolve) => {          // jobId는 단계가 넘어가며 바뀐다
      showJobProgress(title, jobId);
      const tick = async () => {
        const r = await api.jobProgress(jobId);
        if (!r.ok) { hideJobProgress(); resolve({ ok: false, error: r.error }); return; }
        const job = r.data;
        updateJobProgress(job.current, job.total, job.label);
        if (!job.done) { setTimeout(tick, 180); return; }
        // 여러 단계로 나뉜 작업은 단계마다 job이 새로 생긴다. 앞 단계가 끝났다고
        // 멈추면 뒤 단계가 아직 Cache를 쓰는 중에 목록을 그리게 된다 - 개수가
        // 실행할 때마다 달라진다. 후속 job이 있으면 끝까지 따라간다.
        const followUp = job.result && job.result.followUpJobId;
        if (followUp && !job.error) { jobId = followUp; setTimeout(tick, 60); return; }
        hideJobProgress();
        if (job.error) { resolve({ ok: false, error: job.error, cancelled: job.cancelled }); return; }
        resolve({ ok: true, data: job.result });
      };
      tick();
    });
  }

  // ------------------------------------------------------------------
  // TopBar (Archive/Collection 탭 + Window Controls, 레이아웃 재검토로 통합)
  // ------------------------------------------------------------------
  /** Window Controls만 그린다. App Title은 없앴다(레이아웃 재검토) -
   * Navigator 하단으로 옮기는 건 별도 작업이라 이번엔 그냥 없앤다. **창을
   * 끌 수 있는 자리는 여기가 아니라 `#topbar-drag`다**(정적 HTML,
   * index.html) - Archive/Collection 탭과 이 버튼들은 클릭 영역이라
   * 드래그 영역이 아니다.
   */
  function renderWindowControls() {
    const bar = $("window-controls");
    clear(bar);
    // Windows의 창 버튼과 같은 모양으로 - 대시, 네모, 곱하기.
    [["\u2013", "minimize", "최소화"],
     ["\u25a1", "maximize", "최대화"],
     ["\u00d7", "close", "닫기"]].forEach(([glyph, action, label]) => {
      bar.appendChild(h("button", {
        class: "win-btn" + (action === "close" ? " close" : ""), title: label,
        // 닫기 전에 아직 안 나간 UI 상태 저장(컬럼 폭 등)을 먼저 내보낸다 -
        // debounce 타이머가 돌기 전에 창이 닫히면 방금 바꾼 값이 사라진다.
        onClick: async () => {
          if (action === "close") await flushPendingUiState();
          api.windowControl(action);
        },
      }, [glyph]));
    });
  }

  /** Archive 고정 탭 + Collection 탭 + "+". **Archive가 맨 앞이다**(레이아웃
   * 재검토) - 예전엔 spacer로 오른쪽 끝으로 밀어 뒀지만, 이제 탭 오른쪽 빈
   * 공간은 창을 끌 수 있는 자리(`#topbar-drag`)라 탭을 거기로 밀어 넣을
   * spacer가 없다. click/contextmenu/close 동작은 그대로다. */
  function renderTabs() {
    const bar = $("tabs-bar");
    clear(bar);
    const archiveTab = h("div", { class: "ctab archive" + (isArchive() ? " active" : ""),
      title: "여러 Collection에서 수집한 Metadata 보관소" }, [
      icon("database", 13), h("span", { class: "ctab-name" }, ["Archive"]),
    ]);
    archiveTab.addEventListener("click", () => selectTab(ARCHIVE_ID));
    bar.appendChild(archiveTab);

    S.tabs.forEach((id) => {
      const collection = S.collections.find((c) => c.id === id);
      if (!collection) return;
      const tab = h("div", { class: "ctab" + (id === S.activeId ? " active" : "") });
      tab.appendChild(icon("gamepad", 13));
      tab.appendChild(h("span", { class: "ctab-name" }, [collection.name]));
      const close = h("button", { class: "ctab-close", title: "닫기" }, [icon("x", 9)]);
      close.addEventListener("click", (e) => { e.stopPropagation(); closeTab(id); });
      tab.appendChild(close);
      tab.addEventListener("click", () => selectTab(id));
      tab.addEventListener("contextmenu", (e) => { e.preventDefault(); openTabMenu(collection, e); });
      bindTabDrag(tab, id);
      bar.appendChild(tab);
    });
    const add = h("button", { class: "ctab-add", title: "Collection 추가" }, [icon("plus", 13)]);
    add.addEventListener("click", openAddCollection);
    bar.appendChild(add);
  }

  /** Collection 순서. 사용자가 탭을 끌어 정한 순서(Settings > collections.order)가 먼저고,
   * 거기 없는 Collection(새로 추가한 것)은 등록 순서대로 뒤에 붙는다. 닫았다 다시 연 탭도
   * 이 순서의 제자리로 돌아간다. */
  function collectionOrder() {
    const saved = (S.settings && S.settings.collections && S.settings.collections.order) || [];
    const ids = S.collections.map((c) => c.id);
    return [...saved.filter((id, i) => ids.includes(id) && saved.indexOf(id) === i),
            ...ids.filter((id) => !saved.includes(id))];
  }

  function sortTabsByCollectionOrder() {
    const order = collectionOrder();
    const rank = (id) => { const i = order.indexOf(id); return i < 0 ? order.length : i; };
    S.tabs.sort((a, b) => rank(a) - rank(b));
  }

  function moveTab(id, targetId, after) {
    if (id === targetId) return;
    const order = collectionOrder().filter((c) => c !== id);
    const at = order.indexOf(targetId);
    if (at < 0) return;
    order.splice(at + (after ? 1 : 0), 0, id);
    updateSettings("collections", { order });
    sortTabsByCollectionOrder();
    S.collections.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    renderTabs();
  }

  /** 탭을 끌어 순서를 바꾼다. Archive 탭은 늘 맨 앞이라 끌 수도, 그 앞에 놓을 수도 없다. */
  let draggingTab = null;
  function bindTabDrag(tab, id) {
    const clearMarks = () => tab.classList.remove("drop-before", "drop-after");
    tab.draggable = true;
    tab.dataset.collectionId = id;
    tab.addEventListener("dragstart", (e) => {
      draggingTab = id;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/x-rms-tab", id);
      tab.classList.add("dragging");
    });
    tab.addEventListener("dragend", () => {
      draggingTab = null;
      document.querySelectorAll("#tabs-bar .ctab").forEach((t) =>
        t.classList.remove("dragging", "drop-before", "drop-after"));
    });
    tab.addEventListener("dragover", (e) => {
      if (!draggingTab || draggingTab === id) return;
      e.preventDefault();
      const rect = tab.getBoundingClientRect();
      const after = e.clientX > rect.left + rect.width / 2;
      tab.classList.toggle("drop-after", after);
      tab.classList.toggle("drop-before", !after);
    });
    tab.addEventListener("dragleave", clearMarks);
    tab.addEventListener("drop", (e) => {
      if (!draggingTab) return;
      e.preventDefault();
      const after = tab.classList.contains("drop-after");
      clearMarks();
      const moving = draggingTab;
      draggingTab = null;
      moveTab(moving, id, after);
    });
  }

  function openTabMenu(collection, event) {
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [`${collection.name} (${collection.rootPath})`]),
    ]);
    const actions = [
      h("button", { class: "btn", onClick: () => { closeModal(); promptRename(collection); } }, ["이름 변경"]),
    ];
    actions.push(h("button", { class: "btn", onClick: () => {
      closeModal();
      openConvert(collection);
    } }, ["Convert"]));
    // Compare는 두 단계다(§54): 한 탭에서 기준을 정하고, 다른 탭에서 그 기준과 비교한다.
    if (S.compareBase && S.compareBase !== collection.id) {
      const baseName = (S.collections.find((c) => c.id === S.compareBase) || {}).name || "기준";
      actions.push(h("button", { class: "btn primary", onClick: () => {
        closeModal();
        runCompare(S.compareBase, collection.id);
      } }, [`${baseName}와 비교`]));
    } else {
      actions.push(h("button", { class: "btn", onClick: () => {
        closeModal();
        S.compareBase = collection.id;
        showToast("비교 기준으로 지정했습니다. 다른 Collection 탭을 우클릭해 비교를 시작하세요.");
      } }, ["Compare 기준으로 지정"]));
    }
    showModal("Collection", body, [
      ...actions,
      h("button", { class: "btn danger", onClick: () => {
        closeModal();
        showConfirm("Collection 제거", "등록 목록에서 제거합니다. 실제 파일은 삭제되지 않습니다.", true,
          async () => { await api.deleteCollection(collection.id); closeTab(collection.id); await loadCollections(); renderAll(); });
      } }, ["제거"]),
      h("button", { class: "btn primary", onClick: closeModal }, ["닫기"]),
    ]);
  }

  function promptRename(collection) {
    const input = h("input", { class: "field-input", value: collection.name });
    const body = h("div", { class: "modal-body" }, [h("div", { class: "field-label" }, ["이름"]), input]);
    showModal("이름 변경", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary", onClick: async () => {
        const name = input.value.trim();
        closeModal();
        if (!name) return;
        await api.renameCollection(collection.id, name);
        await loadCollections();
        renderAll();
      } }, ["저장"]),
    ]);
    setTimeout(() => input.focus(), 30);
  }

  async function selectTab(id) {
    if (S.activeId === id) return;
    if (id !== ARCHIVE_ID && !S.tabs.includes(id)) { await openTab(id); return; }
    S.activeId = id;
    S.view = "list";
    resetList();
    await ensureDetail(id);
    // 사용자가 맞춰 놓은 컬럼 폭과 정렬을 먼저 되살린 뒤에 그린다 - 나중에 불러오면
    // 기본값으로 한 번 그렸다가 다시 그려서 화면이 흔들린다.
    await loadUiState(id);
    renderAll();
    await reloadList();
    await refreshPlan();
  }

  async function closeTab(id) {
    // Collection을 닫아도 Cache와 실제 파일은 그대로 둔다(스펙 §2.2).
    await api.closeCollection(id);
    S.tabs = S.tabs.filter((t) => t !== id);
    delete S.detail[id];
    delete S.scope[id];
    if (S.activeId === id) {
      S.activeId = S.tabs[0] || null;
      resetList();
      if (S.activeId) await ensureDetail(S.activeId);
    }
    renderAll();
    if (S.activeId) await reloadList();
  }

  async function openTab(id) {
    if (S.tabs.includes(id)) { await selectTab(id); return; }
    if (S.tabs.length >= MAX_TABS) {
      showToast(`동시에 열 수 있는 Collection은 ${MAX_TABS}개까지입니다.`, "warning");
      return;
    }
    const r = await api.openCollection(id);
    if (!r.ok) { showToast(r.error, "error"); return; }
    S.detail[id] = r.data;
    S.tabs.push(id);
    sortTabsByCollectionOrder();
    S.activeId = id;
    // openTab은 ensureDetail을 거치지 않고 openCollection 응답을 그대로 쓴다 -
    // Frontend 고유 기능은 여기서 따로 불러와야 한다.
    await loadAdapterActions();
    resetList();
    await loadUiState(id);
    renderAll();
    await reloadList();
    await refreshPlan();
  }

  async function ensureDetail(id) {
    if (id === ARCHIVE_ID) {
      // Archive에는 Storage 개념이 없다. Collection 헤더와 같은 모양으로만 맞춘다.
      const [systems, rows] = await Promise.all([api.archiveSystems(), api.archiveRows({ limit: 1 })]);
      S.detail[ARCHIVE_ID] = {
        id: ARCHIVE_ID, name: "Archive", frontendLabel: "보관소",
        target: null, os: null, arch: null, rootPath: "", storages: [],
        systemCount: (systems.ok ? systems.data : []).length,
        totalGames: rows.ok ? rows.data.total : 0,
        archiveSystems: systems.ok ? systems.data : [],
      };
      return;
    }
    const r = await api.collectionDetail(id);
    if (r.ok) S.detail[id] = r.data;
    // Frontend마다 제공하는 고유 기능이 다르므로 탭을 바꿀 때마다 다시 묻는다.
    if (id === S.activeId) await loadAdapterActions();
  }

  // ------------------------------------------------------------------
  // Collection 추가
  // ------------------------------------------------------------------
  //: 어떤 Frontend가 ES-DE 스타일(메타데이터/미디어를 한 상위 폴더에 모아 두고
  //  ROM만 다른 곳에 둘 수 있는 구조)인지. 기본 흐름에서는 이 폴더 하나만 받는다 -
  //  ROM/Metadata/Media를 각각 물으면 그 셋이 서로 어떻게 다른지부터 설명해야 했다.
  const ES_STYLE_FRONTEND_IDS = new Set(["es-de"]);

  /** "+ Collection"의 유일한 진입점. 예전 목록을 먼저 보여주고 그 안에 다시 "Import"
   * 버튼이 있는 2단 구조였다 - 그 Import가 뭘 하는 건지 이름만 봐서는 알 수 없었다.
   * 지금은 누르면 바로 이 추가 화면이 뜨고, 이미 등록된 Collection은 아래 접힌
   * "History"에서만 볼 수 있다. */
  async function openAddCollection() {
    const frontendsR = await api.frontends();
    const frontends = frontendsR.ok ? frontendsR.data : [{ id: "es-de", label: "ES-DE" }];
    await loadCollections();

    const nameInput = h("input", { class: "field-input", placeholder: "예: Android ES-DE" });
    // **Metadata와 ROM은 서로 독립적인 두 경로다.**
    //
    // 예전에는 대표 폴더 한 칸만 받고 ROM은 "고급"에 숨겨 두었다. 그런데 ES-DE는 이
    // 둘을 떼어 놓는 것이 기본 사용 방식이고(안드로이드 외장 SD가 그 경우다),
    // 스크래핑을 한 번도 안 한 사용자는 ROM만 가지고 있다. 한 칸으로 뭉치면 어느
    // 쪽을 넣어야 하는지가 사용자마다 달라진다.
    //
    // **둘 다 선택 사항이다.** 유효하지 않은 것은 둘 다 비었을 때뿐이다.
    const pathInput = h("input", { class: "field-input", id: "add-metadata-path",
                                   placeholder: "폴더를 선택하세요 (선택)" });
    const romInput = h("input", { class: "field-input", id: "add-rom-path",
                                  placeholder: "폴더를 선택하세요 (선택)" });
    const targetSel = h("select", { class: "field-input" }, [
      h("option", { value: "" }, ["Unknown"]),
      h("option", { value: "windows" }, ["Windows"]),
      h("option", { value: "android" }, ["Android"]),
      h("option", { value: "linux" }, ["Linux"]),
    ]);
    const archSel = h("select", { class: "field-input" }, [
      h("option", { value: "" }, ["Unknown"]),
      h("option", { value: "x64" }, ["x64"]),
      h("option", { value: "arm64" }, ["ARM64"]),
      h("option", { value: "arm32" }, ["ARM32"]),
    ]);
    const frontendSel = h("select", { class: "field-input" },
      frontends.map((f) => h("option", { value: f.id }, [f.label])));

    const pathLabel = h("div", { class: "field-label" }, ["ROM 디렉토리"]);
    const romLabel = h("div", { class: "field-label" }, ["ROM 디렉토리"]);

    const browseInto = (input, title, alsoName) => h("button", { class: "btn", onClick: async () => {
      const r = await api.pickFolder(title);
      if (!r.ok || !r.data) return;
      input.value = r.data;
      if (alsoName && !nameInput.value.trim()) {
        nameInput.value = String(r.data).split(/[\\/]/).filter(Boolean).pop() || "";
      }
    } }, [icon("folderOpen", 12), h("span", {}, ["찾아보기"])]);

    const metaRow = h("div", { class: "field-row" },
                      [pathInput, browseInto(pathInput, "Metadata 폴더 선택", true)]);
    const romRow = h("div", { class: "field-row" },
                     [romInput, browseInto(romInput, "ROM 폴더 선택", true)]);

    // 긴 설명을 필드 아래 줄줄이 적지 않는다 - hover하면 뜨는 title 툴팁 하나로
    // 충분하다. 항상 보이는 문장이 아니라 필요할 때만 보이는 문장으로 정책을 맞춘다.
    function syncFrontend() {
      const isEs = ES_STYLE_FRONTEND_IDS.has(frontendSel.value);
      pathLabel.textContent = isEs ? "Metadata 디렉토리" : "ROM 디렉토리";
      pathLabel.title = isEs
        ? "ES-DE의 gamelists와 downloaded_media가 포함된 디렉토리입니다."
        : "ROM(과 메타데이터)이 들어 있는 디렉토리입니다.";
      pathInput.title = pathLabel.title;
      romLabel.title = "ROM이 System별 폴더로 들어 있는 디렉토리입니다.";
      romInput.title = romLabel.title;
      // ES 계열이 아니면 경로가 하나뿐이다 - 그 Frontend는 메타데이터를 ROM 옆에 둔다.
      romLabel.hidden = !isEs;
      romRow.hidden = !isEs;
    }
    frontendSel.addEventListener("change", syncFrontend);
    syncFrontend();

    const advancedBody = h("div", {}, [
      h("div", { class: "field-grid two" }, [
        h("div", {}, [h("div", { class: "field-label" }, ["Target"]), targetSel]),
        h("div", {}, [h("div", { class: "field-label" }, ["Architecture"]), archSel]),
      ]),
    ]);
    const advanced = h("details", { class: "add-collection-advanced" }, [
      h("summary", {}, ["고급"]),
      advancedBody,
    ]);

    // History는 기본적으로 접혀 있다 - 방금 연 화면이 다시 예전 목록으로 보이면
    // "+"를 누른 의미가 없다. 필요할 때만 펼쳐서 예전 Collection을 고른다.
    const historyList = h("div", { class: "picker-list" });
    S.collections.forEach((c) => {
      const opened = S.tabs.includes(c.id);
      const row = h("button", { class: "picker-row" + (opened ? " disabled" : "") });
      row.appendChild(icon("gamepad", 14));
      row.appendChild(h("div", { class: "picker-main" }, [
        h("div", { class: "picker-name" }, [c.name]),
        h("div", { class: "picker-sub" }, [`${c.frontendLabel} · ${c.rootPath}`]),
      ]));
      if (opened) row.appendChild(h("span", { class: "picker-badge" }, ["열림"]));
      row.addEventListener("click", () => { if (!opened) { closeModal(); openTab(c.id); } });
      historyList.appendChild(row);
    });
    if (!S.collections.length) {
      historyList.appendChild(h("div", { class: "empty-msg" }, ["등록된 Collection이 없습니다."]));
    }
    const history = h("details", { class: "add-collection-history" }, [
      h("summary", {}, [`History (${formatCount(S.collections.length)})`]),
      historyList,
    ]);

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "field-label" }, ["Frontend"]), frontendSel,
      pathLabel, metaRow,
      romLabel, romRow,
      h("div", { class: "field-label" }, ["이름"]), nameInput,
      advanced,
      history,
    ]);

    showModal("Collection 추가", body, [
      h("button", { class: "btn", onClick: closeModal }, ["Cancel"]),
      h("button", { class: "btn primary", id: "add-collection-submit", onClick: async () => {
        const metaPath = pathInput.value.trim();
        const romPath = romRow.hidden ? "" : romInput.value.trim();
        // 둘 다 선택 사항이다. Metadata만 있어도, ROM만 있어도 정상적인 Collection이다
        // - 스크래핑을 한 번도 안 한 컬렉션이 후자의 모습이다. 유효하지 않은 것은
        // 둘 다 비었을 때뿐이다.
        if (!metaPath && !romPath) {
          showToast("Metadata 디렉토리와 ROM 디렉토리 중 하나는 선택하세요.", "warning");
          return;
        }
        const name = nameInput.value.trim() ||
          String(metaPath || romPath).split(/[\\/]/).filter(Boolean).pop() || "Collection";
        closeModal();
        const r = await api.createCollection(name, frontendSel.value, metaPath || null,
                                             targetSel.value || null, archSel.value || null,
                                             romPath || null, "");
        if (!r.ok) { showToast(r.error, "error"); return; }
        await loadCollections();
        // 메타데이터가 없다는 이유로 여기서 gamelist 생성 여부를 묻지 않는다.
        //
        // ROM만 있는 Collection은 **그 자체로 정상**이다. 만들자마자 "메타데이터가
        // 없습니다"를 띄우면 사용자는 무언가 잘못한 것처럼 느끼고, 실제로 정상적인
        // ES-DE 폴더에서도 ROM 폴더를 따로 준 System 때문에 이 창이 잘못 떴다.
        // gamelist를 미리 만드는 것은 언제든 할 수 있는 선택이지, Collection을 여는
        // 조건이 아니다.
        await openTab(r.data.id);
        runScan(r.data.id);
      } }, ["Add"]),
    ]);
    setTimeout(() => pathInput.focus(), 30);
  }

  // ------------------------------------------------------------------
  // 좌측 내비게이션
  // ------------------------------------------------------------------
  /** Navigator 최상단 고정 영역 - App Title + Settings. GameList 상단
   * Chromium(#collection-header)의 .cheader와 세로 위치가 맞도록 상단에
   * 둔다(사용자 요청) - 예전엔 최하단에 있었다. */
  function navTop() {
    const top = h("div", { class: "nav-top" });
    top.appendChild(h("div", { class: "nav-app-title" }, [
      icon("database", 16),
      h("div", { class: "nav-app-title-text" }, [
        h("div", { class: "nav-app-title-name" }, ["RetroMeta Studio"]),
        h("div", { class: "nav-app-title-sub" }, ["Frontend Metadata Editor"]),
      ]),
    ]));
    const settings = h("button", { class: "icon-btn", title: "Settings" }, [icon("settings", 14)]);
    settings.addEventListener("click", () => openSettings());
    top.appendChild(settings);
    return top;
  }

  /** Navigator 최하단 고정 항목. 실제 기능은 아직 없다(레이아웃 재검토, TODO -
   * PENDING_DECISIONS.md) - 이전 프로젝트 기능을 가져올 진입점 자리만 잡아둔다.
   * App Title이 상단으로 옮겨간 자리에 대신 놓는다(사용자 요청). */
  function navDashboardRow() {
    const row = h("button", {
      class: "nav-dashboard" + (S.view === "dashboard" ? " active" : ""),
      title: S.view === "dashboard" ? "목록으로 돌아가기" : "Collection Dashboard",
    }, [icon("dashboard", 14), h("span", {}, ["Dashboard"])]);
    row.addEventListener("click", () => (S.view === "dashboard" ? showList() : showDashboard()));
    return row;
  }

  function renderNav() {
    const nav = $("nav");
    clear(nav);
    nav.appendChild(navTop());

    // System 제목과 목록만 스크롤 영역에 넣는다 - Dashboard/Add External/App
    // Title/Settings는 System이 아무리 늘어나도 화면에서 밀려나면 안 된다.
    const scroll = h("div", { class: "nav-scroll" });
    nav.appendChild(scroll);

    const detail = activeDetail();
    if (!detail) {
      scroll.appendChild(h("div", { class: "nav-empty" }, ["Collection을 열어주세요"]));
      nav.appendChild(navDashboardRow());
      return;
    }
    const eyebrow = h("div", { class: "nav-eyebrow" }, [h("span", { class: "nav-eyebrow-label" }, ["SYSTEMS"])]);
    scroll.appendChild(eyebrow);

    const scope = activeScope();
    if (isArchive()) {
      const all = navRow("All", detail.totalGames, scope.kind === "all", () => setScope({ kind: "all" }));
      all.classList.add("nav-all");
      all.insertBefore(icon("database", 13), all.firstChild);
      scroll.appendChild(all);
      (detail.archiveSystems || []).forEach((sys) => {
        const row = navRow(sys.system.toUpperCase(), sys.count,
          scope.kind === "system" && scope.id === sys.system,
          () => setScope({ kind: "system", id: sys.system }));
        row.classList.add("nav-system");
        row.insertBefore(systemIcon(sys.system, 14), row.firstChild);
        scroll.appendChild(row);
      });
      nav.appendChild(navDashboardRow());
      return;
    }
    const allRow = navRow("All", detail.totalGames, scope.kind === "all", () => setScope({ kind: "all" }));
    allRow.classList.add("nav-all");
    allRow.insertBefore(icon("layoutList", 13), allRow.firstChild);
    scroll.appendChild(allRow);

    // **System 목록은 기본적으로 평평하다.**
    //
    // 예전에는 `detail.storages`를 순회해서 Storage를 System의 부모 노드로 그렸다.
    // 그래서 External Storage를 한 번도 안 써 본 사용자에게까지 `INTERNAL` / `ROM`
    // 이라는, 요구한 적 없는 분류가 나타났다. Storage는 용량·볼륨·파일 작업을 위한
    // 내부 개념이고 사용자가 관리하는 단위는 System이다.
    //
    // **단, External Storage를 실제로 추가한 뒤에는 이야기가 다르다.** 그때부터는
    // "이 System을 내부/외부 중 어디에 둘지"가 사용자가 직접 관리하는 결정이 되므로
    // (드래그로 옮기고, ES-DE XML은 External만 대상으로 한다) Internal/External을
    // 그룹으로 나눠 보여준다. External이 없으면 이 분기 자체를 안 타므로 예전 그대로다.
    const storageById = {};
    (detail.storages || []).forEach((s) => { storageById[s.id] = s; });
    const externalStorages = (detail.storages || []).filter((s) => s.kind === "external");

    // Plan에 Storage 이동이 올라간 System은 Apply 전에도 목표 Storage 그룹
    // 밑에 미리 보여준다(실사용 피드백: "드래그해도 그 자리에 그대로 있어서
    // 옮겨진 게 안 보인다"). 실제 파일은 아직 그대로지만, 어느 그룹에
    // 나타나는지는 사용자의 마지막 결정(Plan)을 따른다.
    const pendingMoves = (S.plan && S.plan.pendingMoves) || {};
    const displayStorageId = (sys) => pendingMoves[sys.system] || sys.storageId;

    // 빈 System 숨기기(Settings와 SYSTEMS 제목 옆 버튼이 같은 값을 바꾼다). 지금 보고 있는
    // System과 이동이 예정된 System은 비어 있어도 남긴다 - 사라지면 어디 있는지 잃는다.
    const hideEmpty = !!(S.settings && S.settings.navigation && S.settings.navigation.hideEmptySystems);
    const visibleSystem = (sys) => !hideEmpty || sys.count > 0 || !!pendingMoves[sys.system]
      || (scope.kind === "system" && scope.id === sys.system);
    const hiddenCount = (detail.systems || []).filter((sys) => !visibleSystem(sys)).length;
    const hideToggle = h("button", {
      class: "icon-btn nav-hide-empty" + (hideEmpty ? " on" : ""),
      title: hideEmpty ? `빈 System 보이기 (숨김 ${formatCount(hiddenCount)}개)` : "빈 System 숨기기",
      "aria-pressed": hideEmpty ? "true" : "false",
    }, [icon(hideEmpty ? "eyeOff" : "eye", 12)]);
    hideToggle.addEventListener("click", () => updateSettings("navigation", { hideEmptySystems: !hideEmpty }));
    eyebrow.appendChild(hideToggle);

    function renderSystemRow(sys) {
      const row = navRow(sys.system.toUpperCase(), sys.count,
        scope.kind === "system" && scope.id === sys.system,
        () => setScope({ kind: "system", id: sys.system }));
      row.classList.add("nav-system");
      row.insertBefore(systemIcon(sys.system, 14), row.firstChild);
      if (!sys.count) row.classList.add("empty");
      const storage = storageById[sys.storageId];
      const pendingTo = pendingMoves[sys.system];
      if (pendingTo) {
        row.classList.add("pending-move");
        const target = storageById[pendingTo];
        row.title = `${sys.system} · ${formatCount(sys.count)}개\n이동 예정: ${storage ? storage.label : sys.storageId} → ${target ? target.label : pendingTo}(Apply로 확정)`;
      } else if (storage) {
        row.title = `${sys.system} · ${formatCount(sys.count)}개 · ${storage.label}\n${storage.rootPath}`;
      }
      // Compare 중에는 System을 끌어 옮길 수 없다 - 그 드롭/메뉴 하나가 Plan을 바꾸고,
      // Auto Plan이 꺼져 있으면 실제 파일까지 옮긴다.
      if (!isCompare()) {
        row.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          openSystemMenu(sys, detail.storages || [], e);
        });
        // 우클릭 메뉴와 같은 동작(moveSystemToStorage)을 드래그로도 하게 한다 -
        // 메뉴는 남겨 둔다(키보드/터치에서는 드래그가 없다).
        row.draggable = true;
        row.addEventListener("dragstart", (e) => {
          e.dataTransfer.setData("text/plain", sys.system);
          e.dataTransfer.effectAllowed = "move";
        });
      }
      return row;
    }

    if (!externalStorages.length) {
      (detail.systems || []).filter(visibleSystem).forEach((sys) => scroll.appendChild(renderSystemRow(sys)));
    } else {
      (detail.storages || []).forEach((storage) => {
        const group = h("div", { class: "nav-group" });
        const head = h("div", { class: "nav-group-head" },
          [h("span", { class: "nav-group-name" }, [storage.label.toUpperCase()])]);

        // ES-DE의 custom_systems XML은 External Storage에 있는 System만 대상으로
        // 하므로(§ write_custom_systems), 그 그룹 옆에만 버튼을 둔다. Collection당
        // 파일이 하나라 어느 External 그룹에서 눌러도 같은 파일을 다시 쓴다.
        if (storage.kind === "external" && !isCompare() && S.adapterActions && S.adapterActions.length) {
          S.adapterActions.forEach((action) => {
            const xmlBtn = h("button", { class: "icon-btn", title: `${action.label} (External Storage 전체 기준)` },
                             [icon("save", 11)]);
            xmlBtn.addEventListener("click", (e) => { e.stopPropagation(); runAdapterAction(action); });
            head.appendChild(xmlBtn);
          });
        }
        group.appendChild(head);

        if (!isCompare()) {
          const systemNames = (detail.systems || [])
            .filter((sys) => sys.storageId === storage.id).map((sys) => sys.system);
          head.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            if (systemNames.length) openMetadataBootstrap(S.activeId, systemNames);
          });
          group.addEventListener("dragover", (e) => { e.preventDefault(); group.classList.add("drop-target"); });
          group.addEventListener("dragleave", () => group.classList.remove("drop-target"));
          group.addEventListener("drop", (e) => {
            e.preventDefault();
            group.classList.remove("drop-target");
            const system = e.dataTransfer.getData("text/plain");
            if (system) moveSystemToStorage(system, storage.id);
          });
        }

        (detail.systems || []).filter((sys) => displayStorageId(sys) === storage.id && visibleSystem(sys))
          .forEach((sys) => group.appendChild(renderSystemRow(sys)));
        scroll.appendChild(group);
      });
    }

    // Add External Storage는 System이 아무리 늘어나도 밀려나면 안 되므로 스크롤
    // 밖(고정 영역)에 둔다.
    if (!isCompare()) {
      const add = h("button", { class: "nav-action" }, [icon("plus", 12), h("span", {}, ["Add External Storage"])]);
      add.addEventListener("click", openAddStorage);
      nav.appendChild(add);
      // gamelist 만들기는 Toolbar 아이콘(Collection 전체) + System/Storage 우클릭
      // 메뉴(부분)로 옮겼다 - 예전엔 이 버튼 하나뿐이었다.
    }
    nav.appendChild(navDashboardRow());
  }

  function navRow(label, count, active, onClick) {
    const row = h("div", { class: "nav-row" + (active ? " active" : "") }, [
      h("span", { class: "nav-label" }, [label]),
      h("span", { class: "nav-count" }, [formatCount(count)]),
    ]);
    row.addEventListener("click", onClick);
    return row;
  }

  async function setScope(scope) {
    S.scope[S.activeId] = scope;
    // Dashboard를 보다가 System을 고르면 그 System의 목록으로 간다.
    if (S.view === "dashboard") { S.view = "list"; renderCenterView(); }
    resetList();
    // Collection/System을 옮기면 이전 선택은 의미가 없다. 남겨 두면 화면에 보이지도
    // 않는 게임이 선택된 채로 남아, Archive 수집 같은 동작이 그 UID를 대상으로 삼는다.
    clearSelection();
    renderNav();
    // Overview 헤더가 System을 고르면 그 System 이름/아이콘으로 바뀐다
    // (레이아웃 재검토) - scope가 바뀌었으니 다시 그려야 한다.
    renderHeader();
    renderFilterBar();
    // 선택 개수와 수집 대상 표시도 함께 맞춘다 - 선택을 비웠으니 화면도 그래야 한다.
    renderStatusBar();
    await reloadList();
  }

  /** 선택/포커스를 비운다. Collection이나 System이 바뀌면 반드시 거쳐야 한다. */
  function clearSelection() {
    S.selected.clear();
    S.selectAnchor = null;
    S.focused = null;
  }

  async function moveSystemToStorage(system, storageId) {
    if (blockedInCompare("System을 이동")) return;
    // 실제 파일은 아직 움직이지 않는다. Plan에 올려두고 확정할 때 옮긴다(스펙 §10, §28).
    const r = await api.planStorageChange(S.activeId, system, storageId);
    if (!r.ok) { showToast(r.error, "error"); return; }
    await refreshPlan();
    if (S.autoPlan) {
      showToast(`${system.toUpperCase()} 이동을 Plan에 올렸습니다. Apply로 확정하세요.`);
    } else {
      await applyPlan();
    }
  }

  function openAddStorage() {
    if (blockedInCompare("Storage를 추가")) return;
    const labelInput = h("input", { class: "field-input", value: "External SD" });
    const pathInput = h("input", { class: "field-input", placeholder: "예: E:\\ROMs" });
    const browse = h("button", { class: "btn", onClick: async () => {
      const r = await api.pickFolder("External Storage 폴더");
      if (r.ok && r.data) pathInput.value = r.data;
    } }, [icon("folderOpen", 12)]);
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "field-label" }, ["이름"]), labelInput,
      h("div", { class: "field-label" }, ["경로"]),
      h("div", { class: "field-row" }, [pathInput, browse]),
    ]);
    showModal("External Storage 추가", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary", onClick: async () => {
        const path = pathInput.value.trim();
        if (!path) { showToast("경로를 입력하세요.", "warning"); return; }
        closeModal();
        const r = await api.addExternalStorage(S.activeId, labelInput.value.trim(), path);
        if (!r.ok) { showToast(r.error, "error"); return; }
        await ensureDetail(S.activeId);
        renderNav(); renderHeader(); renderStatusBar();
      } }, ["추가"]),
    ]);
  }

  /** System 하나의 정보와 Storage 이동(스펙 §10, §471의 System 메뉴).
   *
   * 예전에는 Storage 그룹 사이로 끌어다 놓는 것이 유일한 이동 방법이었다. 그런데
   * Navigation에서 Storage 계층을 없앴으므로(사용자가 보는 단위는 System이다) 드롭할
   * 그룹 자체가 없다. 기능은 그대로 두고 들어가는 문만 옮긴다.
   */
  /** System 우클릭 메뉴 - 게임 행 메뉴와 같은 컨텍스트 메뉴를 쓴다. */
  function openSystemMenu(sys, storages, event) {
    const current = storages.find((s) => s.id === sys.storageId);
    const items = [];
    const others = storages.filter((s) => s.id !== sys.storageId);
    if (others.length) {
      items.push({ section: "Storage 옮기기" });
      others.forEach((target) => items.push({
        label: target.label, title: target.rootPath,
        icon: target.kind === "internal" ? "hardDrive" : "hardDriveDownload",
        onSelect: () => moveSystemToStorage(sys.system, target.id),
      }));
      items.push("separator");
    }
    items.push({ label: "gamelist 만들기", icon: "fileWarning",
      title: "이 System에 gamelist가 없으면 ROM 파일명만 담아 만듭니다.",
      onSelect: () => openMetadataBootstrap(S.activeId, [sys.system]) });
    // 폴더 경로는 백엔드(Adapter layout)가 정한다 - Storage 배치와 System별 경로 지정을 따른다.
    items.push("separator", { section: "폴더 열기" });
    [["rom", "ROM 폴더"], ["metadata", "Metadata 폴더"], ["media", "Media 폴더"]].forEach(([kind, label]) =>
      items.push({ label, icon: "folderOpen", onSelect: () => openSystemFolder(sys.system, kind) }));
    // 메뉴 최하단, 빨간색(사용자 결정). 누르면 경고 + "확인하였습니다" 체크 + 확인으로 한 번 더 묻는다.
    items.push("separator", {
      label: "전체 삭제", icon: "trash", danger: true,
      title: "이 System의 ROM·Metadata·Media를 디스크에서 지우고 목록에서 뺍니다.",
      onSelect: () => confirmRemoveSystem(sys),
    });
    showContextMenu(menuPoint(event), sys.system.toUpperCase(),
      `게임 ${formatCount(sys.count)} · ${current ? current.label : sys.storageId}`, items,
      current ? current.rootPath : null);
  }

  async function openSystemFolder(system, kind) {
    const r = await api.openSystemFolder(S.activeId, system, kind);
    if (!r.ok) showToast(r.error, "error");
  }

  /** System 전체 삭제. **두 번 묻는다**(사용자 결정 - 실수로 지우는 것을 막는다).
   *
   * 1) System 우클릭 메뉴 최하단의 빨간 [전체 삭제]
   * 2) 경고와 지울 목록을 보여주고, "확인하였습니다"를 체크해야 확인 버튼이 켜진다.
   *    취소하면 아무것도 하지 않는다.
   * 게임이 있어도 지운다(force). Collection/Storage root와 공용 폴더는 백엔드가 남긴다. */
  async function confirmRemoveSystem(sys) {
    const collectionId = S.activeId;
    const preview = await api.systemRemovalPreview(collectionId, sys.system, true);
    if (!preview.ok) { showToast(preview.error, "error"); return; }
    const p = preview.data;
    const name = sys.system.toUpperCase();
    const KIND = { rom: "ROM", metadata: "Metadata", media: "Media" };

    if (p.blockers.length) {
      showModal(`${name} System을 삭제할 수 없습니다`, h("div", { class: "modal-body" },
        p.blockers.map((text) => h("div", { class: "modal-text sysdel-blocker" }, [text]))),
        [h("button", { class: "btn primary", onClick: closeModal }, ["닫기"])]);
      return;
    }

    const list = h("div", { class: "sysdel-list" });
    p.targets.forEach((t) => {
      list.appendChild(h("div", { class: "sysdel-target" }, [
        h("span", { class: "sysdel-kind" }, [KIND[t.kind] || t.kind]),
        h("span", { class: "sysdel-path", title: t.path }, [t.filesOnly ? `${t.path} 안의 파일` : t.path]),
        h("span", { class: "sysdel-count" }, [t.fileCount ? `파일 ${formatCount(t.fileCount)}개` : "비어 있음"]),
      ]));
      t.files.forEach((file) => list.appendChild(h("div", { class: "sysdel-file", title: file }, [file])));
      if (t.fileCount > t.files.length) {
        list.appendChild(h("div", { class: "sysdel-file" }, [`… 외 ${formatCount(t.fileCount - t.files.length)}개`]));
      }
    });

    const summary = !p.targets.length ? "디스크에서 지울 파일이 없습니다. 목록에서만 뺍니다."
      : p.games ? `게임 ${formatCount(p.games)}개를 포함해 아래 파일 ${formatCount(p.totalFiles)}개(${formatBytes(p.totalBytes)})를 디스크에서 영구히 지우고 목록에서 뺍니다.`
      : `게임이 없는 System입니다. 아래 파일 ${formatCount(p.totalFiles)}개를 지우고 목록에서 뺍니다.`;
    const check = h("input", { type: "checkbox", class: "sysdel-ack-input" });
    const confirmBtn = h("button", { class: "btn danger sysdel-confirm" }, ["확인"]);
    confirmBtn.disabled = true;
    check.addEventListener("change", () => { confirmBtn.disabled = !check.checked; });
    confirmBtn.addEventListener("click", async () => {
      if (!check.checked) return;
      closeModal();
      const r = await api.removeSystem(collectionId, sys.system, true);
      if (!r.ok) { showToast(r.error, "error"); return; }
      await ensureDetail(collectionId);
      if (collectionId !== S.activeId) return;
      const scope = activeScope();
      if (scope.kind === "system" && scope.id === sys.system) {
        await setScope({ kind: "all" });
      } else {
        resetList();
        renderAll();
        await reloadList();
      }
      await refreshPlan();
      showToast(`${name} System을 삭제했습니다.`);
    });

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "sysdel-warning" }, [
        h("div", { class: "sysdel-warning-title" }, ["되돌릴 수 없는 삭제입니다"]),
        h("div", { class: "modal-text" }, [summary]),
      ]),
      p.targets.length ? list : null,
      p.kept.length ? h("div", { class: "modal-text sysdel-kept" },
        [`Collection/Storage 최상위 폴더와 다른 System과 함께 쓰는 폴더는 남깁니다: ${p.kept.map((k) => k.path).join(", ")}`]) : null,
      h("label", { class: "sysdel-ack" }, [check, h("span", {}, ["확인하였습니다"])]),
    ]);
    showModal(`${name} 전체 삭제`, body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      confirmBtn,
    ]);
  }

  function openStorageMenu(storage) {
    const stats = h("div", { class: "modal-body" }, [
      h("div", { class: "health-row" }, [h("span", {}, ["경로"]), h("span", {}, [storage.rootPath])]),
      h("div", { class: "health-row" }, [h("span", {}, ["Actual"]), h("span", {}, [formatBytes(storage.actualBytes)])]),
      h("div", { class: "health-row" }, [h("span", {}, ["Capacity"]),
        h("span", {}, [storage.capacityBytes == null ? "Unknown" : formatBytes(storage.capacityBytes)])]),
      h("div", { class: "health-row" }, [h("span", {}, ["Free"]),
        h("span", {}, [storage.freeBytes == null ? "Unknown" : formatBytes(storage.freeBytes)])]),
      h("div", { class: "health-row" }, [h("span", {}, ["Systems"]), h("span", {}, [String(storage.systems.length)])]),
    ]);
    const actions = [h("button", { class: "btn primary", onClick: closeModal }, ["닫기"])];
    if (storage.kind !== "internal") {
      actions.unshift(h("button", { class: "btn danger", onClick: async () => {
        closeModal();
        const r = await api.removeStorage(S.activeId, storage.id);
        if (!r.ok) { showToast(r.error, "error"); return; }
        await ensureDetail(S.activeId);
        renderNav(); renderHeader();
      } }, ["제거"]));
    }
    showModal(`${storage.label} Health`, stats, actions);
  }

  // ------------------------------------------------------------------
  // Collection 헤더
  // ------------------------------------------------------------------
  function renderHeader() {
    const host = $("collection-header");
    clear(host);
    const detail = activeDetail();
    if (!detail) return;

    // Navigator에서 System을 골랐으면 그 System의 정체를 보여준다 - 항상
    // Collection 이름만 보이면 지금 뭘 보고 있는지 다시 Navigator를 봐야
    // 했다(레이아웃 재검토). Frontend/OS/Arch 줄은 System 고유 정보가 아니라
    // Collection 정보라 그대로 둔다.
    const scope = activeScope();
    const systemEntry = scope.kind === "system"
      ? (detail.systems || []).find((s) => s.system === scope.id) : null;

    const compact = h("div", { class: "cheader" });
    compact.appendChild(h("div", { class: "cheader-icon" }, [
      systemEntry ? systemIcon(systemEntry.system, 20) : icon("gamepad", 20),
    ]));

    const main = h("div", { class: "cheader-main" });
    // "Collection 제목 (System)" - Collection 소속을 잃지 않으면서 지금 어느
    // System을 보는지 알린다(사용자 요청). System 이름만 있으면 여러 Collection을
    // 오갈 때 지금 어느 Collection의 System인지 다시 헷갈린다.
    main.appendChild(h("div", { class: "cheader-name" },
      [systemEntry ? `${detail.name} (${systemEntry.system.toUpperCase()})` : detail.name]));
    main.appendChild(h("div", { class: "cheader-sub" }, [
      detail.frontendLabel,
      h("span", { class: "dot" }, ["·"]),
      detail.target ? detail.target : "Unknown",
      h("span", { class: "dot" }, ["·"]),
      detail.arch ? detail.arch.toUpperCase() : "Unknown",
    ]));
    const summary = h("div", { class: "cheader-stats" }, [
      h("span", {}, [`${formatCount(systemEntry ? systemEntry.count : detail.totalGames)} Games`]),
    ]);
    detail.storages.forEach((storage) => {
      // Plan이 있으면 "Actual -> Plan"으로 보여준다(스펙 §19, §30).
      const capacity = planCapacity(storage.id);
      const changed = capacity && capacity.deltaBytes;
      summary.appendChild(h("span", { class: "cheader-storage" + (capacity && capacity.over ? " over" : "") }, [
        `${storage.label} ${formatBytes(storage.actualBytes)}`,
        changed ? ` → ${formatBytes(capacity.planBytes)}` : "",
      ]));
    });
    main.appendChild(summary);
    compact.appendChild(main);

    const right = h("div", { class: "cheader-right" });
    if (isArchive()) {
      // Archive에는 gamelist 만들기/Collection 가져오기/Expand가 의미 없다 -
      // 다시 스캔만 있으면 된다(Toolbar에 있던 것과 중복이라 그쪽은 없앴다).
      const refresh = h("button", { class: "icon-btn", title: "다시 스캔" }, [icon("refresh", 13)]);
      refresh.addEventListener("click", refreshActive);
      right.appendChild(refresh);
      compact.appendChild(right);
      host.appendChild(compact);
      return;
    }

    // gamelist 만들기 / Collection 가져오기는 Toolbar에 있었는데 여기로
    // 옮겼다(레이아웃 재검토 - GameList 상단 chrome에 모으는 게 자연스럽다는
    // 실사용 피드백). 순서: gamelist 생성, Collection 가져오기, 새로고침, 확장.
    if (!isCompare()) {
      const bootstrap = h("button", { class: "icon-btn", id: "make-gamelist-btn",
        title: "gamelist가 없는 System에 ROM 파일명만 담은 gamelist를 만듭니다." },
        [icon("fileWarning", 13)]);
      bootstrap.addEventListener("click", () => openMetadataBootstrap(S.activeId));
      right.appendChild(bootstrap);

      const importBtn = h("button", { class: "icon-btn", title: "Collection 가져오기 (Import)" },
        [icon("upload", 13)]);
      importBtn.addEventListener("click", openAddCollection);
      right.appendChild(importBtn);
    }

    // 아이콘만 - 글자("Rescan")는 없앴다. 확장(v) 버튼과 같은 크기로 맞춘다.
    const rescan = h("button", { class: "icon-btn", title: "다시 스캔" }, [icon("refresh", 13)]);
    rescan.addEventListener("click", refreshActive);
    right.appendChild(rescan);
    const toggle = h("button", { class: "icon-btn", title: S.headerExpanded ? "접기" : "펼치기" },
      [icon(S.headerExpanded ? "chevronUp" : "chevronDown", 13)]);
    toggle.addEventListener("click", () => { S.headerExpanded = !S.headerExpanded; renderHeader(); });
    right.appendChild(toggle);
    compact.appendChild(right);
    host.appendChild(compact);

    if (!S.headerExpanded) return;

    const panel = h("div", { class: "cheader-expanded" });
    const info = h("div", { class: "cheader-info" });
    [["Frontend", detail.frontendLabel], ["Target", detail.target || "Unknown"],
     ["OS", detail.os || "Unknown"], ["Architecture", detail.arch || "Unknown"],
     ["Root Path", detail.rootPath], ["Systems", String(detail.systemCount)],
     ["Games", formatCount(detail.totalGames)]].forEach(([label, value]) => {
      info.appendChild(h("div", { class: "cheader-info-row" }, [
        h("span", { class: "cheader-info-label" }, [label]),
        h("span", { class: "cheader-info-value" }, [value]),
      ]));
    });
    panel.appendChild(info);

    detail.storages.forEach((storage) => {
      const box = h("div", { class: "storage-box" });
      box.appendChild(h("div", { class: "storage-box-title" }, [storage.label.toUpperCase()]));
      const unknown = storage.capacityBytes == null;
      [["Capacity", unknown ? "Unknown" : formatBytes(storage.capacityBytes)],
       ["Actual", formatBytes(storage.actualBytes)],
       ["Free", storage.freeBytes == null ? "Unknown" : formatBytes(storage.freeBytes)]].forEach(([l, v]) => {
        box.appendChild(h("div", { class: "health-row" }, [h("span", {}, [l]), h("span", {}, [v])]));
      });
      if (!unknown && storage.capacityBytes > 0) {
        const used = Math.min(100, (storage.actualBytes / storage.capacityBytes) * 100);
        box.appendChild(h("div", { class: "storage-bar" }, [
          h("div", { class: "storage-bar-fill", style: { width: used.toFixed(1) + "%" } })]));
      }
      panel.appendChild(box);
    });

    // Frontend 고유 기능(ES-DE의 custom systems XML)은 여기 두지 않는다 - 그
    // 기능은 External Storage에 있는 System만 대상으로 하므로, Navigator의
    // External Storage 그룹 옆으로 옮겼다(renderNav 참고).
    host.appendChild(panel);
  }

  async function loadAdapterActions() {
    S.adapterActions = [];
    if (!S.activeId || isArchive()) return;
    const r = await api.adapterActions(S.activeId);
    if (r.ok) S.adapterActions = r.data;
  }

  async function runAdapterAction(action) {
    if (blockedInCompare(`${action.label}을 실행`)) return;
    const r = await api.runAdapterAction(S.activeId, action.id);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const data = r.data || {};
    if (data.written === false) {
      // 만들 내용이 없는 것과 실패한 것은 다르다 - 왜 아무 일도 없었는지 말해준다.
      showToast("Collection 밖에 있는 System이 없어 만들 XML이 없습니다.");
      return;
    }
    const systems = (data.systems || []).join(", ");
    showToast(`${action.label} 완료${systems ? ` - ${systems}` : ""}`);
  }

  // ------------------------------------------------------------------
  // 필터 바
  // ------------------------------------------------------------------
  // 상태의 뜻을 버튼 툴팁으로 고정한다. 특히 **Same은 "같은 ROM 파일"이라는 뜻이 아니다** -
  // 양쪽에 대응 항목이 있고 비교 대상 Metadata가 같다는 뜻이다. 크기가 달라도 Same일 수
  // 있고, 그 차이는 상세의 Size 줄에서 본다.
  const COMPARE_FILTERS = [
    ["all", "All", "양쪽을 맞댄 전체 목록"],
    ["same", "Same", "양쪽에 있고 비교 대상 Metadata가 같음 (ROM 파일이 같다는 뜻은 아님 - 크기는 상세에서 확인)"],
    ["only_a", "Only A", "기준 Collection에만 있음"],
    ["only_b", "Only B", "상대 Collection에만 있음"],
    ["conflict", "Conflict", "양쪽에 있는데 비교 대상 Metadata가 다름"],
    ["media", "Media", "Media 구성이 다름 (상태와 별개 신호)"],
  ];

  function renderCompareBar(bar) {
    const state = S.compare;
    bar.classList.add("compare");
    bar.appendChild(h("div", { class: "compare-title" }, [
      h("span", { class: "compare-eyebrow" }, ["COMPARE"]),
      h("span", { class: "truncate" }, [`${state.baseName} ↔ ${state.otherName}`]),
    ]));

    const filters = h("div", { class: "compare-filters" });
    COMPARE_FILTERS.forEach(([key, label, hint]) => {
      const count = (state.counts || {})[key];
      const btn = h("button", {
        class: "compare-filter" + (S.compareFilter === key ? " active" : "") + " f-" + key,
        title: hint,
      }, [label, count === undefined ? "" : h("span", { class: "compare-filter-count" },
                                              [formatCount(count)])]);
      btn.addEventListener("click", async () => {
        S.compareFilter = key;
        resetList();
        renderFilterBar();
        await reloadList();
      });
      filters.appendChild(btn);
    });
    bar.appendChild(filters);

    bar.appendChild(h("div", { class: "filter-spacer" }));

    // 이 결과는 시작 시점의 스냅샷이다(필터를 눌러도 다시 읽지 않는다). 그 사이
    // Collection이 바뀌었을 수 있으므로 언제 찍은 것인지 밝히고, 다시 찍는 길을 준다.
    if (state.takenAt) {
      bar.appendChild(h("span", { class: "compare-snapshot", title: "이 시각의 스냅샷입니다" },
        [`Snapshot ${formatClock(state.takenAt)}`]));
    }
    const refresh = h("button", { class: "btn compact", title: "지금 상태로 다시 비교합니다" },
      ["Refresh"]);
    refresh.addEventListener("click", () => runCompare(state.baseId, state.otherId));
    bar.appendChild(refresh);

    const exit = h("button", { class: "btn compact" }, ["Exit Compare"]);
    exit.addEventListener("click", exitCompare);
    bar.appendChild(exit);
  }

  function formatClock(epochSeconds) {
    const d = new Date(epochSeconds * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function renderFilterBar() {
    const bar = $("filter-bar");
    clear(bar);
    bar.classList.remove("compare");
    if (isCompare()) { renderCompareBar(bar); return; }
    if (!activeDetail()) return;

    // 이전 프로젝트의 툴바 구성이다.
    //   List/Card · System · Status · ★ · Search · Refresh
    // 정렬 셀렉트와 방향 버튼은 없앴다 - Header를 눌러서 정렬하기 때문이다.
    const detail = activeDetail();

    const modes = h("div", { class: "seg view-mode-seg" });
    [["list", "목록"], ["card", "카드"]].forEach(([mode, label]) => {
      const btn = h("button", {
        class: "seg-btn" + (S.viewMode === mode ? " on" : ""), title: label + " 보기",
      }, [icon(mode === "list" ? "layoutList" : "layoutGrid", 12)]);
      btn.addEventListener("click", () => {
        if (S.viewMode === mode) return;
        S.viewMode = mode;
        // 보기 방식은 UI 상태다 - 다시 열었을 때 그대로여야 한다. 데이터는 그대로이니
        // 목록을 다시 불러오지 않는다.
        saveUiState();
        renderFilterBar();
        renderListWindow();
      });
      modes.appendChild(btn);
    });
    bar.appendChild(modes);

    // System 필터는 없앴다(레이아웃 재검토 결론) - Navigator가 항상 옆에 붙어
    // 있고 지금 System은 Header에 크게 나오므로, 같은 것을 고르는 두 번째
    // 컨트롤을 둘 이유가 없었다.

    const statusSel = h("select", { class: "mini-select", title: "상태 필터" }, [
      h("option", { value: "all" }, ["모든 상태"]),
      h("option", { value: "metadata" }, ["메타데이터 없음"]),
      h("option", { value: "media" }, ["미디어 없음"]),
      h("option", { value: "missing" }, ["ROM 없음"]),
    ]);
    statusSel.value = S.statusFilter;
    statusSel.addEventListener("change", async (e) => {
      S.statusFilter = e.target.value;
      resetList();
      await reloadList();
    });
    bar.appendChild(statusSel);

    // 정렬 셀렉트는 두지 않는다 - 목록 머리글(#list-head)이 Card 보기에서도
    // 그대로 보이고 클릭도 되므로(실사용 확인) 따로 둘 이유가 없다.
    const fav = h("button", {
      class: "icon-btn" + (S.favoritesOnly ? " on" : ""),
      title: S.favoritesOnly ? "전체 보기" : "즐겨찾기만 보기",
    }, [S.favoritesOnly ? "★" : "☆"]);
    fav.addEventListener("click", async () => {
      S.favoritesOnly = !S.favoritesOnly;
      renderFilterBar();
      resetList();
      await reloadList();
    });
    bar.appendChild(fav);

    const search = h("input", { class: "search-input", placeholder: "Search...", value: S.search });
    let timer = null;
    search.addEventListener("input", (e) => {
      clearTimeout(timer);
      const value = e.target.value;
      timer = setTimeout(async () => { S.search = value; resetList(); await reloadList(); }, 180);
    });
    bar.appendChild(h("div", { class: "search-box" }, [icon("search", 13), search]));

    // 다시 스캔 / gamelist 만들기 / Collection 가져오기는 GameList 상단
    // chrome(Overview, renderHeader의 cheader-right)으로 옮겼다 - 여기 그대로
    // 두면 똑같은 기능이 두 곳에 보인다(레이아웃 재검토, 실사용 피드백).
    //
    // Preview 토글도 여기 없다 - Detail 패널 상단(.detail-topspace)의 토글이
    // 이제 항상 보이므로(Preview를 꺼도 그 자리는 남는다) 여기 하나만 있으면
    // 된다.

    bar.appendChild(h("div", { class: "filter-spacer" }));

    // Plan 조작은 여기 있어야 한다. 하단 상태바에 있으면 목록에서 고르고 바로 누르기가
    // 멀고, 무엇보다 지금 무엇이 선택돼 있는지와 떨어져 보인다.
    renderPlanActions(bar);

    bar.appendChild(h("div", { class: "filter-total", id: "filter-total" },
      [`${formatCount(S.total)} items`]));
  }

  /** Archive에 수집 / Delete / AutoPlan / Apply / Cancel. Gamelist 위 툴바 한 곳에
   * 모은다 - 예전에는 이 중 일부가 하단 상태바에도 똑같이 있어서 두 번 보였다.
   * Copy/Paste는 없앴다(QA 재검토 P1) - Collection 사이 이동은 Archive를 거친다. */
  function renderPlanActions(bar) {
    if (isCompare() || isArchive()) return;
    const plan = S.plan;

    // Archive에 수집은 여기 없다 - Detail 패널 상단(.detail-topspace)으로
    // 옮겼다(레이아웃 재검토).
    //
    // Delete는 상시 버튼을 두지 않는다(레이아웃 재검토 결론) - DEL 키와 목록
    // 우클릭 메뉴로만 접근한다. 파괴적인 동작이라 눈에 항상 띄는 자리에 두면
    // 오클릭 위험이 커진다(PENDING_DECISIONS.md).

    // Apply/Cancel은 한 그룹이다 - 같은 Plan을 두고 하는 순간의 동작이라는 걸
    // 구분선으로 보여준다. Auto Plan 토글은 뺐다(실사용 시나리오가 확인될 때까지
    // 화면에서 감춘다, PENDING_DECISIONS.md) - 내부 값은 기본 ON을 유지한다.
    const planGroup = h("div", { class: "seg plan-actions" });
    const apply = h("button", {
      class: "seg-btn" + (plan && plan.total ? " on" : ""), disabled: !(plan && plan.total),
      title: plan && plan.total ? "Plan을 실제 파일에 적용합니다" : "적용할 Plan이 없습니다",
    }, [plan && plan.total ? `Apply (${formatCount(plan.total)})` : "Apply"]);
    if (plan && plan.total) apply.addEventListener("click", applyPlan);
    planGroup.appendChild(apply);

    const cancel = h("button", {
      class: "seg-btn", disabled: !(plan && plan.total), title: "계산해둔 변경을 버립니다",
    }, ["Cancel"]);
    if (plan && plan.total) {
      cancel.addEventListener("click", () => showConfirm(
        "Plan 취소", "계산해둔 변경을 모두 버립니다. 실제 파일은 바뀌지 않습니다.", true,
        async () => { await api.planClear(S.activeId); await refreshPlan(); }));
    }
    planGroup.appendChild(cancel);
    bar.appendChild(planGroup);
  }

  /** 선택이 바뀌었을 때 툴바에서 **실제로 달라지는 것만** 고친다.
   *
   * 툴바를 통째로 다시 그리면 검색창이 새로 만들어져 입력 중이던 커서가 날아간다.
   * 선택 때문에 달라지는 것은 수집 대상 표시뿐이다(Delete는 상시 버튼이 없다).
   */
  function updateSelectionDependentActions() {
    const ingest = $("archive-ingest-btn");
    if (ingest) {
      const scope = archiveScope();
      const label = archiveScopeLabel(scope);
      ingest.dataset.scope = scope.kind;
      ingest.title = `${label}을 Archive에 수집합니다`;
      // 버튼 안에는 span이 둘이다(아이콘 span이 먼저, 글자 span이 나중) - 그냥
      // "span"으로 고르면 **아이콘 span을 잡아 아이콘을 글자로 덮어썼다.**
      const text = ingest.querySelector(".ingest-label");
      if (text) text.textContent = `Archive에 수집 — ${label}`;
    }
    // Archive 탭의 "Collection으로 보내기"도 Detail 패널 상단에 있다 - 선택이
    // 바뀔 때마다 renderDetailPanel()을 통째로 다시 그리진 않으므로(Metadata
    // 입력 중 커서가 날아간다) 여기서 같이 패치한다.
    const send = $("archive-send-btn");
    if (send) {
      const targets = S.tabs.filter((t) => t !== ARCHIVE_ID);
      send.disabled = !S.selected.size || !targets.length;
      send.title = !targets.length ? "보낼 Collection을 먼저 열어주세요"
                 : !S.selected.size ? "보낼 항목을 먼저 고르세요"
                 : "선택 항목을 Collection으로 보냅니다";
      send.onclick = (S.selected.size && targets.length) ? openSendToCollection : null;
    }
  }

  // ------------------------------------------------------------------
  // Gamelist (가상 스크롤)
  // ------------------------------------------------------------------
  function resetList() {
    S.rowCache.clear();
    S.loadedPages.clear();
    S.matchCounts = {};
    S.total = 0;
    S.selected.clear();
    // Shift 범위 선택의 기준점도 지운다. romUid는 Collection마다 새로 매겨지는 값이라
    // (auto-increment) 두 Collection에서 같은 값이 흔히 겹친다 - 지우지 않으면 A에서
    // 남긴 기준점이 다음에 연 B에서 우연히 같은 romUid를 만나 그 행을 기준점으로
    // 오인할 수 있다.
    S.selectAnchor = null;
    S.focused = null;
    S.detailState = null;
    S.queryToken += 1;
    const scroll = $("list-scroll");
    if (scroll) scroll.scrollTop = 0;
  }

  /** 목록을 좌우로 민 만큼 헤더도 민다. */
  function syncHeadScroll() {
    const scroll = $("list-scroll"), head = $("list-head");
    if (!scroll || !head) return;
    head.style.transform = `translateX(${-scroll.scrollLeft}px)`;
  }

  function renderListHead() {
    const head = $("list-head");
    clear(head);
    if (!activeDetail()) return;
    head.style.gridTemplateColumns = gridTemplate();
    // 본문과 같은 폭을 갖게 해야 가로로 밀었을 때 컬럼이 어긋나지 않는다.
    head.style.minWidth = totalColumnWidth() + "px";
    syncHeadScroll();
    // 머리글 우클릭 = 컬럼 표시 메뉴. head는 다시 만들지 않는 요소라 속성으로 한 번만 단다.
    head.oncontextmenu = (e) => { e.preventDefault(); if (!isCompare()) openColumnMenu(e); };

    visibleColumns().forEach((col) => {
      const sorted = col.key && S.order === col.key;
      const cell = h("div", { class: "lh lh-" + col.id + (sorted ? " sorted" : "") },
                     [col.label]);
      if (col.key) {
        // 한 번 누르면 오름차순, 다시 누르면 내림차순. 이전 프로젝트와 같다.
        // Card 보기에서도 이 머리글이 그대로 보이고 클릭도 되므로(실사용 확인),
        // Card 전용 정렬 컨트롤은 따로 두지 않는다.
        cell.addEventListener("click", async () => {
          if (S.order === col.key) S.descending = !S.descending;
          else { S.order = col.key; S.descending = false; }
          saveUiState();
          resetList();
          renderListHead();
          await reloadList();
        });
        if (sorted) cell.appendChild(icon(S.descending ? "chevronDown" : "chevronUp", 10));
      }
      if (!col.fixed) {
        const handle = h("div", { class: "col-resize" });
        handle.addEventListener("mousedown", (e) => startColumnResize(col.id, e));
        handle.addEventListener("click", (e) => e.stopPropagation());
        cell.appendChild(handle);
      }
      if (!isCompare()) bindColumnDrag(cell, col.id);
      head.appendChild(cell);
    });
  }

  /** 머리글을 끌어 컬럼 순서를 바꾼다. 놓는 자리의 왼쪽/오른쪽 절반으로 앞/뒤를 정한다. */
  let draggingColumn = null;
  function bindColumnDrag(cell, id) {
    const clearMarks = () => cell.classList.remove("drop-before", "drop-after");
    cell.draggable = id !== "no";
    cell.addEventListener("dragstart", (e) => {
      if (id === "no") { e.preventDefault(); return; }
      draggingColumn = id;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/x-rms-column", id);
      cell.classList.add("dragging");
    });
    cell.addEventListener("dragend", () => {
      draggingColumn = null;
      document.querySelectorAll("#list-head .lh").forEach((c) =>
        c.classList.remove("dragging", "drop-before", "drop-after"));
    });
    cell.addEventListener("dragover", (e) => {
      if (!draggingColumn || draggingColumn === id) return;
      e.preventDefault();
      const rect = cell.getBoundingClientRect();
      const after = id === "no" || e.clientX > rect.left + rect.width / 2;
      cell.classList.toggle("drop-after", after);
      cell.classList.toggle("drop-before", !after);
    });
    cell.addEventListener("dragleave", clearMarks);
    cell.addEventListener("drop", (e) => {
      if (!draggingColumn) return;
      e.preventDefault();
      const after = cell.classList.contains("drop-after");
      clearMarks();
      const moving = draggingColumn;
      draggingColumn = null;
      moveColumn(moving, id, after);
    });
  }

  function openColumnMenu(event) {
    const { order, hidden } = columnLayout();
    const items = [{ section: "컬럼 표시" }];
    order.filter((id) => id !== "no").forEach((id) => {
      const locked = LOCKED_COLUMNS.has(id);
      const visible = !hidden.has(id);
      items.push({
        label: columnName(COLUMN_BY_ID[id]), icon: visible ? "check" : null, disabled: locked,
        hint: locked ? "항상 표시" : null, title: locked ? "Title은 숨길 수 없습니다." : null,
        onSelect: () => toggleColumn(id, !visible),
      });
    });
    items.push("separator",
      { label: "기본 순서와 표시로", onSelect: resetColumns },
      { label: "Settings에서 설정", icon: "settings", onSelect: () => openSettings("metadata") });
    showContextMenu(menuPoint(event), "GameList 컬럼", "머리글을 끌어 순서를 바꿉니다", items);
  }

  /** 컬럼 경계를 끌어 폭을 바꾼다. 놓는 순간 저장한다. */
  function startColumnResize(id, event) {
    const startX = event.clientX;
    const startWidth = S.colWidths[id] || DEFAULT_COL_WIDTHS[id];
    document.body.style.cursor = "col-resize";

    const onMove = (e) => {
      S.colWidths[id] = Math.max(COL_MIN_WIDTH, startWidth + (e.clientX - startX));
      const template = gridTemplate();
      // 다시 그리지 않고 폭만 바꾼다 - 끄는 동안 목록 전체를 재생성하면 끊긴다.
      const head = $("list-head");
      if (head) head.style.gridTemplateColumns = template;
      document.querySelectorAll(".lrow").forEach((r) => {
        r.style.gridTemplateColumns = template;
      });
    };
    const onUp = () => {
      document.body.style.cursor = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      saveUiState();
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    event.preventDefault();
    event.stopPropagation();
  }

  const isCompare = () => !!S.compare;

  /** Compare는 **읽기 전용**이다(§54-59). 변경 동작의 문 앞마다 이걸 세운다.
   *
   * 화면에서 버튼을 숨기는 것만으로는 부족하다 - 단축키(Ctrl+V, Delete)와 내비
   * 드래그처럼 버튼을 거치지 않는 길이 있고, 그 길로 들어오면 비교 중인 상태에서
   * Plan이 바뀌거나(Auto Plan이 꺼져 있으면) 실제 파일까지 움직인다. */
  function blockedInCompare(what) {
    if (!isCompare()) return false;
    showToast(`Compare 중에는 ${what}할 수 없습니다. Exit Compare 후 진행하세요.`, "warning");
    return true;
  }

  function fetchRows(query) {
    if (isCompare()) return api.compareRows({ ...query, status: S.compareFilter });
    return isArchive() ? api.archiveRows(query) : api.listRows(S.activeId, query);
  }

  async function reloadList() {
    if (!S.activeId) { renderListWindow(); return; }
    const token = ++S.queryToken;
    const r = await fetchRows({ ...currentQuery(), limit: PAGE_SIZE, offset: 0 });
    if (!r.ok) { showToast(r.error, "error"); return; }
    if (token !== S.queryToken) return;   // 더 최신 요청이 있으면 버린다
    S.total = r.data.total;
    S.loadedPages.add(0);
    r.data.rows.forEach((row, i) => S.rowCache.set(i, row));
    const totalEl = $("filter-total");
    if (totalEl) totalEl.textContent = `${formatCount(S.total)} items`;
    renderListWindow();
    loadMatchCounts(r.data.rows, token);
  }

  /** Match 뱃지 개수는 목록 렌더링을 막지 않고 뒤따라 채운다(§49의 [n] 표시). */
  async function loadMatchCounts(rows, token) {
    // Compare 행은 좌우 어느 쪽 romUid인지가 정해져 있지 않고, 애초에 Archive Match와
    // 무관한 화면이다.
    if (isArchive() || isCompare() || !rows.length) return;
    const uids = rows.map((row) => row.romUid);
    const r = await api.matchCounts(S.activeId, uids);
    if (!r.ok || token !== S.queryToken) return;
    let changed = false;
    Object.entries(r.data || {}).forEach(([uid, count]) => {
      if (S.matchCounts[uid] !== count) { S.matchCounts[uid] = count; changed = true; }
    });
    if (changed) renderListWindow();
  }

  async function ensurePages(startIndex, endIndex) {
    const first = Math.floor(startIndex / PAGE_SIZE);
    const last = Math.floor(endIndex / PAGE_SIZE);
    const token = S.queryToken;
    for (let page = first; page <= last; page += 1) {
      if (page < 0 || S.loadedPages.has(page)) continue;
      S.loadedPages.add(page);
      const offset = page * PAGE_SIZE;
      const r = await fetchRows({ ...currentQuery(), limit: PAGE_SIZE, offset });
      if (!r.ok || token !== S.queryToken) { S.loadedPages.delete(page); continue; }
      r.data.rows.forEach((row, i) => S.rowCache.set(offset + i, row));
      renderListWindow();
      loadMatchCounts(r.data.rows, token);
    }
  }

  //: Compare 행의 기호(§56). +는 상대에만, -는 기준에만, △는 Metadata 충돌.
  const COMPARE_MARK = {
    only_b: ["add", "+", "상대 Collection에만 있음"],
    only_a: ["del", "−", "기준 Collection에만 있음"],
    conflict: ["warn", "△", "Metadata가 다름"],
  };

  function compareMark(row) {
    const mark = COMPARE_MARK[row.status];
    if (mark) {
      const [cls, glyph, title] = mark;
      return h("span", { class: "status-mark " + cls, title }, [glyph]);
    }
    if (row.mediaDiff) {
      return h("span", { class: "status-mark muted", title: "Media 구성이 다름" }, ["○"]);
    }
    return h("span", { class: "status-mark ok", title: "양쪽이 같음" }, [""]);
  }

  function statusMark(row) {
    // Plan 상태가 있으면 그것이 우선이다. 기호는 작게만 표시하고 제목이나 설명
    // 전체를 색칠하지 않는다(스펙 §24).
    const marks = (S.plan && S.plan.marks) || { rows: {}, systems: [] };
    const mark = marks.rows[`${row.system}|${row.file}`];
    if (mark === "+") return h("span", { class: "status-mark add", title: "추가 예정" }, ["+"]);
    if (mark === "-") return h("span", { class: "status-mark del", title: "삭제 예정" }, ["−"]);
    if ((marks.systems || []).includes(row.system)) {
      return h("span", { class: "status-mark warn", title: "Storage 이동 예정" }, ["△"]);
    }
    if (!row.present) return h("span", { class: "status-mark warn", title: "ROM 파일 없음 (metadata만 존재)" }, ["△"]);
    if (!row.hasMetadata) return h("span", { class: "status-mark muted", title: "Metadata 없음" }, ["·"]);
    if (!row.hasMedia) return h("span", { class: "status-mark muted", title: "Media 없음" }, ["·"]);
    return h("span", { class: "status-mark ok", title: "정상" }, [""]);
  }

  /** 카드 보기의 "어디까지 지었는가" 표식을 지운다. 다음에 카드로 오면 새로 짓는다. */
  function resetCardWindow(win) {
    delete win.dataset.cardToken;
    delete win.dataset.cardCount;
    if (cardObserver) { cardObserver.disconnect(); cardObserver = null; }
  }

  function renderListWindow() {
    const scroll = $("list-scroll"), spacer = $("list-spacer"), win = $("list-window");
    if (!scroll) return;

    // **여기서 `clear(win)`을 하면 안 된다.** 예전에는 카드 보기로 넘기기 전에 먼저
    // 지웠기 때문에, 카드 쪽에서 무엇을 하든 스크롤할 때마다 전부 다시 만들어졌다.
    // 지우는 것은 실제로 다시 지어야 하는 갈래에서만 한다.
    if (!activeDetail() || S.total === 0) {
      resetCardWindow(win);
      clear(win);
      spacer.style.height = "0px";
      win.style.transform = "";
      win.appendChild(h("div", { class: "empty-msg" }, [
        activeDetail() ? "조건에 맞는 게임이 없습니다."
                       : "등록된 Collection이 없습니다. 상단의 \"+\"를 눌러 추가하세요.",
      ]));
      return;
    }

    if (S.viewMode === "card" && !isCompare()) { renderCardWindow(scroll, spacer, win); return; }

    win.classList.remove("card-mode");
    resetCardWindow(win);
    // **가로 스크롤.** `#list-window`는 위치를 잡아 놓은(absolute) 요소라 폭이 스크롤
    // 컨테이너에 묶여 있었고, 컬럼 합(약 1,200px)이 그보다 넓어도 넘칠 자리가 없었다.
    // 넘칠 폭을 명시해야 스크롤할 것이 생긴다.
    const width = totalColumnWidth();
    win.style.minWidth = width + "px";
    spacer.style.width = width + "px";
    spacer.style.height = (S.total * ROW_HEIGHT) + "px";
    clear(win);

    const viewport = scroll.clientHeight || 600;
    const start = Math.max(0, Math.floor(scroll.scrollTop / ROW_HEIGHT) - OVERSCAN);
    const end = Math.min(S.total - 1, Math.ceil((scroll.scrollTop + viewport) / ROW_HEIGHT) + OVERSCAN);
    win.style.transform = `translateY(${start * ROW_HEIGHT}px)`;

    for (let i = start; i <= end; i += 1) {
      const row = S.rowCache.get(i);
      win.appendChild(row ? rowElement(row, i) : placeholderRow(i));
    }
    ensurePages(start, end);
  }

  /** 카드(격자) 보기.
   *
   * **이미 만든 카드는 다시 만들지 않는다.** 예전에는 이 함수가 매번 `clear(win)`으로
   * 전부 지우고 다시 지었다. 스크롤 이벤트가 rAF마다 이것을 부르므로, 스크롤할 때마다
   * 화면의 모든 카드가 사라졌다 다시 생기고 카드 수만큼 표지 이미지 요청이 다시
   * 나갔다 - 사용자가 본 "깜박이며 전부 다시 읽는" 증상의 정체다. 게임 하나를 고르는
   * 것도 마찬가지였다.
   *
   * 다시 지어야 하는 경우는 **행 집합 자체가 바뀐 때뿐**이다(Collection/System/검색/
   * 정렬). 그것은 `S.queryToken`이 말해 준다. 스크롤·선택·hover는 여기 해당하지 않는다.
   */
  function renderCardWindow(scroll, spacer, win) {
    spacer.style.height = "0px";
    spacer.style.width = "1px";
    win.style.transform = "";
    win.style.minWidth = "";
    win.classList.add("card-mode");

    const token = String(S.queryToken);
    if (win.dataset.cardToken !== token) {
      clear(win);
      win.dataset.cardToken = token;
      win.dataset.cardCount = "0";
      startCardObserver(scroll);
    }

    // 아직 도착하지 않은 페이지에서 멈춘다. 빈 자리를 만들어 두고 나중에 채우면
    // "그 자리에 무엇이 있었는지" 추적해야 하는데, 이어 붙이기만 하면 그럴 일이 없다.
    const loadedUpTo = S.loadedPages.size
      ? (Math.max(...S.loadedPages) + 1) * PAGE_SIZE
      : PAGE_SIZE;
    const renderCount = Math.min(S.total, loadedUpTo);
    let index = Number(win.dataset.cardCount || 0);
    for (; index < renderCount; index += 1) {
      const row = S.rowCache.get(index);
      if (!row) break;
      win.appendChild(cardElement(row, index));
    }
    win.dataset.cardCount = String(index);

    const nearBottom = scroll.scrollTop + scroll.clientHeight > scroll.scrollHeight - 300;
    if (index < S.total && (nearBottom || index === 0)) {
      ensurePages(index, Math.min(S.total - 1, index + PAGE_SIZE - 1));
    }
  }

  //: 화면에 들어온 카드만 표지를 불러오게 하는 관찰자. 카드 집합이 바뀔 때마다 새로
  //  만든다 - 예전 카드에 걸린 관찰은 그 카드와 함께 사라져야 한다.
  let cardObserver = null;

  function startCardObserver(scroll) {
    if (cardObserver) cardObserver.disconnect();
    const token = S.queryToken;
    cardObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        // 한 번 불러온 카드는 다시 관찰하지 않는다. 스크롤을 오르내려도 요청은
        // 카드당 한 번뿐이어야 한다.
        cardObserver.unobserve(entry.target);
        const img = entry.target.querySelector("img");
        // Archive의 식별자(romIdentityId)는 숫자가 아니다 - Number()로 바꾸면
        // NaN이 되어 이 조건이 항상 거짓이 되고, Archive Card 보기는 표지를
        // 아예 요청하지도 않았다. 문자열 그대로 쓴다.
        const romUid = entry.target.dataset.coverFor;
        if (img && romUid) loadCardCover(img, romUid, token);
      });
    }, {
      root: scroll,
      // 화면에 들어오기 전에 미리 받아 둔다 - 스크롤하다 빈 칸을 보지 않게.
      rootMargin: "300px",
    });
  }

  function cardElement(row, index) {
    const card = h("div", {
      class: "preview-card" + (S.selected.has(row.romUid) ? " selected" : "")
             + (S.focused === row.romUid ? " focused" : ""),
      // 선택 표시를 고칠 때 이 카드를 찾는 열쇠. 이것이 있어서 목록을 다시 짓지 않고
      // 클래스만 바꿀 수 있다.
      "data-rom-uid": String(row.romUid),
    });
    const cover = h("div", { class: "preview-cover" });
    if (row.hasMedia !== false) {
      cover.appendChild(h("img", { alt: row.title || row.file }));
      cover.dataset.coverFor = String(row.romUid);
      if (cardObserver) cardObserver.observe(cover);
    } else {
      // Media가 없다고 이미 아는 카드는 아예 묻지 않는다.
      cover.appendChild(icon("imageOff", 20));
    }
    card.appendChild(cover);
    card.appendChild(h("div", { class: "preview-title truncate", title: row.title || row.file },
                       [row.title || row.file]));
    card.addEventListener("click", (e) => handleRowClick(e, row, index));
    return card;
  }

  //: 이미 받아 온 표지. 같은 카드를 다시 그리거나 Collection을 오갈 때 브릿지를
  //  다시 거치지 않는다. 무한정 쌓이면 그것대로 문제이므로 최근 것만 남긴다.
  const COVER_CACHE_MAX = 800;

  /** 카드의 표지 그림. loadMediaImage()는 상세 패널(S.detailState) 것만 신경 쓰므로
   * 목록의 여러 행을 한꺼번에 그리는 카드 보기에는 쓸 수 없다 - romUid를 직접 받는다.
   *
   * Archive 항목은 조회 경로가 다르다(§ loadMediaImage와 같은 이유) - Collection용
   * 조회는 collection_id + rom_uid로 Cache를 뒤지는데 Archive 항목에는 그 둘 다
   * 없다(식별자가 romIdentityId다). 여기서도 구분 없이 Collection 경로를 불러서,
   * Archive Card 보기의 표지가 조용히 실패해 영영 안 보였다. */
  async function loadCardCover(img, romUid, token) {
    const key = `${S.activeId}|${romUid}`;
    if (S.coverCache.has(key)) { img.src = S.coverCache.get(key); return; }

    const r = isArchive()
      ? await api.getArchiveMediaImage(romUid, "Covers", true)
      : await api.getMediaImage(S.activeId, romUid, "Covers", true);
    if (!r.ok || !r.data) return;

    S.coverCache.set(key, r.data);
    if (S.coverCache.size > COVER_CACHE_MAX) {
      S.coverCache.delete(S.coverCache.keys().next().value);
    }
    // 그 사이에 다른 Collection이나 System으로 넘어갔으면 이 응답은 낡은 것이다.
    if (token === S.queryToken) img.src = r.data;
  }

  /** 선택/포커스 표시만 고친다. **목록을 다시 짓지 않는다.**
   *
   * 이전 프로젝트에서 같은 결론에 도달했던 부분이다 - 685개 카드에서 게임 하나를
   * 고를 때마다 전체를 다시 만들면 썸네일이 전부 다시 로드되고 스크롤 위치까지
   * 흔들린다. 실제로 바뀌는 것은 몇 개 요소의 클래스뿐이다.
   */
  function updateSelectionVisual() {
    const win = $("list-window");
    if (!win) return;
    win.querySelectorAll("[data-rom-uid]").forEach((el) => {
      const uid = Number(el.dataset.romUid);
      el.classList.toggle("selected", S.selected.has(uid));
      el.classList.toggle("focused", S.focused === uid);
    });
  }

  /** 아직 받지 않은 줄의 자리표시. **실제 행과 같은 컬럼 틀을 쓴다.**
   *
   * 예전엔 컬럼 폭 없이 칸 세 개만 넣어서, 스크롤하는 동안 그 줄들이 한 칸짜리 전체
   * 폭으로 그려졌다가 데이터가 오면 제 폭으로 돌아갔다(실사용 피드백: "스크롤 중 File
   * 쪽 넓이가 커졌다가 스크롤이 끝나면 원래 크기로 돌아온다"). */
  function placeholderRow(index) {
    if (isCompare()) {
      return h("div", { class: "lrow placeholder", style: { height: ROW_HEIGHT + "px" } }, [
        h("div", { class: "lc lc-index" }, [String(index + 1)]),
        h("div", { class: "lc lc-title" }, [h("span", { class: "skeleton" })]),
      ]);
    }
    return h("div", {
      class: "lrow placeholder",
      style: { height: ROW_HEIGHT + "px", gridTemplateColumns: gridTemplate() },
    }, visibleColumns().map((col) => h("div", { class: "lc lc-" + col.id },
      col.id === "no" ? [truncSpan(String(index + 1))]
        : (col.id === "file" || col.id === "title") ? [h("span", { class: "skeleton" })] : [])));
  }

  function compareRowElement(row, index) {
    const el = h("div", {
      class: "lrow compare-row" + (S.focused === row.key ? " focused" : "") + " s-" + row.status,
      style: { height: ROW_HEIGHT + "px" },
    });
    el.appendChild(h("div", { class: "lc lc-check" }));
    el.appendChild(h("div", { class: "lc lc-index" }, [String(index + 1)]));
    el.appendChild(h("div", { class: "lc lc-title" }, [
      systemIcon(row.system, 15),
      h("span", { class: "lrow-title truncate" }, [row.title || row.file]),
    ]));
    el.appendChild(h("div", { class: "lc lc-system" }, [
      h("span", { class: "sys-badge" }, [String(row.system).toUpperCase()])]));
    el.appendChild(h("div", { class: "lc lc-status" }, [compareMark(row)]));
    el.appendChild(h("div", { class: "lc lc-desc" }, [truncSpan(row.file)]));
    el.addEventListener("click", () => openCompareDetail(row));
    return el;
  }

  function rowElement(row, index) {
    if (isCompare()) return compareRowElement(row, index);
    const selected = S.selected.has(row.romUid);
    const el = h("div", {
      class: "lrow" + (selected ? " selected" : "") + (S.focused === row.romUid ? " focused" : ""),
      // 카드와 같은 열쇠. 선택이 바뀔 때 목록을 다시 짓지 않고 이 행만 고친다.
      "data-rom-uid": String(row.romUid),
      style: { height: ROW_HEIGHT + "px", gridTemplateColumns: gridTemplate() },
    });

    // No. - 화면에 보이는 순번이 아니라 목록 전체에서의 순번이다.
    // 칸은 id별로 만들어 두고, 마지막에 사용자가 정한 순서/표시대로 붙인다.
    const cells = {};
    cells.no = h("div", { class: "lc lc-no" }, [truncSpan(String(index + 1))]);
    // ROM 파일이 실제로 있으면 파일명을 제목과 같은 색으로, 없으면(메타데이터만) 흐리게.
    const missingRom = row.present === false;
    cells.file = h("div", {
      class: "lc lc-file " + (missingRom ? "rom-missing" : "rom-present"),
      title: missingRom ? `${row.file} - ROM 파일 없음` : row.file,
    }, [truncSpan(row.file)]);

    const titleCell = h("div", { class: "lc lc-title" }, [truncSpan(row.title || row.file)]);
    titleCell.title = row.title || row.file;
    // Exact로 확정되지 않은 후보가 있으면 개수만 조용히 알린다. 누르기 전까지는
    // 아무것도 일어나지 않는다(§49 - 자동 병합 금지).
    const matchCount = S.matchCounts[row.romUid];
    if (matchCount) {
      const badge = h("button", { class: "match-badge", title: "Match 후보 보기" },
        [`[${matchCount}]`]);
      badge.addEventListener("click", (e) => { e.stopPropagation(); openMatchDialog(row); });
      titleCell.appendChild(badge);
    }
    cells.title = titleCell;

    // Description이 가장 넓다. 목록만 훑어도 어떤 게임인지 알 수 있어야 한다.
    const desc = (row.desc || "").replace(/\s+/g, " ").trim();
    cells.desc = h("div", { class: "lc lc-desc", title: desc }, [truncSpan(desc)]);
    cells.region = h("div", { class: "lc lc-region" }, [truncSpan(row.region || "")]);
    cells.rating = h("div", { class: "lc lc-rating" }, [formatRating(row.rating)]);

    // 별표는 눌러서 바로 켜고 끈다. 상세 패널을 열지 않아도 되게.
    const star = h("button", {
      class: "fav-btn" + (row.favorite ? " on" : ""),
      title: row.favorite ? "즐겨찾기 해제" : "즐겨찾기",
    }, [row.favorite ? "★" : "☆"]);
    star.addEventListener("click", (e) => { e.stopPropagation(); toggleFavorite(row, star); });
    cells.fav = h("div", { class: "lc lc-fav" }, [star]);

    cells.genre = h("div", { class: "lc lc-genre", title: row.genre || "" },
                    [truncSpan(row.genre || "")]);
    cells.status = h("div", { class: "lc lc-status" }, [statusMark(row)]);
    visibleColumns().forEach((col) => el.appendChild(cells[col.id]));

    el.addEventListener("click", (e) => handleRowClick(e, row, index));
    el.addEventListener("contextmenu", (e) => { e.preventDefault(); openRowMenu(row, e); });
    return el;
  }

  // ------------------------------------------------------------------
  // 컨텍스트 메뉴 (게임 행 / System 공용)
  // ------------------------------------------------------------------
  let contextMenuCleanup = null;
  function closeContextMenu() { if (contextMenuCleanup) contextMenuCleanup(); }

  /** 마우스 위치에 메뉴를 띄운다.
   *
   * items: `{label, icon?, hint?, title?, danger?, disabled?, onSelect}`,
   * `{section: "제목"}`, 또는 `"separator"`. Esc·바깥 클릭·창 크기 변경으로 닫히고
   * ↑↓로 항목을 옮겨 Enter로 고른다. */
  function showContextMenu(point, title, subtitle, items, headTip) {
    closeContextMenu();
    const menu = h("div", { class: "ctx-menu", role: "menu" });
    if (title) {
      menu.appendChild(h("div", { class: "ctx-head", title: headTip || null }, [
        h("div", { class: "ctx-title" }, [title]),
        subtitle ? h("div", { class: "ctx-sub" }, [subtitle]) : null,
      ]));
    }
    const buttons = [];
    items.forEach((item) => {
      if (item === "separator") { menu.appendChild(h("div", { class: "ctx-sep", role: "separator" })); return; }
      if (item.section) { menu.appendChild(h("div", { class: "ctx-section" }, [item.section])); return; }
      const btn = h("button", {
        class: "ctx-item" + (item.danger ? " danger" : ""), role: "menuitem",
        disabled: !!item.disabled, title: item.title || null,
      }, [
        item.icon ? icon(item.icon, 12) : h("span", { class: "ctx-icon-gap" }),
        h("span", { class: "ctx-label" }, [item.label]),
        item.hint ? h("span", { class: "ctx-hint" }, [item.hint]) : null,
      ]);
      btn.addEventListener("click", () => { closeContextMenu(); item.onSelect(); });
      menu.appendChild(btn);
      if (!item.disabled) buttons.push(btn);
    });
    document.body.appendChild(menu);
    const rect = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(4, Math.min(point.x, window.innerWidth - rect.width - 4))}px`;
    menu.style.top = `${Math.max(4, Math.min(point.y, window.innerHeight - rect.height - 4))}px`;

    const onDown = (e) => { if (!menu.contains(e.target)) closeContextMenu(); };
    // 목록 단축키(↑↓, Esc)보다 먼저 받는다 - 메뉴가 떠 있는 동안에는 메뉴의 키다.
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeContextMenu(); return; }
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && buttons.length) {
        e.preventDefault();
        e.stopPropagation();
        const i = buttons.indexOf(document.activeElement);
        const next = e.key === "ArrowDown" ? (i + 1) % buttons.length : (i - 1 + buttons.length) % buttons.length;
        buttons[next].focus();
      }
    };
    const onLeave = () => closeContextMenu();
    setTimeout(() => document.addEventListener("mousedown", onDown, true), 0);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("blur", onLeave);
    window.addEventListener("resize", onLeave);
    contextMenuCleanup = () => {
      menu.remove();
      document.removeEventListener("mousedown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("blur", onLeave);
      window.removeEventListener("resize", onLeave);
      contextMenuCleanup = null;
    };
    if (buttons[0]) buttons[0].focus();
  }

  const menuPoint = (event) => (event
    ? { x: event.clientX, y: event.clientY }
    : { x: window.innerWidth / 2, y: window.innerHeight / 3 });

  function rowByUid(romUid) {
    for (const row of S.rowCache.values()) if (row && row.romUid === romUid) return row;
    return null;
  }

  async function copyTextToClipboard(text, message) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      // WebView에 따라 Clipboard API가 막혀 있다 - 예전 방식으로 한 번 더 시도한다.
      const area = h("textarea", { style: { position: "fixed", opacity: "0" } });
      area.value = text;
      document.body.appendChild(area);
      area.select();
      const copied = document.execCommand("copy");
      area.remove();
      if (!copied) { showToast("클립보드에 복사하지 못했습니다.", "error"); return; }
    }
    showToast(message || "복사했습니다.");
  }

  /** 게임 행 우클릭 메뉴.
   *
   * 예전엔 우클릭하자마자 삭제 확인이 떴다 - 삭제는 여러 동작 중 하나일 뿐인데
   * 오클릭 한 번이 곧바로 삭제 확인으로 이어졌다(사용자 요청). 이제는 메뉴를 먼저
   * 띄우고 삭제는 그 안의 한 항목이다. 선택한 여러 개 중 하나를 우클릭하면 선택
   * 전체가 대상이다(탐색기와 같다). */
  function openRowMenu(row, event) {
    if (!S.selected.has(row.romUid)) {
      S.selected = new Set([row.romUid]);
      S.selectAnchor = row.romUid;
      updateSelectionVisual();
      renderStatusBar();
    }
    const count = S.selected.size;
    const single = count === 1;
    const locked = isCompare();
    const files = [...S.selected].map((uid) => (rowByUid(uid) || {}).file).filter(Boolean);
    const star = document.querySelector(`.lrow[data-rom-uid="${row.romUid}"] .fav-btn, `
      + `.preview-card[data-rom-uid="${row.romUid}"] .fav-btn`);

    showContextMenu(menuPoint(event), single ? (row.title || row.file) : `${formatCount(count)}개 선택됨`,
      single ? row.file : null, [
        { label: "상세 보기", icon: "info", disabled: !single, onSelect: () => {
          openDetail(row);
          if (!S.previewOn) showToast("미리보기가 꺼져 있습니다 - Detail 윗줄의 미리보기를 켜세요.", "warning");
        } },
        { label: row.favorite ? "즐겨찾기 해제" : "즐겨찾기", icon: "star",
          disabled: !single || !star || isArchive() || locked, onSelect: () => toggleFavorite(row, star) },
        "separator",
        { label: "복사", icon: "copy", hint: "Ctrl+C", disabled: isArchive() || locked, onSelect: copySelectedRows },
        { label: "붙여넣기", icon: "upload", hint: "Ctrl+V", disabled: isArchive() || locked, onSelect: pasteClipboard },
        { label: single ? "파일명 복사" : `파일명 ${formatCount(files.length)}개 복사`, icon: "copy",
          disabled: !files.length,
          onSelect: () => copyTextToClipboard(files.join("\n"),
            files.length > 1 ? `파일명 ${formatCount(files.length)}개를 복사했습니다.` : "파일명을 복사했습니다.") },
        "separator",
        { label: "삭제", icon: "trash", hint: "Del", danger: true, disabled: locked, onSelect: deleteSelection },
      ]);
  }

  // ------------------------------------------------------------------
  // 목록 키보드 동작 - **화면에 그려진 행이 아니라 목록 전체가 대상이다.**
  // ------------------------------------------------------------------
  // 목록은 가상 스크롤이라 그려진 행은 수십 개뿐이다. ui/stitch-v2-redesign은 그 행들만
  // 보고 움직여서 큰 목록에서는 끝까지 가지 못했다. 위치는 가상 스크롤의 줄 번호로
  // 다루고, 아직 받지 않은 줄은 그 페이지를 받아 온다.

  async function rowAtIndex(index) {
    if (!S.rowCache.has(index)) await ensurePages(index, index);
    return S.rowCache.get(index) || null;
  }

  function scrollToIndex(index, romUid) {
    if (S.viewMode === "card") {
      const card = document.querySelector(`.preview-card[data-rom-uid="${romUid}"]`);
      if (card) card.scrollIntoView({ block: "nearest" });
      return;
    }
    const scroll = $("list-scroll");
    const top = index * ROW_HEIGHT;
    if (top < scroll.scrollTop) scroll.scrollTop = top;
    else if (top + ROW_HEIGHT > scroll.scrollTop + scroll.clientHeight) {
      scroll.scrollTop = top + ROW_HEIGHT - scroll.clientHeight;
    }
  }

  /** 한 줄을 골라 보여준다 - 그냥 클릭한 것과 같다. */
  function focusRowAt(index, row) {
    scrollToIndex(index, row.romUid);
    S.selected = new Set([row.romUid]);
    S.selectAnchor = row.romUid;
    renderStatusBar();
    openDetail(row);
  }

  /** ↑/↓ = 다음/이전 게임 선택(스크롤이 아니다). Shift를 누르면 기준점부터 범위로 넓힌다. */
  async function moveFocus(delta, extend) {
    if (isCompare() || !S.total) return;
    const current = S.focused == null ? -1 : indexOfRow(S.focused);
    const next = current < 0 ? (delta > 0 ? 0 : S.total - 1)
      : Math.max(0, Math.min(S.total - 1, current + delta));
    if (next === current) return;
    const row = await rowAtIndex(next);
    if (!row) return;
    if (!extend) { focusRowAt(next, row); return; }

    const anchorIndex = S.selectAnchor == null ? current : indexOfRow(S.selectAnchor);
    const [lo, hi] = anchorIndex < next ? [anchorIndex, next] : [next, anchorIndex];
    S.selected.clear();
    for (let i = Math.max(0, lo); i <= hi; i++) {
      const r = S.rowCache.get(i);
      if (r) S.selected.add(r.romUid);
    }
    S.focused = row.romUid;
    scrollToIndex(next, row.romUid);
    updateSelectionVisual();
    renderStatusBar();
  }

  /** 영문/숫자 키 = 그 글자로 시작하는 다음 파일로. 같은 키를 다시 누르면 그다음으로,
   * 끝까지 가면 처음부터 다시 찾는다(탐색기와 같다). */
  async function jumpToLetter(key) {
    if (isCompare() || !S.total) return;
    const after = S.focused == null ? -1 : indexOfRow(S.focused);
    let index = -1;
    if (isArchive()) {
      // Archive 목록은 백엔드 검색이 없다 - 받아 둔 줄에서 찾는다.
      const needle = key.toLowerCase();
      for (let k = 1; k <= S.total; k++) {
        const i = (after + k) % S.total;
        const r = S.rowCache.get(i);
        if (r && String(r.file || "").toLowerCase().startsWith(needle)) { index = i; break; }
      }
    } else {
      const r = await api.findRowIndex(S.activeId, currentQuery(), key, after);
      if (!r.ok) { showToast(r.error, "error"); return; }
      index = r.data;
    }
    if (index < 0) { showToast(`'${key.toUpperCase()}'(으)로 시작하는 파일이 없습니다.`); return; }
    const row = await rowAtIndex(index);
    if (row) focusRowAt(index, row);
  }

  /** Ctrl+A = 지금 목록(필터·정렬 그대로) 전체 선택. */
  async function selectAllRows() {
    if (isCompare() || !S.total) return;
    if (isArchive()) { showToast("Archive에서는 전체 선택을 아직 지원하지 않습니다.", "warning"); return; }
    const r = await api.listUids(S.activeId, currentQuery());
    if (!r.ok) { showToast(r.error, "error"); return; }
    S.selected = new Set(r.data);
    updateSelectionVisual();
    renderStatusBar();
    showToast(`${formatCount(S.selected.size)}개를 선택했습니다.`);
  }

  /** rating은 0~5로 들어온다. 이전 프로젝트처럼 한 자리로만 보여준다. */
  function formatRating(value) {
    const n = parseFloat(value);
    return Number.isFinite(n) && n > 0 ? n.toFixed(1) : "";
  }

  async function toggleFavorite(row, button) {
    if (blockedInCompare("즐겨찾기를 변경")) return;
    if (isArchive()) return;
    const next = !row.favorite;
    // 눌린 것이 바로 보이게 먼저 바꾸고, 실패하면 되돌린다.
    row.favorite = next;
    button.textContent = next ? "★" : "☆";
    button.classList.toggle("on", next);

    const r = await api.setFavorite(S.activeId, row.romUid, next);
    if (!r.ok) {
      row.favorite = !next;
      button.textContent = row.favorite ? "★" : "☆";
      button.classList.toggle("on", row.favorite);
      showToast(r.error, "error");
      return;
    }
    // 즐겨찾기만 보는 중이었다면 방금 해제한 항목은 목록에서 빠져야 한다.
    if (S.favoritesOnly && !next) { resetList(); await reloadList(); }
  }

  /** 행 클릭. **탐색기와 같은 규칙으로 고른다.**
   *
   *   그냥 클릭      - 이 항목 하나만. 상세 패널이 열린다.
   *   Ctrl+클릭      - 이 항목을 선택에 넣거나 뺀다.
   *   Shift+클릭     - 기준점부터 여기까지를 선택으로 대체한다.
   *   Ctrl+Shift+클릭 - 기준점부터 여기까지를 기존 선택에 더한다.
   *
   * 체크박스를 없앤 이유가 여기 있다 - 수천 개 목록에서 체크박스를 하나씩 누르는 것은
   * 실제로 쓸 수 있는 방법이 아니다.
   */
  function handleRowClick(event, row, index) {
    const additive = event.ctrlKey || event.metaKey;
    if (event.shiftKey) {
      const anchor = S.selectAnchor;
      const anchorIndex = anchor == null ? -1 : indexOfRow(anchor);
      if (anchorIndex >= 0) {
        const [lo, hi] = anchorIndex < index ? [anchorIndex, index] : [index, anchorIndex];
        if (!additive) S.selected.clear();
        for (let i = lo; i <= hi; i++) {
          const r = S.rowCache.get(i);
          if (r) S.selected.add(r.romUid);
        }
      } else {
        S.selected = new Set([row.romUid]);
        S.selectAnchor = row.romUid;
      }
      updateSelectionVisual();
      renderStatusBar();
      return;
    }
    if (additive) {
      if (S.selected.has(row.romUid)) S.selected.delete(row.romUid);
      else S.selected.add(row.romUid);
      S.selectAnchor = row.romUid;
      updateSelectionVisual();
      renderStatusBar();
      return;
    }
    S.selected = new Set([row.romUid]);
    S.selectAnchor = row.romUid;
    renderStatusBar();
    openDetail(row);
  }

  /** 캐시에 들어온 행 중에서 그 romUid의 위치. Shift 범위 선택의 기준점 계산용. */
  function indexOfRow(romUid) {
    for (const [index, row] of S.rowCache.entries()) {
      if (row && row.romUid === romUid) return index;
    }
    return -1;
  }

  /** ROM 목록만으로 gamelist를 만든다. **사용자가 직접 부를 때만 뜬다.**
   *
   * 예전에는 Collection을 추가하는 길목에서 자동으로 물었다. 그런데 ROM만 있는
   * Collection은 그 자체로 정상이고, 만들자마자 "메타데이터가 없습니다"가 뜨면
   * 사용자는 무언가 잘못한 것처럼 느낀다. 게다가 ROM 폴더를 따로 준 System 때문에
   * 정상적인 ES-DE 폴더에서도 이 창이 잘못 떴다.
   *
   * 만들지 않아도 Collection은 열린다 - 그때는 Gamelist에 파일명이 제목 자리에 뜨고,
   * 사용자가 항목을 고쳐 저장하는 순간 gamelist.xml이 만들어진다. 미리 만드는 것은
   * 이후 작업(Export/Convert/Archive 수집)을 자연스럽게 하기 위한 선택지일 뿐이다.
   */
  async function openMetadataBootstrap(collectionId, scopeSystems) {
    const status = await api.metadataStatus(collectionId);
    if (!status.ok) { showToast(status.error, "error"); return; }
    // scopeSystems가 있으면 System 하나 또는 한 Storage에 속한 System들로 좁힌다
    // (§ Navigator의 System/Storage 우클릭 메뉴). 없으면 Collection 전체다.
    const missing = scopeSystems
      ? status.data.missing.filter((s) => scopeSystems.includes(s))
      : status.data.missing;
    if (!missing.length) {
      showToast(scopeSystems ? "이미 gamelist가 있습니다." : "모든 System에 gamelist가 있습니다.");
      return;
    }

    const roms = status.data.systems
      .filter((s) => missing.includes(s.system))
      .reduce((sum, s) => sum + s.roms, 0);

    await new Promise((done) => {
      const body = h("div", { class: "modal-body" }, [
        h("div", { class: "modal-text" }, [
          `메타데이터(gamelist.xml)가 없는 System이 ${formatCount(missing.length)}개 있습니다.`,
        ]),
        h("div", { class: "modal-hint" }, [
          `ROM ${formatCount(roms)}개의 파일명만 담은 gamelist를 지금 만들 수 있습니다. `
          + "제목은 파일명 그대로 들어가고 나머지 항목은 비워 둡니다 - 추측해서 채우지 않습니다.",
        ]),
        h("div", { class: "modal-hint" }, [
          `대상: ${missing.slice(0, 8).join(", ")}${missing.length > 8 ? " …" : ""}`,
        ]),
      ]);
      showModal("gamelist 만들기", body, [
        h("button", { class: "btn", onClick: () => { closeModal(); done(); } }, ["나중에"]),
        h("button", { class: "btn primary", onClick: async () => {
          closeModal();
          const made = await api.generateMetadata(collectionId, missing);
          if (!made.ok) { showToast(made.error, "error"); done(); return; }
          const games = (made.data.created || []).reduce((sum, c) => sum + c.games, 0);
          showToast(`${formatCount(made.data.created.length)}개 System에 `
                    + `${formatCount(games)}개 항목의 gamelist를 만들었습니다.`);
          done();
        } }, ["gamelist 만들기"]),
      ]);
    });
  }

  // ------------------------------------------------------------------
  // Convert (스펙 §53)
  // ------------------------------------------------------------------
  /** 변환 대상 고르기 -> 미리보기 -> Plan. 원본 Collection은 건드리지 않는다. */
  async function openConvert(source) {
    const targets = S.collections.filter((c) => c.id !== source.id);
    if (!targets.length) {
      showToast("변환해 넣을 다른 Collection이 없습니다. 먼저 추가하세요.", "warning");
      return;
    }

    const select = h("select", { class: "field-input" },
      targets.map((c) => h("option", { value: c.id }, [`${c.name} (${c.frontendLabel})`])));
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [`${source.name}의 내용을 다른 Collection으로 변환합니다.`]),
      h("div", { class: "field-label" }, ["대상 Collection"]),
      select,
      h("div", { class: "modal-hint" },
        ["원본은 그대로 둡니다. 변환 결과는 Plan에 올라가고, Apply를 눌러야 실제로 반영됩니다."]),
    ]);

    showModal("Convert", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary", onClick: () => {
        const targetId = select.value;
        closeModal();
        showConvertPreview(source.id, targetId);
      } }, ["다음"]),
    ]);
  }

  /** 실행 전에 무엇을 잃는지 보여준다 - Frontend 간 변환은 반드시 무언가를 잃는다(§50-51). */
  async function showConvertPreview(sourceId, targetId) {
    const r = await api.convertPreview(sourceId, targetId);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const d = r.data;

    const body = h("div", { class: "modal-body" });
    body.appendChild(h("div", { class: "convert-head" }, [
      h("span", { class: "truncate" }, [`${d.sourceName} (${d.sourceFrontend})`]),
      h("span", { class: "convert-arrow" }, ["→"]),
      h("span", { class: "truncate" }, [`${d.targetName} (${d.targetFrontend})`]),
    ]));

    const table = h("div", { class: "convert-table" });
    const line = (label, value, cls, hint) => {
      const row = h("div", { class: "convert-row" + (cls ? " " + cls : "") },
                    [h("span", { class: "convert-label" }, [label]),
                     h("span", { class: "convert-value" }, [formatCount(value)])]);
      if (hint) row.setAttribute("title", hint);
      table.appendChild(row);
    };
    line("Games", d.games);
    line("Metadata", d.metadata);
    line("Media", d.media);
    body.appendChild(table);

    // 잃는 것은 따로 묶어서, 넘어가는 숫자와 섞이지 않게 한다.
    const losses = h("div", { class: "convert-table convert-losses" });
    const lossLine = (label, value, hint) => {
      const row = h("div", { class: "convert-row" + (value ? " lossy" : "") }, [
        h("span", { class: "convert-label" }, [label]),
        h("span", { class: "convert-value" }, [formatCount(value)]),
      ]);
      if (hint) row.setAttribute("title", hint);
      losses.appendChild(row);
    };
    lossLine("Unsupported fields", d.unsupportedFields,
             (d.unsupportedFieldNames || []).length
               ? `${d.targetFrontend} 포맷에 자리가 없는 필드: ${d.unsupportedFieldNames.join(", ")}`
               : "대상 포맷이 담지 못하는 공통 필드 값의 개수");
    lossLine("Unsupported media", d.droppedMedia,
             `${d.targetFrontend}가 다루지 않는 media 종류`);
    lossLine("Frontend-specific", d.frontendSpecific,
             "원본 Frontend 고유 값 - 다른 Frontend로는 넘어가지 않습니다");
    body.appendChild(losses);

    if (d.unsupportedFields || d.droppedMedia || d.frontendSpecific) {
      body.appendChild(h("div", { class: "modal-hint" },
        ["표시된 값은 이번 변환에서 대상에 남지 않습니다. 원본 Collection은 그대로 유지됩니다."]));
    }

    showModal("Convert 미리보기", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary", onClick: async () => {
        closeModal();
        const result = await api.startConvert(sourceId, targetId);
        if (!result.ok) { showToast(result.error, "error"); return; }
        const added = result.data.added || 0;
        const skipped = (result.data.skipped || []).length;
        // 대상 Collection의 Plan에 올라갔으므로 그쪽으로 데려간다 - 아니면 사용자는
        // 아무 일도 안 일어난 것처럼 느낀다.
        await openTab(targetId);
        await refreshPlan();
        renderAll();
        showToast(`${formatCount(added)}개를 Plan에 올렸습니다`
                  + (skipped ? ` (원본이 없어 ${skipped}개 제외)` : "")
                  + ". Apply를 눌러야 실제로 반영됩니다.");
      } }, ["Plan에 올리기"]),
    ]);
  }

  // ------------------------------------------------------------------
  // Compare Mode (스펙 §54-59)
  // ------------------------------------------------------------------
  async function runCompare(baseId, otherId) {
    const r = await api.startCompare(baseId, otherId);
    if (!r.ok) { showToast(r.error, "error"); return; }
    S.compare = r.data;
    S.compareBase = null;
    S.compareFilter = "all";
    // Compare는 Gamelist를 통째로 바꾼다. 이전 선택/상세는 다른 세계의 것이므로 버린다.
    resetList();
    renderAll();
    await reloadList();
  }

  async function exitCompare() {
    await api.exitCompare();
    S.compare = null;
    S.compareBase = null;
    resetList();
    renderAll();
    await reloadList();
  }

  /** 좌우를 나란히 놓고 다른 값만 표시를 달리한다(§57). */
  async function openCompareDetail(row) {
    S.focused = row.key;
    renderListWindow();
    const r = await api.compareDetail(row.key);
    if (!r.ok) { showToast(r.error, "error"); return; }
    S.detailState = { compare: r.data, tab: "metadata" };
    renderDetailPanel();
  }

  function renderCompareDetail(panel) {
    const d = S.detailState.compare;
    const inner = h("div", { id: "detail-panel-inner" });
    panel.appendChild(inner);

    const header = h("div", { class: "detail-header" }, [
      h("div", { style: { minWidth: "0", flex: "1" } }, [
        h("div", { class: "detail-eyebrow" }, ["COMPARE"]),
        h("div", { class: "detail-filename" }, [d.file]),
        h("div", { class: "detail-system" }, [systemIcon(d.system, 13), String(d.system).toUpperCase()]),
      ]),
    ]);
    const close = h("button", { class: "icon-btn", title: "닫기 (Esc)" }, [icon("x", 13)]);
    close.addEventListener("click", closeDetail);
    header.appendChild(close);
    inner.appendChild(header);

    const body = h("div", { class: "detail-body" });

    // 어느 쪽에 있는지부터 알려준다 - 한쪽에만 있으면 값 비교 자체가 의미 없다.
    body.appendChild(h("div", { class: "cmp-sides" }, [
      h("div", { class: "cmp-side-name" + (d.left ? "" : " absent") },
        [d.baseName, h("span", { class: "cmp-side-mark" }, [d.left ? "" : " (없음)"])]),
      h("div", { class: "cmp-side-name" + (d.right ? "" : " absent") },
        [d.otherName, h("span", { class: "cmp-side-mark" }, [d.right ? "" : " (없음)"])]),
    ]));

    // 같은 이름인데 크기가 다르면 다른 덤프일 수 있다 - 값 비교보다 먼저 알아야 한다.
    // (크기는 Cache에 이미 있으므로 파일을 다시 읽지 않는다. SHA256 비교는 별건이다.)
    const identity = h("div", { class: "cmp-table cmp-identity" });
    [["File", "filename", (v) => v || "-"],
     ["Size", "size", (v) => (v ? formatBytes(v) : "-")]].forEach(([label, key, fmt]) => {
      const left = (d.left || {})[key];
      const right = (d.right || {})[key];
      const differs = !!d.left && !!d.right && left !== right;
      const line = h("div", { class: "cmp-row" + (differs ? " changed" : "") });
      line.appendChild(h("div", { class: "cmp-label" }, [label]));
      line.appendChild(h("div", { class: "cmp-value" }, [d.left ? fmt(left) : "-"]));
      line.appendChild(h("div", { class: "cmp-value" }, [d.right ? fmt(right) : "-"]));
      identity.appendChild(line);
    });
    body.appendChild(identity);

    const rows = [
      ["Title", "name"], ["Description", "desc"], ["Genre", "genre"],
      ["Developer", "developer"], ["Publisher", "publisher"], ["Release", "releasedate"],
      ["Region", "region"], ["Players", "players"], ["Rating", "rating"],
    ];
    const changed = new Set(d.changedFields || []);
    const table = h("div", { class: "cmp-table" });
    rows.forEach(([label, key]) => {
      const left = ((d.left || {}).fields || {})[key] || "";
      const right = ((d.right || {}).fields || {})[key] || "";
      if (!left && !right) return;
      const line = h("div", { class: "cmp-row" + (changed.has(key) ? " changed" : "") });
      line.appendChild(h("div", { class: "cmp-label" }, [label]));
      line.appendChild(h("div", { class: "cmp-value" }, [left || "-"]));
      line.appendChild(h("div", { class: "cmp-value" }, [right || "-"]));
      table.appendChild(line);
    });
    body.appendChild(table);

    if (d.mediaDiff) {
      body.appendChild(h("div", { class: "cmp-media-note" }, [
        icon("image", 12),
        h("span", {}, [`Media 구성이 다릅니다 - ${((d.left || {}).mediaTypes || []).join(", ") || "없음"}`
                       + ` \u2194 ${((d.right || {}).mediaTypes || []).join(", ") || "없음"}`]),
      ]));
    }
    inner.appendChild(body);
  }

  // ------------------------------------------------------------------
  // Match (스펙 §45-49)
  // ------------------------------------------------------------------
  const TIER_LABEL = { exact: "정확", normalized: "이름 일치", metadata: "메타데이터",
                       heuristic: "유사", manual: "수동 연결" };

  /** 후보 목록. 고르기 전까지 아무것도 반영되지 않는다 - 그것이 이 화면의 요점이다. */
  async function openMatchDialog(row) {
    const r = await api.matchCandidates(S.activeId, row.romUid);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const data = r.data;

    let chosen = data.linkedRomIdentityId || null;
    const list = h("div", { class: "match-list" });

    if (!data.candidates.length) {
      list.appendChild(h("div", { class: "empty-msg" }, ["후보를 찾지 못했습니다."]));
    }
    data.candidates.forEach((candidate) => {
      const option = h("button", {
        class: "match-option" + (candidate.romIdentityId === chosen ? " chosen" : ""),
      });
      option.appendChild(h("span", { class: "match-radio" }, [
        candidate.romIdentityId === chosen ? "◉" : "○"]));
      const main = h("div", { class: "match-option-main" }, [
        h("div", { class: "match-option-title truncate" }, [candidate.title || candidate.filename]),
        h("div", { class: "match-option-sub truncate" }, [
          candidate.filename,
          candidate.region ? ` · ${candidate.region}` : "",
          candidate.size ? ` · ${formatBytes(candidate.size)}` : "",
        ]),
      ]);
      // 점수만 보여주면 "왜 이게 후보인지"에 답하지 못한다 - 무엇이 일치해서 올라온
      // 것인지 함께 적는다.
      if (candidate.evidence && candidate.evidence.length) {
        main.appendChild(h("div", { class: "match-option-why truncate" },
          [candidate.evidence.join(" · ")]));
      }
      option.appendChild(main);
      option.appendChild(h("span", { class: "match-tier tier-" + candidate.tier },
        [TIER_LABEL[candidate.tier] || candidate.tier]));
      option.appendChild(h("span", { class: "match-score" }, [`${Math.round(candidate.score)}%`]));
      option.addEventListener("click", () => {
        chosen = candidate.romIdentityId;
        list.querySelectorAll(".match-option").forEach((el, i) => {
          const isChosen = data.candidates[i].romIdentityId === chosen;
          el.classList.toggle("chosen", isChosen);
          el.querySelector(".match-radio").textContent = isChosen ? "◉" : "○";
        });
        applyBtn.disabled = false;
      });
      list.appendChild(option);
    });

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "match-source" }, [
        h("span", { class: "match-source-label" }, ["Source"]),
        h("span", { class: "truncate" }, [data.source.title || data.source.filename]),
      ]),
      h("div", { class: "field-label" }, ["Candidates"]),
      list,
      h("div", { class: "modal-hint" },
        ["점수는 추천 순서일 뿐입니다. 어느 것도 자동으로 반영되지 않습니다."]),
    ]);

    const applyBtn = h("button", { class: "btn primary", disabled: !chosen }, ["Apply Match"]);
    applyBtn.addEventListener("click", async () => {
      closeModal();
      const applied = await api.applyMatch(S.activeId, row.romUid, chosen);
      if (!applied.ok) { showToast(applied.error, "error"); return; }
      delete S.matchCounts[row.romUid];
      renderListWindow();
      showToast("Match를 확정했습니다. Archive에서 값을 가져오려면 Archive → Collection을 실행하세요.");
    });

    const actions = [h("button", { class: "btn", onClick: closeModal }, ["Cancel"])];
    if (data.linkedRomIdentityId) {
      const unlink = h("button", { class: "btn danger" }, ["Match 해제"]);
      unlink.addEventListener("click", async () => {
        closeModal();
        const cleared = await api.clearMatch(S.activeId, row.romUid);
        if (!cleared.ok) { showToast(cleared.error, "error"); return; }
        await reloadList();
        showToast("Match를 해제했습니다.");
      });
      actions.push(unlink);
    }
    actions.push(applyBtn);
    showModal("Possible Matches", body, actions);
  }

  // ------------------------------------------------------------------
  // 우측 상세 패널 (이전 프로젝트 구성을 유지 - 스펙 §34~36)
  // ------------------------------------------------------------------
  const fieldRefs = {};

  async function openDetail(row) {
    S.focused = row.romUid;
    updateSelectionVisual();
    // 미리보기를 꺼 둔 상태에서는 고르기만 하고 패널을 열지 않는다(탐색기와 같다).
    if (!S.previewOn) return;
    const tab = (S.detailState && S.detailState.tab) || "metadata";

    if (isArchive()) {
      const r = await api.archiveDetail(row.romIdentityId);
      if (!r.ok || !r.data) { showToast(r.error || "항목을 찾을 수 없습니다.", "error"); return; }
      const d = r.data;
      S.detailState = {
        archive: true, romUid: d.romIdentityId, romIdentityId: d.romIdentityId,
        system: d.system, file: d.filename, fields: d.fields, size: d.size,
        present: true, sha256: d.sha256, sources: d.sources,
        media: (d.media || []).reduce((acc, m) => {
          acc[MEDIA_LABEL[m.media_type] || m.media_type] = "pending"; return acc;
        }, {}),
        tab, draft: null,
      };
      renderDetailPanel();
      renderStatusBar();
      return;
    }

    const r = await api.getRow(S.activeId, row.romUid);
    if (!r.ok) { showToast(r.error, "error"); return; }
    S.detailState = { ...r.data, tab, draft: null };
    renderDetailPanel();
    renderStatusBar();
  }

  function closeDetail() {
    S.detailState = null;
    S.focused = null;
    renderDetailPanel();
    updateSelectionVisual();
  }

  function captureDraft() {
    if (!S.detailState) return;
    S.detailState.draft = S.detailState.draft || {};
    Object.keys(fieldRefs).forEach((k) => { if (fieldRefs[k]) S.detailState.draft[k] = fieldRefs[k].value; });
  }

  /** 상세 패널의 별표. 목록의 별표와 같은 곳을 가리켜야 한다. */
  async function toggleFavoriteFromDetail(button) {
    const state = S.detailState;
    if (!state || blockedInCompare("즐겨찾기를 변경")) return;
    const next = !state.favorite;
    state.favorite = next;
    button.textContent = next ? "★" : "☆";
    button.classList.toggle("on", next);

    const r = await api.setFavorite(S.activeId, state.romUid, next);
    if (!r.ok) {
      state.favorite = !next;
      button.textContent = state.favorite ? "★" : "☆";
      button.classList.toggle("on", state.favorite);
      showToast(r.error, "error");
      return;
    }
    // 목록의 별표도 같이 바뀌어야 한다 - 둘이 다르면 어느 쪽이 맞는지 알 수 없다.
    for (const row of S.rowCache.values()) {
      if (row && row.romUid === state.romUid) row.favorite = next;
    }
    renderListWindow();
  }

  /** Detail 윗줄(#detail-top). GameList 상단 줄과 같은 높이라서, 아랫줄
   * #detail-panel의 제목이 GameList의 Toolbar와 같은 선에서 시작한다(레이아웃
   * 재검토 §18). 게임을 선택했든 안 했든, Compare 중이든, Preview가 켜져 있든
   * 꺼져 있든 늘 같은 자리에 같은 것을 보여준다 - Archive 이동(왼쪽)과 Preview
   * 토글(오른쪽)이다. Preview를 꺼도 **이 줄은 그대로 남는다** - 이 줄까지
   * 사라지면 다시 켤 방법이 없다.
   */
  function renderDetailTopSpace() {
    const bar = h("div", { class: "detail-topspace" });

    if (isCompare()) {
      // 비교 중에는 Archive 이동을 안 내놓는다 - 눌리면 비교 화면에서 그대로
      // 변경이 일어난다(renderStatusBar의 예전 sb-actions와 같은 이유).
      bar.appendChild(h("span", { class: "sb-badge" }, ["읽기 전용"]));
    } else if (isArchive()) {
      const targets = S.tabs.filter((t) => t !== ARCHIVE_ID);
      // 못 쓰는 버튼은 **왜 못 쓰는지 말해야 한다.**
      const why = !targets.length ? "보낼 Collection을 먼저 열어주세요"
                : !S.selected.size ? "보낼 항목을 먼저 고르세요"
                : "선택 항목을 Collection으로 보냅니다";
      const send = h("button", {
        class: "btn compact primary", id: "archive-send-btn",
        disabled: !S.selected.size || !targets.length, title: why,
      }, ["Collection으로 보내기"]);
      // updateSelectionDependentActions()도 이 버튼을 onclick으로 다시
      // 잡는다 - addEventListener를 섞으면 두 번 실행될 수 있어 여기도
      // onclick으로 통일한다.
      if (S.selected.size && targets.length) send.onclick = openSendToCollection;
      bar.appendChild(send);
    } else {
      const scope = archiveScope();
      const scopeLabel = archiveScopeLabel(scope);
      const ingest = h("button", { class: "btn compact", id: "archive-ingest-btn",
        "data-scope": scope.kind,
        title: `${scopeLabel}을 Archive에 수집합니다` },
        [icon("database", 12), h("span", { class: "ingest-label truncate" }, [`Archive에 수집 — ${scopeLabel}`])]);
      ingest.addEventListener("click", ingestToArchive);
      bar.appendChild(ingest);
    }

    // 아이콘과 "미리보기" 글자를 합친 전체가 누르는 자리다(사용자 요청). 클릭은
    // 이 바깥 상자 하나에만 건다 - 안쪽 아이콘 버튼에도 걸면 한 번 눌러 두 번 토글된다.
    const previewToggle = h("div", {
      class: "detail-preview-toggle",
      title: S.previewOn ? "미리보기 끄기" : "미리보기 켜기",
    });
    previewToggle.appendChild(h("button", {
      class: "icon-btn" + (S.previewOn ? " on" : ""),
      title: S.previewOn ? "미리보기 끄기" : "미리보기 켜기",
    }, [icon("previewPane", 15)]));
    previewToggle.appendChild(h("span", { class: "detail-preview-label" }, ["미리보기"]));
    previewToggle.addEventListener("click", () => {
      S.previewOn = !S.previewOn;
      saveUiState();
      renderDetailPanel();
    });
    bar.appendChild(previewToggle);

    return bar;
  }

  function renderDetailPanel() {
    const top = $("detail-top");
    clear(top);
    top.appendChild(renderDetailTopSpace());

    const panel = $("detail-panel");
    clear(panel);
    // Preview를 끄면 **아랫줄의 Detail 내용 기둥만** 뺀다. 윗줄(#detail-top)은
    // 남으므로 다시 켤 토글이 사라지지 않고, 빠진 폭은 목록이 쓴다(사용자 요청 -
    // 예전엔 패널 전체 폭을 44px로 접어 윗줄의 GameList 헤더까지 재배치됐고, 그
    // 전엔 폭을 그대로 둬서 목록이 전혀 넓어지지 않았다).
    panel.classList.toggle("off", !S.previewOn);
    if (!S.previewOn) {
      panel.classList.remove("open");
      return;
    }
    const state = S.detailState;
    panel.classList.toggle("open", !!state);
    if (!state) {
      // 패널이 늘 자리를 차지하므로 빈 칸을 그냥 두지 않는다.
      panel.appendChild(h("div", { id: "detail-panel-inner" }, [
        h("div", { class: "panel-empty-state" }, [
          icon("gamepad", 22),
          h("div", { class: "panel-empty-msg" }, ["게임을 선택하면 여기에 표시됩니다"]),
        ]),
      ]));
      return;
    }

    if (state.compare) { renderCompareDetail(panel); return; }

    const inner = h("div", { id: "detail-panel-inner" });
    panel.appendChild(inner);

    const header = h("div", { class: "detail-header" }, [
      h("div", { style: { minWidth: "0", flex: "1" } }, [
        h("div", { class: "detail-eyebrow" }, ["METADATA"]),
        h("div", { class: "detail-filename-row" }, [
          h("div", { class: "detail-filename", title: state.file }, [state.file]),
          h("button", {
            class: "icon-btn detail-copy", title: "파일명 복사",
            onClick: () => copyTextToClipboard(state.file, "파일명을 복사했습니다."),
          }, [icon("copy", 11)]),
        ]),
        h("div", { class: "detail-system" }, [systemIcon(state.system, 13), String(state.system).toUpperCase()]),
      ]),
    ]);

    if (!state.archive) {
      // Play/Favorite는 게임을 보고 있을 때 바로 손이 가는 자리에 있어야
      // 한다(레이아웃 재검토 §20). Preview는 더 이상 여기 없다 -
      // .detail-topspace로 옮겼다.
      //
      // 실행은 아직 연결되지 않았다. **버튼을 없애는 대신 못 한다고 말한다** -
      // 사라진 기능은 언제 돌아오는지 알 수 없지만, 눌러서 안내를 받으면 안다.
      const play = h("button", {
        class: "icon-btn", title: state.present ? "실행 (RetroArch 연동 예정)" : "ROM 파일이 없습니다",
        disabled: !state.present,
      }, [icon("play", 14)]);
      if (state.present) {
        play.addEventListener("click", () => showToast(
          "RetroArch 연동은 다음 버전에서 들어옵니다.", "warning"));
      }
      header.appendChild(play);

      const star = h("button", {
        class: "icon-btn fav-btn" + (state.favorite ? " on" : ""),
        title: state.favorite ? "즐겨찾기 해제" : "즐겨찾기",
      }, [state.favorite ? "★" : "☆"]);
      star.addEventListener("click", () => toggleFavoriteFromDetail(star));
      header.appendChild(star);
    }
    inner.appendChild(header);

    const tabs = h("div", { class: "detail-tabs" });
    const tabDefs = state.archive
      ? [["metadata", "Metadata"], ["media", "Media"], ["sources", "Revision"]]
      : [["metadata", "Metadata"], ["media", "Media"], ["rom", "ROM"]];
    tabDefs.forEach(([key, label]) => {
      const tab = h("button", { class: "detail-tab" + (state.tab === key ? " active" : "") }, [label]);
      tab.addEventListener("click", () => { captureDraft(); state.tab = key; renderDetailPanel(); });
      tabs.appendChild(tab);
    });
    inner.appendChild(tabs);

    const body = h("div", { class: "detail-body" });
    if (state.tab === "metadata") renderMetadataTab(body);
    else if (state.tab === "media") renderMediaTab(body);
    else if (state.tab === "sources") renderSourcesTab(body);
    else renderRomTab(body);
    inner.appendChild(body);

    if (state.tab === "metadata") {
      const footer = h("div", { class: "detail-footer" });
      const save = h("button", { class: "btn primary w-full" },
        [icon("save", 13), h("span", {}, ["저장 (Ctrl+S)"])]);
      save.addEventListener("click", handleSaveDetail);
      footer.appendChild(save);
      inner.appendChild(footer);
    }
  }

  function fieldGroup(iconName, label, key, value) {
    const wrap = h("div", {});
    wrap.appendChild(h("div", { class: "field-label" }, [icon(iconName, 10), label]));
    const input = h("input", { class: "field-input", value: value || "" });
    fieldRefs[key] = input;
    wrap.appendChild(input);
    return wrap;
  }

  function renderMetadataTab(body) {
    const state = S.detailState;
    const fields = state.fields || {};
    const draft = state.draft || {};
    const value = (k) => (draft[k] !== undefined ? draft[k] : (fields[k] || ""));
    Object.keys(fieldRefs).forEach((k) => delete fieldRefs[k]);

    // 상단 고정: 대표 이미지 + 6필드 요약 카드, 그 아래 Title
    const topFixed = h("div", { class: "detail-body-fixed" });
    const card = h("div", { class: "identity-card" });
    const cover = h("div", { class: "identity-cover" });
    if (state.media && state.media.Covers) {
      const img = h("img", { alt: "Cover" });
      cover.appendChild(img);
      loadMediaImage(img, "Covers", true);
    } else {
      cover.appendChild(icon("image", 17));
    }
    const grid = h("div", { class: "identity-grid" });
    [["Genre", "genre"], ["Release", "releasedate"], ["Players", "players"],
     ["Region", "region"], ["Developer", "developer"], ["Publisher", "publisher"]].forEach(([label, key]) => {
      grid.appendChild(h("div", { class: "identity-field" }, [
        h("div", { class: "identity-field-label" }, [label]),
        h("div", { class: "identity-field-value truncate" }, [value(key) || "-"]),
      ]));
    });
    card.appendChild(cover);
    card.appendChild(grid);
    topFixed.appendChild(card);

    topFixed.appendChild(h("div", { class: "field-label" }, ["Title"]));
    const nameInput = h("input", { class: "field-input title-input", value: value("name") });
    fieldRefs.name = nameInput;
    topFixed.appendChild(nameInput);
    body.appendChild(topFixed);

    // Description은 **10줄쯤을 기본으로 두고 넘치면 안에서 스크롤한다.**
    // 남는 세로 공간을 전부 흡수하게 두면 설명이 긴 게임에서 아래 필드들이 화면
    // 밖으로 밀려나, 장르 하나 고치려고 스크롤을 내려야 한다.
    const descWrap = h("div", { class: "detail-body-desc-wrap" });
    descWrap.appendChild(h("div", { class: "field-label" }, ["Description"]));
    const desc = h("textarea", { class: "field-input", rows: 10 });
    desc.value = value("desc");
    fieldRefs.desc = desc;
    descWrap.appendChild(desc);
    body.appendChild(descWrap);

    const bottom = h("div", { class: "detail-body-fixed" });
    const fieldGrid = h("div", { class: "field-grid" });
    fieldGrid.appendChild(fieldGroup("tag", "Genre", "genre", value("genre")));
    fieldGrid.appendChild(fieldGroup("building", "Developer", "developer", value("developer")));
    fieldGrid.appendChild(fieldGroup("building", "Publisher", "publisher", value("publisher")));
    fieldGrid.appendChild(fieldGroup("calendar", "Release", "releasedate", value("releasedate")));
    fieldGrid.appendChild(fieldGroup("globe", "Region", "region", value("region")));
    fieldGrid.appendChild(fieldGroup("star", "Rating", "rating", value("rating")));
    fieldGrid.appendChild(fieldGroup("users", "Players", "players", value("players")));
    bottom.appendChild(fieldGrid);
    body.appendChild(bottom);
  }

  async function loadMediaImage(img, label, thumbnail) {
    const state = S.detailState;
    if (!state) return;
    const romUid = state.romUid;
    // **Archive 항목은 조회 경로가 다르다.**
    //
    // Collection용 조회는 `collection_id` + `rom_uid`로 Cache를 뒤지는데, Archive
    // 항목에는 그 둘 다 없다(식별자가 romIdentityId다). 그런데 여기서 구분 없이
    // Collection 경로를 부르고 있어서, Archive에 media가 저장되어 있는데도 조회가
    // 조용히 실패해 영영 보이지 않았다.
    const r = state.archive
      ? await api.getArchiveMediaImage(state.romIdentityId, label, !!thumbnail)
      : await api.getMediaImage(S.activeId, romUid, label, !!thumbnail);
    if (r.ok && r.data && S.detailState && S.detailState.romUid === romUid) img.src = r.data;
  }

  //: 화면에 보여줄 media와 그 표시 방식.
  //
  //  `file`인 것(영상·설명서)은 그림이 아니라 **있는지 없는지**만 알면 된다. 영상을
  //  data URI로 실어 오면 브릿지가 감당하지 못하고, 설명서는 PDF라 애초에 그릴 수 없다.
  //  그래서 그 둘은 [v] 하나로 표시한다 - 이전 프로젝트가 쓰던 방식이다.
  //: **자리가 정해져 있다.** 어떤 media가 있느냐에 따라 배치가 달라지지 않는다.
  //
  //  Cover는 세로로 긴 표지고 Screenshot은 가로로 넓은 화면이다. 이 둘이 그 게임을
  //  알아보게 하는 주된 그림이므로 크게 놓고, 나머지는 작게 곁들인다. 예전에는 열두
  //  칸을 전부 같은 16:9 타일로 늘어놓아서, 표지가 타일 넓이의 절반도 못 쓰고 양옆에
  //  검은 여백만 남았다.
  //
  //  슬롯을 고정하는 이유는 안정성이다. "있는 것부터 채운다"로 하면 게임을 넘길 때마다
  //  Cover가 있던 자리에 Wheel이 오는 식으로 배치가 출렁인다.
  const MEDIA_HERO = { label: "Cover", key: "Covers" };
  //: Cover 오른쪽. **셋이다.** 넷을 놓으니 난잡하고 각 칸이 너무 납작해졌다.
  const MEDIA_HERO_SIDE = [
    { label: "Marquee", key: "Marquees" },
    { label: "MixImage", key: "Miximages" },
    { label: "TitleScreen", key: "TitleScreens" },
  ];
  const MEDIA_WIDE = { label: "Screenshot", key: "Screenshots" };
  //: 아래 한 줄. Wheel은 가로로 긴 로고라 Cover 옆의 세로 칸보다 여기가 맞는다.
  const MEDIA_REST = [
    { label: "3DBox", key: "3DBoxes" },
    { label: "BackCover", key: "BackCovers" },
    { label: "PhysicalMedia", key: "PhysicalMedia" },
    { label: "Wheel", key: "Wheel" },
  ];
  //: 그림으로 보여주지 않고 **있는지 없는지만** 말하는 것들.
  //
  //  영상은 data URI로 실어 오면 브릿지가 감당하지 못하고, 설명서는 PDF라 애초에
  //  그릴 수 없다. FanArt는 자리를 차지할 만큼 자주 보는 것이 아니어서 여기 둔다
  //  (사용자 결정) - 그래도 있고 없고는 알 수 있어야 누락을 알아챈다.
  const MEDIA_FLAGS = [
    { label: "Video", key: "Videos" },
    { label: "Manual", key: "Manuals" },
    { label: "FanArt", key: "FanArt" },
  ];

  //: 화면에 보여줄 media 전부. 다른 코드가 "어떤 슬롯이 있는지" 물을 때 쓴다.
  const MEDIA_SLOTS = [MEDIA_HERO, ...MEDIA_HERO_SIDE, MEDIA_WIDE,
                       ...MEDIA_REST, ...MEDIA_FLAGS];

  function mediaTile(slot, media, extraClass) {
    const has = !!media[slot.key];
    const zone = h("div", {
      class: ["media-tile", extraClass, has ? "" : "empty"].filter(Boolean).join(" "),
      title: slot.label + (has ? "" : " 없음"),
    });
    // 라벨은 그림 위에 겹쳐 놓는다 - 레이아웃 공간을 먹지 않아야 그림이 커진다.
    zone.appendChild(h("div", { class: "media-tile-label" }, [slot.label]));

    // **비어 있어도 상자 크기는 그대로다.** 크기는 CSS가 정하고 그림은 그 안에
    // 맞춰 들어간다 - 그림 크기가 배치를 정하면 게임을 넘길 때마다 패널이 출렁인다.
    const preview = h("div", { class: "media-tile-preview" });
    if (has) {
      const img = h("img", { alt: slot.label });
      // Screenshot 상자는 CSS가 4:3으로 잡아 두지만, 세로로 더 긴 그림은 그 안에
      // 넣으면 위아래가 빈다. 실제 그림 비율을 알고 나면(로드 후) 상자를 그 비율로
      // 늘려서 빈 자리를 없앤다 - 아래 media-rest가 밀려나는 건 허용한다(CSS 참고).
      if (extraClass === "wide") {
        img.addEventListener("load", () => {
          if (img.naturalWidth && img.naturalHeight > img.naturalWidth) {
            zone.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`;
          }
        });
      }
      preview.appendChild(img);
      loadMediaImage(img, slot.key, false);
      zone.classList.add("clickable");
      zone.addEventListener("click", () => openMediaLightbox(img, slot.label));
    } else {
      // "… 없음"을 열두 번 적으면 그것만 눈에 들어온다. 아이콘 하나로 족하다.
      preview.appendChild(icon("imageOff", 16));
    }
    zone.appendChild(preview);
    return zone;
  }

  /** 그림 없이 있고 없고만 말하는 줄. `v Video   x Manual` 처럼 보인다. */
  function mediaFlagRow(media) {
    const row = h("div", { class: "media-flags" });
    MEDIA_FLAGS.forEach((slot) => {
      const has = !!media[slot.key];
      row.appendChild(h("div", {
        class: "media-flag-item" + (has ? " on" : ""),
        title: `${slot.label}${has ? " 있음" : " 없음"}`,
      }, [
        h("span", { class: "media-flag" }, [has ? "v" : "x"]),
        h("span", { class: "media-flag-label" }, [slot.label]),
      ]));
    });
    return row;
  }

  /** Media 탭. **전체 배치가 고정이다.**
   *
   * 어떤 media가 있느냐, 그림이 어떤 비율이냐에 따라 자리가 달라지지 않는다. 예전에는
   * 이미지에 `width:100%; height:auto`를 줘서 표지 비율이 곧 상자 높이였고, 그래서
   * 게임을 넘길 때마다 Cover 높이가 달라지고 오른쪽 보조 media와 아래위가 어긋났다.
   *
   *   [ Cover ][ Marquee    ]     <- Cover 높이 == 오른쪽 셋의 높이 합
   *   [       ][ MixImage   ]
   *   [       ][ TitleScreen]
   *   [        Screenshot       ]
   *   [3DBox][BackCover][Physical][Wheel]
   *   v Video   v Manual   x FanArt
   */
  function renderMediaTab(body) {
    body.classList.add("media-tab-body");
    const media = S.detailState.media || {};

    const hero = h("div", { class: "media-hero" });
    hero.appendChild(mediaTile(MEDIA_HERO, media, "cover"));
    const side = h("div", { class: "media-hero-side" });
    MEDIA_HERO_SIDE.forEach((slot) => side.appendChild(mediaTile(slot, media, "side")));
    hero.appendChild(side);
    body.appendChild(hero);

    body.appendChild(mediaTile(MEDIA_WIDE, media, "wide"));

    const rest = h("div", { class: "media-rest" });
    MEDIA_REST.forEach((slot) => rest.appendChild(mediaTile(slot, media, "small")));
    body.appendChild(rest);

    body.appendChild(mediaFlagRow(media));
  }

  // Revision 목록(스펙 §44, `docs/ARCHIVE_REVISION_POLICY.md`).
  //
  // 같은 게임이 여러 Collection에서 왔을 때 **어느 값을 쓸지 사용자가 고른다.** 그래서
  // 필드를 표로 늘어놓는 대신 제목과 설명 몇 줄만 보여준다 - 어느 판이 더 나은
  // 설명을 갖고 있는지가 실제 판단 기준이기 때문이다. 나머지 필드는 Metadata 탭이
  // 이미 보여주고 있다.
  //
  // 오른쪽 별표가 **Preferred Revision**이다. 골라 두면 Collection으로 보낼 때 그 판이
  // 먼저 쓰인다(Preferred -> Latest -> Older).
  function renderSourcesTab(body) {
    const state = S.detailState;
    const sources = state.sources || [];
    if (!sources.length) {
      body.appendChild(h("div", { class: "empty-msg" }, ["아직 수집된 Revision이 없습니다."]));
      return;
    }

    const preferredId = state.preferredRecordId || null;
    sources.forEach((source) => {
      const chosen = source.recordId != null && source.recordId === preferredId;
      const box = h("div", { class: "revision-row" + (chosen ? " chosen" : "") });

      const main = h("div", { class: "revision-main" });
      const fields = source.fields || {};
      main.appendChild(h("div", { class: "revision-title truncate" },
                          [fields.name || state.file || "(제목 없음)"]));
      main.appendChild(h("div", { class: "revision-desc" }, [fields.desc || "설명 없음"]));

      const name = source.collectionId === "__archive__"
        ? "Archive에서 직접 편집"
        : (S.collections.find((c) => c.id === source.collectionId) || {}).name
          || source.collectionId;
      main.appendChild(h("div", { class: "revision-meta" }, [`${name} · rev ${source.revision}`]));
      box.appendChild(main);

      // 별표 하나로 "이 판을 쓴다"를 정한다. 다시 누르면 자동 선택(Latest)으로 돌아간다.
      const star = h("button", {
        class: "fav-btn" + (chosen ? " on" : ""),
        title: chosen ? "선택 해제 (가장 최근 판을 씁니다)" : "이 Revision을 우선 사용",
      }, [chosen ? "★" : "☆"]);
      star.addEventListener("click", () => togglePreferredRevision(source, chosen));
      box.appendChild(star);

      body.appendChild(box);
    });
  }

  async function togglePreferredRevision(source, chosen) {
    const state = S.detailState;
    if (!state || source.recordId == null) return;
    const r = chosen
      ? await api.archiveClearPreferred(state.romIdentityId)
      : await api.archiveSetPreferred(state.romIdentityId, source.recordId);
    if (!r.ok) { showToast(r.error, "error"); return; }
    state.preferredRecordId = chosen ? null : source.recordId;
    renderDetailPanel();
    showToast(chosen ? "우선 Revision을 해제했습니다. 가장 최근 판을 씁니다."
                     : "이 Revision을 우선 사용합니다.");
  }

  function renderRomTab(body) {
    const state = S.detailState;
    const rows = [
      ["파일명", state.file],
      ["System", String(state.system).toUpperCase()],
      ["크기", state.size ? formatBytes(state.size) : "-"],
      ["ROM 파일", state.present ? "있음" : "없음 (metadata만 존재)"],
      ["SHA256", state.sha256 || "계산 안 됨"],
    ];
    const box = h("div", { class: "rom-info" });
    rows.forEach(([label, value]) => {
      box.appendChild(h("div", { class: "health-row" }, [
        h("span", {}, [label]), h("span", { class: "truncate" }, [value])]));
    });
    body.appendChild(box);
  }

  async function handleSaveDetail() {
    if (blockedInCompare("저장")) return;
    const state = S.detailState;
    if (!state) return;
    captureDraft();
    const fields = { ...state.fields, ...(state.draft || {}) };
    const r = state.archive
      ? await api.archiveEdit(state.romIdentityId, fields)
      : await api.saveFields(S.activeId, state.romUid, fields);
    if (!r.ok) { showToast(r.error, "error"); return; }
    state.fields = fields;
    state.draft = null;
    if (state.archive) {
      // Archive 편집은 Collection에 자동 반영되지 않는다(스펙 §40). 그 사실을 매번 말해준다.
      showToast("Archive에 저장했습니다. Collection에 반영하려면 \"Collection으로 보내기\"를 누르세요.");
      renderListWindow();
      return;
    }

    // 저장은 즉시 파일에 반영된다(결정 D1). 목록에 보이는 칸도 전부 새 값으로 바꾼다 -
    // 예전엔 제목만 바꿔서, Description을 고쳐도 다른 System에 갔다 와야 목록에
    // 보였다(실사용 피드백).
    const cached = rowByUid(state.romUid);
    if (cached) {
      const saved = r.data || {};
      Object.assign(cached, {
        title: saved.title || fields.name || cached.title,
        desc: fields.desc || "", region: fields.region || "",
        genre: fields.genre || "", rating: fields.rating || "",
        hasMetadata: true,
      });
    }
    renderListWindow();
    showToast("저장되었습니다.");
  }

  // ------------------------------------------------------------------
  // Plan
  // ------------------------------------------------------------------
  async function refreshPlan() {
    if (!S.activeId || isArchive()) { S.plan = null; renderStatusBar(); return; }
    const r = await api.planState(S.activeId);
    S.plan = r.ok ? r.data : null;
    renderHeader();
    // Apply/Cancel이 목록 위 툴바에 있으므로 Plan이 바뀌면 툴바도 다시 그려야 한다.
    renderFilterBar();
    renderStatusBar();
    renderListWindow();
    // Storage 이동을 Plan에 올리면 Navigator도 목표 Storage 밑에 미리 보여줘야
    // 한다(§ moveSystemToStorage) - 안 그러면 드래그가 반영 안 된 것처럼 보인다.
    renderNav();
  }

  const planCapacity = (storageId) =>
    ((S.plan && S.plan.capacity) || []).find((c) => c.storageId === storageId) || null;

  // Copy/Paste - QA 재검토 P1에서 한 번 없앴다("Collection 사이 이동은 Archive를
  // 거친다"). Ctrl+C/Ctrl+V로 되살렸다(사용자 요청) - 새 병합 함수를 만들 뻔했지만
  // tests/test_metadata_only_paste.py를 보니 이미 있는 메커니즘(`plan_add()` +
  // 충돌 해결)이 정확히 이 요구사항을 구현하고 있었다: 대상에 ROM이 이미 있으면
  // 충돌로 뜨고, 사용자가 "메타데이터만"을 고르면 ROM은 그대로 두고 메타데이터/
  // media만 채워진다(파일이 없는 조각만 옮겨진다는 뜻과 같다). 그래서 여기서는
  // 새 로직을 만들지 않고 Apply 흐름과 같은 충돌 다이얼로그를 그대로 쓴다.
  // Archive 탭에는 이 방식이 안 맞는다 - Archive는 rom_uid가 아니라
  // romIdentityId로 식별하고, 자기 전용 경로(Archive에 수집 / Collection으로
  // 보내기)가 이미 있다.
  async function copySelectedRows() {
    if (blockedInCompare("복사")) return;
    if (isArchive()) { showToast("Archive는 복사할 수 없습니다 - \"Collection으로 보내기\"를 쓰세요.", "warning"); return; }
    if (!S.selected.size) { showToast("복사할 항목을 선택하세요.", "warning"); return; }
    const r = await api.copySelection(S.activeId, [...S.selected]);
    if (!r.ok) { showToast(r.error, "error"); return; }
    showToast(`${formatCount(r.data.count)}개 복사했습니다. 대상 System/Collection에서 Ctrl+V로 붙여넣으세요.`);
  }

  async function pasteClipboard() {
    if (blockedInCompare("붙여넣기")) return;
    if (isArchive()) { showToast("Archive에는 붙여넣을 수 없습니다 - \"Archive에 수집\"을 쓰세요.", "warning"); return; }
    const r = await api.paste(S.activeId);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const d = r.data;
    await refreshPlan();
    resetList();
    await reloadList();
    if (d.conflicts) {
      showToast(`추가 ${formatCount(d.added)}개 · 충돌 ${formatCount(d.conflicts)}개 - 대상에 이미 있는 항목입니다.`, "warning");
      openConflictDialog();
      return;
    }
    if (d.added) showToast(`Plan에 ${formatCount(d.added)}개를 추가했습니다.`);
    else showToast("붙여넣을 새 내용이 없습니다(전부 이미 있음).", "info");
  }

  async function deleteSelection() {
    if (blockedInCompare("삭제")) return;
    if (!S.selected.size) { showToast("삭제할 항목을 선택하세요.", "warning"); return; }
    const count = S.selected.size;
    const run = async () => {
      const r = await api.planDelete(S.activeId, [...S.selected]);
      if (!r.ok) { showToast(r.error, "error"); return; }
      S.selected.clear();
      await refreshPlan();
      if (S.autoPlan) showToast(`${formatCount(count)}개를 삭제 예정으로 표시했습니다.`);
      else await applyPlan();
    };
    // Auto Plan이 켜져 있으면 아직 파일이 지워지지 않으므로 확인창까지 띄우지 않는다.
    if (S.autoPlan) run();
    else showConfirm("삭제", `${formatCount(count)}개를 즉시 삭제합니다. 되돌릴 수 없습니다.`, true, run);
  }

  function conflictLine(entry) {
    const first = (entry.conflicts || [])[0] || {};
    return `${entry.filename} — ${first.reason || "목적지에 다른 파일이 있습니다"}`;
  }

  async function openConflictDialog() {
    const entries = (S.plan && S.plan.conflictEntries) || [];
    if (!entries.length) return;

    const list = h("div", { class: "picker-list" });
    entries.slice(0, 50).forEach((entry) => {
      const row = h("div", { class: "conflict-row" }, [
        h("div", { class: "conflict-main" }, [
          h("div", { class: "picker-name truncate" }, [entry.filename]),
          h("div", { class: "picker-sub truncate" }, [conflictLine(entry)]),
        ]),
      ]);
      // "건너뛰기"는 그 항목을 통째로 건너뛴다고 읽힌다. 실제로 하는 일은
      // **ROM은 그대로 두고 메타데이터/media(커버 등)는 반영**이고, 대개는 그것이
      // 사용자가 원한 것이다(Phase 7.22 QA, tests/test_paste_media_overwrite_combo.py).
      [["메타데이터만", "ROM은 그대로 두고, 메타데이터와 media(커버 등)는 새 것으로 채웁니다"],
       ["파일 덮어쓰기", "대상 파일을 새 파일로 교체합니다"]].forEach(([label, tip], i) => {
        const btn = h("button", { class: "btn compact", title: tip }, [label]);
        btn.addEventListener("click", async () => {
          await api.planResolveConflict(S.activeId, entry.key, i === 0 ? "skip" : "overwrite");
          await refreshPlan();
          closeModal();
          openConflictDialog();
        });
        row.appendChild(btn);
      });
      list.appendChild(row);
    });
    if (entries.length > 50) {
      list.appendChild(h("div", { class: "modal-hint" }, [`외 ${formatCount(entries.length - 50)}개 더 있습니다.`]));
    }

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [
        `대상에 같은 이름의 파일이 이미 있는 항목 ${formatCount(entries.length)}개입니다. ` +
        "크기가 같아도 내용이 다를 수 있어 자동으로 덮어쓰지 않습니다."]),
      h("div", { class: "modal-hint" }, [
        "이미 가지고 있는 ROM에 메타데이터와 media(커버 등)만 채우려는 것이라면 " +
        "«메타데이터만»을 고르세요. ROM 파일은 건드리지 않습니다."]),
      list,
    ]);
    showModal("충돌 확인", body, [
      h("button", { class: "btn", onClick: closeModal }, ["나중에"]),
      h("button", { class: "btn", onClick: async () => {
        closeModal();
        await api.planResolveAllConflicts(S.activeId, "skip");
        await refreshPlan();
      } }, ["모두 메타데이터만"]),
      h("button", { class: "btn danger", onClick: () => {
        showConfirm("모두 덮어쓰기",
          `${formatCount(entries.length)}개 항목의 기존 파일을 새 파일로 교체합니다. 되돌릴 수 없습니다.`,
          true, async () => {
            await api.planResolveAllConflicts(S.activeId, "overwrite");
            await refreshPlan();
          });
      } }, ["모두 덮어쓰기"]),
    ]);
  }

  /** 지난 Apply에서 실패해 Plan에 남은 항목을 보여준다.
   *
   * 예전엔 하단 바에 "실패 N"이라는 숫자만 있고 눌러도 아무 일도 없었다 -
   * 왜 실패했는지(예: External Storage에 같은 이름의 파일이 이미 있음) 알
   * 방법이 없어서 Apply를 눌러도 계속 실패만 반복됐다(실사용 피드백). 이유를
   * 보여주고, 재시도(다음 Apply가 자동으로 다시 시도한다)나 포기(Plan에서
   * 제거)를 고르게 한다. */
  async function openFailedDialog() {
    const entries = (S.plan && S.plan.failedEntries) || [];
    if (!entries.length) return;

    const list = h("div", { class: "picker-list" });
    entries.slice(0, 50).forEach((entry) => {
      const row = h("div", { class: "conflict-row" }, [
        h("div", { class: "conflict-main" }, [
          h("div", { class: "picker-name truncate" }, [entry.filename]),
          h("div", { class: "picker-sub truncate" }, [entry.error || "원인을 알 수 없는 실패"]),
        ]),
      ]);
      const remove = h("button", { class: "btn compact", title: "이 항목을 Plan에서 지웁니다 - 다시 시도하지 않습니다" },
        ["Plan에서 제거"]);
      remove.addEventListener("click", async () => {
        await api.planRemoveEntry(S.activeId, entry.key);
        await refreshPlan();
        closeModal();
        openFailedDialog();
      });
      row.appendChild(remove);
      list.appendChild(row);
    });
    if (entries.length > 50) {
      list.appendChild(h("div", { class: "modal-hint" }, [`외 ${formatCount(entries.length - 50)}개 더 있습니다.`]));
    }

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [
        `지난 Apply에서 실패해 Plan에 남은 항목 ${formatCount(entries.length)}개입니다.`]),
      h("div", { class: "modal-hint" }, [
        "다음 Apply 때 다시 시도합니다. 원인이 해결되지 않았다면 같은 이유로 " +
        "또 실패합니다 - 예를 들어 대상 Storage에 같은 이름의 파일이 이미 있으면 " +
        "그 파일을 먼저 지우거나 옮겨야 합니다."]),
      list,
    ]);
    showModal("실패한 항목", body, [
      h("button", { class: "btn", onClick: closeModal }, ["닫기"]),
    ]);
  }

  async function applyPlan() {
    if (!S.plan || !S.plan.total) { showToast("적용할 Plan이 없습니다.", "warning"); return; }
    // 미해결 충돌이 있으면 먼저 결정하게 한다. 그냥 진행하면 그 항목들이 조용히
    // 빠진 채 "적용 완료"로 보인다.
    if (S.plan.conflicts) { openConflictDialog(); return; }
    const check = await api.validatePlan(S.activeId);
    if (!check.ok) { showToast(check.error, "error"); return; }
    const report = check.data;

    const body = h("div", { class: "modal-body" });
    body.appendChild(h("div", { class: "modal-text" }, [
      `추가 ${formatCount(S.plan.added)} · 삭제 ${formatCount(S.plan.deleted)} · 이동 ${formatCount(S.plan.moved)}`,
    ]));
    (report.capacity || []).forEach((c) => {
      const row = h("div", { class: "health-row" + (c.over ? " over" : "") }, [
        h("span", {}, [c.label]),
        h("span", {}, [
          `${formatBytes(c.actualBytes)} → ${formatBytes(c.planBytes)}`,
          c.capacityBytes == null ? " (Capacity Unknown)" : "",
          c.over ? ` · 용량 초과 +${formatBytes(c.overBytes)}` : "",
        ]),
      ]);
      body.appendChild(row);
    });
    if (report.entries && report.entries.length) {
      body.appendChild(h("div", { class: "modal-hint" }, [
        `확정할 수 없는 항목 ${report.entries.length}개: ` +
        report.entries.slice(0, 3).map((e) => `${e.filename} (${e.error})`).join(", "),
      ]));
    }

    const actions = [h("button", { class: "btn", onClick: closeModal }, ["취소"])];
    if (!report.blocked) {
      actions.push(h("button", { class: "btn primary", onClick: async () => {
        closeModal();
        const r = await api.startApply(S.activeId);
        if (!r.ok) { showToast(r.error, "error"); return; }
        const result = await pollJob(r.data.jobId, "Plan 적용 중");
        if (!result.ok) {
          if (!result.cancelled) showToast(result.error, "error");
        } else {
          const data = result.data || {};
          const remaining = (data.failed || 0) + (data.partial || 0) + (data.skipped || 0);
          let message = `적용 ${formatCount(data.applied || 0)}개`;
          if (data.failed) message += ` · 실패 ${formatCount(data.failed)}개`;
          if (data.partial) message += ` · 일부만 반영 ${formatCount(data.partial)}개`;
          if (data.skipped) message += ` · 충돌로 건너뜀 ${formatCount(data.skipped)}개`;
          // "Apply 했으니 끝났다"고 오해하지 않도록 남은 항목을 반드시 말한다.
          if (remaining) message += ` — ${formatCount(remaining)}개가 Plan에 남아 있습니다`;
          showToast(message, remaining ? "warning" : "info");
        }
        await ensureDetail(S.activeId);
        resetList();
        renderAll();
        await reloadList();
        await refreshPlan();
      } }, ["적용"]));
    }
    showModal(report.blocked ? "용량 부족" : "Plan 적용", body, actions);
  }

  // Auto Plan을 껐다 켰다 하는 UI는 없앴다(레이아웃 재검토 결론) - 실사용
  // 시나리오가 확인되기 전까지는 화면에서 감춘다. `S.autoPlan`은 기본 ON으로
  // 고정이고, 이 값을 읽는 곳들(§ moveSystemToStorage, deleteSelection 등)은
  // 그대로 둔다 - 언젠가 토글을 되살릴 때 그 로직까지 다시 짤 필요는 없다.

  // ------------------------------------------------------------------
  // Archive (스펙 §37-44)
  // ------------------------------------------------------------------
  /** 지금 "Archive에 수집"을 누르면 무엇이 들어가는지.
   *
   * 우선순위는 **고른 게임 > Navigation의 System > Collection 전체**다. 사용자가
   * 마지막에 한 행동이 가장 구체적인 의도이기 때문이다(사용자 결정).
   *
   * 예전에는 선택이 없으면 `null`을 보냈고 백엔드가 그것을 "전체"로 해석했다. 화면에는
   * MSX1만 보이는데 Collection 전체가 Archive에 들어간 것이 그 때문이다. 대상은
   * 추측하지 않고 여기서 명시한다.
   */
  function archiveScope() {
    if (S.selected.size) return { kind: "selected", romUids: [...S.selected] };
    const scope = activeScope();
    if (scope.kind === "system") return { kind: "system", system: scope.id };
    return { kind: "all" };
  }

  function archiveScopeLabel(scope) {
    if (scope.kind === "selected") return `선택한 ${formatCount(scope.romUids.length)}개`;
    if (scope.kind === "system") return `${String(scope.system).toUpperCase()} 전체`;
    return "Collection 전체";
  }

  async function ingestToArchive() {
    const scope = archiveScope();
    const label = archiveScopeLabel(scope);
    const started = await api.startArchiveIngest(S.activeId, scope);
    if (!started.ok) { showToast(started.error, "error"); return; }
    if (!started.data.count) { showToast("수집할 항목이 없습니다.", "warning"); return; }

    // 게임 수만큼 DB 쓰기가 일어난다. 동기로 기다리면 큰 Collection에서 창이 멈춘
    // 것처럼 보이고 취소할 방법도 없다.
    const r = await pollJob(started.data.jobId, `Archive 수집 — ${label}`);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const d = r.data;
    showToast(`${label} 수집 완료 — 새 내용 ${formatCount(d.revised)}개, ` +
              `변경 없음 ${formatCount(d.unchanged)}개`);
  }

  function openSendToCollection() {
    const targets = S.tabs.filter((t) => t !== ARCHIVE_ID);
    const list = h("div", { class: "picker-list" });
    targets.forEach((id) => {
      const collection = S.collections.find((c) => c.id === id);
      if (!collection) return;
      const row = h("button", { class: "picker-row" }, [
        icon("gamepad", 14),
        h("div", { class: "picker-main" }, [
          h("div", { class: "picker-name" }, [collection.name]),
          h("div", { class: "picker-sub truncate" }, [collection.rootPath]),
        ]),
      ]);
      row.addEventListener("click", () => { closeModal(); sendToCollection(id); });
      list.appendChild(row);
    });
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" },
        [`선택한 ${formatCount(S.selected.size)}개를 어느 Collection으로 보낼까요?`]),
      list,
      h("div", { class: "modal-hint" }, [
        "이미 있는 게임은 Metadata만 바로 반영되고, 없는 게임은 파일을 가져와야 하므로 " +
        "Plan에 올라갑니다."]),
    ]);
    showModal("Collection으로 보내기", body, [h("button", { class: "btn", onClick: closeModal }, ["취소"])]);
  }

  async function sendToCollection(collectionId) {
    const r = await api.archiveToCollection(collectionId, [...S.selected]);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const d = r.data;
    let message = `Metadata 반영 ${formatCount(d.updated)}개`;
    if (d.planned) message += ` · Plan에 추가 ${formatCount(d.planned)}개`;
    if (d.conflicts) message += ` · 충돌 ${formatCount(d.conflicts)}개`;
    if ((d.skipped || []).length) message += ` · 원본 없어 제외 ${formatCount(d.skipped.length)}개`;
    showToast(message, d.planned || d.conflicts ? "warning" : "info");
    if (S.detail[collectionId]) await ensureDetail(collectionId);
  }

  // ------------------------------------------------------------------
  // 하단 상태 바
  // ------------------------------------------------------------------
  function renderStatusBar() {
    const bar = $("status-bar");
    clear(bar);
    // 선택 개수를 다시 그리는 자리다. 툴바에서 선택에 따라 달라지는 것들(수집 대상
    // 표시, Delete 활성)도 같은 근거를 쓰므로 여기서 함께 맞춘다 - 툴바를 통째로
    // 다시 그리지 않고 그 두 곳만 고친다.
    updateSelectionDependentActions();
    const detail = activeDetail();
    const plan = S.plan;

    const left = h("div", { class: "sb-left" }, [
      icon("layoutList", 12),
      h("span", {}, [`Selected ${formatCount(S.selected.size)}`]),
    ]);
    if (plan && plan.total) {
      if (plan.addedBytes) left.appendChild(h("span", { class: "sb-add" }, [`+${formatBytes(plan.addedBytes)}`]));
      if (plan.deletedBytes) left.appendChild(h("span", { class: "sb-del" }, [`−${formatBytes(plan.deletedBytes)}`]));
      if (plan.conflicts) {
        const btn = h("button", { class: "sb-badge warn", title: "충돌을 확인하고 처리 방식을 정하세요" },
          [`충돌 ${formatCount(plan.conflicts)}`]);
        btn.addEventListener("click", openConflictDialog);
        left.appendChild(btn);
      }
      if (plan.failed) {
        const btn = h("button", { class: "sb-badge danger",
          title: "지난 적용에서 실패해 Plan에 남아 있는 항목 - 눌러서 이유를 보세요" },
          [`실패 ${formatCount(plan.failed)}`]);
        btn.addEventListener("click", openFailedDialog);
        left.appendChild(btn);
      }
    }
    bar.appendChild(left);

    const middle = h("div", { class: "sb-middle" });
    if (detail) {
      middle.appendChild(h("span", { class: "sb-label" }, [plan && plan.total ? "Storage (Actual → Plan)" : "Storage"]));
      detail.storages.forEach((storage) => {
        const capacity = planCapacity(storage.id);
        const changed = capacity && capacity.deltaBytes;
        // Storage의 자리는 여기다 - 용량과 물리 위치를 말하는 곳. Navigation은
        // System을 보여주는 곳이지 Storage 계층을 보여주는 곳이 아니다.
        const chip = h("span", {
          class: "sb-storage clickable" + (capacity && capacity.over ? " over" : ""),
          title: `${storage.rootPath}\n눌러서 상세를 봅니다`,
        }, [
          h("b", {}, [storage.label]), " ",
          formatBytes(storage.actualBytes),
          changed ? ` → ${formatBytes(capacity.planBytes)}` : "",
        ]);
        chip.addEventListener("click", () => openStorageMenu(storage));
        middle.appendChild(chip);
      });
    }
    bar.appendChild(middle);

    const actions = h("div", { class: "sb-actions" });
    if (isCompare()) {
      // 비교 중에는 Copy/Paste/Delete/Apply를 내놓지 않는다. Paste와 Apply는 선택이
      // 없어도 눌리는 버튼이라, 두면 비교 화면에서 그대로 변경이 일어난다.
      actions.appendChild(h("span", { class: "sb-badge" }, ["읽기 전용"]));
      bar.appendChild(actions);
      return;
    }
    // Archive의 "Collection으로 보내기"도 Detail 패널 상단으로 옮겼다(레이아웃
    // 재검토) - AutoPlan/Apply/Cancel/Archive에 수집/Delete와 같은 이유로,
    // 여기 그대로 두면 똑같은 버튼이 두 번 보인다.
    bar.appendChild(actions);
  }

  // ------------------------------------------------------------------
  // 스캔
  // ------------------------------------------------------------------
  /** 지금 보고 있는 탭을 다시 읽는다.
   *
   * Archive는 Collection이 아니다 - 디스크를 훑을 것이 없고 Registry에도 없다.
   * 그런데 새로고침이 탭 종류를 가리지 않고 `startScan(S.activeId)`를 불러서,
   * Archive 탭에서 누르면 백엔드가 "Collection을 찾을 수 없습니다"로 답했다.
   */
  async function refreshActive() {
    if (isArchive()) {
      await ensureDetail(ARCHIVE_ID);
      resetList();
      renderAll();
      await reloadList();
      return;
    }
    await runScan(S.activeId);
  }

  async function runScan(collectionId, force) {
    const r = await api.startScan(collectionId, !!force);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const result = await pollJob(r.data.jobId, "Collection 스캔 중");
    if (!result.ok) {
      if (!result.cancelled) showToast(result.error, "error");
      return;
    }
    await ensureDetail(collectionId);
    if (collectionId === S.activeId) {
      resetList();
      renderAll();
      await reloadList();
    } else {
      renderAll();
    }
  }

  // ------------------------------------------------------------------
  // 렌더 / 초기화
  // ------------------------------------------------------------------
  /** 중앙 영역을 목록/Dashboard 중 하나로 맞춘다. */
  function renderCenterView() {
    $("center").classList.toggle("dashboard-mode", S.view === "dashboard");
  }

  function showList() {
    S.view = "list";
    renderCenterView();
    renderNav();
  }

  let dashboardToken = 0;
  async function showDashboard() {
    if (!S.activeId || isArchive()) {
      showToast("Dashboard는 Collection 탭에서 볼 수 있습니다.", "warning");
      return;
    }
    const id = S.activeId;
    const token = ++dashboardToken;
    S.view = "dashboard";
    renderCenterView();
    renderNav();
    const host = $("dashboard-view");
    clear(host);
    const view = h("div", { class: "dsb" }, [h("div", { class: "dsb-empty" }, ["Dashboard를 불러오는 중…"])]);
    host.appendChild(view);
    const [stats, ui] = await Promise.all([api.dashboardStats(id), api.getUiState(id)]);
    // 기다리는 사이 탭을 바꾸거나 목록으로 돌아갔으면 늦게 온 결과를 그리지 않는다.
    if (token !== dashboardToken || S.view !== "dashboard" || S.activeId !== id) return;
    if (!stats.ok) {
      clear(view);
      view.appendChild(h("div", { class: "dsb-empty" }, [stats.error || "Dashboard 데이터를 읽지 못했습니다."]));
      return;
    }
    const targets = { ...((ui.ok && ui.data && ui.data.dashboardTargets) || {}) };
    window.RMSDashboard.render(view, stats.data, {
      h, icon, formatBytes, formatCount, targets,
      onTargetChange: (storageId, bytes) => {
        targets[storageId] = bytes;
        // 목표 용량은 그 Collection의 화면 상태로 기억한다(Storage 구성이 Collection마다 다르다).
        api.saveUiState(id, { dashboardTargets: { ...targets } });
      },
      onValidate: () => api.validateCollection(id),
      onOpenSystem: (system) => setScope({ kind: "system", id: system }),
    });
  }

  function renderAll() {
    renderCenterView();
    renderWindowControls();
    renderTabs();
    renderNav();
    renderHeader();
    renderFilterBar();
    renderListHead();
    renderListWindow();
    // renderDetailPanel()이 S.previewOn을 직접 보고 접힌/펼친 모습을 정하므로,
    // 복원된 상태를 반영하기 위한 별도 호출이 필요 없다.
    renderDetailPanel();
    renderStatusBar();
  }

  async function loadCollections() {
    const r = await api.listCollections();
    if (!r.ok) return;
    S.collections = r.data;
    const order = collectionOrder();
    S.collections.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
  }

  //: 레이아웃이 견디는 최소 크기. main.py의 MIN_SIZE와 같은 값이어야 한다 -
  //  여기서 더 작게 줄일 수 있게 두면 창은 줄어드는데 안쪽이 깨진다.
  const MIN_WINDOW = { width: 900, height: 640 };

  /** frameless 창에는 네이티브 크기 조절 테두리가 없다. 네 변과 네 모서리에 손잡이를 둔다.
   *
   * 오른쪽/아래만 끌면 크기만 바꾸면 되지만, 왼쪽/위를 끌면 반대편이 제자리에 있어야
   * 하므로 위치도 함께 옮긴다(window_set_bounds). 오른쪽 아래 모서리는 눈에 보이는
   * 손잡이(#resize-grip)가 맡는다. */
  const RESIZE_EDGES = ["n", "s", "e", "w", "ne", "nw", "sw"];
  function bindResizeGrip() {
    const grip = $("resize-grip");
    if (grip) bindWindowEdge(grip, "se");
    RESIZE_EDGES.forEach((edge) => {
      const handle = h("div", { class: `window-resize-grip ${edge}`, "data-edge": edge });
      document.body.appendChild(handle);
      bindWindowEdge(handle, edge);
    });
  }

  function bindWindowEdge(handle, edge) {
    const movesOrigin = edge.includes("n") || edge.includes("w");
    handle.addEventListener("mousedown", (down) => {
      if (down.button !== 0) return;
      down.preventDefault();
      const start = { x: down.screenX, y: down.screenY, left: window.screenX, top: window.screenY,
                      width: window.outerWidth, height: window.outerHeight };
      let pending = null;
      let latest = null;

      const send = () => {
        pending = null;
        if (!latest) return;
        const b = latest;
        if (movesOrigin) api.windowSetBounds(Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height));
        else api.windowResize(Math.round(b.width), Math.round(b.height));
      };
      const onMove = (move) => {
        const dx = move.screenX - start.x;
        const dy = move.screenY - start.y;
        const b = { left: start.left, top: start.top, width: start.width, height: start.height };
        if (edge.includes("e")) b.width = Math.max(MIN_WINDOW.width, start.width + dx);
        if (edge.includes("s")) b.height = Math.max(MIN_WINDOW.height, start.height + dy);
        if (edge.includes("w")) {
          b.width = Math.max(MIN_WINDOW.width, start.width - dx);
          b.left = start.left + (start.width - b.width);
        }
        if (edge.includes("n")) {
          b.height = Math.max(MIN_WINDOW.height, start.height - dy);
          b.top = start.top + (start.height - b.height);
        }
        latest = b;
        // 브릿지 호출은 프레임당 한 번으로 묶는다 - mousemove마다 부르면 창이 끊겨 보인다.
        if (!pending) pending = requestAnimationFrame(send);
      };
      const onUp = () => {
        // 마지막 위치는 반드시 보낸다 - 취소만 하면 놓은 자리보다 한 프레임 전 크기로 남는다.
        if (pending) { cancelAnimationFrame(pending); send(); }
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  function hasTextSelection() {
    const selection = window.getSelection();
    return !!selection && !selection.isCollapsed && String(selection).trim() !== "";
  }

  function bindEvents() {
    bindResizeGrip();
    const scroll = $("list-scroll");
    let ticking = false;
    scroll.addEventListener("scroll", () => {
      // 헤더는 스크롤 컨테이너 **밖에** 있다(세로로는 고정되어야 하므로). 그래서
      // 가로 위치만 손으로 맞춰 준다 - 이것이 없으면 좌우로 밀 때 헤더만 제자리에
      // 남아 어느 컬럼인지 알 수 없게 된다.
      syncHeadScroll();
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => { ticking = false; renderListWindow(); });
    });
    window.addEventListener("resize", () => renderListWindow());
    // Ctrl + 휠 = UI 크기(사용자 결정). Shift + 휠은 가로 스크롤이라 쓰지 않는다 -
    // ui/stitch-v2-redesign이 그 키를 쓰다가 목록 가로 스크롤과 부딪혔다. WebView의
    // 기본 확대/축소는 막는다 - 둘이 겹치면 글자와 레이아웃이 따로 커진다.
    window.addEventListener("wheel", (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const { min, max, step } = window.RMSSettings.SCALE;
      const current = S.settings.appearance.scale;
      const next = Math.max(min, Math.min(max, current + (e.deltaY < 0 ? step : -step)));
      if (next === current) return;
      updateSettings("appearance", { scale: next });
      showToast(`UI 크기 ${next}%`);
    }, { passive: false });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { if ($("modal-root").firstChild) closeModal(); else closeDetail(); }
      // F5 = 지금 탭 다시 스캔. WebView의 페이지 새로고침은 막는다 - 그러면 열어 둔 탭과
      // 선택이 전부 사라진다.
      if (e.key === "F5") { e.preventDefault(); if (S.activeId) refreshActive(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        // Compare 상세도 tab이 "metadata"라서, 이 조건만으로는 비교 화면에서 저장
        // 경로로 들어가 버린다(state.romUid가 없어 엉뚱한 호출이 된다).
        if (!isCompare() && S.detailState && S.detailState.tab === "metadata") handleSaveDetail();
        return;
      }
      // 입력 중에는 목록 단축키가 끼어들면 안 된다.
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!S.activeId) return;
      // 비교 중에도 단축키를 삼키지는 않는다 - 각 동작이 blockedInCompare()로 막으면서
      // "왜 안 되는지"를 말해준다. 조용히 무시하면 사용자는 키가 안 먹었다고 여긴다.
      if (!$("modal-root").firstChild && S.view !== "dashboard") {
        const plain = !e.ctrlKey && !e.metaKey && !e.altKey;
        if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "a") {
          e.preventDefault(); selectAllRows(); return;
        }
        if (plain && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
          e.preventDefault(); moveFocus(e.key === "ArrowDown" ? 1 : -1, e.shiftKey); return;
        }
        if (plain && !e.shiftKey && e.key.length === 1 && /[\p{L}\p{N}]/u.test(e.key)) {
          e.preventDefault(); jumpToLetter(e.key); return;
        }
      }
      if (e.key === "Delete") { e.preventDefault(); deleteSelection(); }
      // 글자를 드래그해 골라 둔 상태면 그 글자를 복사한다(브라우저 기본 동작). 예전엔 늘
      // 게임 복사로 가로채서 Detail의 파일명 같은 글자를 복사할 수 없었다.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c" && !hasTextSelection()) {
        e.preventDefault(); copySelectedRows();
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") { e.preventDefault(); pasteClipboard(); }
    });
  }

  async function init() {
    bindEvents();
    await loadAppSettings();
    await loadCollections();
    renderAll();
    // Collection이 하나도 없어도 선택을 강요하지 않는다 - 빈 메인 화면을 정상적으로
    // 띄우고, "+ Collection"을 사용자가 직접 누르게 한다.
    if (S.collections.length) await openTab(S.collections[0].id);
  }

  if (window.pywebview) init();
  else window.addEventListener("pywebviewready", init);
  // 브라우저에서 직접 열었을 때(목업 모드)는 ready 이벤트가 없다.
  setTimeout(() => { if (!S.collections.length && !$("tabs-bar").firstChild) init(); }, 400);
})();
