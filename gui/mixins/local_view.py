"""
gui/mixins/local_view.py
==========================
Local 화면 담당 Mixin (설계서 v2 §7~§9, §13, §18).

RetroMetadataManagerApp(LocalViewMixin, MasterDBViewMixin, DetailPanelMixin)
형태로 조합되어 사용된다. self.root/self.cfg/self.tree 등은 app.py에서 초기화됨.

이번 리비전에서 수정된 버그:
- [BUG] Title/Description/Genre 컬럼이 항상 빈 값으로 표시되던 문제
  -> importer.read_metadata_fields로 실제 값을 채워서 표시 (다이지쇼 등 미구현 frontend는 예외 처리)
- [BUG] 헤더 클릭 정렬이 오름차순 고정이고 재클릭해도 방향이 바뀌지 않던 문제
  -> 컬럼별 방향 상태를 저장하여 클릭할 때마다 토글
- [BUG] Treeview에 스크롤바가 없어 창을 축소하면 목록을 볼 수 없던 문제
  -> 세로 Scrollbar 추가 + 명시적 마우스 휠 바인딩
"""

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

import config as cfgmod
from importers.scan import scan_local
from importers import get_importer
from utils import bind_mousewheel_scroll, single_line
from gui.style import BG, PANEL, PANEL2, TEXT, MUTED, ACCENT


class LocalViewMixin:
    # =====================================================================
    # Local 화면 진입
    # =====================================================================
    def _show_local(self, local_id):
        local = cfgmod.get_local(self.cfg, local_id)
        if not local:
            return
        self.current_view = ("local", local_id)
        self._render_top_bar()
        self._render_nav()  # 현재 위치 하이라이트 갱신
        self._render_filter_panel_local(local)
        self._render_center_local(local)
        self._render_bottom_local(local)
        self._render_detail_empty()

    def _render_filter_panel_local(self, local):
        for w in self.filter_frame.winfo_children():
            w.destroy()

        tk.Label(self.filter_frame, text="시스템 필터", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(12, 4))

        search_var = tk.StringVar()
        tk.Entry(self.filter_frame, textvariable=search_var, bg=PANEL2, fg=TEXT,
                  bd=1, relief="flat", insertbackground=TEXT).pack(fill="x", padx=12)

        self.system_listbox = tk.Listbox(self.filter_frame, bg=PANEL2, fg=TEXT,
                                          bd=0, highlightthickness=0, selectbackground=ACCENT)
        self.system_listbox.pack(fill="both", expand=True, padx=12, pady=8)
        self.system_listbox.bind("<<ListboxSelect>>", lambda e: self._apply_filters_and_render())

        tk.Label(self.filter_frame, text="상태 필터", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(4, 4))
        self.filter_vars = {}
        for key in ["전체", "완료", "부분", "누락", "중복 ROM"]:
            var = tk.BooleanVar(value=(key != "중복 ROM"))
            self.filter_vars[key] = var
            cb = tk.Checkbutton(self.filter_frame, text=key, variable=var, bg=PANEL, fg=TEXT,
                                 selectcolor=PANEL2, activebackground=PANEL,
                                 command=lambda: self._apply_filters_and_render())
            cb.pack(anchor="w", padx=12)

        ttk.Button(self.filter_frame, text="시스템 이름 매핑",
                   command=lambda: self._open_system_mapping_dialog(local)).pack(
            anchor="w", padx=12, pady=(10, 4)
        )

        self._local_scan_cache = getattr(self, "_local_scan_cache", {})
        self._local_sort_state = {"col": None, "reverse": False}

    def _open_system_mapping_dialog(self, local):
        from gui.dialogs import SystemMappingDialog
        SystemMappingDialog(self.root, self.cfg, local,
                             on_saved=lambda: self._render_center_local(local, refresh_scan=True))

    def _apply_filters_and_render(self):
        if self.current_view and self.current_view[0] == "local":
            local = cfgmod.get_local(self.cfg, self.current_view[1])
            self._render_center_local(local, refresh_scan=False)


    # =====================================================================
    # 게임 목록
    # =====================================================================
    def _scan_progress(self, cur, total, label):
        self._render_status_bar(f"스캔 중: {label}  ({cur}/{total})")
        self.root.update_idletasks()

    def _render_center_local(self, local, refresh_scan=False):
        # 화면 재렌더링(필터/검색/Refresh) 전 현재 시스템 선택을 기억한다.
        previous_system = self._selected_local_system() if hasattr(self, "system_listbox") else None
        for w in self.center_frame.winfo_children():
            w.destroy()

        search_row = tk.Frame(self.center_frame, bg=BG)
        search_row.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(search_row, text="검색 (Ctrl+F)", bg=BG, fg=MUTED).pack(side="left")
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_row, textvariable=search_var, bg=PANEL2, fg=TEXT, bd=1, relief="flat", insertbackground=TEXT)
        search_entry.pack(side="left", fill="x", expand=True, padx=8)
        search_var.trace_add("write", lambda *a: self._filter_tree_by_search(search_var.get()))
        self.root.bind_all("<Control-f>", lambda e: (search_entry.focus_set(), "break"))

        tree_container = tk.Frame(self.center_frame, bg=BG)
        tree_container.pack(fill="both", expand=True, padx=10, pady=4)

        columns = ("file", "title", "desc", "genre", "status")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", selectmode="extended")
        headers = {"file": "File", "title": "Title", "desc": "Description", "genre": "Genre", "status": "Status"}
        widths = {"file": 220, "title": 200, "desc": 320, "genre": 100, "status": 90}
        for col in columns:
            self.tree.heading(col, text=headers[col], command=lambda c=col: self._sort_local_tree(c))
            self.tree.column(col, width=widths[col], anchor="w")

        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        bind_mousewheel_scroll(self.tree, self.tree)

        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_local_rom_select(local))
        self.tree.bind("<Button-3>", lambda e: self._on_local_tree_right_click(e, local))
        self.tree.bind("<Delete>", lambda e: self._delete_selected_local_roms(local))

        scan_key = local["id"]
        cache_map = getattr(self, "_local_scan_cache", {})
        runtime_map = getattr(self, "_local_runtime_cache", {})
        if not refresh_scan and scan_key not in cache_map and scan_key in runtime_map and runtime_map[scan_key].get("last_result"):
            cache_map[scan_key] = runtime_map[scan_key]["last_result"]
        if refresh_scan or scan_key not in cache_map:
            try:
                runtime_cache = runtime_map.setdefault(scan_key, {})
                result = scan_local(local, progress_cb=self._scan_progress, force=False, runtime_cache=runtime_cache)
                cache_map[scan_key] = result
                runtime_cache["last_result"] = result
                self._local_scan_cache = cache_map
            except Exception as e:
                messagebox.showerror("스캔 오류", str(e))
                result = {"rom_list": []}
        else:
            result = cache_map[scan_key]

        self.current_rom_list = result.get("rom_list", [])
        self._populate_local_fields(local)  # [BUG FIX] Title/Desc/Genre 실제 값 채우기

        selected_system = None
        if hasattr(self, "system_listbox") and self.system_listbox.curselection():
            idx = self.system_listbox.curselection()[0]
            if idx > 0:
                systems_sorted = sorted({r["system"] for r in self.current_rom_list})
                if idx - 1 < len(systems_sorted): selected_system = systems_sorted[idx - 1]
        active_status = {k for k, v in self.filter_vars.items() if v.get()} if hasattr(self, "filter_vars") else {"전체"}
        show_all_status = "전체" in active_status
        for rom in self.current_rom_list:
            if selected_system and rom["system"] != selected_system:
                continue
            if not show_all_status and rom.get("_status", "누락") not in active_status:
                continue
            self.tree.insert(
                "", "end", iid=f"{rom['system']}|{rom['filename']}",
                values=(rom["filename"], single_line(rom.get("_title", "")), single_line(rom.get("_desc", "")),
                        single_line(rom.get("_genre", "")), rom.get("_status", "-")),
            )

        systems = sorted({r["system"] for r in self.current_rom_list})
        if hasattr(self, "system_listbox"):
            self.system_listbox.delete(0, "end")
            self.system_listbox.insert("end", f"전체 시스템 ({len(self.current_rom_list)})")
            for s in systems:
                cnt = sum(1 for r in self.current_rom_list if r["system"] == s)
                self.system_listbox.insert("end", f"{s} ({cnt})")
            if previous_system in systems:
                self.system_listbox.selection_set(systems.index(previous_system) + 1)
                self.system_listbox.see(systems.index(previous_system) + 1)

        self._render_status_bar(f"총 {len(self.current_rom_list)}개 ROM")

    def _populate_local_fields(self, local):
        """[BUG FIX] Local 목록의 Title/Description/Genre/Status를 실제 metadata에서 채운다.
        다이지쇼처럼 read_metadata_fields가 미구현(NotImplementedError)인 frontend는
        조용히 건너뛰고 File명만 표시한다 (예외로 인해 전체 목록이 깨지지 않도록 방어)."""
        importer = get_importer(local["frontend"])
        not_implemented_warned = getattr(self, "_field_populate_warned", set())

        for rom in self.current_rom_list:
            fields = rom.get("_fields")
            if fields is None:
                rom["_title"], rom["_desc"], rom["_genre"], rom["_status"] = "", "", "", "누락"
            else:
                rom["_title"] = fields.get("name", "")
                rom["_desc"] = fields.get("desc", "")
                rom["_genre"] = fields.get("genre", "")
                has_title = bool(fields.get("name", "").strip())
                has_desc = bool(fields.get("desc", "").strip())
                rom["_status"] = "완료" if (has_title and has_desc) else ("부분" if (has_title or has_desc) else "누락")

        self._field_populate_warned = not_implemented_warned

    def _filter_tree_by_search(self, query):
        query = query.lower().strip()
        for rom in self.current_rom_list:
            iid = f"{rom['system']}|{rom['filename']}"
            visible = query in rom["filename"].lower() or query in rom.get("_title", "").lower()
            if self.tree.exists(iid):
                if visible:
                    self.tree.reattach(iid, "", "end")
                else:
                    self.tree.detach(iid)

    def _sort_local_tree(self, col):
        """[BUG FIX] 클릭할 때마다 오름차순/내림차순을 토글."""
        state = self._local_sort_state
        reverse = not state["reverse"] if state["col"] == col else False
        state["col"], state["reverse"] = col, reverse

        items = [(self.tree.set(i, col), i) for i in self.tree.get_children("")]
        items.sort(key=lambda t: t[0].lower(), reverse=reverse)
        for idx, (_, i) in enumerate(items):
            self.tree.move(i, "", idx)

        headers = {"file": "File", "title": "Title", "desc": "Description", "genre": "Genre", "status": "Status"}
        arrow = " ↓" if reverse else " ↑"
        for c, label in headers.items():
            self.tree.heading(c, text=(label + arrow) if c == col else label)

    def _on_local_rom_select(self, local):
        sel = self.tree.selection()
        if not sel:
            return
        system, filename = sel[0].split("|", 1)
        self.selected_rom_key = (system, filename)
        self._render_detail_local(local, system, filename)

    # =====================================================================
    # 하단 작업 버튼
    # =====================================================================
    def _render_bottom_local(self, local):
        for w in self.bottom_frame.winfo_children():
            w.destroy()

        btn_row = tk.Frame(self.bottom_frame, bg=PANEL)
        btn_row.pack(fill="x", padx=10, pady=8)

        ttk.Button(btn_row, text="🔄 Refresh List (F5)",
                   command=lambda: self._render_center_local(local, refresh_scan=True)).pack(side="left", padx=4)
        ttk.Button(btn_row, text="🗑 Reset Metadata",
                   command=lambda: self._reset_metadata(local)).pack(side="left", padx=4)
        ttk.Button(btn_row, text="🧹 Orphan Cleanup",
                   command=lambda: self._orphan_cleanup(local)).pack(side="left", padx=4)
        ttk.Button(btn_row, text="📥 Export to MasterDB",
                   command=lambda: self._run_import_to_masterdb(local, target_system=self._selected_local_system())).pack(side="left", padx=4)

        self.status_label_var = tk.StringVar(value="Ready")
        tk.Label(self.bottom_frame, textvariable=self.status_label_var, bg=PANEL, fg=MUTED).pack(
            anchor="w", padx=10
        )

        self.root.bind("<F5>", lambda e: self._render_center_local(local, refresh_scan=True))

    def _selected_local_system(self):
        if not hasattr(self, "system_listbox") or not self.system_listbox.curselection(): return None
        idx = self.system_listbox.curselection()[0]
        if idx <= 0: return None
        systems = sorted({r["system"] for r in self.current_rom_list})
        return systems[idx-1] if idx-1 < len(systems) else None

    def _delete_selected_local_roms(self, local):
        sel = self.tree.selection()
        if not sel:
            return "break"
        if not messagebox.askyesno("삭제 확인", f"선택한 {len(sel)}개 ROM과 연결된 metadata/media를 삭제하시겠습니까?\n되돌릴 수 없습니다."):
            return "break"
        from cleanup_engine import delete_local_roms
        targets = [tuple(i.split("|", 1)) for i in sel]
        try:
            result = delete_local_roms(local, targets)
            # 전체 재스캔하지 않고 현재 in-memory index에서 삭제된 항목만 제거한다.
            cache = getattr(self, "_local_scan_cache", {}).get(local["id"])
            if cache:
                wanted = set(targets)
                old_entries = {(r.get("system"), r.get("filename")): r for r in cache.get("rom_list", [])}
                removed_size = sum(int(old_entries.get(t, {}).get("size", 0) or 0) for t in wanted)
                cache["rom_list"] = [r for r in cache.get("rom_list", [])
                                      if (r.get("system"), r.get("filename")) not in wanted]
                runtime = getattr(self, "_local_runtime_cache", {}).get(local["id"], {})
                for system, filename in wanted:
                    syscache = runtime.get(system, {})
                    syscache.get("files", {}).pop(filename, None)
                    syscache.pop("rom_entries", None)
                stats = local.setdefault("stats", {})
                stats["rom_count"] = max(0, int(stats.get("rom_count", 0)) - len(wanted))
                stats["rom_size_bytes"] = max(0, int(stats.get("rom_size_bytes", 0)) - removed_size)
                for system in {t[0] for t in wanted}:
                    if system in cache.get("per_system", {}):
                        n = sum(1 for t in wanted if t[0] == system)
                        cache["per_system"][system]["rom_count"] = max(0, cache["per_system"][system].get("rom_count", 0) - n)
            self.current_rom_list = cache.get("rom_list", []) if cache else []
            self._render_top_bar()
            self._render_nav()
            self._render_center_local(local, refresh_scan=False)
            self._render_status_bar(f"삭제 완료: ROM {result['roms']} / Metadata {result['metadata']} / Media {result['media']}")
        except Exception as e:
            messagebox.showerror("삭제 오류", str(e))
        return "break"

    def _reset_metadata(self, local):
        from cleanup_engine import reset_metadata
        from config import LocalPathError, validate_local_paths

        # [FIX] 위험한 삭제 작업이므로 경고창을 띄우기 전에 경로부터 검증
        try:
            validate_local_paths(local)
        except LocalPathError as e:
            messagebox.showerror("Local 설정 오류", str(e))
            return

        if not messagebox.askyesno("⚠ 경고", "이 Local의 모든 metadata/media를 삭제합니다.\n"
                                              "이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?"):
            return
        try:
            removed = reset_metadata(local)
            messagebox.showinfo("완료", f"metadata 파일 {removed['metadata_files']}개, "
                                        f"media 폴더 {removed['media_dirs_cleared']}개 삭제됨.")
        except NotImplementedError as e:
            messagebox.showwarning("미지원", str(e))
        except LocalPathError as e:
            messagebox.showerror("Local 설정 오류", str(e))
            return
        self._render_center_local(local, refresh_scan=True)

    def _orphan_cleanup(self, local):
        from cleanup_engine import orphan_cleanup
        from config import LocalPathError, validate_local_paths

        try:
            validate_local_paths(local)
        except LocalPathError as e:
            messagebox.showerror("Local 설정 오류", str(e))
            return

        if not messagebox.askyesno("⚠ 경고", "ROM이 없는 고아 metadata/media를 삭제합니다.\n"
                                              "이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?"):
            return
        try:
            removed = orphan_cleanup(local)
            messagebox.showinfo("완료", f"{len(removed)}개 고아 항목이 삭제되었습니다.")
        except NotImplementedError as e:
            messagebox.showwarning("미지원", str(e))
        except LocalPathError as e:
            messagebox.showerror("Local 설정 오류", str(e))
            return
        self._render_center_local(local, refresh_scan=True)

    def _run_import_to_masterdb(self, local, target_system=None):
        from config import LocalPathError, validate_local_paths
        import db as dbmod
        from import_engine import import_local_to_masterdb
        try:
            validate_local_paths(local)
        except LocalPathError as e:
            messagebox.showerror("Local 설정 오류", str(e)); return
        root = self.cfg.get("masterdb", {}).get("root")
        if not root:
            messagebox.showwarning("MasterDB 없음", "MasterDB 경로가 설정되어 있지 않습니다."); return
        db_data = dbmod.load_db(root)
        cached = self._local_scan_cache.get(local["id"])
        roms = (cached or {"rom_list": []}).get("rom_list", [])
        if target_system:
            roms = [r for r in roms if r["system"] == target_system]
        targets = [(r["system"], r["filename"]) for r in roms
                   if dbmod.make_rom_key(cfgmod.canonical_system(local, r["system"]), r["filename"]) not in db_data.get("roms", {})]
        if not targets:
            messagebox.showinfo("Export", "Export할 신규 ROM이 없습니다.\n이미 MasterDB에 등록된 항목은 건너뜁니다."); return
        def progress(cur, tot, label):
            self._render_status_bar(f"Export 중: {label} ({cur}/{tot})")
            self.root.update_idletasks()
        result = import_local_to_masterdb(local, root, db_data, progress_cb=progress, target_roms=targets, scan_result=cached)
        dbmod.save_db(root, db_data)
        self.db = db_data
        self._render_top_bar()
        self._render_nav()
        messagebox.showinfo("Export 결과", f"신규 처리: {result['imported']}\n중복 스킵: {result['duplicates_skipped']}\n매칭 없음: {len(result['unmatched'])}")
        self._render_status_bar("Ready")

    # =====================================================================
    # 우클릭 메뉴 (선택적 Export / 일괄 스크랩)
    # =====================================================================
    def _on_local_tree_right_click(self, event, local):
        sel = self.tree.selection()
        if not sel:
            return
        target_roms = [tuple(iid.split("|", 1)) for iid in sel]

        menu = tk.Menu(self.root, tearoff=0, bg=PANEL2, fg=TEXT)
        menu.add_command(
            label=f"MasterDB에서 선택 항목 Export ({len(sel)}개)",
            command=lambda: self._export_from_masterdb_into_this_local(local, target_roms),
        )
        menu.add_command(
            label=f"일괄 스크랩 ({len(sel)}개)",
            command=lambda: self._batch_scrape(local, target_roms),
        )
        menu.tk_popup(event.x_root, event.y_root)

    def _batch_scrape(self, local, target_roms):
        from gui.scraper_dialogs import BatchScrapeReviewDialog
        from scraper import screenscraper as ss
        import db as dbmod

        if not self.cfg.get("scraper", {}).get("devid"):
            messagebox.showwarning("설정 필요", "Settings에서 ScreenScraper API 인증 정보를 먼저 입력해주세요.")
            return
        if not self.cfg.get("masterdb", {}).get("root"):
            messagebox.showwarning("MasterDB 없음", "MasterDB 경로가 설정되어 있지 않습니다.")
            return

        rom_list = []
        for system, filename in target_roms:
            match = next((r for r in self.current_rom_list
                          if r["system"] == system and r["filename"] == filename), None)
            if match:
                rom_list.append(match)

        progress_win = tk.Toplevel(self.root)
        progress_win.title("일괄 스크랩 진행 중")
        progress_win.configure(bg=PANEL)
        status_var = tk.StringVar(value="준비 중...")
        tk.Label(progress_win, textvariable=status_var, bg=PANEL, fg=TEXT).pack(padx=20, pady=20)

        def progress(cur, tot, label):
            status_var.set(f"스크랩 중: {label} ({cur}/{tot})")
            progress_win.update_idletasks()

        results = ss.batch_scrape(self.cfg["scraper"], rom_list, progress_cb=progress)
        progress_win.destroy()

        masterdb_root = self.cfg["masterdb"]["root"]
        db_data = dbmod.load_db(masterdb_root)
        BatchScrapeReviewDialog(self.root, db_data, masterdb_root, results, on_saved=lambda: None)

    def _export_from_masterdb_into_this_local(self, local, target_roms):
        from gui.dialogs import ExportConflictDialog
        from export_engine import export_masterdb_to_local
        import db as dbmod

        if not self.cfg.get("masterdb", {}).get("root"):
            messagebox.showinfo("MasterDB 없음", "MasterDB 경로가 설정되어 있지 않습니다.")
            return
        masterdb_root = self.cfg["masterdb"]["root"]
        db_data = dbmod.load_db(masterdb_root)
        export_options = self.cfg.get("export_options", {})

        def resolver(existing, new, rom_info):
            dlg = ExportConflictDialog(self.root, rom_info["filename"], existing, new)
            self.root.wait_window(dlg)
            return dlg.result or "skip"

        def progress(cur, tot, label):
            self._render_status_bar(f"Export 중: {label} ({cur}/{tot})")
            self.root.update_idletasks()

        result = export_masterdb_to_local(
            local, masterdb_root, db_data, export_options,
            conflict_resolver=resolver, progress_cb=progress, target_roms=target_roms,
        )
        messagebox.showinfo(
            "Export 결과",
            f"성공: {result['exported']}  /  매칭없음: {result['skipped_no_match']}  /  "
            f"충돌스킵: {result['skipped_conflict']}  /  한글중복스킵: {result['skipped_korean_dup']}",
        )
        self._render_status_bar("Ready")
