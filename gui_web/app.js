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
  // 기본 순서는 사용자 결정: No/File/Title/Description/Status/Rating/Genre/Region.
  const COLUMNS = [
    { id: "no", label: "No.", width: 34, fixed: true },
    { id: "file", label: "File", key: "filename", width: 190 },
    { id: "title", label: "Title", key: "title", width: 220 },
    { id: "desc", label: "Description", key: "desc", width: 390 },
    { id: "status", label: "Status", width: 88, fixed: true },
    { id: "rating", label: "Rating", key: "rating", width: 66 },
    { id: "genre", label: "Genre", key: "genre", width: 120 },
    { id: "region", label: "Region", key: "region", width: 78 },
    { id: "fav", label: "★", key: "favorite", width: 30, fixed: true },
  ];
  const COL_MIN_WIDTH = 50;
  const DEFAULT_COL_WIDTHS = Object.fromEntries(COLUMNS.map((c) => [c.id, c.width]));

  /** 컬럼 폭의 합. 목록이 이보다 좁은 화면에 놓이면 좌우로 스크롤해야 한다. */
  function totalColumnWidth() {
    return visibleColumns().reduce((sum, col) => sum + (S.colWidths[col.id] || col.width), 0) + 16;
  }

  function gridTemplate() {
    if (isCompare()) return COMPARE_COLUMNS.map((c) => c.grid).join(" ");
    return visibleColumns().map((c) => `${S.colWidths[c.id] || c.width}px`).join(" ");
  }

  // ---- 컬럼 순서/표시 ------------------------------------------------------
  // **앱 전체 설정**(Settings > gamelist)이다 - Collection마다 다르게 둘 이유가 없고,
  // 폭은 화면 크기와 데이터에 따라 달라서 지금처럼 Collection별 ui_state에 남긴다.
  // No./Title도 다른 컬럼과 똑같이 순서를 바꾸거나 숨길 수 있다(사용자 결정,
  // 메뉴 정리 §5) - 다만 컬럼이 하나도 안 남는 빈 목록은 막는다(아래 isLastVisible).
  const COLUMN_BY_ID = Object.fromEntries(COLUMNS.map((c) => [c.id, c]));

  function columnName(col) {
    return col.id === "fav" ? "★ Favorite" : col.label;
  }

  /** 저장된 순서/숨김을 현재 컬럼 정의에 맞춰 푼다. 모르는 id는 버리고, 새로 생긴
   * 컬럼은 뒤에 붙인다 - 설정이 옛 버전에서 왔어도 목록이 깨지지 않는다. */
  function columnLayout() {
    const conf = (S.settings && S.settings.gamelist) || {};
    const order = (Array.isArray(conf.order) ? conf.order : [])
      .filter((id, i, all) => COLUMN_BY_ID[id] && all.indexOf(id) === i);
    COLUMNS.forEach((c) => { if (!order.includes(c.id)) order.push(c.id); });
    const hidden = new Set((Array.isArray(conf.hidden) ? conf.hidden : [])
      .filter((id) => COLUMN_BY_ID[id]));
    return { order, hidden };
  }

  /** 지금 보이는 컬럼이 이것 하나뿐인가 - 목록이 완전히 빈 화면이 되는 것만 막는다. */
  function isLastVisible(id, order, hidden) {
    return !hidden.has(id) && order.filter((x) => !hidden.has(x)).length <= 1;
  }

  //: Compare는 **한 행이 좌/우 두 항목의 짝**이라 일반 Gamelist와 컬럼 구성이 다르다
  //  (사용자 결정 - "가운데 Gamelist: Source의 File|Title <icon> Target의 File|Title").
  //  폭은 `fr`이다 - 창을 늘리면 Detail이 아니라 **목록이 늘어나** 더 많은 글자가 보인다.
  const COMPARE_COLUMNS = [
    { id: "no", label: "No.", width: 40, grid: "40px" },
    { id: "srcFile", label: "File", width: 110, grid: "minmax(90px, 1fr)" },
    { id: "srcTitle", label: "Title", width: 170, grid: "minmax(120px, 1.6fr)" },
    { id: "op", label: "", width: 64, grid: "64px" },
    { id: "dstFile", label: "File", width: 110, grid: "minmax(90px, 1fr)" },
    { id: "dstTitle", label: "Title", width: 170, grid: "minmax(120px, 1.6fr)" },
  ];

  function visibleColumns() {
    // 사용자가 정한 순서/숨김은 일반 Gamelist의 것이라 Compare에는 적용하지 않는다.
    if (isCompare()) return COMPARE_COLUMNS;
    const { order, hidden } = columnLayout();
    return order.filter((id) => !hidden.has(id)).map((id) => COLUMN_BY_ID[id]);
  }

  function saveColumnLayout(order, hidden) {
    updateSettings("gamelist", { order: [...order], hidden: [...hidden] });
  }

  function toggleColumn(id, visible) {
    const { order, hidden } = columnLayout();
    if (!visible && isLastVisible(id, order, hidden)) return;
    if (visible) hidden.delete(id); else hidden.add(id);
    saveColumnLayout(order, hidden);
  }

  /** id를 targetId 앞(after면 뒤)으로 옮긴다. */
  function moveColumn(id, targetId, after) {
    if (id === targetId || !COLUMN_BY_ID[id]) return;
    const { order, hidden } = columnLayout();
    const rest = order.filter((x) => x !== id);
    const at = rest.indexOf(targetId) + (after ? 1 : 0);
    rest.splice(Math.max(0, at), 0, id);
    saveColumnLayout(rest, hidden);
  }

  function moveColumnBy(id, delta) {
    const { order } = columnLayout();
    const j = order.indexOf(id) + delta;
    if (j < 0 || j >= order.length) return;
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
  function makeText(text) {
    const node = document.createTextNode(window.RMSI18n ? window.RMSI18n.t(text) : text);
    if (window.RMSI18n) window.RMSI18n.remember(node, text);
    return node;
  }
  function h(tag, props, children) {
    const el = document.createElement(tag);
    if (props) {
      Object.entries(props).forEach(([k, v]) => {
        if (v === undefined || v === null || v === false) return;
        if (k === "class") el.className = v;
        else if (k === "html") el.innerHTML = v;
        else if (k === "style") Object.assign(el.style, v);
        else if ((k === "title" || k === "aria-label" || k === "placeholder") && typeof v === "string" && window.RMSI18n) {
          el.setAttribute(k, window.RMSI18n.t(v));
          window.RMSI18n.rememberAttr(el, k, v);
        }
        else if (k === "dataset") Object.entries(v).forEach(([dk, dv]) => (el.dataset[dk] = dv));
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
        else el.setAttribute(k, v === true ? "" : v);
      });
    }
    (children || []).forEach((c) => {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === "string" || typeof c === "number"
        ? makeText(String(c)) : c);
    });
    return el;
  }
  const clear = (el) => { while (el && el.firstChild) el.removeChild(el.firstChild); };
  const $ = (id) => document.getElementById(id);
  const icon = (name, size) => h("span", { class: "ic", html: window.RMIcons.svg(name, size || 13) });

  /** System 아이콘. **아이콘 팩 PNG(파일명 기반) → 기존 SVG → 범용 아이콘** 순서다.
   *
   * PNG는 `system-icons-50/<system>.png`를 이름 후보 순서대로 시도한다
   * (system-icons-pack.js). 없는 파일은 한 번만 확인하고 결과를 기억해 둔다 -
   * Navigator는 자주 다시 그려지므로 매번 없는 파일을 요청하면 깜빡이고 낭비다. */
  const systemIconFile = new Map();   // "base|key" -> 찾은 파일명 | null(없음)
  /** System 아이콘. `onGeneric`은 전용 그림(PNG/SVG)이 하나도 없어서 범용
   * 카테고리 아이콘으로 떨어질 때만 불린다 - 그 사실을 알아야 하는 곳이 있다
   * (Chromium Hero는 그때 배경 그림을 아예 깔지 않는다). */
  /** 아이콘 크기는 **네 단계뿐이다**(레이아웃 재검토).
   *
   * 예전에는 자리마다 9·11·12·13·14·15·16·17·20·22를 섞어 썼다. 한 줄에 선 두
   * 아이콘의 크기가 1px씩 어긋나면 눈에 딱 집어 말하기는 어려워도 화면 전체가
   * 정돈되지 않은 느낌을 준다(실사용 피드백 - "통일성과 안정감").
   *
   * - xs: 탭 닫기처럼 글자보다 작아야 하는 자리
   * - sm: 버튼·칩 안에 글자와 나란히 서는 곁들이
   * - md: 도구 버튼 하나가 통째로 아이콘일 때(툴바 기본)
   * - lg: 비어 있음을 알리는 자리표시자처럼 혼자 크게 서는 것
   */
  const IC = { xs: 10, sm: 12, md: 14, lg: 18 };

  function systemIcon(name, size, onGeneric) {
    const px = size || 14;
    const key = String(name || "").toLowerCase();
    const holder = h("span", { class: "sys-ic", style: { width: `${px}px`, height: `${px}px` } });
    const fallback = () => {
      clear(holder);
      if (window.RMSystemIcons && window.RMSystemIcons.has(key)) {
        holder.innerHTML = window.RMSystemIcons.svg(key, px);
      } else {
        holder.appendChild(icon("cartridge", Math.max(10, px - 1)));
        if (onGeneric) onGeneric();
      }
    };
    const pack = window.RMSystemIconPack;
    const candidates = pack ? pack.candidates(key) : [];
    const memoKey = `${pack ? pack.base : ""}|${key}`;
    const known = systemIconFile.get(memoKey);
    if (!candidates.length || known === null) { fallback(); return holder; }

    const img = h("img", { class: "sys-raster", alt: "", draggable: "false" });
    let index = known ? candidates.indexOf(known) : 0;
    if (index < 0) index = 0;
    img.addEventListener("load", () => systemIconFile.set(memoKey, candidates[index]));
    img.addEventListener("error", () => {
      index += 1;
      if (index < candidates.length) { img.src = pack.src(candidates[index]); return; }
      systemIconFile.set(memoKey, null);
      fallback();
    });
    img.src = pack.src(candidates[index]);
    holder.appendChild(img);
    return holder;
  }

  /** Chromium Hero의 색 - 콘솔마다 **몸체색(base) + 포인트색(points)** 두 가지를 갖는다.
   *
   * 실물의 인상을 그대로 옮긴 것이다(사용자 결정). SFC는 회색 몸체에 빨·파·노·초
   * 버튼, 패미컴은 베이지에 빨강·금색, 메가드라이브는 검정에 검붉은색·파랑 하는 식.
   * base는 배경 물듦에, points는 제목 옆 세로 바에 쓴다 - 그래서 System을 바꾸면
   * 화면 색이 그 기기의 색으로 바뀐다.
   *
   * **System 하나하나에 지정하지 않는다.** 계열 단위로만 정하고 못 찾으면 테마
   * 기본색으로 떨어진다 - System이 몇 개로 늘어나든 관리할 것은 이 목록뿐이다. */
  const SYSTEM_PALETTES = [
    // 닌텐도 - 거치형
    [/^(snes|superfamicom|satellaview|sufami)/,
      { base: "#9b9ba6", points: ["#c0392f", "#2f6fb5", "#e0b32c", "#3f9e57"] }],
    [/^(nes|famicom|fds|nesh)/, { base: "#d8cbb0", points: ["#b5322c", "#c9a227"] }],
    [/^(n64)/, { base: "#4a4a52", points: ["#2f6fb5", "#3f9e57", "#c0392f", "#e0b32c"] }],
    [/^(gamecube|gc)/, { base: "#5f5490", points: ["#6b5bbd", "#3f9e57"] }],
    [/^(wii|wiiu)/, { base: "#dfe3e8", points: ["#1f9fd8"] }],
    [/^(switch)/, { base: "#3a3a42", points: ["#e4404a", "#2f9fd8"] }],
    // 닌텐도 - 휴대용
    [/^(gb|gbc)/, { base: "#a8ae96", points: ["#8e2f6a", "#3f5aa8"] }],
    [/^(gba)/, { base: "#6b5bbd", points: ["#8e2f6a", "#3f5aa8"] }],
    [/^(nds|n3ds|virtualboy)/, { base: "#c8ccd2", points: ["#c0392f"] }],
    // 세가
    [/^(megadrive|genesis|segacd|megacd|sega32x|32x)/,
      { base: "#2b2b30", points: ["#8e2b2b", "#2f6fb5"] }],
    [/^(mastersystem|sg1000|gamegear)/, { base: "#2b2b30", points: ["#c0392f"] }],
    [/^(saturn)/, { base: "#3a3a42", points: ["#2f6fb5", "#8e8e96"] }],
    [/^(dreamcast)/, { base: "#e2e2e4", points: ["#e8622c", "#2f6fb5"] }],
    // 소니 - 짙은 회색 몸체에 ✕○□△ 네 색
    [/^(ps[x1-5]?$|psx|ps2|ps3|ps4|ps5|psp|psvita|pocketstation|minis)/,
      { base: "#5a6472", points: ["#4a7fd4", "#d6453f", "#d97ab0", "#4fae7a"] }],
    [/^(xbox)/, { base: "#2f2f34", points: ["#5bb85b"] }],
    // 그 외
    [/^(atari|lynx|jaguar)/, { base: "#3a2f28", points: ["#d4452c", "#e07b2a"] }],
    [/^(pcengine|pcfx|supergrafx|turbografx|tg16)/,
      { base: "#d6d2c8", points: ["#e0842c", "#c0392f"] }],
    [/^(neogeo|ngp|ngpc)/, { base: "#2b2b30", points: ["#c8443a", "#e8b93a"] }],
    [/^(amiga|c64|commodore|vic20|plus4|cpc|amstrad|zx|spectrum)/,
      { base: "#6f6f78", points: ["#d4453f", "#e8b93a", "#3f9e57", "#3a6fc4"] }],
    [/^(arcade|mame|fba|fbneo|cps[123]?|naomi|model[23]|daphne|neogeocd)/,
      { base: "#2b2b30", points: ["#c0392f", "#2f6fb5", "#e0b32c", "#3f9e57"] }],
    [/^(dos|windows|pc98|pc88|x68000|fmtowns|steam|scummvm|linux|android|msx)/,
      { base: "#4a5568", points: ["#4a90d9"] }],
  ];

  function systemPalette(name) {
    const key = String(name || "").toLowerCase();
    const hit = SYSTEM_PALETTES.find(([re]) => re.test(key));
    return hit ? hit[1] : null;
  }

  /** Chromium의 빈 영역에 지금 보고 있는 System을 은은하게 깔아 준다(레이아웃 재검토).
   *
   * **새 그림 자산을 만들지 않는다.** Navigator가 쓰는 System 아이콘을 그대로 크게
   * 키워 아주 낮은 투명도로 깐다 - 전용 PNG가 없어 카테고리 아이콘으로 떨어지는
   * System도 이 투명도에서는 "은은한 무늬"로만 읽혀서, 콘솔 사진을 System마다
   * 준비할 때 생기는 "이 System은 지원이 덜 됐나" 하는 인상이 생기지 않는다. */
  /** 제목 왼쪽의 세로 바. 콘솔의 포인트 색을 그대로 나눠 칠해서, System을 바꾸면
   * 이 바 하나로 어느 기기인지 알아본다(사용자 결정 - 예전 아이콘 상자는 제목
   * 크기와 안 맞아 뺐다). 색을 못 찾은 System은 테마 accent 한 줄이다. */
  function pointBar(system) {
    const palette = systemPalette(system);
    const bar = h("div", { class: "cheader-bar", "aria-hidden": "true" });
    const points = palette ? palette.points : null;
    if (points && points.length) {
      const stops = points.map((color, i) =>
        `${color} ${(i / points.length * 100).toFixed(2)}% ${((i + 1) / points.length * 100).toFixed(2)}%`);
      bar.style.background = `linear-gradient(180deg, ${stops.join(", ")})`;
    }
    return bar;
  }

  function headerArt(system) {
    const art = h("div", { class: "cheader-art", "aria-hidden": "true" });
    const palette = systemPalette(system);
    if (palette) {
      art.style.setProperty("--sys-base", palette.base);
      art.style.setProperty("--sys-point", palette.points[0]);
    }
    // **전용 그림이 없으면 배경을 비운다.** 범용 카트리지 아이콘을 크게 깔면
    // 그것이 있는 System마다 똑같은 실루엣이 반복돼서, 은은한 무늬가 아니라
    // "이 System들은 뭔가 빠졌다"는 표시로 읽힌다(프로토타입 검토 결과).
    art.appendChild(systemIcon(system, 62, () => art.classList.add("generic")));
    return art;
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
    navigation: { hideEmptySystems: false, defaultSortPriority: "none" },
    gamelist: { order: [], hidden: [] },
    collections: { order: [], restoreTabs: true, rememberSystem: true },
    //: 마지막으로 열어 둔 탭(앱을 다시 켜면 그대로 되살린다). 떼어 낸 창에서는 쓰지 않는다.
    session: { tabs: [], active: null },
    transfer: { pasteMode: "overwrite", includeRom: true, includeMedia: true, conflict: "ask",
                unmatchedRomMode: "skip", unmatchedRomMetadata: true, unmatchedRomMedia: true, unmatchedRomVideo: true },
    //: Media 탭의 영상(사용자 결정: 소리 켬, 반복 켬, 5초 뒤 자동 재생 - 전부 Settings에서 바꾼다).
    media: { videoMode: "auto", videoDelay: 3, videoSound: true, videoLoop: true, videoVolume: 70 },
    //: Title Prefix/Postfix - 지역별로 제목에 붙일 표시(app/title_affix.py와 같은 기본값).
    //: 기본은 전부 꺼져 있다 - 사용자가 명시적으로 켜야 제목이 바뀐다.
    titleAffix: {
      kr: { enabled: false, mode: "prefix", text: "KR" },
      en: { enabled: false, mode: "prefix", text: "EN" },
      jp: { enabled: false, mode: "prefix", text: "JP" },
      eu: { enabled: false, mode: "prefix", text: "EU" },
      global: { enabled: false, mode: "prefix", text: "WORLD" },
    },
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
    //: Collection마다 마지막으로 보던 자리(Dashboard/목록, 선택, 스크롤). 탭을 오가도 그대로 돌아온다.
    tabState: {},
    headerExpanded: false,
    search: "",
    order: "title",
    descending: false,
    favoritesOnly: false,
    viewMode: "list",          // "list" | "card"
    // 우선 정렬 - null(구분 없음) | rom | metadata | media. 예전 상태 필터
    // (all/metadata/media/missing)는 currentQuery()가 값을 읽지 않아 실제로는
    // 아무것도 걸러내지 못했다(실사용 피드백) - 지금은 목록을 걸러내지 않고
    // "있는 항목을 먼저 보여주는" 1차 정렬로 동작한다.
    sortPriority: null,
    // 컬럼 폭은 사용자가 맞춰 놓는 것이라 Collection별로 기억한다(`ui_state`).
    colWidths: { ...DEFAULT_COL_WIDTHS },
    // Navigator에서 접어 둔 Storage 그룹 - `${collectionId}:${storageId}`. 세션
    // 동안만 기억한다(서버에 저장하지 않는다) - 접힘은 지금 화면을 정리해 두는
    // 용도지 Collection의 영구 설정이 아니다.
    navCollapsed: new Set(),
    // Dashboard에서 정한 Storage별 목표 용량 - {storageId: bytes}. HERO의 용량
    // 그래프도 같은 값을 쓴다(실사용 피드백 §4) - Dashboard를 열지 않아도 목표
    // 대비 상태를 봐야 하므로, ui_state에서 읽어 여기 함께 둔다.
    dashboardTargets: {},
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
    // 작업 잠금·Undo/Redo 상태. 기존 브릿지 호환을 위해 필드명은 유지한다.
    plan: null,
    // Compare Mode(§54-59). compare가 있으면 Gamelist가 비교 목록으로 바뀐다.
    // compareBase는 "기준으로 지정"만 해두고 아직 상대를 안 고른 중간 상태다.
    // 이 Collection의 Frontend가 제공하는 고유 기능(§22).
    adapterActions: [],
    compare: null,
    compareBase: null,
    compareFilter: "all",
    //: 좌/우 Detail이 함께 쓰는 탭(Metadata/Media/ROM) - 한쪽을 바꾸면 반대쪽도 바뀐다.
    compareTab: "metadata",
    //: Compare 미디어 탭에서 체크한 미디어 종류(소문자 키). 있으면 상단 < >는 이 종류만 보낸다.
    compareMediaSel: new Set(),
    //: Archive 목록에서 "다른 버전이 있는 것만" 보고 있는가(사용자 결정 - 유사롬 filter).
    archiveConflictsOnly: false,
  };

  //: Archive는 Collection이 아니지만 같은 Gamelist/Detail UI를 쓴다(스펙 §43).
  //  별도 화면을 만들지 않고 특수한 탭 id 하나로 취급한다.
  const ARCHIVE_ID = "archive";
  const STORAGE_INTERNAL = "internal";   // app/model/collection.py의 같은 상수와 값을 맞춘다.
  const isArchive = () => S.activeId === ARCHIVE_ID;

  const MEDIA_LABEL = {
    "3dboxes": "3DBoxes", backcovers: "BackCovers", covers: "Covers", fanart: "FanArt",
    manuals: "Manuals", marquees: "Marquees", miximages: "Miximages",
    physicalmedia: "PhysicalMedia", screenshots: "Screenshots",
    titlescreens: "TitleScreens", videos: "Videos", wheel: "Wheel",
  };

  const OWNERSHIP_LABEL = {
    internal: "Archive 보관", linked: "원본 연결", mixed: "혼합", none: "파일 없음",
  };

  function ownershipBadge(mode, compact) {
    const value = OWNERSHIP_LABEL[mode] ? mode : "none";
    const glyph = value === "internal" ? "hardDrive"
      : value === "linked" ? "link" : value === "mixed" ? "arrowLeftRight" : "xCircle";
    return h("span", {
      class: `ownership-badge ${value}` + (compact ? " compact" : ""),
      title: value === "internal" ? "Archive 관리 폴더 안의 파일"
        : value === "linked" ? "외부 Collection의 원본 파일을 연결해서 사용"
          : value === "mixed" ? "Archive 보관 파일과 외부 원본 연결이 함께 있음" : "연결된 파일 없음",
    }, [icon(glyph, IC.xs), OWNERSHIP_LABEL[value]]);
  }

  function mediaOwnership(slot) {
    const key = Object.keys(MEDIA_LABEL).find((name) => MEDIA_LABEL[name] === slot.key);
    return key && S.detailState && S.detailState.ownership
      ? S.detailState.ownership.media?.types?.[key] : null;
  }

  const activeDetail = () => S.detail[S.activeId] || null;
  const activeScope = () => S.scope[S.activeId] || { kind: "all" };

  function effectiveSortPriority() {
    if (S.sortPriority !== "desc_language") return S.sortPriority || null;
    const language = (S.settings.general?.language || "ko").toLowerCase();
    return language === "ko" ? "desc_ko" : language === "ja" ? "desc_ja" : "desc_en";
  }

  function currentQuery() {
    const scope = activeScope();
    const query = {
      search: S.search, order: S.order, descending: S.descending,
      favoritesOnly: !!S.favoritesOnly, priority: effectiveSortPriority(),
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
    // 우선 정렬은 Collection별로 기억해 두지 않는다 - Toolbar에서 그때그때
    // 바꾸는 값이고, 새로 열 때는 항상 Settings의 기본값에서 다시 시작한다.
    const defaultPriority = S.settings.navigation.defaultSortPriority || "none";
    S.sortPriority = defaultPriority === "none" ? null
      : (defaultPriority === "desc_ko" || defaultPriority === "desc_en"
          ? "desc_language" : defaultPriority);
    // 한 번도 끄고 켠 적 없는 Collection은 Settings의 "Preview by default"를 따른다.
    S.previewOn = typeof r.data.previewOn === "boolean"
      ? r.data.previewOn : S.settings.appearance.previewDefault !== false;
    // 보기 방식도 기억한다. 이것이 빠져 있어서 Card로 보던 사용자가 앱을 다시 열면
    // 언제나 List로 시작했다 - "재시작하면 Card가 한참 뒤에 나온다"의 정체는 사실
    // "Card 상태가 저장되지 않았다"였다.
    if (r.data.viewMode === "card" || r.data.viewMode === "list") S.viewMode = r.data.viewMode;
    S.dashboardTargets = { ...(r.data.dashboardTargets || {}) };
    if (r.data.scope && (S.settings.collections || {}).rememberSystem !== false) S.scope[collectionId] = r.data.scope;
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
      // 마지막으로 고른 System/Storage - 앱을 다시 켜도 그 자리에서 시작한다.
      scope: S.scope[id] || null,
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

  // ------------------------------------------------------------------
  // 여러 창 (bridge/windows.py) - 메인 창은 Archive와 여러 Collection 탭, 떼어 낸 창은 Collection 하나.
  // ------------------------------------------------------------------
  S.window = { id: "main", role: "main", collectionId: null };
  const isDetached = () => S.window.role === "detached";

  async function loadWindowInfo() {
    const r = await api.windowInfo();
    if (r.ok && r.data) S.window = r.data;
    document.body.classList.toggle("detached-window", isDetached());
  }

  /** 탭을 화면에서만 뺀다. release면 Collection도 닫는다(떼어 낼 때는 새 창이 이어받으므로 닫지 않는다). */
  async function dropTab(id, release) {
    if (release) await api.closeCollection(id);
    S.tabs = S.tabs.filter((t) => t !== id);
    delete S.detail[id];
    delete S.scope[id];
    delete S.tabState[id];
    if (S.activeId === id) {
      S.activeId = S.tabs[0] || null;
      resetList();
      if (S.activeId) await ensureDetail(S.activeId);
    }
    renderAll();
    if (S.activeId) await reloadList();
    rememberSession();
  }

  async function detachTab(id) {
    await flushPendingUiState();
    const r = await api.detachCollection(id);
    if (!r.ok) { showToast(r.error, "error"); return; }
    await dropTab(id, false);
  }

  async function mergeIntoMain() {
    await flushPendingUiState();
    const r = await api.mergeWindow();
    if (!r.ok) showToast(r.error, "error");
  }

  // 다른 창이 보내는 알림(bridge/windows.py WindowManager.broadcast / merge).
  window.__rmsSettingsChanged = (stored) => {
    S.settings = mergeSettings(stored);
    if (window.RMSI18n) window.RMSI18n.setLanguage((S.settings.general && S.settings.general.language) || "ko");
    applyAppearance(S.settings.appearance);
    renderAll();
    if (S.activeId) refreshListGeometry();
    if (S.activeId && S.sortPriority === "desc_language") {
      resetList();
      void reloadList();
    }
  };
  window.__rmsCollectionsChanged = async () => {
    await loadCollections();
    renderAll();
  };
  window.__rmsAdoptCollection = async (id) => {
    await loadCollections();
    await openTab(id);
    showToast("떼어 낸 창의 Collection을 다시 붙였습니다.");
  };

  async function loadAppSettings() {
    const r = await api.getAppSettings();
    S.settings = mergeSettings(r.ok ? r.data : null);
    if (window.RMSI18n) {
      window.RMSI18n.setLanguage((S.settings.general && S.settings.general.language)
        || window.RMSI18n.getLanguage() || "ko");
    }
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
    if (section === "general" && patch && patch.language) {
      if (window.RMSI18n) window.RMSI18n.setLanguage(patch.language);
      if (S.sortPriority === "desc_language") {
        renderFilterBar();
        resetList();
        void reloadList();
      }
    }
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
      renderEmulator: emulatorSettingsEditor,
      renderScraper: scraperSettingsEditor,
      renderArchive: () => archiveSettingsEditor(async () => {
        await loadArchiveConfigured();
        if (isArchive()) {
          await ensureDetail(ARCHIVE_ID);
          resetList();
          renderAll();
          await reloadList();
        }
      }),
      // 확인 버튼이 부른다(실사용 피드백 §7) - 값은 이미 바뀔 때마다 즉시
      // 적용돼 있지만(슬라이더 미리보기 등), 서버 저장은 300ms 묶어서 나간다.
      // "확인을 눌렀는데 화면은 닫혔고 저장은 아직 안 나갔다"가 없도록 그
      // 자리에서 바로 흘려보낸다.
      flush: flushPendingUiState,
    });
  }

  // ------------------------------------------------------------------
  // Archive 설정 (Settings > Archive, Archive 첫 화면의 [Archive 설정])
  async function inspectFolderInBackground(path, onStarted = () => {}) {
    const started = await api.startInspectCollectionFolder(path);
    if (!started.ok) return started;
    const jobId = started.data.jobId;
    onStarted(jobId);
    while (true) {
      const state = await api.jobProgress(jobId);
      if (!state.ok) return state;
      if (state.data.done) return state.data.error
        ? { ok: false, error: state.data.error, cancelled: !!state.data.cancelled }
        : { ok: true, data: state.data.result };
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  // ------------------------------------------------------------------
  /** Archive를 어디에 어떤 형식으로 둘지. **디렉토리가 진실이다** - 여기서 정한 폴더에 그 Frontend의
   * 형식(gamelist/media)으로 항상 저장되고, archive.db는 Revision과 출처만 관리하는 색인이다.
   * Settings 화면과 Archive 첫 화면이 같은 편집기를 쓴다 - 같은 값을 두 곳에서 다르게 다루지 않는다. */
  function archiveSettingsEditor(onApplied) {
    const wrap = h("div", { class: "stg-archive" });
    let lastDiagnostics = "";
    const draw = async () => {
      const [cfgR, feR] = await Promise.all([api.archiveConfig(), api.frontends()]);
      clear(wrap);
      if (!cfgR.ok) { wrap.appendChild(h("div", { class: "stg-info" }, [cfgR.error])); return; }
      const cfg = cfgR.data;
      const frontends = feR.ok ? feR.data : [{ id: "es-de", label: "ES-DE" }];

      const frontendSel = h("select", { class: "stg-control archive-frontend" },
        [h("option", { value: "" }, ["저장 형식 선택"]),
          ...frontends.map((f) => h("option", { value: f.id }, [f.label]))]);
      frontendSel.value = cfg.configured ? cfg.frontend : "";
      const dirInput = h("input", { class: "stg-control stg-text archive-dir", value: cfg.archiveDir,
                                    placeholder: "예: D:\Archives" });
      const romInput = h("input", { class: "stg-control stg-text archive-rom-dir", value: cfg.romDir,
                                    placeholder: "비워 두면 Archive 디렉토리 안에 둡니다" });
      const media = h("input", { type: "checkbox", class: "archive-media-internal" });
      media.checked = !!cfg.mediaInternal;
      const mode = h("select", { class: "stg-control archive-mode" }, [
        h("option", { value: "new" }, ["새 Archive 만들기"]),
        h("option", { value: "existing" }, ["기존 Archive 연결"]),
        h("option", { value: "convert" }, ["기존 Frontend 폴더를 Archive로 사용"]),
      ]);
      if (cfg.configured) mode.value = "existing";
      const folderInfo = h("div", { class: "folder-detection", role: "status" });
      let folderResult = null;
      let inspectRun = 0;
      let inspectJobId = null;
      let inspectPromise = null;
      let apply = null;
      async function inspectArchiveFolder() {
        const run = ++inspectRun;
        if (apply) apply.disabled = true;
        if (inspectJobId) api.cancelJob(inspectJobId);
        inspectJobId = null;
        const path = dirInput.value.trim();
        folderResult = null;
        if (!path) { folderInfo.textContent = "폴더를 고르면 기존 Archive 여부와 저장 형식을 확인합니다."; return; }
        folderInfo.replaceChildren("폴더 구조 확인 중… ", h("button", {
          class: "btn compact", onClick: () => {
            inspectRun++;
            if (inspectJobId) api.cancelJob(inspectJobId);
            folderInfo.textContent = "폴더 확인을 중지했습니다.";
          },
        }, ["중지"]));
        const result = await inspectFolderInBackground(path, (jobId) => {
          if (run !== inspectRun) api.cancelJob(jobId);
          else inspectJobId = jobId;
        });
        if (run !== inspectRun || dirInput.value.trim() !== path) return;
        inspectJobId = null;
        if (!result.ok) { folderInfo.textContent = result.error; return; }
        folderResult = result.data;
        if (apply) apply.disabled = false;
        const detected = folderResult.findings.map((f) => f.frontend.toUpperCase()).join(", ");
        folderInfo.textContent = (folderResult.archive || folderResult.legacyArchive)
          ? `기존 Archive DB를 찾았습니다.${detected ? ` 저장 형식 후보: ${detected}` : " 저장 형식은 직접 확인하세요."}`
          : (detected ? `기존 Frontend 파일 감지: ${detected}. Archive로 사용할 경우 이 폴더에 파일을 쓸 수 있습니다.`
            : "기존 Archive DB가 없습니다. 새 Archive의 저장 형식을 선택하세요.");
        if (folderResult.suggestedFrontend && !cfg.configured) frontendSel.value = folderResult.suggestedFrontend;
      }
      dirInput.addEventListener("change", () => { inspectPromise = inspectArchiveFolder(); });
      const browse = (input, title) => h("button", { class: "btn compact", onClick: async () => {
        const r = await api.pickFolder(title);
        if (r.ok && r.data) { input.value = r.data; input.dispatchEvent(new Event("change")); }
      } }, ["찾아보기"]);
      const rowOf = (key, label, help, control) => h("div", { class: "stg-row", "data-key": key,
        title: help }, [
        h("div", { class: "stg-label" }, [h("div", { class: "stg-name" }, [label]), h("div", { class: "stg-help" }, [help])]),
        control,
      ]);

      wrap.appendChild(h("div", { class: "stg-help" },
        ["Archive는 선택한 게임의 메타데이터·미디어와 변경 이력을 보관합니다. 현재 Collection과 자동 동기화하지 않습니다."]));
      if (!cfg.configured) wrap.appendChild(rowOf("archive.mode", "시작 방법",
        "새 폴더에 만들거나, 기존 Archive DB가 있는 폴더를 연결합니다.", mode));
      wrap.appendChild(rowOf("archive.frontend", "저장 형식",
        "Archive를 어떤 Frontend의 형식으로 둘지 정합니다. 바꾸면 그 형식으로 다시 배치합니다(이전 형식의 파일은 지우지 않습니다).",
        frontendSel));
      wrap.appendChild(rowOf("archive.archiveDir", "Archive 디렉토리",
        "메타데이터(gamelist)와 미디어가 저장될 폴더입니다. 이전에 만든 Archive 폴더를 고르면 그 내용을 읽어 옵니다.",
        h("div", { class: "stg-path" }, [dirInput, browse(dirInput, "Archive 디렉토리")])));
      wrap.appendChild(folderInfo);
      inspectPromise = inspectArchiveFolder();
      wrap.appendChild(rowOf("archive.romDir", "ROM 디렉토리 (선택)",
        "ROM을 둘 폴더입니다. 지정하면 여기에 ROM을 넣고 새로고침해서 Archive에 올릴 수 있고, Collection으로 ROM까지 보낼 수 있습니다.",
        h("div", { class: "stg-path" }, [romInput, browse(romInput, "ROM 디렉토리")])));
      wrap.appendChild(rowOf("archive.mediaInternal", "미디어를 Archive에 보관",
        "켜면 미디어 파일을 Archive 디렉토리로 복사해 둡니다(없는 파일만 복사). 끄면 원본 Collection의 파일을 참조만 합니다.",
        h("label", { class: "stg-toggle-row" }, [media])));

      const status = h("div", { class: "stg-help archive-apply-status" }, [
        cfg.configured ? "" : "Archive 디렉토리를 정하면 사용할 수 있습니다."]);
      const progressHost = h("div", { class: "stg-progress" });
      async function showSharedConflict() {
        const observed = await api.archiveSharedConflictStatus();
        if (!observed.ok) { showToast(observed.error, "error"); return; }
        const busy = { value: false };
        const resolve = async (choice) => {
          if (busy.value) return;
          busy.value = true;
          const result = await api.archiveResolveSharedConflict(choice, observed.data.digest);
          busy.value = false;
          if (!result.ok) { showToast(result.error, "error"); return; }
          if (result.data.status === "conflict") {
            showToast("공유 Archive가 다시 바뀌었습니다. 충돌 내용을 다시 확인하세요.", "warning");
            closeModal();
            return;
          }
          closeModal();
          const backups = result.data.backups || [];
          showToast(`선택한 Archive DB를 적용했습니다. 두 버전의 백업: ${backups.join(" · ")}`, "success");
          if (isArchive()) { resetList(); await reloadList(); renderAll(); }
        };
        showModal("Archive 공유 DB 충돌", h("div", { class: "modal-body" }, [
          h("div", { class: "modal-text" }, [
            "이 PC와 공유 폴더의 Archive가 각각 바뀌었습니다. 선택 전에 두 DB를 백업합니다."]),
          h("div", { class: "modal-hint" }, [
            "이 PC 내용 사용은 공유 폴더를 갱신하고, 공유 내용 사용은 이 PC의 DB를 교체합니다."]),
        ]), [
          h("button", { class: "btn", onClick: closeModal }, ["나중에"]),
          h("button", { class: "btn", onClick: () => resolve("shared") }, ["공유 내용 사용"]),
          h("button", { class: "btn primary", onClick: () => resolve("local") }, ["이 PC 내용 사용"]),
        ]);
      }
      apply = h("button", { class: "btn primary archive-apply" }, ["저장하고 적용"]);
      apply.disabled = !!inspectPromise;
      apply.addEventListener("click", async () => {
        if (inspectPromise) await inspectPromise;
        if (!dirInput.value.trim()) { showToast("Archive 디렉토리를 정하세요.", "warning"); return; }
        if (!frontendSel.value) { showToast("Archive 저장 형식을 선택하세요.", "warning"); return; }
        if (!folderResult || folderResult.path !== dirInput.value.trim()) {
          showToast("Archive 폴더 확인이 끝난 뒤 적용하세요.", "warning"); return;
        }
        if (!cfg.configured && mode.value === "existing"
            && !folderResult.archive && !folderResult.legacyArchive) {
          showToast("이 폴더에서 기존 Archive DB를 찾지 못했습니다.", "warning"); return;
        }
        if (!cfg.configured && mode.value === "new"
            && (folderResult.archive || folderResult.legacyArchive)) {
          showToast("기존 Archive DB가 있습니다. '기존 Archive 연결'을 선택하세요.", "warning"); return;
        }
        if (!cfg.configured && mode.value === "new" && folderResult.findings.length) {
          showToast("기존 Frontend 파일이 있습니다. 폴더 구조를 확인하고 '기존 Frontend 폴더를 Archive로 사용'을 선택하세요.", "warning"); return;
        }
        if (!cfg.configured && mode.value === "convert"
            && (folderResult.archive || folderResult.legacyArchive || !folderResult.findings.length)) {
          showToast("기존 Frontend 파일이 있는 폴더를 선택하세요.", "warning"); return;
        }
        const saved = await api.saveArchiveConfig({
          frontend: frontendSel.value, archiveDir: dirInput.value.trim(),
          romDir: romInput.value.trim(), mediaInternal: media.checked });
        if (!saved.ok) { showToast(saved.error, "error"); return; }
        const started = await api.startArchiveApply();
        if (!started.ok) { showToast(started.error, "error"); return; }
        const done = await pollJob(started.data.jobId, "Archive 정리 중", progressHost);
        if (!done.ok) {
          if (String(done.error || "").includes("자동으로 합칠 수 없습니다")) await showSharedConflict();
          else if (!done.cancelled) showToast(done.error, "error");
          return;
        }
        const d = done.data || {};
        const p = d.projection || {};
        const timing = d.timings || {};
        const scan = d.synced?.timings || {};
        const write = p.timings || {};
        lastDiagnostics = `읽기 ${timing.scanSeconds ?? "?"}초 (메타 ${scan.metadataSeconds ?? "?"}, 미디어 ${scan.mediaSeconds ?? "?"}, ROM ${scan.romSeconds ?? "?"}, DB ${scan.databaseSeconds ?? "?"}) · Frontend ${timing.projectionSeconds ?? "?"}초 (미디어 ${write.mediaSeconds ?? "?"}, gamelist ${write.writeIndexSeconds ?? "?"}) · 공유 DB ${timing.sharedSeconds ?? "?"}초`;
        showToast(`Archive에 ${formatCount(p.entries || 0)}개를 ${formatCount(p.systems || 0)}개 System으로 정리했습니다. (${timing.scanSeconds ?? "?"}초 읽기, ${timing.projectionSeconds ?? "?"}초 쓰기)`
          + (d.imported && d.imported.identities ? ` (이전 Archive ${formatCount(d.imported.identities)}개 가져옴)` : ""));
        if (d.sharedSnapshot?.status === "conflict")
          await showSharedConflict();
        else if (d.sharedSnapshot?.status === "error")
          showToast(`Archive 공유 DB 저장 실패: ${d.sharedSnapshot.error}`, "warning");
        if (onApplied) await onApplied();
        draw();
      });
      const rescan = h("button", { class: "btn archive-rescan", disabled: !cfg.configured },
        ["디렉터리 다시 읽기"]);
      rescan.addEventListener("click", async () => {
        const started = await api.startArchiveRefresh();
        if (!started.ok) { showToast(started.error, "error"); return; }
        const done = await pollJob(started.data.jobId, "Archive 디렉터리 읽기", progressHost);
        if (!done.ok) {
          if (String(done.error || "").includes("자동으로 합칠 수 없습니다")) await showSharedConflict();
          else if (!done.cancelled) showToast(done.error, "error");
          return;
        }
        const scan = done.data?.timings || {};
        lastDiagnostics = `읽기 ${done.data?.scanSeconds ?? "?"}초 (메타 ${scan.metadataSeconds ?? "?"}, 미디어 ${scan.mediaSeconds ?? "?"}, ROM ${scan.romSeconds ?? "?"}, DB ${scan.databaseSeconds ?? "?"})`;
        status.textContent = lastDiagnostics;
        showToast(`Archive 디렉터리 읽기 완료 (${done.data?.scanSeconds ?? "?"}초)`);
        if (done.data?.sharedSnapshot?.status === "conflict")
          await showSharedConflict();
        if (onApplied) await onApplied();
      });
      wrap.appendChild(h("div", { class: "stg-help" },
        ["저장된 DB를 먼저 표시합니다. 파일 변경분은 필요할 때 다시 읽으세요."]));
      if (lastDiagnostics) status.textContent = lastDiagnostics;
      if (cfg.editLock) {
        const lockInfo = h("div", {class: "stg-help"}, [
          `읽기 전용 · ${cfg.editLock.host || "다른 PC"}에서 Archive 편집 중`,
        ]);
        const release = h("button", {class: "btn compact", disabled: !cfg.editLock.token,
          onClick: () => showConfirm("편집 잠금 인계",
            "기존 PC의 편집 앱이 종료되었는지 확인하세요. 실행 중인 편집의 잠금을 해제하면 데이터가 충돌할 수 있습니다.",
            true, async () => {
              const result = await api.archiveReleaseEditLock(cfg.editLock.token, true);
              if (!result.ok) { showToast(result.error, "error"); return; }
              cfg.editLock = null; draw(); showToast("중단된 편집 잠금을 해제했습니다.");
            })}, ["중단된 잠금 해제"]);
        wrap.appendChild(h("div", {class: "archive-config-actions"}, [lockInfo, release]));
      }
      wrap.appendChild(progressHost);
      wrap.appendChild(h("div", { class: "archive-config-actions" }, [status, rescan, apply]));
    };
    draw();
    return wrap;
  }

  function openArchiveSettings() {
    const body = h("div", { class: "modal-body archive-settings" }, [
      archiveSettingsEditor(async () => {
        closeModal();
        await loadArchiveConfigured();
        if (isArchive()) {
          await ensureDetail(ARCHIVE_ID);
          resetList();
          renderAll();
          await reloadList();
        }
      }),
    ]);
    const heading = h("div", { class: "archive-settings-heading" }, [
      h("span", {}, ["Archive 설정"]),
      h("button", { class: "icon-btn", title: "닫기", "aria-label": "닫기",
        onClick: closeModal }, [icon("x", IC.sm)]),
    ]);
    showModal(heading, body, []).classList.add("archive-settings-card");
  }

  /** Settings > Metadata & Media > GameList Columns. 머리글 드래그/우클릭과 같은 값을 바꿔다.
   * 순서는 ☰ 손잡이를 끌어 바꿔다(사용자 결정 - 위/아래 버튼보다 직관적). 손잡이에 초점이
   * 있으면 ↑↓ 키로도 한 칸씨 옥긴다. No./Title도 다른 컴럼과 동일하게 옥기거나 숨길 수
   * 있다 - 마지막 하나 남은 컴럼만 숨김 체크박스가 잠긴다(빈 목록 방지). */
  function columnSettingsEditor() {
    const wrap = h("div", { class: "stg-columns" });
    const draw = (focusId) => {
      clear(wrap);
      const { order, hidden } = columnLayout();
      const list = h("div", { class: "stg-column-list" });
      order.forEach((id) => {
        const col = COLUMN_BY_ID[id];
        const locked = isLastVisible(id, order, hidden);
        const check = h("input", { type: "checkbox", disabled: locked });
        check.checked = !hidden.has(id);
        check.addEventListener("change", () => { toggleColumn(id, check.checked); draw(); });
        const grip = h("button", {
          class: "stg-column-grip", "aria-label": `${columnName(col)} 순서 바꾸기`,
          title: "끌어서 순서 바꾸기 (↑↓ 키도 됩니다)",
        }, ["☰"]);
        const rowEl = h("div", { class: "stg-column-row" + (hidden.has(id) ? " off" : ""), "data-column": id }, [
          grip,
          h("label", { class: "stg-column-name" }, [check, h("span", {}, [columnName(col)])]),
          locked ? h("span", { class: "stg-column-note" }, ["마지막 컴럼"]) : null,
        ]);
        grip.addEventListener("keydown", (e) => {
          if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
          e.preventDefault();
          moveColumnBy(id, e.key === "ArrowUp" ? -1 : 1);
          draw(id);
        });
        grip.addEventListener("pointerdown", (e) => startColumnDrag(e, id, rowEl, list, () => draw()));
        list.appendChild(rowEl);
      });
      wrap.appendChild(list);
      const reset = h("button", { class: "btn compact stg-column-reset" }, ["기본값으로"]);
      reset.addEventListener("click", () => { resetColumns(); draw(); });
      wrap.appendChild(h("div", { class: "stg-column-actions" }, [
        h("span", { class: "stg-help" }, ["☰를 끌어 순서를 바꿉니다. 목록 머리글을 끌거나 우클릭해도 됩니다."]),
        reset,
      ]));
      if (focusId) {
        const again = wrap.querySelector(`.stg-column-row[data-column="${focusId}"] .stg-column-grip`);
        if (again) again.focus();
      }
    };
    draw();
    return wrap;
  }

  /** ☰ 손잡이 끌기. 포인터가 올라간 행의 위/아래 절반에 따라 그 앞/뒤에 놓는다. */
  function startColumnDrag(event, id, rowEl, list, redraw) {
    if (event.button !== 0) return;
    event.preventDefault();
    const rows = [...list.querySelectorAll(".stg-column-row")];
    let target = null;
    let after = false;
    const unmark = () => rows.forEach((r) => r.classList.remove("drop-before", "drop-after"));
    rowEl.classList.add("dragging");
    const onMove = (e) => {
      unmark();
      target = null;
      for (const r of rows) {
        if (r === rowEl) continue;
        const rect = r.getBoundingClientRect();
        if (e.clientY < rect.top || e.clientY >= rect.bottom) continue;
        // No. 앞으로는 못 간다 - No. 위에 놓으면 그 뒤로 간다.
        after = r.dataset.column === "no" || e.clientY > rect.top + rect.height / 2;
        target = r.dataset.column;
        r.classList.add(after ? "drop-after" : "drop-before");
        break;
      }
    };
    const onUp = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      rowEl.classList.remove("dragging");
      unmark();
      if (target) { moveColumn(id, target, after); redraw(); }
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
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

  function closeModal() {
    const root = $("modal-root");
    const beforeClose = root && root.__beforeClose;
    if (root) root.__beforeClose = null;
    if (beforeClose) beforeClose();
    clear(root);
  }

  function showModal(title, bodyEl, actions, { dismissOnBackdrop = false } = {}) {
    const root = $("modal-root");
    clear(root);
    const card = h("div", { class: "modal-card" }, [
      h("div", { class: "modal-title" }, [title]),
      bodyEl,
      h("div", { class: "modal-actions" }, actions),
    ]);
    const overlay = h("div", { class: "modal-overlay" }, [card]);
    if (dismissOnBackdrop) overlay.addEventListener("click", (event) => {
      if (event.target === overlay) closeModal();
    });
    root.appendChild(overlay);
    return card;
  }

  /** Media 타일을 누르면 확대해 보여준다. 일반 설정 창과 달리 바깥 클릭으로도 닫는다.
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
    const card = showModal(label, body, [], { dismissOnBackdrop: true });
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
  // **작업마다 자기 줄이 있다.** 예전에는 진행률 막대가 화면에 하나뿐이라, 복사가 도는 동안 새로고침을
  // 누르면 (뒤에서 기다리는) 스캔 job과 복사 job이 **같은 막대를 번갈아 덮어썼다** - "막힌 작업
  // 대기 중"과 복사 진행률이 번갈아 나타나며 막대가 요동쳤다(실사용 피드백). 이제 job 하나가 줄 하나다.
  const jobRows = new Set();

  /** 진행률 줄을 하나 만든다. 반환한 객체로 갱신하고 지운다. */
  function showJobProgress(title, jobId, host = null) {
    const bar = host || $("job-progress");
    bar.classList.add("show");
    const row = { jobId, host: bar, el: null, fill: null, pct: null, label: null };
    if (bar.classList.contains("scrape-progress")) {
      row.fill = h("div", { class: "job-progress-bar-fill", style: { width: "0%" } });
      row.pct = h("span", { class: "job-progress-pct" }, ["0%"]);
      row.el = h("div", { class: "scrape-progress-line", title }, [
        h("div", { class: "job-progress-bar" }, [row.fill]), row.pct,
      ]);
      bar.appendChild(row.el);
      jobRows.add(row);
      return row;
    }
    const titleNode = h("div", { class: "job-progress-title", title }, [title]);
    let cancel = null;
    if (jobId) {
      cancel = h("button", { class: "job-progress-cancel" }, ["취소"]);
      // 단계가 넘어가며 jobId가 바뀌므로 눌린 시점의 값을 쓴다.
      cancel.addEventListener("click", () => { cancel.disabled = true; api.cancelJob(row.jobId); });
    }
    row.fill = h("div", { class: "job-progress-bar-fill", style: { width: "0%" } });
    row.pct = h("div", { class: "job-progress-pct" }, ["0%"]);
    row.label = h("div", { class: "job-progress-label" }, ["시작 중..."]);
    row.el = h("div", { class: "job-progress-item" }, [
      titleNode, h("div", { class: "job-progress-bar" }, [row.fill]), row.pct,
      row.label, cancel,
    ]);
    bar.appendChild(row.el);
    jobRows.add(row);
    return row;
  }

  function updateJobProgress(row, current, total, label) {
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    row.fill.style.width = pct + "%";
    row.pct.textContent = pct + "%";
    // 문구가 이미 "n/m"으로 끝나면(복사 진행률이 그렇다) 개수를 또 붙이지 않는다 - 같은 숫자가 두 번,
    // 그것도 서로 다른 기준으로 나오면 (1/3)이 무엇의 개수인지 알 수 없다.
    const counted = /\d+\/\d+$/.test(String(label || ""));
    const detail = !label ? `${current}/${total}` : counted ? label : `${label} (${current}/${total})`;
    if (row.label) row.label.textContent = detail;
    row.el.title = detail;
    // 앞에서 막힌 job은 진행률이 아니라 기다리는 중이라는 것이 보이게 한다.
    row.el.classList.toggle("waiting", /^대기 중/.test(String(label || "")));
  }

  function hideJobProgress(row) {
    if (row && row.el) row.el.remove();
    jobRows.delete(row);
    if (row?.host && ![...jobRows].some((entry) => entry.host === row.host))
      row.host.classList.remove("show");
  }

  function pollJob(jobId, title, host = null) {
    return new Promise((resolve) => {          // jobId는 단계가 넘어가며 바뀐다
      const row = showJobProgress(title, jobId, host);
      const tick = async () => {
        const r = await api.jobProgress(jobId);
        if (!r.ok) { hideJobProgress(row); resolve({ ok: false, error: r.error }); return; }
        const job = r.data;
        updateJobProgress(row, job.current, job.total, job.label);
        if (!job.done) { setTimeout(tick, 180); return; }
        // 여러 단계로 나뉜 작업은 단계마다 job이 새로 생긴다. 앞 단계가 끝났다고
        // 멈추면 뒤 단계가 아직 Cache를 쓰는 중에 목록을 그리게 된다 - 개수가
        // 실행할 때마다 달라진다. 후속 job이 있으면 끝까지 따라간다.
        const followUp = job.result && job.result.followUpJobId;
        if (followUp && !job.error) { jobId = followUp; row.jobId = followUp; setTimeout(tick, 60); return; }
        hideJobProgress(row);
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
    if (isDetached()) {
      // 떼어 낸 창: Collection 탭 하나. 닫기는 창 닫기와 같다.
      S.tabs.forEach((id) => {
        const collection = S.collections.find((c) => c.id === id);
        if (!collection) return;
        const tab = h("div", { class: "ctab active detached" }, [icon("gamepad", IC.md),
          h("span", { class: "ctab-name" }, [collection.name])]);
        const close = h("button", { class: "ctab-close", title: "창 닫기" }, [icon("x", IC.xs)]);
        close.addEventListener("click", async (e) => {
          e.stopPropagation();
          await flushPendingUiState();
          api.windowControl("close");
        });
        tab.appendChild(close);
        tab.addEventListener("contextmenu", (e) => { e.preventDefault(); openTabMenu(collection, e); });
        bar.appendChild(tab);
        document.title = `${collection.name} - RetroMeta Studio`;
      });
      return;
    }
    if (S.archiveConfigured) {
    const archiveTab = h("div", { class: "ctab archive" + (isArchive() ? " active" : ""),
      title: "여러 Collection에서 수집한 Metadata 보관소" }, [
      icon("database", IC.md), h("span", { class: "ctab-name" }, ["Archive"]),
    ]);
    archiveTab.addEventListener("click", () => selectTab(ARCHIVE_ID));
    bar.appendChild(archiveTab);
    }

    S.tabs.forEach((id) => {
      const collection = S.collections.find((c) => c.id === id);
      if (!collection) return;
      const tab = h("div", { class: "ctab" + (id === S.activeId ? " active" : "") });
      tab.appendChild(icon("gamepad", IC.md));
      tab.appendChild(h("span", { class: "ctab-name" }, [collection.name]));
      const close = h("button", { class: "ctab-close", title: "닫기" }, [icon("x", IC.xs)]);
      close.addEventListener("click", (e) => { e.stopPropagation(); closeTab(id); });
      tab.appendChild(close);
      tab.addEventListener("click", () => selectTab(id));
      tab.addEventListener("contextmenu", (e) => { e.preventDefault(); openTabMenu(collection, e); });
      tab.addEventListener("mouseenter", () => attachTabTooltip(tab, collection), { once: true });
      bindTabDrag(tab, id);
      bar.appendChild(tab);
    });
    const add = h("button", { class: "ctab-add", title: "Collection 추가" }, [icon("plus", IC.md)]);
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

  /** 탭에 갖다 대면 롬 개수/총 용량/Metadata 경로를 보여준다(사용자 결정, 메뉴 정리 §6).
   * 매번 다시 불러오지 않도록 Collection당 한 번만 조회해 둔다. */
  async function attachTabTooltip(tab, collection) {
    if (!S.tabInfoCache) S.tabInfoCache = {};
    if (!S.tabInfoCache[collection.id]) {
      const r = await api.collectionDetail(collection.id);
      if (!r.ok) return;
      const d = r.data;
      const size = formatBytes((d.totalRomBytes || 0) + (d.totalMediaBytes || 0));
      S.tabInfoCache[collection.id] =
        `롬 개수: ${formatCount(d.totalGames)}개 · 총 용량: ${size} · Metadata: ${d.rootPath || "-"}`;
    }
    tab.title = S.tabInfoCache[collection.id];
  }

  /** Collection 탭 우클릭 - 다른 우클릭과 같은 플로팅 메뉴다(사용자 결정 - 예전의 버튼 대화상자 대신). */
  function openTabMenu(collection, event) {
    const items = [{ label: "Collection 정보…", icon: "info", onSelect: () => openCollectionInfo(collection) }];
    if (isDetached()) {
      items.push({ label: "메인 창으로 합치기", icon: "layoutList", onSelect: mergeIntoMain });
      showContextMenu(menuPoint(event), collection.name, collection.rootPath, items, collection.rootPath);
      return;
    }
    items.push({ label: "새 창으로 분리", icon: "previewPane", onSelect: () => detachTab(collection.id) });
    items.push("separator");
    // Compare는 두 단계다(§54): 한 탭에서 기준을 정하고, 다른 탭에서 그 기준과 비교한다.
    // 기준을 정한 뒤 두 번째 탭을 고르기 전까지는 취소할 방법이 없었다(실사용 버그
    // 리포트) - 기준이 남아 있는 동안은 어느 탭을 우클릭하든 "기준 해제"를 같이 보여준다.
    if (S.compareBase && S.compareBase !== collection.id) {
      const baseName = (S.collections.find((c) => c.id === S.compareBase) || {}).name || "기준";
      items.push({ label: `${baseName}와 비교`, icon: "scale", onSelect: () => runCompare(S.compareBase, collection.id) });
    } else if (!S.compareBase) {
      items.push({ label: "Compare 기준으로 지정", icon: "scale", onSelect: () => {
        S.compareBase = collection.id;
        showToast("비교 기준으로 지정했습니다. 다른 Collection 탭을 우클릭해 비교를 시작하세요.");
      } });
    }
    if (S.compareBase) {
      const baseName = (S.collections.find((c) => c.id === S.compareBase) || {}).name || "기준";
      items.push({ label: `Compare 기준 해제 (${baseName})`, icon: "x", onSelect: () => {
        S.compareBase = null;
        showToast("비교 기준을 해제했습니다.");
      } });
    }
    items.push("separator");
    items.push({ label: "제거…", icon: "trash", danger: true, title: "등록 목록에서만 제거합니다. 실제 파일은 그대로입니다.",
      onSelect: () => showConfirm("Collection 제거", "등록 목록에서 제거합니다. 실제 파일은 삭제되지 않습니다.", true,
        async () => { await api.deleteCollection(collection.id); closeTab(collection.id); await loadCollections(); renderAll(); }) });
    showContextMenu(menuPoint(event), collection.name, collection.rootPath, items, collection.rootPath);
  }

  /** "Collection 정보" - 탭 우클릭의 "이름 변경"/"Convert"를 하나로 묶었다(사용자 결정,
   * 메뉴 정리 §6). "Collection 추가"와 같은 필드 구성으로 지금 값을 보여주고, 이름/Target/
   * 폴더를 그 자리에서 고칠 수 있다. 폴더는 재스캔이 필수라 바꾸기 전에 반드시 경고한다
   * (사용자 결정) - Adapter의 layout()이 매번 collection.root_path를 새로 읽으므로
   * (app/scan/scanner.py), 경로만 바꾸고 재스캔하면 나머지는 스캔이 새로 맞춘다.
   * 기기(MTP) Collection은 폴더 선택창이 다른 경로라 이 화면에서는 다루지 않는다.
   * Convert는 전용 진입점을 없앤 대신 여기서 계속 쓸 수 있게 버튼으로 남겼다(사용자 결정). */
  async function openCollectionInfo(collection) {
    const r = await api.collectionDetail(collection.id);
    const detail = r.ok ? r.data : {};
    const isDevice = !!detail.isDevice;

    const nameInput = h("input", { class: "field-input", value: collection.name });
    const targetSel = h("select", { class: "field-input" }, [
      h("option", { value: "" }, ["자동"]),
      h("option", { value: "windows" }, ["Windows"]),
      h("option", { value: "android" }, ["Android"]),
      h("option", { value: "linux" }, ["Linux"]),
    ]);
    targetSel.value = collection.target || "";

    const metaInput = h("input", { class: "field-input", value: collection.rootPath || "",
                                   disabled: isDevice });
    const romInput = h("input", { class: "field-input", placeholder: "비워두면 Metadata와 같은 폴더",
                                  disabled: isDevice });
    const browse = (input, title) => {
      const btn = h("button", { class: "btn", disabled: isDevice }, [icon("folderOpen", IC.sm), h("span", {}, ["찾아보기"])]);
      btn.addEventListener("click", async () => {
        const res = await api.pickFolder(title);
        if (res.ok && res.data) input.value = res.data;
      });
      return btn;
    };
    const pathNote = isDevice
      ? h("div", { class: "modal-hint" }, ["기기(MTP) Collection의 폴더는 여기서 바꿀 수 없습니다."])
      : h("div", { class: "modal-hint" }, [
          "폴더를 바꾸면 이 Collection을 처음부터 다시 스캔합니다 - System별로 따로 지정해 둔 " +
          "ROM 위치(External Storage 등)는 그대로 둡니다."]);

    const size = formatBytes((detail.totalRomBytes || 0) + (detail.totalMediaBytes || 0));
    const statsRow = h("div", { class: "modal-hint" }, [
      `롬 개수: ${formatCount(detail.totalGames || 0)}개 · 총 용량: ${size} · Frontend: ${collection.frontendLabel || collection.frontend}`,
    ]);

    const convertBtn = h("button", { class: "btn" }, [icon("arrowLeftRight", IC.sm), h("span", {}, ["Convert…"])]);
    convertBtn.addEventListener("click", () => { closeModal(); openConvert(collection); });

    const body = h("div", { class: "modal-body" }, [
      statsRow,
      h("div", { class: "field-label" }, ["이름"]), nameInput,
      h("div", { class: "field-label" }, ["Target"]), targetSel,
      h("div", { class: "field-label" }, ["Metadata 디렉토리"]),
      h("div", { class: "field-row" }, [metaInput, browse(metaInput, "Metadata 폴더 선택")]),
      h("div", { class: "field-label" }, ["ROM 디렉토리 ", h("span", { class: "field-optional" }, ["(선택)"])]),
      h("div", { class: "field-row" }, [romInput, browse(romInput, "ROM 폴더 선택")]),
      pathNote,
      h("div", { class: "field-label" }, ["다른 Frontend로"]), convertBtn,
    ]);

    showModal("Collection 정보", body, [
      h("button", { class: "btn", onClick: closeModal }, ["닫기"]),
      h("button", { class: "btn primary", onClick: async () => {
        const name = nameInput.value.trim();
        const newMeta = metaInput.value.trim();
        const newRom = romInput.value.trim();
        const pathChanged = !isDevice && (newMeta !== (collection.rootPath || "") || newRom);
        const applyRest = async () => {
          if (name && name !== collection.name) await api.renameCollection(collection.id, name);
          if (targetSel.value !== (collection.target || "")) {
            await api.updateCollectionTarget(collection.id, targetSel.value);
          }
        };
        if (!pathChanged) {
          closeModal();
          await applyRest();
          await loadCollections();
          renderAll();
          return;
        }
        showConfirm("폴더 변경", "폴더를 바꾸면 이 Collection을 처음부터 다시 스캔합니다. 계속할까요?",
          false, async () => {
            closeModal();
            await applyRest();
            const pr = await api.updateCollectionPaths(collection.id, newMeta, newRom);
            if (!pr.ok) { showToast(pr.error, "error"); return; }
            await loadCollections();
            renderAll();
            await runScan(collection.id, true);
          });
      } }, ["저장"]),
    ]);
    setTimeout(() => nameInput.focus(), 30);
  }

  /** 떠나기 전에 지금 보던 자리를 기억한다(Dashboard/목록, 선택, 스크롤). 탭을 오가면 예전에는
   * 이 모든 것이 처음으로 돌아갔다(실사용 피드백 - 선택한 위치가 리셋, Dashboard를 보다 다른
   * Collection을 갔다 오면 System으로 돌아감). */
  function rememberTabState() {
    const id = S.activeId;
    if (!id) return;
    const scroll = $("list-scroll");
    S.tabState[id] = {
      view: S.view, selected: [...S.selected], anchor: S.selectAnchor, focused: S.focused,
      scrollTop: scroll ? scroll.scrollTop : 0,
    };
  }

  /** 기억해 둔 자리로 돌아간다. 목록을 다 그린 뒤에 부른다. */
  async function restoreTabState(id) {
    const saved = S.tabState[id];
    if (!saved || S.activeId !== id) return;
    if (saved.view === "dashboard") { await showDashboard(); return; }
    S.selected = new Set(saved.selected || []);
    S.selectAnchor = saved.anchor == null ? null : saved.anchor;
    S.focused = saved.focused == null ? null : saved.focused;
    const scroll = $("list-scroll");
    if (scroll) scroll.scrollTop = saved.scrollTop || 0;
    updateSelectionVisual();
    renderStatusBar();
    if (!isCompare() && saved.focused != null) {
      // resetList()가 이전 탭의 상세를 비우므로, 선택 표시뿐 아니라 마지막으로
      // 포커스한 게임의 상세도 되살린다. 조회는 백그라운드에서 하고 늦은 응답은
      // openDetail()의 activeId/focused 검사로 버린다.
      openDetail({ romUid: saved.focused, romIdentityId: saved.focused });
    }
  }

  /** 열어 둔 탭과 보던 탭을 저장한다 - 앱을 다시 켜면 그대로 되살린다. 떼어 낸 창은 쓰지 않는다. */
  function rememberSession() {
    if (isDetached()) return;
    updateSettings("session", { tabs: S.tabs.filter((t) => t !== ARCHIVE_ID), active: S.activeId });
  }

  let tabSelectionToken = 0;

  async function selectTab(id) {
    if (S.activeId === id) return;
    if (isDetached() && id !== S.window.collectionId) return;
    if (id !== ARCHIVE_ID && !S.tabs.includes(id)) { await openTab(id); return; }
    rememberTabState();
    const token = ++tabSelectionToken;
    S.activeId = id;
    S.view = "list";
    resetList();
    if (id === ARCHIVE_ID) await loadArchiveConfigured();
    if (token !== tabSelectionToken || S.activeId !== id) return;
    await ensureDetail(id);
    if (token !== tabSelectionToken || S.activeId !== id) return;
    // 사용자가 맞춰 놓은 컬럼 폭과 정렬을 먼저 되살린 뒤에 그린다 - 나중에 불러오면
    // 기본값으로 한 번 그렸다가 다시 그려서 화면이 흔들린다.
    await loadUiState(id);
    if (token !== tabSelectionToken || S.activeId !== id) return;
    renderAll();
    await reloadList();
    if (token !== tabSelectionToken || S.activeId !== id) return;
    await refreshPlan();
    await restoreTabState(id);
    rememberSession();
  }

  /** Archive로 보내기 전에 저장할 곳이 정해져 있는지 확인한다. 없으면 설정 창을 띄우고 false. */
  async function ensureArchiveConfigured() {
    const r = await api.archiveConfig();
    if (r.ok && r.data && r.data.configured) return true;
    showToast("Archive 디렉토리를 먼저 정하세요.", "warning");
    openArchiveSettings();
    return false;
  }

  /** Archive 설정이 있는지 - 없으면 빈 화면이 [Archive 설정] 버튼을 보여준다. */
  async function loadArchiveConfigured() {
    const r = await api.archiveConfig();
    S.archiveConfigured = !!(r.ok && r.data && r.data.configured);
    renderTabs();
  }

  async function closeTab(id) {
    // Collection을 닫아도 Cache와 실제 파일은 그대로 둔다(스펙 §2.2).
    await dropTab(id, true);
  }

  async function openTab(id) {
    if (S.tabs.includes(id)) { await selectTab(id); return; }
    if (isDetached() && id !== S.window.collectionId) {
      showToast("떼어 낸 창에는 Collection을 하나만 열 수 있습니다. 메인 창에서 여세요.", "warning");
      return;
    }
    if (S.tabs.length >= MAX_TABS) {
      showToast(`동시에 열 수 있는 Collection은 ${MAX_TABS}개까지입니다.`, "warning");
      return;
    }
    const r = await api.openCollection(id);
    if (!r.ok) { showToast(r.error, "error"); return; }
    rememberTabState();
    S.view = "list";           // 새로 연 탭은 목록에서 시작한다(Dashboard를 보던 채로 열어도)
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
    rememberSession();
  }

  /** 새 Collection의 기본 이름 - Frontend 이름이고, 겹치면 "Pegasus 2"처럼 번호가 붙는다. */
  function defaultCollectionName(base) {
    const taken = new Set((S.collections || []).map((c) => c.name));
    if (!taken.has(base)) return base;
    for (let n = 2; ; n += 1) if (!taken.has(`${base} ${n}`)) return `${base} ${n}`;
  }

  async function ensureDetail(id) {
    if (id === ARCHIVE_ID) {
      // Archive에는 Storage 개념이 없다. Collection 헤더와 같은 모양으로만 맞춘다.
      const [systems, rows] = await Promise.all([
        api.archiveSystems(), api.archiveRows({ limit: 1 }),
      ]);
      S.detail[ARCHIVE_ID] = {
        id: ARCHIVE_ID, name: "Archive", frontendLabel: "보관소",
        target: null, os: null, arch: null, rootPath: "", storages: [],
        systemCount: (systems.ok ? systems.data : []).length,
        totalGames: rows.ok ? rows.data.total : 0,
        archiveSystems: systems.ok ? systems.data : [],
        ownershipSummary: null,
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
    const nameHint = h("div", { class: "modal-hint add-name-hint" });
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
    // **Architecture는 묻지 않는다.** ES-DE Adapter를 포함해 어떤 Frontend도 이
    // 값으로 동작을 바꾸지 않는다(esde_platform()이 쓰는 것은 target/os뿐이다) -
    // 사용자가 기기 아키텍처를 몰라서 "Unknown"으로 넘겨도 되는데, 넘기는 값이
    // 아무 데도 안 쓰인다면 애초에 묻지 않는 것이 맞다(실사용 피드백).
    // Target은 다르다 - esde_platform()이 이 값으로 custom_systems XML의 System
    // 정의(windows/android/linux 템플릿)와 경로 표기를 고른다. 그래서 이것만 남긴다.
    // "Unknown"이라는 이름은 "아무 것도 안 정한다"처럼 읽히지만, 실제로는 조용히
    // Windows(또는 기기 경로가 있으면 Android)로 정해진다(adapters/es_de.py
    // esde_platform() 참고) - 화면에 그 사실이 보이지 않는 게 혼란의 원인이었다
    // (실사용 피드백). 이름과 툴팁으로 실제 동작을 밝힌다.
    const targetSel = h("select", { class: "field-input" }, [
      h("option", { value: "" }, ["자동"]),
      h("option", { value: "windows" }, ["Windows"]),
      h("option", { value: "android" }, ["Android"]),
      h("option", { value: "linux" }, ["Linux"]),
    ]);
    targetSel.title = "정하지 않으면 Windows로 만듭니다(단, 기기 경로가 있는 Storage를 붙이면 Android로 바뀝니다).";
    const frontendSel = h("select", { class: "field-input", id: "add-frontend" },
      [h("option", { value: "" }, ["저장 형식 선택"]),
        ...frontends.map((f) => h("option", { value: f.id }, [f.label]))]);
    const detectionInfo = h("div", { class: "folder-detection", role: "status" },
      ["폴더를 고르면 저장 형식을 확인합니다."]);
    let detectionPath = "";
    let lastDetection = null;
    let detectionRun = 0;
    let detectionJobId = null;
    function showDetectedFolder(data) {
      const findings = data.findings.map((f) =>
        `${(frontends.find((item) => item.id === f.frontend) || {}).label || f.frontend} (${f.evidence}${f.systems.length ? `, 확인된 폴더 ${f.systems.length}개` : ""})`);
      const pathSummary = frontendSel.value === "es-de"
        ? "선택한 폴더: 메타데이터·미디어 기준 경로 · ROM은 아래에서 별도 선택 가능"
        : "선택한 폴더: 저장 형식의 기준 경로";
      detectionInfo.textContent = findings.length
        ? `감지: ${findings.join(" · ")}${data.suggestedFrontend ? "" : " · 형식을 확인해 선택하세요."} · ${pathSummary}`
        : `저장 형식을 판별할 파일이 없습니다. ROM 전용 폴더라면 형식을 직접 선택하세요. · ${pathSummary}`;
    }
    async function inspectSelectedFolder() {
      const run = ++detectionRun;
      if (detectionJobId) api.cancelJob(detectionJobId);
      detectionJobId = null;
      const path = pathInput.value.trim();
      detectionPath = path;
      lastDetection = null;
      if (source !== "local" || !path) {
        detectionInfo.textContent = path ? "기기 경로는 직접 저장 형식을 선택하세요." : "폴더를 고르면 저장 형식을 확인합니다.";
        return;
      }
      detectionInfo.replaceChildren("폴더 구조 확인 중… ", h("button", {
        class: "btn compact", onClick: () => {
          detectionRun++;
          if (detectionJobId) api.cancelJob(detectionJobId);
          detectionInfo.textContent = "폴더 확인을 중지했습니다.";
        },
      }, ["중지"]));
      const result = await inspectFolderInBackground(path, (jobId) => {
        if (run !== detectionRun) api.cancelJob(jobId);
        else detectionJobId = jobId;
      });
      if (run !== detectionRun || source !== "local"
          || detectionPath !== path || pathInput.value.trim() !== path) return;
      detectionJobId = null;
      if (!result.ok) { detectionInfo.textContent = result.error; return; }
      const data = result.data;
      lastDetection = data;
      if (data.suggestedFrontend) frontendSel.value = data.suggestedFrontend;
      syncFrontend();
      showDetectedFolder(data);
    }
    pathInput.addEventListener("change", inspectSelectedFolder);

    const pathLabel = h("div", { class: "field-label" }, ["ROM 디렉토리"]);
    const romLabel = h("div", { class: "field-label" }, ["ROM 디렉토리"]);
    const extRomInput = h("input", { class: "field-input", id: "add-ext-rom-path",
                                     placeholder: "폴더를 선택하세요 (선택)" });
    const extRomLabel = h("div", { class: "field-label" }, [
      "External ROM 디렉토리 ", h("span", { class: "field-optional" }, ["(선택)"]),
    ]);

    // **버튼 하나가 "찾아보기"를 맡는다.** PC/Android는 이미 위 탭에서 고른
    // 뒤라(sourceSeg), 그 아래 필드마다 "찾아보기"와 "기기에서 찾기"를 나란히
    // 두는 것은 같은 일을 하는 버튼 두 개를 보여주는 것과 같았다(실사용 피드백) -
    // source가 local이면 OS 폴더 선택창을, device면 MTP 폴더 탐색기를 연다.
    function browseButton(input, title, alsoName) {
      const btn = h("button", { class: "btn" }, [icon("folderOpen", IC.sm), h("span", {}, ["찾아보기"])]);
      btn.addEventListener("click", async () => {
        if (source === "device") {
          if (!deviceSel.value) { showToast("먼저 기기를 고르세요.", "warning"); return; }
          browseTarget = input;
          browsePath = "mtp://" + deviceSel.value;
          browserBox.hidden = false;
          renderBrowser();
          return;
        }
        const r = await api.pickFolder(title);
        if (!r.ok || !r.data) return;
        input.value = r.data;
        input.dispatchEvent(new Event("change"));
        // 이름은 폴더 이름으로 채우지 않는다(사용자 결정 - ROM 폴더만 고르면 "Roms"가 이름이 됐다).
        // 비워 두면 Frontend 이름이 쓰이고, 그 이름을 입력칸의 안내 문구로 미리 보여 준다.
      });
      return btn;
    }

    const metaBrowse = browseButton(pathInput, "Metadata 폴더 선택", true);
    const romBrowse = browseButton(romInput, "ROM 폴더 선택", true);
    const extRomBrowse = browseButton(extRomInput, "External ROM 폴더 선택", false);
    const metaRow = h("div", { class: "field-row" }, [pathInput, metaBrowse]);
    const romRow = h("div", { class: "field-row" }, [romInput, romBrowse]);
    // External ROM은 **로컬 PC일 때만 있다.** MTP 경로를 일반 Collection의
    // External Storage로 섞으면 그 경로를 로컬 Provider가 읽으려다 조용히 빈
    // 목록만 돌려주므로(storage.for_path가 종류로 갈리고, add_external_storage가
    // 종류 다른 저장소를 거절한다 - bridge/api.py) source가 device일 때는 숨긴다.
    const extRomRow = h("div", { class: "field-row" }, [extRomInput, extRomBrowse]);

    // --- 안드로이드 기기(MTP) -----------------------------------------
    // **저장 위치를 먼저 고른다**(사용자 결정). 기기는 폴더 선택 대화상자로 고를 수
    // 없어서(MTP에는 드라이브 문자가 없다) 여기서 기기를 고르고 폴더를 한 단계씩
    // 열어 본다. 기기 Collection은 Metadata 전용이라 ROM 폴더는 선택 사항이다 -
    // 넣으면 ROM이 "있는 것"으로 보이고, 안 넣으면 gamelist만 다룬다.
    const deviceSel = h("select", { class: "field-input", id: "add-device" });
    const deviceNote = h("div", { class: "field-hint" }, [""]);
    const deviceRow = h("div", { class: "field-block", hidden: true }, [
      h("div", { class: "field-label" }, ["기기"]), deviceSel, deviceNote,
    ]);
    // **탐색기 주소창처럼**(실사용 피드백 - "explorer처럼 더 직관적인 선택을 원한다").
    // 예전엔 "위로" 한 단계씩만 갈 수 있었다 - 세 단계 위로 가려면 세 번 눌러야 했다.
    // 지금은 지나온 경로 전체를 조각(breadcrumb)으로 보여줘서 아무 조상 폴더나 한 번에
    // 누를 수 있고, 현재 폴더 목록도 폴더 먼저 - 파일 - 이름 순으로 정렬해 익숙하게 만든다.
    const breadcrumb = h("div", { class: "mtp-breadcrumb" });
    const upBtn = h("button", { class: "mtp-up-btn", title: "위 폴더로" }, [icon("cornerUpLeft", 14)]);
    const browserList = h("div", { class: "picker-list mtp-list", id: "mtp-browser" });
    const browserHead = h("div", { class: "mtp-browser-head" }, [upBtn, breadcrumb]);
    const browserBox = h("div", { class: "field-block", hidden: true }, [browserHead, browserList]);
    let browseTarget = null, browsePath = null;

    function rowButton(name, sub, iconName, onClick) {
      const row = h("button", { class: "picker-row", title: sub });
      row.appendChild(icon(iconName, 14));
      row.appendChild(h("div", { class: "picker-main" }, [h("div", { class: "picker-name" }, [name])]));
      row.addEventListener("click", onClick);
      return row;
    }

    /** `mtp://키/a/b` -> 주소창 조각들. 조각을 누르면 그 자리로 바로 이동한다. */
    function renderBreadcrumb(fullPath) {
      breadcrumb.replaceChildren();
      const parts = fullPath.replace(/^mtp:[\\/]{1,2}/i, "").split("/").filter(Boolean);
      if (!parts.length) return;
      const device = (S.mtpDevices || []).find((d) => d.key === parts[0]);
      const labels = [device ? device.name : parts[0], ...parts.slice(1)];
      let acc = "mtp://" + parts[0];
      labels.forEach((label, i) => {
        if (i > 0) { acc += "/" + parts[i]; }
        const target = acc;
        const isLast = i === labels.length - 1;
        const seg = h("button", { class: "mtp-crumb" + (isLast ? " current" : ""), disabled: isLast }, [label]);
        if (!isLast) seg.addEventListener("click", () => { browsePath = target; renderBrowser(); });
        breadcrumb.appendChild(seg);
        if (!isLast) breadcrumb.appendChild(h("span", { class: "mtp-crumb-sep" }, [icon("chevronRight", 11)]));
      });
    }

    async function renderBrowser() {
      browserList.replaceChildren();
      browserList.appendChild(h("div", { class: "empty-msg mtp-loading" }, ["불러오는 중…"]));
      upBtn.disabled = true;
      const r = await api.mtpBrowse(browsePath);
      if (browsePath === null) return;   // 그 사이에 창이 닫혔다.
      browserList.replaceChildren();
      if (!r.ok) { browserList.appendChild(h("div", { class: "empty-msg" }, [r.error])); return; }
      const data = r.data;
      renderBreadcrumb(data.path);
      upBtn.disabled = !data.parent;
      upBtn.onclick = () => { if (data.parent) { browsePath = data.parent; renderBrowser(); } };
      const entries = [...(data.entries || [])].sort((a, b) =>
        a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }));
      if (!entries.length) {
        browserList.appendChild(h("div", { class: "empty-msg" }, ["(하위 폴더가 없습니다)"]));
      }
      entries.forEach((entry) => browserList.appendChild(
        rowButton(entry.name, entry.path, "folderOpen", () => { browsePath = entry.path; renderBrowser(); })));
      browserList.appendChild(h("button", { class: "btn primary", id: "mtp-pick-here",
        onClick: () => {
          browseTarget.value = browsePath;
          if (browseTarget === pathInput && !nameInput.value.trim()) {
            const device = (S.mtpDevices || []).find((d) => d.key === deviceSel.value);
            nameInput.value = device ? device.name : "";
          }
          browserBox.hidden = true;
        } }, ["이 폴더 선택"]));
    }

    async function autoFindEsde() {
      const r = await api.mtpFindEsde(deviceSel.value);
      if (!r.ok) return;
      const found = (r.data.esde || [])[0];
      if (found) pathInput.value = found.path;
      const device = (S.mtpDevices || []).find((d) => d.key === deviceSel.value);
      if (device && !nameInput.value.trim()) nameInput.value = device.name;
      deviceNote.textContent = found
        ? "ES-DE 폴더를 찾았습니다. 다르면 '찾아보기'로 고르세요."
        : "ES-DE 폴더를 못 찾았습니다. '찾아보기'로 직접 고르세요.";
    }

    async function loadDevices() {
      const r = await api.mtpDevices();
      const data = r.ok ? r.data : { devices: [], reason: r.error };
      S.mtpDevices = data.devices || [];
      deviceSel.replaceChildren(...S.mtpDevices.map((d) => h("option", { value: d.key }, [d.name])));
      // 기기가 없으면 이유를 함께 보여준다 - 빈 목록만 보이면 무엇을 해야 할지 모른다.
      deviceNote.textContent = S.mtpDevices.length
        ? "기기의 ES-DE 폴더를 자동으로 찾습니다."
        : (data.reason || "연결된 기기가 없습니다. USB를 파일 전송(MTP) 모드로 두고 기기 화면에서 허용을 눌러주세요.");
      if (S.mtpDevices.length) await autoFindEsde();
    }
    deviceSel.addEventListener("change", autoFindEsde);

    const sourceSeg = h("div", { class: "seg", id: "add-source" });
    let source = "local";
    // **탭이다 - 버튼이 아니다**(실사용 피드백). 둘 중 하나를 고르는 것이지 각각
    // 독립된 동작을 거는 것이 아니므로, Detail 패널 탭과 같은 언더바 방식을 쓰고
    // 폭을 동률로 맞춘다(.source-tabs, studio.css) - 라벨 길이가 서로 달라도
    // 같은 무게로 보여야 "둘 중 하나"라는 게 한눈에 들어온다.
    const sourceBtn = (value, label, iconName) => {
      const btn = h("button", { class: "seg-btn" + (value === source ? " on" : ""),
                                "data-source": value }, [icon(iconName, 12), h("span", {}, [label])]);
      btn.addEventListener("click", () => { source = value; syncSource(); });
      return btn;
    };
    sourceSeg.appendChild(sourceBtn("local", "이 PC", "hardDrive"));
    sourceSeg.appendChild(sourceBtn("device", "Android (MTP)", "smartphone"));

    function syncSource() {
      const device = source === "device";
      sourceSeg.querySelectorAll(".seg-btn").forEach((btn) =>
        btn.classList.toggle("on", btn.dataset.source === source));
      deviceRow.hidden = !device;
      if (!device) browserBox.hidden = true;
      inspectSelectedFolder();
      romInput.placeholder = device
        ? "ROM 폴더 (선택 - 넣으면 ROM 파일도 확인합니다)"
        : "폴더를 선택하세요 (선택)";
      // External Storage는 로컬 파일시스템 개념이다 - MTP 경로를 여기 섞으면
      // add_external_storage가 거절한다(종류가 다른 저장소, bridge/api.py).
      extRomLabel.hidden = extRomRow.hidden = device;
      if (device) {
        targetSel.value = "android";
        // 비어 있으면 다시 시도한다 - 첫 시도가 실패했을 때(기기를 나중에 꽂았거나 허용을
        // 늦게 눌렀을 때) 앱을 다시 켜야만 목록이 나오는 것은 곤란하다.
        if (!S.mtpDevices || !S.mtpDevices.length) loadDevices();
      }
    }

    // 긴 설명을 필드 아래 줄줄이 적지 않는다 - hover하면 뜨는 title 툴팁 하나로
    // 충분하다. 항상 보이는 문장이 아니라 필요할 때만 보이는 문장으로 정책을 맞춘다.
    /** 이름을 비워 두면 쓰일 이름을 입력칸 아래에 보여 준다. */
    function syncNamePlaceholder() {
      const label = (frontends.find((f) => f.id === frontendSel.value) || {}).label;
      nameHint.textContent = label
        ? `비워 두면 "${defaultCollectionName(label)}"(으)로 만듭니다.`
        : "저장 형식을 고르면 기본 이름을 제안합니다.";
    }

    function syncFrontend() {
      syncNamePlaceholder();
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
    frontendSel.addEventListener("change", () => {
      syncFrontend();
      if (lastDetection) showDetectedFolder(lastDetection);
    });
    syncFrontend();
    syncSource();

    const advancedBody = h("div", {}, [
      h("div", { class: "field-label" }, ["Target"]), targetSel,
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
      row.appendChild(icon("gamepad", IC.md));
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
      h("div", { class: "field-label" }, ["저장 위치"]), sourceSeg,
      deviceRow,
      pathLabel, metaRow,
      detectionInfo,
      h("div", { class: "field-label" }, ["저장 형식"]), frontendSel,
      romLabel, romRow,
      extRomLabel, extRomRow,
      browserBox,
      h("div", { class: "field-label" }, ["이름"]), nameInput, nameHint,
      advanced,
      history,
    ]);

    showModal("Collection 추가", body, [
      h("button", { class: "btn", onClick: closeModal }, ["Cancel"]),
      h("button", { class: "btn primary", id: "add-collection-submit", onClick: async () => {
        const metaPath = pathInput.value.trim();
        const romPath = romRow.hidden ? "" : romInput.value.trim();
        const extRomPath = extRomRow.hidden ? "" : extRomInput.value.trim();
        // 둘 다 선택 사항이다. Metadata만 있어도, ROM만 있어도 정상적인 Collection이다
        // - 스크래핑을 한 번도 안 한 컬렉션이 후자의 모습이다. 유효하지 않은 것은
        // 둘 다 비었을 때뿐이다.
        if (!metaPath && !romPath) {
          showToast("Metadata 디렉토리와 ROM 디렉토리 중 하나는 선택하세요.", "warning");
          return;
        }
        if (!frontendSel.value) { showToast("저장 형식을 선택하세요.", "warning"); return; }
        // 이름을 안 적었으면 **선택한 Frontend 이름**이 기본이다(사용자 결정 - Pegasus처럼 ROM 폴더만 고르면
        // 폴더 이름("Roms")이 이름이 되어 무엇인지 알 수 없었다). 같은 이름이 이미 있으면 번호를 붙인다.
        const name = nameInput.value.trim() || defaultCollectionName(
          (frontends.find((f) => f.id === frontendSel.value) || {}).label || frontendSel.value);
        closeModal();
        // 기기 Collection의 Storage는 "Internal"이 아니라 기기 이름으로 보여야 한다.
        const device = source === "device"
          ? (S.mtpDevices || []).find((d) => d.key === deviceSel.value) : null;
        const r = await api.createCollection(name, frontendSel.value, metaPath || null,
                                             targetSel.value || null, null,
                                             romPath || null, "", device ? device.name : null);
        if (!r.ok) { showToast(r.error, "error"); return; }
        await loadCollections();
        // External ROM 디렉토리를 함께 넣었으면 만들자마자 Storage로 붙인다 - 안 그러면
        // 사용자가 이 경로를 여기서 이미 알려 줬는데도 Navigator에서 "Add External
        // Storage"를 다시 눌러 똑같은 경로를 한 번 더 찾아야 했다(실사용 피드백).
        if (extRomPath) {
          // Internal의 기본 이름이 그냥 "Internal"인 것과 맞춘다(실사용 피드백 -
          // "Internal은 Internal인데 External은 왜 External ROMs인가"). 나중에
          // Storage 설정에서 언제든 바꿀 수 있다.
          const ext = await api.addExternalStorage(r.data.id, "External", extRomPath);
          if (ext.ok) await api.attachStorageSystems(r.data.id, ext.data);
          else showToast(`External ROM 디렉토리는 추가하지 못했습니다: ${ext.error}`, "warning");
        }
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
    // 제목은 **글자다 - 그림이 아니다**(사용자 결정 - 구워 둔 픽셀 글자 그림은 열화가 심했다).
    // 글자로 그리면 어떤 배율에서도 또렷하고, 색과 외곽선을 테마에 맞춰 바꿀 수 있다.
    // 대문자 R/M/S와 i의 꼭지에 빨/노/녹/파를 넣어 레트로 느낌을 낸다(사용자 결정).
    const letter = (text, cls) => h("span", cls ? { class: cls } : {}, [text]);
    top.appendChild(h("div", { class: "nav-app-title" }, [
      // 카트리지 그림은 사용자가 만든 것을 그대로 쓴다(tools/make_branding.py) -
      // 제목+부제를 합친 높이에 맞춘다(CSS의 .nav-app-icon).
      // 6등분한 칸 중 **맨 왼쪽 한 칸**이 아이콘 자리다(사용자 결정) - 그 칸의 절반 크기로
      // 가운데 맞춘 정사각형이다. 카트리지는 가로가 길어서 정사각형 안에 맞춰 넣는다(object-fit).
      h("div", { class: "nav-app-icon-cell" },
        [h("img", { class: "nav-app-icon", src: "app-icon.png", alt: "" })]),
      h("div", { class: "nav-app-title-text" }, [
        h("div", { class: "nav-app-title-name", "aria-label": "RetroMeta Studio" }, [
          letter("R", "apt-r"), letter("etro"), letter("M", "apt-m"), letter("eta"),
          // **한 줄이다**(사용자 결정 - 두 줄로 키웠더니 글씨가 너무 컸다). 가운데 네 칸(66%)에
          // 들어갈 크기로 줄인다.
          letter(" "),
          letter("S", "apt-s"), letter("tud"),
          // i의 **꼭지만** 파랗게 칠한다 - 꼭지 없는 ı(U+0131)를 쓰고 네모 점을 따로 얹는다.
          // 서체 안의 점은 따로 색을 줄 수 없기 때문이다. 읽어 주는 이름은 위 aria-label이 맡는다.
          h("span", { class: "apt-i" }, ["ı"]),
          letter("o"),
        ]),
        // 부제(사용자 결정) - 제목보다 훨씬 작게, 한 줄로.
        h("div", { class: "nav-app-subtitle" }, ["Retro Game Metadata Editor"]),
      ]),
    ]));
    return top;
  }

  /** Navigator 최하단 고정 줄 - Dashboard와 Settings.
   *
   * **Settings가 상단에서 여기로 내려왔다**(사용자 결정). 로고가 상단 띠를 꽉
   * 채우면서 톱니가 설 자리가 없어졌는데, 창 컨트롤(─ㅁ✕) 옆은 OS 영역이라
   * 오해를 부르고 하단 Status Bar는 Collection 정보 자리다. Dashboard는 "앱
   * 전체"를 다루는 같은 층위라 나란히 두는 것이 가장 자연스럽다. */
  function navDashboardRow() {
    const dash = h("button", {
      class: "nav-dashboard" + (S.view === "dashboard" ? " active" : ""),
      title: S.view === "dashboard" ? "목록으로 돌아가기" : "Collection Dashboard",
    }, [icon("dashboard", IC.md), h("span", {}, ["Dashboard"])]);
    dash.addEventListener("click", () => (S.view === "dashboard" ? showList() : showDashboard()));

    const settings = h("button", { class: "icon-btn settings-btn", title: "Settings" },
                       [icon("settings", IC.md)]);
    settings.addEventListener("click", () => openSettings());
    return h("div", { class: "nav-bottom" }, [dash, settings]);
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
      nav.appendChild(navDashboardRow());
      return;
    }
    // **All / Favorites는 System이 아니다.** 예전에는 셋을 한 목록에 섞어 놓아서
    // "All"이 System 이름들 사이에 낀 또 하나의 System처럼 보였다(사용자 피드백).
    //
    // 맨 위 띠(.nav-eyebrow)는 **Toolbar와 아래 선을 맞춰야 하는 고정 높이 띠**라
    // (레이아웃 재검토 §18, tests_ui/layout-bands), 그 위에는 아무것도 못 끼운다.
    // **라벨은 "SYSTEMS"다.** 예전엔 "NAVIGATOR"였고 그 아래 스크롤 안에 또
    // "SYSTEMS" 머리가 있어 같은 뜻의 글자가 두 번 보였다(실사용 피드백 - "아래
    // Systems는 중복") - 이제 이 한 줄이 전부고, 빈 System 숨기기 토글도 여기로
    // 옮겨 그 중복을 없앴다.
    const eyebrow = h("div", { class: "nav-eyebrow" }, [h("span", { class: "nav-eyebrow-label" }, ["SYSTEMS"])]);
    nav.insertBefore(eyebrow, scroll);
    // 관점 칸. 스크롤되지 않는다 - System이 아무리 많아도 늘 같은 자리에 있다.
    const lens = h("div", { class: "nav-lens" });
    nav.insertBefore(lens, scroll);

    const scope = activeScope();
    if (isArchive()) {
      const all = navRow("All", detail.totalGames, scope.kind === "all" && !S.favoritesOnly, () => {
        S.favoritesOnly = false;
        setScope({ kind: "all" });
      });
      all.classList.add("nav-all");
      all.insertBefore(icon("database", IC.md), all.firstChild);
      lens.appendChild(all);
      const favorites = navRow("Favorites", null, !!S.favoritesOnly, () => {
        S.favoritesOnly = true;
        setScope({ kind: "all" });
      });
      favorites.classList.add("nav-favorites");
      favorites.insertBefore(icon("star", IC.md), favorites.firstChild);
      lens.appendChild(favorites);
      (detail.archiveSystems || []).forEach((sys) => {
        const row = navRow(sys.system.toUpperCase(), sys.count,
          scope.kind === "system" && scope.id === sys.system,
          () => setScope({ kind: "system", id: sys.system }));
        row.classList.add("nav-system");
        row.insertBefore(systemIcon(sys.system, 18), row.firstChild);
        // 예전엔 이 줄에 우클릭이 아예 안 걸려 있었다 - "prefix 붙이기도 안 된다"는
        // 지적의 진짜 원인이었다(메뉴 자체가 안 뜸). Collection의 System 메뉴 중
        // Archive 데이터만으로 계산 가능한 것만 옮긴다(아래 openArchiveSystemMenu).
        row.addEventListener("contextmenu", (e) => { e.preventDefault(); openArchiveSystemMenu(sys, e); });
        scroll.appendChild(row);
      });
      nav.appendChild(navDashboardRow());
      return;
    }
    const allRow = navRow("All Games", detail.totalGames,
      scope.kind === "all" && !S.favoritesOnly, () => {
        S.favoritesOnly = false;
        setScope({ kind: "all" });
      });
    allRow.classList.add("nav-all");
    allRow.insertBefore(icon("layoutList", IC.md), allRow.firstChild);
    lens.appendChild(allRow);

    // 즐겨찾기는 System을 가로지르는 관점이라 여기 있어야 한다 - Toolbar의 ☆
    // 토글과 같은 값(S.favoritesOnly)을 바꾼다. 두 곳이 서로 다른 상태를 갖지 않는다.
    const favRow = navRow("Favorites", null, !!S.favoritesOnly, () => {
      S.favoritesOnly = true;
      setScope({ kind: "all" });
    });
    favRow.classList.add("nav-favorites");
    favRow.insertBefore(icon("star", IC.md), favRow.firstChild);
    lens.appendChild(favRow);

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
    const pendingMoves = {};
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
    // SYSTEMS 띠 자체가 이 토글이 거는 목록의 이름이므로 그 자리에 둔다(사용자 결정).
    eyebrow.appendChild(hideToggle);

    function renderSystemRow(sys) {
      const row = navRow(sys.system.toUpperCase(), sys.count,
        scope.kind === "system" && scope.id === sys.system,
        () => setScope({ kind: "system", id: sys.system }));
      row.classList.add("nav-system");
      row.insertBefore(systemIcon(sys.system, 18), row.firstChild);
      if (!sys.count) row.classList.add("empty");
      if (sys.conflict && sys.conflict.length) {
        row.classList.add("conflict");
        const where = sys.conflict.map((c) => `${c.label}: ${c.path}`).join("\n");
        row.insertBefore(h("span", {
          class: "nav-conflict",
          title: `같은 System 폴더가 여러 Storage에 있어 쓰기가 막혔습니다.\n${where}\n우클릭에서 한쪽 폴더를 지우거나 이름을 바꾸세요.`,
        }, ["!"]), row.lastChild);
      }
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
        // Gamelist에서 끌어온 게임을 이 System으로 옮긴다(Storage 이동 드래그와 섞이지 않게
        // 게임 쪽만의 데이터 종류를 쓴다).
        row.addEventListener("dragover", (e) => {
          if (![...e.dataTransfer.types].includes(GAME_DRAG_TYPE)) return;
          e.preventDefault();
          e.stopPropagation();
          row.classList.add("drop-target");
        });
        row.addEventListener("dragleave", () => row.classList.remove("drop-target"));
        row.addEventListener("drop", (e) => {
          const raw = e.dataTransfer.getData(GAME_DRAG_TYPE);
          if (!raw) return;
          e.preventDefault();
          e.stopPropagation();
          row.classList.remove("drop-target");
          dropGamesOnSystem(raw, sys.system);
        });
      }
      return row;
    }

    if (!externalStorages.length) {
      (detail.systems || []).filter(visibleSystem).forEach((sys) => scroll.appendChild(renderSystemRow(sys)));
    } else {
      (detail.storages || []).forEach((storage) => {
        const group = h("div", { class: "nav-group" });
        const collapsed = S.navCollapsed.has(`${S.activeId}:${storage.id}`);
        // 접기 화살표 - 왼쪽(사용자 결정). System이 많은 Storage를 접어 두면
        // 다른 Storage를 보려고 스크롤할 거리가 줄어든다.
        const chevron = h("button", { class: "icon-btn nav-group-chevron",
          title: collapsed ? "펼치기" : "접기" }, [icon(collapsed ? "chevronRight" : "chevronDown", IC.sm)]);
        chevron.addEventListener("click", (e) => {
          e.stopPropagation();
          const key = `${S.activeId}:${storage.id}`;
          if (S.navCollapsed.has(key)) S.navCollapsed.delete(key); else S.navCollapsed.add(key);
          renderNav();
        });
        const head = h("div", { class: "nav-group-head" },
          [chevron, h("span", { class: "nav-group-name" }, [storage.label.toUpperCase()])]);

        // **Internal도 External도 같은 설정 버튼 하나다**(실사용 피드백 - "External만
        // Setting이 있는 것도 이상하다"). update_storage는 이미 Internal의 이름/
        // Android 경로를 받는다 - PC 경로만 External에서만 뜻이 있다(Internal의
        // PC 경로는 Collection 경로 자체라 여기서 바꿀 자리가 아니다).
        if (!isCompare()) {
          const gear = h("button", { class: "icon-btn storage-settings-btn", title: `${storage.label} 설정` },
                         [icon("settings", IC.sm)]);
          gear.addEventListener("click", (e) => { e.stopPropagation(); openStorageSettings(storage); });
          head.appendChild(gear);
        }
        // External을 지우면 그 System들을 Internal로 되돌린다(사용자 결정).
        if (storage.kind === "external" && !isCompare()) {
          const remove = h("button", { class: "icon-btn storage-remove-btn", title: `${storage.label} 제거` },
                           [icon("trash", IC.sm)]);
          remove.addEventListener("click", (e) => { e.stopPropagation(); confirmRemoveExternalStorage(storage); });
          head.appendChild(remove);
        }
        group.appendChild(head);
        if (collapsed) { scroll.appendChild(group); return; }

        if (!isCompare()) {
          const systemNames = (detail.systems || [])
            .filter((sys) => sys.storageId === storage.id).map((sys) => sys.system);
          head.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            openStorageGroupMenu(storage, systemNames, e);
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
    // 밖(고정 영역)에 둔다. **이미 External이 있으면 숨긴다**(사용자 결정) - 이
    // Collection이 쓰는 External은 하나뿐이라고 본다. 더 필요하면 먼저 지우고
    // 다시 추가한다(그룹 머리의 제거 버튼).
    if (!isCompare() && detail && !detail.metadataOnly) {
      // 빈 System을 만든다(사용자 결정) - 이름을 넣으면 그 이름의 빈 폴더가 생긴다.
      const addSystem = h("button", { class: "nav-action nav-add-system" },
        [icon("plus", IC.sm), h("span", {}, ["Add System"])]);
      addSystem.addEventListener("click", openCreateSystem);
      nav.appendChild(addSystem);
    }
    if (!isCompare() && !externalStorages.length) {
      const add = h("button", { class: "nav-action" }, [icon("plus", IC.sm), h("span", {}, ["Add External Storage"])]);
      add.addEventListener("click", openAddStorage);
      nav.appendChild(add);
      // gamelist 만들기는 Toolbar 아이콘(Collection 전체) + System/Storage 우클릭
      // 메뉴(부분)로 옮겼다 - 예전엔 이 버튼 하나뿐이었다.
    }
    nav.appendChild(navDashboardRow());
  }

  function navRow(label, count, active, onClick) {
    // count가 null이면 숫자 칸을 비운다 - Favorites처럼 목록을 다 읽기 전에는
    // 개수를 알 수 없는 줄이 "0"으로 보이면 안 된다.
    const row = h("div", { class: "nav-row" + (active ? " active" : "") }, [
      h("span", { class: "nav-label" }, [label]),
      h("span", { class: "nav-count" }, [count == null ? "" : formatCount(count)]),
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
    saveUiState();
    await reloadList();
  }

  /** 선택/포커스를 비운다. Collection이나 System이 바뀌면 반드시 거쳐야 한다. */
  function clearSelection() {
    S.selected.clear();
    S.selectAnchor = null;
    S.focused = null;
  }

  //: Gamelist에서 끌어온 게임임을 알리는 데이터 종류. Storage 이동 드래그("text/plain")와
  //: 섞이면 System 행에 System을 떨어뜨렸을 때 게임 이동으로 오인한다.
  const GAME_DRAG_TYPE = "application/x-rms-games";

  /** 끌어온 게임들을 그 System으로 옮긴다 - ROM+메타데이터+미디어가 함께 간다(Plan 경유). */
  async function dropGamesOnSystem(raw, targetSystem) {
    let uids = [];
    try { uids = JSON.parse(raw) || []; } catch (_) { return; }
    if (!uids.length) return;
    await runImmediateAction("move", { romUids: uids, system: targetSystem });
  }

  async function moveSystemToStorage(system, storageId) {
    if (blockedInCompare("System을 이동")) return;
    // 독립 미리보기에서 충돌을 결정한 뒤 바로 실행한다.
    await runImmediateAction("storage", { system, storageId });
  }

  function openAddStorage() {
    if (blockedInCompare("Storage를 추가")) return;
    // Internal의 기본 이름이 단순히 "Internal"인 것과 맞춘다(실사용 피드백) - SD
    // 카드가 아닌 외장 HDD/USB로 붙이는 경우가 흔해서 "SD"를 기본값으로 못박아
    // 두면 오히려 고쳐야 할 이름이 된다.
    const labelInput = h("input", { class: "field-input", value: "External" });
    const pathInput = h("input", { class: "field-input", placeholder: "예: E:\\ROMs" });
    const browse = h("button", { class: "btn", onClick: async () => {
      const r = await api.pickFolder("External Storage 폴더");
      if (r.ok && r.data) pathInput.value = r.data;
    } }, [icon("folderOpen", IC.sm)]);
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
        // 그 폴더 밑의 System을 External에 붙인다(사용자 결정: 추가하면 External 밑에 보여야 한다).
        const attached = await api.attachStorageSystems(S.activeId, r.data);
        await ensureDetail(S.activeId);
        renderNav(); renderHeader(); renderStatusBar();
        if (!attached.ok) { showToast(attached.error, "error"); return; }
        const a = attached.data;
        const parts = [];
        if (a.added.length) parts.push(`새 System ${formatCount(a.added.length)}개`);
        if (a.moved.length) parts.push(`External로 옮김 ${formatCount(a.moved.length)}개`);
        if (a.conflicts.length) parts.push(`충돌 ${formatCount(a.conflicts.length)}개 (${a.conflicts.join(", ")})`);
        showToast(parts.length ? `External Storage를 추가했습니다 - ${parts.join(" · ")}`
          : "External Storage를 추가했습니다 - 그 폴더에서 ROM이 든 System 폴더를 찾지 못했습니다.",
          a.conflicts.length ? "warning" : "info");
        if (a.added.length || a.moved.length) await runScan(S.activeId);
      } }, ["추가"]),
    ]);
  }

  /** External Storage 제거(사용자 결정) - System을 Internal로 합친 뒤 지운다.
   *
   * **실제 파일은 옮기지 않는다.** 처음엔 Storage 이동 Plan(planStorageChange +
   * Apply)을 그대로 썼는데, 그건 "그 드라이브에 있던 파일을 전부 복사해라"라는
   * 뜻이라 몇십 GB짜리 External을 지우려다 그만큼을 다시 복사하는 일이 벌어졌다
   * (실사용 피드백 - "실제 롬파일은 유지되는데 표시만 Internal로 합쳐지는 걸로
   * 되어야 한다"). `reassignSystemStorage()`는 지금 파일이 있는 절대 경로를
   * System에 그대로 고정해 두고 배치(storage_id)만 바꾼다 - removeStorage는
   * System이 붙어 있으면 거부하므로(그 System이 가리키던 파일이 붕 뜨는 것을 막기
   * 위해) 이 재배치가 먼저 끝나야 한다.
   */
  async function confirmRemoveExternalStorage(storage) {
    if (blockedInCompare("Storage를 제거")) return;
    const detail = activeDetail();
    const systems = (detail.systems || []).filter((sys) => sys.storageId === storage.id);
    const message = systems.length
      ? `"${storage.label}"을 제거합니다. 이 안의 System ${formatCount(systems.length)}개`
        + `(${systems.map((s) => s.system.toUpperCase()).join(", ")})를 Internal로 합칩니다.`
        + ` 실제 파일은 지금 있는 자리에 그대로 남고, 목록에서의 표시만 바뀝니다.`
      : `"${storage.label}"을 제거합니다. 이 안에는 System이 없습니다.`;
    showConfirm("External Storage 제거", message, true, async () => {
      for (const sys of systems) {
        const r = await api.reassignSystemStorage(S.activeId, sys.system, STORAGE_INTERNAL);
        if (!r.ok) { showToast(r.error, "error"); return; }
      }
      const removed = await api.removeStorage(S.activeId, storage.id);
      if (!removed.ok) { showToast(removed.error, "error"); return; }
      await ensureDetail(S.activeId);
      await runScan(S.activeId);
      resetList();
      renderAll();
      showToast(`"${storage.label}"을 제거했습니다.`);
    });
  }

  /** System 하나의 정보와 Storage 이동(스펙 §10, §471의 System 메뉴).
   *
   * 예전에는 Storage 그룹 사이로 끌어다 놓는 것이 유일한 이동 방법이었다. 그런데
   * Navigation에서 Storage 계층을 없앴으므로(사용자가 보는 단위는 System이다) 드롭할
   * 그룹 자체가 없다. 기능은 그대로 두고 들어가는 문만 옮긴다.
   */
  /** System 우클릭 메뉴 - 게임 행 메뉴와 같은 컨텍스트 메뉴를 쓴다. */
  /** 이 System 전체에 Title Prefix/Postfix를 적용하면 뭐라도 바뀌는 게 있는지. 없으면
   * 메뉴 항목 자체를 고를 수 없게 한다(사용자 결정) - 눌러서 "바뀔 게 없다"는 안내를
   * 받는 것보다 아예 흐리게 보이는 편이 직관적이다. */
  async function titleAffixHasChangesForSystem(system) {
    const r = await api.titleAffixPreview(S.activeId, null, system);
    return r.ok && r.data.items.some((i) => i.changed);
  }

  /** Archive System 우클릭 메뉴. 파일 작업은 소유권을 확인해 Archive 관리 루트 안의
   * 자산만 바꾸고, 외부 Collection 연결은 그대로 둔다. */
  async function openArchiveSystemMenu(sys, event) {
    const pastePreview = await api.archiveClipboardSystemTarget(sys.system);
    const copied = pastePreview.ok ? pastePreview.data.items || [] : [];
    const duplicate = pastePreview.ok ? pastePreview.data.duplicates || [] : [];
    const totalCopied = copied.length + duplicate.length;
    const items = [
      ...[["overwrite", "붙여넣기"], ["patch", "채우기"], ["replace", "교체하기"]].map(([mode, label]) => ({
        label: totalCopied ? "여기에 " + label + " (" + formatCount(totalCopied) + "개)" : "여기에 " + label,
        icon: "upload", disabled: !totalCopied,
        title: duplicate.length ? "같은 이름의 게임은 충돌창에서 결정합니다." : "복사한 게임을 이 System으로 가져옵니다.",
        onSelect: () => pasteClipboard(null, sys.system, pastePreview.data, mode),
      })),
      "separator",
      { label: "게임 정보 스크랩…", icon: "sparkles", disabled: !sys.count,
        title: "이 System의 Archive 항목을 순서대로 검토합니다.",
        onSelect: async () => {
          const ids = await api.archiveUids([sys.system]);
          if (!ids.ok) { showToast(ids.error, "error"); return; }
          openScrapeContext(ids.data);
        } },
      { label: "언어 태그 적용…", icon: "tag",
        title: "이 System 전체 제목에서 기존 장식을 떼고, Settings에 설정한 지역별 표시를 다시 붙입니다. 바로 적용됩니다.",
        onSelect: () => openTitleAffixDialog({ system: sys.system, label: sys.system.toUpperCase() }) },
      { label: "멀티 디스크 태그 적용…", icon: "copy",
        title: "여러 장짜리 게임의 제목 뒤에 붙은 장 번호 표시를 지우고, Settings에 고른 형식으로 다시 붙입니다. 바로 적용됩니다.",
        onSelect: () => openDiscRetagDialog(sys.system, sys.system.toUpperCase()) },
      "separator",
      { label: "ROM 없는 항목 정리", icon: "eraser",
        title: "ROM 위치가 한 번도 기록되지 않은 항목(메타데이터만 남은 것)을 Archive에서 지웁니다. "
          + "실제 파일은 건드리지 않습니다.",
        onSelect: () => confirmArchiveOrphanCleanup(sys) },
      { label: "보관 ROM 파일 전체 삭제…", icon: "gamepad", danger: true,
        title: "이 System에서 Archive ROM 디렉토리 안의 파일만 삭제합니다. 외부 원본 연결은 유지합니다.",
        onSelect: () => confirmArchiveSystemRomDelete(sys) },
      { label: "보관 미디어 정리…", icon: "image",
        title: "종류를 골라 Archive 보관 Media 복사본만 삭제합니다. 외부 원본 연결은 유지합니다.",
        onSelect: () => confirmArchiveSystemMediaDelete(sys) },
      { label: "시스템 기록 제거…", icon: "trash", danger: true,
        title: "이 System의 Archive 기록을 전부 지웁니다 - 실제 ROM/Media 파일은 그대로입니다.",
        onSelect: () => confirmRemoveArchiveSystem(sys) },
    ];
    const folders = [["rom", "ROM 폴더", "설정한 Archive ROM 경로의 이 System 폴더를 엽니다."],
      ["metadata", "Metadata 폴더", "Archive frontend 형식으로 저장한 이 System의 Metadata 폴더를 엽니다."],
      ["media", "Media 폴더", "mediaInternal 설정에 따라 Archive 복사본 또는 원본 Media 폴더를 엽니다."]]
      .map(([kind, label, title]) => ({ label, icon: "folderOpen", title,
        onSelect: async () => {
          const r = await api.archiveSystemFolder(sys.system, kind);
          if (!r.ok) showToast(r.error, "error");
        } }));
    items.splice(2, 0, { section: "폴더 열기" }, ...folders, "separator");
    showContextMenu(menuPoint(event), sys.system.toUpperCase(),
      `게임 ${formatCount(sys.count)}`, items, null, systemIcon(sys.system, 15));
  }

  /** Archive의 "ROM 없는 항목 정리" - Collection 쪽과 뜻은 같지만 여기서는
   * Archive 기록만 지우며, 남아 있는 Media 파일은 건드리지 않는다. */
  async function confirmArchiveOrphanCleanup(sys) {
    const preview = await api.archiveOrphanPreview(sys.system);
    if (!preview.ok) { showToast(preview.error, "error"); return; }
    const items = preview.data.items || [];
    if (!items.length) { showToast(`${sys.system.toUpperCase()}에 정리할 항목이 없습니다.`); return; }

    const LIMIT = 50;
    const list = h("div", { class: "sysdel-list" });
    items.slice(0, LIMIT).forEach((item) => list.appendChild(h("div", { class: "sysdel-target" }, [
      h("span", { class: "sysdel-path" }, [item.title || item.filename]),
      h("span", { class: "sysdel-count" }, [item.filename]),
    ])));
    if (items.length > LIMIT) {
      list.appendChild(h("div", { class: "sysdel-file" }, [`… 외 ${formatCount(items.length - LIMIT)}개`]));
    }
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [
        `ROM 위치가 기록되지 않은 항목 ${formatCount(items.length)}개를 Archive에서 지웁니다. `
        + "실제 ROM/Media 파일은 지워지지 않습니다.",
      ]),
      list,
    ]);
    showModal(`${sys.system.toUpperCase()} - ROM 없는 항목 정리`, body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn danger", onClick: async () => {
        closeModal();
        const r = await api.archiveCleanupOrphans(sys.system);
        if (!r.ok) { showToast(r.error, "error"); return; }
        resetList();
        renderAll();
        await reloadList();
        showToast(`${formatCount(r.data.deleted)}개를 Archive에서 지웠습니다.`);
      } }, ["정리"]),
    ]);
  }

  async function confirmRemoveArchiveSystem(sys) {
    showConfirm(`${sys.system.toUpperCase()} 전체 Archive에서 지우기`,
      `이 System의 Archive 항목 ${formatCount(sys.count)}개를 지웁니다. 실제 ROM/Media 파일은 지워지지 `
      + "않습니다 - 필요하면 해당 Collection에서 다시 수집할 수 있습니다.", true, async () => {
        const r = await api.archiveDeleteSystem(sys.system);
        if (!r.ok) { showToast(r.error, "error"); return; }
        resetList();
        renderAll();
        await reloadList();
        showToast(`${formatCount(r.data.deleted)}개를 Archive에서 지웠습니다.`);
      });
  }

  async function openSystemMenu(sys, storages, event) {
    const titleAffixDisabled = !sys.count || !(await titleAffixHasChangesForSystem(sys.system));
    const clipboardTarget = await api.clipboardSystemTarget(S.activeId, sys.system);
    const current = storages.find((s) => s.id === sys.storageId);
    // 기기(MTP) Collection은 Metadata 전용이다 - 파일을 옮기고 지우는 항목은 눌러도
    // 안 되는 대신 아예 비활성으로 보여준다(사용자 결정: "적용할 게 없으면 못 고르게").
    const deviceOnly = !!(activeDetail() && activeDetail().isDevice);
    const deviceTip = "기기 Collection은 Metadata만 다룹니다. 파일 작업은 ADB 모드에서 지원할 예정입니다.";
    const items = [];
    const pastePreview = clipboardTarget.ok ? clipboardTarget.data : null;
    const copied = pastePreview?.items || [];
    const duplicate = pastePreview?.duplicates || [];
    const copiedLabel = copied.length
      ? `여기에 붙여넣기 (${formatCount(copied.length)}개)` : "여기에 붙여넣기";
    [["overwrite", copiedLabel], ["patch", "여기에 채우기"], ["replace", "여기에 교체하기"]].forEach(([mode, label]) => items.push({ label, icon: "upload",
      disabled: deviceOnly || !copied.length,
      title: deviceOnly ? deviceTip : !clipboardTarget.ok ? clipboardTarget.error : duplicate.length
        ? `같은 게임이 이미 있습니다: ${duplicate.map((d) => d.filename).join(", ")}`
        : copied.length ? copied.map((item) => `${item.system} / ${item.title} (${item.filename})`).join("\n")
          : "복사한 게임이 없습니다.",
      onSelect: () => pasteClipboard(null, sys.system, pastePreview, mode) }));
    items.push("separator", { section: "폴더 열기" });
    [["rom", "ROM 폴더"], ["metadata", "Metadata 폴더"], ["media", "Media 폴더"]].forEach(([kind, label]) =>
      items.push({ label, icon: "folderOpen", onSelect: () => openSystemFolder(sys.system, kind) }));
    items.push("separator");
    items.push({ label: "게임 정보 스크랩…", icon: "sparkles", disabled: !sys.count,
      title: sys.count ? "이 System의 게임을 순서대로 검토합니다." : "스크랩할 게임이 없습니다.",
      onSelect: async () => {
        const ids = await api.listUids(S.activeId, { systems: [sys.system] });
        if (!ids.ok) { showToast(ids.error, "error"); return; }
        openScrapeContext(ids.data);
      } });
    if (sys.conflict && sys.conflict.length) {
      items.push({ section: "충돌 해결 - 쓰기 막힘" });
      sys.conflict.forEach((side) => {
        items.push({ label: `${side.label} 폴더 이름 바꾸기…`, icon: "tag", title: side.path,
          onSelect: () => openRenameSystemFolder(sys, side) });
        items.push({ label: `${side.label} 폴더 삭제…`, icon: "trash", danger: true, title: side.path,
          onSelect: () => confirmRemoveSystemFolder(sys, side) });
      });
      items.push("separator");
    }
    const others = deviceOnly ? [] : storages.filter((s) => s.id !== sys.storageId);
    if (others.length) {
      items.push({ section: "Storage 옮기기" });
      others.forEach((target) => items.push({
        label: target.label, title: target.rootPath,
        icon: target.kind === "internal" ? "hardDrive" : "hardDriveDownload",
        onSelect: () => moveSystemToStorage(sys.system, target.id),
      }));
      items.push("separator");
    }
    items.push({ label: "System 이름 바꾸기…", icon: "tag",
      disabled: deviceOnly || !!(sys.conflict && sys.conflict.length),
      title: "ROM·gamelist·media 폴더 이름을 함께 바꿉니다.",
      onSelect: () => openRenameSystemFolder(sys, { storageId: sys.storageId, label: current ? current.label : sys.storageId, path: null }) });
    items.push({ label: "언어 태그 적용…", icon: "tag", disabled: titleAffixDisabled,
      title: titleAffixDisabled
        ? "지금 설정으로는 이 System에서 바뀔 제목이 없습니다. Settings > Metadata & Media에서 규칙을 확인하세요."
        : "이 System 전체 제목에서 기존 장식을 떼고, Settings에 설정한 지역별 표시를 다시 붙입니다.",
      onSelect: () => openTitleAffixDialog({ system: sys.system, label: sys.system.toUpperCase() }) });
    items.push({ label: "멀티 디스크 태그 적용…", icon: "copy", disabled: deviceOnly,
      title: deviceOnly ? deviceTip
        : "여러 장짜리 게임의 제목 뒤에 붙은 장 번호 표시를 지우고, Settings에 고른 형식으로 다시 붙입니다.",
      onSelect: () => openDiscRetagDialog(sys.system, sys.system.toUpperCase()) });
    items.push("separator", {
      label: "ROM 없는 항목 정리", icon: "eraser", disabled: deviceOnly,
      title: deviceOnly ? deviceTip : "Metadata/Media는 있는데 ROM 파일이 없는 항목을 찾아 지웁니다.",
      onSelect: () => confirmOrphanCleanup(sys),
    }, {
      label: "미디어 정리…", icon: "imageOff", disabled: deviceOnly,
      title: deviceOnly ? deviceTip : "Cover/Screenshot/Video 등 media 종류를 골라 이 System 전체에서 지웁니다.",
      onSelect: () => confirmMediaCleanup(sys),
    });
    // 메뉴 최하단, 빨간색(사용자 결정). 누르면 경고 + "확인하였습니다" 체크 + 확인으로 한 번 더 묻는다.
    items.push("separator", {
      label: "시스템과 파일 삭제…", icon: "trash", danger: true, disabled: deviceOnly,
      title: deviceOnly ? deviceTip : "이 System의 ROM·Metadata·Media를 디스크에서 지우고 목록에서 뺍니다.",
      onSelect: () => confirmRemoveSystem(sys),
    });
    showContextMenu(menuPoint(event), sys.system.toUpperCase(),
      `게임 ${formatCount(sys.count)} · ${current ? current.label : sys.storageId}`, items,
      current ? current.rootPath : null, systemIcon(sys.system, 15));
  }

  async function openSystemFolder(system, kind) {
    const r = await api.openSystemFolder(S.activeId, system, kind);
    if (!r.ok) showToast(r.error, "error");
  }

  /** ROM 없는 항목 정리(System 우클릭, 사용자 결정) - Metadata/Media는 있는데 ROM
   * 파일이 없는 항목을 찾아 보여주고, 확인하면 지운다.
   *
   * **삭제 자체는 새로 만들지 않는다** - 기존 Plan 삭제(planDelete → Apply)를 그대로
   * 쓴다. `_apply_delete`가 이미 ROM 없는 행은 ROM 삭제를 건너뛰고 media와 gamelist
   * 항목만 지우도록 되어 있다(이미 검증된 경로) - 여기서는 대상을 찾아 보여주고
   * 확인받는 것까지만 한다. ROM 파일은 원래 없으므로 "전체 삭제"만큼 위험하지
   * 않다 - 확인 한 번(빈 System 삭제와 같은 무게)이면 된다. */
  async function confirmOrphanCleanup(sys) {
    return confirmOrphanCleanupFor([sys.system], sys.system.toUpperCase());
  }

  /** ROM 없는 항목 정리 - System 하나 또는 Storage 그룹의 System 전부. */
  async function confirmOrphanCleanupFor(systemNames, name) {
    const collectionId = S.activeId;
    const previews = await Promise.all(systemNames.map((s) => api.orphanMetadataPreview(collectionId, s)));
    const failed = previews.find((p) => !p.ok);
    if (failed) { showToast(failed.error, "error"); return; }
    const items = previews.flatMap((p) => p.data.items);
    if (!items.length) { showToast(`${name}에 정리할 항목이 없습니다.`); return; }

    const list = h("div", { class: "sysdel-list" });
    const LIMIT = 50;
    items.slice(0, LIMIT).forEach((item) => list.appendChild(h("div", { class: "sysdel-target" }, [
      h("span", { class: "sysdel-path" }, [item.title || item.filename]),
      h("span", { class: "sysdel-count" }, [item.filename]),
    ])));
    if (items.length > LIMIT) {
      list.appendChild(h("div", { class: "sysdel-file" }, [`… 외 ${formatCount(items.length - LIMIT)}개`]));
    }

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [
        `${name}에서 ROM 파일이 없는 항목 ${formatCount(items.length)}개를 찾았습니다. `
        + "Metadata와 Media를 지우고 목록에서 뺍니다. 되돌릴 수 없습니다.",
      ]),
      list,
    ]);
    showModal(`${name} - ROM 없는 항목 정리`, body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn danger", onClick: async () => {
        closeModal();
        const uids = items.map((item) => item.romUid);
        let r = await api.deleteImmediate(collectionId, uids, ["metadata", "media", "video"]);
        if (!r.ok) { showToast(r.error, "error"); return; }
        if (r.data.requiresConfirmation) {
          r = await api.deleteImmediate(collectionId, uids, ["metadata", "media", "video"], true);
          if (!r.ok) { showToast(r.error, "error"); return; }
        }
        const done = await pollJob(r.data.jobId, "항목 정리 중");
        if (!done.ok) { showToast(done.error, "error"); return; }
        resetList();
        await reloadList();
        await refreshPlan();
        // Auto Plan이 켜져 있으면(기본값) 아직 파일이 지워지지 않는다 - deleteSelection과
        // 같은 규칙이다. 꺼져 있으면 applyPlan()이 용량 확인 모달을 띄운 뒤 실제로 적용하고
        // 목록도 그 안에서 새로고침한다.
        showToast(`${formatCount(uids.length)}개를 정리했습니다.`);
      } }, ["삭제"]),
    ]);
  }

  /** System 전체 미디어 정리(System 우클릭, 사용자 결정) - Cover/Screenshot/Video 등
   * media 종류를 체크박스로 골라 그 System 전체에서 지운다. ROM·Metadata·고르지
   * 않은 타입은 건드리지 않는다. 실제로 파일이 있는 타입만 목록에 나온다. */
  async function confirmMediaCleanup(sys) {
    return confirmMediaCleanupFor([sys.system], sys.system.toUpperCase());
  }

  /** 여러 System(Storage 그룹) 또는 하나의 media를 골라 지운다. 종류별 개수는 System들을 합쳐 보여준다. */
  async function confirmMediaCleanupFor(systemNames, name) {
    const collectionId = S.activeId;
    const previews = await Promise.all(systemNames.map((s) => api.mediaCleanupPreview(collectionId, s)));
    const failed = previews.find((p) => !p.ok);
    if (failed) { showToast(failed.error, "error"); return; }
    const merged = new Map();
    previews.forEach((p) => p.data.types.forEach((t) => {
      const cur = merged.get(t.type) || { type: t.type, label: t.label, count: 0, bytes: 0 };
      cur.count += t.count; cur.bytes += t.bytes;
      merged.set(t.type, cur);
    }));
    const types = [...merged.values()];
    if (!types.length) { showToast(`${name}에 정리할 media가 없습니다.`); return; }

    const checks = types.map((t) => {
      const input = h("input", { type: "checkbox" });
      const row = h("label", { class: "media-clean-row" }, [
        input,
        h("span", { class: "media-clean-name" }, [t.label]),
        h("span", { class: "media-clean-count" }, [`${formatCount(t.count)}개 · ${formatBytes(t.bytes)}`]),
      ]);
      return { type: t.type, input, row };
    });

    const confirmBtn = h("button", { class: "btn danger" }, ["삭제"]);
    confirmBtn.disabled = true;
    checks.forEach((c) => c.input.addEventListener("change", () => {
      confirmBtn.disabled = !checks.some((x) => x.input.checked);
    }));
    confirmBtn.addEventListener("click", async () => {
      const selected = checks.filter((c) => c.input.checked).map((c) => c.type);
      if (!selected.length) return;
      closeModal();
      let removed = 0;
      let failedFiles = [];
      for (const system of systemNames) {
        const r = await api.mediaCleanup(collectionId, system, selected);
        if (!r.ok) { showToast(r.error, "error"); return; }
        removed += r.data.removed || 0;
        failedFiles = failedFiles.concat(r.data.failed || []);
      }
      if (collectionId === S.activeId) {
        await ensureDetail(collectionId);
        resetList();
        renderAll();
        await reloadList();
      }
      showToast(`${name}에서 media ${formatCount(removed)}개를 지웠습니다.`
        + (failedFiles.length ? ` (${formatCount(failedFiles.length)}개 실패)` : ""),
        failedFiles.length ? "warning" : "info");
    });

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [`${name}에서 지울 media 종류를 고르세요. ROM과 Metadata는 지우지 않습니다.`]),
      h("div", { class: "media-clean-list" }, checks.map((c) => c.row)),
    ]);
    showModal(`${name} - 미디어 선택 삭제`, body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      confirmBtn,
    ]);
  }

  /** Title Prefix/Postfix 일괄 적용(사용자 결정) - Gamelist에서 고른 항목(target.romUids) 또는
   * System 전체(target.system) 중 하나를 받는다. 미리보기를 보여주고 확인해야 Plan에 올라간다 -
   * System 전체 적용은 "일괄 적용 여부를 확인한 후" 반영해야 한다는 요구가 이 확인 창이다.
   *
   * 실제 파일은 여기서 바뀌지 않는다 - Plan에 올린 뒤 Apply를 눌러야 반영된다(다른 텍스트 편집과
   * 달리 이 기능만 Plan을 거친다, app/model/plan.py의 OP_TITLE_EDIT 참고). */
  async function openTitleAffixDialog(target) {
    const collectionId = S.activeId;
    const archive = isArchive();
    const preview = archive
      ? await api.archiveTitleAffixPreview(target.system || null, target.romUids || null)
      : await api.titleAffixPreview(collectionId, target.romUids || null, target.system || null);
    if (!preview.ok) { showToast(preview.error, "error"); return; }
    const items = preview.data.items;
    const changed = items.filter((i) => i.changed);
    if (!changed.length) {
      showToast("바뀔 제목이 없습니다 - Settings > Metadata & Media에서 Title Prefix/Postfix 설정을 확인하세요.",
        "warning");
      return;
    }

    const LIMIT = 50;
    const list = h("div", { class: "title-affix-list" });
    changed.slice(0, LIMIT).forEach((item) => list.appendChild(h("div", { class: "title-affix-row" }, [
      h("span", { class: "title-affix-old", title: item.oldTitle }, [item.oldTitle || "(제목 없음)"]),
      icon("chevronRight", IC.sm),
      h("span", { class: "title-affix-new", title: item.newTitle }, [item.newTitle]),
    ])));
    if (changed.length > LIMIT) {
      list.appendChild(h("div", { class: "sysdel-file" }, [`… 외 ${formatCount(changed.length - LIMIT)}개`]));
    }

    const unchanged = items.length - changed.length;
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [
        `${target.label} - 제목 ${formatCount(changed.length)}개가 바뀝니다`
        + (unchanged ? ` (변경 없음 ${formatCount(unchanged)}개 제외)` : "") + ". "
        + (archive ? "Archive는 Plan을 거치지 않고 바로 적용됩니다."
          : "확인하면 바로 적용됩니다."),
      ]),
      list,
    ]);
    showModal("Title Prefix/Postfix", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary", onClick: async () => {
        closeModal();
        if (archive) {
          const r = await api.archiveApplyTitleAffix(target.system || null, target.romUids || null);
          if (!r.ok) { showToast(r.error, "error"); return; }
          resetList();
          await reloadList();
          showToast(`제목 ${formatCount(r.data.applied)}개를 바꿨습니다.`);
          return;
        }
        await runImmediateAction("title", { romUids: target.romUids || null, system: target.system || null });
      } }, ["적용"]),
    ]);
  }

  /** 멀티 디스크 태그 적용(System 우클릭) - 기존 꼬리표를 지우고 지금 Settings에 고른
   * 형식으로 다시 붙인다. Title Prefix/Postfix와 같은 D1 예외(Plan을 거치는 텍스트 편집). */
  async function openDiscRetagDialog(system, label) {
    const collectionId = S.activeId;
    const archive = isArchive();
    const preview = archive
      ? await api.archiveDiscRetagPreview(system)
      : await api.discRetagPreview(collectionId, system);
    if (!preview.ok) { showToast(preview.error, "error"); return; }
    const items = preview.data.items;
    const changed = items.filter((i) => i.changed);
    if (!changed.length) {
      showToast("이 System에 여러 장짜리 게임이 없거나, 이미 지금 형식으로 붙어 있습니다.", "warning");
      return;
    }

    const LIMIT = 50;
    const list = h("div", { class: "title-affix-list" });
    changed.slice(0, LIMIT).forEach((item) => list.appendChild(h("div", { class: "title-affix-row" }, [
      h("span", { class: "title-affix-old", title: item.oldTitle }, [item.oldTitle || "(제목 없음)"]),
      icon("chevronRight", IC.sm),
      h("span", { class: "title-affix-new", title: item.newTitle }, [item.newTitle]),
    ])));
    if (changed.length > LIMIT) {
      list.appendChild(h("div", { class: "sysdel-file" }, [`… 외 ${formatCount(changed.length - LIMIT)}개`]));
    }

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [
        `${label} - 제목 ${formatCount(changed.length)}개가 바뀝니다. `
        + (archive ? "Archive는 Plan을 거치지 않고 바로 적용됩니다."
          : "확인하면 바로 적용됩니다."),
      ]),
      list,
    ]);
    showModal("멀티 디스크 태그 적용", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary", onClick: async () => {
        closeModal();
        if (archive) {
          const r = await api.archiveApplyDiscRetag(system);
          if (!r.ok) { showToast(r.error, "error"); return; }
          resetList();
          await reloadList();
          showToast(`제목 ${formatCount(r.data.applied)}개를 바꿨습니다.`);
          return;
        }
        await runImmediateAction("disc", { system });
      } }, ["적용"]),
    ]);
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


  // ------------------------------------------------------------------
  // RetroArch 실행 (bridge: launch_game / retroarch_game_info / set_system_core / set_game_core)
  // ------------------------------------------------------------------
  //: 검증 여부는 경고로 보여주되, 사용자가 지정한 Core의 실행을 막지 않는다.
  let retroarchUnverified = new Set();
  async function loadRetroarchState() {
    const r = await api.retroarchSettings();
    if (r.ok) retroarchUnverified = new Set((r.data.unverified || []).map((s) => String(s).toLowerCase()));
  }
  const retroarchVerified = (system) => !retroarchUnverified.has(String(system || "").toLowerCase());

  /** 이 행을 RetroArch로 실행할 수 있는 상태인지. 안 되면 사유 문자열, 되면 null. */
  /** 실행 API에 넘기는 대상 ID. Archive 항목은 Collection이 아니라 "archive"다. */
  const launchTargetId = () => (isArchive() ? "archive" : S.activeId);

  function launchBlockReason(target) {
    if (isCompare()) return "Compare 중에는 실행할 수 없습니다.";
    if (!target || !target.present) return "ROM 파일이 없습니다.";
    return null;
  }

  /** 실행. Core가 없거나 파일이 사라졌으면 그 자리에서 Core 선택 창을 띄우고 이어서 실행한다. */
  async function launchGame(target) {
    const blocked = launchBlockReason(target);
    if (blocked) { showToast(blocked, "warning"); return; }
    const r = await api.launchGame(launchTargetId(), target.romUid);
    // ok는 "바로 죽지 않았다"는 뜻일 뿐이다 - 게임 화면까지 떴다고 단정하지 않는다.
    if (r.ok) { showToast("RetroArch 실행을 요청했습니다."); return; }
    if (r.errorKind === "core_unset" || r.errorKind === "core_missing") {
      openCoreDialog(target, { reason: r.error, relaunch: true });
      return;
    }
    if (r.errorKind === "retroarch_missing") {
      showToast(`${r.error} - Settings > Emulator에서 RetroArch 경로를 지정하세요.`, "error");
      openSettings("emulator");
      return;
    }
    showToast(r.error, "error");
  }

  /** Core 선택 - System 기본값으로 저장하거나 이 게임에만 지정한다. */
  async function openCoreDialog(target, opts = {}) {
    const collectionId = launchTargetId();
    const info = await api.retroarchGameInfo(collectionId, target.romUid);
    if (!info.ok) { showToast(info.error, "error"); return; }
    const d = info.data;
    if (!d.cores.length) {
      showToast("Core 폴더가 없거나 비어 있습니다 - Settings > Emulator에서 Core 폴더를 지정하세요.", "warning");
      openSettings("emulator");
      return;
    }
    const system = String(d.system).toUpperCase();
    const select = h("select", { class: "field-input core-select" }, [
      h("option", { value: "" }, ["Core를 고르세요"]),
      ...d.cores.map((core) => h("option", { value: core }, [`${coreLabel(core)}  (${core})`])),
    ]);
    select.value = d.gameCore || d.systemCore || "";
    const scopeName = `core-scope-${Date.now()}`;
    const sysRadio = h("input", { type: "radio", name: scopeName, class: "core-scope-system" });
    const gameRadio = h("input", { type: "radio", name: scopeName, class: "core-scope-game" });
    // 게임에 이미 따로 지정돼 있으면 그 지정을 고치는 것이 자연스럽다.
    if (d.gameCore) gameRadio.checked = true; else sysRadio.checked = true;

    const body = h("div", { class: "modal-body core-dialog" }, [
      opts.reason ? h("div", { class: "modal-text core-reason" }, [opts.reason]) : null,
      h("div", { class: "core-now" }, [
        h("div", {}, [`${system} 기본값: `, h("b", {}, [d.systemCore ? coreLabel(d.systemCore) : "없음"])]),
        h("div", {}, ["이 게임 지정: ", h("b", {}, [d.gameCore ? coreLabel(d.gameCore) : "없음 (System 기본값 사용)"])]),
      ]),
      h("div", { class: "field-label" }, ["Core"]), select,
      h("label", { class: "core-scope" }, [sysRadio, h("span", {}, [`${system} 전체의 기본값으로 저장`])]),
      h("label", { class: "core-scope" }, [gameRadio, h("span", {}, [`이 게임에만 지정 (${d.file})`])]),
    ]);
    const save = h("button", { class: "btn primary core-save" }, [opts.relaunch ? "저장 후 실행" : "저장"]);
    save.addEventListener("click", async () => {
      if (!select.value) { showToast("Core를 고르세요.", "warning"); return; }
      const r = gameRadio.checked
        ? await api.setGameCore(d.system, d.file, select.value)
        : await api.setSystemCore(d.system, select.value);
      if (!r.ok) { showToast(r.error, "error"); return; }
      closeModal();
      if (opts.relaunch && collectionId === S.activeId) launchGame(target);
      else showToast(gameRadio.checked ? "이 게임의 Core를 지정했습니다." : `${system} 기본 Core를 저장했습니다.`);
    });
    const actions = [h("button", { class: "btn", onClick: closeModal }, ["취소"])];
    if (d.gameCore) {
      actions.push(h("button", { class: "btn core-clear", onClick: async () => {
        const r = await api.setGameCore(d.system, d.file, null);
        if (!r.ok) { showToast(r.error, "error"); return; }
        closeModal();
        showToast("이 게임의 Core 지정을 지웠습니다 - System 기본값으로 실행됩니다.");
      } }, ["게임 지정 해제"]));
    }
    actions.push(save);
    showModal(`RetroArch Core - ${d.file}`, body, actions);
  }

  const coreLabel = (file) => String(file || "").replace(/\.(dll|so|dylib)$/i, "").replace(/_libretro$/, "");

  /** Settings > Emulator. 경로 두 개와 System별 기본 Core. */
  function emulatorSettingsEditor() {
    const wrap = h("div", { class: "stg-emulator" });
    const systemsInUse = () => {
      const set = new Set();
      Object.values(S.detail || {}).forEach((d) => (d && d.systems || []).forEach((s) => set.add(String(s.system).toLowerCase())));
      return set;
    };
    const draw = async () => {
      const r = await api.retroarchSettings();
      clear(wrap);
      if (!r.ok) { wrap.appendChild(h("div", { class: "stg-info" }, [r.error])); return; }
      const s = r.data;
      retroarchUnverified = new Set((s.unverified || []).map((x) => String(x).toLowerCase()));

      const exeInput = h("input", { class: "stg-control stg-text", value: s.retroarchPath, placeholder: "예: C:\\RetroArch\\retroarch.exe" });
      const coresInput = h("input", { class: "stg-control stg-text", value: s.coresDir, placeholder: "예: C:\\RetroArch\\cores" });
      const saveBoth = async () => {
        const saved = await api.setRetroarchPaths(exeInput.value.trim(), coresInput.value.trim());
        if (!saved.ok) { showToast(saved.error, "error"); return; }
        draw();
      };
      exeInput.addEventListener("change", saveBoth);
      coresInput.addEventListener("change", saveBoth);
      const browseExe = h("button", { class: "btn compact", onClick: async () => {
        const p = await api.pickFile("RetroArch 실행 파일", ["실행 파일 (*.exe)", "모든 파일 (*.*)"], "");
        if (p.ok && p.data) {
          exeInput.value = p.data;
          // 포터블 설치는 실행 파일 옆에 cores 폴더가 있다 - 비어 있으면 그걸로 채운다.
          if (!coresInput.value.trim()) coresInput.value = p.data.replace(/[\\/][^\\/]+$/, "") + "\\cores";
          saveBoth();
        }
      } }, ["찾아보기"]);
      const browseCores = h("button", { class: "btn compact", onClick: async () => {
        const p = await api.pickFolder("RetroArch Core 폴더");
        if (p.ok && p.data) { coresInput.value = p.data; saveBoth(); }
      } }, ["찾아보기"]);
      const pathRow = (key, label, input, button, help) => h("div", { class: "stg-row", "data-key": key }, [
        h("div", { class: "stg-label" }, [h("div", { class: "stg-name" }, [label]), h("div", { class: "stg-help" }, [help])]),
        h("div", { class: "stg-path" }, [input, button]),
      ]);
      wrap.appendChild(pathRow("emulator.retroarchPath", "RetroArch 실행 파일", exeInput, browseExe,
        "게임 행을 더블클릭하거나 Detail의 ▶ 버튼으로 실행합니다."));
      wrap.appendChild(pathRow("emulator.coresDir", "Core 폴더", coresInput, browseCores,
        "Core는 이 폴더 기준 파일명으로 기억합니다 - RetroArch를 옮겨도 폴더만 다시 지정하면 됩니다."));

      const systems = [...new Set([...systemsInUse(), ...Object.keys(s.systemCores)])].sort();
      const fill = h("button", { class: "btn compact stg-core-fill", disabled: !s.cores.length, onClick: async () => {
        const applied = await api.applyDefaultCores(systems);
        if (!applied.ok) { showToast(applied.error, "error"); return; }
        showToast(applied.data.count ? `기본 Core ${formatCount(applied.data.count)}개를 채웠습니다.` : "새로 채울 System이 없습니다.");
        draw();
      } }, ["기본 Core 자동 채우기"]);
      wrap.appendChild(h("div", { class: "stg-subsection-title stg-core-head" }, [h("span", {}, ["System별 기본 Core"]), fill]));
      if (!s.cores.length) {
        wrap.appendChild(h("div", { class: "stg-info" }, ["Core 폴더를 지정하면 설치된 Core 목록에서 고를 수 있습니다."]));
      }
      if (!systems.length) {
        wrap.appendChild(h("div", { class: "stg-info" }, ["열린 Collection이 없습니다."]));
        return;
      }
      const table = h("div", { class: "stg-cores" });
      systems.forEach((system) => {
        const current = s.systemCores[system] || "";
        const select = h("select", { class: "stg-control", disabled: !s.cores.length });
        select.appendChild(h("option", { value: "" }, ["지정 안 함"]));
        if (current && !s.cores.includes(current)) select.appendChild(h("option", { value: current }, [`${coreLabel(current)} (폴더에 없음)`]));
        s.cores.forEach((core) => select.appendChild(h("option", { value: core }, [coreLabel(core)])));
        select.value = current;
        select.addEventListener("change", async () => {
          const saved = await api.setSystemCore(system, select.value || null);
          if (!saved.ok) { showToast(saved.error, "error"); select.value = current; }
        });
        const unverified = retroarchUnverified.has(system);
        table.appendChild(h("div", { class: "stg-core-row" + (unverified ? " unverified" : ""), "data-system": system }, [
          h("span", { class: "stg-core-system" }, [systemIcon(system, 14), system.toUpperCase()]),
          unverified ? h("span", { class: "stg-soon", title: "이 System의 Core/BIOS 조합은 아직 검증되지 않았습니다. 선택한 Core로 실행할 수 있습니다." }, ["실행 검증 안 됨"]) : h("span"),
          select,
        ]));
      });
      wrap.appendChild(table);
    };
    wrap.appendChild(h("div", { class: "stg-info" }, ["불러오는 중…"]));
    draw();
    return wrap;
  }


  // ------------------------------------------------------------------
  // Storage 충돌 · External Storage 설정 (bridge: app/storage_layout.py)
  // ------------------------------------------------------------------
  //: 같은 System 폴더가 여러 Storage에 있으면(ES-DE는 System당 ROM 경로 하나만 인정한다) 그 System은
  //: 충돌이다 - 빨간 !로 표시하고 백엔드가 쓰기를 막는다. 한쪽 폴더를 지우거나 이름을 바꾸면 풀린다.
  function currentSystemConflict(system) {
    const d = activeDetail();
    if (!d || !system) return null;
    const row = (d.systems || []).find((s) => String(s.system).toLowerCase() === String(system).toLowerCase());
    return row && row.conflict && row.conflict.length ? row.conflict : null;
  }

  async function refreshAfterLayoutChange() {
    const id = S.activeId;
    await ensureDetail(id);
    if (id !== S.activeId) return;
    resetList();
    renderAll();
    await reloadList();
    await refreshPlan();
  }

  /** System 추가 - 이름을 넣으면 빈 폴더로 만든다. Storage가 여럿이면 어디에 만들지 고른다. */
  function openCreateSystem() {
    const detail = activeDetail();
    if (!detail) return;
    const input = h("input", { class: "field-input add-system-input", placeholder: "예: fbneo, psx" });
    const storages = detail.storages || [];
    const select = h("select", { class: "field-input add-system-storage" },
      storages.map((s) => h("option", { value: s.id }, [s.label])));
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "field-label" }, ["System 이름"]), input,
      storages.length > 1 ? h("div", { class: "field-label" }, ["만들 위치"]) : null,
      storages.length > 1 ? select : null,
      h("div", { class: "modal-hint" }, [
        "이 이름의 빈 ROM 폴더를 만듭니다. ES-DE는 폴더 이름으로 System을 알아보므로 영문 소문자 이름(psx, snes …)을 쓰세요."]),
    ]);
    showModal("System 추가", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary add-system-save", onClick: async () => {
        const name = input.value.trim();
        if (!name) { showToast("System 이름을 입력하세요.", "warning"); return; }
        closeModal();
        const r = await api.createSystem(S.activeId, name, select.value);
        if (!r.ok) { showToast(r.error, "error"); return; }
        await refreshAfterLayoutChange();
        showToast(r.data.knownToEsde === false
          ? `${name} System을 만들었습니다. ES-DE 기본 목록에 없는 이름이라 custom_systems XML이 필요할 수 있습니다.`
          : `${name} System을 만들었습니다.`, r.data.knownToEsde === false ? "warning" : "info");
      } }, ["만들기"]),
    ]);
    setTimeout(() => input.focus(), 30);
  }

  /** 한 Storage 쪽 System 폴더 이름 바꾸기. side.path가 없으면 등록된 쪽 전체(ROM·gamelist·media 폴더). */
  function openRenameSystemFolder(sys, side) {
    const input = h("input", { class: "field-input rename-system-input", value: sys.system });
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [side.path
        ? `${side.label}의 ${side.path} 폴더 이름을 바꿉니다.`
        : `${sys.system.toUpperCase()} System의 폴더 이름을 바꿉니다(ROM·gamelist·media 폴더를 함께 바꿉니다).`]),
      h("div", { class: "field-label" }, ["새 System 이름"]), input,
      h("div", { class: "modal-hint" }, ["ES-DE는 폴더 이름으로 System을 알아봅니다. 영문 소문자 이름(예: psx, snes)을 쓰세요."]),
    ]);
    showModal(`${sys.system.toUpperCase()} 이름 바꾸기`, body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary rename-system-save", onClick: async () => {
        const name = input.value.trim();
        if (!name || name === sys.system) { showToast("새 이름을 입력하세요.", "warning"); return; }
        closeModal();
        const r = await api.renameSystemFolder(S.activeId, sys.system, side.storageId, name);
        if (!r.ok) { showToast(r.error, "error"); return; }
        await refreshAfterLayoutChange();
        showToast(`${sys.system.toUpperCase()} → ${String(r.data.to).toUpperCase()} 이름을 바꿨습니다.`);
      } }, ["이름 바꾸기"]),
    ]);
    setTimeout(() => { input.focus(); input.select(); }, 30);
  }

  /** 한 Storage 쪽 ROM 폴더만 지운다(충돌 해결). 되돌릴 수 없으니 전체 삭제처럼 두 번 묻는다. */
  async function confirmRemoveSystemFolder(sys, side) {
    const p = await api.systemFolderPreview(S.activeId, sys.system, side.storageId);
    if (!p.ok) { showToast(p.error, "error"); return; }
    const d = p.data;
    const check = h("input", { type: "checkbox", class: "sysdel-ack-input" });
    const confirmBtn = h("button", { class: "btn danger sysdel-confirm" }, ["확인"]);
    confirmBtn.disabled = true;
    check.addEventListener("change", () => { confirmBtn.disabled = !check.checked; });
    confirmBtn.addEventListener("click", async () => {
      if (!check.checked) return;
      closeModal();
      const r = await api.removeSystemFolder(S.activeId, sys.system, side.storageId);
      if (!r.ok) { showToast(r.error, "error"); return; }
      await refreshAfterLayoutChange();
      showToast(`${d.label}의 ${sys.system.toUpperCase()} 폴더를 지웠습니다.`);
    });
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "sysdel-warning" }, [
        h("div", { class: "sysdel-warning-title" }, ["되돌릴 수 없는 삭제입니다"]),
        h("div", { class: "modal-text" }, [`${d.label} 쪽 ROM 폴더만 지웁니다 - 파일 ${formatCount(d.fileCount)}개(${formatBytes(d.totalBytes)}). gamelist와 media는 남깁니다.`]),
      ]),
      h("div", { class: "sysdel-list" }, [h("div", { class: "sysdel-target" }, [
        h("span", { class: "sysdel-kind" }, [d.label]), h("span", { class: "sysdel-path", title: d.path }, [d.path]),
      ])]),
      d.remaining && d.remaining.length ? h("div", { class: "modal-text sysdel-kept" },
        [`남는 쪽: ${d.remaining.map((x) => `${x.label} (${x.path})`).join(", ")}`]) : null,
      h("label", { class: "sysdel-ack" }, [check, h("span", {}, ["확인하였습니다"])]),
    ]);
    showModal(`${sys.system.toUpperCase()} - ${d.label} 폴더 삭제`, body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]), confirmBtn,
    ]);
  }

  /** Storage 그룹(Internal/External) 우클릭 - System 우클릭 메뉴의 기능 중 **그룹 전체에 뜻이 있는 것**만
   * 그 그룹의 System 전부에 적용한다(사용자 결정). 폴더 열기는 특정 System이 정해지지 않았으니 System
   * 폴더들을 품은 **상위 폴더**를 연다. 예전에는 이 자리가 "이미 gamelist가 있습니다"라는 안내만 냈다. */
  function openStorageGroupMenu(storage, systemNames, event) {
    const none = !systemNames.length;
    const deviceOnly = !!(activeDetail() && activeDetail().metadataOnly);
    const noSystems = "이 Storage에 붙은 System이 없습니다.";
    const label = storage.label;
    const items = [
      { label: "언어 태그 적용…", icon: "tag", disabled: none,
        title: none ? noSystems : "이 그룹의 모든 System 제목에 Settings의 지역별 표시를 적용합니다.",
        onSelect: () => openTitleAffixDialog({ system: systemNames, label: `${label} 전체` }) },
      { label: "gamelist 만들기", icon: "fileWarning", disabled: none,
        title: none ? noSystems : "gamelist가 없는 System에 ROM 파일명만 담아 만듭니다.",
        onSelect: () => openMetadataBootstrap(S.activeId, systemNames) },
      "separator",
      { label: "ROM 없는 항목 정리", icon: "eraser", disabled: none || deviceOnly,
        title: none ? noSystems : "Metadata/Media는 있는데 ROM 파일이 없는 항목을 이 그룹 전체에서 찾아 지웁니다.",
        onSelect: () => confirmOrphanCleanupFor(systemNames, label.toUpperCase()) },
      { label: "미디어 정리…", icon: "imageOff", disabled: none || deviceOnly,
        title: none ? noSystems : "media 종류를 골라 이 그룹의 모든 System에서 지웁니다.",
        onSelect: () => confirmMediaCleanupFor(systemNames, label.toUpperCase()) },
      "separator", { section: "폴더 열기 (상위 폴더)" },
    ];
    [["rom", "ROM 폴더"], ["metadata", "Metadata 폴더"], ["media", "Media 폴더"]].forEach(([kind, text]) =>
      items.push({ label: text, icon: "folderOpen", disabled: none, title: none ? noSystems : null,
        onSelect: async () => {
          const r = await api.openStorageFolder(S.activeId, storage.id, kind);
          if (!r.ok) showToast(r.error, "error");
        } }));
    showContextMenu(menuPoint(event), label.toUpperCase(),
      none ? "붙은 System 없음" : `${formatCount(systemNames.length)}개 System`, items);
  }

  /** Storage 설정 - Internal/External 공통(사용자 결정: "External만 Setting이 있는
   * 것도 이상하다"). 이름은 둘 다 바꿀 수 있다. 안드로이드 Storage ID/경로와 PC
   * 경로는 **External에서만** 뜻이 있다.
   *
   * - PC 경로: Internal의 PC 경로는 Collection 경로 자체라 여기서 바꿀 자리가
   *   아니다(update_storage도 Internal의 root_path는 조용히 무시한다).
   * - Android Storage ID/경로: `write_custom_systems()`가 명시적으로 Internal을
   *   건너뛴다("(Android) Internal은 ES-DE 기본 ROM 폴더(%ROMPATH%)를 쓰므로
   *   적지 않는다") - custom_systems XML을 만들 때 Internal의 이 값은 아예
   *   읽히지 않는다. 그런데도 입력칸을 보여주면 "이걸 채워야 하나?" 하는 의미
   *   없는 질문을 만든다(실사용 피드백 - "Internal의 옵션에 들어있는 Android
   *   Storage ID, Storage 경로는 의미없다"). External에서만 보여준다.
   */
  function openStorageSettings(storage) {
    const external = storage.kind === "external";
    const label = h("input", { class: "field-input storage-label", value: storage.label });

    const body = h("div", { class: "modal-body storage-settings" }, [
      h("div", { class: "field-label" }, ["이름"]), label,
    ]);
    let root = null, deviceId = null, deviceRoot = null;
    if (external) {
      root = h("input", { class: "field-input storage-root", value: storage.rootPath });
      const browse = h("button", { class: "btn", onClick: async () => {
        const r = await api.pickFolder("External Storage 폴더");
        if (r.ok && r.data) root.value = r.data;
      } }, [icon("folderOpen", IC.sm)]);
      body.appendChild(h("div", { class: "field-label" }, ["이 PC에서의 경로"]));
      body.appendChild(h("div", { class: "field-row" }, [root, browse]));

      // 기기 경로(전체 경로)가 유일한 입력이다(사용자 결정) - Storage ID만 받으면 PC 경로가
      // SD카드의 하위 폴더일 때 어긋난다. ID는 경로 안에 이미 들어 있다.
      deviceRoot = h("input", { class: "field-input storage-device-root", value: storage.deviceRoot || (storage.deviceId ? `/storage/${storage.deviceId}` : ""),
                                placeholder: "/storage/1234-ABCD/Roms" });
      body.appendChild(h("div", { class: "field-label" }, ["Android 기기에서의 전체 경로"]));
      body.appendChild(deviceRoot);
      body.appendChild(h("div", { class: "modal-hint" }, [
        "위 'PC 경로' 폴더가 안드로이드 기기에서는 어디에 있는지 전체 경로로 적으세요. "
        + "예: SD카드(1234-ABCD)의 Roms 폴더 → /storage/1234-ABCD/Roms. "
        + "기기의 파일 앱에서 그 폴더의 경로를 확인할 수 있습니다. ES-DE custom_systems XML의 ROM 경로에 그대로 쓰입니다."]));
    } else {
      // Internal의 PC 경로는 Collection 자체의 경로다 - 여기서 바꾸면 저장은 되지 않고
      // 조용히 무시되므로, 아예 입력칸을 주지 않고 참고로만 보여준다.
      body.appendChild(h("div", { class: "field-label" }, ["이 PC에서의 경로"]));
      body.appendChild(h("div", { class: "modal-text storage-root-readonly" }, [storage.rootPath]));
    }

    const actions = [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary storage-settings-save", onClick: async () => {
        // Internal은 deviceId/deviceRoot 입력칸 자체가 없다 - null로 넘겨 bridge가
        // 그 필드를 아예 건드리지 않게 한다(빈 문자열을 보내면 "일부러 지웠다"로
        // 읽혀 불필요하게 값을 건드린다).
        const r = await api.updateStorage(S.activeId, storage.id, label.value,
          root ? root.value : null, deviceId ? deviceId.value : null, deviceRoot ? deviceRoot.value : null);
        if (!r.ok) { showToast(r.error, "error"); return; }
        closeModal();
        await ensureDetail(S.activeId);
        renderNav();
        renderHeader();
        showToast("Storage 설정을 저장했습니다.");
      } }, ["저장"]),
    ];
    if (external && !isCompare() && S.adapterActions && S.adapterActions.length) {
      // 취소/저장과 같은 줄에 두지 않는다 - 이건 저장과 무관한 별도 동작이다.
      S.adapterActions.forEach((action) => {
        actions.unshift(h("button", { class: "btn", onClick: () => {
          closeModal();
          runAdapterAction(action, storage.id, storage.label);
        } }, [icon("save", IC.sm), h("span", {}, [action.label])]));
      });
    }
    showModal(`${storage.label} 설정`, body, actions);
  }

  function openStorageMenu(storage) {
    // renderCollapsedHeaderPanel()과 같은 규칙이다 - 목표를 정했으면 Capacity/Free
    // 둘 다 목표 기준이다(실사용 피드백 - "Free 용량이 Target-Actual이 아니라
    // 그냥 하드용량임"). 두 자리에서 다른 계산을 쓰면 같은 Storage를 두 번 클릭할
    // 뿐인데 숫자가 다르게 보인다.
    const target = S.dashboardTargets[storage.id] || null;
    const basis = target || storage.capacityBytes;
    const targetFree = target != null ? Math.max(0, target - storage.actualBytes) : null;
    const free = target != null
      ? (storage.freeBytes == null ? targetFree : Math.min(targetFree, storage.freeBytes))
      : storage.freeBytes;
    const stats = h("div", { class: "modal-body" }, [
      h("div", { class: "health-row" }, [h("span", {}, ["경로"]), h("span", {}, [storage.rootPath])]),
      h("div", { class: "health-row" }, [h("span", {}, ["Actual"]), h("span", {}, [formatBytes(storage.actualBytes)])]),
      h("div", { class: "health-row" }, [h("span", {}, [target ? "Target" : "Capacity"]),
        h("span", {}, [basis == null ? "Unknown" : formatBytes(basis)])]),
      h("div", { class: "health-row" }, [h("span", {}, ["Free"]),
        h("span", {}, [free == null ? "Unknown" : formatBytes(free)])]),
      h("div", { class: "health-row" }, [h("span", {}, ["Systems"]), h("span", {}, [String(storage.systems.length)])]),
    ]);
    const actions = [h("button", { class: "btn primary", onClick: closeModal }, ["닫기"])];
    if (storage.kind !== "internal") {
      // confirmRemoveExternalStorage()를 그대로 쓴다 - 여기서 removeStorage를
      // 바로 부르면 System이 붙어 있을 때 registry가 거부만 하고 끝나서(붙은
      // System을 안내 없이 방치), Storage Health 모달로 들어온 경로만 재배치
      // 확인 없이 막히는 결과가 됐다.
      actions.unshift(h("button", { class: "btn danger", onClick: () => {
        closeModal();
        confirmRemoveExternalStorage(storage);
      } }, ["제거"]));
    }
    showModal(`${storage.label} Health`, stats, actions);
  }

  // ------------------------------------------------------------------
  // Collection 헤더
  // ------------------------------------------------------------------
  /** 목표 대비 사용량 5단계(실사용 피드백 §4) - 파랑(여유) > 녹색 > 노랑 > 주황 >
   * 빨강(목표 넘어감). Dashboard의 3단계(.dsb-meter: ok/warn/over)보다 세밀하게
   * 나눈다 - HERO는 항상 보이는 자리라, 목표에 다가가는 낌새를 Dashboard를 열기
   * 전에 미리 알아채야 한다는 게 이 자리의 존재 이유다. */
  function capacityLevel(ratio) {
    if (ratio == null) return "none";
    if (ratio > 1) return "over";
    if (ratio >= 0.9) return "orange";
    if (ratio >= 0.75) return "yellow";
    if (ratio >= 0.5) return "green";
    return "blue";
  }

  function renderHeader() {
    const host = $("collection-header");
    clear(host);
    // 확장 칸은 다른 기둥에 있지만 이 함수가 함께 책임진다 - 안 비우면 접어도 남는다.
    const expandedSlot = $("collection-expanded");
    if (expandedSlot) clear(expandedSlot);
    const detail = activeDetail();
    if (!detail) {
      const headerRow = $("header-row");
      headerRow.style.removeProperty("--sys-base");
      headerRow.style.removeProperty("--sys-point");
      headerRow.classList.remove("has-sys-art");
      return;
    }

    // Navigator에서 System을 골랐으면 그 System의 정체를 보여준다 - 항상
    // Collection 이름만 보이면 지금 뭘 보고 있는지 다시 Navigator를 봐야
    // 했다(레이아웃 재검토). Frontend/OS/Arch 줄은 System 고유 정보가 아니라
    // Collection 정보라 그대로 둔다.
    const scope = activeScope();
    const systemEntry = scope.kind === "system"
      ? (detail.systems || []).find((s) => s.system === scope.id) : null;

    // HERO의 System 색 배경(.cheader-art)이 Detail 쪽 경계에서 뚝 끊겨 보였다
    // (실사용 피드백 - "hero와 detail 사이는 끊어져 보인다"). 두 기둥의 공통
    // 조상(#header-row)에 같은 색 변수를 둬서, .detail-topspace(#detail-top의
    // 실제로 보이는 자식 - #detail-top 자체는 그 자식에 완전히 가려진다)의
    // 그라데이션이 그 색을 이어받아 오른쪽으로 계속되게 한다 - System을 안
    // 고른 상태에서는 변수를 지워 Detail 쪽도 얼룩 없이 그대로 있는다.
    const headerRow = $("header-row");
    const rowPalette = systemEntry ? systemPalette(systemEntry.system) : null;
    if (rowPalette) {
      headerRow.style.setProperty("--sys-base", rowPalette.base);
      headerRow.style.setProperty("--sys-point", rowPalette.points[0]);
    } else {
      headerRow.style.removeProperty("--sys-base");
      headerRow.style.removeProperty("--sys-point");
    }
    headerRow.classList.toggle("has-sys-art", !!systemEntry);

    // **이 띠의 높이는 절대 변하지 않는다(--header-row-h).** Navigator의 SYSTEMS
    // 띠와 세로로 맞아야 구분선이 한 줄로 이어지고, 이 줄이 커지면 옆의 Detail
    // 패널까지 밀린다(사용자 피드백). 펼쳤을 때 커지는 것은 아래 System 카드다.
    const compact = h("div", { class: "cheader" });
    if (systemEntry) compact.appendChild(headerArt(systemEntry.system));
    // 아이콘 상자 대신 콘솔 포인트 색 바(사용자 결정) - System을 보고 있을 때만.
    compact.appendChild(systemEntry
      ? pointBar(systemEntry.system)
      : h("div", { class: "cheader-icon" }, [icon("gamepad", IC.lg)]));

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
    // 숫자만 나열하면 무엇의 수인지 매번 읽어야 한다 - 앞에 작은 아이콘을 두면
    // 모양만으로 구분된다(사용자 결정). Metadata는 "전체 - 빠진 수"로 계산해서
    // 목록에 뜨는 수와 항상 아귀가 맞는다.
    //
    // **두 칸으로 나눈다.** ROM/Metadata는 지금 보는 System(또는 Collection
    // 전체)의 숫자고, Internal/External은 Collection 전체의 Storage 용량이다 -
    // 서로 다른 단위인데 한 줄에 섞여 있으면 숫자가 바뀔 때마다 그 사이 |
    // 구분선까지 밀렸다 당겼다 했다(실사용 피드백). 각 자리 폭을 고정해서
    // 숫자가 몇 자리든 |가 항상 같은 자리에 있게 한다.
    const romCount = systemEntry ? systemEntry.count : detail.totalGames;
    const missingMeta = systemEntry
      ? (systemEntry.missingMetadata || 0) : (detail.totalMissingMetadata || 0);
    const summary = h("div", { class: "cheader-stats" }, [
      h("div", { class: "cheader-stat-group" }, [
        h("span", { class: "cheader-stat", title: "ROM 항목 수" }, [
          icon("cartridge", IC.sm),
          h("span", { class: "cheader-stat-num" }, [formatCount(romCount)]), " ROMs",
        ]),
        h("span", { class: "cheader-stat", title: "Metadata가 있는 항목 수" }, [
          icon("fileText", IC.sm),
          h("span", { class: "cheader-stat-num" }, [formatCount(Math.max(0, romCount - missingMeta))]), " Metadata",
        ]),
      ]),
    ]);
    if (isArchive() && detail.ownershipSummary) {
      const own = detail.ownershipSummary;
      summary.appendChild(h("span", { class: "cheader-stats-divider", "aria-hidden": "true" }, ["|"]));
      summary.appendChild(h("div", {
        class: "cheader-stat-group ownership-summary",
        title: "각 항목의 ROM과 Media 파일 소유 방식",
      }, [
        h("span", { class: "cheader-stat" }, [icon("hardDrive", IC.xs), `보관 ${formatCount(own.internal || 0)}`]),
        h("span", { class: "cheader-stat" }, [icon("link", IC.xs), `연결 ${formatCount(own.linked || 0)}`]),
        h("span", { class: "cheader-stat" }, [icon("arrowLeftRight", IC.xs), `혼합 ${formatCount(own.mixed || 0)}`]),
      ]));
    }
    if (detail.storages.length) {
      summary.appendChild(h("span", { class: "cheader-stats-divider", "aria-hidden": "true" }, ["|"]));
      const storageGroup = h("div", { class: "cheader-stat-group storages" });
      detail.storages.forEach((storage) => {
        // Plan이 있으면 "Actual -> Plan"으로 보여준다(스펙 §19, §30) - Dashboard
        // 목표(다음 줄)와는 다른 얘기다. 이건 "지금 계산해 둔 변경을 Apply하면
        // 얼마가 되는가"고, 목표는 "얼마까지 채워도 되는가"다.
        const capacity = planCapacity(storage.id);
        const changed = capacity && capacity.deltaBytes;
        // **목표는 Dashboard가 정한 값이다.** 없으면(아직 목표를 안 정했으면)
        // 그래프는 무채색이고 경고도 없다 - 정하지 않은 목표를 "넘었다"고 말할
        // 수는 없다.
        const target = S.dashboardTargets[storage.id] || null;
        const ratio = target ? storage.actualBytes / target : null;
        const level = capacityLevel(ratio);
        // 두 가지 "초과"는 서로 다른 얘기다. planOver는 지금 Plan대로 Apply하면
        // 실제 디스크 용량(storage.capacityBytes)을 넘는다는 뜻이고(예전부터 있던
        // 경고), targetOver는 Dashboard에서 정한 목표를 이미 넘었다는 뜻이다(§4
        // 신규). 하나만 있어도 경고 아이콘을 보여준다.
        const planOver = !!(capacity && capacity.over);
        const targetOver = level === "over";
        const fillPct = ratio != null ? `${Math.min(100, Math.max(0, ratio * 100))}%` : "0%";
        const badge = h("span", {
          class: `cheader-storage level-${level}` + (planOver ? " plan-over" : ""),
          title: (planOver ? "Apply하면 디스크 용량을 넘습니다. " : "")
            + (target
              ? `${storage.label} · 목표 ${formatBytes(target)} 중 ${formatBytes(storage.actualBytes)} 사용 (${Math.round(ratio * 100)}%)`
              : `${storage.label} · 목표를 정하지 않았습니다 (Dashboard에서 정할 수 있습니다)`),
        }, [
          `${storage.label} ${formatBytes(storage.actualBytes)}`,
          changed ? ` → ${formatBytes(capacity.planBytes)}` : "",
          // 경고 아이콘 자리는 **항상 차지한다**(보이지 않아도) - 넘었다 안 넘었다에
          // 따라 자리가 생겼다 없어지면 그 옆 뱃지가 매번 밀린다.
          h("span", { class: "cheader-storage-warn" + (targetOver || planOver ? " on" : "") },
            [(targetOver || planOver) ? icon("triangleAlert", IC.xs) : null]),
          // 목표 대비 그래프 - 띠 높이는 절대 안 늘어난다(header-row-h). 자리를
          // 차지하지 않는 절대 위치로 글자 줄 바로 밑(패딩 안)에 겹쳐 그린다.
          target ? h("span", { class: "cheader-storage-track" }, [
            h("span", { class: "cheader-storage-fill", style: { width: fillPct } }),
          ]) : null,
        ]);
        storageGroup.appendChild(badge);
      });
      summary.appendChild(storageGroup);
    }
    main.appendChild(summary);
    compact.appendChild(main);

    const right = h("div", { class: "cheader-right" });
    if (isArchive()) {
    // Archive에는 Collection용 gamelist 만들기/가져오기/Expand가 의미 없다 -
      // 다시 스캔만 있으면 된다(Toolbar에 있던 것과 중복이라 그쪽은 없앴다).
      const refresh = h("button", { class: "icon-btn", title: "다시 스캔" }, [icon("refresh", IC.md)]);
      refresh.addEventListener("click", refreshActive);
      right.appendChild(refresh);
      compact.appendChild(right);
      host.appendChild(compact);
      return;
    }

    // **순서: 메타데이터 보내기, 메타데이터 가져오기, 새로고침, 확장**(실사용 피드백).
    // gamelist 만들기 아이콘은 없앴다 - Storage 그룹 우클릭(부분)과 System 우클릭
    // 메뉴로도 만들 수 있어, Collection 전체 한 번에 만드는 자리는 여기 하나뿐이었다.
    // "Collection 가져오기(Import)"였던 자리는 그 새 Collection 여는 기능(탭 바의
    // "+"와 중복이었다)이 아니라, **이 Collection의 metadata를 Archive와 주고받는
    // 것**으로 바꿨다 - Detail 패널에 있던 "Archive로" 버튼(§6)이 여기로 옮겨 왔다.
    if (!isCompare()) {
      const send = h("button", { class: "icon-btn", title: "Archive로 보내기" },
        [icon("upload", IC.md)]);
      send.addEventListener("click", ingestToArchive);
      right.appendChild(send);

      const importBtn = h("button", { class: "icon-btn", title: "다른 Collection 또는 Archive에서 가져오기" },
        [icon("download", IC.md)]);
      importBtn.addEventListener("click", () => openImportSourceChooser());
      right.appendChild(importBtn);
    }

    // 아이콘만 - 글자("Rescan")는 없앴다. 확장(v) 버튼과 같은 크기로 맞춘다.
    const rescan = h("button", { class: "icon-btn", title: "다시 스캔" }, [icon("refresh", IC.md)]);
    rescan.addEventListener("click", refreshActive);
    right.appendChild(rescan);
    const toggle = h("button", { class: "icon-btn", title: S.headerExpanded ? "접기" : "펼치기" },
      [icon(S.headerExpanded ? "chevronUp" : "chevronDown", 13)]);
    toggle.addEventListener("click", () => { S.headerExpanded = !S.headerExpanded; renderHeader(); });
    right.appendChild(toggle);
    compact.appendChild(right);
    host.appendChild(compact);

    if (!S.headerExpanded) return;

    // 펼친 내용은 목록 기둥 안에 그린다 - 헤더 줄을 키우지 않으려는 것이다(위 주석).
    const expandedHost = $("collection-expanded");
    const panel = h("div", { class: "cheader-expanded" });
    // **카드에 제목을 다시 쓰지 않는다.** 바로 위 띠에 "Collection (SYSTEM)"이 이미
    // 있어서, 큰 글씨로 한 번 더 쓰면 같은 것을 두 번 읽게 된다(사용자 피드백).
    // 콘솔의 정체(포인트 바·그림·색)는 띠가 맡고, 카드는 숫자만 담는다. 다만 색은
    // 카드까지 이어져서 두 줄이 한 덩어리로 보인다.
    if (systemEntry) {
      const palette = systemPalette(systemEntry.system);
      if (palette) {
        panel.style.setProperty("--sys-base", palette.base);
        panel.style.setProperty("--sys-point", palette.points[0]);
      }
    }

    // **왼쪽은 Collection의 정체, 오른쪽은 지금 보고 있는 것의 숫자다.**
    //
    // 예전에는 일곱 줄을 한 단으로 세로로 늘어놓아서, 폭은 남아돌고 높이만 먹었다.
    // 두 단으로 접으면 같은 높이에 두 배를 담을 수 있어서, Scan이 이미 세어 둔
    // 용량·누락 수치를 Dashboard까지 가지 않고 여기서 바로 보여준다.
    const scoped = systemEntry || null;
    const romBytes = scoped ? (scoped.romBytes || 0) : (detail.totalRomBytes || 0);
    const mediaBytes = scoped ? (scoped.mediaBytes || 0) : (detail.totalMediaBytes || 0);
    const noMeta = scoped ? (scoped.missingMetadata || 0) : (detail.totalMissingMetadata || 0);
    const noMedia = scoped ? (scoped.missingMedia || 0) : (detail.totalMissingMedia || 0);

    const info = h("div", { class: "cheader-info" });
    const infoRow = (label, value, warn) => info.appendChild(
      h("div", { class: "cheader-info-row" + (warn ? " warn" : "") }, [
        h("span", { class: "cheader-info-label" }, [label]),
        h("span", { class: "cheader-info-value", title: String(value) }, [String(value)]),
      ]));
    infoRow("Frontend", detail.frontendLabel);
    infoRow("ROM", formatBytes(romBytes));
    infoRow("Target", detail.target || "Unknown");
    infoRow("Media", formatBytes(mediaBytes));
    infoRow("OS", detail.os || "Unknown");
    infoRow("Metadata 없음", formatCount(noMeta), noMeta > 0);
    infoRow("Architecture", detail.arch || "Unknown");
    infoRow("Media 없음", formatCount(noMedia), noMedia > 0);
    infoRow("Root Path", detail.rootPath);
    infoRow(scoped ? "System" : "Systems",
            scoped ? scoped.system.toUpperCase() : formatCount(detail.systemCount));
    panel.appendChild(info);

    detail.storages.forEach((storage) => {
      const box = h("div", { class: "storage-box" });
      box.appendChild(h("div", { class: "storage-box-title" }, [storage.label.toUpperCase()]));
      // **목표를 정했으면 "Capacity" 자리는 전체 하드 용량이 아니라 목표를
      // 보여준다**(실사용 피드백 §4) - 사용자가 실제로 재고 싶은 것은 "이 디스크가
      // 몇 GB냐"가 아니라 "내가 정한 한도까지 얼마나 남았냐"다. 목표를 안 정했으면
      // 예전처럼 디스크 전체 용량이다.
      const target = S.dashboardTargets[storage.id] || null;
      const basis = target || storage.capacityBytes;
      const unknown = basis == null;
      // **Free도 목표를 정했으면 목표 기준이다**(실사용 피드백 - "Free 용량이
      // Target-Actual이 아니라 그냥 하드용량임"). "이 디스크에 몇 GB가 비어
      // 있냐"가 아니라 "내가 정한 한도까지 얼마나 더 채울 수 있냐"가 궁금한
      // 자리이므로, Capacity를 목표로 바꿨다면 Free도 같이 바뀌어야 한다.
      // 물리적으로 그보다 적게 남았으면(디스크가 실제로 더 작으면) 그쪽이
      // 진짜 한계이므로 더 작은 값을 쓴다 - 목표가 물리 용량보다 커도 실제로
      // 채울 수 있는 만큼만 "Free"라고 말해야 한다.
      const targetFree = target != null ? Math.max(0, target - storage.actualBytes) : null;
      const free = target != null
        ? (storage.freeBytes == null ? targetFree : Math.min(targetFree, storage.freeBytes))
        : storage.freeBytes;
      [[target ? "Target" : "Capacity", unknown ? "Unknown" : formatBytes(basis)],
       ["Actual", formatBytes(storage.actualBytes)],
       ["Free", free == null ? "Unknown" : formatBytes(free)]].forEach(([l, v]) => {
        box.appendChild(h("div", { class: "health-row" }, [h("span", {}, [l]), h("span", {}, [v])]));
      });
      if (!unknown && basis > 0) {
        const ratio = storage.actualBytes / basis;
        const used = Math.min(100, ratio * 100);
        // 같은 5단계 색(파랑>녹색>노랑>주황>빨강)을 여기서도 쓴다 - HERO의 그래프와
        // 다른 색을 쓰면 같은 값인데 두 곳이 다른 말을 하는 것처럼 보인다.
        box.appendChild(h("div", { class: `storage-bar level-${capacityLevel(ratio)}` }, [
          h("div", { class: "storage-bar-fill", style: { width: used.toFixed(1) + "%" } })]));
      }
      panel.appendChild(box);
    });

    // Frontend 고유 기능(ES-DE의 custom systems XML)은 여기 두지 않는다 - 그
    // 기능은 External Storage에 있는 System만 대상으로 하므로, Navigator의
    // External Storage 그룹 옆으로 옮겼다(renderNav 참고).
    expandedHost.appendChild(panel);
  }

  async function loadAdapterActions() {
    S.adapterActions = [];
    if (!S.activeId || isArchive()) return;
    const r = await api.adapterActions(S.activeId);
    if (r.ok) S.adapterActions = r.data;
  }

  /** ES-DE XML 생성 결과.
   *
   * 예전에는 문단 세 개(만든 System 목록 / Storage ID 없음 / 템플릿 없음)를 따로
   * 늘어놓았다 - System이 하나뿐이거나 문제가 없으면 그 문단들이 통째로 비어
   * 보였고, 있어도 긴 설명 문장을 읽어야 무슨 일이 있었는지 알 수 있었다(실사용
   * 피드백 - "빈 항목이 너무 많고 설명이 너무 길다"). 지금은 System마다 한 줄,
   * 상태는 글자가 아니라 점 색깔로 말한다.
   */
  async function runAdapterAction(action, storageId, storageLabel) {
    if (blockedInCompare(`${action.label}을 실행`)) return;
    const r = await api.runAdapterAction(S.activeId, action.id, storageId);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const data = r.data || {};
    const needs = data.needsDeviceId || [];
    const noTemplate = new Set(data.noTemplate || []);
    const systems = data.systems || [];
    if (data.written === false && !needs.length) {
      // 만들 내용이 없는 것과 실패한 것은 다르다 - 왜 아무 일도 없었는지 말해준다.
      const why = {
        "no-systems": "이 Storage에 붙은 System이 없습니다. 먼저 Storage의 System을 붙이세요.",
        "android-internal": "Android Internal은 ES-DE 기본 ROM 폴더를 쓰므로 XML에 적지 않습니다. External Storage에서 실행하세요.",
        "inside-root": "ROM이 Collection 폴더 안에 있어 ES-DE가 스스로 찾으므로 적을 것이 없습니다.",
      }[data.reason];
      showToast(`${storageLabel || "이 Storage"}: ${why || "XML로 적을 System이 없습니다."}`, "warning");
      return;
    }
    const rows = [
      ...systems.map((s) => ({ name: s, warn: noTemplate.has(s),
        note: noTemplate.has(s) ? "ES-DE 기본 목록에 없음" : "" })),
      ...needs.map((s) => ({ name: s, warn: true, note: "기기 경로 없음" })),
    ];
    const table = h("div", { class: "xml-table" }, rows.map((row) => h("div", {
      class: "xml-row" + (row.warn ? " warn" : ""), title: row.note || "정상 반영",
    }, [
      h("span", { class: "xml-row-dot" }), h("span", { class: "xml-row-name" }, [row.name]),
      h("span", { class: "xml-row-note" }, [row.note]),
    ])));
    const kept = (data.kept || []).length;
    const body = h("div", { class: "modal-body xml-result" }, [
      h("div", { class: "modal-text" }, [
        `${storageLabel || "External"} · ${formatCount(systems.length + needs.length)}개`,
        kept ? ` (다른 System ${formatCount(kept)}개는 그대로 둠)` : "",
      ]),
      table,
    ]);
    showModal(action.label, body, [h("button", { class: "btn primary", onClick: closeModal }, ["닫기"])]);
  }

  // ------------------------------------------------------------------
  // 필터 바
  // ------------------------------------------------------------------
  // 상태의 뜻을 버튼 툴팁으로 고정한다. 특히 **Same은 "같은 ROM 파일"이라는 뜻이 아니다** -
  // 양쪽에 대응 항목이 있고 비교 대상 Metadata가 같다는 뜻이다. 크기가 달라도 Same일 수
  // 있고, 그 차이는 상세의 Size 줄에서 본다.
  const COMPARE_FILTERS = [
    ["all", "All", "양쪽을 맞댄 전체 목록"],
    ["diff", "Diffs", "다른 항목 전부(≠, >, < - Similar(≒)는 빠진다)"],
    ["same", "Same", "양쪽에 있고 비교 대상 Metadata가 같음 (ROM 파일이 같다는 뜻은 아님 - 크기는 상세에서 확인)"],
    ["only_a", "Only A", "기준 Collection에만 있음"],
    ["only_b", "Only B", "상대 Collection에만 있음"],
    ["conflict", "Conflict", "양쪽에 있는데 Metadata가 다름"],
    ["similar", "Similar", "양쪽에 있고 Metadata는 같은데 Media만 다름"],
    ["media", "Media", "Media 구성이 다름 (상태와 별개 신호)"],
  ];

  /** Compare 상단 막대. **한 줄**이다(사용자 결정) -
   *   [상태 드롭다운] [* ≠ =] [Swap] [새로고침] ............ [Exit Compare]
   * 어느 Collection끼리 비교하는지는 양쪽 Detail 머리에 이미 있어서 여기서 다시 적지 않고,
   * Snapshot 시각도 보이지 않는다(새로고침으로 다시 찍는다). */
  function renderCompareBar(bar) {
    const state = S.compare;
    bar.classList.add("compare");
    const setFilter = async (key) => {
      S.compareFilter = key;
      resetList();
      renderFilterBar();
      await reloadList();
    };

    const select = h("select", { class: "compare-select", title: "표시할 항목" },
      COMPARE_FILTERS.map(([key, label, hint]) => {
        const count = (state.counts || {})[key];
        const option = h("option", { value: key, title: hint },
                         [count === undefined ? label : `${label} (${formatCount(count)})`]);
        return option;
      }));
    select.value = COMPARE_FILTERS.some(([k]) => k === S.compareFilter) ? S.compareFilter : "";
    select.addEventListener("change", () => setFilter(select.value));
    bar.appendChild(select);

    // 자주 쓰는 세 가지는 아이콘 그룹으로도 둔다.
    const group = h("div", { class: "cmp-group" });
    [["all", "*", "모든 항목"], ["diff", "≠", "메타데이터가 다른 항목(≠ > <)"],
     ["similar", "≒", "메타데이터는 같고 미디어만 다른 항목"], ["same", "=", "같은 항목"]]
      .forEach(([key, glyph, tip]) => {
        const btn = h("button", {
          class: `cmp-group-btn g-${key}` + (S.compareFilter === key ? " active" : ""), title: tip,
        }, [glyph]);
        btn.addEventListener("click", () => setFilter(key));
        group.appendChild(btn);
      });
    bar.appendChild(group);

    // 고른 항목들의 메타데이터+미디어를 반대쪽으로 덮어쓴다(사용자 결정). ROM은 건드리지 않는다 -
    // ROM을 옮기는 것은 행 가운데의 `>` `<`(한쪽에만 ROM이 있을 때)가 맡는다.
    const sendSelected = (direction, label, tip) => {
      const btn = h("button", {
        class: "cmp-send", "data-dir": direction, disabled: !S.selected.size,
        title: S.selected.size
          ? (S.compareMediaSel.size ? `고른 항목의 미디어(${[...S.compareMediaSel].join(", ")})만 보냅니다(Plan)` : tip)
          : "보낼 항목을 먼저 고르세요",
      }, [label]);
      btn.addEventListener("click", () => compareSendSelected(direction));
      return btn;
    };
    bar.appendChild(h("div", { class: "cmp-group cmp-send-group" }, [
      sendSelected("toLeft", "\u276e", "고른 항목의 메타데이터+미디어를 왼쪽으로 덮어씁니다(Plan)"),
      sendSelected("toRight", "\u276f", "고른 항목의 메타데이터+미디어를 오른쪽으로 덮어씁니다(Plan)"),
      manualLinkButton(),
    ]));

    // Swap/새로고침은 **아이콘만**이다(사용자 결정) - 글자까지 넣으면 한 줄이 비좁다.
    const tool = (name, tip, onClick) => {
      const btn = h("button", { class: "cmp-tool icon-only", title: tip }, [icon(name, IC.sm)]);
      btn.addEventListener("click", onClick);
      return btn;
    };
    bar.appendChild(tool("arrowLeftRight", "기준과 상대를 바꿉니다 (Swap)",
      () => runCompare(state.otherId, state.baseId)));
    bar.appendChild(tool("refresh", "지금 상태로 다시 비교합니다 (새로고침)",
      () => runCompare(state.baseId, state.otherId)));

    bar.appendChild(h("div", { class: "filter-spacer" }));

    const exit = h("button", { class: "cmp-exit" }, ["Exit Compare"]);
    exit.addEventListener("click", exitCompare);
    bar.appendChild(exit);
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

    // **순서: LIST/CARD, Favorite, 우선정렬, Search**(실사용 피드백).
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

    // Archive에만 있는 필터 - **충돌(출처 간 내용이 실제로 다른 항목)만** 본다(사용자
    // 결정 - "유사롬만 골라서 볼 수 있는 filter 옵션"). 고를 것이 있는 항목만 남으므로
    // 정리할 때 그것만 훑으면 된다. 아이콘/문구를 System 목록의 "!" 충돌 표시와 같은
    // 언어로 맞췄다(사용자 지적 - 예전엔 "copy" 아이콘이라 충돌 필터인지 알아보기
    // 어려웠다).
    if (isArchive()) {
      const onlyDiff = h("button", {
        class: "icon-btn archive-conflicts-only" + (S.archiveConflictsOnly ? " on" : ""),
        title: S.archiveConflictsOnly ? "전체 보기" : "충돌(출처 간 내용이 다른 항목)만 보기",
      }, [icon("alertTriangle", IC.md)]);
      onlyDiff.addEventListener("click", async () => {
        S.archiveConflictsOnly = !S.archiveConflictsOnly;
        renderFilterBar();
        resetList();
        await reloadList();
      });
      bar.appendChild(onlyDiff);
    }

    // **예전 "상태 필터"는 실제로 아무것도 걸러내지 못했다** - currentQuery()가
    // 그 값을 끝내 읽지 않아서, 셀렉트를 바꿔도 목록은 그대로였다(실사용 피드백).
    // 그 자리를 필터가 아니라 **1차 정렬 기준**으로 바꿨다 - "있는 항목"이
    // "없는 항목"보다 먼저 오고, 그 안에서는 기존 정렬(제목/파일명 등)이 그대로
    // 2차 기준이다. "구분 없음"은 예전과 똑같이 동작한다(1차 기준이 없을 뿐).
    const prioritySel = h("select", { class: "mini-select", title: "우선 정렬" }, [
      h("option", { value: "" }, ["전체보기"]),
      h("option", { value: "rom" }, ["ROM 우선"]),
      h("option", { value: "metadata" }, ["메타데이터 우선"]),
      h("option", { value: "media" }, ["미디어 우선"]),
      h("option", { value: "desc_language",
        title: "Settings의 Language에 맞는 문자 종류를 우선합니다. 언어 태그가 없어 영어·프랑스어·스페인어는 구별하지 못합니다." }, ["언어 우선"]),
    ]);
    prioritySel.value = S.sortPriority || "";
    prioritySel.addEventListener("change", async (e) => {
      S.sortPriority = e.target.value || null;
      resetList();
      await reloadList();
    });
    bar.appendChild(prioritySel);

    // 정렬 셀렉트는 따로 두지 않는다 - 목록 머리글(#list-head)이 Card 보기에서도
    // 그대로 보이고 클릭도 되므로(실사용 확인) 따로 둘 이유가 없다.

    const search = h("input", { class: "search-input", placeholder: "Search...", value: S.search });
    let timer = null;
    search.addEventListener("input", (e) => {
      clearTimeout(timer);
      const value = e.target.value;
      timer = setTimeout(async () => { S.search = value; resetList(); await reloadList(); }, 180);
    });
    bar.appendChild(h("div", { class: "search-box" }, [icon("search", IC.md), search]));

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
  const currentPasteMode = () => "overwrite";

  function renderPlanActions(bar) {
    if (isCompare()) return;
    if (isArchive()) {
      return;
    }

  }

  /** 선택이 바뀌었을 때 툴바에서 **실제로 달라지는 것만** 고친다.
   *
   * 툴바를 통째로 다시 그리면 검색창이 새로 만들어져 입력 중이던 커서가 날아간다.
   * 선택 때문에 달라지는 것은 수집 대상 표시뿐이다(Delete는 상시 버튼이 없다).
   */
  function updateSelectionDependentActions() {
    // Compare 상단의 `<` `>`는 고른 항목이 있을 때만 눌린다.
    document.querySelectorAll(".cmp-send").forEach((btn) => {
      btn.disabled = !S.selected.size;
      btn.title = S.selected.size
        ? `고른 항목의 메타데이터+미디어를 ${btn.dataset.dir === "toLeft" ? "왼쪽" : "오른쪽"}으로 덮어씁니다(Plan)`
        : "보낼 항목을 먼저 고르세요";
    });
    // 직접 잇기도 같다 - 한쪽에만 있는 두 항목을 좌우에서 하나씩 골랐을 때만 눌린다.
    document.querySelectorAll(".cmp-link").forEach((btn) => {
      const pair = manualLinkPair();
      btn.disabled = !pair;
      btn.title = pair
        ? `«${pair.a.file}»와 «${pair.b.file}»를 직접 잉습니다`
        : "한쪽에만 있는 항목을 좌우에서 하나씩, 둘만 고르면 직접 이을 수 있습니다";
      btn.onclick = pair ? () => openManualLinkDialog(pair) : null;
    });
    // "Archive로 보내기"는 HERO 아이콘에서 현재 scope를 계산해 Plan에 담는다.
    // 여기서 선택이 바뀔 때마다 따로 패치해 둘 상태가 없다.
    //
    // Archive 탭의 "Collection으로 보내기"는 여전히 Detail 패널 상단에 있다 - 선택이
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

  /** 머리글을 끌어 컬럼 순서를 바꾼다. 놓는 자리의 왼쪽/오른쪽 절반으로 앞/뒤를 정한다.
   * No./Title도 다른 컬럼과 동일하게 끌 수 있다(사용자 결정, 메뉴 정리 §5). */
  let draggingColumn = null;
  function bindColumnDrag(cell, id) {
    const clearMarks = () => cell.classList.remove("drop-before", "drop-after");
    cell.draggable = true;
    cell.addEventListener("dragstart", (e) => {
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
      const after = e.clientX > rect.left + rect.width / 2;
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
    order.forEach((id) => {
      const locked = isLastVisible(id, order, hidden);
      const visible = !hidden.has(id);
      items.push({
        label: columnName(COLUMN_BY_ID[id]), icon: visible ? "check" : null, disabled: locked,
        hint: locked ? "마지막 컬럼" : null, title: locked ? "적어도 하나는 표시되어야 합니다." : null,
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
    if (isArchive()) return api.archiveRows({ ...query, conflictsOnly: S.archiveConflictsOnly });
    return api.listRows(S.activeId, query);
  }

  async function reloadList() {
    if (!S.activeId) { renderListWindow(); return; }
    const token = ++S.queryToken;
    const r = await fetchRows({ ...currentQuery(), limit: PAGE_SIZE, offset: 0 });
    // 버릴지부터 정한다 - 실패 여부보다 먼저다. 순서가 반대면 이미 떠난 System의
    // 실패가 지금 보고 있는 System 위로 토스트를 띄운다.
    if (token !== S.queryToken) return;   // 더 최신 요청이 있으면 버린다
    if (!r.ok) { showToast(r.error, "error"); return; }
    S.total = r.data.total;
    // A rescan may assign new romUid values. Never retain old virtual pages
    // alongside the new first page: they can open a different game's detail.
    S.rowCache.clear();
    S.loadedPages.clear();
    S.loadedPages.add(0);
    r.data.rows.forEach((row, i) => S.rowCache.set(i, row));
    const totalEl = $("filter-total");
    if (totalEl) totalEl.textContent = `${formatCount(S.total)} items`;
    renderListWindow();
    loadMatchCounts(r.data.rows, token);
  }

  /** `[n]` 뱃지는 목록 렌더링을 막지 않고 뒤따라 채운다.
   *
   * **Archive에서만 나온다**(사용자 결정) - 같은 ROM에 Title/Description/주요 Media가 다른
   * 버전이 둘 이상 있고 아직 고르지 않았을 때만 개수를 보여준다. Collection에는 Matching이
   * 없다: 같은 것만 같은 것으로 다루고, 여러 후보를 고르게 하지 않는다. */
  async function loadMatchCounts(rows, token) {
    if (!isArchive() || !rows.length) return;
    const scope = activeScope();
    const ids = rows.map((row) => String(row.romIdentityId || row.romUid)).filter(Boolean);
    const r = await api.archiveConflicts(scope.kind === "system" ? [scope.id] : null, ids);
    if (!r.ok || token !== S.queryToken) return;
    // 새 페이지의 결과만 합친다. 전체 Archive를 스크롤마다 다시 계산하지 않는다.
    let changed = false;
    ids.forEach((id) => {
      const next = (r.data || {})[id];
      if (S.matchCounts[id] !== next) changed = true;
      if (next === undefined) delete S.matchCounts[id];
      else S.matchCounts[id] = next;
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

  /** Compare 가운데 연산자 칸(사용자 결정).
   *
   *   =  양쪽 ROM도 메타데이터/미디어도 같다
   *   ≠  ROM은 양쪽에 있는데 메타데이터 또는 미디어가 다르다
   *   >  ROM이 왼쪽(기준)에만 있다       <  ROM이 오른쪽(상대)에만 있다
   *
   * `>` `<`는 그대로 버튼이다 - 누르면 ROM+메타데이터를 반대쪽 Plan에 올린다.
   * `≠`는 그 자체로는 방향이 없어서 **양옆에 작은 화살표가 뜨고**(행 높이가 변하지 않는다 -
   * 가상 스크롤 목록에 높이가 변하는 행을 만들면 예전에 행 레이아웃이 깨졌던 문제가 되돌아온다)
   * 그것을 누르면 메타데이터만 보낸다. 실제 파일은 Plan에서 Apply해야 바뀐다. */
  function compareMark(row) {
    if (row.status === "only_a" || row.status === "only_b") {
      const toRight = row.status === "only_a";
      const cell = h("button", {
        class: "cmp-op one-side",
        title: toRight ? "오른쪽으로 ROM+메타데이터를 보냅니다" : "왼쪽으로 ROM+메타데이터를 보냅니다",
      }, [toRight ? ">" : "<"]);
      cell.addEventListener("click", (e) => {
        e.stopPropagation();
        compareCopyRow(row, toRight ? "toRight" : "toLeft", false);
      });
      return cell;
    }
    // `conflict`(Metadata가 다르다, ≠)와 `similar`(Metadata는 같고 Media만 다르다, ≒)는
    // 예전엔 하나로 뭉쳐 있었다 - Cover/Screenshot이 겉보기엔 같은데 다른 Media 종류가
    // 달라서 ≠가 뜨면 "메타데이터도 같은데 왜 다르지?"로 오해를 샀다(실사용 버그
    // 리포트). 지금은 상태 자체를 갈라서 기호와 색으로 구분한다 - 둘 다 화살표로
    // 메타데이터(+similar는 media도)를 반대쪽에 보낼 수 있는 건 같다.
    if (row.status === "conflict" || row.status === "similar") {
      const isSimilar = row.status === "similar";
      const cell = h("div", { class: "cmp-op diff" + (isSimilar ? " similar" : ""),
        title: isSimilar ? "미디어가 다릅니다(메타데이터는 같습니다)" : "메타데이터가 다릅니다" });
      const arrow = (dir, label, tip) => {
        const btn = h("button", { class: "cmp-op-arrow", title: tip }, [label]);
        btn.addEventListener("click", (e) => { e.stopPropagation(); compareCopyRow(row, dir, true); });
        return btn;
      };
      cell.appendChild(arrow("toLeft", "<", "오른쪽 내용을 왼쪽으로 보냅니다(Plan)"));
      cell.appendChild(h("span", { class: "cmp-op-symbol" }, [isSimilar ? "≒" : "≠"]));
      cell.appendChild(arrow("toRight", ">", "왼쪽 내용을 오른쪽으로 보냅니다(Plan)"));
      return cell;
    }
    return h("div", { class: "cmp-op same", title: "양쪽이 같습니다" }, ["="]);
  }

  /** 연산자 버튼이 부르는 것 - 실제 파일은 건드리지 않고 반대쪽 Plan에만 올린다. */
  async function compareCopyRow(row, direction, metadataOnly) {
    await runCompareOperation({keys: [row.key], direction, metadataOnly});
  }

  //: Gamelist Status 아이콘 4개(실사용 피드백 - "Missing Rom/Media/Description/Cover가
  //: 아이콘으로 나오는게 낫겠음. 각 아이콘은 독립적으로 한 칸을 차지하고, 2개 이상
  //: 해당되어도 각 위치에 아이콘이 표기"). 예전엔 우선순위대로 기호 하나만
  //: 보여줬다("·"/"△") - 문제가 두 개 이상이면 하나만 보이고 나머지는 숨겨졌다.
  //: 이제 네 칸이 각자의 자리를 차지하고, 없는 항목만 빨갛게 켜진다.
  // 사용자 결정(2026-09-17/20): ROM / Metadata / Media / Video 네 칸. 상태는 세 가지다.
  //   ok(흰색) 다 있음 · partial(노란색) 일부만 있음 · none(회색) 없음. **빨간색은 쓰지 않는다** -
  //   없는 것이 오류는 아니다.
  //   Metadata: Title+Description이 다 있으면 ok. Media: cover/screenshot/marquee/miximage가 다 있으면 ok.
  const STATUS_ICON_DEFS = [
    { key: "rom", icon: "gamepad", label: "ROM", part: "rom" },
    { key: "metaLevel", icon: "fileText", label: "Metadata", part: "metadata",
      partial: "Title 또는 Description이 비어 있음" },
    { key: "mediaLevel", icon: "image", label: "Media", part: "media",
      partial: "주요 미디어(cover/screenshot/marquee/miximage) 중 일부가 없음" },
    { key: "videoLevel", icon: "play", label: "Video", part: "video" },
  ];

  /** Status 아이콘 우클릭 - 그 칸에 해당하는 것만 지운다.
   * 없는 칸(회색)은 지울 것이 없으므로 흐리게 둔다. */
  function openStatusMenu(row, def, event) {
    if (isCompare()) return;
    if (!S.selected.has(row.romUid)) {
      S.selected = new Set([row.romUid]);
      S.selectAnchor = row.romUid;
      updateSelectionVisual();
      renderStatusBar();
    }
    const count = S.selected.size;
    const names = { rom: "ROM 삭제", metadata: "메타데이터 삭제(gamelist 항목)",
                    media: "미디어 삭제(영상 제외)", video: "영상 삭제" };
    if (isArchive()) {
      const ids = [...S.selected];
      const ownedRom = ids.some((uid) => ["internal", "mixed"].includes(
        (rowByUid(uid) || {}).ownership?.rom?.mode));
      const enabled = def.level !== "none" && (def.part !== "rom" || ownedRom);
      showContextMenu(menuPoint(event), def.label,
        ids.length > 1 ? `${formatCount(ids.length)}개 선택됨` : (row.title || row.file), [
          { label: names[def.part], icon: "trash", danger: true, disabled: !enabled,
            title: def.level === "none" ? `${def.label}이(가) 없습니다.`
                : !ownedRom && def.part === "rom" ? "외부 원본 ROM은 삭제할 수 없습니다." : null,
            onSelect: () => {
              if (def.part === "rom") { deleteArchiveOwnedRoms(); return; }
              if (def.part === "metadata") { deleteArchiveMetadata(); return; }
              showConfirm(`Archive ${names[def.part]}`,
                `선택한 ${formatCount(ids.length)}개 항목에서 Archive가 보관하는 ${def.label}만 삭제합니다. `
                + "외부 원본 파일은 유지합니다.", true, async () => {
                  const r = await api.archiveMediaDeleteSelected(ids, def.part);
                  if (!r.ok) { showToast(r.error, "error"); return; }
                  resetList();
                  await reloadList();
                  showToast(`Archive 보관 ${def.label} ${formatCount(r.data.removed || 0)}개를 삭제했습니다.`
                    + ((r.data.linkedKept || 0) ? ` 원본 연결 ${formatCount(r.data.linkedKept)}개는 유지했습니다.` : ""));
                });
            } },
        ]);
      return;
    }
    showContextMenu(menuPoint(event), def.label,
      count > 1 ? `${formatCount(count)}개 선택됨` : (row.title || row.file), [
        { label: names[def.part], icon: "trash", danger: true, disabled: def.level === "none",
          title: def.level === "none" ? `${def.label}이(가) 없습니다.` : null,
          onSelect: () => deleteSelection([def.part]) },
      ]);
  }

  function statusIcons(row) {
    // Metadata 전용 Collection(ROM 폴더를 주지 않은 기기)에서는 ROM이 없는 것이
    // 정상이다 - 그 칸만 빨갛게 켜지 않는다(자리는 그대로 유지해 칸 정렬이 흔들리지
    // 않게 한다).
    const metaOnly = !!(activeDetail() && activeDetail().metadataOnly);
    return STATUS_ICON_DEFS.map(({ key, icon: name, label, partial, part }) => {
      // 예전 응답(수준 값 없음)도 견디도록 불리언 필드로 떨어진다.
      let level = row[key] || (row.present !== undefined && key === "rom" ? (row.present ? "ok" : "none") : "none");
      if (key === "rom" && metaOnly && level === "none") level = "ok";
      const text = level === "ok" ? label : level === "partial" ? `${label}: ${partial || "일부만 있음"}` : `${label} 없음`;
      const el = h("span", { class: `status-icon lv-${level}`, title: text,
                             "data-status": key }, [icon(name, 12)]);
      // 아이콘을 우클릭하면 **그 칸만** 지우는 메뉴가 뜬다(사용자 결정) - 행 우클릭 메뉴가 뜨지 않게 막는다.
      el.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        e.stopPropagation();
        openStatusMenu(row, { key, label, part, level }, e);
      });
      return el;
    });
  }

  function statusMark(row) {
    // Plan 상태가 있으면 그것이 우선이다 - 지금 뭐가 없는지보다 "곧 뭐가 바뀌는지"가
    // 더 급한 정보다. 기호는 작게만 표시하고 제목이나 설명 전체를 색칠하지 않는다
    // (스펙 §24).
    const marks = (S.plan && S.plan.marks) || { rows: {}, systems: [] };
    const mark = marks.rows[`${row.system}|${row.file}`];
    if (mark === "+") return [h("span", { class: "status-mark add", title: "추가 예정" }, ["+"])];
    if (mark === "-") return [h("span", { class: "status-mark del", title: "삭제 예정" }, ["−"])];
    if (mark === "\u25d0") {
      const parts = ((marks.deleteParts || {})[`${row.system}|${row.file}`] || [])
        .map((p) => DELETE_PART_LABEL[p]).join(" + ");
      return [h("span", { class: "status-mark del", title: `일부 삭제 예정: ${parts}` }, ["\u25d0"])];
    }
    if (mark === "✎") return [h("span", { class: "status-mark edit", title: "편집 예정 (Apply해야 반영)" }, ["✎"])];
    if ((marks.systems || []).includes(row.system)) {
      return [h("span", { class: "status-mark warn", title: "Storage 이동 예정" }, ["△"])];
    }
    return statusIcons(row);
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
      win.style.width = "";
      win.style.height = "";
      if (isArchive() && !S.archiveConfigured) {
        // 설정이 없을 때의 빈 화면 - 무엇을 해야 하는지 바로 누를 수 있게 한다.
        // #list-window는 가상 스크롤을 위해 position:absolute라 너비가 없으면 내용
        // 크기로 쪼그라들어 왼쪽 위에 붙어 보였다(실사용 버그 리포트) - 뷰포트를
        // 그대로 채워야 .archive-empty의 flex 가운데 정렬이 뜻대로 동작한다.
        win.style.width = scroll.clientWidth + "px";
        win.style.height = scroll.clientHeight + "px";
        const set = h("button", { class: "btn primary archive-setup" }, ["Archive 설정"]);
        set.addEventListener("click", openArchiveSettings);
        win.appendChild(h("div", { class: "archive-empty" }, [
          h("div", { class: "archive-empty-title" }, ["Archive를 어디에 어떤 형식으로 저장할지 정하세요."]),
          h("div", { class: "stg-help" }, ["폴더와 Frontend 형식을 정하면 그 폴더에 gamelist/미디어가 저장됩니다."]),
          set,
        ]));
        return;
      }
      win.style.width = scroll.clientWidth + "px";
      win.style.height = scroll.clientHeight + "px";
      win.appendChild(h("div", { class: "archive-empty" }, [
        activeDetail() ? "조건에 맞는 게임이 없습니다."
                       : "등록된 Collection이 없습니다. 상단의 \"+\"를 눌러 추가하세요.",
        !activeDetail() && !S.archiveConfigured
          ? h("button", { class: "btn compact", onClick: openArchiveSettings },
            ["Archive는 Settings에서 선택해 사용할 수 있습니다."])
          : null,
      ]));
      return;
    }

    if (S.viewMode === "card" && !isCompare()) { renderCardWindow(scroll, spacer, win); return; }

    win.classList.remove("card-mode");
    resetCardWindow(win);
    // 빈 목록 화면에서 지정한 픽셀 폭이 Compare/일반 목록에 남으면 창을
    // 넓혀도 목록이 그 폭에 묶인다. 가상 스크롤 폭은 아래 minWidth로 정한다.
    win.style.width = "";
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
      cover.appendChild(icon("imageOff", IC.lg));
    }
    card.appendChild(cover);
    card.appendChild(h("div", { class: "preview-title truncate", title: row.title || row.file },
                       [row.title || row.file]));
    card.addEventListener("click", (e) => handleRowClick(e, row, index));
    card.addEventListener("dblclick", (e) => { if (!e.target.closest("button")) launchGame(row); });
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
      // Compare의 열쇠는 문자열(system|file)이라 숫자로 바꾸면 NaN이 된다.
      const key = isCompare() || isArchive() ? el.dataset.romUid : Number(el.dataset.romUid);
      el.classList.toggle("selected", S.selected.has(key));
      el.classList.toggle("focused", S.focused === key);
    });
  }

  /** 아직 받지 않은 줄의 자리표시. **실제 행과 같은 컬럼 틀을 쓴다.**
   *
   * 예전엔 컬럼 폭 없이 칸 세 개만 넣어서, 스크롤하는 동안 그 줄들이 한 칸짜리 전체
   * 폭으로 그려졌다가 데이터가 오면 제 폭으로 돌아갔다(실사용 피드백: "스크롤 중 File
   * 쪽 넓이가 커졌다가 스크롤이 끝나면 원래 크기로 돌아온다"). */
  function placeholderRow(index) {
    // Compare든 아니든 헤더와 같은 grid-template을 써야 한다 - `.lrow`는 기본
    // grid-template-columns이 없어서(studio.css), 안 주면 모든 칸이 암시적으로
    // 한 칸에 겹쳐 그려진다(실사용 피드백 - "gamelist 상에 표시 내용이 걸쳐서
    // 표기됨"의 원인이 정확히 이것이었다).
    return h("div", {
      class: "lrow placeholder" + (isCompare() ? " compare-row" : ""),
      style: { height: ROW_HEIGHT + "px", gridTemplateColumns: gridTemplate() },
    }, visibleColumns().map((col) => h("div", { class: "lc lc-" + col.id },
      col.id === "no" ? [truncSpan(String(index + 1))]
        : /^(file|title|src(File|Title)|dst(File|Title))$/.test(col.id)
          ? [h("span", { class: "skeleton" })] : [])));
  }

  /** Compare 목록의 행. **헤더와 같은 컬럼 틀(visibleColumns())을 그대로 쓴다** -
   * 예전엔 File/Title/Status만 담은 고정 6칸을 grid-template 없이 그렸는데, `.lrow`
   * 기본값에 grid-template-columns이 없어서 모든 칸이 암시적으로 첫 칸 하나에
   * 겹쳐 그려졌다(실사용 피드백 - "gamelist 상에 표시 내용이 걸쳐서 표기됨").
   * Region/Rating/Genre/★처럼 좌우 비교에 뜻이 없는 칸은 비워 두되 자리는
   * 유지한다 - 그래야 헤더와 계속 줄이 맞는다.
   */
  function compareRowElement(row, index) {
    const el = h("div", {
      class: "lrow compare-row" + (S.selected.has(row.key) ? " selected" : "")
        + (S.focused === row.key ? " focused" : "") + " s-" + row.status,
      // 일반 Gamelist와 **같은 열쇠 이름**을 쓴다 - 선택 표시(updateSelectionVisual)가
      // 두 화면에서 같은 코드로 돌아간다.
      "data-rom-uid": row.key, "data-cmp-key": row.key,
      style: { height: ROW_HEIGHT + "px", gridTemplateColumns: gridTemplate() },
    });
    // ROM이 없는 쪽은 비워 두어 두 줄이 같은 높이에서 마주 보게 한다 - 그래야 >와 <가
    // "어느 쪽에 ROM이 없는지"를 말해 준다. 없다는 판단은 gamelist 항목이 아니라 ROM이다.
    const side = (file, title, present, kind) => {
      if (file === null || file === undefined) return h("div", { class: `lc lc-${kind} cmp-absent` }, ["—"]);
      const norom = present === false ? " rom-missing" : "";
      if (kind.endsWith("File")) {
        return h("div", { class: `lc lc-${kind}${norom}`, title: present === false ? `${file} - ROM 파일 없음` : file },
                 [truncSpan(file)]);
      }
      return h("div", { class: `lc lc-${kind}` }, [
        systemIcon(row.system, 15),
        h("span", { class: "lrow-title truncate" }, [title || file]),
      ]);
    };
    const cells = {
      no: h("div", { class: "lc lc-no" }, [truncSpan(String(index + 1))]),
      srcFile: side(row.leftFile, row.leftTitle, row.leftPresent, "srcFile"),
      srcTitle: side(row.leftFile, row.leftTitle, row.leftPresent, "srcTitle"),
      op: h("div", { class: "lc lc-op" }, [compareMark(row)]),
      dstFile: side(row.rightFile, row.rightTitle, row.rightPresent, "dstFile"),
      dstTitle: side(row.rightFile, row.rightTitle, row.rightPresent, "dstTitle"),
    };
    visibleColumns().forEach((col) => el.appendChild(cells[col.id]));
    // Gamelist와 같은 선택 규칙(Ctrl 추가, Shift 범위). 그냥 누르면 한 개 선택 + 상세 열기다.
    el.addEventListener("click", (e) => {
      handleRowClick(e, row, index);
      if (!e.shiftKey && !(e.ctrlKey || e.metaKey)) openCompareDetail(row);
    });
    return el;
  }

  function rowElement(row, index) {
    if (isCompare()) return compareRowElement(row, index);
    const selected = S.selected.has(row.romUid);
    // **행 전체를 물들이지 않는다**(사용자 결정 - "plan은 전체 색이 아니라 no쪽에 + - 를 표시").
    // 행 전체가 붉어지면 선택/포커스 색과 겹쳐서 지금 무엇을 고른 것인지 오히려 흐려진다.
    const mark = ((S.plan && S.plan.marks) || { rows: {} }).rows[`${row.system}|${row.file}`];
    const el = h("div", {
      class: "lrow" + (selected ? " selected" : "") + (S.focused === row.romUid ? " focused" : ""),
      // 카드와 같은 열쇠. 선택이 바뀔 때 목록을 다시 짓지 않고 이 행만 고친다.
      "data-rom-uid": String(row.romUid),
      style: { height: ROW_HEIGHT + "px", gridTemplateColumns: gridTemplate() },
    });

    // No. - 화면에 보이는 순번이 아니라 목록 전체에서의 순번이다.
    // 칸은 id별로 만들어 두고, 마지막에 사용자가 정한 순서/표시대로 붙인다.
    //
    // **추가/삭제 예정 행은 번호 대신 +/- 아이콘이 선다**(사용자 결정 - "어차피
    // 숫자는 의미가 없는데"). No. 칸은 Status 칸(오른쪽 끝)보다 훨씬 먼저 눈에
    // 들어오는 자리라, 스크롤하면서 바로 알아볼 수 있다.
    // 편집 예정(제목 등 정보가 덮어써질 예정)은 +/-와는 다른 뜻이라 파란
    // 문서 아이콘으로 구분한다(사용자 결정 - "정보가 덮어질 항목은 +-말고
    // 문서아이콘으로 파란색으로").
    const NO_MARK = { "+": ["plus", "add", "추가 예정"], "-": ["minus", "del", "삭제 예정"],
                      "\u25d0": ["minus", "del partial", "일부 삭제 예정(ROM/메타데이터/미디어 중 일부)"],
                      "✎": ["fileText", "edit", "정보 편집 예정"] };
    const cells = {};
    const noMark = NO_MARK[mark];
    cells.no = h("div", { class: "lc lc-no" }, noMark
      ? [h("span", { class: "lno-mark " + noMark[1], title: noMark[2] }, [icon(noMark[0], IC.sm)])]
      : [truncSpan(String(index + 1))]);
    // ROM 파일이 실제로 있으면 파일명을 제목과 같은 색으로, 없으면(메타데이터만) 흐리게.
    // Metadata 전용 Collection에서는 ROM이 없는 것이 정상이라 흐리게 하지 않는다.
    const missingRom = row.present === false && !(activeDetail() && activeDetail().metadataOnly);
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
      const badge = h("button", { class: "match-badge", title: "서로 다른 버전 보기" },
        [`[${matchCount}]`]);
      badge.addEventListener("click", (e) => { e.stopPropagation(); openVersionDialog(row); });
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
    cells.status = h("div", { class: "lc lc-status" }, statusMark(row));
    visibleColumns().forEach((col) => el.appendChild(cells[col.id]));

    el.addEventListener("click", (e) => handleRowClick(e, row, index));
    el.addEventListener("dblclick", (e) => { if (!e.target.closest("button")) launchGame(row); });
    el.addEventListener("contextmenu", (e) => { e.preventDefault(); openRowMenu(row, e); });
    // **게임을 끌어 다른 System으로 옮긴다**(사용자 결정, ES-DE 계열 제외 - 아래 dropGamesOnSystem).
    // 끌기 시작한 행이 선택에 없으면 그 행 하나만 대상이다(탐색기와 같다).
    if (!isCompare() && !isArchive()) {
      el.draggable = true;
      el.addEventListener("dragstart", (e) => {
        if (!S.selected.has(row.romUid)) {
          S.selected = new Set([row.romUid]);
          S.selectAnchor = row.romUid;
          updateSelectionVisual();
          renderStatusBar();
        }
        e.dataTransfer.setData(GAME_DRAG_TYPE, JSON.stringify([...S.selected]));
        e.dataTransfer.effectAllowed = "move";
      });
    }
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
  function showContextMenu(point, title, subtitle, items, headTip, titleIcon) {
    closeContextMenu();
    const menu = h("div", { class: "ctx-menu", role: "menu" });
    let subMenu = null;
    const closeSubmenu = () => { if (subMenu) { subMenu.remove(); subMenu = null; } };
    if (title) {
      const titleRow = titleIcon
        ? h("div", { class: "ctx-title" }, [titleIcon, h("span", {}, [title])])
        : h("div", { class: "ctx-title" }, [title]);
      menu.appendChild(h("div", { class: "ctx-head", title: headTip || null }, [
        titleRow,
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
        item.children ? h("span", { class: "ctx-hint" }, ["›"]) : null,
      ]);
      const openSubmenu = () => {
        closeSubmenu();
        if (!item.children || item.disabled) return;
        subMenu = h("div", { class: "ctx-menu ctx-submenu", role: "menu" });
        item.children.forEach((child) => {
          const action = h("button", {
            class: "ctx-item" + (child.danger ? " danger" : ""), role: "menuitem",
            disabled: !!child.disabled, title: child.title || null,
          }, [child.icon ? icon(child.icon, 12) : h("span", { class: "ctx-icon-gap" }),
              h("span", { class: "ctx-label" }, [child.label])]);
          action.addEventListener("click", () => { closeContextMenu(); child.onSelect(); });
          subMenu.appendChild(action);
        });
        document.body.appendChild(subMenu);
        const rect = btn.getBoundingClientRect();
        const subWidth = subMenu.getBoundingClientRect().width;
        subMenu.style.left = `${rect.right + subWidth < window.innerWidth ? rect.right : rect.left - subWidth}px`;
        subMenu.style.top = `${Math.max(4, Math.min(rect.top, window.innerHeight - subMenu.offsetHeight - 4))}px`;
      };
      if (item.children) btn.addEventListener("mouseenter", openSubmenu);
      btn.addEventListener("click", () => {
        if (item.children) { openSubmenu(); subMenu?.querySelector(".ctx-item:not(:disabled)")?.focus(); }
        else { closeContextMenu(); item.onSelect(); }
      });
      if (!item.children) btn.addEventListener("mouseenter", closeSubmenu);
      menu.appendChild(btn);
      if (!item.disabled) buttons.push(btn);
    });
    document.body.appendChild(menu);
    const rect = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(4, Math.min(point.x, window.innerWidth - rect.width - 4))}px`;
    menu.style.top = `${Math.max(4, Math.min(point.y, window.innerHeight - rect.height - 4))}px`;

    const onDown = (e) => {
      if (!menu.contains(e.target) && !(subMenu && subMenu.contains(e.target))) closeContextMenu();
    };
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
    menu.addEventListener("scroll", closeSubmenu);
    setTimeout(() => document.addEventListener("mousedown", onDown, true), 0);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("blur", onLeave);
    window.addEventListener("resize", onLeave);
    contextMenuCleanup = () => {
      closeSubmenu();
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

  /** 이 행의 선택 열쇠. **Compare는 romUid가 없다** - 한 행이 좌/우 두 항목의 짝이라
   * 어느 쪽 romUid를 써도 한쪽에만 있는 행을 가리키지 못한다. `key`(system|file)가 그 자리를 맡는다. */
  const rowKey = (row) => (row && row.key !== undefined ? row.key : row && row.romUid);

  function rowByUid(romUid) {
    for (const row of S.rowCache.values()) if (row && row.romUid === romUid) return row;
    return null;
  }

  /** 지금 고른 행이 **딱 하나**일 때 그 열쇠("system|파일명"). 아니면 null.
   * 붙여넣기가 "이름으로는 대상을 못 찾겠을 때 고른 행에 붙인다"를 판단하는 데 쓴다. */
  function selectedRowKey() {
    if (S.selected.size !== 1) return null;
    const row = rowByUid([...S.selected][0]);
    return row ? `${row.system}|${row.file}` : null;
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
  async function openRowMenu(row, event) {
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
    const archiveOwnedRoms = isArchive() ? [...S.selected].filter((uid) => {
      const mode = (rowByUid(uid) || {}).ownership?.rom?.mode;
      return mode === "internal" || mode === "mixed";
    }).length : 0;
    const ownedDeletePreview = isArchive() && !locked
      ? await api.archiveDeleteOwnedPreview([...S.selected]) : null;
    const canDeleteOwned = !!(ownedDeletePreview?.ok
      && ownedDeletePreview.data.eligible.length === count
      && !ownedDeletePreview.data.blocked.length);
    const star = document.querySelector(`.lrow[data-rom-uid="${row.romUid}"] .fav-btn, `
      + `.preview-card[data-rom-uid="${row.romUid}"] .fav-btn`);

    // 적용할 내용이 없으면 아예 고를 수 없게 미리 확인한다(사용자 결정) - 눌러서
    // "바뀔 게 없다"는 안내를 받는 것보다 흐리게 보이는 편이 직관적이다.
    // Archive에서도 연다 - 제목을 바꾸는 것은 순수 텍스트 계산이라 Archive 데이터만으로
    // 계산된다(적용은 Plan 없이 편집 층에 바로 쓴다). 예전엔 isArchive()만 보고 막았다.
    let titleAffixDisabled = locked;
    if (!titleAffixDisabled) {
      const preview = isArchive()
        ? await api.archiveTitleAffixPreview(null, [...S.selected])
        : await api.titleAffixPreview(S.activeId, [...S.selected], null);
      titleAffixDisabled = !preview.ok || !preview.data.items.some((i) => i.changed);
    }
    const hasImportSource = S.archiveConfigured || S.tabs.some((id) => id !== S.activeId);

    showContextMenu(menuPoint(event), single ? (row.title || row.file) : `${formatCount(count)}개 선택됨`,
      single ? row.file : null, [
        { label: row.favorite ? "즐겨찾기 해제" : "즐겨찾기에 추가", icon: "star",
          disabled: !single || !star || locked, onSelect: () => toggleFavorite(row, star) },
        { label: "RetroArch로 실행", icon: "play", hint: "더블클릭",
          disabled: !single || !!launchBlockReason(row), title: single ? launchBlockReason(row) : null,
          onSelect: () => launchGame(row) },
        "separator",
        { label: "이름 변경", icon: "edit", hint: "F2",
          disabled: locked || !single, onSelect: () => renameSelectedGame(row) },
        {label: "잘라내기", icon: "scissors", hint: "Ctrl+X",
          disabled: locked, onSelect: cutSelectedRows},
        { label: "게임 복사", icon: "copy", hint: "Ctrl+C", disabled: locked, onSelect: copySelectedRows },
        { label: "붙여넣기", icon: "upload", hint: "Ctrl+V", disabled: locked,
          title: "같은 System과 ROM 파일명에 붙여넣습니다. 이 행을 선택했다면 이 게임에 붙여넣습니다.",
          onSelect: () => pasteClipboard(single ? row : null) },
        { label: "채우기", icon: "upload", disabled: locked,
          title: "비어 있는 메타데이터와 없는 미디어만 채웁니다.",
          onSelect: () => pasteClipboard(single ? row : null, null, null, "patch") },
        { label: "교체하기", icon: "upload", disabled: locked,
          title: "메타데이터를 복사한 게임의 값으로 교체합니다.",
          onSelect: () => pasteClipboard(single ? row : null, null, null, "replace") },
        ...(S.lastPasteUndoId ? [{ label: "실행 취소",
          icon: "cornerUpLeft", hint: "Ctrl+Z", disabled: locked,
          onSelect: undoLastPaste }] : []),
        ...(S.plan?.redoOperationId ? [{label: "다시 실행", icon: "cornerUpRight", hint: "Ctrl+Y",
          disabled: locked, onSelect: redoLastOperation}] : []),
        {label: "작업 기록…", icon: "history", disabled: locked, onSelect: openOperationHistory},
        "separator",
        { label: single ? "게임 정보 스크랩…" : `게임 정보 스크랩… (${formatCount(count)}개)`,
          icon: "sparkles", disabled: locked,
          title: "선택한 게임을 순서대로 검토합니다.",
          onSelect: () => openScrapeContext([...S.selected]) },
        ...(!isArchive() ? [{ label: "다른 Collection·Archive에서 가져오기…", icon: "download",
          disabled: !single || !hasImportSource || locked,
          title: hasImportSource ? "열어 둔 Collection이나 Archive에서 출처를 고릅니다."
            : "다른 Collection을 열거나 Archive를 설정하세요.",
          onSelect: () => openImportSourceChooser(row) }] : []),
        { label: single ? "제목 앞·뒤 태그 적용…" : `제목 앞·뒤 태그 적용… (${formatCount(count)}개)`,
          icon: "tag", disabled: titleAffixDisabled,
          title: titleAffixDisabled && !isArchive() && !locked
            ? "지금 설정으로는 바뀔 제목이 없습니다. Settings > Metadata & Media에서 규칙을 확인하세요." : null,
          onSelect: () => openTitleAffixDialog({ romUids: [...S.selected],
            label: single ? (row.title || row.file) : `선택한 ${formatCount(count)}개` }) },
        { label: single ? "ROM 파일명 복사" : `ROM 파일명 ${formatCount(files.length)}개 복사`, icon: "copy",
          disabled: !files.length,
          onSelect: () => copyTextToClipboard(files.join("\n"),
            files.length > 1 ? `파일명 ${formatCount(files.length)}개를 복사했습니다.` : "파일명을 복사했습니다.") },
        "separator",
        // Archive 보관 ROM은 파일만 지울 수 있다. 외부 연결은 물리 파일을 건드리지 않고,
        // Identity 전체 삭제는 여전히 DB 기록만 제거한다.
        ...(isArchive()
          ? [
              { label: "보관 ROM 파일 삭제", icon: "gamepad", danger: true,
                disabled: locked || !archiveOwnedRoms,
                title: archiveOwnedRoms
                  ? "Archive ROM 디렉토리 안의 파일만 삭제합니다. 외부 원본 연결은 유지합니다."
                  : "선택한 항목에는 Archive가 보관하는 ROM 파일이 없습니다.",
                onSelect: deleteArchiveOwnedRoms },
              { label: "메타데이터 삭제", icon: "fileText", danger: true,
                disabled: locked || ![...S.selected].some((uid) => (rowByUid(uid) || {}).hasMetadata),
                title: "Archive의 현재 메타데이터 표시를 지웁니다. ROM·미디어·출처 Revision은 유지합니다.",
                onSelect: deleteArchiveMetadata },
              { label: "보관 게임·파일 삭제", icon: "trash", danger: true,
                disabled: !canDeleteOwned,
                title: canDeleteOwned
                  ? "Archive가 보관하는 ROM·미디어 파일과 이 게임의 Archive 기록을 삭제합니다."
                  : "외부 원본에 연결된 항목은 전체 삭제할 수 없습니다. Archive에서 지우기는 기록만 제거합니다.",
                onSelect: deleteArchiveOwnedGames },
              { label: "Archive 기록 제거", icon: "trash", hint: "Del", danger: true, disabled: locked,
               title: "실제 ROM/Media 파일은 지우지 않습니다 - Archive의 기록만 지웁니다.",
               onSelect: () => deleteSelection() },
            ]
          : [
              { label: "Game 삭제", icon: "trash", hint: "Del", danger: true, disabled: locked,
                children: [
                  { label: "Game 전체 삭제", danger: true, onSelect: () => deleteSelection(DELETE_ALL) },
                  { label: "메타데이터 삭제", danger: true, onSelect: () => deleteSelection(["metadata"]) },
                  { label: "미디어 삭제", danger: true, onSelect: () => deleteSelection(["media", "video"]) },
                ] },
            ]),
        ...rowFolderItems(row, single),
      ]);
  }

  /** System 우클릭의 "폴더 열기"(System 전체)를 게임 한 개 단위로도 지원한다
   * (실사용 피드백 §5). 여러 개를 고른 채로는 하나만 열 수 없으므로 안 보여준다.
   * 그 게임에 없는 종류(ROM/Metadata/Media)는 회색으로 - 눌러서 "없다"는 안내를
   * 받는 것보다 흐리게 보이는 편이 직관적이다(openSystemMenu와 같은 결정). */
  function rowFolderItems(row, single) {
    // Archive는 Collection의 adapter.layout 대신 보관/연결 경로를 사용한다.
    if (!single) return [];
    if (isArchive()) {
      return ["separator", { label: "폴더 열기", icon: "folderOpen", children: [
        { label: "ROM 디렉터리", onSelect: async () => {
          const r = await api.archiveRomFolder(row.romIdentityId || row.romUid);
          if (!r.ok) showToast(r.error, "error");
        } },
        { label: "메타데이터 디렉터리", onSelect: async () => {
          const r = await api.archiveSystemFolder(row.system, "metadata");
          if (!r.ok) showToast(r.error, "error");
        } },
        { label: "미디어 디렉터리", onSelect: async () => {
          const r = await api.archiveSystemFolder(row.system, "media");
          if (!r.ok) showToast(r.error, "error");
        } },
      ] }];
    }
    return ["separator", { label: "폴더 열기", icon: "folderOpen", children: [
      { label: "ROM 디렉터리", disabled: !row.present,
        title: row.present ? null : "ROM 파일이 없습니다.",
        onSelect: () => openRowFolder(row, "rom") },
      { label: "메타데이터 디렉터리", disabled: !row.hasMetadata,
        title: row.hasMetadata ? null : "Metadata가 없습니다.",
        onSelect: () => openRowFolder(row, "metadata") },
      { label: "미디어 디렉터리", disabled: !row.hasMedia,
        title: row.hasMedia ? null : "Media가 없습니다.",
        onSelect: () => openRowFolder(row, "media") },
    ] }];
  }

  async function openRowFolder(row, kind) {
    const r = await api.openRowFolder(S.activeId, row.romUid, kind);
    if (!r.ok) showToast(r.error, "error");
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
    const key = rowKey(row);
    scrollToIndex(index, key);
    S.selected = new Set([key]);
    S.selectAnchor = key;
    renderStatusBar();
    if (isCompare()) { openCompareDetail(row); return; }
    openDetail(row);
  }

  /** ↑/↓ = 다음/이전 게임 선택(스크롤이 아니다). Shift를 누르면 기준점부터 범위로 넓힌다. */
  async function moveFocus(delta, extend) {
    if (!S.total) return;
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
      if (r) S.selected.add(rowKey(r));
    }
    S.focused = rowKey(row);
    scrollToIndex(next, rowKey(row));
    updateSelectionVisual();
    renderStatusBar();
  }

  /** 영문/숫자 키 = 그 글자로 시작하는 다음 파일로. 같은 키를 다시 누르면 그다음으로,
   * 끝까지 가면 처음부터 다시 찾는다(탐색기와 같다). */
  async function jumpToLetter(key) {
    if (!S.total) return;
    const after = S.focused == null ? -1 : indexOfRow(S.focused);
    let index = -1;
    if (isArchive()) {
      const r = await api.archiveFindRowIndex(
        { ...currentQuery(), conflictsOnly: S.archiveConflictsOnly }, key, after);
      if (!r.ok) { showToast(r.error, "error"); return; }
      index = r.data;
    } else if (isCompare()) {
      // 비교 목록은 시작 시점 스냅샷이라 받아 둔 줄에서 찾는다.
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
    if (!S.total) return;
    if (isCompare()) {
      // 비교 결과 자체는 시작 시점의 스냅샷이라 다시 비교할 필요는 없지만, 지금 이
      // 필터에 맞는 **전체** 열쇠를 새로 물어야 한다(실사용 버그, 번복) - `S.rowCache`는
      // 가상 스크롤이 화면에 그린 조각만 채운 캐시라 "이미 메모리에 다 있다"는 예전
      // 가정이 틀렸다. 총 개수가 한 페이지(200개)를 넘으면 스크롤 안 한 뒤쪽이
      // 조용히 선택에서 빠져, "대부분 다르다고 나오는데 실제로는 몇 개만 붙여넣기
      // 된다"는 증상으로 나타났다.
      const r = await api.compareAllKeys({ ...currentQuery(), status: S.compareFilter });
      if (!r.ok) { showToast(r.error, "error"); return; }
      S.selected = new Set(r.data);
      updateSelectionVisual();
      renderStatusBar();
      showToast(`${formatCount(S.selected.size)}개를 선택했습니다.`);
      return;
    }
    if (isArchive()) {
      // Archive ID는 문자열이다. 화면과 같은 검색·System·즐겨찾기·충돌 필터를
      // archiveUids에 보내 첫 페이지만 선택되거나 숨긴 행까지 선택되지 않게 한다.
      const r = await api.archiveUids({ ...currentQuery(), conflictsOnly: S.archiveConflictsOnly });
      if (!r.ok) { showToast(r.error, "error"); return; }
      S.selected = new Set(r.data);
      updateSelectionVisual();
      renderStatusBar();
      showToast(`${formatCount(S.selected.size)}개를 선택했습니다.`);
      return;
    }
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
    // Archive의 별표는 **Archive 안에서만** 쓰는 표시다 - Collection은 Frontend
    // 파일(ES-DE의 `<favorite>`)에 직접 쓰지만 Archive엔 그럴 파일이 없다(§40).
    const archive = isArchive();
    const next = !row.favorite;
    // 눌린 것이 바로 보이게 먼저 바꾸고, 실패하면 되돌린다.
    row.favorite = next;
    button.textContent = next ? "★" : "☆";
    button.classList.toggle("on", next);

    const r = archive
      ? await api.archiveSetFavorite(row.romIdentityId, next)
      : await api.setFavorite(S.activeId, row.romUid, next);
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
    const key = rowKey(row);
    if (event.shiftKey) {
      const anchor = S.selectAnchor;
      const anchorIndex = anchor == null ? -1 : indexOfRow(anchor);
      if (anchorIndex >= 0) {
        const [lo, hi] = anchorIndex < index ? [anchorIndex, index] : [index, anchorIndex];
        if (!additive) S.selected.clear();
        for (let i = lo; i <= hi; i++) {
          const r = S.rowCache.get(i);
          if (r) S.selected.add(rowKey(r));
        }
      } else {
        S.selected = new Set([key]);
        S.selectAnchor = key;
      }
      S.focused = key;
      updateSelectionVisual();
      renderStatusBar();
      return;
    }
    if (additive) {
      if (S.selected.has(key)) S.selected.delete(key);
      else S.selected.add(key);
      S.selectAnchor = key;
      S.focused = key;
      updateSelectionVisual();
      renderStatusBar();
      return;
    }
    S.selected = new Set([key]);
    S.selectAnchor = key;
    renderStatusBar();
    openDetail(row);
  }

  /** 캐시에 들어온 행 중에서 그 romUid의 위치. Shift 범위 선택의 기준점 계산용. */
  function indexOfRow(key) {
    for (const [index, row] of S.rowCache.entries()) {
      if (row && rowKey(row) === key) return index;
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
  /** 변환 대상 고르기 -> (새 Collection이면 먼저 만들기) -> 미리보기 -> Plan.
   * 원본 Collection은 건드리지 않는다.
   *
   * **"다른 Frontend 형식으로 바꾼다"는 것이 이 앱에서는 "그 형식의 새 Collection을
   * 만든다"는 뜻이다**(사용자 결정) - Frontend별 폴더 구조(gamelist 위치, media 배치
   * 등)를 실제로 아는 것은 Collection 하나가 가리키는 폴더뿐이라, "이 Collection
   * 자체를 다른 형식으로"는 곧 "그 형식의 폴더를 새로 만들고 내용을 옮긴다"와 같다.
   * 예전엔 그 폴더(=Collection)를 미리 "+ Collection"으로 따로 만들어 둬야만
   * 골라졌는데, 그 준비 단계가 안 보여서 "왜 대상이 다른 Collection이냐"는 혼란이
   * 있었다 - 이제 이 창 안에서 바로 만든다. */
  async function openConvert(source) {
    const existing = S.collections.filter((c) => c.id !== source.id);
    const frontendsR = await api.frontends();
    const frontends = frontendsR.ok ? frontendsR.data : [{ id: "es-de", label: "ES-DE" }];

    let mode = "new";
    const modeSeg = h("div", { class: "seg" });
    const modeBtn = (value, label) => {
      const btn = h("button", { class: "seg-btn", "data-mode": value }, [label]);
      btn.addEventListener("click", () => { mode = value; sync(); });
      return btn;
    };
    modeSeg.appendChild(modeBtn("new", "새 Collection으로"));
    modeSeg.appendChild(modeBtn("existing", "이미 있는 Collection으로"));

    const frontendSel = h("select", { class: "field-input" },
      frontends.map((f) => h("option", { value: f.id }, [f.label])));
    const folderInput = h("input", { class: "field-input", placeholder: "폴더를 선택하세요" });
    const browseBtn = h("button", { class: "btn" }, [icon("folderOpen", IC.sm), h("span", {}, ["찾아보기"])]);
    browseBtn.addEventListener("click", async () => {
      const r = await api.pickFolder("변환해 넣을 폴더 선택");
      if (r.ok && r.data) folderInput.value = r.data;
    });
    const newBlock = h("div", { class: "convert-new-block" }, [
      h("div", { class: "field-label" }, ["Frontend"]), frontendSel,
      h("div", { class: "field-label" }, ["폴더"]),
      h("div", { class: "field-row" }, [folderInput, browseBtn]),
      h("div", { class: "modal-hint" }, ["비어 있는(또는 아직 없는) 폴더를 고르세요 - 그 자리에 새 Collection을 만듭니다."]),
    ]);

    const existingSel = h("select", { class: "field-input" },
      existing.map((c) => h("option", { value: c.id }, [`${c.name} (${c.frontendLabel})`])));
    const existingBlock = h("div", { class: "convert-existing-block" }, [
      h("div", { class: "field-label" }, ["대상 Collection"]), existingSel,
    ]);
    if (!existing.length) {
      existingBlock.appendChild(h("div", { class: "modal-hint" }, ["변환해 넣을 다른 Collection이 아직 없습니다."]));
    }

    function sync() {
      modeSeg.querySelectorAll(".seg-btn").forEach((btn) =>
        btn.classList.toggle("on", btn.dataset.mode === mode));
      newBlock.hidden = mode !== "new";
      existingBlock.hidden = mode !== "existing";
    }
    sync();

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" }, [`${source.name}의 내용을 다른 Frontend 형식으로 변환합니다.`]),
      modeSeg,
      newBlock,
      existingBlock,
      h("div", { class: "modal-hint" },
        ["원본은 그대로 둡니다. 변환할 항목을 확인한 뒤 대상에 적용합니다."]),
    ]);

    showModal("Convert", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary", onClick: async () => {
        if (mode === "existing") {
          if (!existingSel.value) { showToast("대상 Collection을 고르세요.", "warning"); return; }
          const targetId = existingSel.value;
          closeModal();
          showConvertPreview(source.id, targetId);
          return;
        }
        const folder = folderInput.value.trim();
        if (!folder) { showToast("폴더를 고르세요.", "warning"); return; }
        const label = (frontends.find((f) => f.id === frontendSel.value) || {}).label || frontendSel.value;
        const created = await api.createCollection(defaultCollectionName(label), frontendSel.value, folder);
        if (!created.ok) { showToast(created.error, "error"); return; }
        await loadCollections();
        closeModal();
        showConvertPreview(source.id, created.data.id);
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
        await openTab(targetId);
        await acceptOperationPreview(result.data);
      } }, ["변환하기"]),
    ]);
  }

  // ------------------------------------------------------------------
  // Compare Mode (스펙 §54-59)
  // ------------------------------------------------------------------
  async function runCompare(baseId, otherId) {
    // **고른 것은 그대로 둔다**(사용자 피드백 - Swap/새로고침 뒤 선택이 사라졌다).
    // 행의 열쇠는 (system|file)이라 좌우를 바꿔도 같은 행을 가리킨다.
    const keptSelection = isCompare() ? new Set(S.selected) : null;
    const keptFocus = isCompare() ? S.focused : null;
    const keptFilter = isCompare() ? S.compareFilter : "all";
    const r = await api.startCompare(baseId, otherId);
    if (!r.ok) { showToast(r.error, "error"); return; }
    S.compare = r.data;
    S.compareBase = null;
    S.compareFilter = keptFilter;
    // Compare에 들어오면 항상 미리보기부터 켠다(사용자 결정, 메뉴 정리 §8) - 두 쪽을
    // 나란히 보는 것이 Compare의 핵심이라, 이전 Collection에서 꺼 둔 채로 남아 있으면
    // 안 된다.
    S.previewOn = true;
    saveUiState();
    resetList();
    renderAll();
    await reloadList();
    if (keptSelection && keptSelection.size) {
      // 다시 비교한 결과에 남아 있는 행만 되살린다 - 사라진 행까지 고른 채로 두면
      // 그 다음 동작이 없는 항목을 대상으로 삼는다.
      const alive = new Set([...S.rowCache.values()].filter(Boolean).map((row) => row.key));
      S.selected = new Set([...keptSelection].filter((key) => alive.has(key)));
      S.focused = alive.has(keptFocus) ? keptFocus : null;
      updateSelectionVisual();
      renderStatusBar();
      renderFilterBar();
    }
  }

  /** 상단 `<` `>` - 고른 행들의 메타데이터+미디어를 반대쪽 Plan에 덮어쓰기로 올린다. */
  /** 고른 두 행이 **서로 다른 쪽에만** 있는가. 그렇다면 사람이 직접 이을 수 있다.
   *
   * 자동 짝짓기는 이름이 닮았을 때만 잇는다 - `Final Fantasy 7.zip`과 `ff7.rom`은 같은 게임인데도
   * 각각 "한쪽에만 있음"으로 남는다. 그때 둘을 골라 잇는 길이다. **Match 결과를 바꾸는 것이 아니라**
   * 이번 전송의 대상을 지목하는 것이다. */
  function manualLinkPair() {
    if (S.selected.size !== 2) return null;
    const rows = [...S.rowCache.values()].filter((r) => r && S.selected.has(r.key));
    if (rows.length !== 2) return null;
    const a = rows.find((r) => r.status === "only_a");
    const b = rows.find((r) => r.status === "only_b");
    return a && b ? { a, b } : null;
  }

  function manualLinkButton() {
    const pair = manualLinkPair();
    const btn = h("button", {
      class: "cmp-link", disabled: !pair,
      title: pair
        ? `«${pair.a.file}»와 «${pair.b.file}»를 직접 잉습니다`
        : "한쪽에만 있는 항목을 좌우에서 하나씩, 둘만 고르면 직접 이을 수 있습니다",
    }, [icon("arrowLeftRight", IC.sm)]);
    if (pair) btn.onclick = () => openManualLinkDialog(pair);
    return btn;
  }

  /** 어느 쪽을 원본으로 삼을지 사람이 정한다 - 방향을 짐작해서 남의 메타데이터를 덮으면 안 된다. */
  function openManualLinkDialog(pair) {
    const send = async (source, target) => {
      closeModal();
      await runCompareOperation({sourceKey: source.key, targetKey: target.key, mode: "replace"});
    };
    const choice = (source, target) => {
      const btn = h("button", { class: "btn picker-row" }, [
        h("div", { class: "picker-main" }, [
          h("div", { class: "picker-title truncate" }, [`${source.file} → ${target.file}`]),
          h("div", { class: "picker-sub truncate" },
            [`«${source.file}»의 내용으로 «${target.file}»를 채웁니다`]),
        ]),
      ]);
      btn.addEventListener("click", () => send(source, target));
      return btn;
    };
    showModal("직접 잉기", h("div", { class: "modal-body" }, [
      h("div", { class: "modal-text" },
        ["고른 두 항목을 같은 게임으로 보고 메타데이터와 미디어를 보냅니다. 어느 쪽을 원본으로 삼을까요?"]),
      h("div", { class: "modal-hint" },
        ["ROM 파일은 옮기지 않습니다. 이 작업은 Match 결과를 바꾸지 않고, 이번 전송의 대상만 지정합니다."]),
      h("div", { class: "picker-list" }, [choice(pair.a, pair.b), choice(pair.b, pair.a)]),
    ]), [h("button", { class: "btn", onClick: closeModal }, ["취소"])]);
  }

  async function compareSendSelected(direction) {
    if (!S.selected.size) { showToast("보낼 항목을 먼저 고르세요.", "warning"); return; }
    await runCompareOperation({keys: [...S.selected], direction, metadataOnly: true,
      mediaTypes: [...S.compareMediaSel]});
  }

  async function exitCompare() {
    await api.exitCompare();
    S.compare = null;
    S.compareBase = null;
    resetList();
    renderAll();
    await reloadList();
  }

  /** 행을 고르면 좌/우 Detail이 각자 그 항목을 보여준다(§57). 다른 값은 노란색으로 표시한다. */
  async function openCompareDetail(row) {
    S.focused = row.key;
    renderListWindow();
    const r = await api.compareDetail(row.key);
    if (!r.ok) { showToast(r.error, "error"); return; }
    S.detailState = { compare: r.data, tab: "metadata" };
    renderDetailPanel();
  }

  //: Compare Detail에서 보여 주는 Metadata 카드(한 줄에 둘). Title/Description은 따로 크게 놓는다.
  const CMP_FIELD_CARDS = [
    ["Genre", "genre"], ["Developer", "developer"], ["Publisher", "publisher"],
    ["Release", "releasedate"], ["Region", "region"], ["Players", "players"], ["Rating", "rating"],
  ];
  //: Media 탭의 줄 구성(사용자 결정). 비율은 CSS가 고정한다.
  const CMP_MEDIA_ROWS = [
    { cls: "cover", items: [["Cover", "Covers"]] },
    { cls: "shot", items: [["Screenshot", "Screenshots"]] },
    { cls: "trio", items: [["Marquee", "Marquees"], ["MixImage", "Miximages"], ["3DBox", "3DBoxes"]] },
  ];
  //: 위 줄들에 안 나오는 종류는 있고 없고만 칩으로 알린다.
  const CMP_MEDIA_CHIPS = [
    ["TitleScreen", "titlescreens"], ["BackCover", "backcovers"], ["PhysicalMedia", "physicalmedia"],
    ["Wheel", "wheel"], ["FanArt", "fanart"], ["Video", "videos"], ["Manual", "manuals"],
  ];

  /** 그림 한 장. 다르면(`changed`) 노란 테두리다. 없으면 빈 칸으로 자리를 지킨다. */
  function cmpImageTile(side, label, key, changed, extraClass) {
    const type = key.toLowerCase();
    const has = !!side && (side.mediaTypes || []).includes(type);
    const tile = h("div", {
      class: `cmp-tile ${extraClass || ""}` + (has ? "" : " empty") + (changed ? " changed" : "")
        + (S.compareMediaSel.has(type) ? " picked" : ""),
      title: label + (has ? "" : " 없음"),
    });
    // 체크하면 상단 < >가 이 미디어 종류만 보낸다(여러 종류 선택 가능, 양쪽 Detail에 함께 표시된다).
    const pick = h("button", { class: "cmp-pick" + (S.compareMediaSel.has(type) ? " on" : ""),
      title: "이 미디어만 보내기 (여러 개 선택 가능)", "aria-pressed": S.compareMediaSel.has(type) ? "true" : "false" },
      [S.compareMediaSel.has(type) ? "✓" : ""]);
    pick.addEventListener("click", (e) => {
      e.stopPropagation();
      if (S.compareMediaSel.has(type)) S.compareMediaSel.delete(type); else S.compareMediaSel.add(type);
      renderDetailPanel();
      renderFilterBar();
    });
    tile.appendChild(pick);
    tile.appendChild(h("div", { class: "cmp-tile-label" }, [label]));
    const box = h("div", { class: "cmp-tile-box" });
    if (has) {
      const img = h("img", { alt: label });
      box.appendChild(img);
      api.getMediaImage(side.collectionId, side.romUid, key, true).then((r) => {
        if (r.ok && r.data) img.src = r.data;
      });
      tile.classList.add("clickable");
      tile.addEventListener("click", () => openMediaLightbox(img, label));
    } else {
      box.appendChild(icon("imageOff", IC.lg));
    }
    tile.appendChild(box);
    return tile;
  }

  const cmpAbsent = () => h("div", { class: "cmp-absent-note" }, ["이 쪽에는 ROM이 없습니다."]);

  function cmpMetadataTab(body, d, side) {
    if (!side) { body.appendChild(cmpAbsent()); return; }
    const changed = new Set(d.changedFields || []);
    const mediaChanged = new Set(d.mediaChanged || []);
    const fields = side.fields || {};
    const mark = (key) => (changed.has(key) ? " changed" : "");
    body.appendChild(h("div", { class: "cmp-block" + mark("name") }, [
      h("div", { class: "cmp-label" }, ["Title"]),
      h("div", { class: "cmp-title-value" }, [fields.name || side.title || "-"]),
    ]));
    // Description은 12줄까지만 보이고 넘으면 말줄임이다(사용자 결정) - 길이가 다른 두 쪽의
    // 아래 그림이 서로 어긋나지 않게 줄 수를 고정한다.
    body.appendChild(h("div", { class: "cmp-block" + mark("desc") }, [
      h("div", { class: "cmp-label" }, ["Description"]),
      h("div", { class: "cmp-desc" }, [fields.desc || "-"]),
    ]));
    const cards = h("div", { class: "cmp-cards" });
    CMP_FIELD_CARDS.forEach(([label, key]) => {
      cards.appendChild(h("div", { class: "cmp-card" + mark(key) }, [
        h("div", { class: "cmp-label" }, [label]),
        h("div", { class: "cmp-card-value truncate", title: fields[key] || "" }, [fields[key] || "-"]),
      ]));
    });
    body.appendChild(cards);
    // 아래에 Cover(세로)와 Screenshot(가로)을 나란히 - 두 쪽을 같은 자리에서 비교한다.
    body.appendChild(h("div", { class: "cmp-media-pair" }, [
      cmpImageTile(side, "Cover", "Covers", mediaChanged.has("covers"), "portrait"),
      cmpImageTile(side, "Screenshot", "Screenshots", mediaChanged.has("screenshots"), "landscape"),
    ]));
  }

  function cmpMediaTab(body, d, side) {
    if (!side) { body.appendChild(cmpAbsent()); return; }
    const changed = new Set(d.mediaChanged || []);
    CMP_MEDIA_ROWS.forEach((row) => {
      const line = h("div", { class: `cmp-media-row ${row.cls}` });
      row.items.forEach(([label, key]) =>
        line.appendChild(cmpImageTile(side, label, key, changed.has(key.toLowerCase()), row.cls)));
      body.appendChild(line);
    });
    const chips = h("div", { class: "cmp-chips" });
    CMP_MEDIA_CHIPS.forEach(([label, type]) => {
      const has = (side.mediaTypes || []).includes(type);
      chips.appendChild(h("span", {
        class: "cmp-chip" + (has ? " on" : "") + (changed.has(type) ? " changed" : ""),
      }, [label]));
    });
    body.appendChild(chips);
  }

  function cmpRomTab(body, d, side) {
    if (!side) { body.appendChild(cmpAbsent()); return; }
    const other = side === d.left ? d.right : d.left;
    const line = (label, value, differs) => h("div", { class: "cmp-block" + (differs ? " changed" : "") }, [
      h("div", { class: "cmp-label" }, [label]),
      h("div", { class: "cmp-rom-value" }, [value || "-"]),
    ]);
    body.appendChild(line("File", side.filename, !!other && other.filename !== side.filename));
    body.appendChild(line("Size", side.size ? formatBytes(side.size) : "-", !!other && other.size !== side.size));
    body.appendChild(line("ROM", side.present ? "있음" : "ROM 파일 없음 (메타데이터만 있음)",
                          !!other && !!other.present !== !!side.present));
    body.appendChild(line("Path", side.romPath, false));
  }

  /** 한쪽 Detail(좌 또는 우). 탭은 양쪽이 함께 바뀐다(`S.compareTab`). */
  function renderCompareSide(panel, d, side, name, withClose) {
    const inner = h("div", {
      id: withClose ? "detail-panel-inner" : "compare-left-inner", class: "cmp-side-inner",
    });
    panel.appendChild(inner);
    const header = h("div", { class: "detail-header" }, [
      h("div", { style: { minWidth: "0", flex: "1" } }, [
        h("div", { class: "detail-eyebrow truncate" }, [name]),
        h("div", { class: "detail-filename truncate", title: side ? side.filename : "" },
          [side ? side.filename : "(없음)"]),
        h("div", { class: "detail-system" }, [systemIcon(d.system, 13), String(d.system).toUpperCase()]),
      ]),
    ]);
    if (withClose) {
      const close = h("button", { class: "icon-btn", title: "닫기 (Esc)" }, [icon("x", IC.md)]);
      close.addEventListener("click", closeDetail);
      header.appendChild(close);
    }
    inner.appendChild(header);

    const tabs = h("div", { class: "detail-tabs" });
    [["metadata", "Metadata"], ["media", "Media"], ["rom", "ROM"]].forEach(([key, label]) => {
      const tab = h("button", { class: "detail-tab" + (S.compareTab === key ? " active" : "") }, [label]);
      tab.addEventListener("click", () => { S.compareTab = key; renderDetailPanel(); });
      tabs.appendChild(tab);
    });
    inner.appendChild(tabs);

    const body = h("div", { class: "detail-body cmp-side-body tab-" + S.compareTab });
    if (S.compareTab === "media") cmpMediaTab(body, d, side);
    else if (S.compareTab === "rom") cmpRomTab(body, d, side);
    else cmpMetadataTab(body, d, side);
    inner.appendChild(body);
  }

  function renderCompareDetail(panel) {
    const d = S.detailState.compare;
    renderCompareSide(panel, d, d.right, d.otherName, true);
    const left = $("compare-left");
    if (left) { clear(left); renderCompareSide(left, d, d.left, d.baseName, false); }
  }

  // ------------------------------------------------------------------
  // Match (스펙 §45-49)
  // ------------------------------------------------------------------
  const TIER_LABEL = { exact: "정확", normalized: "이름 일치", metadata: "메타데이터",
                       heuristic: "유사", manual: "수동 연결" };

  /** 버전 하나의 Cover/Screenshot 미리보기 - 문장(크기)만으로는 "진짜 같은 그림인지"를
   * 눈으로 확인할 수 없었다(실사용 피드백 - work-mtp-0917에 있던 미리보기를 다시 가져옴).
   * 그 버전에 실린 여러 출처 중 첫 번째 것을 대표로 보여준다. */
  function archiveVersionTile(romIdentityId, sourceId, label, key, recordId) {
    const tile = h("div", { class: "cmp-tile ver-tile" });
    tile.appendChild(h("div", { class: "cmp-tile-label" }, [label]));
    const box = h("div", { class: "cmp-tile-box" });
    if (sourceId) {
      const img = h("img", { alt: label });
      box.appendChild(img);
      api.getArchiveVersionMediaImage(romIdentityId, sourceId, label, true, recordId).then((r) => {
        if (r.ok && r.data) img.src = r.data; else tile.classList.add("empty");
      });
    } else {
      tile.classList.add("empty");
      box.appendChild(icon("imageOff", IC.sm));
    }
    tile.appendChild(box);
    return tile;
  }

  /** Archive의 버전 목록. 하나를 고르면 그 버전이 쓰이고 `[n]`이 사라진다.
   *
   * 판단에 필요한 것(파일명/Title/Description/Cover/Screenshot)을 한 화면에 보여준다 -
   * 파일명과 점수만으로는 어느 쪽이 맞는지 알 수 없다. */
  async function openVersionDialog(row) {
    const r = await api.archiveVersions(row.romIdentityId || row.romUid);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const versions = r.data.versions || [];
    const rid = row.romIdentityId || row.romUid;
    const list = h("div", { class: "match-list ver-list" });
    const mediaText = (v, key) => (v.media[key] ? formatBytes(v.media[key]) : "—");
    versions.forEach((v, i) => {
      const option = h("div", { class: "match-option ver-option scrape-candidate" });
      const versionSource = (v.sources || [])[0] || null;
      const cover = h("div", { class: "scrape-thumb empty revision-cover" }, [icon("imageOff", IC.md)]);
      if ((v.media || {}).covers && versionSource) {
        api.getArchiveVersionMediaImage(rid, versionSource, "Covers", true,
          (v.recordIds || [])[0]).then((result) => {
          if (result.ok && result.data && cover.isConnected) {
            clear(cover);
            cover.classList.remove("empty");
            cover.appendChild(h("img", { src: result.data, alt: "Cover" }));
          }
        });
      }
      const choose = h("button", { class: "btn compact revision-pick" }, ["선택"]);
      choose.addEventListener("click", async () => {
        closeModal();
        const chosen = await api.archiveChooseVersion(row.romIdentityId || row.romUid,
                                                      v.recordIds[0]);
        if (!chosen.ok) { showToast(chosen.error, "error"); return; }
        delete S.matchCounts[row.romUid];
        await refreshArchiveRows([row.romIdentityId || row.romUid]);
        showToast(`버전 ${i + 1}을 선택했습니다.`);
      });
      const year = String(v.fields.releasedate || "").match(/\d{4}/)?.[0] || "";
      option.appendChild(h("div", { class: "scrape-candidate-head" }, [cover,
        h("div", { class: "scrape-candidate-main" }, [
          h("div", { class: "scrape-candidate-top" }, [
            h("span", { class: "scrape-system-icon" }, [systemIcon(row.system, 16)]),
            h("span", { class: "scrape-candidate-title", title: v.fields.name || "" },
              [v.fields.name || row.file]),
          ]),
          h("div", { class: "scrape-candidate-desc" },
            [(v.fields.desc || "설명 없음").replace(/\s+/g, " ")]),
          h("div", { class: "scrape-candidate-facts" },
            [[v.fields.developer, v.fields.genre, v.fields.publisher].filter(Boolean).join(" · ")
              || "추가 정보 없음"]),
          h("div", { class: "revision-foot" }, [
            h("span", { class: "revision-source truncate" },
              [(v.sourceNames || v.sources || []).join(", ")]),
            h("span", { class: "revision-when" }, [revisionWhen(v.updatedAt)]),
          ]),
          h("div", { class: "scrape-candidate-bottom" }, [
            h("span", { class: "scrape-candidate-year" }, [year]),
            h("span", { class: "revision-media-summary" },
              [`Cover ${mediaText(v, "covers")} · Screenshot ${mediaText(v, "screenshots")}`]),
            choose,
          ]),
        ]),
      ]));
      list.appendChild(option);
    });
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-hint" },
        ["Title / Description / Cover / Screenshot이 다른 버전입니다. 쓸 버전을 고르세요."]),
      list,
    ]);
    showModal("서로 다른 버전", body, [h("button", { class: "btn", onClick: closeModal }, ["닫기"])])
      .classList.add("ver-dialog-card");
  }

  /** 가져올 곳을 먼저 고른다. Archive를 사용하지 않는 경우에도 Collection 간 이동이 가능하다. */
  function openImportSourceChooser(row = null) {
    const targetId = S.activeId;
    const sources = S.tabs.filter((id) => id !== targetId)
      .map((id) => S.collections.find((c) => c.id === id)).filter(Boolean);
    const list = h("div", { class: "picker-list import-source-list" });
    sources.forEach((collection) => {
      const choice = h("button", { class: "picker-row" }, [
        icon("gamepad", IC.md),
        h("div", { class: "picker-main" }, [
          h("div", { class: "picker-name" }, [collection.name]),
          h("div", { class: "picker-sub truncate" }, [collection.rootPath]),
        ]),
      ]);
      choice.addEventListener("click", () => {
        closeModal();
        if (row) openMatchDialog(row, true, collection.id);
        else importFromCollection(collection.id, targetId);
      });
      list.appendChild(choice);
    });
    if (S.archiveConfigured) {
      const choice = h("button", { class: "picker-row" }, [
        icon("database", IC.md),
        h("div", { class: "picker-main" }, [
          h("div", { class: "picker-name" }, ["Archive"]),
          h("div", { class: "picker-sub" },
            ["가져올 메타데이터와 미디어 확인"]),
        ]),
      ]);
      choice.addEventListener("click", () => {
        closeModal();
        if (row) openMatchDialog(row, true);
        else importFromArchive();
      });
      list.appendChild(choice);
    }
    if (!sources.length && !S.archiveConfigured) {
      list.appendChild(h("div", { class: "empty-msg" },
        ["다른 Collection을 탭으로 열거나 Archive를 설정하세요."]));
    }
    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "modal-hint" }, [row
        ? `${row.file}에 가져올 출처를 고르세요.`
        : "현재 범위에 가져올 출처를 고르세요."]), list,
    ]);
    showModal("가져오기", body, [h("button", { class: "btn", onClick: closeModal }, ["취소"])]);
  }

  /** 후보 목록. 출처를 고른 뒤에도 후보를 직접 확인한다. */
  async function openMatchDialog(row, importOnSelect = false, sourceCollectionId = null) {
    const r = sourceCollectionId
      ? await api.collectionImportCandidates(S.activeId, row.romUid, sourceCollectionId)
      : await api.matchCandidates(S.activeId, row.romUid);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const data = r.data;

    let chosen = sourceCollectionId ? null : data.linkedRomIdentityId || null;
    const list = h("div", { class: "match-list" });

    if (!data.candidates.length) {
      list.appendChild(h("div", { class: "empty-msg" }, ["후보를 찾지 못했습니다."]));
    }
    data.candidates.forEach((candidate) => {
      const option = h("button", {
        class: "match-option scrape-candidate" + (candidate.romIdentityId === chosen ? " chosen" : ""),
      });
      const fields = candidate.fields || {};
      const cover = h("div", { class: "scrape-thumb empty" }, [icon("imageOff", IC.md)]);
      if ((candidate.mediaTypes || []).includes("covers")) {
        const preview = sourceCollectionId
          ? api.getMediaImage(sourceCollectionId, candidate.romUid, "Covers", true)
          : api.getArchiveMediaImage(candidate.romIdentityId, "Covers", true);
        preview.then((result) => {
          if (result.ok && result.data && cover.isConnected) {
            clear(cover);
            cover.classList.remove("empty");
            cover.appendChild(h("img", { src: result.data, alt: fields.name || candidate.title }));
          }
        });
      }
      const fact = (label, value) => h("span", { class: "scrape-fact",
        title: `${label}: ${value || "없음"}` }, [String(value || "")]);
      const year = String(fields.releasedate || "").match(/\d{4}/)?.[0] || "";
      const why = (candidate.evidence || []).join(" · ");
      option.appendChild(h("div", { class: "scrape-candidate-head" }, [cover,
        h("div", { class: "scrape-candidate-main" }, [
          h("div", { class: "scrape-candidate-top" }, [
            h("span", { class: "scrape-system-icon" }, [systemIcon(candidate.system || row.system, 16)]),
            h("span", { class: "scrape-candidate-title", title: fields.name || candidate.title || "" },
              [fields.name || candidate.title || candidate.filename]),
          ]),
          h("div", { class: "scrape-candidate-desc", title: fields.desc || "" },
            [String(fields.desc || "설명 없음").replace(/\s+/g, " ")]),
          h("div", { class: "scrape-candidate-facts" }, [
            h("div", { class: "scrape-fact-row" }, [fact("개발", fields.developer),
              fact("배급", fields.publisher)]),
            h("div", { class: "scrape-fact-row" }, [fact("장르", fields.genre),
              fact("점수", `${Math.round(candidate.score)}%`)]),
            h("div", { class: "scrape-fact-row" }, [fact("연도", year),
              fact("매칭 근거", why || TIER_LABEL[candidate.tier] || candidate.tier)]),
          ]),
        ]),
      ]));
      option.appendChild(h("div", { class: "match-option-sub truncate",
        title: `${candidate.filename}${why ? ` · ${why}` : ""}` }, [candidate.filename]));
      option.addEventListener("click", () => {
        chosen = candidate.romIdentityId;
        list.querySelectorAll(".match-option").forEach((el, i) => {
          const isChosen = data.candidates[i].romIdentityId === chosen;
          el.classList.toggle("chosen", isChosen);
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
      if (sourceCollectionId) {
        await runImmediateAction("import", { sourceId: sourceCollectionId,
          romUids: [chosen], targetRomUid: row.romUid, mode: currentPasteMode() });
        return;
      }
      if (importOnSelect) {
        await runImmediateAction("archive-import", { ids: [chosen],
          targetRomUid: row.romUid, mode: currentPasteMode() });
        return;
      }
      const applied = await api.applyMatch(S.activeId, row.romUid, chosen);
      if (!applied.ok) { showToast(applied.error, "error"); return; }
      delete S.matchCounts[row.romUid];
      renderListWindow();
      showToast("Match를 확정했습니다. Archive에서 값을 가져오려면 Archive → Collection을 실행하세요.");
    });

    const actions = [h("button", { class: "btn", onClick: closeModal }, ["Cancel"])];
    if (data.linkedRomIdentityId && !sourceCollectionId) {
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
    applyBtn.textContent = importOnSelect ? "가져오기" : "Match 확정";
    showModal(sourceCollectionId ? "Collection에서 가져오기" : "Archive에서 가져오기", body, actions);
  }

  // ------------------------------------------------------------------
  // 우측 상세 패널 (이전 프로젝트 구성을 유지 - 스펙 §34~36)
  // ------------------------------------------------------------------
  const fieldRefs = {};

  /** Archive 상세 응답을 화면이 쓰는 모양으로 바꾼다. **한 곳에서만 만든다** -
   * 예전에는 Revision을 고른 뒤 여기와 다른 모양으로 다시 만들어서, 파일명이 비고
   * Media 탭이 깨졌다(`file`/`media` 키가 서로 달랐다). */
  function archiveDetailState(d, tab) {
    return {
      archive: true, romUid: d.romIdentityId, romIdentityId: d.romIdentityId,
      system: d.system, file: d.filename, fields: d.fields, size: d.size,
      present: !!d.present, sha256: d.sha256, sources: d.sources, favorite: !!d.favorite,
      romSources: d.romSources || [],
      ownership: d.ownership || { mode: "none", rom: { mode: "none" },
        media: { mode: "none", types: {} }, metadata: { mode: "internal" } },
      // Revision 탭(renderSourcesTab)이 읽는 값들 - 예전엔 빠뜨려서 목록엔 [n] 충돌
      // 뱃지가 붙는데 열어 보면 늘 "수집된 Revision이 없습니다"였다.
      versions: d.versions, preferredRecordId: d.preferredRecordId,
      media: (d.media || []).reduce((acc, m) => {
        acc[MEDIA_LABEL[m.media_type] || m.media_type] = "pending"; return acc;
      }, {}),
      tab: tab || "metadata", draft: null,
    };
  }

  /** Archive에서 무언가 바꾼 뒤 **그 줄만** 다시 읽어 목록에 반영한다.
   *
   * Effective State(Preferred/편집/별표)가 바뀌면 상세만이 아니라 목록도 같은 시점에
   * 바뀌어야 한다 - 예전에는 renderListWindow()로 캐시를 다시 그리기만 해서, Revision을
   * 골라도 상세만 바뀌고 Gamelist의 제목/설명은 옛 값 그대로였다(실사용 P0).
   * 줄을 손으로 조립하지 않고 백엔드의 목록 코드를 그대로 다시 부른다 - 목록과 갱신이
   * 서로 다른 규칙으로 값을 만들면 또 어긋난다. */
  async function refreshArchiveRows(romIdentityIds) {
    const ids = (romIdentityIds || []).filter(Boolean);
    if (!ids.length || !isArchive()) return;
    const r = await api.archiveRows({ romIdentityIds: ids, limit: ids.length });
    if (!r.ok) return;
    const fresh = new Map((r.data.rows || []).map((row) => [row.romIdentityId, row]));
    for (const [index, row] of S.rowCache.entries()) {
      const next = row && fresh.get(row.romIdentityId);
      if (next) S.rowCache.set(index, next);
    }
    renderListWindow();
  }

  let detailRequestToken = 0;
  async function openDetail(row) {
    const requestToken = ++detailRequestToken;
    stopMediaVideo();
    S.focused = row.romUid;
    updateSelectionVisual();
    // 미리보기를 꺼 둔 상태에서는 고르기만 하고 패널을 열지 않는다(탐색기와 같다).
    if (!S.previewOn) return;
    const tab = (S.detailState && S.detailState.tab) || "metadata";

    // **늦게 온 응답은 버린다.** 고른 줄은 위에서 이미 S.focused에 적었으니, 응답이
    // 돌아왔을 때 그 값이 아니면 그 사이 사용자가 다른 줄로 옮겨 간 것이다. 이 검사가
    // 없으면 A -> B를 빠르게 고를 때 느린 A의 응답이 나중에 도착해 B의 상세를 덮어썼고,
    // 목록은 B를 강조하는데 패널은 A를 보여줬다. 더 나쁜 것은 S.detailState.romUid가
    // A로 남아, 사용자가 B를 고친다고 믿고 누른 저장이 A에 들어간 것이다.
    const collectionId = S.activeId;
    const stale = () => requestToken !== detailRequestToken
      || S.focused !== row.romUid || S.activeId !== collectionId;

    if (isArchive()) {
      const r = await api.archiveDetail(row.romIdentityId);
      if (stale()) return;
      if (!r.ok || !r.data) { showToast(r.error || "항목을 찾을 수 없습니다.", "error"); return; }
      S.detailState = archiveDetailState(r.data, tab);
      renderDetailPanel();
      renderStatusBar();
      return;
    }

    const r = await api.getRow(collectionId, row.romUid);
    if (stale()) return;
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
    const state = S.detailState;
    if (!state) return;
    state.draft = state.draft || {};
    Object.keys(fieldRefs).forEach((k) => {
      const input = fieldRefs[k];
      if (!input) return;
      const baseline = String((state.fields || {})[k] ?? "");
      const value = String(input.value ?? "");
      // Preserve ABSENT when an unrelated field changes. A blank value is
      // CLEARED only when the user actually erased a populated field.
      if (value === baseline) delete state.draft[k];
      else state.draft[k] = value;
    });
  }

  function scraperSettingsEditor() {
    const wrap = h("div", { class: "stg-scraper" }, [h("div", { class: "stg-info" }, ["설정을 불러오는 중…"])]);
    const draw = async () => {
      const result = await api.scraperSettings();
      clear(wrap);
      if (!result.ok) { wrap.appendChild(h("div", { class: "stg-info" }, [result.error])); return; }
      const cfg = result.data;
      wrap.appendChild(h("div", { class: "stg-info" }, [
        cfg.devIdSet && cfg.devPasswordSet
          ? `ScreenScraper 개발자 정보 설정됨 · 사용자 ${cfg.userId || "미로그인"}`
          : "ScreenScraper 개발자 정보가 필요합니다.",
      ]));
      const status = h("div", { class: "stg-info" }, ["연결 상태를 확인하지 않았습니다."]);
      const progressHost = h("div", { class: "stg-progress" });
      const configure = h("button", { class: "btn", onClick: () => openScraperSetup(
        () => openSettings("scraper")) }, ["연결 설정…"]);
      const test = h("button", { class: "btn primary", disabled: !(cfg.devIdSet && cfg.devPasswordSet),
        onClick: async () => {
          test.disabled = true;
          const started = await api.startScraperAccountStatus();
          if (!started.ok) { status.textContent = started.error; test.disabled = false; return; }
          const checked = await pollJob(started.data.jobId, "ScreenScraper 연결 확인", progressHost);
          test.disabled = false;
          if (!checked.ok) { status.textContent = checked.error; return; }
          status.textContent = `${scrapeQuotaText(checked.data)} · 동시 요청 ${checked.data.maxThreads || "확인 불가"}`;
        } }, ["연결 테스트"]);
      wrap.appendChild(h("div", { class: "stg-inline-actions" }, [configure, test]));
      wrap.appendChild(progressHost);
      wrap.appendChild(status);
      const hash = h("input", { type: "checkbox" });
      hash.checked = cfg.useHashes !== false;
      hash.addEventListener("change", () => api.saveScraperSettings({ useHashes: hash.checked }));
      wrap.appendChild(h("div", { class: "stg-row" }, [
        h("div", { class: "stg-label" }, [
          h("div", { class: "stg-name" }, ["ROM 해시로 먼저 찾기"]),
          h("div", { class: "stg-help" }, ["작은 ROM과 단일 파일 ZIP에 우선 적용합니다. 대용량 ROM은 파일명으로 검색합니다."]),
        ]),
        h("label", { class: "stg-switch" }, [hash, h("span", { class: "stg-slider" })]),
      ]));
      const enabledMedia = new Set(cfg.mediaTypes || ["covers", "screenshots", "wheel", "videos"]);
      const mediaHeading = h("div", { class: "stg-subsection-title" }, ["가져올 미디어"]);
      const mediaHelp = h("div", { class: "stg-help" }, ["스크랩 후보에서 내려받을 종류를 고릅니다."]);
      wrap.appendChild(mediaHeading);
      wrap.appendChild(mediaHelp);
      const mediaChoices = h("div", { class: "scrape-media-settings" });
      Object.entries(MEDIA_LABEL).forEach(([value, label]) => {
        const box = h("input", { type: "checkbox" });
        box.checked = enabledMedia.has(value);
        box.addEventListener("change", () => {
          if (box.checked) enabledMedia.add(value); else enabledMedia.delete(value);
          api.saveScraperSettings({ mediaTypes: [...enabledMedia] });
        });
        mediaChoices.appendChild(h("label", { class: "scrape-media-choice" }, [
          box, h("span", {}, [label]),
        ]));
      });
      wrap.appendChild(mediaChoices);
      const datHeading = h("div", { class: "stg-subsection-title" }, ["식별 데이터"]);
      const datHelp = h("div", { class: "stg-help" },
        ["보유한 Logiqx DAT 또는 MAME listxml을 가져오면 ROM 코드명과 CRC를 정식 제목 검색에 활용합니다. 결과는 직접 확인해야 합니다."]);
      const datStatus = h("div", { class: "stg-info" }, ["가져온 DAT를 확인하는 중…"]);
      const datProgress = h("div", { class: "stg-progress" });
      const systemSelect = h("select", { class: "field-input", "aria-label": "DAT System" });
      const systems = await api.scraperSystems();
      (systems.ok ? systems.data : []).filter((row) => row.name && row.id).forEach((row) => {
        systemSelect.appendChild(h("option", { value: row.name }, [row.name]));
      });
      const datButton = h("button", { class: "btn", onClick: async () => {
        const picked = await api.pickFile("DAT XML 선택", ["XML files (*.xml;*.dat)"]);
        if (!picked.ok || !picked.data) return;
        datButton.disabled = true;
        const started = await api.startDatImport(picked.data, systemSelect.value);
        if (!started.ok) {
          datStatus.textContent = started.error;
          datButton.disabled = false;
          return;
        }
        const completed = await pollJob(started.data.jobId, "DAT 가져오기", datProgress);
        datStatus.textContent = completed.ok
          ? completed.data.name + " · " + completed.data.system + " · " + completed.data.games.toLocaleString() + "개 게임"
          : completed.error;
        datButton.disabled = false;
        if (completed.ok) refreshDatSources();
      } }, ["DAT 추가…"]);
      const datSources = h("div", { class: "stg-help" });
      const refreshDatSources = async () => {
        const sources = await api.datSources();
        datSources.textContent = !sources.ok ? sources.error
          : sources.data.length
            ? sources.data.map((source) => source.name + " (" + source.system + ", " + source.entries.toLocaleString() + "개)").join(" · ")
            : "가져온 DAT 없음";
      };
      wrap.append(datHeading, datHelp, h("div", { class: "stg-inline-actions" },
        [systemSelect, datButton]), datProgress, datStatus, datSources);
      refreshDatSources();
    };
    draw();
    return wrap;
  }

  // ------------------------------------------------------------------
  // Scraper review context
  // ------------------------------------------------------------------
  async function openScraperSetup(afterSave) {
    const current = await api.scraperSettings();
    const cfg = current.ok ? current.data : {};
    const devId = h("input", { class: "field-input", placeholder: cfg.devIdSet ? "저장됨 - 바꿀 때만 입력" : "Dev ID" });
    const devPassword = h("input", { class: "field-input", type: "password",
      placeholder: cfg.devPasswordSet ? "저장됨 - 바꿀 때만 입력" : "Dev password" });
    const softName = h("input", { class: "field-input", value: cfg.softName || "RetroMetaStudio" });
    const userId = h("input", { class: "field-input", value: cfg.userId || "", placeholder: "ScreenScraper 사용자 ID" });
    const userPassword = h("input", { class: "field-input", type: "password",
      placeholder: cfg.userPasswordSet ? "저장됨 - 바꿀 때만 입력" : "사용자 비밀번호" });
    const setupRow = (label, input, help) => h("label", { class: "scrape-setup-row" }, [
      h("span", { class: "field-label" }, [label]), input,
      help ? h("span", { class: "modal-hint" }, [help]) : null,
    ]);
    const body = h("div", { class: "modal-body scrape-setup" }, [
      setupRow("Developer ID", devId), setupRow("Developer Password", devPassword),
      setupRow("Software name", softName), setupRow("User ID", userId),
      setupRow("User Password", userPassword,
        "비밀번호는 Windows 보안 저장소에 암호화해 저장합니다."),
    ]);
    const card = showModal("ScreenScraper 연결", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary", onClick: async () => {
        const patch = { enabled: true, softName: softName.value.trim(), userId: userId.value.trim() };
        if (devId.value) patch.devId = devId.value;
        if (devPassword.value) patch.devPassword = devPassword.value;
        if (userPassword.value) patch.userPassword = userPassword.value;
        const saved = await api.saveScraperSettings(patch);
        if (!saved.ok) { showToast(saved.error, "error"); return; }
        closeModal();
        if (afterSave) afterSave();
      } }, ["저장"]),
    ]);
    card.classList.add("scrape-setup-card");
  }

  function scrapeQuotaText(quota) {
    if (!quota) return "사용량 확인 중";
    const used = Number(quota.requestsToday || 0);
    const limit = Number(quota.requestsLimit || 0);
    return limit ? `오늘 ${formatCount(used)} / ${formatCount(limit)}회`
      : `오늘 ${formatCount(used)} / 한도 미확인`;
  }

  async function openScrapeContext(itemIds) {
    const ids = [...new Set((itemIds || []).map(String))];
    if (!ids.length) { showToast("스크랩할 게임을 선택하세요.", "error"); return; }
    const settings = await api.scraperSettings();
    if (!settings.ok) { showToast(settings.error, "error"); return; }
    if (!settings.data.devIdSet || !settings.data.devPasswordSet) {
      openScraperSetup(() => openScrapeContext(ids));
      return;
    }
    const systemsResult = await api.scraperSystems();
    const scraperSystems = systemsResult.ok ? systemsResult.data : [];
    const arcadeNames = new Set(["arcade", "mame", "mame2003", "mame2003plus",
      "mame2010", "fbneo", "fbern", "fba", "cps1", "cps2", "cps3"]);
    const scraperSystemName = (name) => {
      const normalized = String(name || "").toLowerCase();
      if (normalized === "vita") return "psvita";
      // The dropdown exposes one Arcade choice; item.system retains the
      // original Collection/Archive folder for applying results.
      return arcadeNames.has(normalized) ? "arcade" : normalized;
    };
    const currentSystems = isArchive()
      ? (activeDetail()?.archiveSystems || []).map((entry) => scraperSystemName(entry.system))
      : (activeDetail()?.systems || []).map((entry) => scraperSystemName(entry.system));
    const systemChoices = [...new Map([
      ...scraperSystems.map((entry) => [scraperSystemName(entry.name),
        { ...entry, name: scraperSystemName(entry.name) }]),
      ...currentSystems.map((name) => [name, scraperSystems.find((entry) => entry.name === name)
        || { name, id: null }]),
    ]).values()].filter((entry) => entry.id).sort((a, b) => a.name.localeCompare(b.name));
    const target = isArchive() ? "archive" : "collection";
    const created = await api.createScrapeSession(target, isArchive() ? null : S.activeId, ids);
    if (!created.ok) { showToast(created.error, "error"); return; }
    const session = created.data;
    let index = 0;
    let searching = false;
    let currentJobId = null;
    let stopRequested = false;
    let quota = session.quota;
    let accountQuotaBase = quota && !quota.estimated ? Number(quota.requestsToday || 0) : 0;
    let sessionEstimate = quota?.estimated ? Number(quota.requestsToday || 0) : 0;
    const expandedCandidates = new Set();
    let closed = false;

    const body = h("div", { class: "modal-body scrape-context" });
    const cancelSession = async () => {
      closed = true;
      if (currentJobId) await api.cancelJob(currentJobId);
      await api.cancelScrapeSession(session.id);
    };
    const titleCount = h("span", { class: "scrape-title-count" }, ["스크랩"]);
    const quotaBadge = h("span", { class: "scrape-quota", title: "ScreenScraper 일일 요청 사용량" },
      [scrapeQuotaText(quota)]);
    const card = showModal(h("div", { class: "scrape-modal-heading" },
      [titleCount, quotaBadge]), body, []);
    card.classList.add("scrape-context-card");
    $("modal-root").__beforeClose = cancelSession;
    const cancel = () => closeModal();

    async function searchCurrent(query, systemHint, forceSearch = false) {
      if (searching || closed) return;
      searching = true;
      stopRequested = false;
      draw();
      const item = session.items[index];
      const started = await api.startScrapeItem(session.id, item.id, query || item.query,
                                                systemHint, forceSearch);
      if (!started.ok) { searching = false; showToast(started.error, "error"); draw(); return; }
      currentJobId = started.data.jobId;
      if (stopRequested) await api.cancelJob(currentJobId);
      const result = await pollJob(started.data.jobId,
        `${index + 1}/${session.items.length} ${item.filename}`, body.querySelector(".scrape-progress"));
      currentJobId = null;
      searching = false;
      if (closed) return;
      if (!result.ok) {
        item.status = result.cancelled ? "cancelled" : "error";
        item.error = result.error;
      } else {
        Object.assign(item, result.data.item || {});
        delete item.error;
        const incomingQuota = result.data.quota || {};
        if (incomingQuota.estimated) sessionEstimate = Number(incomingQuota.requestsToday || 0);
        quota = { ...quota, ...incomingQuota,
          requestsToday: incomingQuota.estimated
            ? Math.max(Number(quota?.requestsToday || 0), accountQuotaBase + sessionEstimate)
            : Number(incomingQuota.requestsToday || 0),
          requestsLimit: incomingQuota.requestsLimit || quota?.requestsLimit || 0 };
      }
      draw();
    }

    function candidateCard(item, candidate) {
      let expanded = expandedCandidates.has(candidate.candidate_id);
      const previouslySelected = item.selectedCandidateId === candidate.candidate_id;
      const selectedFields = new Set(previouslySelected
        ? (item.selectedFields || []) : Object.keys(candidate.fields || {}));
      // The provider has already filtered media to the selected Settings
      // types. Default to all of those results, including video/manual/etc.
      const selectedMedia = new Set(previouslySelected ? (item.selectedMedia || [])
        : (candidate.media || []).map((_, mediaIndex) => mediaIndex));
      const wrap = h("div", { class: "scrape-candidate" + (previouslySelected ? " selected" : "") });
      const selectCandidate = async () => {
          const selectedFieldKeys = [...selectedFields];
          const selected = await api.selectScrapeCandidate(session.id, item.id,
                                                            candidate.candidate_id, selectedFieldKeys,
                                                            [...selectedMedia]);
          if (!selected.ok) { showToast(selected.error, "error"); return; }
          item.selectedCandidateId = candidate.candidate_id;
          item.selectedFields = selectedFieldKeys;
          item.selectedMedia = [...selectedMedia];
          item.status = "selected";
          delete item.applyError;
          draw();
      };
      wrap.addEventListener("click", (event) => {
        if (!event.target.closest("button,input")) selectCandidate();
      });
      const redraw = () => {
        clear(wrap);
        wrap.classList.toggle("expanded", expanded);
        const cover = (candidate.media || []).find((m) => m.media_type === "covers")
          || (candidate.media || []).find((m) => m.media_type === "screenshots");
        const thumb = cover
          ? h("img", { class: "scrape-thumb", src: cover.url, alt: candidate.title, referrerpolicy: "no-referrer" })
          : h("div", { class: "scrape-thumb empty" }, [icon("image", IC.md)]);
        const toggle = h("button", { class: "icon-btn scrape-expand", title: expanded ? "접기" : "자세히" },
          [icon(expanded ? "chevronUp" : "chevronDown", IC.sm)]);
        toggle.addEventListener("click", () => {
          expanded = !expanded;
          if (expanded) expandedCandidates.add(candidate.candidate_id);
          else expandedCandidates.delete(candidate.candidate_id);
          redraw();
        });
        const year = String(candidate.fields?.releasedate || "").match(/\d{4}/)?.[0] || "";
        const description = String(candidate.fields?.desc || "").replace(/\s+/g, " ").trim();
        const fact = (label, value) => h("span", { class: "scrape-fact", title: `${label}: ${value || "없음"}` },
          [String(value || "")]);
        wrap.appendChild(h("div", { class: "scrape-candidate-head" }, [thumb,
          h("div", { class: "scrape-candidate-main" }, [
            h("div", { class: "scrape-candidate-top" }, [
              h("span", { class: "scrape-system-icon", title: candidate.system || item.system },
                [systemIcon(item.systemHint || item.system, 16)]),
              h("div", { class: "scrape-candidate-title", title: candidate.title || "" },
                [candidate.title || "제목 없음"]),
              Number(candidate.confidence || 0) < 45
                ? h("span", { class: "scrape-review-icon",
                  title: candidate.confidence_reason || "낮은 유사도 · 직접 확인 필요",
                  "aria-label": "낮은 유사도 · 직접 확인 필요" },
                [icon("triangleAlert", IC.xs)]) : null,
            ]),
            h("div", { class: "scrape-candidate-desc", title: description }, [description || "설명 없음"]),
            h("div", { class: "scrape-candidate-facts" }, [
              h("div", { class: "scrape-fact-row" }, [
                fact("연도", year), fact("개발", candidate.fields?.developer),
                fact("장르", candidate.fields?.genre), toggle,
              ]),
            ]),
          ])]));
        if (!expanded) return;
        if ((candidate.evidence || []).length) wrap.appendChild(h("div", { class: "scrape-evidence" },
          candidate.evidence.map((value) => h("div", {}, [value]))));
        const fields = h("div", { class: "scrape-fields" });
        Object.entries(candidate.fields || {}).forEach(([key, value]) => {
          if (value === "" || value === null || value === undefined) return;
          const box = h("input", { type: "checkbox", value: key });
          box.checked = selectedFields.has(key);
          box.addEventListener("change", () => {
            if (box.checked) selectedFields.add(key); else selectedFields.delete(key);
            if (item.selectedCandidateId === candidate.candidate_id) selectCandidate();
          });
          fields.appendChild(h("label", { class: "scrape-field" }, [box,
            h("span", { class: "scrape-field-name" }, [key]),
            h("span", { class: "scrape-field-current" }, [String(item.fields?.[key] || "비어 있음")]),
            h("span", { class: "scrape-field-arrow" }, ["→"]),
            h("span", { class: "scrape-field-value" }, [Array.isArray(value) ? value.join(", ") : String(value)]),
          ]));
        });
        wrap.appendChild(fields);
        const previewMedia = (candidate.media || []).map((media, mediaIndex) => ({ media, mediaIndex }))
          .filter(({ media }) => media.media_type === "covers" || media.media_type === "screenshots");
        if (previewMedia.length) {
          const mediaList = h("div", { class: "scrape-media-list" });
          previewMedia.forEach(({ media, mediaIndex }) => {
            const radio = h("input", { type: "checkbox" });
            radio.checked = selectedMedia.has(mediaIndex);
            radio.addEventListener("change", () => {
              if (radio.checked) {
                (candidate.media || []).forEach((other, otherIndex) => {
                  if (other.media_type === media.media_type) selectedMedia.delete(otherIndex);
                });
                selectedMedia.add(mediaIndex);
                redraw();
              } else selectedMedia.delete(mediaIndex);
              if (item.selectedCandidateId === candidate.candidate_id) selectCandidate();
            });
            mediaList.appendChild(h("label", { class: "scrape-media-option" }, [
              radio,
              h("img", { src: media.url, alt: media.media_type, loading: "lazy", referrerpolicy: "no-referrer" }),
              h("span", {}, [media.media_type]),
              h("small", {}, [[media.region, media.language].filter(Boolean).join(" · ")]),
            ]));
          });
          wrap.appendChild(mediaList);
        }
      };
      redraw();
      return wrap;
    }

    function hasSelection() {
      return session.items.some((item) => item.status === "selected" && item.selectedCandidateId);
    }

    async function finish() {
      const started = await api.startApplyScrapeSession(session.id);
      if (!started.ok) { showToast(started.error, "error"); return; }
      const applied = await pollJob(started.data.jobId, "스크랩 결과 적용",
        body.querySelector(".scrape-progress"));
      if (!applied.ok) { if (!applied.cancelled) showToast(applied.error, "error"); return; }
      const failedCount = (applied.data.failed || []).length;
      const partialCount = (applied.data.partial || []).length;
      if (failedCount || partialCount) {
        const problems = [...(applied.data.failed || []), ...(applied.data.partial || [])];
        const refreshed = await api.scrapeSession(session.id);
        if (refreshed.ok) {
          Object.assign(session, refreshed.data);
          const retryIndex = session.items.findIndex((item) => item.status === "selected");
          if (retryIndex >= 0) index = retryIndex;
        }
        problems.forEach((problem) => {
          const item = session.items.find((entry) => String(entry.id) === String(problem.itemId));
          if (item) item.applyError = problem.error;
        });
        showToast(`스크랩 적용: 완료 ${formatCount((applied.data.applied || []).length)}개`
          + (partialCount ? ` · 일부 반영 ${formatCount(partialCount)}개` : "")
          + (failedCount ? ` · 실패 ${formatCount(failedCount)}개` : ""),
        failedCount ? "error" : "warning");
        draw();
        return;
      }
      const appliedIds = new Set((applied.data.applied || []).map(String));
      session.items.forEach((item) => {
        if (appliedIds.has(String(item.id))) {
          item.status = "applied";
          item.selectedCandidateId = null;
        }
      });
      const nextIndex = Array.from({ length: session.items.length }, (_, step) =>
        (index + step + 1) % session.items.length).find((candidateIndex) =>
        !["applied", "skipped"].includes(session.items[candidateIndex].status));
      if (nextIndex >= 0) {
        index = nextIndex;
        showToast(`${formatCount(appliedIds.size)}개 게임에 스크랩 결과를 적용했습니다.`);
        await reloadList();
        draw();
        const nextItem = session.items[index];
        if (nextItem.status === "pending" && !(nextItem.candidates || []).length) {
          await searchCurrent(nextItem.query, nextItem.systemHint);
        }
        return;
      }
      $("modal-root").__beforeClose = null;
      closed = true;
      closeModal();
      showToast(`${formatCount(applied.data.applied.length)}개 게임에 스크랩 결과를 적용했습니다.`);
      await reloadList();
      // Collection media Apply may rescan and assign new romUid values. Find
      // the reviewed game by System and filename, never by its old numeric ID.
      const reviewed = session.items[index];
      let row = [...S.rowCache.values()].find((entry) => entry
        && entry.system === reviewed.system && entry.file === reviewed.filename);
      if (!row) {
        const found = await fetchRows({ ...currentQuery(), search: reviewed.filename,
          systems: [reviewed.system], limit: PAGE_SIZE, offset: 0 });
        if (found.ok) row = (found.data.rows || []).find((entry) =>
          entry.system === reviewed.system && entry.file === reviewed.filename);
      }
      S.detailState = null;
      if (row) {
        S.selected = new Set([row.romUid]);
        S.selectAnchor = row.romUid;
        await openDetail(row);
      } else {
        S.focused = null;
        renderDetailPanel();
        updateSelectionVisual();
      }
    }

    function draw() {
      clear(body);
      const item = session.items[index];
      titleCount.textContent = `스크랩 결과 (${index + 1}/${session.items.length})`;
      const head = h("div", { class: "scrape-context-head" }, [
        h("span", { class: "scrape-file-tag" }, ["ROM"]),
        h("span", { class: "scrape-current-file", title: item.filename }, [item.filename]),
        h("button", { class: "icon-btn scrape-file-copy", title: "ROM 이름 복사",
          onClick: () => copyTextToClipboard(
            String(item.filename || "").replace(/\.[^.]+$/, ""), "ROM 이름을 복사했습니다.") },
        [icon("copy", IC.sm)]),
      ]);
      quotaBadge.textContent = scrapeQuotaText(quota);
      quotaBadge.title = quota?.estimated ? "ScreenScraper 사용량 추정치 · 확인 후 갱신됩니다" : "ScreenScraper 일일 요청 사용량";
      const query = h("input", { class: "field-input scrape-query", value: item.query || "",
                                  placeholder: "검색할 게임명" });
      const system = h("select", { class: "field-input scrape-system" }, [
        h("option", { value: "" }, ["전체 시스템"]),
        ...systemChoices.map((entry) => h("option", { value: entry.name },
          [entry.name.toUpperCase()])),
      ]);
      const defaultSystem = systemChoices.some((entry) => entry.name === scraperSystemName(item.system) && entry.id)
        ? scraperSystemName(item.system) : "";
      const chosenSystem = item.systemHint === undefined ? defaultSystem
        : scraperSystemName(item.systemHint);
      system.value = chosenSystem || "";
      query.addEventListener("input", () => { item.query = query.value; });
      system.addEventListener("change", () => { item.systemHint = system.value; });
      const retrySearch = () => searchCurrent(query.value.trim(), system.value);
      query.addEventListener("keydown", (event) => { if (event.key === "Enter") retrySearch(); });
      system.addEventListener("keydown", (event) => { if (event.key === "Enter") retrySearch(); });
      const retry = h("button", { class: "btn primary compact", onClick: () => {
        if (searching) {
          stopRequested = true;
          retry.disabled = true;
          retry.textContent = "중지 중…";
          if (currentJobId) api.cancelJob(currentJobId);
        } else retrySearch();
      } }, [searching ? "스크랩 중지" : "스크랩 시작"]);
      body.appendChild(head);
      body.appendChild(h("div", { class: "scrape-search-row" }, [
        h("label", {}, [h("span", {}, ["검색명"]), query]),
        h("label", {}, [h("span", {}, ["시스템"]), system])]));
      body.appendChild(h("div", { class: "scrape-progress" }));
      body.appendChild(h("div", { class: "scrape-results-head" }, [
        h("span", {}, [`후보 결과 : ${(item.candidates || []).length}건 감지됨`]), retry,
      ]));
      if (item.confirmedGameId || item.aliasGameId) body.appendChild(h("div", { class: "scrape-confirmed-actions" }, [
        h("span", {}, ["이전에 확정한 게임을 우선 표시합니다."]),
        h("button", { class: "btn compact", disabled: searching,
          onClick: () => searchCurrent(query.value.trim(), system.value, true) }, ["다른 후보 검색"]),
        h("button", { class: "btn compact", disabled: searching, onClick: async () => {
          const cleared = await api.clearScrapeConfirmedMatch(session.id, item.id);
          if (!cleared.ok) { showToast(cleared.error, "error"); return; }
          delete item.confirmedGameId;
          draw();
        } }, ["확정·별칭 해제"]),
      ]));
      if (item.applyError) body.appendChild(h("div", { class: "modal-text error", role: "alert" },
        [`적용 실패: ${item.applyError}`]));
      const candidates = h("div", { class: "scrape-candidates" });
      if (searching) candidates.appendChild(h("div", { class: "panel-empty-state" }, ["검색 중…"]));
      else if (item.error) candidates.appendChild(h("div", { class: "modal-text error" }, [item.error]));
      else if (!(item.candidates || []).length && item.status !== "pending")
        candidates.appendChild(h("div", { class: "panel-empty-state" },
          ["후보가 없습니다. 검색 키나 시스템을 바꾸고 다시 스크랩하세요."]));
      else if (!(item.candidates || []).length)
        candidates.appendChild(h("div", { class: "panel-empty-state" },
          ["검색명과 시스템을 확인한 뒤 스크랩 시작을 누르세요."]));
      else (item.candidates || []).forEach((candidate) => candidates.appendChild(candidateCard(item, candidate)));
      body.appendChild(candidates);

      const previous = h("button", { class: "btn", disabled: index === 0 || searching,
        onClick: () => { index -= 1; draw(); } }, ["이전 스크랩"]);
      const skip = h("button", { class: "btn", disabled: searching, onClick: async () => {
        if (item.status !== "selected" && item.status !== "applied") {
          const skipped = await api.skipScrapeItem(session.id, item.id);
          if (!skipped.ok) { showToast(skipped.error, "error"); return; }
          item.status = "skipped";
        }
        if (index + 1 < session.items.length) { index += 1; draw(); } else draw();
      } }, ["다음 스크랩"]);
      const actions = h("div", { class: "scrape-actions" }, [previous, skip,
        h("span", { class: "scrape-action-spacer" }),
        h("button", { class: "btn", onClick: cancel }, ["취소"]),
        h("button", { class: "btn primary", disabled: !hasSelection() || searching, onClick: finish },
          ["선택 적용"]),
      ]);
      body.appendChild(actions);
    }

    draw();
    // Quota is useful context, but its separate network request must not
    // hold up the candidate search.
    api.startScraperAccountStatus().then(async (started) => {
      if (!started.ok) return;
      const poll = async () => {
        const result = await api.jobProgress(started.data.jobId);
        if (closed || !result.ok) return;
        if (!result.data.done) { setTimeout(poll, 250); return; }
        if (!result.data.error) {
          const actual = Number(result.data.result?.requestsToday || 0);
          accountQuotaBase = Math.max(0, actual - sessionEstimate);
          quota = { ...quota, ...result.data.result,
            requestsToday: Math.max(actual, Number(quota?.requestsToday || 0)),
            estimated: Number(quota?.requestsToday || 0) > actual };
          quotaBadge.textContent = scrapeQuotaText(quota);
        }
      };
      poll();
    });
  }

  async function confirmArchiveSystemRomDelete(sys) {
    showConfirm(`${sys.system.toUpperCase()} - Archive 보관 ROM 삭제`,
      `이 System의 항목 ${formatCount(sys.count)}개를 확인해 Archive ROM 디렉토리 안의 파일만 삭제합니다. `
      + "외부 Collection의 원본 ROM과 연결은 그대로 유지합니다.", true, async () => {
        const ids = await api.archiveUids([sys.system]);
        if (!ids.ok) { showToast(ids.error, "error"); return; }
        const r = await api.archiveRomDelete(ids.data || []);
        if (!r.ok) { showToast(r.error, "error"); return; }
        resetList();
        renderAll();
        await reloadList();
        showToast(`Archive 보관 ROM ${formatCount(r.data.deletedFiles || 0)}개를 삭제했습니다.`
          + ((r.data.linkedSourcesKept || 0)
            ? ` 원본 연결 ${formatCount(r.data.linkedSourcesKept)}개는 유지했습니다.` : ""));
      });
  }

  async function confirmArchiveSystemMediaDelete(sys) {
    const preview = await api.archiveMediaCleanupPreview(sys.system);
    if (!preview.ok) { showToast(preview.error, "error"); return; }
    const types = preview.data.types || [];
    if (!types.length) { showToast("Archive에 보관된 미디어가 없습니다."); return; }
    const checks = types.map((item) => {
      const input = h("input", { type: "checkbox" });
      const row = h("label", { class: "media-clean-row" }, [input,
        h("span", { class: "media-clean-name" }, [item.label]),
        h("span", { class: "media-clean-count" },
          [`${formatCount(item.count)}개 · ${formatBytes(item.bytes)}`]),
      ]);
      return { type: item.type, input, row };
    });
    const remove = h("button", { class: "btn danger", disabled: true }, ["삭제"]);
    checks.forEach(({ input }) => input.addEventListener("change", () => {
      remove.disabled = !checks.some((entry) => entry.input.checked);
    }));
    remove.addEventListener("click", async () => {
      const selected = checks.filter((entry) => entry.input.checked).map((entry) => entry.type);
      if (!selected.length) return;
      closeModal();
      const r = await api.archiveMediaDeleteSystem(sys.system, selected);
      if (!r.ok) { showToast(r.error, "error"); return; }
      resetList();
      renderAll();
      await reloadList();
      showToast(`Archive 보관 Media ${formatCount(r.data.removed || 0)}개를 삭제했습니다.`
        + ((r.data.linkedKept || 0)
          ? ` 원본 연결 ${formatCount(r.data.linkedKept)}개는 유지했습니다.` : "")
        + ((r.data.failures || []).length
          ? ` 실패 ${formatCount(r.data.failures.length)}개.` : ""),
      (r.data.failures || []).length ? "warning" : "success");
    });
    showModal(`${sys.system.toUpperCase()} - Archive 미디어 정리`,
      h("div", { class: "modal-body" }, [
        h("div", { class: "modal-text" }, [
          "종류를 골라 Archive 보관 미디어만 삭제합니다. 외부 Collection 원본은 유지합니다."]),
        ...checks.map((entry) => entry.row),
      ]), [h("button", { class: "btn", onClick: closeModal }, ["취소"]), remove]);
  }

  /** 상세 패널의 별표. 목록의 별표와 같은 곳을 가리켜야 한다. */
  async function toggleFavoriteFromDetail(button) {
    const state = S.detailState;
    if (!state || blockedInCompare("즐겨찾기를 변경")) return;
    const next = !state.favorite;
    state.favorite = next;
    button.textContent = next ? "★" : "☆";
    button.classList.toggle("on", next);

    const r = state.archive
      ? await api.archiveSetFavorite(state.romIdentityId, next)
      : await api.setFavorite(S.activeId, state.romUid, next);
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
    }
    // "Archive로" 버튼은 여기 있었다. 무엇을 하는 버튼인지 이름만 봐서는 잘 안
    // 읽혔고(실사용 피드백), HERO의 Archive로 보내기 아이콘으로 옮겼다.

    // 아이콘과 "미리보기" 글자를 합친 전체가 누르는 자리다(사용자 요청). 클릭은
    // 이 바깥 상자 하나에만 건다 - 안쪽 아이콘 버튼에도 걸면 한 번 눌러 두 번 토글된다.
    const previewToggle = h("div", {
      class: "detail-preview-toggle",
      title: S.previewOn ? "미리보기 끄기" : "미리보기 켜기",
    });
    previewToggle.appendChild(h("button", {
      class: "icon-btn" + (S.previewOn ? " on" : ""),
      title: S.previewOn ? "미리보기 끄기" : "미리보기 켜기",
    }, [icon("previewPane", IC.md)]));
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
    stopMediaVideo();
    const top = $("detail-top");
    clear(top);
    top.appendChild(renderDetailTopSpace());

    const panel = $("detail-panel");
    clear(panel);
    // Compare가 아니거나 상세가 닫혔으면 왼쪽 Detail(기준 쪽)은 비운다.
    const leftPanel = $("compare-left");
    if (leftPanel && !(S.detailState && S.detailState.compare)) clear(leftPanel);
    // Preview를 끄면 **아랫줄의 Detail 내용 기둥만** 뺀다. 윗줄(#detail-top)은
    // 남으므로 다시 켤 토글이 사라지지 않고, 빠진 폭은 목록이 쓴다(사용자 요청 -
    // 예전엔 패널 전체 폭을 44px로 접어 윗줄의 GameList 헤더까지 재배치됐고, 그
    // 전엔 폭을 그대로 둬서 목록이 전혀 넓어지지 않았다).
    //
    // Compare 중에는 좌/우 두 기둥이 있고, `leftPanel`은 `panel`과 다른 DOM
    // 노드다 - 끌 때 `panel`만 손대면 오른쪽만 사라졌다(실사용 버그 리포트,
    // 메뉴 정리 §8). 둘 다 같은 상태를 따라가야 한다.
    panel.classList.toggle("off", !S.previewOn);
    if (leftPanel) leftPanel.classList.toggle("off", !S.previewOn);
    if (!S.previewOn) {
      panel.classList.remove("open");
      if (leftPanel) clear(leftPanel);
      return;
    }
    const state = S.detailState;
    panel.classList.toggle("open", !!state);
    if (!state) {
      // 패널이 늘 자리를 차지하므로 빈 칸을 그냥 두지 않는다.
      panel.appendChild(h("div", { id: "detail-panel-inner" }, [
        h("div", { class: "panel-empty-state" }, [
          icon("gamepad", IC.lg),
          h("div", { class: "panel-empty-msg" }, ["게임을 선택하면 여기에 표시됩니다"]),
        ]),
      ]));
      return;
    }

    if (state.compare) { renderCompareDetail(panel); return; }

    const inner = h("div", { id: "detail-panel-inner" });
    panel.appendChild(inner);

    // **순서: Favorite, 제목, 파일명 복사, Play**(실사용 피드백 §6).
    //
    // Favorite는 제목 왼쪽으로 - 게임을 훑어보며 즐겨찾기를 표시할 때 가장 먼저
    // 눈에 들어오는 자리다. 파일명 복사는 예전에 파일명 글자 바로 뒤에 붙어 있어서,
    // 파일명이 길면 버튼이 밀려나거나 말줄임(...)과 겹쳐 보였다 - Play 옆(맨
    // 오른쪽 고정 자리)으로 옮기고, 파일명 자리는 항상 같은 폭을 갖고 넘치면
    // 말줄임으로 잘라 보여준다(.detail-filename의 text-overflow는 그대로 둔다).
    const header = h("div", { class: "detail-header" });
    {
      const star = h("button", {
        class: "icon-btn fav-btn" + (state.favorite ? " on" : ""),
        title: state.favorite ? "즐겨찾기 해제" : "즐겨찾기",
      }, [state.favorite ? "★" : "☆"]);
      star.addEventListener("click", () => toggleFavoriteFromDetail(star));
      header.appendChild(star);
    }

    header.appendChild(h("div", { style: { minWidth: "0", flex: "1" } }, [
      h("div", { class: "detail-eyebrow" }, ["METADATA"]),
      h("div", { class: "detail-filename", title: state.file }, [state.file]),
      h("div", { class: "detail-system" }, [
        systemIcon(state.system, 13), String(state.system).toUpperCase(),
        state.archive ? ownershipBadge(state.ownership?.mode, true) : null,
      ]),
    ]));

    // 파일명 복사는 Archive 항목에도 있다(예전부터 그랬다) - Play/Favorite만
    // 실행 개념이 있는 일반 Collection 전용이다.
    const copyBtn = h("button", {
      class: "icon-btn detail-copy", title: "파일명 복사",
      onClick: () => copyTextToClipboard(state.file, "파일명을 복사했습니다."),
    }, [icon("copy", IC.sm)]);
    header.appendChild(copyBtn);

    const target = { romUid: state.romUid, system: state.system, file: state.file, present: state.present };
    const blocked = launchBlockReason(target);
    const play = h("button", {
      class: "icon-btn detail-launch", title: blocked || "RetroArch로 실행 (행 더블클릭도 됩니다)",
      disabled: !!blocked,
    }, [icon("play", IC.md)]);
    play.addEventListener("click", () => launchGame(target));
    header.appendChild(play);
    inner.appendChild(header);

    const tabs = h("div", { class: "detail-tabs" });
    const tabDefs = state.archive
      ? [["metadata", "Metadata"], ["media", "Media"], ["rom", "ROM"], ["sources", "Revision"]]
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
      const footer = h("div", { class: "detail-footer detail-footer-split" });
      const conflictInfo = !state.archive && currentSystemConflict(state.system);
      const scrap = h("button", { class: "btn detail-scrap", title: "이 게임의 메타데이터 후보 찾기" },
        [icon("sparkles", IC.md), h("span", {}, ["스크랩"])]);
      scrap.addEventListener("click", () => openScrapeContext([
        state.archive ? state.romIdentityId : state.romUid,
      ]));
      const save = h("button", { class: "btn primary detail-save", disabled: !!conflictInfo },
        [icon("save", IC.md), h("span", {}, [conflictInfo ? "쓰기 막힘 - Storage 충돌" : "저장 (Ctrl+S)"])]);
      if (conflictInfo) save.title = "같은 System 폴더가 여러 Storage에 있습니다 - System 우클릭에서 한쪽을 지우거나 이름을 바꾸세요.";
      save.addEventListener("click", handleSaveDetail);
      footer.appendChild(scrap);
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
      cover.appendChild(icon("image", IC.lg));
    }
    // **표지는 크게, 요약은 그 옆에.** 아래 편집 폼과 값이 겹치지만, 편집하러
    // 들어오기 전에 "이 게임이 무엇인가"를 한눈에 보는 자리라 그대로 둔다(사용자
    // 결정 - 한 번 없애 봤더니 게임을 알아보기 어려워졌다).
    const main = h("div", { class: "identity-main" });
    const grid = h("div", { class: "identity-grid" });
    [["Genre", "genre"], ["Release", "releasedate"], ["Players", "players"],
     ["Region", "region"], ["Developer", "developer"], ["Publisher", "publisher"]].forEach(([label, key]) => {
      grid.appendChild(h("div", { class: "identity-field" }, [
        h("div", { class: "identity-field-label" }, [label]),
        h("div", { class: "identity-field-value truncate" }, [value(key) || "-"]),
      ]));
    });
    main.appendChild(grid);

    // 폼에 없는 것 - ROM과 Media의 실물 상태. 요약 맨 아래 한 줄로만 둔다.
    const mediaCount = Object.keys(state.media || {}).length;
    main.appendChild(h("div", { class: "identity-facts" }, [
      h("span", { class: "identity-fact" + (state.present ? "" : " warn"), title: "ROM 파일" }, [
        icon("cartridge", IC.sm),
        state.present ? formatBytes(state.size || 0) : "ROM 없음",
      ]),
      h("span", { class: "identity-fact" + (mediaCount ? "" : " warn"), title: "가지고 있는 media 종류" }, [
        icon("image", IC.sm), `Media ${formatCount(mediaCount)}`,
      ]),
    ]));

    card.appendChild(cover);
    card.appendChild(main);
    topFixed.appendChild(card);

    topFixed.appendChild(h("div", { class: "field-label" }, ["Title"]));
    const nameInput = h("input", { class: "field-input title-input", value: value("name") });
    fieldRefs.name = nameInput;
    topFixed.appendChild(nameInput);
    body.appendChild(topFixed);

    // Description은 **12줄에서 멈춘다**(실사용 피드백 - 예전엔 남는 세로 공간을
    // 전부 흡수해서 창을 늘릴수록 한없이 길어졌다). 12줄보다 길면 안에서
    // 스크롤한다. rows 속성 그대로가 그 12줄 높이를 정한다 - CSS가 더 이상
    // flex:1로 늘리지 않는다(style.css의 .detail-body-desc-wrap 참고).
    const descWrap = h("div", { class: "detail-body-desc-wrap" });
    descWrap.appendChild(h("div", { class: "field-label" }, ["Description"]));
    const desc = h("textarea", { class: "field-input", rows: 12 });
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

    // Description을 12줄로 멈춘 만큼 남는 세로 공간을, 패널이 넉넉히 클 때만
    // (컨테이너 쿼리, 850px) Screenshot과 나머지 media 유무로 채운다(실사용
    // 피드백) - 비좁은 화면에서는 style.css가 이 블록 자체를 숨긴다.
    //
    // **숨겨져 있으면 요청 자체를 안 보낸다.** CSS display:none은 화면에서만
    // 감출 뿐이라, 여기서 바로 loadMediaImage()를 부르면 좁은 패널에서도 게임을
    // 넘길 때마다 안 보이는 Screenshot을 매번 받아 온다(코드 리뷰 지적) -
    // extra가 실제로 DOM에 붙은 다음 프레임에 컨테이너 쿼리 결과(getComputedStyle)를
    // 보고, 보일 때만 요청한다.
    const extra = h("div", { class: "detail-body-fixed detail-extra-media" });
    extra.appendChild(h("div", { class: "field-label" }, ["Screenshot"]));
    const shot = h("div", { class: "detail-extra-screenshot" });
    let shotImg = null;
    if (state.media && state.media.Screenshots) {
      shotImg = h("img", { alt: "Screenshot" });
      shot.appendChild(shotImg);
    } else {
      shot.appendChild(icon("image", IC.lg));
    }
    extra.appendChild(shot);
    extra.appendChild(mediaFlagRow(state.media || {}));
    body.appendChild(extra);
    if (shotImg) {
      const img = shotImg;
      requestAnimationFrame(() => {
        if (getComputedStyle(extra).display !== "none") loadMediaImage(img, "Screenshots", true);
      });
    }
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
  let externalMediaSlot = MEDIA_HERO;

  async function importExternalMedia(slot, file) {
    const state = S.detailState;
    if (!state || state.compare || state.tab !== "media") return;
    if (!file || (!file.type?.startsWith("image/")
                  && !/\.(png|jpe?g|webp|gif)$/i.test(file.name || ""))) {
      showToast("이미지 파일만 미디어 슬롯에 놓을 수 있습니다.", "warning"); return;
    }
    if (file.size > 24 * 1024 * 1024) {
      showToast("이미지는 24MB 이하만 가져올 수 있습니다.", "error"); return;
    }
    if (slot.key === "Videos") {
      showToast("영상 슬롯에는 이미지를 놓을 수 없습니다.", "warning"); return;
    }
    try {
      const encoded = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const itemId = state.archive ? state.romIdentityId : state.romUid;
      const result = await api.importMediaImage(state.archive ? "archive" : "collection",
        state.archive ? null : S.activeId, itemId, slot.key, encoded);
      if (!result.ok) { showToast(result.error, "error"); return; }
      if (state.archive) {
        const detail = await api.archiveDetail(itemId);
        if (detail.ok && S.detailState === state) {
          S.detailState = archiveDetailState(detail.data, "media");
          renderDetailPanel();
        }
        await refreshArchiveRows([itemId]);
        showToast(`${slot.label} 이미지를 적용했습니다.`);
      } else {
        await acceptOperationPreview(result.data);
      }
    } catch (error) {
      showToast(`이미지를 읽지 못했습니다: ${error}`, "error");
    }
  }

  function mediaTile(slot, media, extraClass) {
    const has = !!media[slot.key];
    const ownership = has ? mediaOwnership(slot) : null;
    const zone = h("div", {
      class: ["media-tile", extraClass, has ? "" : "empty"].filter(Boolean).join(" "),
      title: slot.label + (has ? "" : " 없음"),
      tabindex: "0",
    });
    zone.addEventListener("pointerenter", () => { externalMediaSlot = slot; });
    zone.addEventListener("focus", () => { externalMediaSlot = slot; });
    zone.addEventListener("dragover", (event) => {
      if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      const file = [...(event.dataTransfer?.files || [])].find((entry) =>
        entry.type.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(entry.name));
      if (file) importExternalMedia(slot, file);
    });
    // 라벨은 그림 위에 겹쳐 놓는다 - 레이아웃 공간을 먹지 않아야 그림이 커진다.
    zone.appendChild(h("div", { class: "media-tile-label" }, [slot.label]));
    if (ownership) {
      zone.appendChild(h("div", {
        class: `media-tile-owner ${ownership.mode}`,
        title: OWNERSHIP_LABEL[ownership.mode] || "파일 없음",
      }, [icon(ownership.mode === "internal" ? "hardDrive" : "link", IC.xs)]));
    }

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
    } else if (slot === MEDIA_WIDE && media.Videos) {
      // Screenshot이 없는데 영상은 있는 경우 - 깨진 그림 아이콘 대신 무엇을 기다리는지 말한다
      // (사용자 결정 - "x 표시 대신 wait for video play ...").
      preview.appendChild(h("div", { class: "media-video-wait" }, [
        icon("play", IC.md), h("span", {}, ["영상 준비 중…"]),
      ]));
    } else {
      // "… 없음"을 열두 번 적으면 그것만 눈에 들어온다. 아이콘 하나로 족하다.
      preview.appendChild(icon("imageOff", IC.lg));
    }
    zone.appendChild(preview);
    zone.addEventListener("contextmenu", (e) => openMediaMenu(e, slot, has));
    return zone;
  }

  /** 복사해 둔 media 하나(다음 붙여넣기 대상). 그림 한 장만 옮길 때 쓴다 -
   * 상대 cover가 더 마음에 들 때 메타데이터는 그대로 두고 그것만 가져온다. */
  let mediaClip = null;

  function openMediaMenu(e, slot, has) {
    const state = S.detailState;
    if (!state || state.compare) return;
    e.preventDefault();
    e.stopPropagation();
    // Archive든 Collection이든 붙여넣을 수 있다 - 가는 길만 다르다(Archive는 즉시, Collection은 Plan).
    const pasteOk = !!mediaClip;
    const ownership = state.archive ? mediaOwnership(slot) : null;
    const ownsMedia = ownership?.mode === "internal";
    showContextMenu(menuPoint(e), slot.label, mediaClip
      ? `복사해 둔 것: ${mediaClip.label} (${mediaClip.title})` : null, [
      { label: "미디어 복사", icon: "copy", disabled: !has, onSelect: () => {
        mediaClip = state.archive
          ? { kind: "archive", uid: state.romIdentityId, key: slot.key }
          : { kind: "collection", id: S.activeId, uid: state.romUid, key: slot.key };
        mediaClip.label = slot.label;
        mediaClip.title = (state.fields && state.fields.name) || state.file || "";
        showToast(`${slot.label}을(를) 복사했습니다.`);
      } },
      { label: "미디어 붙여넣기", icon: "upload", disabled: !pasteOk,
        title: mediaClip ? null : "복사한 미디어가 없습니다",
        onSelect: async () => {
          // Archive는 그 자리에서 바뀌고, mediaInternal이면 Archive 내부 Revision 복사본에도
          // 보관한다. Collection은 바이트가 움직이므로 Plan을 거친다(D1).
          const r = state.archive
            ? await api.archiveMediaPaste(state.romIdentityId, slot.key, mediaClip)
            : await api.mediaPaste(S.activeId, state.romUid, slot.key, mediaClip);
          if (!r.ok) { showToast(r.error, "error"); return; }
          if (state.archive) {
            state.media = { ...(state.media || {}), [slot.key]: true };
            renderDetailPanel();
            await refreshArchiveRows([state.romIdentityId]);
            showToast(`${slot.label}을(를) 붙여넣었습니다.`);
            return;
          }
          await acceptOperationPreview(r.data);
        } },
      ...(state.archive ? [{ label: ownsMedia ? "Archive 보관 미디어 삭제" : "Archive에서 미디어 연결 제거",
        icon: "trash", danger: true,
        disabled: !has,
        title: ownsMedia
          ? "Archive가 보관하는 복사본을 삭제하고 제거 상태를 기록합니다. 외부 원본은 그대로 둡니다."
          : "외부 원본 파일은 건드리지 않고 Archive의 연결만 제거 상태로 기록합니다.",
        onSelect: () => showConfirm(ownsMedia ? "Archive 보관 미디어 삭제" : "Archive 미디어 연결 제거",
          ownsMedia
            ? `${slot.label}의 Archive 보관 복사본을 삭제합니다. 외부 원본 파일은 삭제하지 않습니다.`
            : `${slot.label} 연결을 Archive 항목에서 제거합니다. 외부 원본 파일은 삭제하지 않습니다.`,
          true, async () => {
            const r = await api.archiveMediaDelete(state.romIdentityId, slot.key);
            if (!r.ok) { showToast(r.error, "error"); return; }
            const detail = await api.archiveDetail(state.romIdentityId);
            if (detail.ok && detail.data && S.detailState === state) {
              S.detailState = archiveDetailState(detail.data, state.tab);
              renderDetailPanel();
            }
            await refreshArchiveRows([state.romIdentityId]);
            showToast(ownsMedia
              ? `${slot.label}의 Archive 보관 복사본을 삭제했습니다. 외부 원본은 그대로입니다.`
              : `${slot.label} 연결을 Archive에서 제거했습니다. 원본 파일은 그대로입니다.`);
          }) }] : []),
    ]);
  }

  //: 그림으로 보여줄 수 없는 media의 아이콘. 영상은 재생, 설명서는 문서다.
  const MEDIA_FLAG_ICONS = { Videos: "play", Manuals: "fileText", FanArt: "image" };

  /** 그림 없이 있고 없고만 말하는 줄.
   *
   * 예전에는 `v` / `x` 글자를 그대로 찍었는데, 두 글자가 서로 닮아서 멀리서는
   * 구분이 안 되고 투박했다(사용자 피드백). 지금은 media 종류를 뜻하는 아이콘을
   * 칩 안에 넣고, **있으면 또렷하게 없으면 흐리게** 한다 - 글자를 읽지 않아도
   * 밝기만으로 갈린다. */
  function mediaFlagRow(media) {
    const row = h("div", { class: "media-flags" });
    MEDIA_FLAGS.forEach((slot) => {
      const has = !!media[slot.key];
      const ownership = has ? mediaOwnership(slot) : null;
      row.appendChild(h("div", {
        class: "media-flag-item" + (has ? " on" : ""),
        title: `${slot.label}${has ? " 있음" : " 없음"}`,
      }, [
        icon(MEDIA_FLAG_ICONS[slot.key] || "image", 11),
        h("span", { class: "media-flag-label" }, [slot.label]),
        ownership ? h("span", {
          class: `media-flag-owner ${ownership.mode}`,
          title: OWNERSHIP_LABEL[ownership.mode] || "파일 없음",
        }, [icon(ownership.mode === "internal" ? "hardDrive" : "link", 9)]) : null,
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

  // ------------------------------------------------------------------
  // Media 영상 재생 - Screenshot 자리 (Settings > Metadata & Media > Video)
  // ------------------------------------------------------------------
  //
  // **자연스러운 전환이 핵심이다(사용자 요구).** Screenshot을 그대로 둔 채 그 위에 투명한 영상을
  // 겹쳐 두고, 브라우저가 실제로 첫 프레임을 그린 뒤(`playing`)에야 서서히 보이게 한다. src를
  // 넣자마자 보이게 하면 로딩 동안 검은 화면이 번쩍인다. 멈출 때는 반대로 서서히 사라진다.
  //
  // 영상은 이미지처럼 base64로 받지 않는다 - 로컬 전용 서버의 URL을 받는다(bridge/media_server.py).
  // 대기 시간이 끝나기 전에 게임을 넘기면 URL을 요청하지도 않는다.
  let mediaVideo = null;   // 지금 Screenshot 자리에 붙어 있는 영상 하나 { zone, video, timer, playBtn }

  /** 사용자가 영상을 멈춰 뒀는가(사용자 결정 - "한번 Pause 시 다른 게임으로 넘어가도 유지").
   * 앱을 켜 둔 동안만 기억한다 - 설정이 아니라 지금의 기분에 가깝다. */
  let mediaVideoPaused = false;

  function mediaVideoSettings() {
    return { ...DEFAULT_SETTINGS.media, ...((S.settings && S.settings.media) || {}) };
  }

  function stopMediaVideo(options = {}) {
    const current = mediaVideo;
    if (!current) return;
    mediaVideo = null;
    clearTimeout(current.timer);
    const { zone, video } = current;
    zone.classList.remove("video-playing", "video-loading", "video-paused");
    if (current.playBtn) current.playBtn.remove();
    if (current.pauseBadge) current.pauseBadge.remove();
    try { video.pause(); } catch (_) { /* 이미 떨어져 나간 요소 */ }
    const release = () => { video.removeAttribute("src"); try { video.load(); } catch (_) { /* 무시 */ } video.remove(); };
    // 서서히 사라지는 동안(CSS transition)만 남겨 두고 떼어낸다 - 다운로드도 여기서 끊긴다.
    if (options.fade && zone.isConnected) setTimeout(release, 400); else release();
  }

  function attachMediaVideo(zone, media) {
    stopMediaVideo();
    const settings = mediaVideoSettings();
    const state = S.detailState;
    if (!state || !media.Videos || settings.videoMode === "off") return;

    const video = h("video", { class: "media-video", preload: "none" });
    video.setAttribute("playsinline", "");
    video.loop = settings.videoLoop !== false;
    video.muted = settings.videoSound === false;
    // 음량은 Settings에서 정한다(사용자 결정). 0~100으로 받아 0~1로 쓴다.
    video.volume = Math.min(1, Math.max(0, Number(settings.videoVolume ?? 70) / 100));
    zone.classList.add("has-video");
    zone.appendChild(video);
    // 재생 버튼(.media-video-play)과 같은 재질의 동그란 배지 - "||" 글자보다 또렷하다
    // (실사용 피드백 "pause 버튼이 허접하다").
    const pauseBadge = h("div", { class: "media-video-pause-badge" }, [icon("pause", IC.lg)]);
    const current = { zone, video, timer: null, playBtn: null, pauseBadge };
    mediaVideo = current;

    video.addEventListener("playing", () => {
      if (mediaVideo !== current) return;
      zone.classList.remove("video-loading", "video-paused");
      zone.classList.add("video-playing");
      pauseBadge.remove();
    });
    // 코덱을 못 읽거나 파일이 사라졌으면 조용히 Screenshot으로 둔다.
    video.addEventListener("error", () => { if (mediaVideo === current) stopMediaVideo(); });

    const start = async () => {
      if (mediaVideo !== current) return;
      const r = state.archive
        ? await api.getArchiveMediaVideoUrl(state.romIdentityId)
        : await api.getMediaVideoUrl(S.activeId, state.romUid);
      if (mediaVideo !== current) return;
      if (!r.ok || !r.data || !r.data.url) { stopMediaVideo(); return; }
      // Screenshot이 없으면 이 자리에 깨진 그림 아이콘만 있었다 - 무엇을 기다리는지 말해 준다
      // (사용자 결정 - "x 표시 대신 wait for video play ... 라고 출력된 후 video 재생").
      zone.classList.add("video-loading");
      video.src = r.data.url;
      try {
        await video.play();
      } catch (_) {
        // 소리 있는 자동 재생을 브라우저가 막는 경우가 있다 - 그때는 소리만 끄고 보여준다.
        if (mediaVideo !== current || video.muted) return;
        video.muted = true;
        try { await video.play(); } catch (__) { if (mediaVideo === current) stopMediaVideo(); }
      }
    };

    // **누르면 멈추고, 다시 누르면 이어서 본다**(사용자 결정 - 예전에는 눌러서 끄면 Screenshot으로
    // 돌아가 버렸다). 멈춘 것은 앱을 켜 둔 동안 기억해, 다른 게임으로 넘어가도 저절로 재생하지 않는다.
    zone.addEventListener("click", (e) => {
      if (mediaVideo !== current || !zone.matches(".video-playing, .video-loading, .video-paused")) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      if (zone.classList.contains("video-paused")) {
        mediaVideoPaused = false;
        zone.classList.remove("video-paused");
        pauseBadge.remove();
        video.play().catch(() => stopMediaVideo());
        return;
      }
      mediaVideoPaused = true;
      video.pause();
      zone.classList.remove("video-playing", "video-loading");
      zone.classList.add("video-paused");
      zone.appendChild(pauseBadge);
    }, true);

    // 멈춰 둔 상태이거나 "눌러서 재생"이면 재생 버튼을 놓는다 - 저절로 시작하지 않는다.
    if (settings.videoMode === "manual" || mediaVideoPaused) {
      const btn = h("button", { class: "media-video-play", title: "영상 재생" }, [icon("play", IC.lg)]);
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        mediaVideoPaused = false;
        btn.remove();
        current.playBtn = null;
        start();
      });
      zone.appendChild(btn);
      current.playBtn = btn;
    } else {
      current.timer = setTimeout(start, Math.max(0, Number(settings.videoDelay) || 0) * 1000);
    }
  }

  function renderMediaTab(body) {
    body.classList.add("media-tab-body");
    const state = S.detailState;
    const media = state.media || {};

    // 패널이 넉넉히 클 때만(컨테이너 쿼리, 850px) 맨 위에 Title/Description을
    // 보여준다(실사용 피드백 - "타이틀 description 순으로"). 읽기 전용이다 -
    // 편집은 Metadata 탭에서만 한다(같은 값을 두 곳에서 고치게 하지 않는다).
    const fields = state.fields || {};
    body.appendChild(h("div", { class: "media-tab-identity" }, [
      h("div", { class: "media-tab-title truncate" }, [fields.name || state.file || "(제목 없음)"]),
      h("div", { class: "media-tab-desc" }, [fields.desc || "설명 없음"]),
    ]));

    const hero = h("div", { class: "media-hero" });
    hero.appendChild(mediaTile(MEDIA_HERO, media, "cover"));
    const side = h("div", { class: "media-hero-side" });
    MEDIA_HERO_SIDE.forEach((slot) => side.appendChild(mediaTile(slot, media, "side")));
    hero.appendChild(side);
    body.appendChild(hero);

    const wide = mediaTile(MEDIA_WIDE, media, "wide");
    body.appendChild(wide);
    attachMediaVideo(wide, media);

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
  /** Archive 상세의 Revision 탭.
   *
   * **같은 내용은 한 줄로 묶는다**(실사용 피드백 - "우측 Revision에 여전히 동일 버젼이 같이
   * 보인다"). 출처가 둘이어도 내용이 같으면 고를 이유가 없다 - 고를 것이 있을 때만 여러 줄이
   * 나와야 그 선택이 뜻을 가진다. 묶는 규칙은 `[n]` 뱃지와 **같은 것**을 쓴다(app/archive/conflicts.py).
   */
  //: Revision 줄에 보여줄 필드와 그 이름. Compare의 카드 구성과 같은 순서다.
  const REVISION_FIELDS = [
    ["name", "Title"], ["desc", "Description"], ["genre", "Genre"], ["developer", "Developer"],
    ["publisher", "Publisher"], ["releasedate", "Release"], ["region", "Region"],
    ["players", "Players"], ["rating", "Rating"],
  ];

  function revisionWhen(seconds) {
    if (!seconds) return "";
    const d = new Date(seconds * 1000);
    const two = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
  }

  /** 판들 사이에서 **실제로 갈리는** 필드/미디어만 추린다.
   *
   * "버전 1/2/3"만 늘어놓으면 왜 셋인지 알 수 없다(실사용 지적) - 무엇이 다른지가
   * 이 탭의 존재 이유다. 값이 모두 같은 필드는 굳이 줄마다 반복해서 보여주지 않는다. */
  function revisionDifferences(versions) {
    const differing = new Set();
    REVISION_FIELDS.forEach(([key]) => {
      const seen = new Set(versions.map((v) => String((v.fields || {})[key] || "").trim()));
      if (seen.size > 1) differing.add(key);
    });
    const mediaTypes = new Set();
    versions.forEach((v) => Object.keys(v.media || {}).forEach((t) => mediaTypes.add(t)));
    const mediaDiffering = new Set();
    mediaTypes.forEach((type) => {
      const seen = new Set(versions.map((v) => String((v.media || {})[type] ?? "없음")));
      if (seen.size > 1) mediaDiffering.add(type);
    });
    return { differing, mediaTypes: [...mediaTypes].sort(), mediaDiffering };
  }

  /** Revision 탭. **Preferred는 즐겨찾기(★)와 다른 것이다**(실사용 지적 - 같은 별표라
   * 헷갈렸다). 별표는 게임 자체의 즐겨찾기고, 여기서 고르는 것은 "이 게임의 값을
   * 어느 판에서 가져올지"다. 그래서 별표를 쓰지 않고 PREFERRED 배지와 글자 버튼으로
   * 표시한다. */
  function renderSourcesTab(body) {
    const state = S.detailState;
    const versions = state.versions || [];
    if (!versions.length) {
      body.appendChild(h("div", { class: "empty-msg" }, ["아직 수집된 Revision이 없습니다."]));
      return;
    }
    if (versions.length > 1) {
      body.appendChild(h("div", { class: "modal-hint revision-single" },
        [`서로 다른 판 ${formatCount(versions.length)}개 · 사용할 판을 고르세요.`]));
    }

    const preferredId = state.preferredRecordId || null;
    const sourceName = (id) => (id === "__archive__" ? "Archive에서 직접 편집"
      : (S.collections.find((c) => c.id === id) || {}).name || id);
    const { differing, mediaTypes, mediaDiffering } = revisionDifferences(versions);
    let previewId = state.revisionPreviewId ?? preferredId;
    const choose = h("button", { class: "btn primary compact",
      disabled: previewId == null || previewId === preferredId },
      ["선택"]);
    const selectPreview = (recordId) => {
      previewId = recordId;
      state.revisionPreviewId = recordId;
      body.querySelectorAll(".revision-row").forEach((node) =>
        node.classList.toggle("chosen", String(node.dataset.recordId) === String(recordId)));
      choose.disabled = recordId === preferredId;
    };
    choose.addEventListener("click", () => {
      if (previewId == null) return;
      togglePreferredRevision({ recordId: previewId }, false);
    });

    versions.forEach((version, index) => {
      const recordId = (version.recordIds || [])[0];
      const chosen = (version.recordIds || []).includes(previewId);
      const box = h("div", { class: "revision-row scrape-candidate" + (chosen ? " chosen" : ""),
        "data-record-id": recordId });
      box.addEventListener("click", (event) => {
        if (!event.target.closest("button")) selectPreview(recordId);
      });
      const fields = version.fields || {};
      const source = (version.sources || []).map(sourceName).join(", ") || `버전 ${index + 1}`;
      const cover = h("div", { class: "scrape-thumb empty revision-cover" }, [icon("imageOff", IC.md)]);
      if ((version.media || {}).covers) {
        const sourceId = (version.sources || [])[0];
        api.getArchiveVersionMediaImage(state.romIdentityId, sourceId, "Covers", true,
          (version.recordIds || [])[0]).then((result) => {
          if (result.ok && result.data && cover.isConnected) {
            clear(cover);
            cover.classList.remove("empty");
            cover.appendChild(h("img", { src: result.data, alt: fields.name || "Cover" }));
          }
        });
      }
      const year = String(fields.releasedate || "").match(/\d{4}/)?.[0] || "";
      const fact = (label, value) => h("span", { class: "scrape-fact",
        title: `${label}: ${value || "없음"}` }, [String(value || "")]);
      const expanded = h("div", { class: "revision-expanded", hidden: true });
      const toggle = h("button", { class: "icon-btn scrape-expand revision-expand", title: "자세히" },
        [icon("chevronDown", IC.sm)]);
      toggle.addEventListener("click", () => {
        expanded.hidden = !expanded.hidden;
        clear(toggle);
        toggle.appendChild(icon(expanded.hidden ? "chevronDown" : "chevronUp", IC.sm));
        toggle.title = expanded.hidden ? "자세히" : "접기";
      });
      box.appendChild(h("div", { class: "scrape-candidate-head" }, [cover,
        h("div", { class: "scrape-candidate-main" }, [
          h("div", { class: "scrape-candidate-top" }, [
            h("span", { class: "scrape-system-icon" }, [systemIcon(state.system, 16)]),
            h("span", { class: "scrape-candidate-title", title: fields.name || "" },
              [fields.name || state.filename || "제목 없음"]),
            (version.recordIds || []).includes(preferredId)
              ? h("span", { class: "revision-badge" }, ["PREFERRED"]) : null,
          ]),
          h("div", { class: "scrape-candidate-desc", title: fields.desc || "" },
            [String(fields.desc || "설명 없음").replace(/\s+/g, " ")]),
          h("div", { class: "scrape-candidate-facts" }, [
            h("div", { class: "scrape-fact-row" }, [
              fact("연도", year), fact("개발", fields.developer),
              fact("장르", fields.genre), toggle,
            ]),
          ]),
        ]),
      ]));
      box.appendChild(h("div", { class: "revision-foot" }, [
        h("span", { class: "revision-source truncate", title: source }, [source]),
        h("span", { class: "revision-when" }, [revisionWhen(version.updatedAt)]),
      ]));

      // 제목은 늘 보여준다(무엇에 대한 판인지 알아야 한다). 나머지는 갈리는 것만.
      const rows = h("div", { class: "revision-fields" });
      REVISION_FIELDS.forEach(([key, label]) => {
        if (key !== "name" && !differing.has(key)) return;
        const value = String(fields[key] || "").trim();
        rows.appendChild(h("div", { class: "revision-field" + (differing.has(key) ? " changed" : "") }, [
          h("span", { class: "revision-field-label" }, [label]),
          h("span", { class: "revision-field-value" }, [value || "(없음)"]),
        ]));
      });
      expanded.appendChild(rows);

      if (mediaTypes.length) {
        const chips = h("div", { class: "revision-media" });
        mediaTypes.forEach((type) => {
          const size = (version.media || {})[type];
          chips.appendChild(h("span", {
            class: "revision-chip" + (size == null ? " off" : "")
              + (mediaDiffering.has(type) ? " changed" : ""),
            title: size == null ? `${type} 없음` : `${type} ${formatBytes(size)}`,
          }, [MEDIA_LABEL[type] || type]));
        });
        expanded.appendChild(chips);
      }
      box.appendChild(expanded);

      body.appendChild(box);
    });
    body.appendChild(h("div", { class: "revision-actions" }, [
      preferredId != null ? h("button", { class: "btn compact", onClick: () =>
        togglePreferredRevision({ recordId: preferredId }, true) }, ["선택 해제"]) : null,
      choose,
    ]));
  }

  async function togglePreferredRevision(source, chosen) {
    const state = S.detailState;
    if (!state || source.recordId == null) return;
    const r = chosen
      ? await api.archiveClearPreferred(state.romIdentityId)
      : await api.archiveSetPreferred(state.romIdentityId, source.recordId);
    if (!r.ok) { showToast(r.error, "error"); return; }
    // **다시 읽는다** - 고른 버전의 값과 그림이 실제로 화면에 반영되어야 한다(실사용 피드백 -
    // "한 version을 선택해도 바뀌는 것이 없다"). 목록의 [n] 뱃지도 함께 사라진다.
    const detail = await api.archiveDetail(state.romIdentityId);
    if (detail.ok && S.detailState === state) {
      S.detailState = archiveDetailState(detail.data, state.tab);
    } else {
      state.preferredRecordId = chosen ? null : source.recordId;
    }
    delete S.matchCounts[state.romUid];
    renderDetailPanel();
    await refreshArchiveRows([state.romIdentityId]);
    showToast(chosen ? "우선 버전을 해제했습니다. 가장 최근 판을 씁니다."
                     : "이 버전을 우선 사용합니다.");
  }

  function renderRomTab(body) {
    const state = S.detailState;
    const rows = [
      ["파일명", state.file],
      ["System", String(state.system).toUpperCase()],
      ["크기", state.size ? formatBytes(state.size) : "-"],
      ["ROM 파일", state.present ? "있음" : "없음 (metadata만 존재)"],
      ...(state.archive ? [["보관 방식", OWNERSHIP_LABEL[state.ownership?.rom?.mode] || "파일 없음"]] : []),
      ["SHA256", state.sha256 || "계산 안 됨"],
    ];
    const box = h("div", { class: "rom-info" });
    rows.forEach(([label, value]) => {
      box.appendChild(h("div", { class: "health-row" }, [
        h("span", {}, [label]), h("span", { class: "truncate" }, [value])]));
    });
    body.appendChild(box);
    body.appendChild(romCoreSection(state));
  }

  /** ROM 탭의 RetroArch Core 선택(사용자 결정 - Detail 머리의 옵션 버튼과 대화상자 대신, 비어 있던
   * ROM 탭에 둔다). 실행 실패로 Core를 물어야 할 때는 여전히 대화상자(openCoreDialog)를 쓴다 -
   * 저장한 뒤 이어서 실행해야 하기 때문이다. */
  function romCoreSection(state) {
    const section = h("div", { class: "rom-core" }, [h("div", { class: "rom-core-title" }, ["RetroArch Core"])]);
    const target = { romUid: state.romUid, system: state.system, file: state.file, present: state.present };
    if (!retroarchVerified(state.system)) section.appendChild(h("div", { class: "rom-core-note" },
      ["이 System의 실행은 아직 검증되지 않았습니다. 선택한 Core로 실행할 수 있습니다."]));
    const blocked = launchBlockReason(target);
    if (blocked) {
      section.appendChild(h("div", { class: "rom-core-note" }, [blocked]));
      return section;
    }
    const content = h("div", { class: "rom-core-body" }, [h("div", { class: "rom-core-note" }, ["불러오는 중…"])]);
    section.appendChild(content);
    const collectionId = launchTargetId();
    const draw = async () => {
      const info = await api.retroarchGameInfo(collectionId, state.romUid);
      // 그 사이 다른 게임이나 탭으로 넘어갔으면 그리지 않는다.
      if (S.detailState !== state || launchTargetId() !== collectionId) return;
      clear(content);
      if (!info.ok) { content.appendChild(h("div", { class: "rom-core-note" }, [info.error])); return; }
      const d = info.data;
      if (!d.cores.length) {
        content.appendChild(h("div", { class: "rom-core-note" }, ["Core 폴더가 없거나 비어 있습니다."]));
        content.appendChild(h("button", { class: "btn compact rom-core-settings", onClick: () => openSettings("emulator") },
          ["Settings > Emulator 열기"]));
        return;
      }
      const system = String(d.system).toUpperCase();
      const select = h("select", { class: "field-input core-select" }, [
        h("option", { value: "" }, ["Core를 고르세요"]),
        ...d.cores.map((core) => h("option", { value: core }, [`${coreLabel(core)}  (${core})`])),
      ]);
      select.value = d.gameCore || d.systemCore || "";
      const scopeName = `rom-core-scope-${state.romUid}`;
      const sysRadio = h("input", { type: "radio", name: scopeName, class: "core-scope-system" });
      const gameRadio = h("input", { type: "radio", name: scopeName, class: "core-scope-game" });
      if (d.gameCore) gameRadio.checked = true; else sysRadio.checked = true;
      const save = h("button", { class: "btn primary compact core-save" }, ["저장"]);
      save.addEventListener("click", async () => {
        if (!select.value) { showToast("Core를 고르세요.", "warning"); return; }
        const forGame = gameRadio.checked;
        const r = forGame
          ? await api.setGameCore(d.system, d.file, select.value)
          : await api.setSystemCore(d.system, select.value);
        if (!r.ok) { showToast(r.error, "error"); return; }
        showToast(forGame ? "이 게임의 Core를 지정했습니다." : `${system} 기본 Core를 저장했습니다.`);
        draw();
      });
      const current = (label, value) => h("div", { class: "health-row" }, [h("span", {}, [label]), h("span", { class: "truncate" }, [value])]);
      content.appendChild(current(`${system} 기본값`, d.systemCore ? coreLabel(d.systemCore) : "없음"));
      content.appendChild(current("이 게임 지정", d.gameCore ? coreLabel(d.gameCore) : "없음 (System 기본값 사용)"));
      content.appendChild(select);
      content.appendChild(h("label", { class: "core-scope" }, [sysRadio, h("span", {}, [`${system} 전체의 기본값으로 저장`])]));
      content.appendChild(h("label", { class: "core-scope" }, [gameRadio, h("span", {}, ["이 게임에만 지정"])]));
      content.appendChild(h("div", { class: "rom-core-actions" }, [
        d.gameCore ? h("button", { class: "btn compact core-clear", onClick: async () => {
          const r = await api.setGameCore(d.system, d.file, null);
          if (!r.ok) { showToast(r.error, "error"); return; }
          showToast("이 게임의 Core 지정을 지웠습니다 - System 기본값으로 실행됩니다.");
          draw();
        } }, ["게임 지정 해제"]) : null,
        save,
      ]));
    };
    draw();
    return section;
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
      await refreshArchiveRows([state.romIdentityId]);
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
    await refreshPlan();
  }

  // ------------------------------------------------------------------
  // Plan
  // ------------------------------------------------------------------
  async function refreshPlan() {
    if (!S.activeId) { S.plan = null; S.lastPasteUndoId = null; renderStatusBar(); return; }
    const collectionId = S.activeId;
    const r = await api.operationState(isArchive() ? "__archive__" : collectionId);
    // 늦게 온 이전 Collection의 Plan은 버린다. 이게 없으면 A -> B로 빠르게 옮겼을 때
    // A의 응답이 나중에 도착해 S.plan이 A의 것이 되고, 툴바는 A의 건수를 보여주면서
    // Apply는 B에 걸린다 - 사용자가 보는 숫자와 눌렀을 때 벌어지는 일이 달라진다.
    if (S.activeId !== collectionId) return;
    S.plan = r.ok ? r.data : null;
    S.lastPasteUndoId = S.plan?.undoOperationId || null;
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
  function renameSelectedGame(row) {
    if (!row || isCompare()) return;
    const input = h("input", { class: "input", value: row.file });
    const apply = async () => {
      const started = await api.renameGame(isArchive() ? "__archive__" : S.activeId, row.romUid, input.value);
      if (!started.ok) { showToast(started.error, "error"); return; }
      closeModal();
      const result = await pollJob(started.data.jobId, "이름 변경 중");
      if (!result.ok) { showToast(result.error, "error"); return; }
      S.lastPasteUndoId = result.data.undoOperationId;
      resetList(); await reloadList(); await refreshPlan();
      const query = {systems: [row.system], search: result.data.filename, limit: 100};
      const rows = isArchive() ? await api.archiveRows(query) : await api.listRows(S.activeId, query);
      const renamed = rows.ok && rows.data.rows.find(item => item.file === result.data.filename);
      if (renamed) { S.selected = new Set([renamed.romUid]); await openDetail(renamed); }
      showToast("이름을 변경했습니다.", "success");
    };
    input.addEventListener("keydown", event => { if (event.key === "Enter") apply(); });
    showModal("이름 변경", h("div", {class: "modal-body"}, [input]), [
      h("button", {class: "btn", onClick: closeModal}, ["취소"]),
      h("button", {class: "btn primary", onClick: apply}, ["변경"]),
    ]);
    input.focus(); input.setSelectionRange(0, row.file.lastIndexOf(".") > 0 ? row.file.lastIndexOf(".") : row.file.length);
  }

  async function cutSelectedRows() {
    if (isCompare() || !S.selected.size) return;
    const result = await api.cutSelection(isArchive() ? "__archive__" : S.activeId, [...S.selected]);
    if (!result.ok) { showToast(result.error, "error"); return; }
    showToast(`${formatCount(result.data.count)}개 잘라냈습니다. 대상 System에서 붙여넣으세요.`);
  }

  async function copySelectedRows() {
    if (blockedInCompare("복사")) return;
    if (!S.selected.size) { showToast("복사할 항목을 선택하세요.", "warning"); return; }
    const r = isArchive()
      ? await api.archiveCopySelection([...S.selected])
      : await api.copySelection(S.activeId, [...S.selected]);
    if (!r.ok) { showToast(r.error, "error"); return; }
    showToast(`${formatCount(r.data.count)}개 복사했습니다. 대상 System/Collection에서 Ctrl+V로 붙여넣으세요.`);
  }

  /** `targetRow`를 주면 클립보드 항목(정확히 하나여야 한다)을 **그 행에 지목해서** 붙인다 -
   * 파일명이 서로 달라 자동 매칭(System+파일명)이 닿지 않는 두 게임을 사람이 직접 이을 때 쓴다
   * (실사용 버그 리포트 - "Replace로 다른 이름의 게임에 덮어썼는데 결과가 똑같다": 원인은
   * 이 경로가 없어서, 평범한 Ctrl+V가 **복사한 항목 자신의 자리**에 조용히 다시 채워지고
   * 실제로 고르려던 대상 행은 전혀 건드리지 못했던 것이다). */
  async function pasteClipboard(targetRow, targetSystem = null, targetPreview = null, mode = "overwrite") {
    if (blockedInCompare("붙여넣기")) return;
    if (isArchive()) {
      const scope = activeScope();
      const destinationSystem = targetSystem || (!targetRow && scope.kind === "system" ? scope.id : null);
      const r = await api.archivePaste(mode,
        targetRow?.romIdentityId || targetRow?.romUid || null,
        destinationSystem, false, true);
      if (!r.ok) { showToast(r.error, "error"); return; }
      const d = r.data || {};
      if (d.operationId) {
        if (d.collisions?.length) openPasteConflictDialog(d);
        else await executePasteOperation(d, {});
        return;
      }
      await reloadList();
      if (targetRow && S.detailState?.archive) {
        const detail = await api.archiveDetail(targetRow.romIdentityId || targetRow.romUid);
        if (detail.ok && detail.data) {
          S.detailState = archiveDetailState(detail.data, S.detailState.tab);
          renderDetailPanel();
        }
      }
      showToast(`Archive에 ${formatCount(d.pasted || 0)}개를 붙여넣었습니다.`
        + ((d.copiedRoms || 0) ? ` ROM ${formatCount(d.copiedRoms)}개를 보관 폴더로 복사했습니다.` : "")
        + ((d.conflicts || []).length ? ` 기존 ROM ${formatCount(d.conflicts.length)}개는 덮어쓰지 않았습니다.` : "")
        + ((d.skipped || []).length ? ` 건너뜀 ${formatCount(d.skipped.length)}개: ${d.skipped[0].reason || "사유 없음"}.` : ""),
        (d.conflicts || []).length || (d.skipped || []).length ? "warning" : "success");
      return;
    }
    let systemMap = {};
    let targetMap = null;
    if (targetSystem) {
      if (!targetPreview?.items?.length) return;
      systemMap = Object.fromEntries(targetPreview.items.map((item) => [item.system, targetSystem]));
    } else if (targetRow) {
      const clip = await api.clipboardItems();
      if (!clip.ok) { showToast(clip.error, "error"); return; }
      if (clip.data.count !== 1) {
        showToast("항목을 하나만 복사했을 때만 이 항목에 붙여넣을 수 있습니다.", "warning");
        return;
      }
      const item = clip.data.items[0];
      targetMap = { [`${item.system}|${item.filename}`]: `${targetRow.system}|${targetRow.file}` };
    } else {
      // 이 Collection에 없는 System이 섞여 있으면 **어디로 붙일지 먼저 묻는다**(사용자 결정).
      // 묻지 않으면 `FBNEO ACT` 같은 이름이 ES-DE에 그대로 만들어져 Frontend가 못 읽는다.
      systemMap = await askPasteSystemMap();
      if (systemMap === null) return;                     // 사용자가 취소했다
    }
    // **고른 행이 하나면 그 행을 대상 후보로 함께 보낸다**(사용자 모델 - "행을 고르고
    // 붙여넣으면 그 행에 붙는다"). 백엔드는 이름으로 확실한 대상을 못 찾았을 때만 이걸 쓴다.
    // 이게 없으면 이름이 전혀 다른 두 게임(`FF7.zip` <-> `ff7.rom`)은 대상을 골라 놓고
    // 붙여넣어도 닿지 않았다.
    const fallback = !targetRow && !targetSystem && S.selected.size === 1 ? selectedRowKey() : null;
    const r = await api.paste(S.activeId, mode, systemMap, targetMap, fallback,
      false, true);
    if (!r.ok) { showToast(r.error, "error"); return; }
    const d = r.data;
    if (d.operationId) {
      if (d.collisions?.length) openPasteConflictDialog(d);
      else await executePasteOperation(d, {});
      return;
    }
    const left = (d.skipped || []).filter((item) => item.reason);
    showToast(left.length ? `붙여넣을 내용이 없습니다 - ${left[0].reason}`
      : "작업 미리보기를 받지 못했습니다. 다시 시도하세요.", "warning");
  }

  async function acceptOperationPreview(preview) {
    if (!preview.operationId) { showToast("작업 미리보기를 받지 못했습니다.", "error"); return; }
    if (preview.collisions?.length) openPasteConflictDialog(preview);
    else await executePasteOperation(preview, {});
  }

  async function runCompareOperation(options) {
    const response = await api.compareOperationPreview(options);
    if (!response.ok) { showToast(response.error, "error"); return; }
    if (!response.data.count) { showToast(response.data.skipped?.[0]?.reason || "적용할 변경이 없습니다.", "warning"); return; }
    if (response.data.collisions?.length) openPasteConflictDialog(response.data);
    else await executePasteOperation(response.data, {});
  }

  async function runImmediateAction(action, options) {
    const response = await api.operationPreview(S.activeId, action, options);
    if (!response.ok) { showToast(response.error, "error"); return; }
    if (!response.data.count) { showToast(response.data.skipped?.[0]?.reason || "변경할 항목이 없습니다."); return; }
    if (response.data.collisions?.length) openPasteConflictDialog(response.data);
    else await executePasteOperation(response.data, {});
  }

  async function executePasteOperation(preview, decisions, acknowledged = false) {
    const operationLabel = ({ title: "제목 변경", disc: "디스크 태그 변경", move: "이동",
      storage: "Storage 이동", media: "미디어 붙여넣기", compare: "비교 결과 적용", convert: "변환", import: "가져오기", "archive-import": "가져오기" })[preview.action] || "붙여넣기";
    if (!preview.undoable && !acknowledged) {
      showConfirm(`${operationLabel} 확인`,
        preview.target === "archive"
          ? "마스터에는 변경 이력이 남지만 파일 전체 되돌리기는 아직 보장하지 못합니다. 계속할까요?"
          : "이 작업은 자동 되돌리기를 보장할 수 없습니다. 계속할까요?",
        true, () => executePasteOperation(preview, decisions, true));
      return;
    }
    const collectionId = S.activeId;
    const compareSnapshot = preview.action === "compare" ? S.compare : null;
    const focused = S.focused == null ? null : rowByUid(S.focused);
    const focusedKey = focused ? `${focused.system}|${focused.file}` : null;
    const started = await api.pasteExecute(preview.operationId, decisions, acknowledged);
    if (!started.ok) { showToast(started.error, "error"); return; }
    if (!started.data.jobId) { showToast("건너뛴 항목 외에 붙여넣을 내용이 없습니다."); return; }
    const result = await pollJob(started.data.jobId, `${operationLabel} 중`);
    if (!result.ok) { showToast(result.error || "붙여넣기가 중단되었습니다.", "error"); return; }
    const data = result.data || {};
    if (data.undoOperationId) S.lastPasteUndoId = data.undoOperationId;
    showToast((data.rolledBack ? `${operationLabel}에 실패해 변경을 복구했습니다.` : `${operationLabel} ${formatCount(data.applied || 0)}개`)
      + (data.failed ? ` · 실패 ${formatCount(data.failed)}개` : "")
      + (data.partial ? ` · 일부 반영 ${formatCount(data.partial)}개` : ""),
    data.failed || data.partial ? "warning" : "success");
    if (S.activeId !== collectionId) return;
    if (compareSnapshot) {
      const updated = await api.startCompare(compareSnapshot.baseId || S.compareBase,
        compareSnapshot.otherId);
      if (updated.ok) { S.compare = updated.data; resetList(); await reloadList(); renderAll(); }
      else showToast(updated.error, "warning");
      return;
    }
    resetList();
    await reloadList();
    if (focusedKey) {
      const [system, file] = focusedKey.split(/\|(.*)/s);
      const query = { systems: [system], search: file, limit: 100, offset: 0 };
      const found = preview.target === "archive"
        ? await api.archiveRows(query) : await api.listRows(collectionId, query);
      const row = found.ok && (found.data.rows || []).find((item) =>
        item.system === system && item.file === file);
      if (row) {
        S.selected = new Set([row.romUid]);
        S.selectAnchor = row.romUid;
        await openDetail(row);
      }
    }
    await refreshPlan();
  }

  async function undoLastPaste() {
    if (!S.activeId) return;
    const collectionId = S.activeId;
    const focused = S.focused == null ? null : rowByUid(S.focused);
    const focusedKey = focused ? {system: focused.system, file: focused.file} : null;
    const started = await api.pasteUndo(isArchive() ? "__archive__" : collectionId);
    if (!started.ok) { showToast(started.error, "warning"); return; }
    const result = await pollJob(started.data.jobId, "작업 되돌리는 중");
    if (!result.ok) { showToast(result.error, "error"); return; }
    S.lastPasteUndoId = null;
    if (S.activeId === collectionId) {
      resetList();
      await reloadList();
      if (focusedKey) {
        const query = {systems: [focusedKey.system], search: focusedKey.file, limit: 100, offset: 0};
        const found = collectionId === ARCHIVE_ID
          ? await api.archiveRows(query) : await api.listRows(collectionId, query);
        const row = found.ok && (found.data.rows || []).find((item) =>
          item.system === focusedKey.system && item.file === focusedKey.file);
        if (row && S.activeId === collectionId) {
          S.selected = new Set([row.romUid]);
          S.selectAnchor = row.romUid;
          await openDetail(row);
        }
      }
    }
    showToast("직전 작업을 되돌렸습니다.", "success");
    await refreshPlan();
  }

  async function redoLastOperation() {
    const activeId = S.activeId;
    const focused = S.focused == null ? null : rowByUid(S.focused);
    const key = focused ? {system: focused.system, file: focused.file} : null;
    const id = isArchive() ? "__archive__" : S.activeId;
    const started = await api.pasteRedo(id);
    if (!started.ok) { showToast(started.error, "warning"); return; }
    const result = await pollJob(started.data.jobId, "다시 실행 중");
    if (!result.ok) { showToast(result.error, "error"); return; }
    if (S.activeId !== activeId) return;
    resetList(); await reloadList(); await refreshPlan();
    if (key) {
      const query = {systems:[key.system], search:key.file, limit:100, offset:0};
      const found = id === "__archive__" ? await api.archiveRows(query) : await api.listRows(id, query);
      const row = found.ok && (found.data.rows || []).find(item => item.system === key.system && item.file === key.file);
      if (row && S.activeId === activeId) {
        S.selected = new Set([row.romUid]); S.selectAnchor = row.romUid;
        await openDetail(row);
      }
    }
    showToast("작업을 다시 실행했습니다.", "success");
  }

  async function openOperationHistory() {
    const id = isArchive() ? "__archive__" : S.activeId;
    const result = await api.operationHistory(id);
    if (!result.ok) { showToast(result.error, "error"); return; }
    const rows = result.data.items || [];
    const labels = {committed: "완료", undone: "실행 취소", recovered: "복구됨", running: "복구 필요", restoring: "복구 필요", redoing: "복구 필요"};
    const actions = {paste: "붙여넣기", add: "붙여넣기", delete: "삭제", rename: "이름 변경", move: "이동", metadata_edit: "메타데이터 편집", "file-operation": "파일 작업", archive_edit: "메타데이터 편집", archive_rename: "이름 변경", archive_rom_delete: "ROM 삭제", archive_delete: "기록 삭제"};
    const body = h("div", {class: "modal-body"});
    if (result.data.recoveryError) body.appendChild(h("div", {class: "field-help"}, [result.data.recoveryError]));
    body.appendChild(h("div", {class: "field-help"}, [`${rows.length}개 · 백업 ${formatBytes(rows.reduce((sum, row) => sum + row.bytes, 0))}`]));
    for (const row of rows) {
      body.appendChild(h("div", {class: "field-row"}, [
        h("span", {class: "field-help"}, [`${new Date(row.createdAt * 1000).toLocaleString()} · ${actions[row.action] || "Archive 편집"} · ${labels[row.status] || row.status} · ${formatBytes(row.bytes)}`]),
        h("button", {class: "btn", disabled: !row.canDiscard, onClick: () => {
          showConfirm("백업 삭제", "이 작업의 실행 취소·다시 실행이 불가능해집니다.", true, async () => {
            const removed = await api.discardOperationHistory(id, [row.id], true);
            if (!removed.ok) { showToast(removed.error, "error"); return; }
            closeModal(); await refreshPlan(); await openOperationHistory();
          });
        }}, ["백업 삭제"]),
      ]));
    }
    showModal("작업 기록", body, [h("button", {class: "btn", onClick: closeModal}, ["닫기"])]);
  }

  function openPasteConflictDialog(preview) {
    const collisions = preview.collisions || [];
    const decisions = {};
    let position = 0;
    const body = h("div", { class: "modal-body paste-conflict-body" });
    const applyRemaining = h("input", { type: "checkbox" });
    const render = () => {
      clear(body);
      const item = collisions[position];
      if (!item) return;
      body.appendChild(h("div", { class: "modal-hint" }, [
        `${preview.source || "원본"}에서 ${preview.target === "archive" ? "마스터" : "현재 Collection"}로 ${formatCount(preview.count)}개 복사 예정`
        + ` (${formatCount(collisions.length)}건 충돌) · ${position + 1}/${collisions.length}`,
      ]));
      body.appendChild(h("div", { class: "paste-conflict-filename" },
        [`대상 게임 ${item.filename}이(가) 이미 있습니다.`]));
      const makeSide = (label, title, desc, fields, incoming) => {
        const cover = h("img", { alt: "커버", class: "paste-conflict-thumb" });
        const screen = h("img", { alt: "스크린샷", class: "paste-conflict-thumb" });
        const detailCover = h("img", { alt: "커버", class: "scrape-thumb" });
        [cover, screen, detailCover].forEach((image) => { image.style.visibility = "hidden"; });
        const facts = [fields?.developer, fields?.publisher, fields?.genre, fields?.region,
          String(fields?.releasedate || "").match(/\d{4}/)?.[0], fields?.rating,
          fields?.players].filter(Boolean).slice(0, 5);
        const expanded = h("div", { class: "paste-conflict-expanded scrape-candidate" }, [
          h("div", { class: "scrape-candidate-head" }, [
            detailCover,
            h("div", { class: "scrape-candidate-main" }, [
              h("span", { class: "scrape-candidate-title" }, [title]),
              h("span", { class: "scrape-candidate-desc" }, [desc || "설명 없음"]),
              h("div", { class: "scrape-candidate-facts" }, [
                h("div", { class: "scrape-fact-row" },
                  facts.map((value) => h("span", { class: "scrape-fact", title: String(value) },
                    [String(value)]))),
              ]),
            ]),
          ]),
        ]);
        const toggle = h("button", { class: "btn compact paste-conflict-expand",
          title: "자세히 보기", "aria-expanded": "false" }, [icon("chevronDown", IC.sm)]);
        toggle.addEventListener("click", () => {
          const open = expanded.classList.toggle("open");
          toggle.setAttribute("aria-expanded", String(open));
        });
        const row = h("div", { class: "paste-conflict-side", title: desc || title }, [
          h("span", { class: "paste-conflict-side-label" }, [label]),
          h("span", { class: "paste-conflict-side-title truncate" }, [title]),
          cover, screen, toggle, expanded,
        ]);
        for (const [type, image] of [["covers", cover], ["screenshots", screen]]) {
          const request = incoming
            ? api.pastePreviewMedia(preview.operationId, item.key, type)
            : preview.target === "archive"
              ? api.getArchiveMediaImage(item.existingRomUid,
                type === "covers" ? "Covers" : "Screenshots", true)
              : api.getMediaImage(S.activeId, item.existingRomUid,
                type === "covers" ? "Covers" : "Screenshots", true);
          request.then((result) => {
            if (result.ok && result.data && row.isConnected) {
              image.src = result.data;
              image.style.visibility = "visible";
              if (type === "covers") {
                detailCover.src = result.data;
                detailCover.style.visibility = "visible";
              }
            }
            else image.classList.add("empty");
          });
        }
        return row;
      };
      body.appendChild(makeSide("기존", item.existingTitle,
        item.existingDescription, item.existingFields, false));
      body.appendChild(makeSide("대상", item.incomingTitle,
        item.incomingDescription, item.incomingFields, true));
      const checkbox = h("label", { class: "paste-conflict-remaining" }, [
        applyRemaining, h("span", {}, ["남은 충돌에 모두 적용"]),
      ]);
      body.appendChild(checkbox);
    };
    const choose = async (choice) => {
      decisions[collisions[position].key] = choice;
      if (applyRemaining.checked) {
        collisions.slice(position + 1).forEach((item) => { decisions[item.key] = choice; });
        closeModal();
        await executePasteOperation(preview, decisions);
        return;
      }
      position += 1;
      if (position >= collisions.length) {
        closeModal();
        await executePasteOperation(preview, decisions);
      } else render();
    };
    render();
    const card = showModal("같은 이름의 게임", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn", onClick: () => choose("skip") }, ["이 게임 건너뛰기"]),
      h("button", { class: "btn primary", onClick: () => choose("overwrite") },
        ["기존 게임 덮어쓰기"]),
    ]);
    card.classList.add("paste-conflict-card");
  }

  /** 붙여넣기 전에 System 이름을 맞춘다. 반환: {원본:대상} 또는 취소면 null, 물을 것이 없으면 {}.
   *
   * Frontend마다 허용하는 System 이름이 다르다(사용자 피드백 - Pegasus의 `FBNEO ACT`는 ES-DE에 없다).
   * 이 Collection에 없는 System만 묻는다 - 있는 것은 물을 이유가 없다. */
  async function askPasteSystemMap() {
    const info = await api.clipboardSystems(S.activeId);
    if (!info.ok) return {};                              // 알 수 없으면 예전처럼 그대로 붙인다
    const missing = (info.data.systems || []).filter((s) => !s.exists);
    if (!missing.length) return {};
    const targets = info.data.targetSystems || [];
    return new Promise((resolve) => {
      let settled = false;
      const done = (value) => { if (!settled) { settled = true; resolve(value); } };
      const selects = missing.map((entry) => {
        const select = h("select", { class: "field-input paste-system-select", "data-system": entry.system }, [
          // 원본 이름 그대로 쓰면 그 이름의 System이 새로 생긴다.
          h("option", { value: "" }, [`새 System으로 만들기 (${entry.system})`]),
          ...targets.map((name) => h("option", { value: name }, [name.toUpperCase()])),
        ]);
        return { entry, select };
      });
      const body = h("div", { class: "modal-body paste-system-map" }, [
        h("div", { class: "modal-text" }, [
          `이 Collection에 없는 System이 ${formatCount(missing.length)}개 있습니다. 어디로 붙일지 고르세요.`]),
        h("div", { class: "modal-hint" }, [
          "Frontend마다 쓸 수 있는 System 이름이 다릅니다. 기존 System을 고르면 그 폴더로 들어갑니다."]),
        ...selects.map(({ entry, select }) => h("div", { class: "paste-system-row" }, [
          h("div", { class: "field-label" }, [`${entry.system} · ${formatCount(entry.count)}개`]),
          select,
        ])),
      ]);
      showModal("붙여넣을 System 고르기", body, [
        h("button", { class: "btn", onClick: () => { closeModal(); done(null); } }, ["취소"]),
        h("button", { class: "btn primary paste-system-ok", onClick: () => {
          const map = {};
          selects.forEach(({ entry, select }) => { if (select.value) map[entry.system] = select.value; });
          closeModal();
          done(map);
        } }, ["붙여넣기"]),
      ]);
    });
  }

  //: 삭제할 수 있는 부분과 그 이름(사용자 결정 - 무엇이 지워지는지 메뉴에서 알 수 있어야 한다).
  const DELETE_PART_LABEL = { rom: "ROM", metadata: "메타데이터", media: "미디어", video: "영상" };
  //: 우클릭 메뉴의 세 가지 삭제. "메타데이터 삭제"는 gamelist 항목과 미디어(영상 포함)를 함께 지운다.
  const DELETE_ALL = ["rom", "metadata", "media", "video"];
  const DELETE_META_AND_MEDIA = ["metadata", "media", "video"];

  async function deleteArchiveMetadata() {
    const ids = [...S.selected];
    if (!ids.length) return;
    showConfirm("Archive 메타데이터 삭제",
      `선택한 ${formatCount(ids.length)}개 항목의 Archive 메타데이터를 지웁니다. `
      + "ROM·미디어·원본 Collection과 출처 Revision은 유지합니다.", true, async () => {
        const r = await api.archiveMetadataDelete(ids);
        if (!r.ok) { showToast(r.error, "error"); return; }
        resetList();
        await reloadList();
        if (S.detailState?.archive && ids.map(String).includes(String(S.detailState.romIdentityId))) {
          const detail = await api.archiveDetail(S.detailState.romIdentityId);
          if (detail.ok && detail.data) {
            S.detailState = archiveDetailState(detail.data, S.detailState.tab);
            renderDetailPanel();
          }
        }
        const failed = (r.data.failures || []).length;
        showToast(`Archive 메타데이터 ${formatCount(r.data.cleared || 0)}개를 지웠습니다.`
          + (failed ? ` 실패 ${formatCount(failed)}개.` : ""), failed ? "warning" : "success");
      });
  }

  async function deleteArchiveOwnedGames() {
    const ids = [...S.selected];
    if (!ids.length) return;
    showConfirm("Archive Game 전체 삭제",
      `Archive가 보관하는 ${formatCount(ids.length)}개 게임의 ROM·미디어 파일과 기록을 삭제합니다. `
      + "외부 원본에 연결된 게임은 이 동작으로 삭제할 수 없습니다.", true, async () => {
        const r = await api.archiveDeleteOwned(ids);
        if (!r.ok) { showToast(r.error, "error"); return; }
        const failures = r.data.failures || [];
        S.selected.clear();
        resetList();
        await reloadList();
        showToast(`Archive Game ${formatCount(r.data.deleted || 0)}개를 삭제했습니다.`
          + (failures.length ? ` 실패 ${formatCount(failures.length)}개: ${failures[0].reason}` : ""),
        failures.length ? "warning" : "success");
      });
  }

  async function deleteArchiveOwnedRoms() {
    if (blockedInCompare("ROM 삭제")) return;
    const ids = [...S.selected];
    if (!ids.length) return;
    showConfirm("Archive 보관 ROM 삭제",
      `선택한 ${formatCount(ids.length)}개 항목에서 Archive ROM 디렉토리 안의 파일만 삭제합니다. `
      + "외부 Collection의 원본 연결은 그대로 유지합니다.", true, async () => {
        const r = await api.archiveRomDelete(ids);
        if (!r.ok) { showToast(r.error, "error"); return; }
        const result = r.data || {};
        await reloadList();
        if (S.detailState?.archive && ids.map(String).includes(String(S.detailState.romIdentityId))) {
          const detail = await api.archiveDetail(S.detailState.romIdentityId);
          if (detail.ok && detail.data) {
            S.detailState = archiveDetailState(detail.data, S.detailState.tab);
            renderDetailPanel();
          }
        }
        const kept = result.linkedSourcesKept || 0;
        const failed = (result.failures || []).length;
        showToast(`Archive 보관 ROM ${formatCount(result.deletedFiles || 0)}개를 삭제했습니다.`
          + (kept ? ` 원본 연결 ${formatCount(kept)}개는 유지했습니다.` : "")
          + (failed ? ` 실패 ${formatCount(failed)}개.` : ""), failed ? "warning" : "success");
      });
  }

  /** `parts`를 지운다(정하지 않으면 전부). 무엇이 지워지는지 확인창과 토스트가 그대로 말한다. */
  async function deleteSelection(parts, permanent = false) {
    if (blockedInCompare("삭제")) return;
    if (!S.selected.size) { showToast("삭제할 항목을 선택하세요.", "warning"); return; }
    const count = S.selected.size;
    // Archive는 Plan을 거치지 않는다(D1 - 파일이 안 움직인다, Metadata 편집과 같은 자리에서
    // 바로 지운다). 예전엔 여기서 Collection용 planDelete(S.activeId=…)를 그대로 불러
    // "Collection을 찾을 수 없습니다"로 매번 죽었다(실사용 버그 리포트 - "삭제가
    // 구조적으로 안 되냐"). 실제 ROM/Media 파일은 지우지 않는다(§37) - Archive의 기록만
    // 지운다.
    if (isArchive()) {
      const ids = [...S.selected];
      const run = async () => {
        const r = await api.archiveDelete(ids);
        if (!r.ok) { showToast(r.error, "error"); return; }
        S.selected.clear();
        resetList();
        await reloadList();
        showToast(`Archive에서 ${formatCount(r.data.deleted)}개를 지웠습니다 - 실제 ROM/Media 파일은 그대로입니다.`);
      };
      showConfirm("Archive에서 지우기",
        `${formatCount(count)}개를 Archive에서 지웁니다. 실제 ROM/Media 파일은 지워지지 않습니다 - `
        + "필요하면 해당 Collection에서 다시 수집할 수 있습니다.", true, run);
      return;
    }
    const chosen = Array.isArray(parts) && parts.length ? parts : DELETE_ALL;
    const what = chosen.map((p) => DELETE_PART_LABEL[p]).join(" + ");
    const collectionId = S.activeId;
    const ids = [...S.selected];
    const run = async (force = false) => {
      const r = await api.deleteImmediate(collectionId, ids, chosen, force);
      if (!r.ok) { showToast(r.error, "error"); return; }
      if (r.data.requiresConfirmation) {
        showConfirm("삭제 확인", formatCount(count) + "개의 " + what
          + "을(를) 영구 삭제합니다. 이 경로에서는 되돌릴 수 없습니다.", true, () => run(true));
        return;
      }
      const completed = await pollJob(r.data.jobId, "삭제하는 중");
      if (!completed.ok) { showToast(completed.error, "error"); return; }
      const result = completed.data || {};
      if (result.undoOperationId) S.lastPasteUndoId = result.undoOperationId;
      if (S.activeId !== collectionId) return;
      S.selected.clear();
      resetList();
      await reloadList();
      await refreshPlan();
      showToast(result.rolledBack ? "삭제에 실패해 변경을 복구했습니다."
        : formatCount(result.applied || 0) + "개 삭제"
          + (result.undoOperationId ? " · Ctrl+Z로 실행 취소" : ""),
      result.failed || result.partial ? "warning" : "success");
    };
    if (permanent) showConfirm("영구 삭제", formatCount(count) + "개의 " + what
      + "을(를) 영구 삭제합니다. 되돌릴 수 없습니다.", true, () => run(true));
    else await run();
  }

  /** 충돌 하나의 종류 라벨 - ROM이면 "ROM 파일", media면 그 종류(Covers 등). */
  function conflictKindLabel(conflict) {
    if (conflict.kind === "rom") return "ROM 파일";
    return MEDIA_LABEL[conflict.mediaType] || "Media";
  }

  /** 기존 파일과 가져올 파일을 나란히 보여주고, 선택한 쪽만 강조한다. */
  function conflictDetailRow(conflict, entryKey, index, choices) {
    const current = h("button", { class: "conflict-choice existing", type: "button",
      title: `현재 Collection · ${conflictKindLabel(conflict)}` });
    const incoming = h("button", { class: "conflict-choice incoming", type: "button",
      title: `가져올 파일 · ${conflictKindLabel(conflict)}` });
    const update = () => {
      current.classList.toggle("selected", choices[index] === "skip");
      incoming.classList.toggle("selected", choices[index] === "overwrite");
    };
    current.addEventListener("click", () => { choices[index] = "skip"; update(); });
    incoming.addEventListener("click", () => { choices[index] = "overwrite"; update(); });
    update();
    if (conflict.kind === "media") {
      for (const button of [current, incoming]) button.appendChild(icon("image", IC.md));
      api.planConflictPreview(S.activeId, entryKey, index).then((result) => {
        if (!result.ok || !result.data) return;
        [[current, result.data.existing], [incoming, result.data.incoming]].forEach(([button, src]) => {
          if (!src || !button.isConnected) return;
          clear(button);
          button.appendChild(h("img", { class: "conflict-thumb", src,
            alt: conflictKindLabel(conflict) }));
        });
      });
    } else {
      current.appendChild(h("span", {}, ["현재 ROM"]));
      incoming.appendChild(h("span", {}, ["가져올 ROM"]));
    }
    return h("div", { class: "conflict-preview", title: conflictKindLabel(conflict) },
      [current, incoming]);
  }



  /** 지난 Apply에서 실패해 Plan에 남은 항목을 보여준다.
   *
   * 예전엔 하단 바에 "실패 N"이라는 숫자만 있고 눌러도 아무 일도 없었다 -
   * 왜 실패했는지(예: External Storage에 같은 이름의 파일이 이미 있음) 알
   * 방법이 없어서 Apply를 눌러도 계속 실패만 반복됐다(실사용 피드백). 이유를
   * 보여주고, 재시도(다음 Apply가 자동으로 다시 시도한다)나 포기(Plan에서
   * 제거)를 고르게 한다. */




  // 파일 변경은 독립 미리보기와 작업 기록을 사용한다.

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
    // 디렉토리를 정하기 전에는 보내지 않는다(사용자 피드백) - 그 자리에서 설정 창을 띄워 준다.
    if (!(await ensureArchiveConfigured())) return;
    const scope = archiveScope();
    const label = archiveScopeLabel(scope);
    const result = await api.startArchiveIngest(S.activeId, scope);
    if (!result.ok) { showToast(result.error, "error"); return; }
    const done = await pollJob(result.data.jobId, "Archive로 보내는 중");
    if (!done.ok) { showToast(done.error, "error"); return; }
    showToast(`${label} · Archive에 저장했습니다.`);
  }

  function importParts(entry) {
    const parts = entry.parts || {};
    const labels = [];
    if (parts.metadata) labels.push("메타데이터");
    if (parts.media) labels.push(`미디어 ${formatCount(parts.media)}`);
    if (parts.rom) labels.push("ROM");
    return labels.join(" · ") || "변경";
  }

  /** 방금 가져온 항목만 보여 준다. 기존 Plan 항목과 섞어 결과를 과장하지 않는다. */


  async function importFromCollection(sourceId, targetId) {
    const scope = activeScope();
    const system = scope.kind === "system" ? scope.id : null;
    const label = system ? `${String(system).toUpperCase()} 전체` : "Collection 전체";
    await runImmediateAction("import", { sourceId, system, mode: currentPasteMode() });
  }

  /** 현재 범위에 해당하는 Archive 항목을 Plan에 담는다. */
  async function importFromArchive() {
    const scope = activeScope();
    const systems = scope.kind === "system" ? [scope.id] : null;
    const label = systems ? `${String(scope.id).toUpperCase()} 전체` : "Collection 전체";
    const uidsR = await api.archiveUids(systems);
    if (!uidsR.ok) { showToast(uidsR.error, "error"); return; }
    if (!uidsR.data.length) { showToast(`${label}에 해당하는 Archive 항목이 없습니다.`, "warning"); return; }
    await runImmediateAction("archive-import", { ids: uidsR.data, mode: currentPasteMode() });
  }

  function openSendToCollection() {
    const targets = S.tabs.filter((t) => t !== ARCHIVE_ID);
    const list = h("div", { class: "picker-list" });
    targets.forEach((id) => {
      const collection = S.collections.find((c) => c.id === id);
      if (!collection) return;
      const row = h("button", { class: "picker-row" }, [
        icon("gamepad", IC.md),
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
        "대상을 선택한 뒤 충돌을 확인하고 바로 복사합니다."]),
    ]);
    showModal("Collection으로 보내기", body, [h("button", { class: "btn", onClick: closeModal }, ["취소"])]);
  }

  async function sendToCollection(collectionId) {
    const ids = [...S.selected];
    await selectTab(collectionId);
    if (S.activeId !== collectionId) {
      return;
    }
    await runImmediateAction("archive-import", { ids, mode: currentPasteMode() });
  }

  // ------------------------------------------------------------------
  // 하단 상태 바
  // ------------------------------------------------------------------


  function renderStatusBar() {
    const bar = $("status-bar");
    const progressBar = $("job-progress");
    clear(bar);
    // 선택 개수를 다시 그리는 자리다. 툴바에서 선택에 따라 달라지는 것들(수집 대상
    // 표시, Delete 활성)도 같은 근거를 쓰므로 여기서 함께 맞춘다 - 툴바를 통째로
    // 다시 그리지 않고 그 두 곳만 고친다.
    updateSelectionDependentActions();
    const detail = activeDetail();
    const plan = S.plan;

    const right = h("div", { class: "sb-left" }, [
      icon("layoutList", IC.sm),
      h("span", {}, [`Selected ${formatCount(S.selected.size)}`]),
    ]);
    const left = h("div", { class: "sb-middle" });
    if (detail) {
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
        left.appendChild(chip);
      });
    }
    bar.appendChild(left);
    bar.appendChild(progressBar);
    bar.appendChild(right);

    const actions = h("div", { class: "sb-actions" });
    if (isCompare()) {
      // 비교 중에는 Copy/Paste/Delete/Apply를 내놓지 않는다. Paste와 Apply는 선택이
      // 없어도 눌리는 버튼이라, 두면 비교 화면에서 그대로 변경이 일어난다.
      actions.appendChild(h("span", { class: "sb-badge" }, ["읽기 전용"]));
      right.appendChild(actions);
      return;
    }
    // Archive의 "Collection으로 보내기"도 Detail 패널 상단으로 옮겼다(레이아웃
    // 재검토) - AutoPlan/Apply/Cancel/Archive에 수집/Delete와 같은 이유로,
    // 여기 그대로 두면 똑같은 버튼이 두 번 보인다.
    right.appendChild(actions);
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
      // 디렉토리가 진실이다 - 직접 넣은 ROM이나 고친 gamelist를 먼저 읽어 들인다.
      // 설정이 없으면(configured 아님) 읽을 디렉토리가 없으므로 조용히 넘어간다.
      const started = await api.startArchiveRefresh();
      if (!started.ok) { showToast(started.error, "error"); return; }
      const synced = await pollJob(started.data.jobId, "Archive 다시 읽는 중");
      if (!synced.ok) { if (!synced.cancelled) showToast(synced.error, "error"); return; }
      if (synced.data && (synced.data.added || synced.data.romsLinked || synced.data.mediaLinked)) {
        showToast(`Archive 디렉토리에서 ${synced.data.added}개 추가, ROM ${synced.data.romsLinked}개, `
          + `Media ${synced.data.mediaLinked || 0}개 연결`);
      }
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
    $("center").classList.toggle("compare-mode", isCompare());
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
        // HERO도 같은 값을 쓴다(§4) - Dashboard에서 바꾸는 순간 HERO의 그래프도
        // 바로 따라가야, "Dashboard에서는 바뀌었는데 옆에서 보면 그대로다"가 안 생긴다.
        S.dashboardTargets = { ...targets };
        if (id === S.activeId) renderHeader();
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

  //: 언어가 바뀌면 동적으로 그린 화면을 원문에서 다시 그린다(i18n.js가 부른다).
  window.__rmsRelocalize = () => { if (S.collections) renderAll(); };

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
    document.addEventListener("paste", (event) => {
      if (!S.detailState || S.detailState.compare || S.detailState.tab !== "media"
          || $("modal-root").firstChild) return;
      const tag = (event.target && event.target.tagName) || "";
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      const image = [...(event.clipboardData?.items || [])]
        .find((item) => item.kind === "file" && item.type.startsWith("image/"));
      if (!image) return;
      event.preventDefault();
      document.__rmsImagePasteHandled = true;
      importExternalMedia(externalMediaSlot, image.getAsFile());
    });
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
      if (e.key === "F5") { e.preventDefault(); if (S.activeId && !$("modal-root").firstChild) refreshActive(); return; }
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
      if ($("modal-root").firstChild) return;
      if (!S.activeId) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        const search = document.querySelector(".search-input");
        if (search) { search.focus(); search.select(); }
        return;
      }
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
      if (e.key === "F2" && !$("modal-root").firstChild && S.selected.size === 1) {
        e.preventDefault(); renameSelectedGame(rowByUid([...S.selected][0])); return;
      }
      if (e.key === "Delete" && !$("modal-root").firstChild) {
        e.preventDefault(); deleteSelection(null, e.shiftKey);
      }
      // 글자를 드래그해 골라 둔 상태면 그 글자를 복사한다(브라우저 기본 동작). 예전엔 늘
      // 게임 복사로 가로채서 Detail의 파일명 같은 글자를 복사할 수 없었다.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "x" && !hasTextSelection()) {
        e.preventDefault(); cutSelectedRows(); return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c" && !hasTextSelection()) {
        e.preventDefault(); copySelectedRows();
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") {
        if (S.detailState?.tab === "media" && !$("modal-root").firstChild) {
          // Let the paste event inspect native image clipboard data first.
          // Text and game items keep the ordinary clipboard path.
          document.__rmsImagePasteHandled = false;
          setTimeout(() => { if (!document.__rmsImagePasteHandled) pasteClipboard();
            document.__rmsImagePasteHandled = false; }, 0);
          return;
        }
        e.preventDefault(); pasteClipboard();
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z"
          && !e.target.closest("input,textarea,[contenteditable=true]")) {
        e.preventDefault(); undoLastPaste();
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
        e.preventDefault(); redoLastOperation();
      }
    });
  }

  async function init() {
    bindEvents();
    await loadWindowInfo();
    await loadAppSettings();
    await loadRetroarchState();
    await loadCollections();
    await loadArchiveConfigured();
    renderAll();
    // Collection이 하나도 없어도 선택을 강요하지 않는다 - 빈 메인 화면을 정상적으로
    // 띄우고, "+ Collection"을 사용자가 직접 누르게 한다.
    if (isDetached()) { if (S.window.collectionId) await openTab(S.window.collectionId); return; }
    // 마지막에 열어 둔 탭을 모두 되살린다(예전에는 첫 Collection 하나만 열려서, 두 번째부터는 앱을
    // 껐다 켤 때마다 다시 열어야 했다). 순서대로 열고 마지막에 보던 탭으로 돌아온다.
    const known = new Set(S.collections.map((c) => c.id));
    const session = S.settings.session || {};
    const restore = (S.settings.collections || {}).restoreTabs !== false
      ? (session.tabs || []).filter((id) => known.has(id)).slice(0, MAX_TABS) : [];
    if (restore.length) {
      for (const id of restore) await openTab(id);
      if (session.active && session.active !== S.activeId
          && (restore.includes(session.active)
              || (session.active === ARCHIVE_ID && S.archiveConfigured))) await selectTab(session.active);
      return;
    }
    if (S.collections.length) await openTab(S.collections[0].id);
  }

  if (window.pywebview) init();
  else window.addEventListener("pywebviewready", init);
  // 브라우저에서 직접 열었을 때(목업 모드)는 ready 이벤트가 없다.
  setTimeout(() => { if (!S.collections.length && !$("tabs-bar").firstChild) init(); }, 400);
})();
