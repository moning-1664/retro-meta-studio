"""
gui/app.py
==========
Retro Metadata Manager 메인 GUI 컨트롤러.

이 파일은 "코어"만 담당한다: 창 레이아웃, 상단 카드, 좌측 Nav, Dashboard/Settings 진입,
자동 저장, 종료 처리. 각 화면(Local/MasterDB/Detail)의 세부 로직은
gui/mixins/ 아래 파일로 분리되어 있다 (디버깅 시 필요한 파일만 확인하면 되도록 모듈화).

파일 구조 안내는 프로젝트 루트의 MODULE_MAP.md 참고.

[BUG FIX] 이전 버전은 MasterDB 미설정 시 설정 대화창만 예약하고 화면이 비어 있는 채로
멈추는 문제가 있었다. 이제는 Local이 있으면 즉시 Local 화면을 먼저 보여주고,
MasterDB 설정 대화창은 별도로(닫아도 화면이 비지 않도록) 띄운다.

[NEW] 종료 시 설정 자동 저장(WM_DELETE_WINDOW) + 주기적 자동 저장(설정된 간격) 추가.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

import config as cfgmod
import db as dbmod
from gui.style import (
    apply_base_style, BG, HEADER, PANEL, PANEL2, PANEL3, BORDER, ACCENT2,
    TEXT, MUTED, ACCENT, STATUS_COLOR, STATUS_DOT, RoundedCard, animate_hover, FONT_H1, FONT_CAPTION,
)
from gui.dialogs import LocalEditDialog, MasterDBPathDialog
from gui.dashboard import render_dashboard
from gui.settings import render_settings

from gui.mixins.local_view import LocalViewMixin
from gui.mixins.masterdb_view import MasterDBViewMixin
from gui.mixins.detail_panel import DetailPanelMixin

from version import __version__

APP_TITLE = f"Retro Metadata Manager v{__version__}"


class RetroMetadataManagerApp(LocalViewMixin, MasterDBViewMixin, DetailPanelMixin):
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(cfgmod.load_config().get("window_geometry", "1500x900"))
        apply_base_style(root)

        self.cfg = cfgmod.load_config()
        self.db = None
        self._local_scan_cache = {}
        self._local_runtime_cache = {}
        self.current_view = None
        self.current_rom_list = []
        self.selected_rom_key = None

        self._build_layout()
        # Delete 키는 Treeview 포커스 여부와 관계없이 현재 화면의 선택 항목에 적용
        self.root.bind_all("<Delete>", self._on_global_delete)
        self._render_top_bar()
        self._render_nav()

        # [BUG FIX] Local이 있으면 MasterDB 설정 여부와 무관하게 먼저 화면을 채운다.
        if self.cfg.get("locals"):
            self._show_local(self.cfg["locals"][0]["id"])
        elif self.cfg.get("masterdb", {}).get("root"):
            self._show_masterdb()
        else:
            self._render_welcome_placeholder()

        # MasterDB가 설정 안 되어 있으면 최초 실행 안내 대화창을 별도로 띄운다 (설계서 §6).
        # 취소해도 위에서 이미 화면이 채워져 있으므로 빈 화면으로 멈추지 않는다.
        if not self.cfg.get("masterdb", {}).get("root"):
            self.root.after(200, self._prompt_masterdb_setup)

        # [NEW] 종료 시 설정 저장 + 주기적 자동 저장
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._schedule_autosave()

    def _on_global_delete(self, event=None):
        if isinstance(self.current_view, tuple) and self.current_view[0] == "local":
            local = cfgmod.get_local(self.cfg, self.current_view[1])
            if local:
                return self._delete_selected_local_roms(local)
            return "break"
        if isinstance(self.current_view, tuple) and self.current_view[0] == "masterdb":
            self._delete_selected_masterdb_roms()
            return "break"
        return None

    # =====================================================================
    # 자동 저장 / 종료 처리
    # =====================================================================
    def _on_close(self):
        try:
            self.cfg["window_geometry"] = self.root.geometry()
            cfgmod.save_config(self.cfg)
        except Exception:
            pass
        self.root.destroy()

    def _schedule_autosave(self):
        interval_min = self.cfg.get("ui", {}).get("auto_save_interval_min", 5)
        interval_ms = max(1, int(interval_min)) * 60 * 1000

        def tick():
            try:
                cfgmod.save_config(self.cfg)
            except Exception:
                pass
            self.root.after(interval_ms, tick)

        self.root.after(interval_ms, tick)

    def _render_welcome_placeholder(self):
        for w in self.center_frame.winfo_children():
            w.destroy()
        tk.Label(
            self.center_frame,
            text="등록된 Local이나 MasterDB가 없습니다.\n"
                 "상단 '+' 버튼으로 Local을 추가하거나 MasterDB 경로를 설정해주세요.",
            bg=BG, fg=MUTED, font=("Segoe UI", 12), justify="center",
        ).pack(expand=True)

    # =====================================================================
    # 레이아웃 골격
    # =====================================================================
    def _build_layout(self):
        self.top_frame = tk.Frame(self.root, bg=HEADER, height=90)
        self.top_frame.pack(fill="x", side="top")
        self.top_frame.pack_propagate(False)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)

        self.nav_frame = tk.Frame(body, bg=PANEL, width=140)
        self.nav_frame.pack(fill="y", side="left")
        self.nav_frame.pack_propagate(False)

        self.filter_frame = tk.Frame(body, bg=PANEL, width=220)
        self.filter_frame.pack(fill="y", side="left")
        self.filter_frame.pack_propagate(False)

        self.detail_frame = tk.Frame(body, bg=PANEL, width=380)
        self.detail_frame.pack(fill="y", side="right")
        self.detail_frame.pack_propagate(False)

        self.center_frame = tk.Frame(body, bg=BG)
        self.center_frame.pack(fill="both", expand=True, side="left")

        self.bottom_frame = tk.Frame(self.root, bg=PANEL, height=110)
        self.bottom_frame.pack(fill="x", side="bottom")
        self.bottom_frame.pack_propagate(False)

    # =====================================================================
    # 상단: Local / MasterDB 카드 (§5)
    # =====================================================================
    def _render_top_bar(self):
        for w in self.top_frame.winfo_children():
            w.destroy()

        row = tk.Frame(self.top_frame, bg=HEADER)
        row.pack(fill="both", expand=True, padx=10, pady=10)

        # [디자인 개선] 앱 타이틀/버전 브랜딩 박스 (참고 코드 스타일)
        title_box = tk.Frame(row, bg=HEADER)
        title_box.pack(side="left", padx=(4, 14), anchor="w")
        tk.Label(title_box, text="🎮 RETRO METADATA MANAGER", bg=HEADER, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(title_box, text=f"v{__version__}", bg=HEADER, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w")

        for local in self.cfg.get("locals", []):
            self._make_local_card(row, local)

        if cfgmod.can_add_local(self.cfg):
            add_btn = tk.Button(
                row, text="+", font=("Segoe UI", 16, "bold"), bg=PANEL2, fg=TEXT,
                relief="flat", bd=0, width=3, cursor="hand2", command=self._open_add_local_dialog,
            )
            add_btn.pack(side="left", padx=6, fill="y")
            animate_hover(add_btn, PANEL2, PANEL3)

        self._make_masterdb_card(row)

    def _bind_click_recursive(self, widget, handler):
        """[BUG FIX] 카드의 Label 등 자식 위젯을 클릭해도 반응하도록 재귀적으로 바인딩.
        기존에는 card/inner 프레임에만 바인딩되어 있어서, 실제로 눈에 보이는 텍스트(Label)를
        클릭하면 아무 반응이 없었다 (Label은 부모의 바인딩을 자동으로 물려받지 않음)."""
        widget.bind("<Button-1>", handler)
        for child in widget.winfo_children():
            self._bind_click_recursive(child, handler)

    def _make_local_card(self, parent, local):
        is_selected = self.current_view == ("local", local["id"])
        border_color = ACCENT if is_selected else BORDER
        card = RoundedCard(parent, bg=PANEL2, border=border_color, radius=14,
                            border_width=2 if is_selected else 1, outer_bg=HEADER,
                            width=210, height=92)
        card.pack(side="left", padx=6)
        card.pack_propagate(False)

        stats = local.get("stats", {})
        status = local.get("status", "미설정")
        dot_color = STATUS_COLOR.get(status, MUTED)
        dot = STATUS_DOT.get(status, "●")

        inner = tk.Frame(card.body, bg=PANEL2)
        inner.pack(padx=16, pady=10, fill="both", expand=True)

        tk.Label(inner, text=f"💾 {local['label']}", bg=PANEL2, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 2))
        tk.Label(inner, text=f"ROM: {stats.get('rom_count', 0):,}", bg=PANEL2, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w")
        # [요청 반영] 상단 Local 카드에 ROM/Metadata 경로 표시 (길면 말줄임)
        rom_path_text = self._truncate_path(local.get("rom_path", ""))
        tk.Label(inner, text=f"📁 {rom_path_text}", bg=PANEL2, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w")
        tk.Label(inner, text=f"{dot} {status}", bg=PANEL2, fg=dot_color,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(2, 0))

        self._bind_click_recursive(card, lambda e, lid=local["id"]: self._show_local(lid))
        self._bind_click_recursive(inner, lambda e, lid=local["id"]: self._show_local(lid))

    @staticmethod
    def _truncate_path(path, max_len=34):
        if not path:
            return "(경로 미설정)"
        if len(path) <= max_len:
            return path
        head_len = max_len // 2 - 2
        tail_len = max_len - head_len - 3
        return f"{path[:head_len]}...{path[-tail_len:]}"

    def _make_masterdb_card(self, parent):
        root_path = self.cfg.get("masterdb", {}).get("root", "")
        status = self.cfg.get("masterdb", {}).get("status", "미설정")
        if root_path and self.db is None:
            self.db = dbmod.load_db(root_path)
        is_selected = self.current_view == ("masterdb", None)
        is_unset = not root_path

        # [FIX] 미설정 시 카드 자체를 회색(비활성)으로 표시 (설계서 §5, §6)
        card_bg = "#293040" if is_unset else PANEL2
        border_color = BORDER if is_unset else (ACCENT if is_selected else BORDER)
        text_color = "#6B7280" if is_unset else TEXT

        card = RoundedCard(parent, bg=card_bg, border=border_color, radius=14,
                            border_width=2 if is_selected else 1, outer_bg=HEADER,
                            width=210, height=92)
        card.pack(side="right", padx=6)
        card.pack_propagate(False)
        card.configure(cursor=("arrow" if is_unset else "hand2"))

        inner = tk.Frame(card.body, bg=card_bg)
        inner.pack(padx=16, pady=10, fill="both", expand=True)

        tk.Label(inner, text="🗄 MASTER DB", bg=card_bg, fg=text_color, font=("Segoe UI", 10, "bold")).pack(anchor="w")

        if is_unset:
            tk.Label(inner, text="경로 미설정", bg=card_bg, fg="#6B7280", font=("Segoe UI", 8)).pack(anchor="w")
            btn = tk.Button(inner, text="설정하기", bg=ACCENT, fg="white", relief="flat", bd=0, cursor="hand2",
                             activebackground=ACCENT2, command=self._prompt_masterdb_setup)
            btn.pack(anchor="w", pady=(4, 0))
            animate_hover(btn, ACCENT, ACCENT2)
            # 카드 본체 클릭은 비활성 (설정하기 버튼으로만 진입 가능)
        else:
            rom_count = len(self.db.get("roms", {})) if self.db else 0
            meta_count = 0
            if self.db:
                for entry in self.db.get("roms", {}).values():
                    versions = entry.get("versions", {}) or {}
                    if any(any(str(v.get("fields", {}).get(k, "") or "").strip() for k in ("name", "desc", "genre", "developer", "publisher", "releasedate", "region", "players", "rating")) for v in versions.values()):
                        meta_count += 1
            dot_color = STATUS_COLOR.get(status, MUTED)
            dot = STATUS_DOT.get(status, "●")
            tk.Label(inner, text=f"ROM: {rom_count:,}", bg=PANEL2, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
            tk.Label(inner, text=f"Metadata: {meta_count:,}", bg=PANEL2, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
            tk.Label(inner, text=f"{dot} {status}", bg=PANEL2, fg=dot_color,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")
            # [BUG FIX] 최상위 MasterDB 카드를 눌러도 화면 전환이 안 되던 문제
            # -> Label 등 자식까지 전부 재귀 바인딩해야 실제로 클릭이 먹힘
            self._bind_click_recursive(card, lambda e: self._show_masterdb())
            self._bind_click_recursive(inner, lambda e: self._show_masterdb())

    def _open_add_local_dialog(self):
        LocalEditDialog(self.root, self.cfg, on_saved=self._on_local_saved)

    def _on_local_saved(self, entry):
        cfgmod.save_config(self.cfg)
        self._render_top_bar()
        self._render_nav()  # [BUG FIX] Nav의 Local 목록도 즉시 갱신
        self._show_local(entry["id"])

    def _prompt_masterdb_setup(self):
        MasterDBPathDialog(self.root, self.cfg, on_saved=self._on_masterdb_saved)

    def _on_masterdb_saved(self, path):
        dbmod.ensure_masterdb_structure(path)
        self.db = dbmod.load_db(path)
        cfgmod.save_config(self.cfg)
        self._render_top_bar()
        self._show_masterdb()

    # =====================================================================
    # 좌측 Navigation (§4)
    # =====================================================================
    def _render_nav(self):
        for w in self.nav_frame.winfo_children():
            w.destroy()

        current_kind = self.current_view[0] if isinstance(self.current_view, tuple) else self.current_view
        current_local_id = self.current_view[1] if isinstance(self.current_view, tuple) and self.current_view[0] == "local" else None

        LOCAL_STATUS_ICON = {"정상": "●", "경고": "▲", "오류": "✕", "미설정": "○"}

        def section_label(text):
            tk.Label(self.nav_frame, text=text, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=14, pady=(14, 4))

        def nav_btn(parent, text, cmd, indent=False, small=False, active=False):
            # [디자인 개선] 선택 상태를 꽉 찬 accent 블록 대신, 살짝 밝은 배경 + accent 글자색으로
            # 더 은은하게 표시 (참고 코드 스타일 반영)
            bg = PANEL3 if active else PANEL
            fg = ACCENT2 if active else (MUTED if small else TEXT)
            btn = tk.Button(
                parent, text=text, anchor="w", bg=bg, fg=fg,
                relief="flat", font=("Segoe UI", 9 if small else 10, "bold" if active else "normal"),
                padx=(26 if indent else 14), pady=(6 if small else 9),
                command=cmd, activebackground=PANEL3, activeforeground=ACCENT2,
                cursor="hand2", bd=0,
            )
            btn.pack(fill="x", pady=1)
            if not active:
                animate_hover(btn, PANEL, PANEL3)
            return btn

        nav_btn(self.nav_frame, "📊 Dashboard", self._show_dashboard, active=(current_kind == "dashboard"))

        section_label("LOCAL")
        for local in self.cfg.get("locals", []):
            icon = LOCAL_STATUS_ICON.get(local.get("status", "미설정"), "○")
            label = f"{icon} {local['label']} ({cfgmod.FRONTEND_LABELS.get(local['frontend'], local['frontend'])})"
            nav_btn(self.nav_frame, label, lambda lid=local["id"]: self._show_local(lid),
                    indent=True, small=True, active=(local["id"] == current_local_id))
        if cfgmod.can_add_local(self.cfg):
            nav_btn(self.nav_frame, "＋ Local 추가", self._open_add_local_dialog, indent=True, small=True)

        section_label("SERVER")
        nav_btn(self.nav_frame, "🗄 MasterDB", self._show_masterdb, indent=True, small=True,
                active=(current_kind == "masterdb"))

        section_label("")
        nav_btn(self.nav_frame, "⚙ Settings", self._show_settings, active=(current_kind == "settings"))

    def _show_local_nav(self):
        """Nav에 등록된 Local이 하나도 없을 때 안내용으로 남겨둠 (현재는 직접 호출 경로 없음)."""
        locals_ = self.cfg.get("locals", [])
        if not locals_:
            messagebox.showinfo("Local 없음", "등록된 Local이 없습니다. Nav의 '＋ Local 추가'로 등록해주세요.")
            return
        self._show_local(locals_[0]["id"])

    # =====================================================================
    # Dashboard / Settings
    # =====================================================================
    def _show_dashboard(self):
        self.current_view = ("dashboard", None)
        self._render_nav()  # 현재 위치 하이라이트 갱신
        for frame in (self.filter_frame, self.detail_frame):
            for w in frame.winfo_children():
                w.destroy()
        for w in self.bottom_frame.winfo_children():
            w.destroy()
        masterdb_root = self.cfg.get("masterdb", {}).get("root")
        db_data = dbmod.load_db(masterdb_root) if masterdb_root else {"roms": {}}
        render_dashboard(self.center_frame, self.cfg, db_data, masterdb_root=masterdb_root, local_scan_cache=self._local_scan_cache)

    def _show_settings(self):
        self.current_view = ("settings", None)
        self._render_nav()  # 현재 위치 하이라이트 갱신
        for frame in (self.filter_frame, self.detail_frame):
            for w in frame.winfo_children():
                w.destroy()
        for w in self.bottom_frame.winfo_children():
            w.destroy()
        masterdb_root = self.cfg.get("masterdb", {}).get("root")
        db_data = dbmod.load_db(masterdb_root) if masterdb_root else None

        def on_changed():
            cfgmod.save_config(self.cfg)
            self._render_top_bar()
            self._render_nav()  # [BUG FIX] Settings에서 Local 추가/삭제해도 Nav 목록 갱신
            self._show_settings()

        render_settings(self.center_frame, self.cfg, db=db_data, masterdb_root=masterdb_root, on_changed=on_changed)

    # =====================================================================
    def _render_status_bar(self, text):
        if hasattr(self, "status_label_var"):
            self.status_label_var.set(text)


def main():
    root = tk.Tk()
    app = RetroMetadataManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
