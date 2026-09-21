"""
app/title_affix.py
====================
Title Prefix/Postfix - 지역별로 제목 앞뒤에 표시를 자동으로 붙이거나 뗀다(사용자 결정).

이 기능을 실행하면 순서대로:

1. **기존 장식을 먼저 뗀다.** 이 기능으로든 사람이 손으로든 제목 양 끝에 붙어 있던
   장식(괄호로 감싼 덩어리, `KR_`/`_KR`처럼 구분자로 붙은 덩어리)을 지운다. 그래야 이미
   `[KR]`가 붙어 있는 제목에 또 `[KR]`를 덧붙이는 일이 없다.
2. **디스크 표시는 따로 인식해서 보존한다.** `(Disk 1 of 3)`, `(Disc 2)`처럼 여러 장으로
   나뉜 게임의 디스크 번호는 지역 장식이 아니다 - 1번에서 함께 지워지지 않도록 먼저
   빼내 기억해 두고, 새 제목을 만들 때 정해진 자리(제목 바로 뒤)에 다시 넣는다.
3. **파일명에 붙은 지역 태그로 분류하고, 설정에 따라 새 장식을 붙인다.** `(KR)`,
   `[Kor]`, `_k`, `(USA)`, `global`처럼 ROM 파일명에 접두/접미로 붙은 표시를 읽는다
   (사용자 결정). gamelist의 `region` 필드가 아니다 - 그 필드는 비어 있는 Collection이
   흔해서 기준으로 쓸 수 없다. 태그가 없으면 **미분류**이고, 미분류는 아무것도 하지
   않는다 - 장식을 떼지도, 붙이지도 않는다(자동 적용 대상에서 제외).

실제 파일에 쓰는 것은 이 모듈의 일이 아니다. 여기서는 문자열만 계산하고, 저장은
`app/plan/builder.py`(Plan에 올리기)와 `app/plan/applier.py`(Apply 때 실제로 쓰기)가 한다 -
이 기능은 Plan을 거친다(사용자 결정 - 되돌릴 수 있어야 하는 일괄 작업이라 즉시쓰기(D1)의
예외로 둔다).
"""

from __future__ import annotations

import re

#: 5개 구역. 순서가 Settings 화면에 보여줄 순서이기도 하다.
REGIONS = ("kr", "en", "jp", "eu", "global")

REGION_LABELS = {
    "kr": "한국(KR)", "en": "영어권(EN)", "jp": "일본(JP)", "eu": "유럽(EU)", "global": "글로벌",
}

#: 파일명의 지역 태그에서 자주 보는 표기 -> 5개 구역. No-Intro/GoodTools의 한 글자
#: 표기((K), (U), (J), (E), (W))부터 풀네임까지 받는다. 앞에 있는 구역이 우선한다.
_REGION_KEYWORDS: dict[str, set[str]] = {
    "kr": {"k", "kr", "kor", "korea", "korean"},
    "en": {"u", "us", "usa", "na", "en", "eng", "english", "america"},
    "jp": {"j", "jp", "jpn", "jap", "japan"},
    "eu": {"e", "eu", "eur", "europe", "pal", "uk", "gb"},
    "global": {"w", "world", "global", "int", "intl", "international"},
}

#: 괄호/대괄호로 감싼 덩어리 - 안에 무엇이 들어 있든 일단 잡고, 아래에서 **전부 지역 표기일 때만** 인정한다.
_GROUP_RE = re.compile(r"[\(\[]\s*([^()\[\]]{1,40}?)\s*[\)\]]")
#: 한 괄호 안의 여러 지역을 가르는 구분 - `(Japan, Europe)`, `(USA/Europe)`, `(Japan & USA)`.
_GROUP_SPLIT_RE = re.compile(r"\s*(?:,|/|\+|&|\band\b)\s*", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z]{1,12}")
#: 구분자로 붙인 태그 - `Game_k`, `Game-kr`, `global_Game`. **공백은 구분자로 치지
#: 않는다** - 공백까지 받으면 제목 속 평범한 단어("Global Defense"의 Global)가 걸린다.
_TAG_DELIMITED_RE = re.compile(r"(?:^|[_\-])([A-Za-z]{1,12})(?=[_\-]|$)")

_ALL_KEYWORDS = set().union(*_REGION_KEYWORDS.values())


def _region_tokens(stem: str) -> set[str]:
    tokens: set[str] = set()
    for group in _GROUP_RE.findall(stem):
        parts = [p for p in _GROUP_SPLIT_RE.split(group) if p]
        if not parts or not all(_WORD_RE.fullmatch(p) for p in parts):
            continue                        # (Disc 1), (2/2), (Rev A) 같은 것은 지역 표기가 아니다
        lowered = [p.lower() for p in parts]
        # **여럿이 들어 있으면 전부 지역 표기일 때만** 인정한다. `(En,Fr,De)`는 언어 목록이라
        # En 하나만 걸려 영어권으로 분류되면 안 된다. 하나뿐이면 예전처럼 걸리는 것만 본다.
        if len(lowered) > 1 and not all(t in _ALL_KEYWORDS for t in lowered):
            continue
        tokens.update(lowered)
    tokens.update(t.lower() for t in _TAG_DELIMITED_RE.findall(stem))
    return tokens


def classify_regions(filename: str | None) -> list[str]:
    """**파일명**에 붙은 지역 태그로 해당하는 구역을 **모두** 돌려준다(REGIONS 순서).

    `Game (Japan, Europe).zip`은 일본과 유럽 둘 다다 - 예전에는 괄호 안에 쉼표가 있으면 통째로
    무시해서 미분류가 됐다(실사용 질문 - "롬이름에 (Japan, Europe)은 어떻게 적용되나?").
    """
    stem = str(filename or "")
    stem = stem[:stem.rfind(".")] if "." in stem else stem
    tokens = _region_tokens(stem)
    return [bucket for bucket in REGIONS if tokens & _REGION_KEYWORDS[bucket]]


def classify_region(filename: str | None) -> str | None:
    """대표 구역 하나(여럿이면 앞선 것). 태그가 없으면 **None(미분류)** - 미분류는 자동 적용
    대상에서 통째로 빠진다. 여러 구역을 다루려면 `classify_regions()`를 쓴다."""
    found = classify_regions(filename)
    return found[0] if found else None


# ----------------------------------------------------------------------
# 디스크 표시 - "(Disk 1 of 3)", "(Disc 2)", "(2/2)"처럼 여러 장으로 나뉜 게임의 디스크
# 번호는 지역 장식이 아니라 따로 인식해서 보존한다.
# ----------------------------------------------------------------------
#: "Disk"/"Disc" 단어가 있는 표기 - 단어가 있으니 총 장수 없이 번호 하나만 있어도
#: ("Disc A") 디스크 표시로 인정한다.
_DISK_WORD_RE = re.compile(
    r"[\(\[]\s*(dis[ck])\s*\.?\s*([0-9]+|[a-z])\s*(?:(?:of|/)\s*([0-9]+|[a-z]))?\s*[\)\]]",
    re.IGNORECASE,
)
#: 단어 없이 숫자만 있는 표기("(2/2)", "(1 of 3)") - **번호와 총 장수가 둘 다 있을 때만**
#: 인정한다. 총 장수 없이 숫자 하나만 있으면("(1994)") 발매연도 같은 것과 구별할 수
#: 없어서 디스크 표시로 보지 않는다 - 실사용 피드백: 단어 없는 "(2/2)"가 지역 장식과
#: 함께 지워졌다.
_DISK_FRACTION_RE = re.compile(r"[\(\[]\s*([0-9]{1,2})\s*(?:of|/)\s*([0-9]{1,2})\s*[\)\]]")


def _extract_disk_marker(title: str) -> tuple[str, str | None]:
    """디스크 표시를 찾아 빼내고 (나머지 제목, 정규화한 표시)를 돌려준다.

    여러 개가 있으면 첫 번째만 인정한다 - 정상적인 제목에 디스크 표시는 하나뿐이다.
    표기는 "Disk"/"Disc", 숫자/로마자, 단어 없는 분수 등 제각각이라 **단어가 있으면
    그 단어(Disk 또는 Disc)를 살리고, 없으면 "Disk"로 통일**하며 나머지 모양만
    맞춘다(`(Disk 1 of 3)`, `(Disc A)`).
    """
    m = _DISK_WORD_RE.search(title)
    if m:
        word, num, total = m.group(1).capitalize(), m.group(2).upper(), m.group(3)
    else:
        m = _DISK_FRACTION_RE.search(title)
        if not m:
            return title, None
        word, num, total = "Disk", m.group(1), m.group(2)
    marker = f"({word} {num}{f' of {total.upper()}' if total else ''})"
    remaining = (title[:m.start()] + " " + title[m.end():]).strip()
    return remaining, marker


# ----------------------------------------------------------------------
# 기존 장식 떼기 - 양 끝에서 괄호 덩어리나 구분자로 붙은 덩어리를 반복해서 벗겨낸다.
# ----------------------------------------------------------------------
#: 대괄호 바로 앞뒤의 구분자([\s_\-])도 함께 삼킨다 - "_[KR]_"처럼 겹친 장식이 한
#: 번의 겹수 안에서도 통째로 떨어지게(테스트: 겹쳐 쌓인 장식도 전부 지워진다).
_HEAD_BRACKET = re.compile(r"^[\s_\-]*[\(\[\{][^()\[\]{}]*[\)\]\}][\s_\-]*")
_TAIL_BRACKET = re.compile(r"[\s_\-]*[\(\[\{][^()\[\]{}]*[\)\]\}][\s_\-]*$")
#: "KR_제목"처럼 문자/숫자 덩어리 뒤에 구분자(_ 또는 -)가 바로 붙어 있는 머리.
_HEAD_TOKEN = re.compile(r"^\s*[A-Za-z0-9]+[_\-]+\s*")
#: "제목_KR"처럼 구분자 뒤에 문자/숫자 덩어리가 붙어 있는 꼬리.
_TAIL_TOKEN = re.compile(r"\s*[_\-]+[A-Za-z0-9]+\s*$")

#: 한 번 실행에서 벗겨낼 최대 겹수. 정상적인 제목이 이보다 많이 겹쳐 있을 리 없고,
#: 이 값이 없으면 병적인 입력에서 무한히 벗겨내려 들 수 있다.
_MAX_STRIP_LAYERS = 6


def _strip_edge_affixes(title: str) -> str:
    """양 끝의 장식을 반복해서 뗀다. **전부 벗겨서 빈 문자열이 되는 것은 막는다** -
    제목 전체가 괄호 하나뿐인 것처럼 보여도 실제로는 그것이 유일한 내용일 수 있다."""
    text = title.strip()
    for _ in range(_MAX_STRIP_LAYERS):
        stripped = text
        for pattern in (_HEAD_BRACKET, _TAIL_BRACKET, _HEAD_TOKEN, _TAIL_TOKEN):
            candidate = pattern.sub("", stripped, count=1).strip()
            if candidate:
                stripped = candidate
        if stripped == text:
            break
        text = stripped
    return text or title.strip()


def strip_existing_title_affix(title: str) -> tuple[str, str | None]:
    """제목에서 기존 장식을 걷어낸다. 디스크 표시는 먼저 빼서 보존한다.

    반환: (장식을 뗀 바탕 제목, 디스크 표시 또는 None)
    """
    without_disk, disk_marker = _extract_disk_marker(title or "")
    base = _strip_edge_affixes(without_disk)
    return base, disk_marker


# ----------------------------------------------------------------------
# 새 장식 붙이기 - 구분되어 있지 않은 텍스트에만 언더바를 끼운다(사용자 결정).
# ----------------------------------------------------------------------
#: 이 문자로 끝나거나(prefix) 시작하면(postfix) 이미 "구분되어 있다"고 본다.
_DELIM_CHARS = set("_-.~()[]{}")


def _join_prefix(text: str, title: str) -> str:
    """`text` 앞뒤 공백은 지우지 않는다 - 예전엔 `strip()`으로 지웠는데, 그러면
    사용자가 `" (KR)"`처럼 일부러 넣은 공백까지 사라져 `"Title(KR)"`처럼 붙어버렸다
    (실사용 피드백: "띄어쓰기를 넣고 싶어도 적용이 안된다"). 자동 구분자(`_`)는
    `text`가 이미 구분자나 공백으로 끝날 때만 생략한다 - 그래야 사용자가 직접 넣은
    공백이 곧 구분자 역할을 한다.
    """
    if not text.strip():
        return title
    sep = "" if (text[-1] in _DELIM_CHARS or text[-1].isspace()) else "_"
    return f"{text}{sep}{title}"


def _join_postfix(title: str, text: str) -> str:
    if not text.strip():
        return title
    sep = "" if (text[0] in _DELIM_CHARS or text[0].isspace()) else "_"
    return f"{title}{sep}{text}"


#: Settings 기본값. bridge가 이 모양 그대로 저장/병합한다.
DEFAULT_CONFIG: dict[str, dict] = {
    "kr": {"enabled": False, "mode": "prefix", "text": "KR"},
    "en": {"enabled": False, "mode": "prefix", "text": "EN"},
    "jp": {"enabled": False, "mode": "prefix", "text": "JP"},
    "eu": {"enabled": False, "mode": "prefix", "text": "EU"},
    "global": {"enabled": False, "mode": "prefix", "text": "WORLD"},
}


def normalize_config(config: dict | None) -> dict:
    """저장된/받은 설정을 5개 구역 모두 채운 모양으로 맞춘다. 잘못된 값은 기본값으로."""
    config = config or {}
    out = {}
    for bucket in REGIONS:
        defaults = DEFAULT_CONFIG[bucket]
        given = config.get(bucket) or {}
        mode = given.get("mode") if given.get("mode") in ("prefix", "postfix") else defaults["mode"]
        out[bucket] = {
            "enabled": bool(given.get("enabled", defaults["enabled"])),
            "mode": mode,
            "text": str(given.get("text", defaults["text"]) or ""),
        }
    return out


_WRAPPED_RE = re.compile(r"^(\s*)([\(\[\{])(.*)([\)\]\}])(\s*)$")


def _merge_texts(texts: list[str]) -> str:
    """여러 지역의 장식 문구를 하나로 합친다.

    모두 **같은 괄호**로 감싼 `[JP]` `[EU]`면 `[JP,EU]`로 하나로 묶는다(사용자 질문 - "[Jp][Eu]로
    따로 넣었으면 [Jp,Eu]도 가능?"). 괄호가 다르거나 없으면(`JP_`, `EU_`) 이어 붙인다."""
    if len(texts) == 1:
        return texts[0]
    wrapped = [_WRAPPED_RE.match(t) for t in texts]
    if all(wrapped) and len({(m.group(2), m.group(4)) for m in wrapped}) == 1:
        first, last = wrapped[0], wrapped[-1]
        inner = ",".join(m.group(3).strip() for m in wrapped)
        return f"{first.group(1)}{first.group(2)}{inner}{last.group(4)}{last.group(5)}"
    return "".join(texts)


def compute_new_title(current_title: str, filename: str | None, config: dict | None) -> dict:
    """이 게임에 실제로 적용될 새 제목을 계산한다. 구역은 **파일명**으로 정한다.

    파일명에 지역이 여럿이면(`(Japan, Europe)`) 켜져 있는 구역의 문구를 모두 붙인다 - 같은
    괄호면 `[JP,EU]`로 합치고 아니면 이어 붙인다.

    반환: {"oldTitle", "newTitle", "changed", "regionBucket", "regionBuckets", "diskMarker"}
    """
    current_title = current_title or ""
    buckets = classify_regions(filename)
    if not buckets:
        # 미분류 - 장식을 떼지도, 붙이지도 않는다(사용자 결정: 자동 적용 대상에서 제외).
        return {"oldTitle": current_title, "newTitle": current_title, "changed": False,
                "regionBucket": None, "regionBuckets": [], "diskMarker": None}

    base, disk_marker = strip_existing_title_affix(current_title)
    core = f"{base} {disk_marker}" if disk_marker else base

    config = normalize_config(config)
    active = [config[b] for b in buckets if config[b]["enabled"] and config[b]["text"].strip()]
    prefixes = [c["text"] for c in active if c["mode"] != "postfix"]
    postfixes = [c["text"] for c in active if c["mode"] == "postfix"]
    new_title = core
    if postfixes:
        new_title = _join_postfix(new_title, _merge_texts(postfixes))
    if prefixes:
        new_title = _join_prefix(_merge_texts(prefixes), new_title)

    return {"oldTitle": current_title, "newTitle": new_title, "changed": new_title != current_title,
            "regionBucket": buckets[0], "regionBuckets": buckets, "diskMarker": disk_marker}


def preview_titles(rows: list[dict], config: dict | None) -> list[dict]:
    """여러 게임에 대해 한 번에 계산한다(미리보기 화면과 Plan에 올리기가 함께 쓴다).

    `rows`는 각 게임의 `{"rom_uid", "system", "filename", "title"}` - Cache의
    `get_row()`/`query_rows()`가 그대로 주는 모양(snake_case)과 맞춘다 - 호출부(bridge)가
    다시 이름을 바꿔 넘길 필요가 없게 하기 위해서다.
    """
    config = normalize_config(config)
    out = []
    for row in rows:
        result = compute_new_title(row.get("title") or "", row.get("filename"), config)
        out.append({"romUid": row["rom_uid"], "system": row["system"], "filename": row["filename"], **result})
    return out
