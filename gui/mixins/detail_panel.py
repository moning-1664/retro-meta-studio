"""
gui/mixins/detail_panel.py
=============================
우측 Metadata/Media Detail 패널 (v0.3.0 전면 재작성).

이번 리비전에서 수정된 버그 (실사용 피드백):
- [BUG] Local 화면에서 게임을 선택하면 "MasterDB로 Import해야 편집 가능"이라는
  안내만 뜨고 실제 metadata/media를 전혀 보여주지 않던 문제
  -> Import 여부와 무관하게 Local 자체 파일에서 읽어 읽기 전용으로 표시.
- [BUG] Media 탭이 파일 개수/이름 텍스트만 보여주고 실제 이미지를 렌더링하지 않던 문제
  -> gui.image_utils로 실제 썸네일 표시. 여러 장이면 이전/다음 이동 가능.
- [BUG] Media 탭에서 다른 게임으로 이동(Treeview 재선택)이 막히던 문제
  -> 클로저 상태가 꼬여있던 이전 구현을 정리하고, 불필요했던
     "미디어 영역에 마우스휠로 Treeview를 스크롤" 바인딩(부작용 소지) 제거.
- [BUG] Description이 여러 줄로 늘어나 목록 정렬이 깨지던 문제는 각 화면(local_view/masterdb_view)에서
  1줄로 sanitize하도록 별도 수정 (이 파일과는 무관하지만 함께 안내).
- [UX] 필드 순서를 Title -> Description -> (짧은 필드 2열 그리드) 순으로 변경,
  그리드 아래 남는 공간에 대표 Screenshot을 미리보기로 표시.
- [UX] 커서가 안 보이던 문제 -> 모든 Entry/Text에 insertbackground 명시 적용(이미 반영됨).
"""

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

import config as cfgmod
import db as dbmod
from utils import bind_entry_undo_redo, bind_mousewheel_scroll
from gui.image_utils import load_thumbnail
from gui.style import BG, PANEL, PANEL2, PANEL3, BORDER, TEXT, MUTED, ACCENT, FONT_H3, FONT_BODY_BOLD, FONT_CAPTION

SHORT_FIELD_PAIRS = [
    ("genre", "Genre"), ("developer", "Developer"),
    ("publisher", "Publisher"), ("releasedate", "Release"),
    ("region", "Region"), ("players", "Players"),
    ("rating", "Rating"), (None, None),
]

MEDIA_TABS = [("covers", "Covers"), ("miximages", "Miximages"),
              ("screenshots", "Screenshots"), ("wheel", "Wheel")]


class DetailPanelMixin:
    def _render_detail_empty(self):
        for w in self.detail_frame.winfo_children():
            w.destroy()
        tk.Label(self.detail_frame, text="게임을 선택하세요", bg=PANEL, fg=MUTED).pack(expand=True)

    # =====================================================================
    # Local 화면: MasterDB Import 여부와 무관하게 자체 파일에서 읽어 표시 (읽기 전용)
    # =====================================================================
    def _render_detail_local(self, local, system, filename):
        for w in self.detail_frame.winfo_children():
            w.destroy()

        tk.Label(self.detail_frame, text=filename, bg=PANEL, fg=TEXT,
                 font=FONT_H3, wraplength=340).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(self.detail_frame, text="Local Metadata / Media",
                 bg=PANEL, fg=MUTED, font=FONT_CAPTION).pack(anchor="w", padx=16, pady=(0, 10))

        from importers import get_importer
        from exporters import get_exporter
        importer = get_importer(local["frontend"])
        exporter = get_exporter(local["frontend"])

        try:
            fields = importer.read_metadata_fields(local["metadata_path"], system, filename) or {}
        except Exception as e:
            fields = {}
            tk.Label(self.detail_frame, text=f"metadata 읽기 오류: {e}", bg=PANEL, fg=MUTED,
                     wraplength=340, justify="left").pack(anchor="w", padx=16)

        notebook = ttk.Notebook(self.detail_frame)
        notebook.pack(fill="both", expand=True, padx=10, pady=8)
        meta_tab = tk.Frame(notebook, bg=PANEL)
        media_tab = tk.Frame(notebook, bg=PANEL)
        notebook.add(meta_tab, text="Metadata")
        notebook.add(media_tab, text="Media")

        vars_ = {}
        tk.Label(meta_tab, text="Title", bg=PANEL, fg=MUTED, font=FONT_CAPTION).pack(anchor="w", padx=12, pady=(10, 2))
        name_var = tk.StringVar(value=str(fields.get("name", "")))
        vars_["name"] = name_var
        tk.Entry(meta_tab, textvariable=name_var, bg=PANEL2, fg=TEXT, bd=1, relief="flat",
                 insertbackground=TEXT, font=FONT_BODY_BOLD).pack(fill="x", padx=12)

        tk.Label(meta_tab, text="Description", bg=PANEL, fg=MUTED, font=FONT_CAPTION).pack(anchor="w", padx=12, pady=(10, 2))
        desc = tk.Text(meta_tab, height=5, bg=PANEL2, fg=TEXT, bd=1, relief="flat", wrap="word",
                       undo=True, insertbackground=TEXT)
        desc.insert("1.0", fields.get("desc", ""))
        desc.pack(fill="x", padx=12)

        grid = tk.Frame(meta_tab, bg=PANEL); grid.pack(fill="x", padx=12, pady=(10, 0))
        for i, (key, label) in enumerate(SHORT_FIELD_PAIRS):
            if key is None: continue
            r, c = divmod(i, 2)
            cell = tk.Frame(grid, bg=PANEL); cell.grid(row=r, column=c, sticky="w", padx=(0, 10), pady=3)
            tk.Label(cell, text=label, bg=PANEL, fg=MUTED, font=FONT_CAPTION).pack(anchor="w")
            var = tk.StringVar(value=str(fields.get(key, "")))
            vars_[key] = var
            tk.Entry(cell, textvariable=var, bg=PANEL2, fg=TEXT, bd=1, relief="flat",
                     insertbackground=TEXT, width=15).pack(anchor="w")

        def save_local_metadata():
            new_fields = {k: v.get() for k, v in vars_.items()}
            new_fields["desc"] = desc.get("1.0", "end-1c")
            try:
                exporter.write_metadata_fields(local["metadata_path"], system, filename, new_fields)
                # 캐시의 해당 ROM metadata도 즉시 갱신하여 화면 이동/필터에서 재파싱하지 않는다.
                cache = getattr(self, "_local_scan_cache", {}).get(local["id"])
                if cache:
                    for r in cache.get("rom_list", []):
                        if r.get("system") == system and r.get("filename") == filename:
                            r["_fields"] = dict(new_fields); r["has_metadata"] = bool(new_fields.get("name"))
                            break
                messagebox.showinfo("저장 완료", "Local metadata가 저장되었습니다.")
                self._render_center_local(local, refresh_scan=False)
            except NotImplementedError as e:
                messagebox.showwarning("미지원", str(e))
            except Exception as e:
                messagebox.showerror("저장 오류", str(e))

        ttk.Button(meta_tab, text="💾 Local Metadata 저장", style="Accent.TButton",
                   command=save_local_metadata).pack(anchor="w", padx=12, pady=12)

        try:
            media = importer.read_media(local["media_path"], system, filename, game_title=fields.get("name"))
        except Exception:
            media = {}
        self._render_media_tab(media_tab, media, editable_ref=None)

    # =====================================================================
    # MasterDB 게임 상세 (Metadata / Media 탭, 편집 가능)
    # =====================================================================
    def _render_detail_masterdb(self, rom_entry):
        for w in self.detail_frame.winfo_children():
            w.destroy()

        header_row = tk.Frame(self.detail_frame, bg=PANEL)
        header_row.pack(fill="x", padx=10, pady=(12, 0))
        tk.Label(header_row, text=rom_entry["rom_filename"], bg=PANEL, fg=TEXT,
                 font=FONT_H3, wraplength=250).pack(side="left")
        ttk.Button(header_row, text="🔍 스크랩", command=lambda: self._open_scrape_dialog(rom_entry)).pack(side="right")

        notebook = ttk.Notebook(self.detail_frame)
        notebook.pack(fill="both", expand=True, padx=10, pady=8)

        meta_tab = tk.Frame(notebook, bg=PANEL)
        media_tab = tk.Frame(notebook, bg=PANEL)
        notebook.add(meta_tab, text="Metadata")
        notebook.add(media_tab, text="Media")

        fields = dbmod.get_default_fields(rom_entry)

        # --- Title ---
        tk.Label(meta_tab, text="Title", bg=PANEL, fg=MUTED, font=FONT_CAPTION).pack(anchor="w", padx=12, pady=(10, 2))
        name_var = tk.StringVar(value=str(fields.get("name", "")))
        name_entry = tk.Entry(meta_tab, textvariable=name_var, bg=PANEL2, fg=TEXT, bd=1, relief="flat",
                               insertbackground=TEXT, font=FONT_BODY_BOLD)
        name_entry.pack(fill="x", padx=12)
        bind_entry_undo_redo(name_entry, name_var)

        # --- Description ---
        tk.Label(meta_tab, text="Description", bg=PANEL, fg=MUTED, font=FONT_CAPTION).pack(anchor="w", padx=12, pady=(10, 2))
        desc_text = tk.Text(meta_tab, height=4, bg=PANEL2, fg=TEXT, bd=1, relief="flat",
                             wrap="word", undo=True, autoseparators=True, maxundo=-1, insertbackground=TEXT)
        desc_text.insert("1.0", fields.get("desc", ""))
        desc_text.pack(fill="x", padx=12)
        desc_text.bind("<KeyRelease>", lambda e: desc_text.update_idletasks())
        bind_mousewheel_scroll(desc_text, desc_text)

        # --- 짧은 필드 2열 그리드 + 여백에 대표 Screenshot 미리보기 ---
        body_row = tk.Frame(meta_tab, bg=PANEL); body_row.pack(fill="both", expand=True, padx=12, pady=(10, 4))
        grid = tk.Frame(body_row, bg=PANEL); grid.pack(side="left", fill="y", anchor="n")

        self._detail_field_vars = {"name": name_var}
        for i, (key, label) in enumerate(SHORT_FIELD_PAIRS):
            r, c = divmod(i, 2)
            if key is None:
                continue
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=r, column=c, sticky="w", padx=(0, 8), pady=3)
            tk.Label(cell, text=label, bg=PANEL, fg=MUTED, font=FONT_CAPTION).pack(anchor="w")
            var = tk.StringVar(value=str(fields.get(key, "")))
            self._detail_field_vars[key] = var
            entry = tk.Entry(cell, textvariable=var, bg=PANEL2, fg=TEXT, bd=1, relief="flat",
                              insertbackground=TEXT, width=13, font=("Segoe UI", 9))
            entry.pack(anchor="w")
            bind_entry_undo_redo(entry, var)

        # 대표 Screenshot 미리보기 (그리드 옆 남는 공간)
        shot_frame = tk.Frame(body_row, bg=PANEL2, width=140, height=140)
        shot_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))
        shot_frame.pack_propagate(False)
        self._render_representative_shot(shot_frame, rom_entry)

        self._detail_desc_widget = desc_text

        # --- Version 관리 ---
        tk.Label(meta_tab, text="Version", bg=PANEL, fg=MUTED, font=FONT_CAPTION).pack(anchor="w", padx=12, pady=(10, 2))
        sorted_versions = dbmod.list_versions_sorted(rom_entry)
        version_labels = [dbmod.version_label(rom_entry, vid) for vid, _ in sorted_versions]
        vid_by_label = {dbmod.version_label(rom_entry, vid): vid for vid, _ in sorted_versions}
        default_vid = rom_entry.get("default_version_id")
        default_label = dbmod.version_label(rom_entry, default_vid) if default_vid else ""

        version_combo = ttk.Combobox(meta_tab, values=version_labels, state="readonly")
        version_combo.set(default_label)
        version_combo.pack(fill="x", padx=12, pady=2)

        def load_version_into_fields(vid):
            vfields = rom_entry["versions"][vid]["fields"]
            for key, var in self._detail_field_vars.items():
                var.set(str(vfields.get(key, "")))
            desc_text.delete("1.0", "end")
            desc_text.insert("1.0", vfields.get("desc", ""))

        def on_version_change(event=None):
            vid = vid_by_label.get(version_combo.get())
            if vid:
                load_version_into_fields(vid)

        version_combo.bind("<<ComboboxSelected>>", on_version_change)

        vbtn_row = tk.Frame(meta_tab, bg=PANEL); vbtn_row.pack(fill="x", padx=12, pady=4)
        ttk.Button(vbtn_row, text="복제", command=lambda: self._version_clone(rom_entry, version_combo)).pack(
            side="left", padx=2
        )
        ttk.Button(vbtn_row, text="기본값 설정",
                   command=lambda: self._version_set_default(rom_entry, version_combo)).pack(side="left", padx=2)
        ttk.Button(vbtn_row, text="삭제", command=lambda: self._version_delete(rom_entry, version_combo)).pack(
            side="left", padx=2
        )

        ver_diff_state = "normal" if len(rom_entry.get("versions", {})) > 1 else "disabled"
        ttk.Button(meta_tab, text="⚖ Ver Diff (버전 비교/정리)", state=ver_diff_state,
                   command=lambda: self._open_version_diff_dialog(rom_entry)).pack(fill="x", padx=12, pady=(4, 4))

        def save_current_version(event=None):
            try:
                if not meta_tab.winfo_exists():
                    return "break" if event else None
            except tk.TclError:
                return "break" if event else None

            vid = vid_by_label.get(version_combo.get()) or rom_entry.get("default_version_id")
            if not vid:
                return "break" if event else None
            for key, var in self._detail_field_vars.items():
                rom_entry["versions"][vid]["fields"][key] = var.get()
            rom_entry["versions"][vid]["fields"]["desc"] = desc_text.get("1.0", "end-1c")

            masterdb_root = self.cfg["masterdb"]["root"]
            dbmod.save_db(masterdb_root, self.db)
            self._render_status_bar(f"저장 완료 ({rom_entry['rom_filename']}) - "
                                     f"{__import__('datetime').datetime.now():%H:%M:%S}")
            self._show_masterdb()
            return "break" if event else None

        ttk.Button(meta_tab, text="💾 저장 (Save) [Ctrl+S]", style="Accent.TButton",
                   command=save_current_version).pack(fill="x", padx=12, pady=(10, 4))
        self.root.bind_all("<Control-s>", save_current_version)

        self._render_media_tab(media_tab, rom_entry.get("media", {}), editable_ref=rom_entry)

    def _render_representative_shot(self, container, rom_entry):
        media = rom_entry.get("media", {})
        candidate = media.get("screenshots") or media.get("covers")
        path = None
        if isinstance(candidate, list) and candidate:
            path = candidate[0]
        elif isinstance(candidate, str):
            path = candidate

        photo = load_thumbnail(path, max_width=136, max_height=136) if path else None
        if photo:
            lbl = tk.Label(container, image=photo, bg=PANEL2)
            lbl.image = photo  # GC 방지 (참조 유지)
            lbl.pack(expand=True)
        else:
            tk.Label(container, text="🖼", bg=PANEL2, fg=BORDER, font=("Segoe UI", 28)).pack(expand=True)

    def _version_clone(self, rom_entry, version_combo):
        vid = None
        for v_id, _ in dbmod.list_versions_sorted(rom_entry):
            if dbmod.version_label(rom_entry, v_id) == version_combo.get():
                vid = v_id
                break
        if not vid:
            return
        dbmod.clone_version(rom_entry, vid)
        dbmod.save_db(self.cfg["masterdb"]["root"], self.db)
        self._show_masterdb()

    def _version_set_default(self, rom_entry, version_combo):
        for v_id, _ in dbmod.list_versions_sorted(rom_entry):
            if dbmod.version_label(rom_entry, v_id) == version_combo.get():
                dbmod.set_default_version(rom_entry, v_id)
                dbmod.save_db(self.cfg["masterdb"]["root"], self.db)
                self._show_masterdb()
                return

    def _version_delete(self, rom_entry, version_combo):
        if len(rom_entry.get("versions", {})) <= 1:
            messagebox.showwarning("삭제 불가", "최소 1개의 Version은 유지되어야 합니다.")
            return
        if not messagebox.askyesno("삭제 확인", "이 Version을 삭제하시겠습니까?"):
            return
        for v_id, _ in dbmod.list_versions_sorted(rom_entry):
            if dbmod.version_label(rom_entry, v_id) == version_combo.get():
                dbmod.delete_version(rom_entry, v_id)
                dbmod.save_db(self.cfg["masterdb"]["root"], self.db)
                self._show_masterdb()
                return

    # =====================================================================
    # Media 탭 (완전 재작성: 실제 이미지 렌더링 + 게임 전환 시 안전한 상태 관리)
    # =====================================================================
    def _render_media_tab(self, media_tab, media, editable_ref):
        """
        media: { mediatype: path 또는 [path,...] }
        editable_ref: MasterDB의 rom_entry(있으면 탭 선택 기억을 config에 저장), None이면 Local(읽기전용).

        [BUG FIX] 이전 구현은 클로저로 캡처한 상태(last_type)가 갱신되지 않아 탭 강조가
        어긋나고, 미디어 미리보기 영역에 걸어둔 마우스휠->Treeview 바인딩이 다른 게임으로
        전환할 때 참조가 꼬여 목록 선택이 막히는 부작용이 있었다. 이번엔 위젯마다 독립된
        state dict로 관리하고, Treeview에 대한 바인딩은 아예 걸지 않는다.
        """
        state = {"type": self.cfg.get("ui", {}).get("last_selected_media_type", "covers") if editable_ref else "covers",
                  "index": 0}

        tab_row = tk.Frame(media_tab, bg=PANEL); tab_row.pack(fill="x", padx=10, pady=10)
        preview_frame = tk.Frame(media_tab, bg=PANEL2)
        preview_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        nav_row = tk.Frame(media_tab, bg=PANEL); nav_row.pack(fill="x", padx=10, pady=(0, 10))

        def current_list():
            val = media.get(state["type"])
            if not val:
                return []
            return val if isinstance(val, list) else [val]

        def render_tab_buttons():
            for w in tab_row.winfo_children():
                w.destroy()
            for mtype, label in MEDIA_TABS:
                is_sel = state["type"] == mtype
                bg = ACCENT if is_sel else PANEL2
                fg = "#FFFFFF" if is_sel else MUTED
                tk.Button(tab_row, text=label, bg=bg, fg=fg, relief="flat", bd=0,
                          font=("Segoe UI", 9, "bold" if is_sel else "normal"), padx=12, pady=6,
                          cursor="hand2", command=lambda m=mtype: switch_type(m)).pack(side="left", padx=(0, 4))

        def render_preview():
            for w in preview_frame.winfo_children():
                w.destroy()
            for w in nav_row.winfo_children():
                w.destroy()

            items = current_list()
            if not items:
                tk.Label(preview_frame, text="🖼  미디어 없음", bg=PANEL2, fg=MUTED,
                         font=("Segoe UI", 10)).pack(expand=True)
                return

            idx = max(0, min(state["index"], len(items) - 1))
            state["index"] = idx
            path = items[idx]

            photo = load_thumbnail(path, max_width=320, max_height=260)
            if photo:
                lbl = tk.Label(preview_frame, image=photo, bg=PANEL2)
                lbl.image = photo  # GC 방지
                lbl.pack(expand=True, pady=10)
            else:
                tk.Label(preview_frame, text=f"🖼\n{Path(path).name}\n(미리보기 실패)", bg=PANEL2, fg=MUTED,
                         justify="center").pack(expand=True)

            if len(items) > 1:
                ttk.Button(nav_row, text="◀ 이전", command=lambda: move(-1)).pack(side="left")
                tk.Label(nav_row, text=f"{idx + 1} / {len(items)}", bg=PANEL, fg=MUTED,
                         font=FONT_CAPTION).pack(side="left", padx=10)
                ttk.Button(nav_row, text="다음 ▶", command=lambda: move(1)).pack(side="left")

        def move(delta):
            items = current_list()
            if not items:
                return
            state["index"] = (state["index"] + delta) % len(items)
            render_preview()

        def switch_type(mtype):
            state["type"] = mtype
            state["index"] = 0
            if editable_ref is not None:
                self.cfg.setdefault("ui", {})["last_selected_media_type"] = mtype
                cfgmod.save_config(self.cfg)
            render_tab_buttons()
            render_preview()

        render_tab_buttons()
        render_preview()

    def _open_scrape_dialog(self, rom_entry):
        from gui.scraper_dialogs import SingleScrapeDialog

        if not self.cfg.get("scraper", {}).get("devid"):
            messagebox.showwarning("설정 필요", "Settings에서 ScreenScraper API 인증 정보를 먼저 입력해주세요.")
            return
        masterdb_root = self.cfg["masterdb"]["root"]
        SingleScrapeDialog(self.root, self.cfg, self.db, masterdb_root, rom_entry,
                            on_applied=self._show_masterdb)

    def _open_version_diff_dialog(self, rom_entry):
        from gui.dialogs import VersionDiffDialog

        if len(rom_entry.get("versions", {})) <= 1:
            messagebox.showinfo("안내", "비교할 Version이 2개 이상이어야 합니다.")
            return
        masterdb_root = self.cfg["masterdb"]["root"]
        VersionDiffDialog(self.root, self.db, masterdb_root, rom_entry, on_saved=self._show_masterdb)
