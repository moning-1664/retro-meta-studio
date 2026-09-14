/* ==========================================================================
   settings.js — Settings 화면

   화면 구성(7개 섹션, 좌측 목록 + 우측 내용)은 ui/stitch-v2-redesign의 것을 그대로
   따른다. 다른 점은 **구조**다:

   - 설정 값의 주인은 app.js다. 이 모듈은 `ctx.get()`으로 읽고 `ctx.update()`로만
     바꾼다 - 그 브랜치처럼 localStorage에 따로 저장하거나, 다른 버튼의 클릭을
     가로채서 열리지 않는다.
   - **실제로 동작하는 항목만 켠다.** 아직 기능이 없는 항목은 자리를 지키되
     "준비 중"으로 표시하고 조작할 수 없게 둔다. 눌러도 아무 일도 안 일어나는
     스위치는 사용자를 속인다.
   ========================================================================== */
(function () {
  "use strict";

  const SECTIONS = [
    ["general", "General", "프로그램의 기본 동작"],
    ["collections", "Collections", "Collection 열기와 세션"],
    ["metadata", "Metadata & Media", "목록과 메타데이터 표시"],
    ["transfer", "Import / Export", "가져오기와 내보내기"],
    ["emulator", "Emulator", "RetroArch 연동"],
    ["appearance", "Appearance", "테마와 화면 밀도"],
    ["advanced", "Advanced", "캐시와 진단"],
  ];

  const THEMES = [
    ["stitch", "Stitch / Original"],
    ["sfc", "White / SFC"],
    ["md", "Black / MD"],
    ["nes", "NES / Family"],
  ];

  const SCALE = { min: 80, max: 130, step: 5 };

  function open(ctx) {
    const { h } = ctx;
    const root = document.getElementById("modal-root");
    let active = ctx.section || "appearance";

    while (root.firstChild) root.removeChild(root.firstChild);
    const overlay = h("div", { class: "modal-overlay stg-overlay" });
    const panel = h("div", { class: "stg-panel", role: "dialog", "aria-label": "Settings" });
    const close = () => { while (root.firstChild) root.removeChild(root.firstChild); };

    const head = h("div", { class: "stg-head" }, [
      h("div", {}, [
        h("div", { class: "stg-eyebrow" }, ["APPLICATION SETTINGS"]),
        h("div", { class: "stg-title" }, ["Settings"]),
      ]),
      h("button", { class: "stg-close", title: "닫기 (Esc)", onClick: close }, ["×"]),
    ]);
    const nav = h("div", { class: "stg-nav" });
    const main = h("div", { class: "stg-main" });
    panel.appendChild(head);
    panel.appendChild(h("div", { class: "stg-body" }, [nav, main]));
    overlay.appendChild(panel);
    // 바깥(어두운 영역)을 누르면 닫는다 - 패널 안에서 끌다가 바깥에서 놓는 경우는 닫지 않는다.
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    root.appendChild(overlay);

    function render() {
      while (nav.firstChild) nav.removeChild(nav.firstChild);
      SECTIONS.forEach(([id, name, desc]) => {
        const item = h("button", {
          class: "stg-nav-item" + (id === active ? " active" : ""), "data-section": id,
        }, [h("div", { class: "stg-nav-name" }, [name]), h("div", { class: "stg-nav-desc" }, [desc])]);
        item.addEventListener("click", () => { active = id; render(); });
        nav.appendChild(item);
      });
      while (main.firstChild) main.removeChild(main.firstChild);
      main.appendChild(content(active));
    }

    // ---------------------------------------------------------------- 컨트롤
    function row(key, label, control, help, soon) {
      return h("div", { class: "stg-row" + (soon ? " soon" : ""), "data-key": key }, [
        h("div", { class: "stg-label" }, [
          h("div", { class: "stg-name" }, [label, soon ? h("span", { class: "stg-soon" }, ["준비 중"]) : null]),
          help ? h("div", { class: "stg-help" }, [help]) : null,
        ]),
        control,
      ]);
    }
    function select(value, options, onChange, disabled) {
      const el = h("select", { class: "stg-control", disabled: !!disabled });
      options.forEach(([v, text]) => {
        const opt = h("option", { value: v }, [text]);
        if (String(v) === String(value)) opt.selected = true;
        el.appendChild(opt);
      });
      if (onChange) el.addEventListener("change", () => onChange(el.value));
      return el;
    }
    function toggle(checked, onChange, disabled) {
      const input = h("input", { type: "checkbox", disabled: !!disabled });
      input.checked = !!checked;
      if (onChange) input.addEventListener("change", () => onChange(input.checked));
      return h("label", { class: "stg-switch" }, [input, h("span", { class: "stg-slider" })]);
    }
    function textInput(placeholder) {
      return h("input", { class: "stg-control stg-text", placeholder, disabled: true });
    }
    function section(title, desc) {
      return [h("div", { class: "stg-section-title" }, [title]),
              h("div", { class: "stg-section-desc" }, [desc])];
    }
    const soonSelect = (options) => select(options[0][0], options, null, true);
    const soonToggle = (checked) => toggle(checked, null, true);

    // ---------------------------------------------------------------- 섹션
    function content(key) {
      const c = h("div", { class: "stg-content", "data-section": key });
      const add = (...nodes) => nodes.forEach((n) => c.appendChild(n));
      const s = ctx.get();

      if (key === "general") {
        add(...section("General", "RetroMeta Studio의 전역 동작을 설정합니다."));
        add(row("general.language", "Language", soonSelect([["ko", "한국어"], ["en", "English"]]), null, true));
        add(row("general.startup", "Startup", soonSelect([["last", "마지막 상태 복원"], ["archive", "항상 Archive"]]), null, true));
        add(row("general.autoSave", "Auto Save", soonToggle(false), "편집한 Metadata를 자동 저장합니다.", true));
        add(row("general.confirmDelete", "Confirm before delete", soonToggle(true), null, true));
      } else if (key === "collections") {
        add(...section("Collections", "Collection 자체의 경로가 아니라 열기/복원 동작을 설정합니다."));
        add(row("collections.restoreTabs", "Restore open tabs", soonToggle(true), null, true));
        add(row("collections.rememberSystem", "Remember last System", soonToggle(true), null, true));
        add(h("div", { class: "stg-info" }, ["ROM / Metadata / Media 경로는 Collection 탭의 우클릭 메뉴에서 관리합니다."]));
      } else if (key === "metadata") {
        add(...section("Metadata & Media", "목록 표시와 Metadata/Media의 기본 처리 정책입니다."));
        add(h("div", { class: "stg-subsection-title" }, ["GameList Columns"]));
        add(ctx.renderColumns ? ctx.renderColumns() :
          h("div", { class: "stg-info" }, ["컬럼 순서/표시 설정은 준비 중입니다."]));
        add(row("media.overwrite", "Media overwrite", soonSelect([["ask", "Always ask"], ["replace", "Replace"], ["keep", "Keep existing"]]), null, true));
      } else if (key === "transfer") {
        add(...section("Import / Export", "파일과 Metadata/Media를 옮길 때의 기본값입니다."));
        add(ctx.renderTransfer ? ctx.renderTransfer() :
          h("div", { class: "stg-info" }, ["Collection → Collection 복사 정책은 준비 중입니다."]));
        add(row("transfer.backup", "Backup before overwrite", soonToggle(false), null, true));
      } else if (key === "emulator") {
        add(...section("Emulator", "외부 에뮬레이터 실행에 필요한 설정입니다."));
        add(row("emulator.retroarchPath", "RetroArch executable", textInput("예: C:\\RetroArch\\retroarch.exe"), null, true));
        add(row("emulator.corePolicy", "Core selection", soonSelect([["system", "System별 Core"], ["manual", "실행 시 선택"]]), null, true));
      } else if (key === "appearance") {
        const a = s.appearance;
        add(...section("Appearance", "Stitch 기본 디자인과 콘솔 세대별 색상 테마를 선택합니다."));
        add(row("appearance.theme", "Theme",
          select(a.theme, THEMES, (v) => ctx.update("appearance", { theme: v })),
          "Stitch는 절제된 어두운 기본 팔레트입니다. SFC는 콘솔 버튼 4색, MD는 빨강+금색, NES는 베이지+빨강+금색을 씁니다."));
        add(row("appearance.density", "UI Density",
          select(a.density, [["compact", "Compact"], ["normal", "Normal"]], (v) => ctx.update("appearance", { density: v })),
          "Normal은 목록 한 줄을 조금 더 높게 씁니다."));

        const value = h("span", { class: "stg-range-value" }, [`${a.scale}%`]);
        const range = h("input", { type: "range", min: SCALE.min, max: SCALE.max, step: SCALE.step, value: a.scale });
        range.addEventListener("input", () => {
          value.textContent = `${range.value}%`;
          ctx.update("appearance", { scale: Number(range.value) });
        });
        add(row("appearance.scale", "UI Scale", h("div", { class: "stg-range" }, [range, value]),
          "Ctrl + 마우스 휠로도 바로 바꿀 수 있습니다."));
        add(row("appearance.previewDefault", "Preview by default",
          toggle(a.previewDefault, (v) => ctx.update("appearance", { previewDefault: v })),
          "처음 여는 Collection에서 미리보기를 켤지 정합니다. 이미 연 Collection은 마지막 상태를 따릅니다."));
      } else {
        add(...section("Advanced", "일반 사용자가 자주 만질 필요가 없는 진단 옵션입니다."));
        add(row("advanced.logLevel", "Log level", soonSelect([["normal", "Normal"], ["verbose", "Verbose"], ["debug", "Debug"]]), null, true));
        const reset = h("button", { class: "stg-danger" }, ["화면 설정 초기화"]);
        reset.addEventListener("click", () => { ctx.reset(); render(); });
        add(row("advanced.reset", "Reset UI Settings", reset, "테마·밀도·크기를 기본값으로 되돌립니다."));
      }
      return c;
    }

    render();
    return { rerender: render };
  }

  window.RMSSettings = { open, THEMES, SCALE };
})();
