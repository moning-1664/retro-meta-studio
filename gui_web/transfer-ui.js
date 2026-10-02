/* UI module. Shared application state is injected by app.js. */
(function () {
  "use strict";
  window.RMSTransferUI = {
    create(context) {
      const { $, IC, S, activeScope, api, archiveDetailState, blockedInCompare, clear, closeModal, formatBytes, formatCount, h, icon, indexOfRow, isArchive, msg, pollJob, refreshPlan, reloadList, renderAll, renderDetailPanel, resetList, restoreGameFocus, rowByUid, selectedRowKey, showConfirm, showModal, showToast } = context;
    async function copySelectedRows() {
        if (blockedInCompare("복사")) return;
        if (!S.selected.size) { showToast("복사할 항목을 선택하세요.", "warning"); return; }
        const r = isArchive()
          ? await api.archiveCopySelection([...S.selected])
          : await api.copySelection(S.activeId, [...S.selected]);
        if (!r.ok) { showToast(r.error, "error"); return; }
        showToast(msg("ui.copy.completed", {count:formatCount(r.data.count)}));
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
          showToast(window.RMSI18n.t("ui.legacy.d457ee2e15", {value0: (formatCount(d.pasted || 0))})
            + ((d.copiedRoms || 0) ? window.RMSI18n.t("ui.legacy.523ae4c007", {value0: (formatCount(d.copiedRoms))}) : "")
            + ((d.conflicts || []).length ? window.RMSI18n.t("ui.legacy.d45f266575", {value0: (formatCount(d.conflicts.length))}) : "")
            + ((d.skipped || []).length ? window.RMSI18n.t("ui.legacy.4a76ddaa04", {value0: (formatCount(d.skipped.length)), value1: (d.skipped[0].reason || window.RMSI18n.t("ui.legacy.4c5dcbc26c"))}) : ""),
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
            showToast(window.RMSI18n.t("ui.legacy.520bb22935"), "warning");
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
        showToast(left.length ? window.RMSI18n.t("ui.legacy.f59818def6", {value0: (left[0].reason)})
          : window.RMSI18n.t("ui.legacy.06e8898ba5"), "warning");
      }
    
      async function acceptOperationPreview(preview) {
        if (!preview.operationId) { showToast(window.RMSI18n.t("ui.legacy.75572bc9cf"), "error"); return; }
        if (preview.collisions?.length) openPasteConflictDialog(preview);
        else await executePasteOperation(preview, {});
      }
    
      async function runCompareOperation(options) {
        const response = await api.compareOperationPreview(options);
        if (!response.ok) { showToast(response.error, "error"); return; }
        if (!response.data.count) { showToast(response.data.skipped?.[0]?.reason || window.RMSI18n.t("ui.legacy.4a99344c54"), "warning"); return; }
        if (response.data.collisions?.length) openPasteConflictDialog(response.data);
        else await executePasteOperation(response.data, {});
      }
    
      async function runImmediateAction(action, options) {
        let response;
        if (action === "archive-import") {
          const started = await api.startArchiveImportPreview(S.activeId, options);
          if (!started.ok) { showToast(started.error, "error"); return; }
          response = await pollJob(started.data.jobId, window.RMSI18n.t("ui.legacy.28363408e6"));
        } else response = await api.operationPreview(S.activeId, action, options);
        if (!response.ok) { showToast(response.error, "error"); return; }
        if (!response.data.count) { showToast(response.data.skipped?.[0]?.reason || window.RMSI18n.t("ui.legacy.cb3865a74c")); return; }
        if (response.data.collisions?.length) openPasteConflictDialog(response.data);
        else await executePasteOperation(response.data, {});
      }
    
      async function executePasteOperation(preview, decisions, acknowledged = false) {
        const operationLabel = window.RMSI18n.t(({ title: window.RMSI18n.t("ui.legacy.3906d4ee9b"), disc: window.RMSI18n.t("ui.legacy.3479f43bd1"), move: window.RMSI18n.t("ui.legacy.8389ba5869"),
          storage: window.RMSI18n.t("ui.legacy.9d67156750"), media: "미디어 붙여넣기", compare: window.RMSI18n.t("ui.legacy.7e7ba30284"), convert: window.RMSI18n.t("ui.legacy.97d396f42f"), import: "가져오기", "archive-import": "가져오기" })[preview.action] || "붙여넣기");
        if (!preview.undoable && !acknowledged) {
          showConfirm(window.RMSI18n.t("ui.legacy.3799853cdf", {value0: (operationLabel)}),
            preview.target === "archive"
              ? "Archive에는 변경 이력이 남지만 파일 전체 되돌리기는 아직 보장하지 못합니다. 계속할까요?"
              : window.RMSI18n.t("ui.legacy.a156c835e3"),
            true, () => executePasteOperation(preview, decisions, true));
          return;
        }
        const collectionId = S.activeId;
        const compareSnapshot = preview.action === "compare" ? S.compare : null;
        const focused = S.focused == null ? null : rowByUid(S.focused);
        const focusedIndex = Math.max(0, indexOfRow(S.focused));
        const detailTab = S.detailState?.tab || "metadata";
        const started = await api.pasteExecute(preview.operationId, decisions, acknowledged);
        if (!started.ok) { showToast(started.error, "error"); return; }
        if (!started.data.jobId) { showToast(window.RMSI18n.t("ui.legacy.f431567720")); return; }
        const result = await pollJob(started.data.jobId, window.RMSI18n.t("ui.legacy.8714af5080", {value0: (operationLabel)}));
        if (!result.ok) { showToast(result.error || window.RMSI18n.t("ui.legacy.3583791930"), "error"); return; }
        const data = result.data || {};
        if (data.undoOperationId) S.lastPasteUndoId = data.undoOperationId;
        showToast((data.rolledBack ? window.RMSI18n.t("ui.legacy.56f60c868c", {value0: (operationLabel)}) : window.RMSI18n.t("ui.legacy.0c61b8d318", {value0: (operationLabel), value1: (formatCount(data.applied || 0))}))
          + (data.failed ? window.RMSI18n.t("ui.legacy.17d1480882", {value0: (formatCount(data.failed))}) : "")
          + (data.partial ? window.RMSI18n.t("ui.legacy.c7d7fc1f42", {value0: (formatCount(data.partial))}) : ""),
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
        await reloadList({ autoSelect: false });
        if (S.activeId !== collectionId) return;
        await restoreGameFocus(focused, detailTab, focusedIndex);
        await refreshPlan();
      }
    
      async function undoLastPaste() {
        if (!S.activeId) return;
        const collectionId = S.activeId;
        const focused = S.focused == null ? null : rowByUid(S.focused);
        const focusedIndex = Math.max(0, indexOfRow(S.focused));
        const detailTab = S.detailState?.tab || "metadata";
        const started = await api.pasteUndo(isArchive() ? "__archive__" : collectionId);
        if (!started.ok) { showToast(started.error, "warning"); return; }
        const result = await pollJob(started.data.jobId, window.RMSI18n.t("ui.legacy.9c0df60bc7"));
        if (!result.ok) { showToast(result.error, "error"); return; }
        S.lastPasteUndoId = null;
        if (S.activeId === collectionId) {
          resetList();
          await reloadList({ autoSelect: false });
          if (S.activeId === collectionId) await restoreGameFocus(focused, detailTab, focusedIndex);
        }
    
        showToast(window.RMSI18n.t("ui.legacy.b19d486221"), "success");
        await refreshPlan();
      }
    
      async function redoLastOperation() {
        const activeId = S.activeId;
        const focused = S.focused == null ? null : rowByUid(S.focused);
        const focusedIndex = Math.max(0, indexOfRow(S.focused));
        const detailTab = S.detailState?.tab || "metadata";
        const id = isArchive() ? "__archive__" : S.activeId;
        const started = await api.pasteRedo(id);
        if (!started.ok) { showToast(started.error, "warning"); return; }
        const result = await pollJob(started.data.jobId, window.RMSI18n.t("ui.legacy.16f187fffc"));
        if (!result.ok) { showToast(result.error, "error"); return; }
        if (S.activeId !== activeId) return;
        resetList();
        await reloadList({ autoSelect: false });
        if (S.activeId !== activeId) return;
        await restoreGameFocus(focused, detailTab, focusedIndex);
        await refreshPlan();
        showToast(window.RMSI18n.t("ui.legacy.c87da5c0da"), "success");
      }
    
      async function openOperationHistory() {
        const id = isArchive() ? "__archive__" : S.activeId;
        const result = await api.operationHistory(id);
        if (!result.ok) { showToast(result.error, "error"); return; }
        const rows = result.data.items || [];
        const labels = {committed: "완료", undone: "실행 취소", recovered: "복구됨", recovery_failed: "복구 실패", closed: "닫힘 · 백업 유지", running: "복구 필요", restoring: "복구 필요", redoing: "복구 필요"};
        const actions = {paste: "붙여넣기", add: "붙여넣기", delete: "삭제", rename: "이름 변경", move: window.RMSI18n.t("ui.legacy.8389ba5869"), metadata_edit: window.RMSI18n.t("ui.legacy.da8b8cc661"), "file-operation": window.RMSI18n.t("ui.legacy.1217166fa0"), archive_edit: window.RMSI18n.t("ui.legacy.da8b8cc661"), archive_rename: "이름 변경", archive_rom_delete: "ROM 삭제", archive_delete: window.RMSI18n.t("ui.legacy.b1d272fc25")};
        const body = h("div", {class: "modal-body operation-history-body"});
        if (result.data.recoveryError) body.appendChild(h("div", {class: "field-help"}, [window.RMSI18n.formatError(result.data.recoveryError)]));
        body.appendChild(h("div", {class: "field-help"}, [msg("ui.history.summary", {count:rows.length,size:formatBytes(rows.reduce((sum,row)=>sum+row.bytes,0))})]));
        for (const row of rows) {
          const recover = async (action) => {
            const response = await api.recoveryAction(id, row.id, action);
            if (!response.ok) { showToast(response.error, "error"); return; }
            if (action !== "open") { closeModal(); await refreshPlan(); await reloadList(); await openOperationHistory(); }
          };
          body.appendChild(h("div", {class: "field-row operation-history-row"}, [
            h("span", {class: "field-help"}, [msg("ui.history.row", {date:new Date(row.createdAt*1000).toLocaleString(),action:window.RMSI18n.t(actions[row.action] || "Archive 편집"),status:window.RMSI18n.t(labels[row.status] || row.status),size:formatBytes(row.bytes)})]),
            h("button", {class: "btn", disabled: !row.canDiscard, onClick: () => {
              showConfirm("백업 삭제", row.status === "closed" ? window.RMSI18n.t("ui.legacy.83ea668416") : window.RMSI18n.t("ui.legacy.3c6968d5de"), true, async () => {
                const removed = await api.discardOperationHistory(id, [row.id], true);
                if (!removed.ok) { showToast(removed.error, "error"); return; }
                closeModal(); await refreshPlan(); await openOperationHistory();
              });
            }}, ["백업 삭제"]),
            ...(row.canForceRecovery ? [
              h("button", {class: "btn", onClick: () => showConfirm("소유자 확인 불가 · 수동 복구",
                "다른 RetroMeta Studio 앱을 모두 종료했는지 확인하세요. 실행 중인 작업을 복구하면 파일이 되돌려질 수 있습니다. 파일·DB 변경 검사는 유지합니다.", true, () => recover("force"))}, ["수동 복구…"]),
            ] : []),
            ...(row.status === "recovery_failed" ? [
              h("button", {class: "btn", onClick: () => recover("retry")}, ["다시 시도"]),
              h("button", {class: "btn", onClick: () => recover("open")}, ["백업 폴더 열기"]),
              h("button", {class: "btn", onClick: () => showConfirm("복구 기록 닫기",
                "현재 파일을 유지하고 자동 복구를 종료합니다. 백업은 남습니다.", false, () => recover("close"))}, ["기록 닫기(백업 유지)"]),
            ] : []),
          ]));
          if (row.recoveryError) body.appendChild(h("div", {class: "field-help"}, [window.RMSI18n.formatError(row.recoveryError)]));
        }
        showModal("작업 기록", body, [h("button", {class: "btn", onClick: closeModal}, ["닫기"])]);
      }
    
      function openPasteConflictDialog(preview) {
        const toast = $("toast");
        if (toast?.classList.contains("info")) toast.classList.remove("show");
        const collisions = preview.collisions || [];
        const decisions = {};
        let position = 0;
        let selectedChoice = "skip";
        let resolving = false;
        let keepButton, overwriteButton;
        const body = h("div", { class: "modal-body paste-conflict-body" });
        const applyRemaining = h("input", { type: "checkbox" });
        const render = () => {
          clear(body);
          selectedChoice = "skip";
          keepButton?.classList.add("primary");
          overwriteButton?.classList.remove("primary");
          const item = collisions[position];
          if (!item) return;
          body.appendChild(h("div", { class: "modal-hint" }, [
            msg("ui.paste.summary", {source:window.RMSI18n.t(preview.source || window.RMSI18n.t("ui.legacy.e828d32bbf")),target:preview.target === "archive" ? "Archive" : window.RMSI18n.t("현재 Collection"),count:formatCount(preview.count),conflicts:formatCount(collisions.length),index:position+1,total:collisions.length}),
          ]));
          body.appendChild(h("div", { class: "paste-conflict-filename" },
            [msg("ui.paste.exists", {filename:item.filename})]));
          const makeSide = (label, title, desc, fields, incoming) => {
            const cover = h("img", { alt: window.RMSI18n.t("ui.legacy.375e858515"), class: "paste-conflict-thumb" });
            const screen = h("img", { alt: window.RMSI18n.t("ui.legacy.efc2b3cebb"), class: "paste-conflict-thumb" });
            const detailCover = h("img", { alt: window.RMSI18n.t("ui.legacy.375e858515"), class: "scrape-thumb" });
            [cover, screen, detailCover].forEach((image) => { image.style.visibility = "hidden"; });
            const expanded = h("div", { class: "paste-conflict-expanded scrape-candidate" }, [
              h("div", { class: "scrape-candidate-head" }, [
                detailCover,
                h("div", { class: "scrape-candidate-main" }, [
                  h("span", { class: "scrape-candidate-title", "data-i18n-skip": "" }, [window.RMSI18n.raw(title)]),
                  h("span", { class: "scrape-candidate-desc", "data-i18n-skip": "" }, [desc ? window.RMSI18n.raw(desc) : window.RMSI18n.t("설명 없음")]),
                  window.RMSCandidateUI.facts(h, fields),
                ]),
              ]),
            ]);
            const fieldRows = window.RMSCandidateUI.fields(h, fields);
            expanded.appendChild(fieldRows);
            const detailScreen = h("img", { class: "candidate-screenshot", alt: window.RMSI18n.t("ui.legacy.efc2b3cebb"), hidden: true });
            expanded.appendChild(detailScreen);
            const toggle = h("button", { class: "btn compact paste-conflict-expand",
              title: "자세히 보기", "aria-expanded": "false" }, [icon("chevronDown", IC.sm)]);
            toggle.addEventListener("click", () => {
              const open = expanded.classList.toggle("open");
              toggle.setAttribute("aria-expanded", String(open));
            });
            const row = h("div", { class: "paste-conflict-side" + (!incoming ? " selected" : ""),
              title: window.RMSI18n.raw(desc || title), tabindex: "0", role: "radio", "aria-checked": String(!incoming) }, [
              h("span", { class: "paste-conflict-side-label" }, [label]),
              h("span", { class: "paste-conflict-side-title truncate" }, [window.RMSI18n.raw(title)]),
              cover, screen, toggle, expanded,
            ]);
            const selectSide = () => {
              selectedChoice = incoming ? "overwrite" : "skip";
              body.querySelectorAll(".paste-conflict-side").forEach((side) => {
                const selected = side === row;
                side.classList.toggle("selected", selected);
                side.setAttribute("aria-checked", String(selected));
              });
              keepButton?.classList.toggle("primary", !incoming);
              overwriteButton?.classList.toggle("primary", incoming);
            };
            row.addEventListener("click", (event) => {
              if (!event.target.closest("button,input,label")) selectSide();
            });
            row.addEventListener("keydown", (event) => {
              if (event.target === row && (event.key === " " || event.key === "Enter")) {
                event.preventDefault(); selectSide();
                if (event.key === "Enter") choose(selectedChoice);
              }
            });
            const romFacts = item.romComparison?.[incoming ? "incoming" : "existing"];
            if (romFacts) {
              const size = romFacts.size == null ? window.RMSI18n.t("ui.legacy.23c969799f") : formatBytes(romFacts.size);
              const modified = romFacts.modifiedAt == null ? window.RMSI18n.t("ui.legacy.e83f4ac461")
                : new Date(romFacts.modifiedAt).toLocaleString();
              const text = `ROM · ${size} · ${modified}`;
              row.insertBefore(h("div", { class: "paste-conflict-rom truncate", title: text }, [text]), expanded);
            }
            row.addEventListener("dblclick", (event) => {
              if (!event.target.closest("button")) choose(incoming ? "overwrite" : "skip");
            });
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
                  if (type === "screenshots") { detailScreen.src = result.data; detailScreen.hidden = false; }
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
          if (resolving) return;
          resolving = true;
          keepButton.disabled = true;
          overwriteButton.disabled = true;
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
          } else {
            resolving = false;
            keepButton.disabled = false;
            overwriteButton.disabled = false;
            render();
          }
        };
        render();
        keepButton = h("button", { class: "btn primary", onClick: () => choose("skip") }, ["이 게임 건너뛰기"]);
        overwriteButton = h("button", { class: "btn", onClick: () => choose("overwrite") }, ["기존 게임 덮어쓰기"]);
        const card = showModal("같은 이름의 게임", body, [
          h("button", { class: "btn", onClick: closeModal }, ["취소"]),
          keepButton, overwriteButton,
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
              h("option", { value: "" }, [window.RMSI18n.t("ui.legacy.9f18124c91", {value0: (entry.system)})]),
              ...targets.map((name) => h("option", { value: name }, [name.toUpperCase()])),
            ]);
            return { entry, select };
          });
          const body = h("div", { class: "modal-body paste-system-map" }, [
            h("div", { class: "modal-text" }, [
              window.RMSI18n.t("ui.legacy.846fe308f0", {value0: (formatCount(missing.length))})]),
            h("div", { class: "modal-hint" }, [
              window.RMSI18n.t("ui.legacy.0306bace0e")]),
            ...selects.map(({ entry, select }) => h("div", { class: "paste-system-row" }, [
              h("div", { class: "field-label" }, [window.RMSI18n.t("ui.legacy.b8543eea48", {value0: (entry.system), value1: (formatCount(entry.count))})]),
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
      return { copySelectedRows, pasteClipboard, acceptOperationPreview, runCompareOperation, runImmediateAction, executePasteOperation, undoLastPaste, redoLastOperation, openOperationHistory, openPasteConflictDialog, askPasteSystemMap };
    }
  };
})();
