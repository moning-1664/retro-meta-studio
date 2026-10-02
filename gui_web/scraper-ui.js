/* Scraper settings and session UI. Application state is supplied by app.js. */
(function () {
  "use strict";
  window.RMSScraperUI = {
    create(context) {
      const { $, IC, MEDIA_LABEL, PAGE_SIZE, S, activeDetail, api, clear, closeModal, copyTextToClipboard, currentQuery, fetchRows, formatCount, h, icon, isArchive, msg, openDetail, openSettings, pollJob, reloadList, renderDetailPanel, rowAtIndex, rowKey, scrollToIndex, showModal, showToast, systemIcon, updateSelectionVisual } = context;
    function scraperSettingsEditor() {
        const wrap = h("div", { class: "stg-scraper" }, [h("div", { class: "stg-info" }, [window.RMSI18n.t("ui.legacy.605a0a3cfd")])]);
        const draw = async () => {
          const result = await api.scraperSettings();
          clear(wrap);
          if (!result.ok) { wrap.appendChild(h("div", { class: "stg-info" }, [window.RMSI18n.formatError(result.error)])); return; }
          const cfg = result.data;
          wrap.appendChild(h("div", { class: "stg-info" }, [
            cfg.devIdSet && cfg.devPasswordSet
              ? msg("ui.scraper.account", {user: cfg.userId || window.RMSI18n.t("ui.scraper.notLoggedIn")})
              : window.RMSI18n.t("ui.legacy.924e8b3f04"),
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
              const checked = await pollJob(started.data.jobId, window.RMSI18n.t("ui.legacy.8361045f8d"), progressHost);
              test.disabled = false;
              if (!checked.ok) { status.textContent = checked.error; return; }
              status.textContent = window.RMSI18n.t(msg("ui.scrape.accountResult", {quota:scrapeQuotaText(checked.data),threads:checked.data.maxThreads || window.RMSI18n.t("ui.scrape.unknown")}));
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
            const picked = await api.pickFile(window.RMSI18n.t("ui.legacy.3cebf2a745"), ["XML files (*.xml;*.dat)"]);
            if (!picked.ok || !picked.data) return;
            datButton.disabled = true;
            const started = await api.startDatImport(picked.data, systemSelect.value);
            if (!started.ok) {
              datStatus.textContent = started.error;
              datButton.disabled = false;
              return;
            }
            const completed = await pollJob(started.data.jobId, window.RMSI18n.t("ui.legacy.cbc69812c1"), datProgress);
            datStatus.textContent = completed.ok
              ? window.RMSI18n.t(msg("ui.dat.imported", {name:completed.data.name,system:completed.data.system,count:completed.data.games.toLocaleString()}))
              : completed.error;
            datButton.disabled = false;
            if (completed.ok) refreshDatSources();
          } }, ["DAT 추가…"]);
          const datSources = h("div", { class: "stg-help" });
          const refreshDatSources = async () => {
            const sources = await api.datSources();
            datSources.textContent = !sources.ok ? sources.error
              : sources.data.length
                ? sources.data.map((source) => window.RMSI18n.t(msg("ui.dat.source", {name:source.name,system:source.system,count:source.entries.toLocaleString()}))).join(" · ")
                : window.RMSI18n.t("ui.scraper.datEmpty");
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
          h("button", { class: "btn", onClick: async (event) => {
            const button = event.currentTarget;
            button.disabled = true;
            const patch = { enabled: true, softName: softName.value.trim(), userId: userId.value.trim() };
            if (devId.value) patch.devId = devId.value;
            if (devPassword.value) patch.devPassword = devPassword.value;
            if (userPassword.value) patch.userPassword = userPassword.value;
            try {
              const saved = await api.saveScraperSettings(patch);
              if (!saved.ok) { connectionResult.textContent = window.RMSI18n.t(msg("ui.scrape.connectionFailed", {error:window.RMSI18n.formatError(saved.error)})); return; }
              const started = await api.startScraperAccountStatus();
              if (!started.ok) { connectionResult.textContent = window.RMSI18n.t(msg("ui.scrape.connectionFailed", {error:window.RMSI18n.formatError(started.error)})); return; }
              const host = h("div", { class: "stg-progress" });
              body.appendChild(host);
              const checked = await pollJob(started.data.jobId, window.RMSI18n.t("ui.legacy.bfcde009ac"), host);
              connectionResult.textContent = checked.ok ? window.RMSI18n.t(msg("ui.scrape.connectionSuccess", {quota:scrapeQuotaText(checked.data)})) : window.RMSI18n.t(msg("ui.scrape.connectionFailed", {error:window.RMSI18n.formatError(checked.error)}));
            } finally { button.disabled = false; }
          } }, ["연결 테스트"]),
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
        const connectionResult = h("div", { class: "scrape-connection-result", role: "status" });
        card.querySelector(".modal-actions").prepend(connectionResult);
      }
    
      function scrapeQuotaText(quota) {
        if (!quota) return window.RMSI18n.t("ui.scrape.checkingUsage");
        const used = Number(quota.requestsToday || 0);
        const limit = Number(quota.requestsLimit || 0);
        return limit ? window.RMSI18n.t(msg("ui.scrape.quota", {used:formatCount(used), limit:formatCount(limit)}))
          : window.RMSI18n.t(msg("ui.scrape.quotaUnknown", {used:formatCount(used)}));
      }
    
      async function openScrapeContext(itemIds) {
        const rememberedDetailTab = S.detailState?.tab || "metadata";
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
        const candidateScroll = new Map();
        let closed = false;
        let selecting = false;
        let applying = false;
    
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
          if (searching || selecting || applying || closed) return;
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
          if (!item.error && (item.candidates || []).length === 1
              && item.status !== "applied" && item.status !== "skipped") {
            const candidate = item.candidates[0];
            await selectCandidateFor(item, candidate, Object.keys(candidate.fields || {}),
              (candidate.media || []).map((_, mediaIndex) => mediaIndex));
          }
          draw();
        }
    
        async function selectCandidateFor(item, candidate, fields, media) {
          if (selecting || applying || searching || closed) return;
          selecting = true;
          draw();
          try {
            const selected = await api.selectScrapeCandidate(session.id, item.id,
              candidate.candidate_id, fields, media);
            if (!selected.ok) { showToast(selected.error, "error"); return; }
            item.selectedCandidateId = candidate.candidate_id;
            item.selectedFields = fields;
            item.selectedMedia = media;
            item.status = "selected";
            delete item.applyError;
          } finally {
            selecting = false;
            if (!closed) draw();
          }
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
          const wrap = h("div", { class: "scrape-candidate" + (previouslySelected ? " selected" : ""),
            tabindex: "0", role: "radio", "aria-checked": String(previouslySelected),
            "aria-disabled": String(searching || selecting || applying) });
          const selectCandidate = async () => {
              const selectedFieldKeys = [...selectedFields];
              await selectCandidateFor(item, candidate, selectedFieldKeys, [...selectedMedia]);
          };
          wrap.addEventListener("click", (event) => {
            if (!event.target.closest("button,input,label")) selectCandidate();
          });
          wrap.addEventListener("keydown", (event) => {
            if (event.target === wrap && (event.key === "Enter" || event.key === " ")) {
              event.preventDefault(); selectCandidate();
            }
          });
          const redraw = () => {
            clear(wrap);
            wrap.classList.toggle("expanded", expanded);
            const cover = (candidate.media || []).find((m) => m.media_type === "covers")
              || (candidate.media || []).find((m) => m.media_type === "screenshots");
            const thumb = cover
              ? h("img", { class: "scrape-thumb", src: cover.url, alt: candidate.title, referrerpolicy: "no-referrer" })
              : h("div", { class: "scrape-thumb empty" }, [icon("image", IC.md)]);
            if (cover) thumb.addEventListener("error", () => {
              thumb.replaceWith(h("div", { class: "scrape-thumb empty", title: window.RMSI18n.t("ui.legacy.184fe48d86") }, [icon("image", IC.md)]));
            }, { once: true });
            const toggle = h("button", { class: "icon-btn scrape-expand", title: expanded ? "접기" : "자세히" },
              [icon(expanded ? "chevronUp" : "chevronDown", IC.sm)]);
            toggle.addEventListener("click", () => {
              expanded = !expanded;
              if (expanded) expandedCandidates.add(candidate.candidate_id);
              else expandedCandidates.delete(candidate.candidate_id);
              redraw();
            });
            const description = String(candidate.fields?.desc || "").replace(/\s+/g, " ").trim();
            wrap.appendChild(h("div", { class: "scrape-candidate-head" }, [thumb,
              h("div", { class: "scrape-candidate-main" }, [
                h("div", { class: "scrape-candidate-top" }, [
                  h("span", { class: "scrape-system-icon", title: candidate.system || item.system },
                    [systemIcon(item.systemHint || item.system, 16)]),
                  h("div", { class: "scrape-candidate-title", "data-i18n-skip": "", title: window.RMSI18n.raw(candidate.title || "") },
                    [candidate.title ? window.RMSI18n.raw(candidate.title) : window.RMSI18n.t(window.RMSI18n.t("ui.legacy.a1609f9b95"))]),
                  Number(candidate.confidence || 0) < 45
                    ? h("span", { class: "scrape-review-icon",
                      title: candidate.confidence_reason || "낮은 유사도 · 직접 확인 필요",
                      "aria-label": "낮은 유사도 · 직접 확인 필요" },
                    [icon("triangleAlert", IC.xs)]) : null,
                ]),
                h("div", { class: "scrape-candidate-desc", "data-i18n-skip": "", title: window.RMSI18n.raw(description) }, [description ? window.RMSI18n.raw(description) : window.RMSI18n.t("설명 없음")]),
                window.RMSCandidateUI.facts(h, candidate.fields, toggle),
              ])]));
            if (!expanded) return;
            if ((candidate.evidence || []).length) wrap.appendChild(h("div", { class: "scrape-evidence" },
              candidate.evidence.map((value) => h("div", {}, [value]))));
            wrap.appendChild(window.RMSCandidateUI.fields(h, candidate.fields, {
              current: item.fields || {}, selected: selectedFields,
              onChange: (key, checked) => {
                if (checked) selectedFields.add(key); else selectedFields.delete(key);
                if (item.selectedCandidateId === candidate.candidate_id) selectCandidate();
              },
            }));
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
          const item = session.items[index];
          return item.status === "selected"
            && (item.candidates || []).some((candidate) => candidate.candidate_id === item.selectedCandidateId)
            && ((item.selectedFields || []).length > 0 || (item.selectedMedia || []).length > 0);
        }
    
        async function finish() {
          if (applying || searching || selecting || !hasSelection()) return;
          applying = true;
          body.querySelectorAll("button, input, select").forEach((control) => { control.disabled = true; });
          try {
            await applySelection();
          } finally {
            applying = false;
            if (!closed) draw();
          }
        }
    
        async function applySelection() {
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
            showToast(window.RMSI18n.t(msg("ui.scrape.applySummary", {applied:formatCount((applied.data.applied || []).length)}))
              + (partialCount ? window.RMSI18n.t(msg("ui.scrape.partialCount", {count:formatCount(partialCount)})) : "")
              + (failedCount ? window.RMSI18n.t(msg("ui.scrape.failedCount", {count:formatCount(failedCount)})) : ""),
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
            // The apply job is complete. Release its guard before starting the
            // next search, which manages its own busy state and candidate selection.
            applying = false;
            showToast(window.RMSI18n.t("ui.legacy.cd71e2b7a4", {value0: (formatCount(appliedIds.size))}));
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
          showToast(msg("ui.scrape.finished", {count:formatCount(applied.data.applied.length)}));
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
            await openDetail(row, rememberedDetailTab);
            let after = -1;
            const visited = new Set();
            while (true) {
              const result = isArchive()
                ? await api.archiveFindRowIndex(currentQuery(), reviewed.filename, after)
                : await api.findRowIndex(S.activeId, currentQuery(), reviewed.filename, after);
              const position = result.ok ? result.data : -1;
              if (position < 0 || visited.has(position)) break;
              visited.add(position);
              const found = await rowAtIndex(position);
              if (found?.system === reviewed.system && found?.file === reviewed.filename) {
                scrollToIndex(position, rowKey(found));
                break;
              }
              after = position;
            }
          } else {
            S.focused = null;
            renderDetailPanel();
            updateSelectionVisual();
          }
        }
    
        function draw() {
          const oldCandidates = body.querySelector(".scrape-candidates");
          if (oldCandidates && body.dataset.itemId) candidateScroll.set(body.dataset.itemId, oldCandidates.scrollTop);
          clear(body);
          const item = session.items[index];
          body.dataset.itemId = String(item.id);
          titleCount.textContent = window.RMSI18n.t(msg("ui.scrape.result", {index:index+1,total:session.items.length}));
          const head = h("div", { class: "scrape-context-head" }, [
            h("span", { class: "scrape-file-tag" }, ["ROM"]),
            h("span", { class: "scrape-current-file", title: item.filename }, [item.filename]),
            h("button", { class: "icon-btn scrape-file-copy", title: "ROM 이름 복사",
              onClick: () => copyTextToClipboard(
                String(item.filename || "").replace(/\.[^.]+$/, ""), window.RMSI18n.t("ui.legacy.c7b6366d01")) },
            [icon("copy", IC.sm)]),
          ]);
          quotaBadge.textContent = scrapeQuotaText(quota);
          quotaBadge.title = window.RMSI18n.t(quota?.estimated ? "ui.scrape.estimatedUsage" : "ui.scrape.usageHelp");
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
              retry.textContent = window.RMSI18n.t("ui.scrape.stopping");
              if (currentJobId) api.cancelJob(currentJobId);
            } else retrySearch();
          } }, [searching ? "스크랩 중지" : "스크랩 시작"]);
          query.disabled = searching || selecting || applying;
          system.disabled = searching || selecting || applying;
          retry.disabled = selecting || applying;
          body.appendChild(head);
          body.appendChild(h("div", { class: "scrape-search-row" }, [
            h("label", {}, [h("span", {}, ["검색명"]), query]),
            h("label", {}, [h("span", {}, ["시스템"]), system])]));
          body.appendChild(h("div", { class: "scrape-progress" }));
          body.appendChild(h("div", { class: "scrape-results-head" }, [
            h("span", {}, [msg("ui.scrape.candidateCount", {count:(item.candidates || []).length})]), retry,
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
              [msg("ui.scrape.applyFailed", {error:window.RMSI18n.formatError(item.applyError)})]));
          const candidates = h("div", { class: "scrape-candidates" });
          if (searching) candidates.appendChild(h("div", { class: "panel-empty-state" }, ["검색 중…"]));
          else if (item.error) candidates.appendChild(h("div", { class: "modal-text error" }, [window.RMSI18n.formatError(item.error)]));
          else if (!(item.candidates || []).length && item.status !== "pending")
            candidates.appendChild(h("div", { class: "panel-empty-state" },
              ["후보가 없습니다. 검색 키나 시스템을 바꾸고 다시 스크랩하세요."]));
          else if (!(item.candidates || []).length)
            candidates.appendChild(h("div", { class: "panel-empty-state" },
              ["검색명과 시스템을 확인한 뒤 스크랩 시작을 누르세요."]));
          else (item.candidates || []).forEach((candidate) => candidates.appendChild(candidateCard(item, candidate)));
          body.appendChild(candidates);
          candidates.scrollTop = candidateScroll.get(String(item.id)) || 0;
          if (searching || selecting || applying) candidates.querySelectorAll("button,input").forEach((control) => { control.disabled = true; });
    
          const previous = h("button", { class: "btn", disabled: index === 0 || searching || selecting || applying,
            onClick: () => { index -= 1; draw(); } }, ["이전 스크랩"]);
          const skip = h("button", { class: "btn", disabled: searching || selecting || applying, onClick: async () => {
            if (item.status !== "selected" && item.status !== "applied") {
              const skipped = await api.skipScrapeItem(session.id, item.id);
              if (!skipped.ok) { showToast(skipped.error, "error"); return; }
              item.status = "skipped";
            }
            if (index + 1 < session.items.length) { index += 1; draw(); } else draw();
          } }, ["다음 스크랩"]);
          const actions = h("div", { class: "scrape-actions" }, [previous, skip,
            h("span", { class: "scrape-action-spacer" }),
            h("button", { class: "btn", disabled: applying, onClick: cancel }, ["취소"]),
            h("button", { class: "btn primary", disabled: !hasSelection() || searching || selecting || applying, onClick: finish },
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
      return { scraperSettingsEditor, openScraperSetup, openScrapeContext };
    }
  };
})();
