"""app/title_affix.py - 지역 분류, 기존 장식 떼기, 디스크 표시 보존, 새 장식 붙이기."""

import unittest

from app.title_affix import (
    DEFAULT_CONFIG, classify_region, compute_new_title, normalize_config,
    strip_existing_title_affix,
)


class RegionClassifyTests(unittest.TestCase):
    def test_common_notations_map_to_the_right_bucket(self):
        cases = {
            "USA": "en", "US": "en", "usa": "en", "English": "en", "America": "en",
            "Japan": "jp", "JP": "jp", "jpn": "jp",
            "Europe": "eu", "EU": "eu", "UK": "eu", "GB": "eu",
            "Korea": "kr", "KR": "kr", "kor": "kr",
            "World": "global", "Wor": "global", "International": "global",
        }
        for region, expected in cases.items():
            self.assertEqual(classify_region(region), expected, region)

    def test_unrecognized_or_empty_region_is_none(self):
        for region in (None, "", "  ", "Brazil", "???"):
            self.assertIsNone(classify_region(region))

    def test_multi_token_region_prefers_the_bucket_that_comes_first_in_REGIONS(self):
        # REGIONS 순서(kr, en, jp, eu, global)대로 먼저 매치되는 쪽이 이긴다.
        self.assertEqual(classify_region("USA, Europe"), "en")
        self.assertEqual(classify_region("Europe, Japan"), "jp")


class StripExistingAffixTests(unittest.TestCase):
    def test_bracket_prefix_and_postfix_are_removed(self):
        self.assertEqual(strip_existing_title_affix("[KR] Final Fantasy X"), ("Final Fantasy X", None))
        self.assertEqual(strip_existing_title_affix("Final Fantasy X (KR)"), ("Final Fantasy X", None))
        self.assertEqual(strip_existing_title_affix("[KR] Final Fantasy X (EU)"), ("Final Fantasy X", None))

    def test_underscore_and_dash_joined_tokens_are_removed(self):
        self.assertEqual(strip_existing_title_affix("KR_Final Fantasy X"), ("Final Fantasy X", None))
        self.assertEqual(strip_existing_title_affix("Final Fantasy X_KR"), ("Final Fantasy X", None))
        self.assertEqual(strip_existing_title_affix("EU-Final Fantasy X"), ("Final Fantasy X", None))
        self.assertEqual(strip_existing_title_affix("Final Fantasy X-EU"), ("Final Fantasy X", None))

    def test_stacked_affixes_from_repeated_runs_are_all_removed(self):
        # 이 기능을 두 번 돌렸을 때처럼 접두/접미가 겹쳐 쌓인 경우.
        self.assertEqual(strip_existing_title_affix("[KR]_[KR]_Final Fantasy X"), ("Final Fantasy X", None))

    def test_disk_marker_is_extracted_and_normalized_not_treated_as_junk(self):
        base, disk = strip_existing_title_affix("Final Fantasy VII (Disc 1 of 3)")
        self.assertEqual((base, disk), ("Final Fantasy VII", "(Disc 1 of 3)"))
        base, disk = strip_existing_title_affix("Final Fantasy VII (disk 2)")
        self.assertEqual((base, disk), ("Final Fantasy VII", "(Disk 2)"))
        base, disk = strip_existing_title_affix("[Disk A] Xanadu")
        self.assertEqual((base, disk), ("Xanadu", "(Disk A)"))

    def test_disk_marker_survives_alongside_region_affixes(self):
        base, disk = strip_existing_title_affix("[KR] Final Fantasy VII (Disc 1 of 3)_EU")
        self.assertEqual((base, disk), ("Final Fantasy VII", "(Disc 1 of 3)"))

    def test_a_title_with_no_decoration_is_untouched(self):
        self.assertEqual(strip_existing_title_affix("Chrono Trigger"), ("Chrono Trigger", None))

    def test_never_strips_down_to_an_empty_title(self):
        # 제목 전체가 괄호 하나뿐이면(흔치 않지만) 벗겨서 빈 문자열로 만들지 않는다.
        base, _ = strip_existing_title_affix("(Homebrew)")
        self.assertTrue(base)


class JoinTests(unittest.TestCase):
    """텍스트가 괄호/구분자로 이미 묶여 있지 않으면 언더바를 자동으로 끼운다(사용자 결정)."""

    def test_bare_text_gets_an_underscore_at_the_join(self):
        r = compute_new_title("Final Fantasy X", "USA", {"en": {"enabled": True, "mode": "prefix", "text": "EN"}})
        self.assertEqual(r["newTitle"], "EN_Final Fantasy X")
        r = compute_new_title("Final Fantasy X", "USA", {"en": {"enabled": True, "mode": "postfix", "text": "EN"}})
        self.assertEqual(r["newTitle"], "Final Fantasy X_EN")

    def test_bracket_wrapped_text_needs_no_extra_separator(self):
        r = compute_new_title("Final Fantasy X", "USA", {"en": {"enabled": True, "mode": "prefix", "text": "[EN]"}})
        self.assertEqual(r["newTitle"], "[EN]Final Fantasy X")
        r = compute_new_title("Final Fantasy X", "USA", {"en": {"enabled": True, "mode": "postfix", "text": "(EN)"}})
        self.assertEqual(r["newTitle"], "Final Fantasy X(EN)")

    def test_text_already_ending_or_starting_with_a_delimiter_needs_no_extra_underscore(self):
        r = compute_new_title("Final Fantasy X", "USA", {"en": {"enabled": True, "mode": "prefix", "text": "EN-"}})
        self.assertEqual(r["newTitle"], "EN-Final Fantasy X")
        r = compute_new_title("Final Fantasy X", "USA", {"en": {"enabled": True, "mode": "postfix", "text": "-EN"}})
        self.assertEqual(r["newTitle"], "Final Fantasy X-EN")


class ComputeNewTitleTests(unittest.TestCase):
    def test_disabled_region_leaves_the_stripped_title_unchanged(self):
        r = compute_new_title("[KR] Final Fantasy X", "Korea", DEFAULT_CONFIG)
        self.assertEqual(r["newTitle"], "Final Fantasy X")
        self.assertTrue(r["changed"])  # 장식은 뗐으므로 그 자체로 변경이다
        self.assertEqual(r["regionBucket"], "kr")

    def test_unrecognized_region_only_strips_and_does_not_add_a_new_affix(self):
        config = {"global": {"enabled": True, "mode": "prefix", "text": "WORLD"}}
        r = compute_new_title("Some Homebrew Game", "Brazil", config)
        self.assertEqual(r["newTitle"], "Some Homebrew Game")
        self.assertFalse(r["changed"])
        self.assertIsNone(r["regionBucket"])

    def test_full_pipeline_strip_then_reapply_with_disk_marker_preserved(self):
        config = normalize_config({"kr": {"enabled": True, "mode": "prefix", "text": "KR"}})
        r = compute_new_title("[EU] Final Fantasy VII (Disc 2 of 3)", "Korea", config)
        self.assertEqual(r["newTitle"], "KR_Final Fantasy VII (Disc 2 of 3)")
        self.assertEqual(r["diskMarker"], "(Disc 2 of 3)")

    def test_already_correctly_decorated_title_is_reported_unchanged(self):
        config = normalize_config({"kr": {"enabled": True, "mode": "prefix", "text": "KR"}})
        r = compute_new_title("KR_Final Fantasy X", "Korea", config)
        self.assertEqual(r["newTitle"], "KR_Final Fantasy X")
        self.assertFalse(r["changed"])

    def test_postfix_mode(self):
        config = normalize_config({"jp": {"enabled": True, "mode": "postfix", "text": "JP"}})
        r = compute_new_title("Dragon Quest", "Japan", config)
        self.assertEqual(r["newTitle"], "Dragon Quest_JP")


class NormalizeConfigTests(unittest.TestCase):
    def test_fills_in_missing_regions_and_fields_with_defaults(self):
        result = normalize_config({"kr": {"enabled": True}})
        self.assertEqual(result["kr"], {"enabled": True, "mode": "prefix", "text": "KR"})
        self.assertEqual(result["global"], DEFAULT_CONFIG["global"])

    def test_rejects_an_invalid_mode(self):
        result = normalize_config({"kr": {"mode": "nonsense"}})
        self.assertEqual(result["kr"]["mode"], "prefix")


if __name__ == "__main__":
    unittest.main()
