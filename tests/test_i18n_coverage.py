"""tests/test_i18n_coverage.py
===============================
번역표(`gui_web/i18n-data.js` + `i18n-extra.js`) 자체의 무결성을 검사한다 -
tests/test_wiring.py가 app.js<->api-client.js<->bridge/api.py 체인의 이름을
정적으로 맞춰 보는 것과 같은 자리에 있는 검사다.

**여기서 보는 것과 보지 않는 것을 분명히 가른다.**

번역표 안에서 "이 키는 언어마다 값이 다 있는가/비어 있지 않은가/중복은
없는가"는 규칙이 명확해서 자동으로 맞고 틀림을 가릴 수 있다 - 그래서 실패하면
반드시 고쳐야 하는 테스트로 만든다.

반면 "소스 코드의 어떤 한글 문자열이 아직 번역표에 없는가"는 값을 정확히
가릴 수 없다. 그 문자열이 사용자 데이터(게임 제목, 파일명)인지 UI 문구인지,
런타임에 조합되는 동적 문자열(백틱 템플릿의 `${...}` 보간)인지를 정적 분석만으로
완벽히 구분할 수 없어서 오탐이 필연적이다 - 그래서 이건 실패하는 테스트가 아니라
`tools/i18n_coverage.py`가 만드는 참고용 리포트로 남긴다(PART 21/22의 "자동
검사"는 이 리포트로 충족한다 - 검사 결과를 사람이 보고 우선순위를 매기는 것과
"빌드를 막는 통과/실패"는 다른 도구다).
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_JS = ROOT / "gui_web" / "i18n-data.js"
EXTRA_JS = ROOT / "gui_web" / "i18n-extra.js"

#: i18n.js가 실제로 표시할 수 있는 언어(한국어 제외 - 원문 자체가 한국어라 번역표가 필요 없다).
LANGS = ("en", "ja", "es", "fr")


def _extract_json_object(src: str, marker: str) -> dict:
    """`<marker>{ ... }` 모양에서 객체 리터럴만 뽑아 JSON으로 읽는다.

    두 파일 다 `json.dumps(..., ensure_ascii=...)`로 만들어져 순수 JSON이므로,
    중괄호 균형만 맞추면 `json.loads`가 그대로 읽는다(값 안에 리터럴 `{`/`}`가
    없다 - 전부 사람이 쓴 문장이다).
    """
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
    raise AssertionError(f"{marker!r} 뒤에서 짝 맞는 객체 리터럴을 찾지 못했다 - 파일 구조가 바뀌었을 수 있다")


def load_tables() -> tuple[dict, dict]:
    data = _extract_json_object(DATA_JS.read_text(encoding="utf-8"), "window.RMS_I18N_TABLE = ")
    extra = _extract_json_object(EXTRA_JS.read_text(encoding="utf-8"), "i18n.addTable(")
    return data, extra


def _has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


class TranslationTableIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.data, self.extra = load_tables()

    def test_parser_actually_found_entries(self):
        """정규식/파서가 파일 구조 변화로 0개를 뽑고도 '통과'하는 사고를 막는다."""
        self.assertGreater(len(self.data), 100)
        self.assertGreater(len(self.extra), 50)

    def test_no_key_is_duplicated_across_the_two_tables(self):
        """같은 원문이 두 파일에 다 있으면 `i18n.addTable()`이 나중 것(extra)으로
        조용히 덮어쓴다 - 데이터 쪽 항목은 죽은 코드가 되고, 유지보수하다 둘 중
        하나만 고치면 언젠가 다시 어긋난다(PART 21 - Duplicate key)."""
        dup = sorted(set(self.data) & set(self.extra))
        self.assertEqual(dup, [], f"i18n-data.js와 i18n-extra.js에 같은 키가 있다: {dup}")

    def test_every_korean_keyed_entry_has_every_language_non_empty(self):
        """**원문이 한글인 키만** 본다. 원문이 이미 영단어인 키(예: "Settings",
        "System")는 en 번역이 없는 게 정상이다 - 원문 자체가 영문 표시값이기
        때문이다(PART 19 - 실제 데이터와 UI 문자열을 구분한다의 반대쪽 사례:
        UI 문구인데 원문이 영문인 경우)."""
        missing = []
        for name, table in (("i18n-data.js", self.data), ("i18n-extra.js", self.extra)):
            for key, value in table.items():
                if not _has_hangul(key):
                    continue
                for lang in LANGS:
                    text = str(value.get(lang, "")).strip()
                    if not text:
                        missing.append(f"{name}::{key!r}::{lang}")
        self.assertEqual(missing, [], "언어별 번역이 비어 있거나 없는 항목:\n" + "\n".join(missing))

    def test_no_language_value_equals_the_untranslated_korean_source(self):
        """번역값이 원문(한글)을 그대로 복사해 붙인 것이면 번역이 아니라 자리만 채운
        것이다 - 조용히 '완료'로 보이는 것을 막는다."""
        copies = []
        for name, table in (("i18n-data.js", self.data), ("i18n-extra.js", self.extra)):
            for key, value in table.items():
                if not _has_hangul(key):
                    continue
                for lang in LANGS:
                    if str(value.get(lang, "")).strip() == key.strip():
                        copies.append(f"{name}::{key!r}::{lang}")
        self.assertEqual(copies, [], "원문을 그대로 복사한 번역값:\n" + "\n".join(copies))


if __name__ == "__main__":
    unittest.main()
