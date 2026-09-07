"""
gui/style.py
============
디자인 토큰 + 재사용 컴포넌트 (v0.3.0 — Minimal & Modern SaaS 리팩토링).

컨셉: Stripe / Vercel / Linear 느낌의 다크모드 SaaS UI.
- 배경/카드/포인트 색상은 사용자가 지정한 팔레트를 그대로 사용
- 라운드 카드(rounded-xl)는 Canvas로 직접 그려서 구현 (Tkinter엔 border-radius가 없음)
- 버튼 Hover는 색상 보간(lerp) 애니메이션으로 부드럽게 처리
"""

import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# 컬러 토큰 (사용자 지정 팔레트)
# ---------------------------------------------------------------------------
BG = "#0F172A"          # 메인 배경 (slate-900)
HEADER = "#0B1220"       # 상단바 (BG보다 살짝 더 어둡게)
PANEL = "#1E293B"         # 카드/패널 (slate-800)
PANEL2 = "#243447"         # 입력창 등 살짝 밝은 표면
PANEL3 = "#2E4057"          # hover/active 표면
CARD = PANEL
BORDER = "#334155"           # slate-600 계열 미세 보더
TEXT = "#F1F5F9"               # slate-100
MUTED = "#94A3B8"                # slate-400
ACCENT = "#6366F1"                 # indigo-500 포인트 컬러
ACCENT_HOVER = "#818CF8"            # 살짝 밝은 hover 색
ACCENT2 = "#818CF8"
SUCCESS = "#22C55E"
WARNING = "#F59E0B"
ERROR = "#EF4444"
GRAY = "#64748B"

STATUS_COLOR = {
    "정상": SUCCESS, "완료": SUCCESS,
    "경고": WARNING, "부분": WARNING, "완료(?)": WARNING,
    "오류": ERROR, "누락": ERROR,
    "미설정": GRAY,
}
STATUS_DOT = {
    "정상": "●", "완료": "●", "경고": "●", "부분": "●",
    "완료(?)": "◐", "오류": "●", "누락": "●", "미설정": "●",
}

# ---------------------------------------------------------------------------
# Typography — 명확한 위계 (Heading / Body / Caption)
# ---------------------------------------------------------------------------
FONT_FAMILY = "Segoe UI"
FONT_H1 = (FONT_FAMILY, 18, "bold")     # 페이지 타이틀
FONT_H2 = (FONT_FAMILY, 13, "bold")      # 섹션 타이틀
FONT_H3 = (FONT_FAMILY, 11, "bold")       # 카드 타이틀
FONT_BODY = (FONT_FAMILY, 10)              # 본문
FONT_BODY_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL = (FONT_FAMILY, 9)                # 보조 텍스트
FONT_CAPTION = (FONT_FAMILY, 8)                # 캡션/라벨
RADIUS = 12                                     # 기본 rounded-xl 반경


def apply_base_style(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=TEXT, font=FONT_BODY)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_CAPTION)
    style.configure("Header.TLabel", background=BG, foreground=TEXT, font=FONT_H2)

    style.configure("TButton", background=PANEL2, foreground=TEXT, font=FONT_BODY,
                     padding=8, borderwidth=0, relief="flat")
    style.map("TButton", background=[("active", PANEL3), ("disabled", PANEL)])

    style.configure("Accent.TButton", background=ACCENT, foreground="#FFFFFF",
                     font=FONT_BODY_BOLD, padding=8, borderwidth=0)
    style.map("Accent.TButton", background=[("active", ACCENT_HOVER)])

    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                     rowheight=30, borderwidth=0, font=FONT_BODY)
    style.configure("Treeview.Heading", background=PANEL2, foreground=MUTED, font=FONT_BODY_BOLD,
                     relief="flat", padding=(10, 8))
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#FFFFFF")])
    style.map("Treeview.Heading", background=[("active", PANEL3)])

    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL2, foreground=MUTED, padding=(14, 8), font=FONT_BODY_BOLD)
    style.map("TNotebook.Tab", background=[("selected", PANEL3)], foreground=[("selected", TEXT)])

    style.configure("TEntry", fieldbackground=PANEL2, foreground=TEXT, insertcolor=TEXT,
                     borderwidth=1, relief="flat")
    style.configure("TCombobox", fieldbackground=PANEL2, foreground=TEXT, borderwidth=1)
    style.configure("TScrollbar", background=PANEL2, troughcolor=PANEL, borderwidth=0, arrowsize=12)

    style.configure("TCheckbutton", background=BG, foreground=TEXT, font=FONT_BODY)
    style.map("TCheckbutton", background=[("active", BG)])

    return style


# ---------------------------------------------------------------------------
# 라운드 카드 (Canvas 기반, rounded-xl 근사)
# ---------------------------------------------------------------------------

def _rounded_rect_points(x1, y1, x2, y2, r):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    if r < 0:
        r = 0
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class RoundedCard(tk.Frame):
    """
    rounded-xl 느낌의 카드 컨테이너. 내부에 일반 tk 위젯을 자유롭게 pack/grid 하면 된다.

    사용법:
        card = RoundedCard(parent, bg=PANEL, border=BORDER, radius=14)
        card.pack(...)
        tk.Label(card.body, text="...", bg=PANEL, ...).pack(...)
    """

    def __init__(self, parent, bg=PANEL, border=BORDER, radius=RADIUS, border_width=1,
                 outer_bg=None, **kwargs):
        outer_bg = outer_bg if outer_bg is not None else _parent_bg(parent)
        super().__init__(parent, bg=outer_bg, **kwargs)
        self._bg = bg
        self._border = border
        self._radius = radius
        self._border_width = border_width

        self.canvas = tk.Canvas(self, bg=outer_bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")

        self.canvas.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        w, h = event.width, event.height
        self.canvas.delete("card_bg")
        if w > 2 and h > 2:
            pts = _rounded_rect_points(1, 1, w - 1, h - 1, self._radius)
            self.canvas.create_polygon(pts, smooth=True, fill=self._bg,
                                        outline=self._border, width=self._border_width, tags="card_bg")
            self.canvas.tag_lower("card_bg")
        self.canvas.itemconfig(self._window, width=w, height=h)


def _parent_bg(widget):
    try:
        return widget["bg"]
    except Exception:
        return BG


# ---------------------------------------------------------------------------
# Hover 애니메이션 버튼 (색상 보간)
# ---------------------------------------------------------------------------

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _lerp_color(c1, c2, t):
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t))


def animate_hover(widget, base_color, hover_color, steps=6, delay=12):
    """
    버튼(tk.Button/tk.Frame 등 'bg' 옵션을 갖는 위젯)에 부드러운 hover color 전환을 적용한다.
    <Enter>/<Leave> 이벤트에서 매 프레임 after()로 색상을 보간하며 다시 그린다.
    """
    state = {"job": None}

    def _step(target, i):
        if state["job"] is not None:
            widget.after_cancel(state["job"])
        t = i / steps
        color = _lerp_color(base_color, hover_color, t) if target == "hover" else _lerp_color(hover_color, base_color, t)
        try:
            widget.configure(bg=color)
        except tk.TclError:
            return
        if i < steps:
            state["job"] = widget.after(delay, lambda: _step(target, i + 1))

    widget.bind("<Enter>", lambda e: _step("hover", 0))
    widget.bind("<Leave>", lambda e: _step("normal", 0))
    return widget
