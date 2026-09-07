"""
tests/test_scan_alias_dedup.py
================================
실사용 버그 리포트: ES-DE의 msx/msx1처럼 alias 관계인 두 raw 시스템 폴더가 둘 다
존재하고, 둘 다 같은 파일명의 gamelist 항목(스크래퍼가 두 폴더 모두에 똑같이
만들어둔 메타데이터)을 가지면 Local GameList에 같은 게임이 두 줄로 보이던 문제.

재현 조건(실제 사용자 데이터로 확인됨): roms/msx1/에는 ROM 파일이 있고
roms/msx/는 비어있지만, gamelists/msx/gamelist.xml과 gamelists/msx1/gamelist.xml
둘 다 완전히 동일한 <game> 항목을 갖고 있었음. MasterDB Import는 canonical_system()
덕분에 이미 정상적으로 하나로 합쳐지지만(사용자가 직접 확인), Local 자체 목록
(api.py의 scan_local())은 raw 시스템 기준으로만 순회해서 병합 없이 두 줄을 그대로
보여주고 있었다.
"""
import shutil
import unittest
from pathlib import Path

import config as cfgmod
from api import Api


class ScanLocalAliasDedupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path("/tmp/test_scan_alias_dedup_" + self.id().split(".")[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self._orig_config_path = cfgmod.CONFIG_PATH
        self._orig_backup_dir = cfgmod.BACKUP_DIR
        cfgmod.CONFIG_PATH = self.tmp / "config.json"
        cfgmod.BACKUP_DIR = self.tmp / "backup"
        self.api = Api()
        self.api.set_masterdb_path(str(self.tmp / "masterdb"))

    def tearDown(self):
        try:
            self.api.close()
        except Exception:
            pass
        cfgmod.CONFIG_PATH = self._orig_config_path
        cfgmod.BACKUP_DIR = self._orig_backup_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gamelist_xml(self):
        return (
            "<gameList><game><path>./Hyper Sports 1 (Japan).zip</path>"
            "<name>하이퍼 스포츠 1</name><developer>Konami</developer>"
            "<publisher>Konami</publisher><genre>Sports</genre>"
            "<desc>d</desc><rating>0.7</rating><releasedate>19840101T000000</releasedate>"
            "<players>2</players></game></gameList>"
        )

    def test_identical_msx_msx1_gamelist_entries_collapse_to_one_row(self):
        root = self.tmp / "L_ES-DE"
        # roms/msx1 has the real ROM file; roms/msx is a genuinely empty folder.
        (root / "roms" / "msx1").mkdir(parents=True)
        (root / "roms" / "msx").mkdir(parents=True)
        (root / "roms" / "msx1" / "Hyper Sports 1 (Japan).zip").write_text("x")

        # Both gamelists carry an identical entry for the same file (e.g. an old
        # scraper run wrote metadata into both alias folders).
        (root / "meta" / "gamelists" / "msx1").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx1" / "gamelist.xml").write_text(self._gamelist_xml(), encoding="utf-8")
        (root / "meta" / "gamelists" / "msx" / "gamelist.xml").write_text(self._gamelist_xml(), encoding="utf-8")

        r = self.api.add_local("L1", "ES-DE", str(root / "roms"), str(root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        local_id = r["data"]["id"]

        s = self.api.scan_local(local_id)
        self.assertTrue(s["ok"], s.get("error"))
        games = s["data"]["games"]
        titles = [g["title"] for g in games]
        self.assertEqual(titles.count("하이퍼 스포츠 1"), 1, f"같은 게임이 두 줄로 보임: {games}")
        # The surviving row should be the one with the actual ROM file (msx1), not
        # the empty duplicate (msx).
        self.assertTrue(games[0]["romMatched"])
        self.assertEqual(games[0]["system"], "msx1")

    def test_differing_msx_msx1_entries_are_not_merged(self):
        """파일명이 다르면(다른 게임이면) 절대 합치면 안 된다."""
        root = self.tmp / "L_ES-DE"
        (root / "roms" / "msx1").mkdir(parents=True)
        (root / "roms" / "msx").mkdir(parents=True)
        (root / "roms" / "msx1" / "GameA.zip").write_text("x")
        (root / "roms" / "msx" / "GameB.zip").write_text("x")
        (root / "meta" / "gamelists" / "msx1").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx1" / "gamelist.xml").write_text(
            "<gameList><game><path>./GameA.zip</path><name>Game A</name><desc>a</desc></game></gameList>",
            encoding="utf-8",
        )
        (root / "meta" / "gamelists" / "msx" / "gamelist.xml").write_text(
            "<gameList><game><path>./GameB.zip</path><name>Game B</name><desc>b</desc></game></gameList>",
            encoding="utf-8",
        )
        r = self.api.add_local("L1", "ES-DE", str(root / "roms"), str(root / "meta"))
        local_id = r["data"]["id"]
        s = self.api.scan_local(local_id)
        titles = sorted(g["title"] for g in s["data"]["games"])
        self.assertEqual(titles, ["Game A", "Game B"])

    def test_winner_prefers_the_side_with_actual_media_over_metadata_only(self):
        """실사용 재현: roms/에 ROM 파일이 아예 없어(사용자 예시는 metadata 백업 폴더만
        공유한 경우) 둘 다 romMatched=False지만, msx1에만 실제 media(covers 등)가 있고
        msx는 gamelist만 있고 media가 하나도 없는 경우 - media가 있는 쪽이 이겨야 한다.
        예전엔 '메타데이터 존재 여부'만 보고 알파벳순으로 먼저인 msx가 이겨서 media가
        통째로 사라져 보였다."""
        root = self.tmp / "L_ES-DE"
        # No roms/ directory at all - both are Missing ROM, exactly like the shared
        # ES-DE_ODIN2 metadata-only backup folder.
        (root / "meta" / "gamelists" / "msx1").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx").mkdir(parents=True)
        (root / "meta" / "downloaded_media" / "msx1" / "covers").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx1" / "gamelist.xml").write_text(self._gamelist_xml(), encoding="utf-8")
        (root / "meta" / "gamelists" / "msx" / "gamelist.xml").write_text(self._gamelist_xml(), encoding="utf-8")
        (root / "meta" / "downloaded_media" / "msx1" / "covers" / "Hyper Sports 1 (Japan).png").write_bytes(b"PNG")

        r = self.api.add_local("L1", "ES-DE", "", str(root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        local_id = r["data"]["id"]

        s = self.api.scan_local(local_id)
        self.assertTrue(s["ok"], s.get("error"))
        games = s["data"]["games"]
        self.assertEqual(len(games), 1, f"두 줄로 남아있음: {games}")
        self.assertEqual(games[0]["system"], "msx1", "media가 있는 쪽(msx1)이 승자여야 함")
        self.assertTrue(games[0]["hasCover"], "승자로 뽑힌 쪽에 실제 media가 있어야 함")

    def test_media_split_across_alias_folders_is_unioned(self):
        """msx엔 covers만, msx1엔 나머지 media 타입만 있으면 - 한쪽만 반영되지 않고
        둘 다 합쳐져서 반영되어야 한다."""
        root = self.tmp / "L_ES-DE"
        (root / "roms" / "msx1").mkdir(parents=True)
        (root / "roms" / "msx1" / "Hyper Sports 1 (Japan).zip").write_text("x")
        for sub in ("covers",):
            (root / "meta" / "downloaded_media" / "msx" / sub).mkdir(parents=True)
        for sub in ("screenshots", "marquees", "miximages", "wheel"):
            (root / "meta" / "downloaded_media" / "msx1" / sub).mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx1").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx1" / "gamelist.xml").write_text(self._gamelist_xml(), encoding="utf-8")
        (root / "meta" / "gamelists" / "msx" / "gamelist.xml").write_text(self._gamelist_xml(), encoding="utf-8")
        (root / "meta" / "downloaded_media" / "msx" / "covers" / "Hyper Sports 1 (Japan).png").write_bytes(b"PNG")
        for sub in ("screenshots", "marquees", "miximages", "wheel"):
            (root / "meta" / "downloaded_media" / "msx1" / sub / "Hyper Sports 1 (Japan).png").write_bytes(b"PNG")

        r = self.api.add_local("L1", "ES-DE", str(root / "roms"), str(root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        local_id = r["data"]["id"]

        s = self.api.scan_local(local_id)
        self.assertTrue(s["ok"], s.get("error"))
        games = s["data"]["games"]
        self.assertEqual(len(games), 1, f"두 줄로 남아있음: {games}")
        self.assertTrue(games[0]["hasCover"], "msx 쪽의 covers가 반영되어야 함")
        self.assertEqual(games[0]["status"], "완료", "msx1 쪽의 나머지 4개 타입까지 합쳐져야 5종 전부 채워짐")
        self.assertFalse(games[0]["missingMedia"])

    def test_only_msx1_present_still_works_normally(self):
        """msx 폴더 자체가 없는 일반적인 경우는 기존과 동일하게 동작해야 한다."""
        root = self.tmp / "L_ES-DE"
        (root / "roms" / "msx1").mkdir(parents=True)
        (root / "roms" / "msx1" / "Hyper Sports 1 (Japan).zip").write_text("x")
        (root / "meta" / "gamelists" / "msx1").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx1" / "gamelist.xml").write_text(self._gamelist_xml(), encoding="utf-8")
        r = self.api.add_local("L1", "ES-DE", str(root / "roms"), str(root / "meta"))
        local_id = r["data"]["id"]
        s = self.api.scan_local(local_id)
        self.assertEqual(len(s["data"]["games"]), 1)
        self.assertTrue(s["data"]["games"][0]["romMatched"])


if __name__ == "__main__":
    unittest.main()
