"""
app/gameid.py
==============
**"이 둘은 같은 게임인가"를 판단하는 단 하나의 자리.**

예전에는 같은 질문을 세 곳이 각자 다르게 답했다 - Compare는 `normalize_title()`,
Archive 수집은 `rom_key_of()`, 붙여넣기는 파일명 완전 일치. 그래서 Compare에서는
한 줄로 짝지어 "메타데이터가 다르다"고 보여주는 항목을, 정작 붙여넣기는 찾지도
못했다(실사용 버그). 판단 규칙은 여기 한 곳에만 둔다.

규칙(사용자 결정)
-----------------
1. **ROM 파일의 존재 여부는 판단에 쓰지 않는다.** 파일명만 본다.
2. 디스크 표기(`(Disc 1)`, `(Disk 1 of 3)`, `(1/3)`)는 **같은 게임**이다. 다만 번호는
   따로 들고 있다가 짝지을 때 쓴다 - 1번 디스크의 메타데이터가 2번 디스크를 덮으면 안 된다.
3. 괄호/대괄호로 묶인 보조정보(지역, 언어, 리비전, 덤프 표시)는 뺀다.
4. `_ - : ;` 같은 구분자는 공백과 같게 본다.
5. 부제는 **한쪽에만 있을 때만** 비교에서 뺀다. 양쪽 다 있으면 부제까지 같아야 한다.
   (`Metal Gear 2 - Solid Snake` == `Metal Gear 2`, 그러나
    `Contra: Hard Corps` != `Contra: Legacy of War`)
6. 편수가 없으면 1편으로 본다(`Metal Gear` == `Metal Gear 1`).
7. **로마자는 숫자로 바꾸지 않는다**(사용자 결정, 번복). 실제 라이브러리에서 맞게
   변환되는 것(`Final Fantasy X` -> 10)보다 틀리게 변환되는 것(`Rockman X`,
   `Rally X`, `Spartan X`, `Guilty Gear X`, `Ace Combat X`...)이 훨씬 많았다 -
   `X`는 로마자 10보다 글자 그대로 쓰이는 제목이 많다. 대신 **로마자로 끝나면 편수가
   이미 있는 것으로 본다** - 안 그러면 `Final Fantasy II`가 `final fantasy ii 1`이 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


#: 디스크 표기. `Disc/Disk` 다음에 번호(숫자 또는 한 글자)가 오는 형태와, 단어 없이
#: `1 of 3` / `1/3`처럼 번호와 총 장수가 함께 오는 형태를 받는다.
#:
#: 단어 경계를 요구하므로 `(Userdisk)`처럼 `disk`가 다른 낱말에 붙은 것은 걸리지 않는다
#: (실제 라이브러리에 `Ancient Ys ... (Userdisk).dsk`가 있다 - 이건 디스크 번호가 아니다).
_DISC_WORD_RE = re.compile(
    r"[\(\[]?\s*\b(?:dis[ck])\s*\.?\s*([0-9]+|[a-z])\b"
    r"(?:\s*(?:of|/)\s*([0-9]+|[a-z]))?\s*[\)\]]?",
    re.IGNORECASE)
#: 단어 없이 번호만 있는 형태. **총 장수가 반드시 있어야** 한다 - 없으면 `(1994)` 같은
#: 발매연도와 구별할 수 없다.
_DISC_FRACTION_RE = re.compile(r"[\(\[]\s*([0-9]{1,2})\s*(?:of|/)\s*([0-9]{1,2})\s*[\)\]]")

#: 남은 괄호/대괄호 덩어리 - 지역(USA), 언어[K], 리비전(Rev A), 덤프 표시[b] 등.
_BRACKET_RE = re.compile(r"[\(\[][^\)\]]*[\)\]]")
#: 구분자. 공백과 같게 본다.
_SEPARATOR_RE = re.compile(r"[_\-:;~]+")
_SPACE_RE = re.compile(r"\s+")
#: 부제 경계. **띄어 쓴** 하이픈이나 콜론만 부제로 본다 - 낱말에 붙은 하이픈
#: (`Gaiden-The Knight`, `Rockman X2-Soul Eraser`)은 그냥 구분자다.
_SUBTITLE_RE = re.compile(r"\s+[-–]\s+|\s*:\s+|\s*:\s*$")
#: 로마자만으로 이루어진 낱말 - 편수 표기로 본다(숫자로 바꾸지는 않는다).
_ROMAN_RE = re.compile(r"^[ivx]+$", re.IGNORECASE)


@dataclass(frozen=True)
class GameKey:
    """같은 게임인지 판단하기 위해 파일명에서 뽑아낸 것."""

    full: str                 #: 부제까지 포함한 정규화 이름
    base: str                 #: 부제를 뺀 정규화 이름(부제가 없으면 full과 같다)
    has_subtitle: bool
    disc: str | None          #: 디스크 번호("1", "a" 등). 없으면 None
    disc_total: str | None    #: 총 장수. 모르면 None

    @property
    def buckets(self) -> tuple[str, ...]:
        """후보를 좁히는 데 쓸 열쇠들. 둘 중 하나라도 같아야 비교할 가치가 있다."""
        return (self.full,) if self.full == self.base else (self.full, self.base)


def _strip_discs(stem: str) -> tuple[str, str | None, str | None]:
    """디스크 표기를 떼어 내고 (남은 이름, 번호, 총 장수)를 준다."""
    number = total = None

    def take_word(match):
        nonlocal number, total
        if number is None:
            number, total = match.group(1).lower(), (match.group(2) or "").lower() or None
        return " "

    def take_fraction(match):
        nonlocal number, total
        if number is None:
            number, total = match.group(1), match.group(2)
        return " "

    stem = _DISC_WORD_RE.sub(take_word, stem)
    stem = _DISC_FRACTION_RE.sub(take_fraction, stem)
    return stem, number, total


def _tidy(text: str) -> str:
    text = _BRACKET_RE.sub(" ", text)
    text = _SEPARATOR_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip(" .,")
    return text.lower()


def _with_episode(text: str) -> str:
    """편수가 없으면 1편으로 본다. 로마자로 끝나면 이미 편수가 있는 것으로 본다."""
    words = text.split()
    if not words:
        return text
    last = words[-1]
    if last.isdigit() or _ROMAN_RE.match(last):
        return text
    return f"{text} 1"


def _stem(filename: str) -> str:
    """확장자만 떼어 낸다. `Path().stem`을 쓰지 않는 이유는 `Snatcher (1/3).dsk`처럼
    이름 안에 `/`가 있으면 그것을 경로 구분자로 읽어 이름이 잘리기 때문이다."""
    name = filename.rsplit("\\", 1)[-1]
    dot = name.rfind(".")
    # 확장자는 짧다 - `Metal Gear (1987)(Konami)`처럼 점이 없는 이름을 자르지 않는다.
    return name[:dot] if 0 < dot and len(name) - dot <= 6 else name


def key_of(filename: str | None) -> GameKey:
    """파일명 -> GameKey. 확장자는 보지 않는다(`.gba`와 `.zip`은 같은 게임이다)."""
    stem = _stem(str(filename or ""))
    stem, disc, disc_total = _strip_discs(stem)

    # 부제 경계는 **구분자를 정리하기 전에** 찾아야 한다 - `-`를 공백으로 바꾸고 나면
    # 어디까지가 부제였는지 알 수 없다.
    parts = _SUBTITLE_RE.split(stem, maxsplit=1)
    head = parts[0]
    has_subtitle = len(parts) > 1 and bool(_tidy(parts[1]))

    full = _with_episode(_tidy(stem))
    base = _with_episode(_tidy(head)) if has_subtitle else full
    return GameKey(full=full, base=base, has_subtitle=has_subtitle,
                   disc=disc, disc_total=disc_total)


def same_game(a: GameKey, b: GameKey) -> bool:
    """두 파일명이 같은 게임을 가리키는가. 디스크 번호는 보지 않는다(같은 게임이다)."""
    if not a.full or not b.full:
        return False
    if a.full == b.full:
        return True
    # 부제가 한쪽에만 있으면 바탕 이름끼리 본다(사용자 결정).
    if a.has_subtitle != b.has_subtitle and a.base == b.base:
        return True
    return False


def same_disc(a: GameKey, b: GameKey) -> bool:
    """같은 게임 안에서 **같은 장**인가. 둘 다 디스크 번호가 없으면 같은 것으로 본다."""
    return (a.disc or None) == (b.disc or None)


def pick_target(source_filename: str, candidates: list) -> tuple[object | None, str]:
    """같은 게임인 후보가 여럿일 때 어디에 쓸지 고른다(사용자 결정).

    `candidates`: `(filename, payload)`의 목록. 반환: `(payload 또는 None, 어떻게 골랐는지)`.

    고르는 순서 - 앞의 조건으로 하나만 남으면 거기서 끝낸다.

    1. **파일명이 글자까지 같은 것.** 있으면 두말할 것 없다.
    2. **디스크 번호가 같은 것.** 1번 디스크의 메타데이터가 2번 디스크를 덮으면 안 된다.
    3. **지역 태그가 같은 것.** `(JP)` 원본은 `(JP)` 대상으로 간다.
    4. 그래도 여럿이면 **알파벳 순 첫 번째**(사용자 결정 - "없는 경우이니 아무거나").
       임의로 고르는 것이 아니라 **같은 입력에 늘 같은 답**이 나오게 하기 위한 규칙이다.

    후보가 아예 없으면 `(None, "none")`.
    """
    from app import title_affix            # 순환 import를 피해 여기서 부른다

    if not candidates:
        return None, "none"

    exact = [c for c in candidates if c[0] == source_filename]
    if exact:
        return exact[0][1], "exact"

    mine = key_of(source_filename)
    pool = list(candidates)

    by_disc = [c for c in pool if same_disc(mine, key_of(c[0]))]
    if by_disc:
        pool = by_disc
    if len(pool) == 1:
        return pool[0][1], "disc" if by_disc else "single"

    my_regions = set(title_affix.classify_regions(source_filename))
    if my_regions:
        by_region = [c for c in pool if set(title_affix.classify_regions(c[0])) == my_regions]
        if by_region:
            pool = by_region
    if len(pool) == 1:
        return pool[0][1], "region"

    pool.sort(key=lambda c: str(c[0]).casefold())
    return pool[0][1], "first"
