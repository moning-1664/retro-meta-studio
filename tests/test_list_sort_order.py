"""목록 정렬 - 실사용 피드백 두 건.

    1. Title 정렬이 `title_norm`(§3.1의 "같은 메타데이터인가" 판정용, 대괄호/태그를
       지운 값)을 재사용해서, 대괄호만 다른 두 제목이 정렬에서 구별되지 않았다.
    2. Description 정렬에서 값이 없는 항목(빈 문자열)이 정렬 방향과 무관하게 위로
       몰려 파일명 순서로 섞여 나왔다 - "정렬 기준이 뭔지 모르겠다"는 인상을 줬다.

이 파일은 `app/store/cache.CacheStore`를 직접 다뤄 ES-DE 트리를 거치지 않는다 -
정렬은 SQL 문제이지 어댑터 문제가 아니다.
"""

import unittest
from pathlib import Path

from app.store.cache import CacheStore
from tests.fixtures import temp_root


def _row(filename, title, *, size=1024, desc=None):
    return {
        "filename": filename, "rel_path": filename, "title": title,
        "title_norm": title.lower(), "size": size, "has_metadata": desc is not None,
        "has_media": False, "present": True,
        "fields": ({"desc": desc} if desc is not None else {}),
    }


class TitleSortIncludesBracketsTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_sort_title_")
        self.cache = CacheStore(self.dir / "cache.db")
        self.addCleanup(self.cache.close)

    def files(self, **kw):
        return [r["filename"] for r in self.cache.query_rows(order="title", **kw)]

    def test_bracket_tags_participate_in_the_sort(self):
        """§3.1의 title_norm은 두 항목을 전부 "ff3"로 뭉갠다 - 화면 정렬은 그러면 안 된다."""
        self.cache.replace_system("snes", [
            _row("b.zip", "FF3 [Rev B]"),
            _row("a.zip", "FF3 [Rev A]"),
        ])
        # title_norm 기준이었다면 둘 다 "ff3"로 동률이라 filename(a, b)으로 갈렸을 것이다.
        # 대괄호가 정렬에 들어가면 "Rev A" < "Rev B" 순서가 title만으로 결정된다.
        self.assertEqual(self.files(), ["a.zip", "b.zip"])

    def test_still_case_insensitive(self):
        self.cache.replace_system("snes", [_row("b.zip", "banana"), _row("a.zip", "Apple")])
        self.assertEqual(self.files(), ["a.zip", "b.zip"])

    def test_descending_reverses_it(self):
        self.cache.replace_system("snes", [_row("a.zip", "Apple [USA]"), _row("b.zip", "Banana [USA]")])
        self.assertEqual(self.files(descending=True), ["b.zip", "a.zip"])


class DescriptionSortPutsEmptyLastTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_sort_desc_")
        self.cache = CacheStore(self.dir / "cache.db")
        self.addCleanup(self.cache.close)

    def files(self, **kw):
        return [r["filename"] for r in self.cache.query_rows(order="desc", **kw)]

    def test_items_without_a_description_sort_to_the_end_ascending(self):
        self.cache.replace_system("snes", [
            _row("no_desc_1.zip", "가나다"),          # desc 없음 - filename만 다르면 뒤섞여 보이던 원인
            _row("english.zip", "Zelda", desc="A description"),
            _row("no_desc_2.zip", "Apple"),          # desc 없음
            _row("korean.zip", "게임", desc="한글 설명입니다"),
        ])
        # 설명이 있는 두 항목이 먼저(영문 -> 한글, 코드포인트 순), 없는 두 항목은 맨 뒤.
        self.assertEqual(self.files(), ["english.zip", "korean.zip", "no_desc_1.zip", "no_desc_2.zip"])

    def test_items_without_a_description_stay_last_even_when_descending(self):
        """방향을 뒤집어도 "값 없음"이 앞으로 튀어나오면 안 된다(빈 값은 순서에 대해
        아무 의견도 없다는 뜻이라, 내림차순이라고 맨 앞으로 오는 것은 이상하다)."""
        self.cache.replace_system("snes", [
            _row("no_desc.zip", "Apple"),
            _row("has_desc.zip", "Banana", desc="Some text"),
        ])
        self.assertEqual(self.files(descending=True), ["has_desc.zip", "no_desc.zip"])

    def test_ties_within_the_empty_group_fall_back_to_filename(self):
        self.cache.replace_system("snes", [_row("z.zip", "Z"), _row("a.zip", "A")])
        self.assertEqual(self.files(), ["a.zip", "z.zip"])

    def test_korean_and_latin_description_priorities_keep_empty_last(self):
        self.cache.replace_system("snes", [
            _row("empty.zip", "Empty"),
            _row("japanese.zip", "Japanese", desc="日本語の説明です"),
            _row("english.zip", "English", desc="An English description"),
            _row("korean.zip", "Korean", desc="한글 설명입니다"),
        ])
        korean = self.files(priority="desc_ko")
        english = self.files(priority="desc_en")
        self.assertEqual(korean, ["korean.zip", "english.zip", "japanese.zip", "empty.zip"])
        self.assertEqual(english, ["english.zip", "korean.zip", "japanese.zip", "empty.zip"])
        self.assertEqual(self.files(priority="desc_ko", descending=True)[0], "korean.zip")
        for priority, expected in (("desc_ko", korean), ("desc_en", english)):
            uids = self.cache.query_uids(priority=priority)
            rows = self.cache.query_rows(priority=priority)
            self.assertEqual(uids, [row["rom_uid"] for row in rows])
            self.assertEqual(self.cache.index_of_prefix("k", priority=priority),
                             expected.index("korean.zip"))


if __name__ == "__main__":
    unittest.main()
