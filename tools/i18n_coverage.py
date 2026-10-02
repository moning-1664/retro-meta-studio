"""tools/i18n_coverage.py
==========================
번역표에 없는 한글 UI 문구를 찾아 보여주는 **참고용 리포트 도구**다(개발자가 직접
실행해서 읽는다 - CI를 막는 pass/fail 테스트가 아니다. 이유는
이 도구의 조각 기반 분석에는 오탐이 있다).

필수 검사는 tools/validate_ui_translations.py를 사용한다. 이 검사는 AST로
프런트엔드 문구와 알려진 백엔드 메시지를 추출하고, 네 외국어 누락을 실패 처리한다.
이 파일은 기존 참고 리포트의 호환성을 유지한다.

정적 분석이라 두 종류의 오탐이 있다.

- 사용자 데이터(게임 제목, Collection/System/Storage 이름, 파일 경로)가 우연히
  한글이면 걸린다 - 이건 번역 대상이 애초에 아니다(PART 19).
- 백틱 템플릿 리터럴의 `${...}` 보간 부분은 실행해 봐야 알 수 있는 값이라, 여기서는
  그 부분을 잘라내고 **남은 한글 조각**만 본다. 조각이 i18n.js의 정규식 PATTERNS로
  덮여 있어도(예: "${label} 전체" 같은 모양) 여기서는 그 사실을 모르므로 다시 걸릴
  수 있다 - 그래서 `--ignore`로 알려진 오탐을 계속 뺄 수 있게 했다.

사용:
    python tools/i18n_coverage.py                 # 전체 리포트
    python tools/i18n_coverage.py --area system    # AREA_HINTS로 좁힌 파일/영역만
    python tools/i18n_coverage.py --list-areas
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "gui_web"
DATA_JS = GUI / "i18n-data.js"
EXTRA_JS = GUI / "i18n-extra.js"

HANGUL_RE = re.compile(r"[가-힣]")
#: 큰따옴표/작은따옴표 문자열 리터럴과 백틱 템플릿을 함께 잡는다. 이스케이프된
#: 따옴표(`\"`)가 있는 흔한 경우까지는 처리하고, 그 이상의 복잡한 이스케이프는
#: 놓칠 수 있다(리포트 도구이므로 완벽할 필요는 없다).
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|`([^`]*)`')
#: 백틱 템플릿의 `${...}` 보간 - 중첩 괄호는 얕게만(실제 코드에서 이 안에 다시
#: 백틱/중괄호가 오는 경우는 드물다).
_INTERP_RE = re.compile(r"\$\{[^{}]*\}")

#: PART 17이 특히 확인하라고 지목한 영역 -> 이 문자열이 코드에 있으면 근처(±40줄)를 본다.
AREA_HINTS = {
    "system-menu": ("openSystemMenu",),
    "gamelist-columns": ("GameList Columns", "renderColumns"),
    "paste-mode": ("PASTE_MODES", "pasteModeToggle"),
    "add-collection": ("openAddCollection", "add-collection"),
    "mtp": ("mtpBrowser", "openMtpPicker", "MTP"),
    "archive": ("isArchive", "archiveSend", "Archive"),
    "title-affix": ("titleAffix", "openTitleAffixDialog"),
}

FILES = ["app.js", "scraper-ui.js", "transfer-ui.js", "archive-settings-ui.js", "collection-setup-ui.js", "settings.js", "dashboard.js"]


def _extract_json_object(src: str, marker: str) -> dict:
    start = src.index(marker) + len(marker)
    depth, obj_start = 0, None
    for i in range(start, len(src)):
        ch = src[i]
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(src[obj_start:i + 1])
    raise AssertionError(f"{marker!r} 뒤에서 객체 리터럴을 찾지 못함")


def load_table() -> dict:
    data = _extract_json_object(DATA_JS.read_text(encoding="utf-8"), "window.RMS_I18N_TABLE = ")
    extra = _extract_json_object(EXTRA_JS.read_text(encoding="utf-8"), "i18n.addTable(")
    return {**data, **extra}


def strip_comments(src: str) -> str:
    # 블록 주석은 통째로 지우면 그 안의 줄바꿈까지 사라져 이후 모든 줄 번호가
    # 밀린다 - 내용만 지우고 줄바꿈 개수는 그대로 남긴다.
    def _blank_block(m):
        return "\n" * m.group(0).count("\n")
    without_blocks = re.sub(r"/\*[\s\S]*?\*/", _blank_block, src)
    return re.sub(r"//.*$", "", without_blocks, flags=re.M)


def literals_with_korean(src: str):
    """(원본 조각, 그 조각이 시작하는 줄 번호)의 목록. 백틱은 보간을 자르고 남은
    부분을 공백으로 이어 붙인다."""
    out = []
    for m in _STRING_RE.finditer(src):
        raw = m.group(1) or m.group(2) or m.group(3) or ""
        if m.group(3) is not None:  # backtick
            raw = _INTERP_RE.sub(" ", raw)
        raw = raw.strip()
        if raw and HANGUL_RE.search(raw):
            line = src.count("\n", 0, m.start()) + 1
            out.append((raw, line))
    return out


def report(area: str | None, ignore: set[str]):
    table = load_table()
    files = FILES if not area else [f for f in FILES]  # area는 줄 범위로 좁힌다(아래)
    hints = AREA_HINTS.get(area) if area else None

    total_missing = 0
    for name in files:
        path = GUI / name
        src = strip_comments(path.read_text(encoding="utf-8"))
        lines = src.splitlines()
        ranges = None
        if hints:
            ranges = []
            for i, line in enumerate(lines, start=1):
                if any(h in line for h in hints):
                    ranges.append((max(1, i - 40), i + 40))
            if not ranges:
                continue

        missing = {}
        for text, line in literals_with_korean(src):
            if ranges and not any(a <= line <= b for a, b in ranges):
                continue
            if text in ignore or text in table:
                continue
            missing.setdefault(text, []).append(line)

        if missing:
            print(f"\n== {name} ({'전체' if not area else area}) - 번역표에 없는 문구 {len(missing)}개 ==")
            for text, lns in sorted(missing.items(), key=lambda kv: kv[1][0]):
                total_missing += 1
                print(f"  L{lns[0]:<6} {text!r}")
    if total_missing == 0:
        print("걸린 것 없음(사용자 데이터/오탐 제외 후 남는 게 없을 수도 있다 - --ignore로 오탐을 뺐는지 확인).")
    else:
        print(f"\n총 {total_missing}건 - 사용자 데이터/오탐은 --ignore로 제외하고 다시 보면 실제 공백만 남는다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", choices=sorted(AREA_HINTS), help="PART 17이 지목한 영역만 본다")
    parser.add_argument("--list-areas", action="store_true")
    parser.add_argument("--ignore", nargs="*", default=[], help="이미 확인한 오탐(사용자 데이터 등) 문자열")
    args = parser.parse_args()
    if args.list_areas:
        for name, hints in AREA_HINTS.items():
            print(f"{name}: {', '.join(hints)}")
        return
    report(args.area, set(args.ignore))


if __name__ == "__main__":
    main()
