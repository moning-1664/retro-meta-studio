"""Language tag normalization; Archive imports do not use it as identity."""

import unittest

from app import title_affix


class LanguageBaseTests(unittest.TestCase):
    def test_only_recognized_language_tags_are_removed(self):
        base = title_affix.language_base
        self.assertEqual(base("FF3.zip"), "ff3")
        self.assertEqual(base("FF3(KR).zip"), "ff3")
        self.assertEqual(base("FF3 (Japan, Europe).zip"), "ff3")
        # 언어 태그가 아닌 괄호는 그대로 - 다른 디스크/리비전을 하나로 뭉치지 않는다.
        self.assertNotEqual(base("Game (Disc 1).zip"), base("Game (Disc 2).zip"))
        self.assertNotEqual(base("Game (Rev A).zip"), base("Game.zip"))


if __name__ == "__main__":
    unittest.main()
