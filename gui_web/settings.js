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
    ["scraper", "Scraper", "외부 게임 정보 검색"],
    ["transfer", "Import / Export", "가져오기와 내보내기"],
    ["archive", "Archive", "저장 형식과 위치"],
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
    const close = () => {
      window.__rmsSettingsRerender = null;
      while (root.firstChild) root.removeChild(root.firstChild);
    };

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
    // **좌측 하단 확인 버튼**(실사용 결정) - 구석의 ×만으로 닫는 것보다, "확인을
    // 누르면 적용되고 사라진다"는 편이 더 또렷하다. 값 자체는 이미 바뀔 때마다
    // 즉시 반영돼 있으므로(슬라이더 미리보기 등) 이 버튼이 하는 일은 아직 안 나간
    // 저장을 그 자리에서 흘려보내고 닫는 것이다 - 취소가 아니라 확인이다.
    const confirmBtn = h("button", { class: "btn primary stg-confirm" }, ["확인"]);
    confirmBtn.addEventListener("click", async () => {
      if (ctx.flush) await ctx.flush();
      close();
    });
    panel.appendChild(h("div", { class: "stg-foot" }, [confirmBtn]));
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
    window.__rmsSettingsRerender = () => { if (root.contains(panel)) render(); };

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
    /** 1% 단위 슬라이더(사용자 결정, 메뉴 정리 §9) - 예전 6단계 select보다 세밀하게
     * 고를 수 있다. 옆의 숫자는 지금 값을 그 자리에서 보여준다. */
    function volumeSlider(value, onChange) {
      const wrap = h("div", { class: "stg-range" });
      const input = h("input", { type: "range", min: "0", max: "100", step: "1", value: String(value) });
      const readout = h("span", { class: "stg-range-value" }, [`${value}%`]);
      input.addEventListener("input", () => { readout.textContent = `${input.value}%`; });
      input.addEventListener("change", () => onChange(Number(input.value)));
      wrap.appendChild(input);
      wrap.appendChild(readout);
      return wrap;
    }
    function section(title, desc) {
      return [h("div", { class: "stg-section-title" }, [title]),
              h("div", { class: "stg-section-desc" }, [desc])];
    }
    const soonSelect = (options) => select(options[0][0], options, null, true);
    const soonToggle = (checked) => toggle(checked, null, true);

    /** Title Prefix/Postfix - 5개 구역(한국/영어권/일본/유럽/글로벌) 줄마다 켜짐 여부·
     * Prefix/Postfix·붙일 텍스트를 정한다(app/title_affix.py의 DEFAULT_CONFIG와 같은 구역).
     *
     * `ctx.update()`는 패널을 다시 그리지 않으므로, 한 구역
     * 안에서 여러 필드를 잇달아 바꿔도 항상 최신 값을 함께 보내도록 `state`에 누적해 둔다 -
     * 안 그러면 나중에 바꾼 필드가 먼저 바꾼 필드를 예전 값으로 되돌려 보낸다("titleAffix"
     * 섹션도 한 단계 깊이까지만 병합되므로, 이 구역 하나는 항상 통째로 보내야 한다).
     */
    /** 장 번호 표기 형식. 보기는 **백엔드가 실제로 만든 것**을 가져온다 - 설명과
     * 동작이 어긋나지 않게 한다. */
    function discFormatRow(s) {
      const current = (s.metadata || {}).discTitleFormat || "paren_word_slash";
      const el = select(current, [[current, current]], (v) => ctx.update("metadata", { discTitleFormat: v }));
      window.api.discTitleFormats().then((r) => {
        if (!r.ok) return;
        // 실제로 적용되는 예시만 보여준다(사용자 결정, 메뉴 정리 §9) - 플로피 표기까지
        // 괄호로 함께 보여주면 "이게 무슨 뜻이냐"는 혼란만 더했다. Disc/Disk 중 어느
        // 낱말이 붙는지는 System 종류(title_affix._DISK_SYSTEMS)가 정하고, 여기서는
        // 형식(괄호/대괄호, 총 장수 표기 방식)만 고른다.
        el.replaceChildren(...r.data.map((f) => {
          const opt = h("option", { value: f.id }, [f.sample]);
          if (f.id === current) opt.selected = true;
          return opt;
        }));
      });
      return row("metadata.discTitleFormat", "표기 형식", el);
    }

    function titleAffixEditor(s) {
      const REGIONS = [["kr", "한국(KR)"], ["en", "영어권(EN)"], ["jp", "일본(JP)"],
                       ["eu", "유럽(EU)"], ["global", "글로벌"]];
      const wrap = h("div", { class: "stg-title-affix", "data-key": "titleAffix" });
      REGIONS.forEach(([bucket, label]) => {
        let state = { ...s.titleAffix[bucket] };
        const commit = (patch) => {
          state = { ...state, ...patch };
          ctx.update("titleAffix", { [bucket]: state });
        };
        const textInput = h("input", {
          class: "stg-control stg-text stg-title-affix-text", value: state.text,
          placeholder: "예: KR", disabled: !state.enabled,
        });
        textInput.addEventListener("change", () => commit({ text: textInput.value }));
        const modeSelect = select(state.mode,
          [["prefix", "제목 앞에 (Prefix)"], ["postfix", "제목 뒤에 (Postfix)"]],
          (v) => commit({ mode: v }), !state.enabled);
        const rowEl = h("div", { class: "stg-title-affix-row" + (state.enabled ? "" : " off") }, [
          toggle(state.enabled, (v) => {
            commit({ enabled: v });
            modeSelect.disabled = !v;
            textInput.disabled = !v;
            rowEl.classList.toggle("off", !v);
          }),
          h("span", { class: "stg-title-affix-label" }, [label]),
          modeSelect,
          textInput,
        ]);
        wrap.appendChild(rowEl);
      });
      return wrap;
    }


    // ---------------------------------------------------------------- 섹션
    function content(key) {
      const c = h("div", { class: "stg-content", "data-section": key });
      const add = (...nodes) => nodes.forEach((n) => c.appendChild(n));
      const s = ctx.get();

      if (key === "general") {
        add(...section("General", "RetroMeta Studio의 전역 동작을 설정합니다."));
        const currentLanguage = (s.general && s.general.language) || "ko";
        // 언어 이름은 **그 나라 고유 표기**로 보여준다(사용자 결정, 메뉴 정리 §9) - "한국어"
        // 처럼 흔한 UI 문구와 겹치는 문자열은 i18n 번역표를 거치면 "Korean"처럼 옮겨져
        // 버렸다. h()의 문자열 자식은 모두 번역을 거치므로, 이미 만든 Text 노드를 건네
        // 그 통로를 피한다(h()는 노드를 그대로 붙이고 문자열만 옮긴다).
        add(row("general.language", "Language",
          select(currentLanguage,
            (window.RMSI18n ? window.RMSI18n.LANGS.map((code) => [code, window.RMSI18n.LABELS[code]])
              : [["ko", "한국어"], ["en", "English"], ["ja", "日本語"], ["es", "Español"], ["fr", "Français"]])
              .map(([code, label]) => [code, document.createTextNode(label)]),
            (v) => ctx.update("general", { language: v })), null));
        add(row("general.startup", "Startup", soonSelect([["last", "마지막 상태 복원"], ["archive", "항상 Archive"]]), null, true));
        add(row("general.autoSave", "Auto Save", soonToggle(false), "편집한 Metadata를 자동 저장합니다.", true));
        add(row("general.confirmDelete", "Confirm before delete", soonToggle(true), null, true));
      } else if (key === "collections") {
        add(...section("Collections", "Collection 자체의 경로가 아니라 열기/복원 동작을 설정합니다."));
        const coll = { restoreTabs: true, rememberSystem: true, ...(s.collections || {}) };
        add(row("collections.restoreTabs", "Restore open tabs",
          toggle(coll.restoreTabs !== false, (v) => ctx.update("collections", { restoreTabs: v })),
          "앱을 다시 켜면 마지막에 열어 둔 Collection 탭을 모두 되살립니다(끄면 첫 Collection만 엽니다)."));
        add(row("collections.rememberSystem", "Remember last System",
          toggle(coll.rememberSystem !== false, (v) => ctx.update("collections", { rememberSystem: v })),
          "Collection마다 마지막으로 고른 System/Storage에서 시작합니다."));
        add(row("navigation.hideEmptySystems", "Hide empty systems",
          toggle(s.navigation && s.navigation.hideEmptySystems,
            (v) => ctx.update("navigation", { hideEmptySystems: v })),
          "좌측 SYSTEMS 목록에서 게임이 없는 System을 숨깁니다. SYSTEMS 제목 옆 눈 아이콘으로도 바꿀 수 있습니다."));
        // 우선 정렬(실사용 피드백) - 예전 상태 필터는 실제로 아무것도 걸러내지
        // 못했다. 그 자리를 "ROM/Metadata/Media가 있는 항목을 먼저 보여주는"
        // 1차 정렬로 바꾸면서, Collection을 새로 열 때 기본으로 쓸 값도 여기서
        // 정할 수 있게 했다 - Toolbar에서 그때그때 바꾼 값은 이 기본값과 별개다.
        add(row("navigation.defaultSortPriority", "Default sort priority",
          select(s.navigation && s.navigation.defaultSortPriority || "none", [
            ["none", "전체보기"], ["rom", "ROM 우선"],
            ["metadata", "메타데이터 우선"], ["media", "미디어 우선"],
          ], (v) => ctx.update("navigation", { defaultSortPriority: v })),
          "Collection을 새로 열 때 목록의 기본 우선 정렬입니다. Toolbar에서 그때그때 바꿀 수 있습니다."));
        add(h("div", { class: "stg-info" }, ["ROM / Metadata / Media 경로는 Collection 탭의 우클릭 메뉴에서 관리합니다."]));
      } else if (key === "metadata") {
        add(...section("Metadata & Media", "목록 표시와 Metadata/Media의 기본 처리 정책입니다."));
        add(h("div", { class: "stg-subsection-title" }, ["GameList Columns"]));
        add(ctx.renderColumns ? ctx.renderColumns() :
          h("div", { class: "stg-info" }, ["컬럼 순서/표시 설정은 준비 중입니다."]));
        const m = { videoMode: "auto", videoDelay: 3, videoSound: true, videoLoop: true,
                    videoVolume: 70, ...(s.media || {}) };
        add(h("div", { class: "stg-subsection-title" }, ["Video"]));
        add(row("media.videoMode", "영상 재생",
          select(m.videoMode, [["auto", "자동 재생"], ["manual", "눌러서 재생"], ["off", "재생 안 함"]],
            (v) => ctx.update("media", { videoMode: v })),
          "Media 탭의 Screenshot 자리에서 영상을 보여줍니다. 재생 중에 누르면 멈춥니다."));
        add(row("media.videoDelay", "자동 재생 대기",
          select(m.videoDelay, [[0, "0초"], [1, "1초"], [3, "3초"], [5, "5초"], [10, "10초"], [15, "15초"]],
            (v) => ctx.update("media", { videoDelay: Number(v) })),
          "게임을 고르고 이 시간만큼 그대로 두면 재생합니다. 그 전에 다른 게임으로 넘기면 재생하지 않습니다."));
        add(row("media.videoSound", "소리", toggle(m.videoSound, (v) => ctx.update("media", { videoSound: v }))));
        add(row("media.videoVolume", "음량", volumeSlider(m.videoVolume,
            (v) => ctx.update("media", { videoVolume: v })),
          "소리를 켰을 때의 재생 음량입니다."));
        add(row("media.videoLoop", "반복 재생", toggle(m.videoLoop, (v) => ctx.update("media", { videoLoop: v }))));
        add(row("media.overwrite", "Media overwrite", soonSelect([["ask", "Always ask"], ["replace", "Replace"], ["keep", "Keep existing"]]), null, true));
        add(h("div", { class: "stg-subsection-title" }, ["Title Prefix/Postfix"]));
        add(h("div", { class: "stg-help" }, [
          "구역은 ROM 파일명의 지역 태그로 정합니다 - (KR), [Kor], _k, (USA), global 같은 표시입니다. "
          + "해당 구역이 켜져 있으면 제목 양 끝의 기존 장식을 떼고(디스크 표시는 보존) 아래 텍스트를 "
          + "다시 붙입니다. 태그가 없는 파일은 미분류라 건드리지 않습니다. "
          + "문구 앞뒤의 공백은 그대로 쓰입니다(예: \" (KR)\"). 파일명에 지역이 여럿이면((Japan, Europe)) 켜진 구역의 "
          + "문구를 모두 붙이고, 같은 괄호면 [JP][EU]가 [JP,EU]로 합쳐집니다. "
          + "실행은 Gamelist나 System 우클릭 메뉴에서 합니다.",
        ]));
        add(titleAffixEditor(s));

        // 여러 장짜리 게임 - ES-DE는 목록에 파일명을 안 보여줘서 제목이 전부 같아 보인다.
        // 이름은 사용자 결정(메뉴 정리 §9) - "장 번호"는 비직관적이라 "디스크 번호"로 바꿨다.
        add(h("div", { class: "stg-subsection-title" }, ["멀티디스크 태그"]));
        add(row("metadata.discTitles", "제목 뒤에 디스크 번호 태그 붙이기",
          toggle(!!(s.metadata || {}).discTitles, (v) => ctx.update("metadata", { discTitles: v })),
          "Apply할 때 제목 뒤에만 붙입니다. 파일명은 건드리지 않고, 두 번 적용해도 늘어나지 않습니다. "
          + "CD를 쓰는 System은 Disc, 플로피를 쓰는 System(MSX, PC-98 등)은 Disk로 적습니다."));
        add(discFormatRow(s));
      } else if (key === "scraper") {
        add(...section("Scraper", "ScreenScraper 계정과 요청 사용량을 관리합니다."));
        add(ctx.renderScraper ? ctx.renderScraper()
          : h("div", { class: "stg-info" }, ["Scraper 설정을 불러올 수 없습니다."]));
      } else if (key === "transfer") {
        add(...section("Import / Export", "파일과 Metadata/Media를 옮길 때의 기본값입니다."));
        // 붙여넣기(bridge paste)가 이 값을 읽는다. 기본값은 예전 동작 그대로다.
        // unmatchedRom*은 registry에 평평하게 저장한다(bridge/api.py TRANSFER_DEFAULTS 참고) -
        // "transfer" 섹션 patch는 한 단계 깊이까지만 병합되므로, 중첩 객체로 두면 필드 하나만
        // 바꿔도 나머지가 지워진다.
        const t = {
          pasteMode: "patch", includeRom: true, includeMedia: true, conflict: "ask",
          unmatchedRomMode: "skip", unmatchedRomMetadata: true, unmatchedRomMedia: true, unmatchedRomVideo: true,
          ...(s.transfer || {}),
        };
        // 이름은 사용자 결정(메뉴 정리 §9) - "Collection → Collection 복사 (Ctrl+C / Ctrl+V)"는
        // 무엇을 하는 구역인지보다 조작 방법이 앞서 보였다.
        //
        // "같은 파일이 이미 있을 때"(transfer.conflict)와 "ROM 미매칭일 때"(unmatchedRomPolicy)
        // 두 항목은 화면에서 뺐다(사용자 결정, 메뉴 정리 §9 후속) - patch/overwrite/replace와
        // 겹치지 않는 별개의 경우(엉뚱한 파일이 이미 있음 / 대상 자체가 없어 새로 생김)를 다루는
        // 것은 맞지만, 그 구분 자체가 사용자에게 혼란만 줬다. **기능은 그대로 둔다** - 저장된
        // 값이 없으면 기본값(둘 다 "Plan에서 직접 고르기"/"복사 안 함"에 준하는 값)을 그대로
        // 쓰므로(bridge/api.py TRANSFER_DEFAULTS), 화면에서 안 보여도 동작은 바뀌지 않는다.
        add(h("div", { class: "stg-subsection-title" }, ["Collection 간 복사 설정"]));
        add(row("transfer.pasteMode", "붙여넣기 모드",
          select(t.pasteMode, [["patch", "Patch - 보완(없는 것만 채움)"], ["overwrite", "Overwrite - 덮어쓰기(원본 값 적용)"],
                               ["replace", "Replace - 완전 교체(원본으로 다시 만듦)"]],
            (v) => ctx.update("transfer", { pasteMode: v })),
          "Patch: 이미 있는 항목의 빈 값과 없는 미디어만 채웁니다. Overwrite: 원본의 값과 미디어가 대상 것을 대신합니다. "
          + "Replace: 게임의 메타데이터와 미디어를 원본으로 다시 만듭니다. 상단 Plan 버튼 옆에서도 바꿀 수 있습니다."));
        add(row("transfer.includeRom", "ROM 파일 복사",
          toggle(t.includeRom, (v) => ctx.update("transfer", { includeRom: v })),
          "켜면 **대상에 ROM 파일이 없을 때만** 원본 ROM을 복사합니다. 이미 있는 ROM은 어느 모드에서도 덮어쓰지 않습니다."));
        add(row("transfer.includeMedia", "Media 복사",
          toggle(t.includeMedia, (v) => ctx.update("transfer", { includeMedia: v })),
          "끄면 커버·스크린샷·동영상을 옮기지 않습니다."));
        add(row("transfer.backup", "Backup before overwrite", soonToggle(false), null, true));
      } else if (key === "archive") {
        add(...section("Archive", "Archive를 어디에 어떤 형식으로 저장할지 정합니다."));
        add(ctx.renderArchive ? ctx.renderArchive()
          : h("div", { class: "stg-info" }, ["Archive 설정은 준비 중입니다."]));
      } else if (key === "emulator") {
        add(...section("Emulator", "외부 에뮬레이터 실행에 필요한 설정입니다."));
        add(ctx.renderEmulator ? ctx.renderEmulator()
          : h("div", { class: "stg-info" }, ["RetroArch 설정은 준비 중입니다."]));
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
