"""
gui/mixins/masterdb_view.py
=============================
MasterDB 화면 담당 Mixin (설계서 v2 §8, §9, §14, §3.3).

수정된 버그:
- [BUG] MasterDB 목록은 헤더 클릭 정렬 자체가 아예 연결되어 있지 않던 문제 -> 연결 + 토글
- [BUG] 스크롤바 없음 -> 추가
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import db as dbmod
from utils import bind_mousewheel_scroll, single_line
from gui.style import BG, PANEL, PANEL2, TEXT, MUTED, ACCENT


class MasterDBViewMixin:
    def _show_masterdb(self):
        root_path = self.cfg.get("masterdb", {}).get("root", "")
        if not root_path:
            self._prompt_masterdb_setup()
            return

        self.current_view = ("masterdb", None)
        self.db = dbmod.load_db(root_path)
        self._render_top_bar()
        self._render_nav()  # 현재 위치 하이라이트 갱신

        for w in self.filter_frame.winfo_children():
            w.destroy()
        tk.Label(self.filter_frame, text="시스템 필터", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        self.system_listbox = tk.Listbox(self.filter_frame, bg=PANEL2, fg=TEXT, bd=0,
                                          highlightthickness=0, selectbackground=ACCENT)
        self.system_listbox.pack(fill="both", expand=True, padx=12, pady=8)

        dup_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self.filter_frame, text="중복 ROM만 보기", variable=dup_var, bg=PANEL, fg=TEXT,
                        selectcolor=PANEL2, activebackground=PANEL,
                        command=lambda: self._render_masterdb_tree(dup_var.get())).pack(anchor="w", padx=12, pady=4)
        self._masterdb_dup_filter_var = dup_var
        self._masterdb_sort_state = {"col": None, "reverse": False}

        for w in self.center_frame.winfo_children():
            w.destroy()
        tree_container = tk.Frame(self.center_frame, bg=BG)
        tree_container.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("file", "title", "desc", "genre", "status")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", selectmode="extended")
        headers = {"file": "File", "title": "Title", "desc": "Description", "genre": "Genre", "status": "Status"}
        for col in columns:
            self.tree.heading(col, text=headers[col], command=lambda c=col: self._sort_masterdb_tree(c))
            self.tree.column(col, width=200, anchor="w")

        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        bind_mousewheel_scroll(self.tree, self.tree)

        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_masterdb_rom_select())
        self.tree.bind("<Button-3>", self._on_masterdb_tree_right_click)

        self._render_masterdb_tree(dup_filter=False)

        systems = {re["system"] for re in self.db.get("roms", {}).values()}
        self.system_listbox.insert("end", f"전체 시스템 ({len(systems)})")
        for s in sorted(systems):
            self.system_listbox.insert("end", s)
        self.system_listbox.bind("<<ListboxSelect>>", self._on_masterdb_system_select)
        self.system_listbox.bind("<Button-3>", self._on_masterdb_system_right_click)
        self._masterdb_systems = sorted(systems)

        for w in self.bottom_frame.winfo_children():
            w.destroy()
        btn_row = tk.Frame(self.bottom_frame, bg=PANEL)
        btn_row.pack(fill="x", padx=10, pady=8)
        ttk.Button(btn_row, text="🔄 Refresh List", command=self._show_masterdb).pack(side="left", padx=4)
        ttk.Button(btn_row, text="📤 Export to Local", command=self._open_export_to_local_dialog).pack(side="left", padx=4)
        self.export_lpl_btn = ttk.Button(btn_row, text="🎮 Export to RetroArch",
                                          command=self._export_selected_system_to_lpl, state="disabled")
        self.export_lpl_btn.pack(side="left", padx=4)

        self.status_label_var = tk.StringVar(value="Ready")
        tk.Label(self.bottom_frame, textvariable=self.status_label_var, bg=PANEL, fg=MUTED).pack(anchor="w", padx=10)

        self._render_detail_empty()
        self._render_status_bar(f"총 {len(self.db.get('roms', {}))}개 게임")

    def _render_masterdb_tree(self, dup_filter=False, system_filter=None):
        self.tree.delete(*self.tree.get_children())

        dup_keys = set()
        if dup_filter:
            dup_groups = dbmod.find_duplicate_roms(self.db)
            for keys in dup_groups.values():
                dup_keys.update(keys)

        for rom_key, rom_entry in self.db.get("roms", {}).items():
            if dup_filter and rom_key not in dup_keys:
                continue
            if system_filter and rom_entry["system"] != system_filter:
                continue
            fields = dbmod.get_default_fields(rom_entry)
            status = dbmod.rom_status(rom_entry)
            self.tree.insert("", "end", iid=rom_key,
                              values=(rom_entry["rom_filename"], single_line(fields.get("name", "")),
                                      single_line(fields.get("desc", "")), single_line(fields.get("genre", "")), status))


    def _sort_masterdb_tree(self, col):
        """[BUG FIX] MasterDB 목록도 Local과 동일하게 헤더 클릭 정렬/토글 지원."""
        state = self._masterdb_sort_state
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

    def _delete_selected_masterdb_roms(self):
        sel = self.tree.selection()
        if not sel:
            return
        if not messagebox.askyesno("삭제 확인", f"{len(sel)}개 항목을 MasterDB에서 삭제하시겠습니까?\n"
                                                "이 작업은 되돌릴 수 없습니다."):
            return
        root = self.cfg["masterdb"]["root"]
        for rom_key in sel:
            entry = self.db["roms"].pop(rom_key, None)
            if entry:
                dbmod.delete_rom_storage(root, entry["system"], entry["rom_filename"], entry.get("media", {}))
        dbmod.save_db(root, self.db)
        self._show_masterdb()

    def _on_masterdb_rom_select(self):
        sel = self.tree.selection()
        if not sel:
            return
        rom_key = sel[0]
        rom_entry = self.db["roms"].get(rom_key)
        if rom_entry:
            self._render_detail_masterdb(rom_entry)

    def _on_masterdb_tree_right_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        menu = tk.Menu(self.root, tearoff=0, bg=PANEL2, fg=TEXT)
        menu.add_command(label=f"선택 항목 Export ({len(sel)}개)",
                          command=lambda: self._export_selected_roms_to_local(sel))
        menu.tk_popup(event.x_root, event.y_root)

    def _export_selected_roms_to_local(self, selected_rom_keys):
        target_roms = []
        for rom_key in selected_rom_keys:
            rom_entry = self.db["roms"].get(rom_key)
            if rom_entry:
                target_roms.append((rom_entry["system"], rom_entry["rom_filename"]))

        locals_ = self.cfg.get("locals", [])
        if not locals_:
            messagebox.showinfo("Local 없음", "등록된 Local이 없습니다.")
            return

        pick_win = tk.Toplevel(self.root)
        pick_win.title("Export 대상 Local 선택")
        pick_win.configure(bg=PANEL)
        tk.Label(pick_win, text="Export할 Local을 선택하세요", bg=PANEL, fg=TEXT).pack(padx=16, pady=12)
        for local in locals_:
            ttk.Button(
                pick_win, text=local["label"],
                command=lambda l=local: self._run_export_to_local(l, pick_win, target_roms=target_roms),
            ).pack(fill="x", padx=16, pady=4)
        ttk.Button(pick_win, text="취소", command=pick_win.destroy).pack(fill="x", padx=16, pady=(4, 12))

    def _on_masterdb_system_select(self, event=None):
        sel = self.system_listbox.curselection()
        if not sel or sel[0] == 0:
            self.export_lpl_btn.configure(state="disabled")
            self._selected_masterdb_system = None
            return
        self._selected_masterdb_system = self._masterdb_systems[sel[0] - 1]
        self.export_lpl_btn.configure(state="normal")
        self._render_masterdb_tree(self._masterdb_dup_filter_var.get(), self._selected_masterdb_system)

    def _on_masterdb_system_right_click(self, event):
        idx = self.system_listbox.nearest(event.y)
        if idx == 0 or idx > len(self._masterdb_systems):
            return
        self.system_listbox.selection_clear(0, "end")
        self.system_listbox.selection_set(idx)
        self._on_masterdb_system_select()
        system = self._masterdb_systems[idx - 1]

        from gui.dialogs import CoreSettingDialog

        menu = tk.Menu(self.root, tearoff=0, bg=PANEL2, fg=TEXT)
        menu.add_command(label=f"'{system}' 시스템 Export",
                          command=lambda: self._export_system_roms_to_local(system))
        menu.add_command(label="Export to RetroArch", command=self._export_selected_system_to_lpl)
        menu.add_command(label="Core 설정", command=lambda: self._open_core_setting_dialog(system))
        menu.add_command(label="시스템 전체 스크랩", command=lambda: self._batch_scrape_system(system))
        menu.tk_popup(event.x_root, event.y_root)

    def _open_core_setting_dialog(self, system):
        from gui.dialogs import CoreSettingDialog
        CoreSettingDialog(self.root, self.db, system,
                           on_saved=lambda: dbmod.save_db(self.cfg["masterdb"]["root"], self.db))

    def _batch_scrape_system(self, system):
        if not self.cfg.get("scraper", {}).get("devid"):
            messagebox.showwarning("설정 필요", "Settings에서 ScreenScraper API 인증 정보를 먼저 입력해주세요.")
            return
        messagebox.showinfo(
            "안내",
            "시스템 전체 스크랩은 MasterDB에 등록된 게임을 대상으로 하며,\n"
            "실제 ROM 파일 경로가 필요한 해시 매칭은 Local 화면에서의 일괄 스크랩을 이용해주세요.",
        )

    def _export_system_roms_to_local(self, system):
        target_roms = [(re["system"], re["rom_filename"]) for re in self.db["roms"].values()
                       if re["system"] == system]
        locals_ = self.cfg.get("locals", [])
        if not locals_:
            messagebox.showinfo("Local 없음", "등록된 Local이 없습니다.")
            return
        pick_win = tk.Toplevel(self.root)
        pick_win.title("Export 대상 Local 선택")
        pick_win.configure(bg=PANEL)
        tk.Label(pick_win, text="Export할 Local을 선택하세요", bg=PANEL, fg=TEXT).pack(padx=16, pady=12)
        for local in locals_:
            ttk.Button(
                pick_win, text=local["label"],
                command=lambda l=local: self._run_export_to_local(l, pick_win, target_roms=target_roms),
            ).pack(fill="x", padx=16, pady=4)
        ttk.Button(pick_win, text="취소", command=pick_win.destroy).pack(fill="x", padx=16, pady=(4, 12))

    def _export_selected_system_to_lpl(self):
        from exporters.retroarch_lpl import export_system_to_lpl

        system = getattr(self, "_selected_masterdb_system", None)
        if not system:
            return

        # [FIX] CRC32 계산용 로컬 경로(실제 파일 존재)와, .lpl에 기록될 대상 경로(문자열)를 분리해서 받는다.
        # 안드로이드 등 다른 기기에 복사해서 쓸 경우 target path는 이 PC에 존재하지 않는 가상의 경로일 수 있음.
        crc_source = filedialog.askdirectory(
            parent=self.root, title=f"'{system}' 실제 ROM 파일 경로 (CRC32 계산용, 이 PC 기준)"
        )
        if not crc_source:
            return

        target_path = self._ask_target_path_dialog(default_value=crc_source)
        if target_path is None:
            return

        save_dir = filedialog.askdirectory(parent=self.root, title="Playlist(.lpl) 저장 위치 지정")
        if not save_dir:
            return

        try:
            out_path = export_system_to_lpl(self.db, system, crc_source, save_dir,
                                             target_path_prefix=target_path)
            messagebox.showinfo("Export 완료", f"RetroArch Playlist가 생성되었습니다:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Export 오류", str(e))

    def _ask_target_path_dialog(self, default_value=""):
        """
        Playlist에 기록될 대상 경로를 텍스트로 입력받는 대화창.
        폴더 선택 대화창이 아닌 텍스트 입력인 이유: 안드로이드 등 이 PC에 존재하지 않는
        경로(예: /storage/emulated/0/ROMs/snes)를 지정해야 하는 경우가 있기 때문.
        """
        win = tk.Toplevel(self.root)
        win.title("Playlist 대상 경로")
        win.configure(bg=PANEL)
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="Playlist에 기록될 ROM 경로", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(
            win,
            text="이 .lpl 파일을 그대로 다른 기기(예: 안드로이드)에서 사용할 경우,\n"
                 "그 기기에서 ROM이 위치할 경로를 직접 입력하세요.\n"
                 "같은 PC에서만 쓸 경우 기본값을 그대로 두면 됩니다.",
            bg=PANEL, fg=MUTED, wraplength=420, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        var = tk.StringVar(value=default_value)
        tk.Entry(win, textvariable=var, bg=PANEL2, fg=TEXT, bd=1, relief="flat", width=50,
                 insertbackground=TEXT).pack(
            fill="x", padx=16, pady=4
        )
        tk.Label(win, text="예: /storage/emulated/0/ROMs/snes", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=16)

        result = {"value": None}

        def confirm():
            result["value"] = var.get().strip()
            win.destroy()

        def cancel():
            win.destroy()

        btn_row = tk.Frame(win, bg=PANEL); btn_row.pack(fill="x", padx=16, pady=16, side="bottom")
        ttk.Button(btn_row, text="취소", command=cancel).pack(side="right")
        ttk.Button(btn_row, text="확인", style="Accent.TButton", command=confirm).pack(side="right", padx=8)

        self.root.wait_window(win)
        return result["value"]

    def _open_export_to_local_dialog(self):
        locals_ = self.cfg.get("locals", [])
        if not locals_:
            messagebox.showinfo("Local 없음", "등록된 Local이 없습니다.")
            return

        pick_win = tk.Toplevel(self.root)
        pick_win.title("Export 대상 Local 선택")
        pick_win.configure(bg=PANEL)
        tk.Label(pick_win, text="Export할 Local을 선택하세요", bg=PANEL, fg=TEXT).pack(padx=16, pady=12)
        for local in locals_:
            ttk.Button(pick_win, text=local["label"],
                       command=lambda l=local: self._run_export_to_local(l, pick_win)).pack(
                fill="x", padx=16, pady=4
            )
        ttk.Button(pick_win, text="취소", command=pick_win.destroy).pack(fill="x", padx=16, pady=(4, 12))

    def _run_export_to_local(self, local_entry, pick_win, target_roms=None):
        from gui.dialogs import ExportConflictDialog
        from export_engine import export_masterdb_to_local

        if pick_win:
            pick_win.destroy()

        # [FIX] 방어 코드: 어떤 경로로 호출되든 MasterDB 미설정 시 명확히 에러 처리
        if not self.cfg.get("masterdb", {}).get("root"):
            messagebox.showerror("MasterDB 없음", "MasterDB 경로가 설정되어 있지 않습니다.")
            return
        masterdb_root = self.cfg["masterdb"]["root"]
        export_options = self.cfg.get("export_options", {})

        def resolver(existing, new, rom_info):
            dlg = ExportConflictDialog(self.root, rom_info["filename"], existing, new)
            self.root.wait_window(dlg)
            return dlg.result or "skip"

        def progress(cur, tot, label):
            self._render_status_bar(f"Export 중: {label} ({cur}/{tot})")
            self.root.update_idletasks()

        result = export_masterdb_to_local(
            local_entry, masterdb_root, self.db, export_options,
            conflict_resolver=resolver, progress_cb=progress, target_roms=target_roms,
        )

        msg = (f"Export 완료\n\n"
               f"성공: {result['exported']}\n"
               f"매칭 없음(Local에 없는 ROM): {result['skipped_no_match']}\n"
               f"충돌로 건너뜀: {result['skipped_conflict']}\n"
               f"한글화 중복으로 건너뜀: {result['skipped_korean_dup']}")
        if result["not_implemented"]:
            msg += "\n\n⚠ 이 Frontend는 아직 Export가 구현되지 않았습니다:\n" + "\n".join(result["errors"])
        messagebox.showinfo("Export 결과", msg)
        self._render_status_bar("Ready")
