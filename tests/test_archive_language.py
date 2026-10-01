"""Archive -> Collection에서 언어 태그만 다른 파일명을 같은 게임으로 잇는다."""

import unittest

from app import title_affix
from app.archive.service import _language_matches


def _index(*names, system="snes"):
    return {(system, n): {"filename": n} for n in names}


class LanguageBaseTests(unittest.TestCase):
    def test_only_recognized_language_tags_are_removed(self):
        base = title_affix.language_base
        self.assertEqual(base("FF3.zip"), "ff3")
        self.assertEqual(base("FF3(KR).zip"), "ff3")
        self.assertEqual(base("FF3 (Japan, Europe).zip"), "ff3")
        # 언어 태그가 아닌 괄호는 그대로 - 다른 디스크/리비전을 하나로 뭉치지 않는다.
        self.assertNotEqual(base("Game (Disc 1).zip"), base("Game (Disc 2).zip"))
        self.assertNotEqual(base("Game (Rev A).zip"), base("Game.zip"))


class LanguageMatchTests(unittest.TestCase):
    def test_exact_filename_wins_over_language_variants(self):
        rows = _language_matches(_index("FF3.zip", "FF3(KR).zip"), "snes", "FF3.zip")
        self.assertEqual([r["filename"] for r in rows], ["FF3.zip"])

    def test_untagged_archive_file_finds_the_tagged_target(self):
        rows = _language_matches(_index("FF3(KR).zip"), "snes", "FF3.zip")
        self.assertEqual(rows, [])

    def test_tagged_archive_file_finds_the_untagged_target(self):
        rows = _language_matches(_index("FF3.zip"), "snes", "FF3(KR).zip")
        self.assertEqual(rows, [])

    def test_every_language_variant_gets_the_metadata(self):
        rows = _language_matches(_index("FF3(KR).zip", "FF3(JP).zip"), "snes", "FF3.zip")
        self.assertEqual(rows, [])

    def test_different_tags_on_both_sides_are_not_the_same_game(self):
        self.assertEqual(_language_matches(_index("FF3(JP).zip"), "snes", "FF3(KR).zip"), [])

    def test_other_system_or_title_does_not_match(self):
        self.assertEqual(_language_matches(_index("FF3(KR).zip", system="nes"), "snes", "FF3.zip"), [])
        self.assertEqual(_language_matches(_index("FF4(KR).zip"), "snes", "FF3.zip"), [])


if __name__ == "__main__":
    unittest.main()
