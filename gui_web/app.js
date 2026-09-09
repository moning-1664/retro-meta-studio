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

  const ROW_HEIGHT = 26;   // 이전 프로젝트의 줄 높이. 34는 한 화면에 너무 적게 들어간다

  // Gamelist 컬럼. 이전 프로젝트에서 실제로 쓰던 구성이다 - 제목이 아니라 **설명**이
  // 가장 넓다. 목록만 훑어도 어떤 게임인지 알 수 있어야 하기 때문이다.
  //
  // `key`가 없는 컬럼(No., ★)은 정렬도 폭 조절도 하지 않는다.
  const COLUMNS = [
    { id: "no", label: "No.", width: 46, fixed: true },
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

  function gridTemplate() {
    return COLUMNS.map((c) => `${S.colWidths[c.id] || c.width}px`).join(" ");
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
  const S = {
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
    // 접어 둔 Storage 그룹. 폴더 트리처럼 더블클릭으로 여닫는다.
    collapsedStorages: {},
    previewOn: true,
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
    if (typeof r.data.previewOn === "boolean") S.previewOn = r.data.previewOn;
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
    if (!pendingUiStateFlush) return;
    clearTimeout(uiStateTimer);
    const send = pendingUiStateFlush;
    pendingUiStateFlush = null;
    await send();
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
   * 클릭으로 닫히는 동작을 새로 만들 필요가 없다(모달 공통 처리에 이미 있다). */
  function openMediaLightbox(img, label) {
    if (!img || !img.src) return;
    const body = h("div", { class: "modal-body lightbox-body" }, [
      h("img", { src: img.src, alt: label, class: "lightbox-img" }),
    ]);
    const card = showModal(label, body, [
      h("button", { class: "btn", onClick: closeModal }, ["닫기"]),
    ]);
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
  // 타이틀바 / 탭
  // ------------------------------------------------------------------
  function renderTitlebar() {
    const bar = $("titlebar");
    clear(bar);
    // **막대 전체가 끌기 영역이다.** `pywebview-drag-region`이 붙은 곳만 창을 옮기는데,
    // 예전에는 제목과 가운데 여백에만 붙어 있어서 그 사이 빈틈을 잡으면 창이 안 움직였다.
    // 창 버튼에는 붙이지 않는다 - 버튼을 누를 때 창이 딸려 움직이면 안 된다.
    bar.classList.add("pywebview-drag-region");

    // 제목은 가운데 놓는다. 양옆에 같은 폭을 두어 버튼이 있어도 가운데가 밀리지 않게 한다.
    bar.appendChild(h("div", { class: "titlebar-side" }));
    bar.appendChild(h("div", { class: "brand" }, [
      h("span", { class: "brand-icon" }, [icon("database", 20)]),
      h("span", { class: "brand-title" }, ["RetroMeta Studio"]),
    ]));

    const controls = h("div", { class: "titlebar-side window-controls" });
    // Windows의 창 버튼과 같은 모양으로 - 대시, 네모, 곱하기.
    [["\u2013", "minimize", "최소화"],
     ["\u25a1", "maximize", "최대화"],
     ["\u00d7", "close", "닫기"]].forEach(([glyph, action, label]) => {
      controls.appendChild(h("button", {
        class: "win-btn" + (action === "close" ? " close" : ""), title: label,
        // 닫기 전에 아직 안 나간 UI 상태 저장(컬럼 폭 등)을 먼저 내보낸다 -
        // debounce 타이머가 돌기 전에 창이 닫히면 방금 바꾼 값이 사라진다.
        onClick: async () => {
          if (action === "close") await flushPendingUiState();
          api.windowControl(action);
        },
      }, [glyph]));
    });
    bar.appendChild(controls);
  }

  function renderTabs() {
    const bar = $("tabs-bar");
    clear(bar);
    S.tabs.forEach((id) => {
      const collection = S.collections.find((c) => c.id === id);
      if (!collection) return;
      const tab = h("div", { class: "ctab" + (id === S.activeId ? " active" : "") });
      tab.appendChild(icon("gamepad", 13));
      tab.appendChild(h("span", { class: "ctab-name" }, [collection.name]));
      const close = h("button", { class: "ctab-close", title: "닫기" }, [icon("x", 10)]);
      close.addEventListener("click", (e) => { e.stopPropagation(); closeTab(id); });
      tab.appendChild(close);
      tab.addEventListener("click", () => selectTab(id));
      tab.addEventListener("contextmenu", (e) => { e.preventDefault(); openTabMenu(collection, e); });
      bar.appendChild(tab);
    });
    const add = h("button", { class: "ctab-add", title: "Collection 추가" }, [icon("plus", 13)]);
    add.addEventListener("click", openAddCollection);
    bar.appendChild(add);

    bar.appendChild(h("div", { class: "ctab-spacer" }));
    const archiveTab = h("div", { class: "ctab archive" + (isArchive() ? " active" : ""),
      title: "여러 Collection에서 수집한 Metadata 보관소" }, [
      icon("database", 13), h("span", { class: "ctab-name" }, ["Archive"]),
    ]);
    archiveTab.addEventListener("click", () => selectTab(ARCHIVE_ID));
    bar.appendChild(archiveTab);
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
    const pathInput = h("input", { class: "field-input", placeholder: "폴더를 선택하세요" });
    // 대개는 이 하나로 충분하다. ROM이 메타데이터와 다른 물리 위치에 있는 흔치 않은
    // 경우(§9, 안드로이드 외장 SD)만 "고급"을 펼쳐 따로 지정한다 - 매번 세 칸을
    // 채우게 하면 그 드문 경우 때문에 흔한 경우가 불편해진다.
    const romInput = h("input", { class: "field-input",
      placeholder: "비워두면 위 폴더에서 함께 찾습니다" });
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

    const pathLabel = h("div", { class: "field-label" }, ["ROM 디렉토리:"]);

    const browseInto = (input, title, alsoName) => h("button", { class: "btn", onClick: async () => {
      const r = await api.pickFolder(title);
      if (!r.ok || !r.data) return;
      input.value = r.data;
      if (alsoName && !nameInput.value.trim()) {
        nameInput.value = String(r.data).split(/[\\/]/).filter(Boolean).pop() || "";
      }
    } }, [icon("folderOpen", 12), h("span", {}, ["찾아보기"])]);

    // 긴 설명을 필드 아래 줄줄이 적지 않는다 - hover하면 뜨는 title 툴팁 하나로
    // 충분하다. 항상 보이는 문장이 아니라 필요할 때만 보이는 문장으로 정책을 맞춘다.
    function syncFrontend() {
      const isEs = ES_STYLE_FRONTEND_IDS.has(frontendSel.value);
      pathLabel.textContent = isEs ? "ES-DE 디렉토리:" : "ROM 디렉토리:";
      pathLabel.title = isEs
        ? "ES-DE의 gamelists와 downloaded_media가 포함된 상위 디렉토리입니다."
        : "ROM(과 메타데이터)이 들어 있는 디렉토리입니다.";
      pathInput.title = pathLabel.title;
    }
    frontendSel.addEventListener("change", syncFrontend);
    syncFrontend();

    const advancedBody = h("div", {}, [
      h("div", { class: "field-label" }, ["ROM 폴더 (선택, ROM이 다른 위치에 있을 때만)"]),
      h("div", { class: "field-row" }, [romInput, browseInto(romInput, "ROM 폴더 선택")]),
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
      pathLabel,
      h("div", { class: "field-row" }, [pathInput, browseInto(pathInput, "폴더 선택", true)]),
      h("div", { class: "field-label" }, ["이름"]), nameInput,
      advanced,
      history,
    ]);

    showModal("Collection 추가", body, [
      h("button", { class: "btn", onClick: closeModal }, ["Cancel"]),
      h("button", { class: "btn primary", onClick: async () => {
        const romPath = romInput.value.trim();
        // ROM 폴더만 주고 대표 폴더를 비운 경우도 정상이다 - 스크래핑을 한 번도 안 한
        // 컬렉션이 그 모습이다. 그때는 ROM 폴더가 곧 Collection root가 된다.
        const path = pathInput.value.trim() || romPath;
        if (!path) { showToast("폴더를 선택하세요.", "warning"); return; }
        const name = nameInput.value.trim() ||
          String(path).split(/[\\/]/).filter(Boolean).pop() || "Collection";
        closeModal();
        const r = await api.createCollection(name, frontendSel.value, path,
                                             targetSel.value || null, archSel.value || null,
                                             romPath, "");
        if (!r.ok) { showToast(r.error, "error"); return; }
        await loadCollections();
        // **불러오기 전에** 묻는다 - 스캔이 끝난 뒤에 물으면 사용자는 이미 "메타데이터가
        // 없는 목록"을 본 뒤라 무엇을 정하는 건지 알기 어렵다.
        await offerMetadataBootstrap(r.data.id);
        await openTab(r.data.id);
        runScan(r.data.id);
      } }, ["Add"]),
    ]);
    setTimeout(() => pathInput.focus(), 30);
  }

  // ------------------------------------------------------------------
  // 좌측 내비게이션
  // ------------------------------------------------------------------
  function renderNav() {
    const nav = $("nav");
    clear(nav);
    const detail = activeDetail();
    if (!detail) {
      nav.appendChild(h("div", { class: "nav-empty" }, ["Collection을 열어주세요"]));
      return;
    }
    nav.appendChild(h("div", { class: "nav-eyebrow" }, ["SYSTEMS"]));

    const scope = activeScope();
    if (isArchive()) {
      const all = navRow("All", detail.totalGames, scope.kind === "all", () => setScope({ kind: "all" }));
      all.classList.add("nav-all");
      all.insertBefore(icon("database", 13), all.firstChild);
      nav.appendChild(all);
      (detail.archiveSystems || []).forEach((sys) => {
        const row = navRow(sys.system.toUpperCase(), sys.count,
          scope.kind === "system" && scope.id === sys.system,
          () => setScope({ kind: "system", id: sys.system }));
        row.classList.add("nav-system");
        row.insertBefore(systemIcon(sys.system, 14), row.firstChild);
        nav.appendChild(row);
      });
      return;
    }
    const allRow = navRow("All", detail.totalGames, scope.kind === "all", () => setScope({ kind: "all" }));
    allRow.classList.add("nav-all");
    allRow.insertBefore(icon("layoutList", 13), allRow.firstChild);
    nav.appendChild(allRow);

    detail.storages.forEach((storage) => {
      const total = storage.systems.reduce((sum, s) => sum + s.count, 0);
      const group = h("div", { class: "nav-group" });
      const head = h("div", { class: "nav-group-head" + (scope.kind === "storage" && scope.id === storage.id ? " active" : "") });
      head.appendChild(icon(storage.kind === "internal" ? "hardDrive" : "hardDriveDownload", 13));
      head.appendChild(h("span", { class: "nav-group-name" }, [storage.label.toUpperCase()]));
      head.appendChild(h("span", { class: "nav-count" }, [formatCount(total)]));
      head.addEventListener("click", () => setScope({ kind: "storage", id: storage.id }));
      // 폴더처럼 접었다 편다. System이 많은 Storage가 목록을 다 차지하지 않게.
      //
      // 키는 Collection ID와 함께 묶는다. Storage id("ext-1" 등)는 Collection마다
      // 처음부터 다시 매겨지므로, storage.id만으로 저장하면 Collection A에서 접은
      // ext-1이 그것과 무관한 Collection B의 ext-1도 함께 접어 버린다.
      const collapseKey = `${S.activeId}|${storage.id}`;
      head.addEventListener("dblclick", (e) => {
        e.preventDefault();
        S.collapsedStorages[collapseKey] = !S.collapsedStorages[collapseKey];
        renderNav();
      });
      if (!isCompare()) {
        head.addEventListener("contextmenu", (e) => { e.preventDefault(); openStorageMenu(storage, e); });
      }
      const collapsed = !!S.collapsedStorages[collapseKey];
      head.insertBefore(icon(collapsed ? "chevronRight" : "chevronDown", 11), head.firstChild);
      group.appendChild(head);
      if (collapsed) group.classList.add("collapsed");

      (collapsed ? [] : storage.systems).forEach((sys) => {
        const row = navRow(sys.system.toUpperCase(), sys.count,
          scope.kind === "system" && scope.id === sys.system,
          () => setScope({ kind: "system", id: sys.system }));
        row.classList.add("nav-system");
        row.insertBefore(systemIcon(sys.system, 14), row.firstChild);
        // Compare 중에는 System을 끌어 옮길 수 없다 - 그 드롭 하나가 Plan을 바꾸고,
        // Auto Plan이 꺼져 있으면 실제 파일까지 옮긴다.
        if (!isCompare()) {
          row.setAttribute("draggable", "true");
          row.addEventListener("dragstart", (e) => {
            e.dataTransfer.setData("text/plain", JSON.stringify({ system: sys.system, from: storage.id }));
          });
        }
        group.appendChild(row);
      });

      // System을 다른 Storage로 끌어다 놓는 자리(스펙 §10).
      //
      // **그룹 전체가 받는다.** 예전에는 머리글 한 줄만 받아서, 사람이 자연스럽게
      // 하는 동작 - 그 그룹 "안에" 떨어뜨리기 - 이 아무 일도 하지 않았다.
      group.addEventListener("dragover", (e) => {
        e.preventDefault();
        group.classList.add("drop-target");
      });
      group.addEventListener("dragleave", (e) => {
        if (!group.contains(e.relatedTarget)) group.classList.remove("drop-target");
      });
      group.addEventListener("drop", async (e) => {
        e.preventDefault();
        group.classList.remove("drop-target");
        let payload;
        try { payload = JSON.parse(e.dataTransfer.getData("text/plain")); } catch (_) { return; }
        if (!payload || payload.from === storage.id) return;
        await moveSystemToStorage(payload.system, storage.id);
      });

      nav.appendChild(group);
    });

    if (!isCompare()) {
      const add = h("button", { class: "nav-action" }, [icon("plus", 12), h("span", {}, ["Add External Storage"])]);
      add.addEventListener("click", openAddStorage);
      nav.appendChild(add);
    }
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
    resetList();
    renderNav();
    await reloadList();
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

    const compact = h("div", { class: "cheader" });
    compact.appendChild(h("div", { class: "cheader-icon" }, [icon("gamepad", 20)]));

    const main = h("div", { class: "cheader-main" });
    main.appendChild(h("div", { class: "cheader-name" }, [detail.name]));
    main.appendChild(h("div", { class: "cheader-sub" }, [
      detail.frontendLabel,
      h("span", { class: "dot" }, ["·"]),
      detail.target ? detail.target : "Unknown",
      h("span", { class: "dot" }, ["·"]),
      detail.arch ? detail.arch.toUpperCase() : "Unknown",
    ]));
    const summary = h("div", { class: "cheader-stats" }, [
      h("span", {}, [`${formatCount(detail.totalGames)} Games`]),
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
      host.appendChild(compact);
      return;
    }
    const rescan = h("button", { class: "btn compact", title: "다시 스캔" },
      [icon("refresh", 12), h("span", {}, ["Rescan"])]);
    rescan.addEventListener("click", () => runScan(S.activeId));
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

    // Frontend 고유 기능(§22). Storage 같은 일반 기능으로 올리지 않고 여기 둔다 -
    // ES-DE의 custom systems XML은 ES-DE의 사정이고, 다른 Frontend에는 다른 기능이
    // 붙는다. 지원 기능이 없는 Frontend에서는 줄 자체가 나타나지 않는다.
    if (S.adapterActions && S.adapterActions.length) {
      const extras = h("div", { class: "cheader-extras" });
      extras.appendChild(h("span", { class: "cheader-info-label" }, ["Frontend 기능"]));
      S.adapterActions.forEach((action) => {
        const btn = h("button", { class: "btn compact" }, [`[${action.label}]`]);
        btn.addEventListener("click", () => runAdapterAction(action));
        extras.appendChild(btn);
      });
      panel.appendChild(extras);
    }
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

    const modes = h("div", { class: "seg" });
    [["list", "목록"], ["card", "카드"]].forEach(([mode, label]) => {
      const btn = h("button", {
        class: "seg-btn" + (S.viewMode === mode ? " on" : ""), title: label + " 보기",
      }, [icon(mode === "list" ? "layoutList" : "layoutGrid", 12)]);
      btn.addEventListener("click", () => {
        if (S.viewMode === mode) return;
        S.viewMode = mode;
        renderFilterBar();
        renderListWindow();
      });
      modes.appendChild(btn);
    });
    bar.appendChild(modes);

    // System 필터. 좌측 내비게이션과 같은 곳을 가리키므로 상태를 공유한다.
    const scope = activeScope();
    const systems = (detail ? detail.storages.flatMap((s) => s.systems) : [])
      .map((s) => s.system).sort();
    const sysSel = h("select", { class: "mini-select", title: "System 필터" }, [
      h("option", { value: "" }, ["모든 System"]),
      ...systems.map((s) => h("option", { value: s }, [s])),
    ]);
    sysSel.value = scope.kind === "system" ? scope.id : "";
    sysSel.addEventListener("change", async (e) => {
      // setScope가 목록 재조회까지 한다. 여기서 또 부르면 같은 질의를 두 번 보낸다.
      await setScope(e.target.value ? { kind: "system", id: e.target.value } : { kind: "all" });
      renderFilterBar();
    });
    bar.appendChild(sysSel);

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

    const refresh = h("button", { class: "icon-btn", title: "다시 스캔" }, [icon("refresh", 12)]);
    refresh.addEventListener("click", () => runScan(S.activeId));
    bar.appendChild(refresh);

    // Import는 눈에 보이는 자리에 있어야 한다. 예전에는 «+» 탭을 눌러 창을 하나 더
    // 거쳐야만 닿아서, 기능이 없는 것과 구별되지 않았다.
    const importBtn = h("button", { class: "icon-btn", title: "Collection 가져오기 (Import)" },
                        [icon("upload", 12)]);
    importBtn.addEventListener("click", openAddCollection);
    bar.appendChild(importBtn);

    // 탐색기의 미리보기 창과 같다. **끄면 목록이 그 자리까지 넓어진다** - 상세를
    // 안 보는 동안 화면 3분의 1을 비워둘 이유가 없다.
    const preview = h("button", {
      class: "icon-btn" + (S.previewOn ? " on" : ""),
      title: S.previewOn ? "미리보기 끄기" : "미리보기 켜기",
    }, [icon("previewPane", 13)]);
    preview.addEventListener("click", () => {
      S.previewOn = !S.previewOn;
      saveUiState();
      renderFilterBar();
      applyPreviewMode();
    });
    bar.appendChild(preview);

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

    const ingest = h("button", { class: "btn compact",
      title: "이 Collection의 Metadata를 Archive에 수집합니다" },
      [icon("database", 12), h("span", {}, ["Archive에 수집"])]);
    ingest.addEventListener("click", ingestToArchive);
    bar.appendChild(ingest);

    const del = h("button", {
      class: "btn compact", disabled: !S.selected.size,
      title: S.selected.size ? "선택한 항목을 삭제합니다" : "삭제할 항목을 먼저 고르세요",
    }, ["Delete"]);
    if (S.selected.size) del.addEventListener("click", deleteSelection);
    bar.appendChild(del);

    const auto = h("button", {
      class: "btn compact" + (S.autoPlan ? " primary" : ""),
      title: "Auto Plan: 변경을 바로 적용하지 않고 먼저 계산합니다",
    }, [S.autoPlan ? "✓ Auto Plan" : "Auto Plan OFF"]);
    auto.addEventListener("click", toggleAutoPlan);
    bar.appendChild(auto);

    const apply = h("button", {
      class: "btn compact primary", disabled: !(plan && plan.total),
      title: plan && plan.total ? "Plan을 실제 파일에 적용합니다" : "적용할 Plan이 없습니다",
    }, [plan && plan.total ? `Apply (${formatCount(plan.total)})` : "Apply"]);
    if (plan && plan.total) apply.addEventListener("click", applyPlan);
    bar.appendChild(apply);

    // 지우개 아이콘 대신 Cancel. 무엇이 일어나는지 글자로 말하는 편이 낫다.
    const cancel = h("button", {
      class: "btn compact", disabled: !(plan && plan.total), title: "계산해둔 변경을 버립니다",
    }, ["Cancel"]);
    if (plan && plan.total) {
      cancel.addEventListener("click", () => showConfirm(
        "Plan 취소", "계산해둔 변경을 모두 버립니다. 실제 파일은 바뀌지 않습니다.", true,
        async () => { await api.planClear(S.activeId); await refreshPlan(); }));
    }
    bar.appendChild(cancel);
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

  function renderListHead() {
    const head = $("list-head");
    clear(head);
    if (!activeDetail()) return;
    head.style.gridTemplateColumns = gridTemplate();

    COLUMNS.forEach((col) => {
      const sorted = col.key && S.order === col.key;
      const cell = h("div", { class: "lh lh-" + col.id + (sorted ? " sorted" : "") },
                     [col.label]);
      if (col.key) {
        // 한 번 누르면 오름차순, 다시 누르면 내림차순. 이전 프로젝트와 같다 -
        // 그래서 별도의 정렬 셀렉트와 방향 버튼이 필요 없다.
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
      head.appendChild(cell);
    });
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

  function renderListWindow() {
    const scroll = $("list-scroll"), spacer = $("list-spacer"), win = $("list-window");
    if (!scroll) return;
    spacer.style.height = (S.total * ROW_HEIGHT) + "px";
    clear(win);

    if (!activeDetail()) {
      win.appendChild(h("div", { class: "empty-msg" }, [
        "등록된 Collection이 없습니다. 상단의 \"+\"를 눌러 추가하세요.",
      ]));
      return;
    }
    if (S.total === 0) {
      win.appendChild(h("div", { class: "empty-msg" }, ["조건에 맞는 게임이 없습니다."]));
      return;
    }

    if (S.viewMode === "card" && !isCompare()) { renderCardWindow(scroll, spacer, win); return; }
    win.classList.remove("card-mode");

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

  /** 카드(격자) 보기. 목록의 가상 스크롤과 달리 지금까지 불러온 페이지만큼만
   * 그려 넣고, 바닥 근처까지 스크롤하면 다음 페이지를 더 불러온다 - 수천 개
   * 규모의 가상 그리드는 이번 작업 범위 밖이다(§작업 원칙). */
  function renderCardWindow(scroll, spacer, win) {
    spacer.style.height = "0px";
    win.style.transform = "";
    win.classList.add("card-mode");
    clear(win);

    const loadedUpTo = S.loadedPages.size
      ? (Math.max(...S.loadedPages) + 1) * PAGE_SIZE
      : PAGE_SIZE;
    const renderCount = Math.min(S.total, loadedUpTo);
    for (let i = 0; i < renderCount; i += 1) {
      const row = S.rowCache.get(i);
      win.appendChild(row ? cardElement(row, i) : cardPlaceholder(i));
    }

    const nearBottom = scroll.scrollTop + scroll.clientHeight > scroll.scrollHeight - 300;
    if (renderCount < S.total && (nearBottom || renderCount === 0)) {
      ensurePages(renderCount, Math.min(S.total - 1, renderCount + PAGE_SIZE - 1));
    }
  }

  function cardElement(row, index) {
    const selected = S.selected.has(row.romUid);
    const card = h("div", {
      class: "preview-card" + (selected ? " selected" : "") + (S.focused === row.romUid ? " focused" : ""),
    });
    const cover = h("div", { class: "preview-cover" });
    if (row.hasMedia !== false) {
      const img = h("img", { alt: row.title || row.file });
      cover.appendChild(img);
      loadCardCover(img, row.romUid);
    } else {
      cover.appendChild(icon("imageOff", 20));
    }
    card.appendChild(cover);
    card.appendChild(h("div", { class: "preview-title truncate", title: row.title || row.file },
                       [row.title || row.file]));
    card.addEventListener("click", (e) => handleRowClick(e, row, index));
    return card;
  }

  function cardPlaceholder(index) {
    return h("div", { class: "preview-card placeholder", key: index }, [
      h("div", { class: "preview-cover" }),
      h("div", { class: "preview-title" }, [h("span", { class: "skeleton" })]),
    ]);
  }

  /** 카드의 표지 그림. loadMediaImage()는 상세 패널(S.detailState) 것만 신경 쓰므로
   * 목록의 여러 행을 한꺼번에 그리는 카드 보기에는 쓸 수 없다 - romUid를 직접 받는다. */
  async function loadCardCover(img, romUid) {
    const r = await api.getMediaImage(S.activeId, romUid, "Covers", true);
    if (r.ok && r.data) img.src = r.data;
  }

  function placeholderRow(index) {
    return h("div", { class: "lrow placeholder", style: { height: ROW_HEIGHT + "px" } }, [
      h("div", { class: "lc lc-check" }),
      h("div", { class: "lc lc-index" }, [String(index + 1)]),
      h("div", { class: "lc lc-title" }, [h("span", { class: "skeleton" })]),
    ]);
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
    el.appendChild(h("div", { class: "lc lc-desc truncate" }, [row.file]));
    el.addEventListener("click", () => openCompareDetail(row));
    return el;
  }

  function rowElement(row, index) {
    if (isCompare()) return compareRowElement(row, index);
    const selected = S.selected.has(row.romUid);
    const el = h("div", {
      class: "lrow" + (selected ? " selected" : "") + (S.focused === row.romUid ? " focused" : ""),
      style: { height: ROW_HEIGHT + "px", gridTemplateColumns: gridTemplate() },
    });

    // No. - 화면에 보이는 순번이 아니라 목록 전체에서의 순번이다.
    el.appendChild(h("div", { class: "lc lc-no" }, [String(index + 1)]));
    el.appendChild(h("div", { class: "lc lc-file truncate", title: row.file }, [row.file]));

    const titleCell = h("div", { class: "lc lc-title truncate" }, [row.title || row.file]);
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
    el.appendChild(titleCell);

    // Description이 가장 넓다. 목록만 훑어도 어떤 게임인지 알 수 있어야 한다.
    const desc = (row.desc || "").replace(/\s+/g, " ").trim();
    el.appendChild(h("div", { class: "lc lc-desc truncate", title: desc }, [desc]));
    el.appendChild(h("div", { class: "lc lc-region truncate" }, [row.region || ""]));
    el.appendChild(h("div", { class: "lc lc-rating" }, [formatRating(row.rating)]));

    // 별표는 눌러서 바로 켜고 끈다. 상세 패널을 열지 않아도 되게.
    const star = h("button", {
      class: "fav-btn" + (row.favorite ? " on" : ""),
      title: row.favorite ? "즐겨찾기 해제" : "즐겨찾기",
    }, [row.favorite ? "★" : "☆"]);
    star.addEventListener("click", (e) => { e.stopPropagation(); toggleFavorite(row, star); });
    el.appendChild(h("div", { class: "lc lc-fav" }, [star]));

    el.appendChild(h("div", { class: "lc lc-genre truncate", title: row.genre || "" },
                     [row.genre || ""]));
    el.appendChild(h("div", { class: "lc lc-status" }, [statusMark(row)]));

    el.addEventListener("click", (e) => handleRowClick(e, row, index));
    return el;
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
      renderListWindow();
      renderStatusBar();
      return;
    }
    if (additive) {
      if (S.selected.has(row.romUid)) S.selected.delete(row.romUid);
      else S.selected.add(row.romUid);
      S.selectAnchor = row.romUid;
      renderListWindow();
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

  /** gamelist가 없는 Collection이면 ROM 목록만으로 만들어 줄지 묻는다.
   *
   * 만들지 않아도 Collection은 열린다 - 그때는 Gamelist에 파일명이 제목 자리에 뜨고,
   * 사용자가 항목을 고쳐 저장하는 순간 gamelist.xml이 만들어진다. 여기서 미리 만드는
   * 것은 이후 작업(Export/Convert/Archive 수집)을 자연스럽게 하기 위한 선택지다.
   */
  async function offerMetadataBootstrap(collectionId) {
    const status = await api.metadataStatus(collectionId);
    if (!status.ok || !status.data.missing.length) return;

    const missing = status.data.missing;
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
      showModal("메타데이터가 없습니다", body, [
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
    renderListWindow();
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
    renderListWindow();
  }

  function captureDraft() {
    if (!S.detailState) return;
    S.detailState.draft = S.detailState.draft || {};
    Object.keys(fieldRefs).forEach((k) => { if (fieldRefs[k]) S.detailState.draft[k] = fieldRefs[k].value; });
  }

  /** 미리보기를 끄면 상세 패널을 접고 목록이 그 자리까지 넓어진다. */
  function applyPreviewMode() {
    const panel = $("detail-panel");
    if (!panel) return;
    panel.classList.toggle("hidden", !S.previewOn);
    if (S.previewOn) renderDetailPanel();
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

  function renderDetailPanel() {
    const panel = $("detail-panel");
    clear(panel);
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
        h("div", { class: "detail-filename" }, [state.file]),
        h("div", { class: "detail-system" }, [systemIcon(state.system, 13), String(state.system).toUpperCase()]),
      ]),
    ]);

    if (!state.archive) {
      // 즐겨찾기와 실행은 게임을 보고 있을 때 바로 손이 가는 자리에 있어야 한다.
      const star = h("button", {
        class: "icon-btn fav-btn" + (state.favorite ? " on" : ""),
        title: state.favorite ? "즐겨찾기 해제" : "즐겨찾기",
      }, [state.favorite ? "★" : "☆"]);
      star.addEventListener("click", () => toggleFavoriteFromDetail(star));
      header.appendChild(star);

      // 실행은 아직 연결되지 않았다. **버튼을 없애는 대신 못 한다고 말한다** -
      // 사라진 기능은 언제 돌아오는지 알 수 없지만, 눌러서 안내를 받으면 안다.
      const play = h("button", {
        class: "icon-btn", title: state.present ? "실행 (RetroArch 연동 예정)" : "ROM 파일이 없습니다",
        disabled: !state.present,
      }, [icon("gamepad", 14)]);
      if (state.present) {
        play.addEventListener("click", () => showToast(
          "RetroArch 연동은 다음 버전에서 들어옵니다.", "warning"));
      }
      header.appendChild(play);
    }

    const close = h("button", { class: "icon-btn", title: "닫기 (Esc)" }, [icon("x", 13)]);
    close.addEventListener("click", closeDetail);
    header.appendChild(close);
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
    const r = await api.getMediaImage(S.activeId, romUid, label, !!thumbnail);
    if (r.ok && r.data && S.detailState && S.detailState.romUid === romUid) img.src = r.data;
  }

  //: 화면에 보여줄 media와 그 표시 방식.
  //
  //  `file`인 것(영상·설명서)은 그림이 아니라 **있는지 없는지**만 알면 된다. 영상을
  //  data URI로 실어 오면 브릿지가 감당하지 못하고, 설명서는 PDF라 애초에 그릴 수 없다.
  //  그래서 그 둘은 [v] 하나로 표시한다 - 이전 프로젝트가 쓰던 방식이다.
  const MEDIA_SLOTS = [
    { label: "Cover", key: "Covers" },
    { label: "Marquee", key: "Marquees" },
    { label: "MixImage", key: "Miximages" },
    { label: "Wheel", key: "Wheel" },
    { label: "Screenshot", key: "Screenshots" },
    { label: "TitleScreen", key: "TitleScreens" },
    { label: "3DBox", key: "3DBoxes" },
    { label: "BackCover", key: "BackCovers" },
    { label: "FanArt", key: "FanArt" },
    { label: "PhysicalMedia", key: "PhysicalMedia" },
    { label: "Video", key: "Videos", file: true },
    { label: "Manual", key: "Manuals", file: true },
  ];

  function renderMediaTab(body) {
    body.classList.add("media-tab-body");
    const media = S.detailState.media || {};

    const grid = h("div", { class: "media-grid" });
    MEDIA_SLOTS.forEach((slot) => {
      const has = !!media[slot.key];
      const zone = h("div", {
        class: "media-tile" + (slot.file ? " file-slot" : "") + (has ? "" : " empty"),
        title: slot.label + (has ? "" : " 없음"),
      });
      zone.appendChild(h("div", { class: "media-tile-label" }, [slot.label]));

      // **비어 있어도 자리는 그대로다.** 예전에는 Screenshot이 없으면 높이가 무너져
      // 패널 전체 배치가 흔들렸다. 타일마다 16:9를 고정한다.
      const preview = h("div", { class: "media-tile-preview" });
      if (slot.file) {
        // 있는지 없는지만 말한다. 있으면 [v].
        preview.appendChild(h("div", { class: "media-flag" + (has ? " on" : "") },
                              [has ? "v" : ""]));
      } else if (has) {
        const img = h("img", { alt: slot.label });
        preview.appendChild(img);
        loadMediaImage(img, slot.key, false);
        zone.classList.add("clickable");
        zone.addEventListener("click", () => openMediaLightbox(img, slot.label));
      } else {
        // "Screenshot 없음"을 열두 번 적으면 그것만 눈에 들어온다. 아이콘 하나로 족하다.
        preview.appendChild(icon("imageOff", 16));
      }
      zone.appendChild(preview);
      grid.appendChild(zone);
    });
    body.appendChild(grid);
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

    // 저장은 즉시 파일에 반영된다(결정 D1). 목록의 제목만 갱신한다.
    const cached = [...S.rowCache.entries()].find(([, row]) => row.romUid === state.romUid);
    if (cached) cached[1].title = r.data.title;
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
  }

  const planCapacity = (storageId) =>
    ((S.plan && S.plan.capacity) || []).find((c) => c.storageId === storageId) || null;

  // Copy/Paste는 Gamelist에서 없앴다(QA 재검토 P1) - Collection 사이에 항목을
  // 옮기는 경로는 Archive에 수집 -> Collection으로 보내기 하나로 통일한다. 백엔드의
  // api.copySelection/api.paste 자체는 남아 있다(다른 진입점이 나중에 필요할 수
  // 있다) - 여기서 없앤 것은 화면의 버튼과 단축키뿐이다.

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
      // **파일은 그대로 두고 메타데이터만 반영**이고, 대개는 그것이 사용자가 원한 것이다.
      [["메타데이터만", "파일은 그대로 두고 메타데이터/미디어만 반영합니다"],
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
        "이미 가지고 있는 ROM에 메타데이터와 미디어만 채우려는 것이라면 " +
        "«메타데이터만»을 고르세요. 파일은 건드리지 않습니다."]),
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

  function toggleAutoPlan() {
    if (!S.autoPlan) { S.autoPlan = true; renderStatusBar(); return; }
    // 끄기 전에 경고한다(스펙 §32).
    showConfirm("Auto Plan 끄기",
      "이후 복사 / 삭제 / 이동이 실제 파일에 즉시 적용됩니다. 계속하시겠습니까?", true,
      () => { S.autoPlan = false; renderStatusBar(); });
  }

  // ------------------------------------------------------------------
  // Archive (스펙 §37-44)
  // ------------------------------------------------------------------
  async function ingestToArchive() {
    const selected = S.selected.size ? [...S.selected] : null;
    const label = selected ? `선택한 ${formatCount(selected.length)}개` : "전체";
    const r = await api.archiveIngest(S.activeId, selected);
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
        left.appendChild(h("span", { class: "sb-badge danger", title: "지난 적용에서 실패해 Plan에 남아 있는 항목" },
          [`실패 ${formatCount(plan.failed)}`]));
      }
    }
    bar.appendChild(left);

    const middle = h("div", { class: "sb-middle" });
    if (detail) {
      middle.appendChild(h("span", { class: "sb-label" }, [plan && plan.total ? "Storage (Actual → Plan)" : "Storage"]));
      detail.storages.forEach((storage) => {
        const capacity = planCapacity(storage.id);
        const changed = capacity && capacity.deltaBytes;
        middle.appendChild(h("span", { class: "sb-storage" + (capacity && capacity.over ? " over" : "") }, [
          h("b", {}, [storage.label]), " ",
          formatBytes(storage.actualBytes),
          changed ? ` → ${formatBytes(capacity.planBytes)}` : "",
        ]));
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
    if (isArchive()) {
      const targets = S.tabs.filter((t) => t !== ARCHIVE_ID);
      // 못 쓰는 버튼은 **왜 못 쓰는지 말해야 한다.** 예전에는 선택이 없어서 꺼져
      // 있을 때도 "선택 항목을 보냅니다"라고 적혀 있어서, 기능이 고장 난 것처럼 보였다.
      const why = !targets.length ? "보낼 Collection을 먼저 열어주세요"
                : !S.selected.size ? "보낼 항목을 먼저 고르세요"
                : "선택 항목을 Collection으로 보냅니다";
      const send = h("button", {
        class: "btn compact primary", disabled: !S.selected.size || !targets.length,
        title: why,
      }, ["Collection으로 보내기"]);
      if (S.selected.size && targets.length) send.addEventListener("click", openSendToCollection);
      actions.appendChild(send);
      bar.appendChild(actions);
      return;
    }

    // AutoPlan/Apply/Cancel/Archive에 수집/Delete는 전부 위쪽 Gamelist 툴바
    // (renderPlanActions)로 옮겼다 - 여기 그대로 두면 똑같은 버튼이 두 번 보인다.
    bar.appendChild(actions);
  }

  // ------------------------------------------------------------------
  // 스캔
  // ------------------------------------------------------------------
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
  function renderAll() {
    renderTitlebar();
    renderTabs();
    renderNav();
    renderHeader();
    renderFilterBar();
    renderListHead();
    renderListWindow();
    renderDetailPanel();
    renderStatusBar();
  }

  async function loadCollections() {
    const r = await api.listCollections();
    if (r.ok) S.collections = r.data;
  }

  //: 레이아웃이 견디는 최소 크기. main.py의 MIN_SIZE와 같은 값이어야 한다 -
  //  여기서 더 작게 줄일 수 있게 두면 창은 줄어드는데 안쪽이 깨진다.
  const MIN_WINDOW = { width: 900, height: 640 };

  /** frameless 창에는 네이티브 크기 조절 테두리가 없다. 손잡이를 끌어 대신한다. */
  function bindResizeGrip() {
    const grip = $("resize-grip");
    if (!grip) return;

    grip.addEventListener("mousedown", (down) => {
      down.preventDefault();
      const start = { x: down.screenX, y: down.screenY,
                      width: window.outerWidth, height: window.outerHeight };
      let pending = null;

      const onMove = (move) => {
        const width = Math.max(MIN_WINDOW.width, start.width + (move.screenX - start.x));
        const height = Math.max(MIN_WINDOW.height, start.height + (move.screenY - start.y));
        // 브릿지 호출은 프레임당 한 번으로 묶는다 - mousemove마다 부르면 창이 끊겨 보인다.
        if (pending) return;
        pending = requestAnimationFrame(() => {
          pending = null;
          api.windowResize(Math.round(width), Math.round(height));
        });
      };
      const onUp = () => {
        if (pending) cancelAnimationFrame(pending);
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  function bindEvents() {
    bindResizeGrip();
    const scroll = $("list-scroll");
    let ticking = false;
    scroll.addEventListener("scroll", () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => { ticking = false; renderListWindow(); });
    });
    window.addEventListener("resize", () => renderListWindow());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { if ($("modal-root").firstChild) closeModal(); else closeDetail(); }
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
      if (e.key === "Delete") { e.preventDefault(); deleteSelection(); }
    });
  }

  async function init() {
    bindEvents();
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
