/* UI module. Shared application state is injected by app.js. */
(function () {
  "use strict";
  window.RMSArchiveSettingsUI = {
    create(context) {
      const { ARCHIVE_ID, Event, IC, api, clear, closeModal, ensureDetail, formatCount, h, icon, inspectFolderInBackground, isArchive, loadArchiveConfigured, msg, pollJob, reloadList, renderAll, resetList, showConfirm, showModal, showToast } = context;
    function archiveSettingsEditor(onApplied) {
        const wrap = h("div", { class: "stg-archive" });
        let lastDiagnostics = "";
        const draw = async () => {
          const [cfgR, feR] = await Promise.all([api.archiveConfig(), api.frontends()]);
          clear(wrap);
          if (!cfgR.ok) { wrap.appendChild(h("div", { class: "stg-info" }, [window.RMSI18n.formatError(cfgR.error)])); return; }
          const cfg = cfgR.data;
          const frontends = feR.ok ? feR.data : [{ id: "es-de", label: "ES-DE" }];
    
          const frontendSel = h("select", { class: "stg-control archive-frontend" },
            [h("option", { value: "" }, ["저장 형식 선택"]),
              ...frontends.map((f) => h("option", { value: f.id }, [f.label]))]);
          frontendSel.value = cfg.configured ? cfg.frontend : "";
          const dirInput = h("input", { class: "stg-control stg-text archive-dir", value: cfg.archiveDir,
                                        placeholder: msg("ui.archive.pathExample") });
          const romInput = h("input", { class: "stg-control stg-text archive-rom-dir", value: cfg.romDir,
                                        placeholder: "비워 두면 Archive 디렉토리 안에 둡니다" });
          const media = h("input", { type: "checkbox", class: "archive-media-internal" });
          media.checked = !!cfg.mediaInternal;
          const mode = h("select", { class: "stg-control archive-mode" }, [
            h("option", { value: "new" }, [window.RMSI18n.t("ui.legacy.55fe125c87")]),
            h("option", { value: "existing" }, [window.RMSI18n.t("ui.legacy.581670987b")]),
            h("option", { value: "convert" }, [window.RMSI18n.t("ui.legacy.da319f4d4f")]),
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
            if (!path) { folderInfo.textContent = window.RMSI18n.t("ui.archive.folderReady"); return; }
            folderInfo.replaceChildren(window.RMSI18n.t("ui.archive.checkFolder"), h("button", {
              class: "btn compact", onClick: () => {
                inspectRun++;
                if (inspectJobId) api.cancelJob(inspectJobId);
                folderInfo.textContent = window.RMSI18n.t("ui.archive.folderStopped");
              },
            }, [window.RMSI18n.t("ui.legacy.ddb7af8ef7")]));
            const result = await inspectFolderInBackground(path, (jobId) => {
              if (run !== inspectRun) api.cancelJob(jobId);
              else inspectJobId = jobId;
            });
            if (run !== inspectRun || dirInput.value.trim() !== path) return;
            inspectJobId = null;
            if (!result.ok) { folderInfo.textContent = result.error; return; }
            folderResult = result.data;
            if (folderResult.selectedPath && folderResult.path) dirInput.value = folderResult.path;
            if (apply) apply.disabled = false;
            const detected = folderResult.findings.map((f) => f.frontend.toUpperCase()).join(", ");
            folderInfo.textContent = (folderResult.archive || folderResult.legacyArchive)
              ? window.RMSI18n.t(msg("ui.archive.dbDetected", {format:detected ? ` · ${detected}` : ""}))
              : (detected ? window.RMSI18n.t(msg("ui.archive.detected", {format: detected})) : window.RMSI18n.t("ui.archive.new"));
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
          if (!cfg.configured) wrap.appendChild(rowOf("archive.mode", window.RMSI18n.t("ui.legacy.b43dc959bb"),
            window.RMSI18n.t("ui.legacy.5ff094de1f"), mode));
          wrap.appendChild(rowOf("archive.frontend", "저장 형식",
            "Archive를 어떤 Frontend의 형식으로 둘지 정합니다. 바꾸면 그 형식으로 다시 배치합니다(이전 형식의 파일은 지우지 않습니다).",
            frontendSel));
          wrap.appendChild(rowOf("archive.archiveDir", "메타데이터 폴더",
            "메타데이터와 미디어 폴더입니다. 이 폴더에 Archive DB도 저장됩니다.",
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
                showToast(msg("ui.archive.changedAgain"), "warning");
                closeModal();
                return;
              }
              closeModal();
              const backups = result.data.backups || [];
              showToast(msg("ui.archive.resolved", {paths: backups.join(" · ")}), "success");
              if (isArchive()) { resetList(); await reloadList(); renderAll(); }
            };
            showModal(msg("ui.archive.sharedTitle"), h("div", { class: "modal-body" }, [
              h("div", { class: "modal-text" }, [
                msg("ui.archive.sharedHelp")]),
              h("div", { class: "modal-hint" }, [
                msg("ui.archive.sharedChoiceHelp")]),
            ]), [
              h("button", { class: "btn", onClick: closeModal }, ["나중에"]),
              h("button", { class: "btn", onClick: () => resolve("shared") }, [msg("ui.archive.useShared")]),
              h("button", { class: "btn primary", onClick: () => resolve("local") }, [msg("ui.archive.useLocal")]),
            ]);
          }
          apply = h("button", { class: "btn primary archive-apply" }, ["저장하고 적용"]);
          apply.disabled = !!inspectPromise;
          apply.addEventListener("click", async () => {
            if (inspectPromise) await inspectPromise;
            if (!dirInput.value.trim()) { showToast("Archive 디렉토리를 정하세요.", "warning"); return; }
            if (!frontendSel.value) { showToast(window.RMSI18n.t("ui.legacy.46a15198dc"), "warning"); return; }
            if (!folderResult || folderResult.path !== dirInput.value.trim()) {
              showToast(window.RMSI18n.t("ui.legacy.89b07c3519"), "warning"); return;
            }
            if (!cfg.configured && mode.value === "existing"
                && !folderResult.archive && !folderResult.legacyArchive) {
              showToast(window.RMSI18n.t("ui.legacy.69acf3f7c1"), "warning"); return;
            }
            if (!cfg.configured && mode.value === "new"
                && (folderResult.archive || folderResult.legacyArchive)) {
              showToast(window.RMSI18n.t("ui.legacy.438cb53640"), "warning"); return;
            }
            if (!cfg.configured && mode.value === "new" && folderResult.findings.length) {
              showToast(window.RMSI18n.t("ui.legacy.52864898f7"), "warning"); return;
            }
            if (!cfg.configured && mode.value === "convert"
                && (folderResult.archive || folderResult.legacyArchive || !folderResult.findings.length)) {
              showToast(window.RMSI18n.t("ui.legacy.1e2becebbe"), "warning"); return;
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
            lastDiagnostics = window.RMSI18n.t("ui.legacy.746fd58997", {value0: (timing.scanSeconds ?? "?"), value1: (scan.metadataSeconds ?? "?"), value2: (scan.mediaSeconds ?? "?"), value3: (scan.romSeconds ?? "?"), value4: (scan.databaseSeconds ?? "?"), value5: (timing.projectionSeconds ?? "?"), value6: (write.mediaSeconds ?? "?"), value7: (write.writeIndexSeconds ?? "?"), value8: (timing.sharedSeconds ?? "?")});
            showToast(window.RMSI18n.t("ui.legacy.fbedff50ac", {value0: (formatCount(p.entries || 0)), value1: (formatCount(p.systems || 0)), value2: (timing.scanSeconds ?? "?"), value3: (timing.projectionSeconds ?? "?")})
              + (d.imported && d.imported.identities ? window.RMSI18n.t("ui.legacy.c3c0033d78", {value0: (formatCount(d.imported.identities))}) : ""));
            if (d.sharedSnapshot?.status === "conflict")
              await showSharedConflict();
            else if (d.sharedSnapshot?.status === "error")
              showToast(window.RMSI18n.t("ui.legacy.2966c5ffc5", {value0: (d.sharedSnapshot.error)}), "warning");
            if (onApplied) await onApplied();
            draw();
          });
          const rescan = h("button", { class: "btn archive-rescan", disabled: !cfg.configured },
            ["디렉터리 다시 읽기"]);
          rescan.addEventListener("click", async () => {
            const started = await api.startArchiveRefresh();
            if (!started.ok) { showToast(started.error, "error"); return; }
            const done = await pollJob(started.data.jobId, window.RMSI18n.t("ui.legacy.3e6cf405ea"), progressHost);
            if (!done.ok) {
              if (String(done.error || "").includes("자동으로 합칠 수 없습니다")) await showSharedConflict();
              else if (!done.cancelled) showToast(done.error, "error");
              return;
            }
            const scan = done.data?.timings || {};
            lastDiagnostics = window.RMSI18n.t("ui.legacy.3bc47ee5a2", {value0: (done.data?.scanSeconds ?? "?"), value1: (scan.metadataSeconds ?? "?"), value2: (scan.mediaSeconds ?? "?"), value3: (scan.romSeconds ?? "?"), value4: (scan.databaseSeconds ?? "?")});
            status.textContent = lastDiagnostics;
            showToast(window.RMSI18n.t("ui.legacy.b4f74b78a3", {value0: (done.data?.scanSeconds ?? "?")}));
            if (done.data?.sharedSnapshot?.status === "conflict")
              await showSharedConflict();
            if (onApplied) await onApplied();
          });
          wrap.appendChild(h("div", { class: "stg-help" },
            ["저장된 DB를 먼저 표시합니다. 파일 변경분은 필요할 때 다시 읽으세요."]));
          if (lastDiagnostics) status.textContent = lastDiagnostics;
          if (cfg.editLock) {
            const lockInfo = h("div", {class: "stg-help"}, [
              window.RMSI18n.t("ui.legacy.fc8cda2a63", {value0: (cfg.editLock.host || window.RMSI18n.t("ui.legacy.ab6df16281"))}),
            ]);
            const release = h("button", {class: "btn compact", disabled: !cfg.editLock.token,
              onClick: () => showConfirm(window.RMSI18n.t("ui.legacy.ad06417203"),
                window.RMSI18n.t("ui.legacy.d189eb993b"),
                true, async () => {
                  const result = await api.archiveReleaseEditLock(cfg.editLock.token, true);
                  if (!result.ok) { showToast(result.error, "error"); return; }
                  cfg.editLock = null; draw(); showToast(window.RMSI18n.t("ui.legacy.d6953dc944"));
                })}, [window.RMSI18n.t("ui.legacy.bba8797185")]);
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
      return { archiveSettingsEditor, openArchiveSettings };
    }
  };
})();
