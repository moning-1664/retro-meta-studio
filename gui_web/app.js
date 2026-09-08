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

  const ROW_HEIGHT = 34;
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
    // 가상 스크롤
    rowCache: new Map(), // index -> row
    loadedPages: new Set(),
    total: 0,
    queryToken: 0,
    selected: new Set(),
    focused: null,       // 선택된 romUid (상세 패널 대상)
    detailState: null,
    // Plan은 세션 한정이다(결정 D2). 백엔드 메모리에만 있고 여기서는 요약만 들고 있다.
    plan: null,
    // Auto Plan이 켜져 있으면 복사/삭제/이동이 Plan으로 들어간다(스펙 §26).
    // 끄면 같은 동작이 확인 후 즉시 실행된다.
    autoPlan: true,
  };

  //: Archive는 Collection이 아니지만 같은 Gamelist/Detail UI를 쓴다(스펙 §43).
  //  별도 화면을 만들지 않고 특수한 탭 id 하나로 취급한다.
  const ARCHIVE_ID = "archive";
  const isArchive = () => S.activeId === ARCHIVE_ID;

  const MEDIA_LABEL = { "3dboxes": "3DBoxes", covers: "Covers", marquees: "Marquees",
    miximages: "Miximages", screenshots: "Screenshots", videos: "Videos", wheel: "Wheel" };

  const activeDetail = () => S.detail[S.activeId] || null;
  const activeScope = () => S.scope[S.activeId] || { kind: "all" };

  function currentQuery() {
    const scope = activeScope();
    const query = { search: S.search, order: S.order, descending: S.descending };
    if (scope.kind === "system") query.systems = [scope.id];
    else if (scope.kind === "storage") query.storageIds = [scope.id];
    return query;
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
    return new Promise((resolve) => {
      showJobProgress(title, jobId);
      const tick = async () => {
        const r = await api.jobProgress(jobId);
        if (!r.ok) { hideJobProgress(); resolve({ ok: false, error: r.error }); return; }
        const job = r.data;
        updateJobProgress(job.current, job.total, job.label);
        if (!job.done) { setTimeout(tick, 180); return; }
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
    bar.appendChild(h("div", { class: "brand" }, [
      h("span", { class: "brand-icon" }, [icon("database", 17)]),
      h("span", { class: "brand-title" }, ["RetroMeta Studio"]),
    ]));
    bar.appendChild(h("div", { class: "titlebar-spacer" }));
    const controls = h("div", { class: "window-controls" });
    [["menu", "minimize"], ["layoutGrid", "maximize"], ["x", "close"]].forEach(([ico, action]) => {
      controls.appendChild(h("button", { class: "icon-btn", title: action,
        onClick: () => api.windowControl(action) }, [icon(ico, 12)]));
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
    const add = h("button", { class: "ctab-add", title: "Collection 열기/추가" }, [icon("plus", 13)]);
    add.addEventListener("click", openCollectionPicker);
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
    showModal("Collection", body, [
      h("button", { class: "btn", onClick: () => { closeModal(); promptRename(collection); } }, ["이름 변경"]),
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
    resetList();
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
  }

  // ------------------------------------------------------------------
  // Collection 추가
  // ------------------------------------------------------------------
  async function openCollectionPicker() {
    await loadCollections();
    const list = h("div", { class: "picker-list" });
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
      list.appendChild(row);
    });
    if (!S.collections.length) {
      list.appendChild(h("div", { class: "empty-msg" }, ["등록된 Collection이 없습니다."]));
    }
    const body = h("div", { class: "modal-body" }, [list]);
    showModal("Collection 열기", body, [
      h("button", { class: "btn", onClick: closeModal }, ["닫기"]),
      h("button", { class: "btn primary", onClick: () => { closeModal(); openAddCollection(); } },
        [icon("plus", 12), h("span", {}, ["새 Collection 추가"])]),
    ]);
  }

  async function openAddCollection() {
    const frontendsR = await api.frontends();
    const frontends = frontendsR.ok ? frontendsR.data : [{ id: "es-de", label: "ES-DE" }];

    const nameInput = h("input", { class: "field-input", placeholder: "예: Android ES-DE" });
    const pathInput = h("input", { class: "field-input", placeholder: "Collection 폴더" });
    const frontendSel = h("select", { class: "field-input" },
      frontends.map((f) => h("option", { value: f.id }, [f.label])));
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

    const browse = h("button", { class: "btn", onClick: async () => {
      const r = await api.pickFolder("Collection 폴더 선택");
      if (r.ok && r.data) {
        pathInput.value = r.data;
        if (!nameInput.value.trim()) nameInput.value = String(r.data).split(/[\\/]/).filter(Boolean).pop() || "";
      }
    } }, [icon("folderOpen", 12), h("span", {}, ["찾아보기"])]);

    const body = h("div", { class: "modal-body" }, [
      h("div", { class: "field-label" }, ["이름"]), nameInput,
      h("div", { class: "field-label" }, ["Frontend"]), frontendSel,
      h("div", { class: "field-label" }, ["폴더"]),
      h("div", { class: "field-row" }, [pathInput, browse]),
      h("div", { class: "field-grid two" }, [
        h("div", {}, [h("div", { class: "field-label" }, ["Target"]), targetSel]),
        h("div", {}, [h("div", { class: "field-label" }, ["Architecture"]), archSel]),
      ]),
      h("div", { class: "modal-hint" },
        ["Target/OS/Architecture는 서로 다른 값입니다. 모르면 Unknown으로 두세요."]),
    ]);

    showModal("새 Collection", body, [
      h("button", { class: "btn", onClick: closeModal }, ["취소"]),
      h("button", { class: "btn primary", onClick: async () => {
        const name = nameInput.value.trim(), path = pathInput.value.trim();
        if (!name || !path) { showToast("이름과 폴더를 입력하세요.", "warning"); return; }
        closeModal();
        const r = await api.createCollection(name, frontendSel.value, path,
                                             targetSel.value || null, archSel.value || null);
        if (!r.ok) { showToast(r.error, "error"); return; }
        await loadCollections();
        await openTab(r.data.id);
        runScan(r.data.id);
      } }, ["추가"]),
    ]);
    setTimeout(() => nameInput.focus(), 30);
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
      head.addEventListener("contextmenu", (e) => { e.preventDefault(); openStorageMenu(storage, e); });
      group.appendChild(head);

      storage.systems.forEach((sys) => {
        const row = navRow(sys.system.toUpperCase(), sys.count,
          scope.kind === "system" && scope.id === sys.system,
          () => setScope({ kind: "system", id: sys.system }));
        row.classList.add("nav-system");
        row.insertBefore(systemIcon(sys.system, 14), row.firstChild);
        row.setAttribute("draggable", "true");
        row.addEventListener("dragstart", (e) => {
          e.dataTransfer.setData("text/plain", JSON.stringify({ system: sys.system, from: storage.id }));
        });
        group.appendChild(row);
      });

      // System을 다른 Storage로 끌어다 놓는 자리(스펙 §10).
      head.addEventListener("dragover", (e) => { e.preventDefault(); head.classList.add("drop-target"); });
      head.addEventListener("dragleave", () => head.classList.remove("drop-target"));
      head.addEventListener("drop", async (e) => {
        e.preventDefault();
        head.classList.remove("drop-target");
        let payload;
        try { payload = JSON.parse(e.dataTransfer.getData("text/plain")); } catch (_) { return; }
        if (!payload || payload.from === storage.id) return;
        await moveSystemToStorage(payload.system, storage.id);
      });

      nav.appendChild(group);
    });

    const add = h("button", { class: "nav-action" }, [icon("plus", 12), h("span", {}, ["Add External Storage"])]);
    add.addEventListener("click", openAddStorage);
    nav.appendChild(add);
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
    host.appendChild(panel);
  }

  // ------------------------------------------------------------------
  // 필터 바
  // ------------------------------------------------------------------
  function renderFilterBar() {
    const bar = $("filter-bar");
    clear(bar);
    if (!activeDetail()) return;

    const search = h("input", { class: "search-input", placeholder: "Search...", value: S.search });
    let timer = null;
    search.addEventListener("input", (e) => {
      clearTimeout(timer);
      const value = e.target.value;
      timer = setTimeout(async () => { S.search = value; resetList(); await reloadList(); }, 180);
    });
    bar.appendChild(h("div", { class: "search-box" }, [icon("search", 13), search]));

    const orderSel = h("select", { class: "mini-select" }, [
      h("option", { value: "title" }, ["제목순"]),
      h("option", { value: "filename" }, ["파일명순"]),
      h("option", { value: "system" }, ["시스템순"]),
      h("option", { value: "size" }, ["크기순"]),
    ]);
    orderSel.value = S.order;
    orderSel.addEventListener("change", async (e) => { S.order = e.target.value; resetList(); await reloadList(); });
    bar.appendChild(orderSel);

    const dir = h("button", { class: "icon-btn", title: S.descending ? "내림차순" : "오름차순" },
      [icon(S.descending ? "chevronDown" : "chevronUp", 12)]);
    dir.addEventListener("click", async () => { S.descending = !S.descending; resetList(); await reloadList(); });
    bar.appendChild(dir);

    bar.appendChild(h("div", { class: "filter-spacer" }));
    bar.appendChild(h("div", { class: "filter-total", id: "filter-total" },
      [`${formatCount(S.total)} items`]));
  }

  // ------------------------------------------------------------------
  // Gamelist (가상 스크롤)
  // ------------------------------------------------------------------
  function resetList() {
    S.rowCache.clear();
    S.loadedPages.clear();
    S.total = 0;
    S.selected.clear();
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
    head.appendChild(h("div", { class: "lh lh-check" }));
    head.appendChild(h("div", { class: "lh lh-index" }, ["#"]));
    head.appendChild(h("div", { class: "lh lh-title" }, ["Title"]));
    head.appendChild(h("div", { class: "lh lh-system" }, ["System"]));
    head.appendChild(h("div", { class: "lh lh-status" }, ["Status"]));
    head.appendChild(h("div", { class: "lh lh-desc" }, ["File"]));
  }

  function fetchRows(query) {
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
    }
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
      win.appendChild(h("div", { class: "empty-msg" }, ["Collection을 열면 게임 목록이 표시됩니다."]));
      return;
    }
    if (S.total === 0) {
      win.appendChild(h("div", { class: "empty-msg" }, ["조건에 맞는 게임이 없습니다."]));
      return;
    }

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

  function placeholderRow(index) {
    return h("div", { class: "lrow placeholder", style: { height: ROW_HEIGHT + "px" } }, [
      h("div", { class: "lc lc-check" }),
      h("div", { class: "lc lc-index" }, [String(index + 1)]),
      h("div", { class: "lc lc-title" }, [h("span", { class: "skeleton" })]),
    ]);
  }

  function rowElement(row, index) {
    const selected = S.selected.has(row.romUid);
    const el = h("div", {
      class: "lrow" + (selected ? " selected" : "") + (S.focused === row.romUid ? " focused" : ""),
      style: { height: ROW_HEIGHT + "px" },
    });

    const check = h("input", { type: "checkbox" });
    check.checked = selected;
    check.addEventListener("click", (e) => e.stopPropagation());
    check.addEventListener("change", () => {
      if (check.checked) S.selected.add(row.romUid); else S.selected.delete(row.romUid);
      el.classList.toggle("selected", check.checked);
      renderStatusBar();
    });
    el.appendChild(h("div", { class: "lc lc-check" }, [check]));
    el.appendChild(h("div", { class: "lc lc-index" }, [String(index + 1)]));

    el.appendChild(h("div", { class: "lc lc-title" }, [
      systemIcon(row.system, 15),
      h("span", { class: "lrow-title truncate" }, [row.title || row.file]),
    ]));
    el.appendChild(h("div", { class: "lc lc-system" }, [
      h("span", { class: "sys-badge" }, [String(row.system).toUpperCase()])]));
    el.appendChild(h("div", { class: "lc lc-status" }, [statusMark(row)]));
    el.appendChild(h("div", { class: "lc lc-desc truncate" }, [row.file]));

    el.addEventListener("click", () => openDetail(row));
    return el;
  }

  // ------------------------------------------------------------------
  // 우측 상세 패널 (이전 프로젝트 구성을 유지 - 스펙 §34~36)
  // ------------------------------------------------------------------
  const fieldRefs = {};

  async function openDetail(row) {
    S.focused = row.romUid;
    renderListWindow();
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

  function renderDetailPanel() {
    const panel = $("detail-panel");
    clear(panel);
    const state = S.detailState;
    panel.classList.toggle("open", !!state);
    if (!state) return;

    const inner = h("div", { id: "detail-panel-inner" });
    panel.appendChild(inner);

    const header = h("div", { class: "detail-header" }, [
      h("div", { style: { minWidth: "0", flex: "1" } }, [
        h("div", { class: "detail-eyebrow" }, ["METADATA"]),
        h("div", { class: "detail-filename" }, [state.file]),
        h("div", { class: "detail-system" }, [systemIcon(state.system, 13), String(state.system).toUpperCase()]),
      ]),
    ]);
    const close = h("button", { class: "icon-btn", title: "닫기 (Esc)" }, [icon("x", 13)]);
    close.addEventListener("click", closeDetail);
    header.appendChild(close);
    inner.appendChild(header);

    const tabs = h("div", { class: "detail-tabs" });
    const tabDefs = state.archive
      ? [["metadata", "Metadata"], ["media", "Media"], ["sources", "Sources"]]
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

    // Description은 남는 세로 공간을 우선 흡수한다(스펙 §34).
    const descWrap = h("div", { class: "detail-body-desc-wrap" });
    descWrap.appendChild(h("div", { class: "field-label" }, ["Description"]));
    const desc = h("textarea", { class: "field-input" });
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

  function renderMediaTab(body) {
    body.classList.add("media-tab-body");
    const media = S.detailState.media || {};

    const tile = (label, key, cls) => {
      const zone = h("div", { class: `media-tile ${cls || ""}`.trim() });
      zone.appendChild(h("div", { class: "media-tile-label" }, [label]));
      const preview = h("div", { class: "media-tile-preview" });
      if (key === "Videos" && media[key]) {
        preview.appendChild(h("div", { class: "dropzone-empty" }, [icon("upload", 18), "영상 등록됨"]));
      } else if (media[key]) {
        const img = h("img", { alt: label });
        preview.appendChild(img);
        loadMediaImage(img, key, false);
      } else {
        preview.appendChild(h("div", { class: "dropzone-empty" }, [icon("imageOff", 18), `${label} 없음`]));
      }
      zone.appendChild(preview);
      return zone;
    };

    const hero = h("div", { class: "media-quad-grid" }, [
      tile("Cover", "Covers", "cover"),
      tile("Marquee", "Marquees", "marquee"),
      tile("MixImage", "Miximages", "miximage"),
      tile("Wheel", "Wheel", "wheel"),
    ]);
    body.appendChild(hero);
    body.appendChild(h("div", { class: "media-lower-grid" }, [tile("Screenshot", "Screenshots", "screenshot")]));
    if (media.Videos) body.appendChild(tile("Video", "Videos", "video"));
  }

  // 출처별 Metadata를 나란히 보여준다(스펙 §44). 같은 게임이 여러 Collection에서
  // 왔을 때 어느 쪽 값이 맞는지 사용자가 판단할 수 있어야 한다.
  function renderSourcesTab(body) {
    const sources = S.detailState.sources || [];
    if (!sources.length) {
      body.appendChild(h("div", { class: "empty-msg" }, ["출처 정보가 없습니다."]));
      return;
    }
    sources.forEach((source) => {
      const box = h("div", { class: "storage-box" });
      const name = source.collectionId === "__archive__"
        ? "Archive에서 직접 편집"
        : (S.collections.find((c) => c.id === source.collectionId) || {}).name || source.collectionId;
      box.appendChild(h("div", { class: "storage-box-title" }, [`${name} · rev ${source.revision}`]));
      [["Title", "name"], ["Genre", "genre"], ["Developer", "developer"],
       ["Release", "releasedate"], ["Region", "region"]].forEach(([label, key]) => {
        box.appendChild(h("div", { class: "health-row" }, [
          h("span", {}, [label]),
          h("span", { class: "truncate" }, [(source.fields || {})[key] || "-"]),
        ]));
      });
      body.appendChild(box);
    });
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
    renderStatusBar();
    renderListWindow();
  }

  const planCapacity = (storageId) =>
    ((S.plan && S.plan.capacity) || []).find((c) => c.storageId === storageId) || null;

  async function copySelection() {
    if (!S.selected.size) { showToast("복사할 항목을 선택하세요.", "warning"); return; }
    const r = await api.copySelection(S.activeId, [...S.selected]);
    if (!r.ok) { showToast(r.error, "error"); return; }
    await refreshPlan();
    // 다른 창에서도 붙여넣을 수 있다(결정 D5).
    showToast(`${formatCount(r.data.count)}개를 복사했습니다. 다른 창에서도 붙여넣을 수 있습니다.`);
  }

  async function pasteIntoActive() {
    const r = await api.paste(S.activeId);
    if (!r.ok) { showToast(r.error, "error"); return; }
    await refreshPlan();
    const skipped = (r.data.skipped || []).length;
    const suffix = skipped ? ` (원본이 없어 ${skipped}개 제외)` : "";
    if (S.autoPlan) showToast(`${formatCount(r.data.added)}개를 Plan에 올렸습니다${suffix}.`);
    else await applyPlan();
  }

  async function deleteSelection() {
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
      ["건너뛰기", "덮어쓰기"].forEach((label, i) => {
        const btn = h("button", { class: "btn compact" }, [label]);
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
        `목적지에 같은 이름의 다른 파일이 있는 항목 ${formatCount(entries.length)}개입니다. ` +
        "크기가 같아도 내용이 다를 수 있어 자동으로 덮어쓰지 않습니다."]),
      list,
    ]);
    showModal("충돌 확인", body, [
      h("button", { class: "btn", onClick: closeModal }, ["나중에"]),
      h("button", { class: "btn", onClick: async () => {
        closeModal();
        await api.planResolveAllConflicts(S.activeId, "skip");
        await refreshPlan();
      } }, ["모두 건너뛰기"]),
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
    if (isArchive()) {
      const targets = S.tabs.filter((t) => t !== ARCHIVE_ID);
      const send = h("button", {
        class: "btn compact primary", disabled: !S.selected.size || !targets.length,
        title: targets.length ? "선택 항목을 Collection으로 보냅니다"
                              : "먼저 대상 Collection을 열어주세요",
      }, ["Collection으로 보내기"]);
      if (S.selected.size && targets.length) send.addEventListener("click", openSendToCollection);
      actions.appendChild(send);
      bar.appendChild(actions);
      return;
    }

    const ingest = h("button", { class: "btn compact",
      title: "이 Collection의 Metadata를 Archive에 수집합니다" },
      [icon("database", 12), h("span", {}, ["Archive에 수집"])]);
    ingest.addEventListener("click", ingestToArchive);
    actions.appendChild(ingest);

    const autoBtn = h("button", { class: "btn compact" + (S.autoPlan ? " primary" : ""),
      title: "Auto Plan: 변경을 바로 적용하지 않고 먼저 계산합니다" },
      [S.autoPlan ? "✓ Auto Plan" : "Auto Plan OFF"]);
    autoBtn.addEventListener("click", toggleAutoPlan);
    actions.appendChild(autoBtn);

    [["Copy", copySelection, !S.selected.size],
     ["Paste", pasteIntoActive, !(plan && plan.clipboard)],
     ["Delete", deleteSelection, !S.selected.size]].forEach(([label, fn, disabled]) => {
      const btn = h("button", { class: "btn compact", disabled: disabled || !detail }, [label]);
      if (!disabled && detail) btn.addEventListener("click", fn);
      actions.appendChild(btn);
    });

    const applyBtn = h("button", {
      class: "btn compact primary", disabled: !(plan && plan.total),
      title: plan && plan.total ? "Plan을 실제 파일에 적용합니다" : "적용할 Plan이 없습니다",
    }, [plan && plan.total ? `Apply (${formatCount(plan.total)})` : "Apply"]);
    if (plan && plan.total) applyBtn.addEventListener("click", applyPlan);
    actions.appendChild(applyBtn);

    if (plan && plan.total) {
      const discard = h("button", { class: "btn compact", title: "Plan 비우기" }, [icon("eraser", 12)]);
      discard.addEventListener("click", () => showConfirm("Plan 비우기", "계산해둔 변경을 모두 버립니다.", true,
        async () => { await api.planClear(S.activeId); await refreshPlan(); }));
      actions.appendChild(discard);
    }
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

  function bindEvents() {
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
        if (S.detailState && S.detailState.tab === "metadata") handleSaveDetail();
        return;
      }
      // 입력 중에는 목록 단축키가 끼어들면 안 된다.
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!S.activeId) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c") { e.preventDefault(); copySelection(); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") { e.preventDefault(); pasteIntoActive(); }
      else if (e.key === "Delete") { e.preventDefault(); deleteSelection(); }
    });
  }

  async function init() {
    bindEvents();
    await loadCollections();
    renderAll();
    if (S.collections.length) await openTab(S.collections[0].id);
    else openCollectionPicker();
  }

  if (window.pywebview) init();
  else window.addEventListener("pywebviewready", init);
  // 브라우저에서 직접 열었을 때(목업 모드)는 ready 이벤트가 없다.
  setTimeout(() => { if (!S.collections.length && !$("tabs-bar").firstChild) init(); }, 400);
})();
