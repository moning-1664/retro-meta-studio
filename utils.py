"""
utils.py
========
공용 유틸리티: 타이틀 정규화, 한글화 ROM 판별, 파일명 stem 비교 등.

설계서 v2 부록B 참조.
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# 타이틀 정규화 (동일 metadata / 중복 ROM 판단에 사용)
# ---------------------------------------------------------------------------

# 괄호로 표기된 부가정보 (예: "(USA)", "(Rev 1)", "[!]", "[b]") 제거
_BRACKET_INFO_RE = re.compile(r"[\(\[][^\)\]]*[\)\]]")
# prefix/postfix로 흔히 붙는 한글화 태그 (제거 대상이자 한글 판별 대상)
_KOREAN_TAG_RE = re.compile(
    r"(?:\[(?:K|KR|KO|KOR|KOREAN|KOREA)\]"
    r"|\((?:K|KR|KO|KOR|KOREAN|KOREA)\)"
    r"|(?<![A-Za-z0-9])(?:KOR|KOREAN|KOREA|KR|KO)(?![A-Za-z0-9]))",
    re.IGNORECASE,
)
# 공백류(tab 포함) 및 구두점 정리
_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_EDGE_RE = re.compile(r"^[\s\-_,.]+|[\s\-_,.]+$")


def normalize_title(title):
    """
    타이틀에서 prefix/postfix, 괄호 부가정보, 비문자(tab/space 등)를 제거하고
    비교 가능한 정규화된 형태로 반환한다. (설계서 §3.1 동일 metadata 판단 기준)
    """
    if not title:
        return ""
    t = title
    t = _KOREAN_TAG_RE.sub(" ", t)
    t = _BRACKET_INFO_RE.sub(" ", t)
    t = _WHITESPACE_RE.sub(" ", t).strip()
    t = _NON_ALNUM_EDGE_RE.sub("", t)
    return t.lower()


def is_korean_rom(rom_filename_or_title):
    """
    한글화 ROM 판별 (설계서 §3.2, 부록B):
    파일명에 prefix/postfix 형태로 [K] (KR) Korean KOR KR 등이 포함된 경우.
    """
    if not rom_filename_or_title:
        return False
    return bool(_KOREAN_TAG_RE.search(rom_filename_or_title))


def apply_korean_prefix(title, rom_filename, prefix="[한] "):
    """한글화 ROM으로 판별되면 지정된 prefix를 타이틀에 적용."""
    if is_korean_rom(rom_filename) and not title.startswith(prefix):
        return f"{prefix}{title}"
    return title


# ---------------------------------------------------------------------------
# ROM filename matching normalization (MasterDB -> Local)
# ---------------------------------------------------------------------------

# Only remove *recognized* decoration tokens.  Do not remove arbitrary bracket text,
# because it may be part/episode information that distinguishes different games.
_LANG_TOKEN = r"(?:k|kr|ko|kor|korean|korea|j|jp|jpn|japanese|e|en|eng|english)"
_DISC_TOKEN = r"(?:(?:cd|disc|disk)\s*\d+(?:\s*(?:of|/)\s*\d+)?|\d+\s*(?:of|/)\s*\d+)"
_VER_TOKEN = r"(?:v|ver|version)\s*\d+(?:\.\d+)*"
_REL_TOKEN = r"(?:r|rel|release)\s*(?:\d{4}(?:[-_.]?\d{1,2}){0,2}|\d+)"
_DECOR_TOKEN = rf"(?:{_LANG_TOKEN}|{_DISC_TOKEN}|{_VER_TOKEN}|{_REL_TOKEN})"
_DECOR_BRACKET_RE = re.compile(rf"[\(\[]\s*{_DECOR_TOKEN}\s*[\)\]]", re.IGNORECASE)
_DECOR_UNDERSCORE_RE = re.compile(rf"(?:^|_)\s*{_DECOR_TOKEN}\s*(?=_|$)", re.IGNORECASE)
_EDGE_DECOR_TOKEN = rf"(?:{_DISC_TOKEN}|{_VER_TOKEN}|{_REL_TOKEN})"
_DECOR_EDGE_RE = re.compile(rf"(?:^|[\s._-]){_EDGE_DECOR_TOKEN}(?=$|[\s._-])", re.IGNORECASE)
_MATCH_PUNCT_RE = re.compile(r"[^0-9a-zA-Z가-힣]+")



# Roman numeral normalization for sequel/part numbers. 1..30 only, deliberately
# conservative so ordinary title words are not rewritten.
_ROMAN_TO_INT = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
    "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13,
    "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19,
    "XX": 20, "XXI": 21, "XXII": 22, "XXIII": 23, "XXIV": 24,
    "XXV": 25, "XXVI": 26, "XXVII": 27, "XXVIII": 28, "XXIX": 29, "XXX": 30,
}
_ROMAN_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(sorted(_ROMAN_TO_INT, key=len, reverse=True)) + r")(?![A-Za-z0-9])", re.IGNORECASE)

def _normalize_part_numerals(text):
    def repl(m):
        return str(_ROMAN_TO_INT[m.group(1).upper()])
    return _ROMAN_TOKEN_RE.sub(repl, text)

_KNOWN_ROM_EXTS = {
    ".zip", ".7z", ".rar", ".chd", ".iso", ".cue", ".bin", ".rom", ".nes",
    ".sfc", ".smc", ".gba", ".gb", ".gbc", ".n64", ".z64", ".v64", ".md",
    ".gen", ".sms", ".gg", ".pce", ".dsk", ".dosz", ".m3u", ".cso", ".pbp",
    ".rvz", ".wad", ".wbfs", ".gcz", ".elf", ".xiso", ".xbe", ".ccd", ".img",
}

def _safe_rom_stem(value):
    """Strip only a known ROM extension, never a dotted version suffix such as 1.0."""
    text = str(value)
    suffix = Path(text).suffix.lower()
    return text[:-len(suffix)] if suffix in _KNOWN_ROM_EXTS else text


def normalize_rom_match_title(filename_or_title):
    """Return a conservative filename match key.

    Removes language / disc / version / release decorations only when they are clearly
    tagged.  Standalone sequel/part numbers are preserved, so ``Game 2`` never matches
    ``Game 3``.  The caller must additionally constrain matches to the same system.
    """
    if not filename_or_title:
        return ""
    t = _safe_rom_stem(filename_or_title)
    t = _DECOR_BRACKET_RE.sub(" ", t)
    # Underscore suffix/prefix tags are common in ROM collections (foo_K, foo_ver1.2).
    # Run twice because removing one token can expose another underscore boundary.
    for _ in range(2):
        t = _DECOR_UNDERSCORE_RE.sub("_", t)
    t = _DECOR_EDGE_RE.sub(" ", t)
    t = _MATCH_PUNCT_RE.sub(" ", t).strip().lower()
    # Treat sequel/part numerals such as "VII" and "7" as the same token.
    t = _normalize_part_numerals(t)
    return _WHITESPACE_RE.sub(" ", t)


def rom_match_keys(filename_or_title):
    """Return strongest-to-weakest keys for conservative MasterDB matching.

    The first key keeps the complete normalized title.  Additional keys progressively
    remove trailing `` - subtitle`` segments from the *original* filename.  A fallback
    key is only safe when it resolves to exactly one MasterDB ROM in the same system.
    """
    if not filename_or_title:
        return []
    raw = _safe_rom_stem(filename_or_title)
    variants = [raw]
    parts = re.split(r"\s+-\s+", raw)
    while len(parts) > 1:
        parts = parts[:-1]
        variants.append(" - ".join(parts))
    out = []
    for v in variants:
        key = normalize_rom_match_title(v)
        if key and key not in out:
            out.append(key)
    return out


# ---------------------------------------------------------------------------
# Media 매칭 (파일명 stem 완전일치) - 설계서 §3.1, 부록B
# ---------------------------------------------------------------------------

def rom_stem(rom_filename):
    return Path(rom_filename).stem


def find_matching_media_files(rom_filename, media_dir, extensions=None):
    """
    ROM 파일명(stem) == media 파일명(stem) 완전 일치 기준으로 media_dir 내 파일을 찾는다.
    extensions: 허용 확장자 리스트 (없으면 전체 이미지/비디오 확장자 기본값 사용)
    """
    if extensions is None:
        extensions = [".png", ".jpg", ".jpeg", ".webp", ".mp4", ".avi"]

    media_dir = Path(media_dir)
    if not media_dir.exists():
        return []

    stem = rom_stem(rom_filename)
    matches = []
    for f in media_dir.iterdir():
        if f.is_file() and f.stem == stem and f.suffix.lower() in extensions:
            matches.append(f)
    return matches


# ---------------------------------------------------------------------------
# 크기/개수 표시 포맷
# ---------------------------------------------------------------------------

def format_bytes(num_bytes):
    step = 1024.0
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < step:
            return f"{num_bytes:.2f} {unit}" if unit != "B" else f"{int(num_bytes)} {unit}"
        num_bytes /= step
    return f"{num_bytes:.2f} PB"


def format_count(n):
    return f"{n:,}"


def single_line(text, max_len=120):
    """[BUG FIX] Treeview 등 한 줄 목록에 표시할 때 개행 문자를 공백으로 치환하고 길이를 제한한다.
    ES-DE 등에서 스크랩한 Description에는 실제 줄바꿈 문자가 포함된 경우가 많아,
    그대로 Treeview 셀에 넣으면 행 정렬이 깨져 보였다 (Tk Treeview는 셀 내 줄바꿈을 지원하지 않음)."""
    if not text:
        return ""
    flat = " ".join(str(text).replace("\r", " ").split())
    if len(flat) > max_len:
        flat = flat[: max_len - 1].rstrip() + "…"
    return flat


# ---------------------------------------------------------------------------
# Frontend별 metadata 값 정규화 (Import 시 사용)
# ---------------------------------------------------------------------------

def normalize_esde_date(date_str):
    """ES-DE releasedate 형식(YYYYMMDDT000000)을 'YYYY-MM-DD'로 변환.
    이미 'YYYY-MM-DD' 형식이거나 파싱 불가하면 원본 그대로 반환."""
    if not date_str:
        return ""
    s = date_str.strip()
    if re.fullmatch(r"\d{8}T\d{6}", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return s


def normalize_esde_rating(rating_str):
    """ES-DE rating(0.0~1.0)을 5점 만점 문자열로 변환. 실패 시 원본 반환."""
    if not rating_str:
        return ""
    try:
        val = float(rating_str)
        if 0.0 <= val <= 1.0:
            return f"{val * 5:.1f}"
        return rating_str
    except (ValueError, TypeError):
        return rating_str


# ---------------------------------------------------------------------------
# GUI 보조 헬퍼 (Entry Undo/Redo, 마우스 휠 스크롤)
# 사내 QA 체크리스트 항목 대응: Ctrl+Z/Y가 tk.Entry에는 기본 미지원이라 수동 구현.
# ---------------------------------------------------------------------------

def bind_entry_undo_redo(widget, var, max_history=100):
    """
    tk.Entry + StringVar 조합에 Ctrl+Z(Undo)/Ctrl+Y(Redo)를 수동으로 구현하여 바인딩한다.
    (tk.Entry는 tk.Text와 달리 자체 Undo 스택이 없어 기본적으로 Ctrl+Z가 동작하지 않음)

    Ctrl+C/X/V는 Tk의 기본 가상 이벤트(<<Copy>>/<<Cut>>/<<Paste>>)로 이미 지원되므로 별도 처리 불필요.
    """
    state = {"history": [var.get()], "index": 0, "suppress": False}

    def on_change(*_args):
        if state["suppress"]:
            return
        current = var.get()
        if state["history"][state["index"]] == current:
            return
        # 현재 위치 이후의 redo 이력은 새 입력이 들어오면 버린다
        state["history"] = state["history"][: state["index"] + 1]
        state["history"].append(current)
        if len(state["history"]) > max_history:
            state["history"].pop(0)
        else:
            state["index"] += 1

    def undo(event=None):
        if state["index"] > 0:
            state["index"] -= 1
            state["suppress"] = True
            var.set(state["history"][state["index"]])
            state["suppress"] = False
        return "break"

    def redo(event=None):
        if state["index"] < len(state["history"]) - 1:
            state["index"] += 1
            state["suppress"] = True
            var.set(state["history"][state["index"]])
            state["suppress"] = False
        return "break"

    var.trace_add("write", on_change)
    widget.bind("<Control-z>", undo)
    widget.bind("<Control-y>", redo)
    widget.bind("<Control-Z>", undo)  # 일부 IME/키보드 레이아웃 대비
    return widget


def bind_mousewheel_scroll(widget, scrollable):
    """
    위젯에 마우스 커서를 올렸을 때 스크롤 휠로 scrollable(Treeview 등)을 스크롤할 수 있도록 바인딩.
    Windows는 <MouseWheel> 이벤트(delta 단위 120)를 사용한다.
    """
    def on_wheel(event):
        scrollable.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    widget.bind("<MouseWheel>", on_wheel)
    return widget
