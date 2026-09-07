"""
gui/settings.py
=================
Settings 화면 (설계서 v2 §16).
좌측 메뉴 + 우측 상세. 이번 단계에서는 실제 config와 연결된 항목 위주로 구현하고,
아직 세부 로직이 없는 항목은 placeholder로 표시한다.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import shutil
from pathlib import Path

import config as cfgmod
import db as dbmod
from gui.style import BG, PANEL, PANEL2, PANEL3, TEXT, MUTED, ACCENT

MENU_ITEMS = [
    "일반 설정", "Local 관리", "Server / MasterDB 관리", "Metadata 설정",
    "Export 설정", "한글화 / 표시 설정", "백업 / 복원", "로그 설정", "고급 설정", "단축키 설정",
]


def render_settings(container, cfg, db=None, masterdb_root=None, on_changed=None):
    for w in container.winfo_children():
        w.destroy()

    # [BUG FIX] 하단 공통 버튼(취소/설정저장/기본값복원)을 container에 매번 새로 pack하던 탓에
    # 메뉴를 클릭할 때마다 버튼 줄이 계속 쌓이던 문제. 이제 딱 한 번만 생성한다.
    btn_row = tk.Frame(container, bg=BG)
    btn_row.pack(fill="x", side="bottom", padx=16, pady=10)

    body = tk.Frame(container, bg=BG)
    body.pack(fill="both", expand=True)

    menu_frame = tk.Frame(body, bg=PANEL, width=180)
    menu_frame.pack(fill="y", side="left")
    menu_frame.pack_propagate(False)

    detail_frame = tk.Frame(body, bg=BG)
    detail_frame.pack(fill="both", expand=True, side="left", padx=16, pady=16)

    state = {"selected": MENU_ITEMS[0]}

    def render_menu():
        for w in menu_frame.winfo_children():
            w.destroy()
        for item in MENU_ITEMS:
            is_sel = state["selected"] == item
            bg = PANEL3 if is_sel else PANEL
            fg = ACCENT if is_sel else TEXT
            b = tk.Button(
                menu_frame, text=item, anchor="w", bg=bg, fg=fg,
                relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9, "bold" if is_sel else "normal"),
                padx=16, pady=9,
                command=lambda i=item: (state.update(selected=i), render_menu(), render_detail()),
            )
            b.pack(fill="x")
            if not is_sel:
                from gui.style import animate_hover
                animate_hover(b, PANEL, PANEL3)

    def render_detail():
        for w in detail_frame.winfo_children():
            w.destroy()
        item = state["selected"]
        if item == "일반 설정":
            _render_general(detail_frame, cfg)
        elif item == "Local 관리":
            _render_local_mgmt(detail_frame, cfg, on_changed)
        elif item == "Server / MasterDB 관리":
            _render_masterdb_mgmt(detail_frame, cfg, on_changed)
        elif item == "Metadata 설정":
            _render_metadata_settings(detail_frame, cfg, db, masterdb_root)
        elif item == "Export 설정":
            _render_export_settings(detail_frame, cfg)
        elif item == "한글화 / 표시 설정":
            _render_korean_display_settings(detail_frame, cfg)
        elif item == "백업 / 복원":
            _render_backup_restore(detail_frame, cfg, masterdb_root)
        else:
            tk.Label(detail_frame, text=f"{item} (다음 단계에서 구현 예정)", bg=BG, fg=MUTED,
                     font=("Segoe UI", 11)).pack(anchor="w")

    for w in btn_row.winfo_children():
        w.destroy()
    ttk.Button(btn_row, text="취소", command=lambda: render_detail()).pack(side="right")
    ttk.Button(btn_row, text="설정 저장", style="Accent.TButton",
               command=lambda: (cfgmod.save_config(cfg), messagebox.showinfo("저장됨", "설정이 저장되었습니다."))
               ).pack(side="right", padx=8)
    ttk.Button(btn_row, text="기본값으로 복원",
               command=lambda: messagebox.showinfo("안내", "기본값 복원은 항목별로 개별 지원 예정입니다.")
               ).pack(side="right", padx=8)

    render_menu()
    render_detail()


def _labeled_row(parent, label):
    row = tk.Frame(parent, bg=BG); row.pack(fill="x", pady=6)
    tk.Label(row, text=label, bg=BG, fg=TEXT, width=16, anchor="w").pack(side="left")
    return row


def _render_general(parent, cfg):
    ui = cfg.setdefault("ui", {})
    tk.Label(parent, text="일반 설정", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))

    row = _labeled_row(parent, "언어")
    lang_var = tk.StringVar(value=ui.get("language", "ko"))
    ttk.Combobox(row, textvariable=lang_var, values=["ko", "en"], state="readonly", width=20).pack(side="left")
    lang_var.trace_add("write", lambda *a: ui.__setitem__("language", lang_var.get()))

    row = _labeled_row(parent, "테마")
    theme_var = tk.StringVar(value=ui.get("theme", "system"))
    ttk.Combobox(row, textvariable=theme_var, values=["system", "dark", "light"], state="readonly", width=20).pack(side="left")
    theme_var.trace_add("write", lambda *a: ui.__setitem__("theme", theme_var.get()))

    row = _labeled_row(parent, "자동 저장 간격(분)")
    interval_var = tk.IntVar(value=ui.get("auto_save_interval_min", 5))
    tk.Spinbox(row, from_=1, to=60, textvariable=interval_var, width=6).pack(side="left")
    interval_var.trace_add("write", lambda *a: ui.__setitem__("auto_save_interval_min", interval_var.get()))

    # 유사 ROM 판정 임계값은 일반 설정에서 단일 값만 노출한다.
    sim = cfg.setdefault("similar_rom", {})
    tk.Label(parent, text="유사 ROM 판정 임계값", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(18, 6))
    sim_row = tk.Frame(parent, bg=BG); sim_row.pack(fill="x", pady=4)
    sim_var = tk.IntVar(value=int(sim.get("threshold", 60)))
    scale = tk.Scale(sim_row, from_=0, to=100, orient="horizontal", variable=sim_var,
                     showvalue=False, resolution=1, bg=BG, fg=TEXT, highlightthickness=0, troughcolor=PANEL2, length=360)
    scale.pack(side="left")
    sim_label = tk.Label(sim_row, text=f"{sim_var.get()}%", bg=BG, fg=TEXT, width=5, anchor="w")
    sim_label.pack(side="left", padx=8)
    def update_sim(*_):
        sim["threshold"] = int(sim_var.get()); sim_label.configure(text=f"{sim_var.get()}%")
    sim_var.trace_add("write", update_sim)
    tk.Label(parent, text="낮을수록 유사 판정이 쉬워집니다.", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")

    restore_var = tk.BooleanVar(value=ui.get("restore_last_session", True))
    tk.Checkbutton(parent, text="이전 작업 자동 복원", variable=restore_var, bg=BG, fg=TEXT,
                    selectcolor=PANEL2, activebackground=BG,
                    command=lambda: ui.__setitem__("restore_last_session", restore_var.get())).pack(anchor="w", pady=6)


def _render_local_mgmt(parent, cfg, on_changed):
    from gui.dialogs import LocalEditDialog

    tk.Label(parent, text="Local 관리", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))
    listbox_frame = tk.Frame(parent, bg=BG); listbox_frame.pack(fill="both", expand=True)

    lb = tk.Listbox(listbox_frame, bg=PANEL2, fg=TEXT, height=8)
    lb.pack(fill="x")
    for l in cfg.get("locals", []):
        lb.insert("end", f"{l['label']} ({l['frontend']})")

    btn_row = tk.Frame(parent, bg=BG); btn_row.pack(fill="x", pady=8)

    def add():
        LocalEditDialog(parent.winfo_toplevel(), cfg, on_saved=lambda e: (on_changed() if on_changed else None))

    def edit():
        sel = lb.curselection()
        if not sel:
            return
        existing = cfg["locals"][sel[0]]
        LocalEditDialog(parent.winfo_toplevel(), cfg, existing=existing,
                         on_saved=lambda e: (on_changed() if on_changed else None))

    def delete():
        sel = lb.curselection()
        if not sel:
            return
        target = cfg["locals"][sel[0]]
        if messagebox.askyesno("삭제 확인", f"{target['label']}을(를) 삭제하시겠습니까?"):
            cfgmod.remove_local(cfg, target["id"])
            cfgmod.save_config(cfg)
            if on_changed:
                on_changed()

    ttk.Button(btn_row, text="+ 추가", command=add).pack(side="left", padx=4)
    ttk.Button(btn_row, text="편집", command=edit).pack(side="left", padx=4)
    ttk.Button(btn_row, text="삭제", command=delete).pack(side="left", padx=4)


def _render_masterdb_mgmt(parent, cfg, on_changed):
    from gui.dialogs import MasterDBPathDialog

    tk.Label(parent, text="Server / MasterDB 관리", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(
        anchor="w", pady=(0, 12)
    )
    root = cfg.get("masterdb", {}).get("root", "(미설정)")
    tk.Label(parent, text=f"현재 경로: {root}", bg=BG, fg=MUTED).pack(anchor="w", pady=4)
    ttk.Button(parent, text="경로 변경",
               command=lambda: MasterDBPathDialog(parent.winfo_toplevel(), cfg,
                                                   on_saved=lambda p: (on_changed() if on_changed else None))
               ).pack(anchor="w", pady=8)


def _render_metadata_settings(parent, cfg, db, masterdb_root):
    tk.Label(parent, text="Metadata 설정", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))

    tk.Label(parent, text="Default Core (시스템별)", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(
        anchor="w", pady=(4, 4)
    )

    if db is None:
        tk.Label(parent, text="MasterDB가 설정되어야 Core 관리가 가능합니다.", bg=BG, fg=MUTED).pack(anchor="w")
        return

    columns = ("system", "core", "custom")
    tree = ttk.Treeview(parent, columns=columns, show="headings", height=10)
    tree.heading("system", text="System")
    tree.heading("core", text="Default Core")
    tree.heading("custom", text="Custom")
    for col in columns:
        tree.column(col, width=150)
    tree.pack(fill="x", pady=6)

    def refresh():
        tree.delete(*tree.get_children())
        for system, info in db.get("system_cores", {}).items():
            tree.insert("", "end", iid=system, values=(system, info.get("default_core", ""),
                                                         "Y" if info.get("is_custom") else "N"))

    refresh()

    def edit_selected():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("안내", "시스템을 선택해주세요.")
            return
        from gui.dialogs import CoreSettingDialog
        CoreSettingDialog(parent.winfo_toplevel(), db, sel[0],
                           on_saved=lambda: (dbmod.save_db(masterdb_root, db), refresh()))

    ttk.Button(parent, text="선택 시스템 Core 편집", command=edit_selected).pack(anchor="w", pady=4)

    # --- 버전 일괄 정리 (Feature A) ---
    tk.Label(parent, text="버전 일괄 정리", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(
        anchor="w", pady=(20, 4)
    )
    tk.Label(
        parent,
        text="각 게임의 Default Version에 없는 정보를 non-default 버전들(최신 우선) 값으로 채운 뒤,\n"
             "Default를 제외한 나머지 Version을 모두 삭제합니다. Media(이미지)는 영향을 받지 않습니다.\n"
             "⚠ 되돌릴 수 없는 작업입니다. 먼저 백업하는 것을 권장합니다.",
        bg=BG, fg=MUTED, wraplength=480, justify="left",
    ).pack(anchor="w", pady=(0, 8))

    def run_version_cleanup():
        if db is None or not masterdb_root:
            messagebox.showwarning("MasterDB 없음", "MasterDB가 설정되어야 사용할 수 있습니다.")
            return

        proceed = messagebox.askyesno(
            "⚠ 버전 일괄 정리 경고",
            "이 작업은 Default를 제외한 모든 Version을 영구적으로 삭제합니다.\n"
            "삭제 전 Default에 없는 정보는 자동으로 채워지지만, 되돌릴 수는 없습니다.\n\n"
            "먼저 Settings > 백업/복원에서 백업하는 것을 강력히 권장합니다.\n\n"
            "계속하시겠습니까?",
        )
        if not proceed:
            return
        # 2차 확인
        if not messagebox.askyesno("최종 확인", "정말로 진행하시겠습니까? 이 작업은 취소할 수 없습니다."):
            return

        import db as dbmod
        result = dbmod.cleanup_non_default_versions(db)
        dbmod.save_db(masterdb_root, db)
        messagebox.showinfo(
            "완료",
            f"{result['roms_processed']}개 게임 처리, {result['versions_removed']}개 Version 삭제됨.",
        )

    ttk.Button(parent, text="버전 일괄 정리 실행", command=run_version_cleanup).pack(anchor="w", pady=4)

    # --- CSV Export/Import (Feature C) ---
    tk.Label(parent, text="CSV 일괄 편집", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(
        anchor="w", pady=(20, 4)
    )
    tk.Label(
        parent,
        text="모든 게임의 모든 Version을 CSV로 내보내 엑셀 등에서 일괄 편집한 뒤 다시 가져올 수 있습니다.\n"
             "가져오기는 'add' 방식입니다: CSV의 version_id가 기존과 일치하면 해당 Version을 강제로\n"
             "덮어쓰고, 없으면 새 Version으로 추가합니다. CSV에 없는 기존 데이터는 그대로 유지됩니다.\n"
             "(media/이미지는 CSV에 포함되지 않습니다)",
        bg=BG, fg=MUTED, wraplength=480, justify="left",
    ).pack(anchor="w", pady=(0, 8))

    def do_csv_export():
        if db is None or not masterdb_root:
            messagebox.showwarning("MasterDB 없음", "MasterDB가 설정되어야 사용할 수 있습니다.")
            return
        dest = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="masterdb_metadata.csv",
                                             filetypes=[("CSV files", "*.csv")])
        if not dest:
            return
        from csv_engine import export_db_to_csv
        count = export_db_to_csv(db, dest)
        messagebox.showinfo("완료", f"{count}개 행을 내보냈습니다:\n{dest}")

    def do_csv_import():
        if db is None or not masterdb_root:
            messagebox.showwarning("MasterDB 없음", "MasterDB가 설정되어야 사용할 수 있습니다.")
            return
        src = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if not src:
            return
        from csv_engine import import_csv_to_db
        import db as dbmod
        result = import_csv_to_db(src, db)
        dbmod.save_db(masterdb_root, db)
        msg = f"추가: {result['added']}  /  덮어씀: {result['overwritten']}"
        if result["errors"]:
            msg += f"\n\n오류 {len(result['errors'])}건:\n" + "\n".join(result["errors"][:10])
        messagebox.showinfo("완료", msg)

    csv_btn_row = tk.Frame(parent, bg=BG); csv_btn_row.pack(fill="x", pady=4)
    ttk.Button(csv_btn_row, text="CSV로 내보내기", command=do_csv_export).pack(side="left", padx=(0, 6))
    ttk.Button(csv_btn_row, text="CSV 가져오기", command=do_csv_import).pack(side="left", padx=6)


def _render_export_settings(parent, cfg):
    opts = cfg.setdefault("export_options", {})
    tk.Label(parent, text="Export 설정", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))

    items = [
        ("korean_only_on_conflict", "중복 시 한글화 롬만 복사"),
        ("copy_media", "Media도 복사"),
        ("copy_video", "Video도 복사"),
    ]
    for key, label in items:
        var = tk.BooleanVar(value=opts.get(key, True))
        tk.Checkbutton(parent, text=label, variable=var, bg=BG, fg=TEXT, selectcolor=PANEL2,
                        activebackground=BG, command=lambda k=key, v=var: opts.__setitem__(k, v.get())
                        ).pack(anchor="w", pady=4)

    tk.Label(parent, text="ScreenScraper API 인증", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(
        anchor="w", pady=(16, 6)
    )
    scraper_cfg = cfg.setdefault("scraper", {})
    for key, label in [("devid", "Dev ID"), ("devpassword", "Dev Password"),
                        ("username", "사용자 계정"), ("password", "사용자 비밀번호")]:
        row = _labeled_row(parent, label)
        var = tk.StringVar(value=scraper_cfg.get(key, ""))
        show = "*" if "password" in key else ""
        tk.Entry(row, textvariable=var, bg=PANEL2, fg=TEXT, show=show, bd=1, relief="flat", insertbackground=TEXT).pack(
            side="left", fill="x", expand=True
        )
        var.trace_add("write", lambda *a, k=key, v=var: scraper_cfg.__setitem__(k, v.get()))


def _render_korean_display_settings(parent, cfg):
    tk.Label(parent, text="한글화 / 표시 설정", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(
        anchor="w", pady=(0, 12)
    )
    tk.Label(
        parent,
        text="한글화 판별 규칙: 파일명 prefix/postfix에 [K] (KR) Korean KOR KR 포함 시 (utils.is_korean_rom)",
        bg=BG, fg=MUTED, wraplength=500, justify="left",
    ).pack(anchor="w", pady=4)
    tk.Label(parent, text="세부 표시 언어/Prefix 커스터마이징은 다음 단계에서 확장 예정입니다.",
             bg=BG, fg=MUTED, wraplength=500, justify="left").pack(anchor="w", pady=(10, 0))


def _render_backup_restore(parent, cfg, masterdb_root):
    from backup_engine import create_backup, list_backups, restore_backup

    tk.Label(parent, text="백업 / 복원", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))
    tk.Label(parent, text="백업은 실행 파일 위치의 backup/ 폴더에 날짜/시각을 붙여 저장됩니다.",
             bg=BG, fg=MUTED, wraplength=480, justify="left").pack(anchor="w", pady=(0, 8))

    list_frame = tk.Frame(parent, bg=BG)
    list_frame.pack(fill="both", expand=True, pady=(4, 8))
    backup_listbox = tk.Listbox(list_frame, bg=PANEL2, fg=TEXT, height=8)
    backup_listbox.pack(fill="both", expand=True)

    def refresh_list():
        backup_listbox.delete(0, "end")
        for p in list_backups():
            backup_listbox.insert("end", p.name)

    refresh_list()

    def do_backup():
        if not masterdb_root:
            messagebox.showwarning("MasterDB 없음", "MasterDB가 설정되어야 백업할 수 있습니다.")
            return
        path = create_backup(masterdb_root)
        messagebox.showinfo("완료", f"백업 완료:\n{path}")
        refresh_list()

    def do_restore():
        if not masterdb_root:
            messagebox.showwarning("MasterDB 없음", "MasterDB 경로를 먼저 설정해주세요.")
            return
        sel = backup_listbox.curselection()
        backups = list_backups()
        if not sel or sel[0] >= len(backups):
            messagebox.showinfo("안내", "복원할 백업 파일을 목록에서 선택해주세요.")
            return
        chosen = backups[sel[0]]
        if not messagebox.askyesno("복원 확인", f"'{chosen.name}'으로 현재 MasterDB 데이터를 덮어씁니다.\n"
                                              "계속하시겠습니까?"):
            return
        restore_backup(chosen, masterdb_root)
        messagebox.showinfo("완료", "복원이 완료되었습니다. 프로그램을 재시작해주세요.")

    btn_row = tk.Frame(parent, bg=BG); btn_row.pack(fill="x", pady=4)
    ttk.Button(btn_row, text="지금 백업", command=do_backup).pack(side="left", padx=(0, 6))
    ttk.Button(btn_row, text="선택한 백업으로 복원", command=do_restore).pack(side="left", padx=6)
    ttk.Button(btn_row, text="새로고침", command=refresh_list).pack(side="left", padx=6)
