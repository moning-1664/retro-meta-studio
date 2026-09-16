"""app/title_affix.py - 지역 분류, 기존 장식 떼기, 디스크 표시 보존, 새 장식 붙이기."""

import unittest

from app.title_affix import (
    DEFAULT_CONFIG, classify_region, compute_new_title, normalize_config,
    strip_existing_title_affix,
)


class RegionClassifyTests(unittest.TestCase):
    """구역은 **파일명의 지역 태그**로 정한다(사용자 결정) - gamelist의 region 필드가 아니다."""

    def test_bracket_tags_in_the_filename(self):
        cases = {
            "Game (K).iso": "kr", "Game (KR).iso": "kr", "Game [Kor].zip": "kr", "Game (Korea).iso": "kr",
            "Game (U).iso": "en", "Game (USA).iso": "en", "Game [us].bin": "en",
            "Game (J).iso": "jp", "Game (Japan).iso": "jp",
            "Game (E).iso": "eu", "Game (Europe).iso": "eu", "Game [PAL].iso": "eu",
            "Game (W).iso": "global", "Game (World).iso": "global", "Game (Global).iso": "global",
        }
        for filename, expected in cases.items():
            self.assertEqual(classify_region(filename), expected, filename)

    def test_delimiter_attached_tags_in_the_filename(self):
        self.assertEqual(classify_region("Game_k.gba"), "kr")
        self.assertEqual(classify_region("Game-kr.gba"), "kr")
        self.assertEqual(classify_region("global_Game.bin"), "global")
        self.assertEqual(classify_region("Game_usa_v2.iso"), "en")

    def test_no_tag_is_unclassified(self):
        # 미분류는 자동 적용 대상에서 빠진다 - 아무 구역으로도 단정하지 않는다.
        for filename in (None, "", "Chrono Trigger.sfc", "SMW.sfc", "Final Fantasy X.iso"):
            self.assertIsNone(classify_region(filename))

    def test_words_inside_the_title_are_not_mistaken_for_tags(self):
        # 공백으로 띄운 평범한 단어는 태그가 아니다 - 괄호나 _ - 로 붙어야 인정한다.
        self.assertIsNone(classify_region("Global Defense.iso"))
        self.assertIsNone(classify_region("Europe Simulator.iso"))

    def test_disk_and_revision_brackets_are_not_region_tags(self):
        self.assertIsNone(classify_region("Chrono Trigger (Disc 1).iso"))
        self.assertIsNone(classify_region("Chrono Trigger (2/2).iso"))
        self.assertIsNone(classify_region("Game (Rev A).iso"))
        self.assertIsNone(classify_region("Game (1994).iso"))

    def test_multiple_tags_prefer_the_bucket_that_comes_first_in_priority_order(self):
        # kr, en, jp, eu, global 순으로 먼저 매치되는 쪽이 이긴다.
        self.assertEqual(classify_region("Game (USA) (Europe).iso"), "en")
        self.assertEqual(classify_region("Game (Europe) (Japan).iso"), "jp")


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

    def test_bare_fraction_disk_marker_without_the_word_is_recognized(self):
        # 실사용 피드백: 단어 없는 "(2/2)"가 지역 장식과 함께 지워졌다.
        base, disk = strip_existing_title_affix("Chrono Trigger (2/2)")
        self.assertEqual((base, disk), ("Chrono Trigger", "(Disk 2 of 2)"))
        base, disk = strip_existing_title_affix("Chrono Trigger (1 of 3)")
        self.assertEqual((base, disk), ("Chrono Trigger", "(Disk 1 of 3)"))

    def test_a_lone_number_without_a_word_or_total_is_not_a_disk_marker(self):
        # 총 장수 없이 숫자 하나만 있으면 발매연도 등과 구별할 수 없다 - 디스크로 보지 않는다.
        base, disk = strip_existing_title_affix("Some Game (1994)")
        self.assertIsNone(disk)
        self.assertEqual(base, "Some Game")   # 여전히 일반 괄호 장식으로는 떼어낸다

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
        r = compute_new_title("Final Fantasy X", "FFX (USA).iso", {"en": {"enabled": True, "mode": "prefix", "text": "EN"}})
        self.assertEqual(r["newTitle"], "EN_Final Fantasy X")
        r = compute_new_title("Final Fantasy X", "FFX (USA).iso", {"en": {"enabled": True, "mode": "postfix", "text": "EN"}})
        self.assertEqual(r["newTitle"], "Final Fantasy X_EN")

    def test_bracket_wrapped_text_needs_no_extra_separator(self):
        r = compute_new_title("Final Fantasy X", "FFX (USA).iso", {"en": {"enabled": True, "mode": "prefix", "text": "[EN]"}})
        self.assertEqual(r["newTitle"], "[EN]Final Fantasy X")
        r = compute_new_title("Final Fantasy X", "FFX (USA).iso", {"en": {"enabled": True, "mode": "postfix", "text": "(EN)"}})
        self.assertEqual(r["newTitle"], "Final Fantasy X(EN)")

    def test_text_already_ending_or_starting_with_a_delimiter_needs_no_extra_underscore(self):
        r = compute_new_title("Final Fantasy X", "FFX (USA).iso", {"en": {"enabled": True, "mode": "prefix", "text": "EN-"}})
        self.assertEqual(r["newTitle"], "EN-Final Fantasy X")
        r = compute_new_title("Final Fantasy X", "FFX (USA).iso", {"en": {"enabled": True, "mode": "postfix", "text": "-EN"}})
        self.assertEqual(r["newTitle"], "Final Fantasy X-EN")

    def test_사용자가_직접_넣은_공백은_지워지지_않는다(self):
        """실사용 피드백: " (KR)"를 postfix로 넣으면 앞 공백이 사라져 "Title(KR)"이
        됐다. 공백 자체가 구분자이므로 자동 언더바 없이 그대로 살아야 한다."""
        r = compute_new_title("Final Fantasy X", "FFX (K).iso",
                              {"kr": {"enabled": True, "mode": "postfix", "text": " (KR)"}})
        self.assertEqual(r["newTitle"], "Final Fantasy X (KR)")
        r = compute_new_title("Final Fantasy X", "FFX (K).iso",
                              {"kr": {"enabled": True, "mode": "prefix", "text": "(KR) "}})
        self.assertEqual(r["newTitle"], "(KR) Final Fantasy X")


class ComputeNewTitleTests(unittest.TestCase):
    def test_disabled_region_leaves_the_stripped_title_unchanged(self):
        r = compute_new_title("[KR] Final Fantasy X", "FFX (K).iso", DEFAULT_CONFIG)
        self.assertEqual(r["newTitle"], "Final Fantasy X")
        self.assertTrue(r["changed"])  # 장식은 뗐으므로 그 자체로 변경이다
        self.assertEqual(r["regionBucket"], "kr")

    def test_untagged_filename_is_left_completely_alone(self):
        """미분류는 장식을 떼지도, 붙이지도 않는다(사용자 결정 - 자동 적용 대상에서 제외)."""
        config = normalize_config({"global": {"enabled": True, "mode": "prefix", "text": "WORLD"}})
        r = compute_new_title("[EU] Some Homebrew Game", "Homebrew.iso", config)
        self.assertEqual(r["newTitle"], "[EU] Some Homebrew Game")   # 기존 장식도 그대로 둔다
        self.assertFalse(r["changed"])
        self.assertIsNone(r["regionBucket"])

    def test_global_tag_in_the_filename_uses_the_global_setting(self):
        # 사용자 피드백: 글로벌은 파일명에 global이라고 따로 붙어 나온다.
        config = normalize_config({"global": {"enabled": True, "mode": "prefix", "text": "WORLD"}})
        r = compute_new_title("Some Game", "global_Some Game.iso", config)
        self.assertEqual(r["newTitle"], "WORLD_Some Game")
        self.assertEqual(r["regionBucket"], "global")

    def test_full_pipeline_strip_then_reapply_with_disk_marker_preserved(self):
        config = normalize_config({"kr": {"enabled": True, "mode": "prefix", "text": "KR"}})
        r = compute_new_title("[EU] Final Fantasy VII (Disc 2 of 3)", "FF7 (K) (Disc 2 of 3).iso", config)
        self.assertEqual(r["newTitle"], "KR_Final Fantasy VII (Disc 2 of 3)")
        self.assertEqual(r["diskMarker"], "(Disc 2 of 3)")

    def test_already_correctly_decorated_title_is_reported_unchanged(self):
        config = normalize_config({"kr": {"enabled": True, "mode": "prefix", "text": "KR"}})
        r = compute_new_title("KR_Final Fantasy X", "FFX [Kor].iso", config)
        self.assertEqual(r["newTitle"], "KR_Final Fantasy X")
        self.assertFalse(r["changed"])

    def test_postfix_mode(self):
        config = normalize_config({"jp": {"enabled": True, "mode": "postfix", "text": "JP"}})
        r = compute_new_title("Dragon Quest", "DQ (J).sfc", config)
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
