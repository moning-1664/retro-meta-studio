"""
gui/dialogs.py
===============
- Local 추가/편집 대화창 (설계서 v2 §7, 실사용 피드백 반영 v0.2.1)
  ROM 경로 + "Metadata/Media 경로"(단일 필드) 두 가지만 입력받는다.
  [설계 변경] 지원하는 모든 Frontend(ES-DE/EmulationStation/Pegasus/LaunchBox)는
  metadata와 media가 항상 같은 "루트" 폴더 밑에 있는 구조라서 (예: ES-DE는
  <root>/gamelists/ 와 <root>/downloaded_media/ 가 형제 폴더), Media 경로를
  별도로 입력받을 필요가 없다. media_path는 항상 metadata_path와 동일하게 저장한다.
  same_dir Frontend(Pegasus 등)는 ROM 경로 필드도 비활성화하고 같은 값을 미러링한다.
- MasterDB 경로 설정 대화창 (§6)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import config as cfgmod
from importers.scan import detect_local_structure
from gui.style import BG, PANEL2, TEXT, MUTED, SUCCESS, WARNING, ERROR


class LocalEditDialog(tk.Toplevel):
    def __init__(self, parent, cfg, existing=None, on_saved=None):
        super().__init__(parent)
        self.cfg = cfg
        self.existing = existing
        self.on_saved = on_saved

        self.title("Local 추가" if not existing else f"{existing['label']} 설정")
        self.configure(bg=BG)
        # [BUG FIX] 창이 너무 작아 등록 버튼이 잘려 보이지 않던 문제 -> 충분히 크게 + 리사이즈 가능
        self.geometry("600x480")
        self.minsize(560, 440)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.label_var = tk.StringVar(value=(existing or {}).get("label", f"LOCAL {len(cfg['locals'])+1}"))
        self.frontend_var = tk.StringVar(value=(existing or {}).get("frontend", cfgmod.SUPPORTED_FRONTENDS[0]))
        self.rom_path_var = tk.StringVar(value=(existing or {}).get("rom_path", ""))
        # [설계 변경] Metadata와 Media는 항상 같은 루트 폴더이므로 필드 하나로 통합
        self.metadata_path_var = tk.StringVar(value=(existing or {}).get("metadata_path", ""))
        self.status_text = tk.StringVar(value="")

        self._build_ui()
        self._on_frontend_change()

    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 16, "pady": (10, 2)}

        tk.Label(self, text="Local 이름", bg=BG, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w", **pad)
        tk.Entry(self, textvariable=self.label_var, bg=PANEL2, fg=TEXT, bd=1, relief="flat", insertbackground=TEXT).pack(
            fill="x", padx=16
        )

        tk.Label(self, text="Frontend", bg=BG, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w", **pad)
        fe_combo = ttk.Combobox(
            self, textvariable=self.frontend_var, state="readonly",
            values=[cfgmod.FRONTEND_LABELS[f] for f in cfgmod.SUPPORTED_FRONTENDS],
        )
        # Combobox는 표시용 라벨을 쓰고 내부 값은 별도 매핑
        self._label_to_frontend = {v: k for k, v in cfgmod.FRONTEND_LABELS.items()}
        fe_combo.set(cfgmod.FRONTEND_LABELS.get(self.frontend_var.get(), self.frontend_var.get()))
        fe_combo.bind("<<ComboboxSelected>>", lambda e: self._on_frontend_selected(fe_combo.get()))
        fe_combo.pack(fill="x", padx=16)
        self._fe_combo = fe_combo

        # ROM 경로
        tk.Label(self, text="ROM 경로", bg=BG, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w", **pad)
        rom_row = tk.Frame(self, bg=BG); rom_row.pack(fill="x", padx=16)
        self.rom_entry = tk.Entry(rom_row, textvariable=self.rom_path_var, bg=PANEL2, fg=TEXT, bd=1, relief="flat", insertbackground=TEXT)
        self.rom_entry.pack(side="left", fill="x", expand=True)
        self.rom_browse_btn = ttk.Button(rom_row, text="찾아보기", command=self._browse_rom)
        self.rom_browse_btn.pack(side="left", padx=6)

        # Metadata/Media 경로 (통합)
        tk.Label(self, text="Metadata / Media 경로", bg=BG, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", **pad
        )
        tk.Label(
            self,
            text=self._frontend_hint(self.frontend_var.get()),
            bg=BG, fg=MUTED, font=("Segoe UI", 8), wraplength=560, justify="left",
        ).pack(anchor="w", padx=16)
        self._hint_label = self.winfo_children()[-1]

        meta_row = tk.Frame(self, bg=BG); meta_row.pack(fill="x", padx=16, pady=(2, 0))
        self.meta_entry = tk.Entry(meta_row, textvariable=self.metadata_path_var, bg=PANEL2, fg=TEXT, bd=1, relief="flat", insertbackground=TEXT)
        self.meta_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(meta_row, text="찾아보기", command=self._browse_metadata).pack(side="left", padx=6)

        # 구조 검사
        check_row = tk.Frame(self, bg=BG); check_row.pack(fill="x", padx=16, pady=(14, 4))
        ttk.Button(check_row, text="구조 검사", command=self._do_check).pack(side="left")
        self.status_label = tk.Label(self, textvariable=self.status_text, bg=BG, fg=MUTED,
                                      font=("Segoe UI", 9), wraplength=560, justify="left")
        self.status_label.pack(anchor="w", padx=16, pady=(2, 10))

        # 하단 버튼 (항상 하단 고정 - 창을 줄여도 위쪽 내용이 밀리도록 side="bottom" 먼저 배치)
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=16, pady=12, side="bottom")
        ttk.Button(btn_row, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(btn_row, text="저장" if self.existing else "등록",
                   style="Accent.TButton", command=self._save).pack(side="right", padx=8)

    def _frontend_hint(self, frontend):
        hints = {
            "es-de": "ES-DE의 루트 폴더 하나만 지정하세요 (예: ...\\ES-DE\\ES-DE).\n"
                     "이 폴더 밑에 gamelists\\ 와 downloaded_media\\ 가 함께 있어야 합니다.",
            "emulationstation": "EmulationStation 설정 루트 폴더 하나만 지정하세요\n"
                                 "(gamelists\\ 와 media 폴더가 함께 있는 위치).",
            "pegasus": "Pegasus는 ROM과 Metadata/Media가 모두 같은 폴더입니다.\n"
                       "시스템 폴더들이 들어있는 상위 폴더 하나만 지정하면 됩니다.",
            "launchbox": "LaunchBox 설치 루트 폴더 하나만 지정하세요\n"
                         "(Data\\Platforms\\ 와 Images\\ 가 함께 있는 위치).",
            "daijisho": "다이지쇼 구조는 아직 확인 전입니다 (추후 지원 예정).",
        }
        return hints.get(frontend, "")

    # ------------------------------------------------------------------
    def _on_frontend_selected(self, label_text):
        self.frontend_var.set(self._label_to_frontend.get(label_text, label_text))
        self._on_frontend_change()

    def _on_frontend_change(self):
        """same_dir Frontend면 ROM 경로 필드를 비활성화하고 Metadata/Media 경로 값을 미러링. (§7)"""
        frontend = self.frontend_var.get()
        same_dir = cfgmod.FRONTEND_ROM_METADATA_SAME_DIR.get(frontend, False)

        if hasattr(self, "_hint_label"):
            self._hint_label.configure(text=self._frontend_hint(frontend))

        if same_dir:
            self.rom_path_var.set(self.metadata_path_var.get())
            self.rom_entry.configure(state="disabled", disabledbackground=PANEL2, disabledforeground=MUTED)
            self.rom_browse_btn.configure(state="disabled")
            # metadata 경로가 바뀔 때마다 rom_path를 미러링하도록 trace 등록
            self._mirror_trace_id = self.metadata_path_var.trace_add(
                "write", lambda *a: self.rom_path_var.set(self.metadata_path_var.get())
            )
        else:
            self.rom_entry.configure(state="normal")
            self.rom_browse_btn.configure(state="normal")
            if hasattr(self, "_mirror_trace_id"):
                try:
                    self.metadata_path_var.trace_remove("write", self._mirror_trace_id)
                except Exception:
                    pass

    def _browse_rom(self):
        path = filedialog.askdirectory(parent=self, title="ROM 경로 선택")
        if path:
            self.rom_path_var.set(path)

    def _browse_metadata(self):
        path = filedialog.askdirectory(parent=self, title="Metadata / Media 경로 선택")
        if path:
            self.metadata_path_var.set(path)

    def _do_check(self):
        # media_path는 항상 metadata_path와 동일
        status, msg = detect_local_structure(
            self.rom_path_var.get(), self.metadata_path_var.get(),
            self.metadata_path_var.get(), self.frontend_var.get(),
        )
        color = {"valid": SUCCESS, "warning": WARNING, "invalid": ERROR}.get(status, MUTED)
        self.status_text.set(f"[{status.upper()}] {msg}")
        self.status_label.configure(fg=color)
        return status, msg

    def _save(self):
        # [BUG FIX] 이전에는 media 경로 미입력만 자동으로 통과됐는데(별도 필드였음),
        # 이제 metadata_path가 곧 media_path이므로 이 하나만 확실히 검증하면 된다.
        if not self.metadata_path_var.get().strip():
            messagebox.showwarning("입력 필요", "Metadata / Media 경로를 지정해주세요.", parent=self)
            return
        if not self.rom_path_var.get().strip():
            messagebox.showwarning("입력 필요", "ROM 경로를 지정해주세요.", parent=self)
            return

        status, msg = self._do_check()
        if status == "invalid":
            if not messagebox.askyesno("경고", f"구조 검사 결과가 INVALID입니다:\n{msg}\n\n그래도 등록하시겠습니까?", parent=self):
                return

        if self.existing:
            entry = self.existing
        else:
            if not cfgmod.can_add_local(self.cfg):
                messagebox.showerror("등록 불가", f"Local은 최대 {cfgmod.MAX_LOCALS}개까지 등록할 수 있습니다.", parent=self)
                return
            entry = cfgmod.add_local(self.cfg, self.label_var.get(), self.frontend_var.get())

        entry["label"] = self.label_var.get()
        entry["frontend"] = self.frontend_var.get()
        entry["rom_path"] = self.rom_path_var.get()
        entry["metadata_path"] = self.metadata_path_var.get()
        entry["media_path"] = self.metadata_path_var.get()  # [설계 변경] 항상 metadata와 동일
        entry["rom_metadata_same_dir"] = cfgmod.FRONTEND_ROM_METADATA_SAME_DIR.get(self.frontend_var.get(), False)
        entry["status"] = {"valid": "정상", "warning": "경고", "invalid": "오류"}.get(status, "미설정")

        cfgmod.save_config(self.cfg)
        if self.on_saved:
            self.on_saved(entry)
        self.destroy()


class MasterDBPathDialog(tk.Toplevel):
    """최초 실행 시 / Server 관리에서 MasterDB 경로 설정 (설계서 §6)"""

    def __init__(self, parent, cfg, on_saved=None):
        super().__init__(parent)
        self.cfg = cfg
        self.on_saved = on_saved
        self.title("MasterDB 경로 설정")
        self.configure(bg=BG)
        self.geometry("480x220")
        self.transient(parent)
        self.grab_set()

        self.path_var = tk.StringVar(value=cfg.get("masterdb", {}).get("root", ""))

        tk.Label(self, text="MasterDB 경로 설정", bg=BG, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        tk.Label(
            self, text="MasterDB를 사용하려면 저장 위치를 먼저 지정해야 합니다.",
            bg=BG, fg=MUTED, wraplength=440, justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 10))

        row = tk.Frame(self, bg=BG); row.pack(fill="x", padx=16)
        tk.Entry(row, textvariable=self.path_var, bg=PANEL2, fg=TEXT, bd=1, relief="flat", insertbackground=TEXT).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(row, text="찾기", command=self._browse).pack(side="left", padx=6)

        tk.Label(
            self, text="이 폴더에 MasterDB 데이터가 저장되며, JSON 및 미디어 파일이 관리됩니다.",
            bg=BG, fg=MUTED, wraplength=440, justify="left"
        ).pack(anchor="w", padx=16, pady=(10, 0))

        btn_row = tk.Frame(self, bg=BG); btn_row.pack(fill="x", padx=16, pady=16, side="bottom")
        ttk.Button(btn_row, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(btn_row, text="확인", style="Accent.TButton", command=self._save).pack(side="right", padx=8)

    def _browse(self):
        path = filedialog.askdirectory(parent=self, title="MasterDB 경로 선택")
        if path:
            self.path_var.set(path)

    def _save(self):
        if not self.path_var.get().strip():
            messagebox.showwarning("입력 필요", "경로를 지정해주세요.", parent=self)
            return
        self.cfg["masterdb"]["root"] = self.path_var.get()
        self.cfg["masterdb"]["status"] = "정상"
        cfgmod.save_config(self.cfg)
        if self.on_saved:
            self.on_saved(self.path_var.get())
        self.destroy()


class ExportConflictDialog(tk.Toplevel):
    """
    Export 충돌 대화창 (설계서 v2 §3.2).
    좌우 비교(diff) + [OK] [Skip] [Replace All] [Skip All] 버튼.
    modal로 띄우고 wait_window로 결과를 동기적으로 반환한다.

    사용법:
        dlg = ExportConflictDialog(root, rom_filename, existing_fields, new_fields)
        root.wait_window(dlg)
        action = dlg.result  # "ok" | "skip" | "replace_all" | "skip_all"
    """

    FIELD_LABELS = [
        ("name", "Title"), ("desc", "Description"), ("genre", "Genre"),
        ("developer", "Developer"), ("publisher", "Publisher"),
        ("releasedate", "Release"), ("region", "Region"),
        ("players", "Players"), ("rating", "Rating"),
    ]

    def __init__(self, parent, rom_filename, existing_fields, new_fields):
        super().__init__(parent)
        self.result = None
        self.title("Metadata 충돌 발견")
        self.configure(bg=BG)
        self.geometry("620x420")
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text=f"⚠ Metadata 충돌 발견", bg=BG, fg=WARNING,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self, text=rom_filename, bg=BG, fg=TEXT, font=("Segoe UI", 10)).pack(
            anchor="w", padx=16, pady=(0, 10)
        )

        table = tk.Frame(self, bg=BG)
        table.pack(fill="both", expand=True, padx=16)

        tk.Label(table, text="기존 (Local)", bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )
        tk.Label(table, text="신규 (MasterDB)", bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=2, sticky="w", padx=6, pady=4
        )

        existing_fields = existing_fields or {}
        for r, (key, label) in enumerate(self.FIELD_LABELS, start=1):
            old_val = str(existing_fields.get(key, ""))
            new_val = str(new_fields.get(key, ""))
            differs = old_val.strip() != new_val.strip()
            bg_old = WARNING if differs else BG
            bg_new = WARNING if differs else BG

            tk.Label(table, text=label, bg=BG, fg=TEXT, font=("Segoe UI", 9, "bold")).grid(
                row=r, column=0, sticky="w", padx=6, pady=2
            )
            tk.Label(table, text=old_val or "-", bg=BG, fg=(BG if differs else MUTED),
                     wraplength=220, justify="left",
                     **({"bg": PANEL2} if not differs else {"bg": "#3A2E10", "fg": TEXT})).grid(
                row=r, column=1, sticky="w", padx=6, pady=2
            )
            tk.Label(table, text=new_val or "-", wraplength=220, justify="left",
                     **({"bg": PANEL2, "fg": MUTED} if not differs else {"bg": "#123A1E", "fg": TEXT})).grid(
                row=r, column=2, sticky="w", padx=6, pady=2
            )

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=16, pady=16, side="bottom")
        ttk.Button(btn_row, text="Skip All", command=lambda: self._choose("skip_all")).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Replace All", command=lambda: self._choose("replace_all")).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Skip", command=lambda: self._choose("skip")).pack(side="right", padx=4)
        ttk.Button(btn_row, text="OK", style="Accent.TButton", command=lambda: self._choose("ok")).pack(
            side="right", padx=4
        )

    def _choose(self, action):
        self.result = action
        self.destroy()


class CoreSettingDialog(tk.Toplevel):
    """
    Core 설정 대화창 (설계서 v2 §17).
    현재 System / 현재 값 / 리스트형 선택(해당 시스템 호환 core만) / (v) 모든 롬에 덮어쓰기
    """

    # 시스템 -> 호환 가능한 RetroArch core 목록 (알려진 매핑, 없으면 전체 목록+직접입력)
    SYSTEM_CORE_OPTIONS = {
        "snes": ["snes9x", "bsnes", "bsnes-mercury-balanced", "mesen-s"],
        "nes": ["fceumm", "mesen", "nestopia", "quicknes"],
        "megadrive": ["genesis_plus_gx", "picodrive", "blastem"],
        "genesis": ["genesis_plus_gx", "picodrive", "blastem"],
        "gba": ["mgba", "vba_next", "gpsp"],
        "gb": ["gambatte", "mgba", "sameboy"],
        "gbc": ["gambatte", "mgba", "sameboy"],
        "psx": ["beetle_psx", "beetle_psx_hw", "pcsx_rearmed"],
        "ps1": ["beetle_psx", "beetle_psx_hw", "pcsx_rearmed"],
        "n64": ["mupen64plus_next", "parallel_n64"],
        "arcade": ["fbneo", "mame2003_plus", "mame"],
        "neogeo": ["fbneo", "mame2003_plus"],
        "pcengine": ["mednafen_pce", "mednafen_pce_fast"],
        "dreamcast": ["flycast"],
        "saturn": ["mednafen_saturn", "yabause"],
    }
    # 매핑에 없는 시스템을 위한 폴백 전체 목록 (§17: "어려우면 모든 가능한 core를 다 표기")
    ALL_KNOWN_CORES = sorted({c for lst in SYSTEM_CORE_OPTIONS.values() for c in lst})

    def __init__(self, parent, db, system, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.system = system
        self.on_saved = on_saved

        self.title("Core 설정")
        self.configure(bg=BG)
        self.geometry("420x280")
        self.transient(parent)
        self.grab_set()

        current = db.get("system_cores", {}).get(system, {})
        current_core = current.get("default_core", "(미설정)")

        tk.Label(self, text="Core 설정", bg=BG, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=16, pady=(16, 10)
        )
        tk.Label(self, text=f"현재 System : {system}", bg=BG, fg=TEXT).pack(anchor="w", padx=16)
        tk.Label(self, text=f"현재 값     : {current_core}", bg=BG, fg=MUTED).pack(anchor="w", padx=16, pady=(0, 10))

        tk.Label(self, text="변경", bg=BG, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16)
        options = self.SYSTEM_CORE_OPTIONS.get(system, self.ALL_KNOWN_CORES)
        self.core_var = tk.StringVar(value=current.get("default_core", options[0] if options else ""))
        self.combo = ttk.Combobox(self, textvariable=self.core_var, values=options + ["(직접 입력)"])
        self.combo.pack(fill="x", padx=16, pady=4)

        self.overwrite_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="모든 롬에 덮어쓰기", variable=self.overwrite_var,
                        bg=BG, fg=TEXT, selectcolor=PANEL2, activebackground=BG).pack(anchor="w", padx=16, pady=10)

        btn_row = tk.Frame(self, bg=BG); btn_row.pack(fill="x", padx=16, pady=16, side="bottom")
        ttk.Button(btn_row, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(btn_row, text="확인", style="Accent.TButton", command=self._save).pack(side="right", padx=8)

    def _save(self):
        import db as dbmod

        core_name = self.core_var.get().strip()
        if not core_name or core_name == "(직접 입력)":
            messagebox.showwarning("입력 필요", "Core를 선택하거나 입력해주세요.", parent=self)
            return

        is_custom = core_name not in self.SYSTEM_CORE_OPTIONS.get(self.system, self.ALL_KNOWN_CORES)
        dbmod.set_system_default_core(self.db, self.system, core_name, is_custom=is_custom)

        if self.overwrite_var.get():
            count = dbmod.apply_core_to_all_roms_in_system(self.db, self.system, core_name)
            messagebox.showinfo("완료", f"{self.system} 시스템의 ROM {count}개에 core가 적용되었습니다.", parent=self)

        if self.on_saved:
            self.on_saved()
        self.destroy()


class SystemMappingDialog(tk.Toplevel):
    """
    Local의 시스템(폴더)명 <-> MasterDB canonical(ES-DE 기준) 시스템명 매핑 편집.

    Pegasus/다이지쇼 등 Local의 시스템 폴더명이 ES-DE 표준과 다를 수 있으므로
    (예: 'super_nintendo' vs 'snes'), Import/Export 시 올바르게 매칭되도록 매핑을 지정한다.
    매핑하지 않으면 원본 이름을 그대로 사용한다 (identity).
    """

    def __init__(self, parent, cfg, local_entry, on_saved=None):
        super().__init__(parent)
        self.cfg = cfg
        self.local_entry = local_entry
        self.on_saved = on_saved

        self.title(f"{local_entry['label']} - 시스템 이름 매핑")
        self.configure(bg=BG)
        self.geometry("520x440")
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text="시스템 이름 매핑", bg=BG, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        tk.Label(
            self,
            text="이 Local의 시스템(폴더)명이 MasterDB 표준(ES-DE 기준)과 다르면 매핑을 지정하세요.\n"
                 "비워두면 원본 이름을 그대로 사용합니다.",
            bg=BG, fg=MUTED, wraplength=480, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        from importers import get_importer

        importer = get_importer(local_entry["frontend"])
        try:
            raw_systems = importer.list_systems(local_entry["rom_path"], local_entry["metadata_path"])
        except Exception:
            raw_systems = []

        table_frame = tk.Frame(self, bg=BG)
        table_frame.pack(fill="both", expand=True, padx=16)

        self._entry_vars = {}
        mapping = local_entry.get("system_name_map", {})

        if not raw_systems:
            tk.Label(table_frame, text="스캔된 시스템이 없습니다. 먼저 Refresh List를 실행해주세요.",
                     bg=BG, fg=MUTED).pack(pady=20)
        else:
            header = tk.Frame(table_frame, bg=BG); header.pack(fill="x", pady=4)
            tk.Label(header, text="Local 시스템명", bg=BG, fg=MUTED, width=22, anchor="w").pack(side="left")
            tk.Label(header, text="MasterDB 시스템명", bg=BG, fg=MUTED, width=22, anchor="w").pack(side="left")

            for raw in raw_systems:
                row = tk.Frame(table_frame, bg=BG); row.pack(fill="x", pady=2)
                tk.Label(row, text=raw, bg=BG, fg=TEXT, width=22, anchor="w").pack(side="left")
                var = tk.StringVar(value=mapping.get(raw, raw))
                tk.Entry(row, textvariable=var, bg=PANEL2, fg=TEXT, width=22, bd=1, relief="flat", insertbackground=TEXT).pack(side="left")
                self._entry_vars[raw] = var

        btn_row = tk.Frame(self, bg=BG); btn_row.pack(fill="x", padx=16, pady=16, side="bottom")
        ttk.Button(btn_row, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(btn_row, text="저장", style="Accent.TButton", command=self._save).pack(side="right", padx=8)

    def _save(self):
        new_map = {}
        for raw, var in self._entry_vars.items():
            canon = var.get().strip()
            if canon and canon != raw:
                new_map[raw] = canon
        self.local_entry["system_name_map"] = new_map
        cfgmod.save_config(self.cfg)
        if self.on_saved:
            self.on_saved()
        self.destroy()


class VersionDiffDialog(tk.Toplevel):
    """
    Metadata Version Comparison & Edit (설계서 후속, 9번 목업 참조).

    좌우 2개 Version을 나란히 놓고 편집/비교/삭제한다. 3개 이상의 Version이 있어도
    상단 드롭다운으로 고른 2개만 비교하는 구조다 (전체 Version을 한 화면에 다루지 않음).

    기본 선택: 좌측 = Default Version, 우측 = Default가 아닌 것 중 가장 최근(latest) Version.
    [Ver Diff] 버튼은 Version이 2개 이상일 때만 활성화된다 (호출부에서 체크).
    """

    def __init__(self, parent, db, masterdb_root, rom_entry, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.masterdb_root = masterdb_root
        self.rom_entry = rom_entry
        self.on_saved = on_saved

        self.title("Metadata Version Comparison & Edit")
        self.configure(bg=BG)
        self.geometry("820x560")
        self.transient(parent)
        self.grab_set()

        import db as dbmod
        self._dbmod = dbmod

        sorted_versions = dbmod.list_versions_sorted(rom_entry)
        self._version_labels = [dbmod.version_label(rom_entry, vid) for vid, _ in sorted_versions]
        self._label_to_vid = {dbmod.version_label(rom_entry, vid): vid for vid, _ in sorted_versions}

        default_vid = rom_entry.get("default_version_id")
        non_default_vids = [vid for vid, _ in sorted_versions if vid != default_vid]
        # 기본: 좌측=Default, 우측=Default가 아닌 것 중 가장 최근(list는 이미 오래된->최신 순이므로 마지막)
        left_default_vid = default_vid
        right_default_vid = non_default_vids[-1] if non_default_vids else default_vid

        self._field_defs = [
            ("name", "제목"), ("desc", "상세 설명"), ("genre", "장르"),
            ("developer", "개발사"), ("publisher", "배급사"),
            ("releasedate", "출시일"), ("region", "지역"),
            ("players", "인원"), ("rating", "평점"),
        ]

        # 각 슬롯의 상태: version_id + StringVar들 (None이면 삭제됨/비활성)
        self.left = {"vid": left_default_vid, "vars": {}}
        self.right = {"vid": right_default_vid, "vars": {}}

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        top_row = tk.Frame(self, bg=BG); top_row.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(top_row, text="버전 선택", bg=BG, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")

        pick_row = tk.Frame(self, bg=BG); pick_row.pack(fill="x", padx=16)
        left_col = tk.Frame(pick_row, bg=BG); left_col.pack(side="left", fill="x", expand=True, padx=(0, 8))
        right_col = tk.Frame(pick_row, bg=BG); right_col.pack(side="left", fill="x", expand=True, padx=(8, 0))

        tk.Label(left_col, text="현재 버전", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.left_combo = ttk.Combobox(left_col, values=self._version_labels, state="readonly")
        self.left_combo.set(self._dbmod.version_label(self.rom_entry, self.left["vid"]))
        self.left_combo.pack(fill="x")
        self.left_combo.bind("<<ComboboxSelected>>", lambda e: self._on_slot_version_change("left"))

        tk.Label(right_col, text="비교 대상", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.right_combo = ttk.Combobox(right_col, values=self._version_labels, state="readonly")
        self.right_combo.set(self._dbmod.version_label(self.rom_entry, self.right["vid"]))
        self.right_combo.pack(fill="x")
        self.right_combo.bind("<<ComboboxSelected>>", lambda e: self._on_slot_version_change("right"))

        # 필드 비교 영역
        self.fields_frame = tk.Frame(self, bg=BG)
        self.fields_frame.pack(fill="both", expand=True, padx=16, pady=8)

        # 삭제 버튼 영역
        del_row = tk.Frame(self, bg=BG); del_row.pack(fill="x", padx=16, pady=(4, 8))
        self.left_delete_btn = ttk.Button(del_row, text="Delete This Version [좌]",
                                           command=lambda: self._delete_slot("left"))
        self.left_delete_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.right_delete_btn = ttk.Button(del_row, text="Delete This Version [우]",
                                            command=lambda: self._delete_slot("right"))
        self.right_delete_btn.pack(side="left", fill="x", expand=True, padx=(8, 0))

        # 하단 버튼
        btn_row = tk.Frame(self, bg=BG); btn_row.pack(fill="x", padx=16, pady=16, side="bottom")
        ttk.Button(btn_row, text="취소 (Cancel)", command=self.destroy).pack(side="right")
        ttk.Button(btn_row, text="저장 (Save)", style="Accent.TButton", command=self._save).pack(
            side="right", padx=8
        )

        self._render_fields()

    def _on_slot_version_change(self, side):
        combo = self.left_combo if side == "left" else self.right_combo
        vid = self._label_to_vid.get(combo.get())
        if vid:
            (self.left if side == "left" else self.right)["vid"] = vid
            self._render_fields()

    def _render_fields(self):
        for w in self.fields_frame.winfo_children():
            w.destroy()
        self.left["vars"] = {}
        self.right["vars"] = {}

        left_fields = self.rom_entry["versions"][self.left["vid"]]["fields"] if self.left["vid"] else {}
        right_fields = self.rom_entry["versions"][self.right["vid"]]["fields"] if self.right["vid"] else {}

        header = tk.Frame(self.fields_frame, bg=BG); header.grid_forget()
        for r, (key, label) in enumerate(self._field_defs):
            tk.Label(self.fields_frame, text=label, bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold")).grid(
                row=r, column=0, sticky="w", padx=(0, 8), pady=3
            )

            lv = left_fields.get(key, "") if left_fields else ""
            rv = right_fields.get(key, "") if right_fields else ""
            differs = str(lv).strip() != str(rv).strip()
            bg_color = "#3A2E10" if differs else PANEL2

            left_var = tk.StringVar(value=str(lv))
            right_var = tk.StringVar(value=str(rv))
            self.left["vars"][key] = left_var
            self.right["vars"][key] = right_var

            le = tk.Entry(self.fields_frame, textvariable=left_var, bg=bg_color, fg=TEXT, bd=1, relief="flat",
                           insertbackground=TEXT,
                           state=("normal" if self.left["vid"] else "disabled"))
            le.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
            re_ = tk.Entry(self.fields_frame, textvariable=right_var, bg=bg_color, fg=TEXT, bd=1, relief="flat",
                            insertbackground=TEXT,
                            state=("normal" if self.right["vid"] else "disabled"))
            re_.grid(row=r, column=2, sticky="ew", padx=4, pady=3)

        self.fields_frame.columnconfigure(1, weight=1)
        self.fields_frame.columnconfigure(2, weight=1)

        self.left_delete_btn.configure(state=("normal" if self.left["vid"] else "disabled"))
        self.right_delete_btn.configure(state=("normal" if self.right["vid"] else "disabled"))

    def _current_slot_fields(self, side):
        """슬롯의 현재 편집 중인 값들을 dict로 수집."""
        slot = self.left if side == "left" else self.right
        if not slot["vid"]:
            return None
        result = {}
        for key, var in slot["vars"].items():
            result[key] = var.get()
        return result

    def _delete_slot(self, side):
        slot = self.left if side == "left" else self.right
        other = self.right if side == "left" else self.left

        if not slot["vid"]:
            return
        if len(self.rom_entry.get("versions", {})) <= 1:
            messagebox.showwarning("삭제 불가", "최소 1개의 Version은 유지되어야 합니다.")
            return
        if not messagebox.askyesno("⚠ 경고", "이 Version을 삭제합니다. 되돌릴 수 없습니다.\n계속하시겠습니까?"):
            return
        if not messagebox.askyesno("최종 확인", "정말로 삭제하시겠습니까?"):
            return

        # 삭제될 슬롯의 (현재 편집중인) 값 중, 반대편에 없는 정보는 반대편으로 이전
        deleted_fields = self._current_slot_fields(side)
        if other["vid"] and deleted_fields:
            other_fields = self._current_slot_fields(side="right" if side == "left" else "left")
            merged = self._dbmod.migrate_unique_fields(deleted_fields, other_fields)
            for key, val in merged.items():
                if key in other["vars"]:
                    other["vars"][key].set(str(val))
            # DB에도 즉시 반영 (편집 중인 값 기준으로 병합 저장)
            self.rom_entry["versions"][other["vid"]]["fields"].update(merged)

        self._dbmod.delete_version(self.rom_entry, slot["vid"])
        self._dbmod.save_db(self.masterdb_root, self.db)

        slot["vid"] = None
        remaining = self._dbmod.list_versions_sorted(self.rom_entry)
        if len(remaining) < 2:
            messagebox.showinfo("안내", "비교할 Version이 1개 이하로 남아 창을 닫습니다.")
            if self.on_saved:
                self.on_saved()
            self.destroy()
            return

        # 콤보박스 갱신
        self._version_labels = [self._dbmod.version_label(self.rom_entry, vid) for vid, _ in remaining]
        self._label_to_vid = {self._dbmod.version_label(self.rom_entry, vid): vid for vid, _ in remaining}
        self.left_combo.configure(values=self._version_labels)
        self.right_combo.configure(values=self._version_labels)
        if slot is self.left:
            self.left_combo.set("")
        else:
            self.right_combo.set("")
        self._render_fields()

    def _save(self):
        left_fields = self._current_slot_fields("left")
        right_fields = self._current_slot_fields("right")

        left_empty = left_fields is None or self._dbmod.is_version_empty(left_fields)
        right_empty = right_fields is None or self._dbmod.is_version_empty(right_fields)

        if left_empty and right_empty:
            messagebox.showerror("저장 불가", "두 버전 모두 빈 메타데이터(제목/설명 없음)입니다.\n"
                                            "저장할 수 없습니다.")
            return

        # 한쪽만 비어있으면 자동 삭제 + 정보 이전
        if left_empty and self.left["vid"]:
            if right_fields:
                merged = self._dbmod.migrate_unique_fields(left_fields or {}, right_fields)
                self.rom_entry["versions"][self.right["vid"]]["fields"].update(merged)
            self._dbmod.delete_version(self.rom_entry, self.left["vid"])
        elif self.left["vid"] and left_fields:
            self.rom_entry["versions"][self.left["vid"]]["fields"].update(left_fields)

        if right_empty and self.right["vid"]:
            if left_fields:
                merged = self._dbmod.migrate_unique_fields(right_fields or {}, left_fields)
                self.rom_entry["versions"][self.left["vid"]]["fields"].update(merged)
            self._dbmod.delete_version(self.rom_entry, self.right["vid"])
        elif self.right["vid"] and right_fields:
            self.rom_entry["versions"][self.right["vid"]]["fields"].update(right_fields)

        self._dbmod.save_db(self.masterdb_root, self.db)
        if self.on_saved:
            self.on_saved()
        self.destroy()
