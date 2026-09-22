"""app/gameid.py - "이 둘은 같은 게임인가"의 단 하나의 규칙(사용자 결정).

여기 있는 예시는 **사용자의 실제 라이브러리에서 뽑은 것**이 많다. 규칙을 바꿀 때
이 파일이 실제로 무엇을 뭉치고 무엇을 가르는지 보여 준다.
"""

import unittest

from app.gameid import GameKey, key_of, pick_target, same_disc, same_game


def same(a, b):
    return same_game(key_of(a), key_of(b))


class SameGameTests(unittest.TestCase):
    def test_region_and_language_tags_do_not_matter(self):
        self.assertTrue(same("Final Fantasy 3 (K).zip", "Final Fantasy 3.zip"))
        self.assertTrue(same("Game (USA).zip", "Game (Japan).zip"))
        self.assertTrue(same("1942.zip", "1942 (World).zip"))
        self.assertTrue(same("94 Super World Cup Soccer (K).sms", "94 Super World Cup Soccer [K].sms"))

    def test_the_extension_does_not_matter(self):
        self.assertTrue(same("Tactics Ogre Gaiden-The Knight of Lodis [K].gba",
                             "Tactics Ogre Gaiden-The Knight of Lodis [K].zip"))
        self.assertTrue(same("Antarctic Adventure (J).zip", "Antarctic Adventure.rom"))

    def test_separators_are_just_spaces(self):
        self.assertTrue(same("Super_Mario-World.sfc", "Super Mario World.sfc"))
        self.assertTrue(same("Rockman X2 Soul Eraser.zip", "Rockman X2-Soul Eraser [K].zip"))

    def test_a_missing_episode_number_means_one(self):
        self.assertTrue(same("Metal Gear.zip", "Metal Gear 1.zip"))
        self.assertTrue(same("Metal Gear (1987)(Konami)(Jp)[RC-750].rom", "Metal Gear 1.zip"))

    def test_a_subtitle_on_only_one_side_is_ignored(self):
        self.assertTrue(same("Metal Gear 2 - Solid Snake.zip", "Metal Gear 2.zip"))
        self.assertTrue(same("Dragon Quest VIII - Journey of the Cursed King.chd",
                             "Dragon Quest VIII.chd"))

    def test_two_different_subtitles_are_two_games(self):
        self.assertFalse(same("Contra: Hard Corps.zip", "Contra: Legacy of War.zip"))

    def test_episode_numbers_are_compared_strictly(self):
        self.assertFalse(same("Dragon Ball 2 (K).zip", "Dragon Ball Z1 (K).zip"))
        self.assertFalse(same("Final Fantasy 3.zip", "Final Fantasy 4.zip"))
        self.assertFalse(same("Rockman X.smc", "Rockman.smc"))

    def test_roman_numerals_are_left_alone(self):
        """사용자 결정(번복) - 로마자를 숫자로 바꾸면 실제 라이브러리에서 틀리는 쪽이
        훨씬 많았다(`Rockman X`, `Rally X`, `Spartan X`, `Guilty Gear X`...). 글자
        그대로 둔다."""
        self.assertFalse(same("Final Fantasy II.zip", "Final Fantasy 2.zip"))
        # 그래도 로마자로 끝나는 제목이 "편수 없음"으로 뭉개지지는 않는다.
        self.assertFalse(same("Rally X.zip", "Rally.zip"))
        self.assertEqual(key_of("Final Fantasy II.zip").full, "final fantasy ii")

    def test_the_rom_file_is_never_consulted(self):
        """파일명만 본다 - ROM이 실제로 있는지는 판단에 들어가지 않는다."""
        self.assertTrue(same("Ghost.iso", "Ghost.iso"))

    def test_an_empty_name_matches_nothing(self):
        self.assertFalse(same("", "Game.zip"))
        self.assertFalse(same("", ""))


class DiscTests(unittest.TestCase):
    def test_discs_are_the_same_game(self):
        self.assertTrue(same("Game (Disc 1).bin", "Game (Disc 2).bin"))
        self.assertTrue(same("Yu-No (Disc A).chd", "Yu-No (Disc C).chd"))
        self.assertTrue(same("Snatcher (Disk 1 of 3).dsk", "Snatcher (Disk 3 of 3).dsk"))

    def test_the_number_is_kept_for_pairing(self):
        self.assertEqual(key_of("Game (Disc 2 of 4).bin").disc, "2")
        self.assertEqual(key_of("Game (Disc 2 of 4).bin").disc_total, "4")
        self.assertEqual(key_of("Snatcher (1 of 3).dsk").disc, "1")
        self.assertEqual(key_of("Yu-No (Disc A).chd").disc, "a")

    def test_a_slash_in_the_name_does_not_cut_it_short(self):
        """`Path().stem`을 쓰면 `1/3`을 경로로 읽어 이름이 잘린다."""
        self.assertEqual(key_of("Snatcher (1/3).dsk").full, "snatcher 1")
        self.assertEqual(key_of("Snatcher (1/3).dsk").disc, "1")

    def test_a_bare_number_without_a_total_is_not_a_disc(self):
        """`(1994)`는 발매연도지 디스크가 아니다."""
        self.assertIsNone(key_of("Game (1994).zip").disc)

    def test_userdisk_is_not_a_disc_number(self):
        """실제 라이브러리의 `Ancient Ys ... (Userdisk).dsk`."""
        self.assertIsNone(key_of("Ancient Ys (Userdisk).dsk").disc)
        self.assertTrue(same("Ancient Ys (Disk 1 of 2).dsk", "Ancient Ys (Userdisk).dsk"))

    def test_same_disc_treats_no_disc_as_equal(self):
        self.assertTrue(same_disc(key_of("A.zip"), key_of("B.zip")))
        self.assertFalse(same_disc(key_of("A (Disc 1).bin"), key_of("A (Disc 2).bin")))


class PickTargetTests(unittest.TestCase):
    """후보가 여럿일 때 어디에 쓸지(사용자 결정) - 임의가 아니라 정해진 순서로 고른다."""

    def test_an_exact_filename_wins(self):
        got, how = pick_target("Game (USA).zip",
                               [("Game (Japan).zip", "jp"), ("Game (USA).zip", "us")])
        self.assertEqual((got, how), ("us", "exact"))

    def test_the_disc_number_pairs_up(self):
        got, how = pick_target("Game (Disc 2) [K].bin",
                               [("Game (Disc 1).bin", "d1"), ("Game (Disc 2).bin", "d2")])
        self.assertEqual((got, how), ("d2", "disc"))

    def test_the_region_pairs_up_when_the_disc_cannot_decide(self):
        got, how = pick_target("Game (Japan).zip",
                               [("Game (Korea).zip", "kr"), ("Game (Japan) (Rev 1).zip", "jp")])
        self.assertEqual((got, how), ("jp", "region"))

    def test_otherwise_the_first_by_name_wins_and_stays_stable(self):
        """사용자 결정 - "아무거나". 임의로 고르면 실행할 때마다 답이 달라지므로
        알파벳 순으로 고정한다."""
        candidates = [("Game (Korea).zip", "kr"), ("Game (Japan).zip", "jp")]
        first = pick_target("Game (Europe).zip", candidates)
        second = pick_target("Game (Europe).zip", list(reversed(candidates)))
        self.assertEqual(first, second)
        self.assertEqual(first, ("jp", "first"))

    def test_no_candidate(self):
        self.assertEqual(pick_target("Game.zip", []), (None, "none"))

class DiscSuffixTests(unittest.TestCase):
    """제목 뒤에 장 번호 붙이기(사용자 결정 - 옵션). ES-DE는 목록에 파일명을 보여주지
    않아 여러 장짜리 게임의 제목이 전부 똑같아 보인다."""

    def test_the_word_depends_on_the_system(self):
        from app.title_affix import disc_suffix
        self.assertIn("Disc", disc_suffix("Game (Disc 1 of 3).bin", "psx"))
        self.assertIn("Disk", disc_suffix("Game (Disk 1 of 3).dsk", "msx2"))
        self.assertIn("Disk", disc_suffix("Game (Disk 1 of 3).d88", "pc98"))

    def test_every_format_produces_something_readable(self):
        from app.title_affix import DISC_FORMATS, disc_suffix
        for fmt in DISC_FORMATS:
            got = disc_suffix("Game (Disc 2 of 4).bin", "psx", fmt)
            self.assertIn("2", got, fmt)
            self.assertTrue(got.startswith(" "), fmt)

    def test_an_unknown_total_does_not_leave_a_dangling_slash(self):
        from app.title_affix import disc_suffix
        got = disc_suffix("Game (Disc 3).bin", "psx", "paren_word_slash")
        self.assertNotIn("/", got)
        self.assertIn("3", got)

    def test_a_game_without_discs_gets_nothing(self):
        from app.title_affix import disc_suffix, with_disc_suffix
        self.assertEqual(disc_suffix("Plain.zip", "psx"), "")
        self.assertEqual(with_disc_suffix("Plain", "Plain.zip", "psx"), "Plain")

    def test_applying_twice_does_not_stack(self):
        from app.title_affix import with_disc_suffix
        once = with_disc_suffix("Snatcher", "Snatcher (Disk 1 of 3).dsk", "msx2")
        twice = with_disc_suffix(once, "Snatcher (Disk 1 of 3).dsk", "msx2")
        self.assertEqual(once, twice)
        self.assertEqual(once.count("Disk"), 1)

    def test_a_letter_disc_is_kept(self):
        from app.title_affix import with_disc_suffix
        self.assertIn("A", with_disc_suffix("Yu-No", "Yu-No (Disc A).chd", "saturn"))

if __name__ == "__main__":
    unittest.main()


class DiscRetagTests(unittest.TestCase):
    """"멀티 디스크 태그 적용"(System 우클릭) - 기존 꼬리표를 지우고 지금 고른 형식으로
    다시 붙인다."""

    def test_strip_removes_only_disc_looking_suffixes(self):
        from app.title_affix import strip_disc_suffix
        self.assertEqual(strip_disc_suffix("Metal Gear Solid (Disc 1/2)"), "Metal Gear Solid")
        self.assertEqual(strip_disc_suffix("Metal Gear Solid [Disc 1 of 2]"), "Metal Gear Solid")
        self.assertEqual(strip_disc_suffix("Metal Gear Solid (1/2)"), "Metal Gear Solid")
        # 발매연도/지역/리비전은 디스크 표시가 아니다 - 지우면 안 된다.
        self.assertEqual(strip_disc_suffix("Metal Gear Solid (1994)"), "Metal Gear Solid (1994)")
        self.assertEqual(strip_disc_suffix("Metal Gear Solid (USA)"), "Metal Gear Solid (USA)")
        self.assertEqual(strip_disc_suffix("Metal Gear Solid (Rev A)"), "Metal Gear Solid (Rev A)")

    def test_retag_switches_the_format_instead_of_stacking(self):
        from app.title_affix import retagged_disc_suffix
        title = retagged_disc_suffix("Snatcher (Disk 1/3)", "Snatcher (Disk 1 of 3).dsk",
                                     "msx2", "bracket_word_of")
        self.assertEqual(title, "Snatcher [Disk 1 of 3]")
        self.assertNotIn("(Disk 1/3)", title)
