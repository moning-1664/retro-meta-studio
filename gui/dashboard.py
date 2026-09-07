"""
gui/dashboard.py
==================
Dashboard 화면 (설계서 v2 §15).
- Local/MasterDB 섞지 않음, 상단 탭으로 전환
- 전체 요약 + 시스템별 상세 통계 테이블 + 원형 그래프 2종
  (ROM 크기 기준 / Media 크기 기준 - ROM "개수"가 아닌 "저장 공간 사용량" 기준, §15 명시)

MasterDB는 실제 ROM 파일을 보유하지 않으므로 ROM 크기 그래프는 Local에서만 제공하고,
MasterDB에서는 자체적으로 보유한 Media 파일의 실제 디스크 사용량 기준 그래프만 제공한다.
"""

import tkinter as tk
from tkinter import ttk
from pathlib import Path

import db as dbmod
from importers.scan import scan_local
from importers.base import directory_size_bytes
from utils import format_bytes, format_count
from gui.style import BG, PANEL, PANEL2, TEXT, MUTED, ACCENT, BORDER, animate_hover

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


def render_dashboard(container, cfg, db, masterdb_root=None, local_scan_cache=None):
    for w in container.winfo_children():
        w.destroy()

    tab_row = tk.Frame(container, bg=BG)
    tab_row.pack(fill="x", padx=10, pady=10)
    body = tk.Frame(container, bg=BG)
    body.pack(fill="both", expand=True, padx=10)

    targets = [("local", l) for l in cfg.get("locals", [])] + [("masterdb", None)]
    if not targets:
        tk.Label(body, text="등록된 Local/MasterDB가 없습니다.", bg=BG, fg=MUTED).pack(expand=True)
        return

    state = {"selected": targets[0]}

    def render_tabs():
        for w in tab_row.winfo_children():
            w.destroy()
        for kind, target in targets:
            label = target["label"] if kind == "local" else "MasterDB"
            is_sel = state["selected"] == (kind, target)
            bg = ACCENT if is_sel else PANEL2
            b = tk.Button(
                tab_row, text=label, bg=bg, fg=TEXT, relief="flat", bd=0, cursor="hand2",
                font=("Segoe UI", 9, "bold" if is_sel else "normal"), padx=16, pady=8,
                command=lambda k=kind, t=target: (state.update(selected=(k, t)), render_tabs(), render_body()),
            )
            b.pack(side="left", padx=4)
            if not is_sel:
                animate_hover(b, PANEL2, PANEL)

    def render_body():
        for w in body.winfo_children():
            w.destroy()
        kind, target = state["selected"]
        if kind == "local":
            _render_local_dashboard(body, target, local_scan_cache or {})
        else:
            _render_masterdb_dashboard(body, db, masterdb_root)

    render_tabs()
    render_body()


def _render_local_dashboard(body, local, local_scan_cache):
    scan_result = local_scan_cache.get(local["id"])
    # Dashboard 진입에서 10,000 ROM 전체 스캔을 동기 실행하면 화면이 1분 이상 멈출 수 있다.
    # 이미 Local에서 스캔한 결과가 있으면 캐시를 사용하고, 없으면 config에 저장된 통계를 즉시 사용한다.
    # 실제 상세 스캔은 사용자가 Local의 Refresh List를 실행할 때 수행한다.
    per_system = scan_result.get("per_system", {}) if scan_result else {}
    stats = (scan_result or {}).get("stats", {}) or local.get("stats", {})
    if not per_system:
        for s, d in (local.get("per_system_stats", {}) or {}).items():
            per_system[s] = d

    _render_summary(body, {
        "ROM 개수": format_count(stats.get("rom_count", 0)),
        "ROM 전체 크기": format_bytes(stats.get("rom_size_bytes", 0)),
        "Media 전체 크기": format_bytes(stats.get("media_size_bytes", 0)),
        "Missing Metadata": format_count(stats.get("missing_metadata", 0)),
        "Missing Media": format_count(stats.get("missing_media", 0)),
    })

    columns = ("system", "rom_count", "rom_size", "media_size", "missing_meta", "missing_media")
    tree = ttk.Treeview(body, columns=columns, show="headings", height=8)
    headers = {"system": "System", "rom_count": "ROM 수", "rom_size": "ROM 크기",
               "media_size": "Media 크기", "missing_meta": "Missing Metadata", "missing_media": "Missing Media"}
    widths = {"system": 140, "rom_count": 90, "rom_size": 110, "media_size": 110,
              "missing_meta": 140, "missing_media": 130}
    # [BUG FIX] anchor를 지정하지 않아 헤더와 셀 내용의 정렬 기준이 서로 달라 보이던 문제.
    # 텍스트(System)는 좌측 정렬, 숫자/용량 컬럼은 우측 정렬로 통일.
    for col in columns:
        anchor = "w" if col == "system" else "e"
        tree.heading(col, text=headers[col], anchor=anchor)
        tree.column(col, width=widths[col], anchor=anchor, stretch=True)
    tree.pack(fill="x", pady=10)
    for s, d in sorted(per_system.items()):
        tree.insert("", "end", values=(
            s, d["rom_count"], format_bytes(d["rom_size"]), format_bytes(d["media_size"]),
            d["missing_metadata"], d["missing_media"],
        ))

    if HAS_MATPLOTLIB and per_system:
        _render_pie_charts(
            body,
            {"labels": list(per_system.keys()),
             "series_a": [d["rom_size"] for d in per_system.values()],
             "series_a_title": "비율 (ROM 크기 기준)",
             "series_b": [d["media_size"] for d in per_system.values()],
             "series_b_title": "비율 (Media 크기 기준)"},
        )
    else:
        tk.Label(body, text="(matplotlib 미설치 - 원형 그래프 생략)", bg=BG, fg=MUTED).pack(anchor="w", pady=6)


def _render_masterdb_dashboard(body, db, masterdb_root):
    roms = db.get("roms", {})
    total_rom = len(roms)
    missing_meta = sum(1 for r in roms.values() if dbmod.rom_status(r) == "누락")

    per_system = {}
    for rom_entry in roms.values():
        s = rom_entry["system"]
        per_system.setdefault(s, {"count": 0})
        per_system[s]["count"] += 1

    if masterdb_root:
        paths = dbmod.db_paths(masterdb_root)
        for s in per_system:
            per_system[s]["media_size"] = directory_size_bytes(paths["media_dir"] / s)
    else:
        for s in per_system:
            per_system[s]["media_size"] = 0

    _render_summary(body, {
        "ROM(게임) 개수": format_count(total_rom),
        "Missing Metadata": format_count(missing_meta),
        "시스템 수": format_count(len(per_system)),
    })

    columns = ("system", "count", "media_size")
    tree = ttk.Treeview(body, columns=columns, show="headings", height=8)
    tree.heading("system", text="System", anchor="w")
    tree.heading("count", text="게임 수", anchor="e")
    tree.heading("media_size", text="Media 크기", anchor="e")
    widths = {"system": 180, "count": 100, "media_size": 130}
    for col in columns:
        anchor = "w" if col == "system" else "e"
        tree.column(col, width=widths[col], anchor=anchor, stretch=True)
    tree.pack(fill="x", pady=10)
    for s, d in sorted(per_system.items()):
        tree.insert("", "end", values=(s, d["count"], format_bytes(d["media_size"])))

    if HAS_MATPLOTLIB and per_system:
        _render_pie_charts(
            body,
            {"labels": list(per_system.keys()),
             "series_a": [d["count"] for d in per_system.values()],
             "series_a_title": "비율 (게임 개수 기준)",
             "series_b": [d["media_size"] for d in per_system.values()],
             "series_b_title": "비율 (Media 크기 기준)"},
        )
        tk.Label(body, text="※ MasterDB는 ROM 파일 자체를 보유하지 않아 ROM 크기 기준 그래프는 제공하지 않습니다.",
                 bg=BG, fg=MUTED).pack(anchor="w", pady=(4, 0))
    else:
        tk.Label(body, text="(matplotlib 미설치 - 원형 그래프 생략)", bg=BG, fg=MUTED).pack(anchor="w", pady=6)


def _render_summary(body, kv_dict):
    from gui.style import RoundedCard, HEADER
    row = tk.Frame(body, bg=BG); row.pack(fill="x", pady=6)
    for k, v in kv_dict.items():
        card = RoundedCard(row, bg=PANEL2, border=BORDER, radius=12, outer_bg=BG, width=140, height=76)
        card.pack(side="left", padx=6)
        card.pack_propagate(False)
        inner = tk.Frame(card.body, bg=PANEL2)
        inner.pack(expand=True, fill="both", padx=14, pady=10)
        tk.Label(inner, text=v, bg=PANEL2, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(inner, text=k, bg=PANEL2, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 0))


def _render_pie_charts(body, spec):
    fig = Figure(figsize=(8, 3.2), facecolor=BG)
    ax1 = fig.add_subplot(121)
    ax2 = fig.add_subplot(122)

    labels = spec["labels"]

    if sum(spec["series_a"]) > 0:
        ax1.pie(spec["series_a"], labels=labels, autopct="%1.1f%%", textprops={"fontsize": 7})
    ax1.set_title(spec["series_a_title"], color=TEXT, fontsize=9)

    if sum(spec["series_b"]) > 0:
        ax2.pie(spec["series_b"], labels=labels, autopct="%1.1f%%", textprops={"fontsize": 7})
    ax2.set_title(spec["series_b_title"], color=TEXT, fontsize=9)

    canvas = FigureCanvasTkAgg(fig, master=body)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="x", pady=10)
