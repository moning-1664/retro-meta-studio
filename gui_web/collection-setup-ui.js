/* UI module. Shared application state is injected by app.js. */
(function () {
  "use strict";
  window.RMSCollectionSetupUI = {
    create(context) {
      const { ES_STYLE_FRONTEND_IDS, Event, IC, S, api, closeModal, defaultCollectionName, formatCount, h, icon, inspectFolderInBackground, loadCollections, msg, openTab, runScan, showModal, showToast } = context;
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
                                       placeholder: msg("ui.collection.optionalFolder") });
        const romInput = h("input", { class: "field-input", id: "add-rom-path",
                                      placeholder: msg("ui.collection.optionalFolder") });
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
          h("option", { value: "" }, [msg("ui.collection.auto")]),
          h("option", { value: "windows" }, ["Windows"]),
          h("option", { value: "android" }, ["Android"]),
          h("option", { value: "linux" }, ["Linux"]),
        ]);
        targetSel.title = window.RMSI18n.t("ui.collection.targetHelp");
        const frontendSel = h("select", { class: "field-input", id: "add-frontend" },
          [h("option", { value: "" }, ["저장 형식 선택"]),
            ...frontends.map((f) => h("option", { value: f.id }, [f.label]))]);
        const detectionInfo = h("div", { class: "folder-detection", role: "status" },
          [window.RMSI18n.t("ui.collection.detectHelp")]);
        let detectionPath = "";
        let lastDetection = null;
        let detectionRun = 0;
        let detectionJobId = null;
        function showDetectedFolder(data) {
          const findings = data.findings.map((f) =>
            (frontends.find((item) => item.id === f.frontend) || {}).label || f.frontend);
          detectionInfo.textContent = findings.length
            ? window.RMSI18n.t("ui.legacy.031fa070a8", {value0: (findings.join(" · ")), value1: (data.suggestedFrontend ? "" : (" " + window.RMSI18n.t("ui.legacy.538c2b801e")))})
            : window.RMSI18n.t("ui.legacy.d6ef408284");
          detectionInfo.title = data.findings.map((finding) => finding.evidence).join(" · ");
        }
        async function inspectSelectedFolder() {
          const run = ++detectionRun;
          if (detectionJobId) api.cancelJob(detectionJobId);
          detectionJobId = null;
          const path = pathInput.value.trim();
          detectionPath = path;
          lastDetection = null;
          if (source !== "local" || !path) {
            detectionInfo.textContent = path ? window.RMSI18n.t("ui.legacy.f9b2e36056") : window.RMSI18n.t("ui.collection.detectHelp");
            return;
          }
          detectionInfo.replaceChildren((window.RMSI18n.t("ui.legacy.f640ae798a") + " "), h("button", {
            class: "btn compact", onClick: () => {
              detectionRun++;
              if (detectionJobId) api.cancelJob(detectionJobId);
              detectionInfo.textContent = "폴더 확인을 중지했습니다.";
            },
          }, [window.RMSI18n.t("ui.legacy.ddb7af8ef7")]));
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
          if (data.selectedPath && data.path) pathInput.value = data.path;
          if (data.suggestedRomDir && !romInput.value.trim()) romInput.value = data.suggestedRomDir;
          if (data.suggestedFrontend) frontendSel.value = data.suggestedFrontend;
          syncFrontend();
          showDetectedFolder(data);
        }
        pathInput.addEventListener("change", inspectSelectedFolder);
    
        const pathLabel = h("div", { class: "field-label" }, [window.RMSI18n.t("ui.collection.frontend")]);
        const romLabel = h("div", { class: "field-label" }, ["ROM 디렉토리"]);
        const extRomInput = h("input", { class: "field-input", id: "add-ext-rom-path",
                                         placeholder: msg("ui.collection.optionalFolder") });
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
        const upBtn = h("button", { class: "mtp-up-btn", title: window.RMSI18n.t("ui.legacy.01e6d2c2ec") }, [icon("cornerUpLeft", 14)]);
        const browserList = h("div", { class: "picker-list mtp-list", id: "mtp-browser" });
        const browserHead = h("div", { class: "mtp-browser-head" }, [upBtn, breadcrumb]);
        const browserBox = h("div", { class: "field-block", hidden: true }, [browserHead, browserList]);
        browserBox.classList.add("folder-picker");
        upBtn.className = "mtp-up-btn btn compact";
        let browserRequest = 0;
        let browseTarget = null, browsePath = null;
    
        function rowButton(name, sub, iconName, onClick) {
          const row = h("button", { class: "picker-row", title: window.RMSI18n.raw(sub) });
          row.appendChild(icon(iconName, 14));
          row.appendChild(h("div", { class: "picker-main" }, [h("div", { class: "picker-name" }, [window.RMSI18n.raw(name)])]));
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
            const seg = h("button", { class: "mtp-crumb" + (isLast ? " current" : ""), disabled: isLast }, [window.RMSI18n.raw(label)]);
            if (!isLast) seg.addEventListener("click", () => { browsePath = target; renderBrowser(); });
            breadcrumb.appendChild(seg);
            if (!isLast) breadcrumb.appendChild(h("span", { class: "mtp-crumb-sep" }, [icon("chevronRight", 11)]));
          });
        }
    
        async function renderBrowser() {
          const request = ++browserRequest;
          const requestedPath = browsePath;
          browserList.replaceChildren();
          browserList.appendChild(h("div", { class: "empty-msg mtp-loading" }, ["불러오는 중…"]));
          upBtn.disabled = true;
          const r = await api.mtpBrowse(browsePath);
          if (browsePath === null || request !== browserRequest || browsePath !== requestedPath) return;
          browserList.replaceChildren();
          if (!r.ok) { browserList.appendChild(h("div", { class: "empty-msg" }, [window.RMSI18n.formatError(r.error)])); return; }
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
          const selectedPath = h("div", { class: "field-hint folder-picker-path", title: data.path }, [data.path]);
          browserList.appendChild(selectedPath);
          browserList.appendChild(h("div", { class: "folder-picker-actions" }, [
          h("button", { class: "btn", onClick: () => { browserBox.hidden = true; browsePath = null; browserRequest++; } }, ["취소"]),
          h("button", { class: "btn primary", id: "mtp-pick-here",
            onClick: () => {
              browseTarget.value = browsePath;
              if (browseTarget === pathInput && !nameInput.value.trim()) {
                const device = (S.mtpDevices || []).find((d) => d.key === deviceSel.value);
                nameInput.value = device ? device.name : "";
              }
              browserBox.hidden = true;
              browseTarget.dispatchEvent(new Event("change"));
          } }, ["이 폴더 선택"])]));
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
            : msg("ui.collection.optionalFolder");
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
            ? window.RMSI18n.t("ui.legacy.fe9e8d3409", {value0: (defaultCollectionName(label))})
            : window.RMSI18n.t("ui.collection.nameHelp");
        }
    
        function syncFrontend() {
          syncNamePlaceholder();
          const isEs = ES_STYLE_FRONTEND_IDS.has(frontendSel.value);
          pathLabel.textContent = window.RMSI18n.t("ui.collection.frontend");
          pathLabel.title = isEs
            ? window.RMSI18n.t("ES-DE의 gamelists와 downloaded_media가 포함된 디렉토리입니다.")
            : window.RMSI18n.t("ui.collection.frontendHelp");
          pathInput.title = pathLabel.title;
          romLabel.title = window.RMSI18n.t("ui.collection.romHelp");
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
        const advanced = advancedBody;
    
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
            if (!frontendSel.value) { showToast(window.RMSI18n.t("ui.legacy.8714e99d3b"), "warning"); return; }
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
              else showToast(window.RMSI18n.t("ui.legacy.47d210de80", {value0: (ext.error)}), "warning");
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
      return { openAddCollection };
    }
  };
})();
