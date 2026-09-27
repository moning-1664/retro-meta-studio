"""EmulationStation media 링크가 Plan/Apply를 거쳐 실제로 gamelist에 적히는지 (Phase 7.1).

Phase 7에서 Adapter까지만 만들고 Apply에 연결하지 않아, **파일은 복사되는데 화면에는
안 나오는** 구멍이 남아 있었다. 이 파일이 그 구멍을 닫는다.

여기서 지키는 경계:

    Adapter          무엇을 어디에 둘지 계산한다 (build_media_links)
    Plan             아무 파일도 건드리지 않는다
    Apply            복사하고, 그 다음에 기록한다 (write_media_links)

그리고 기록은 **System 단위로 한 번만** 일어나야 한다 - ROM마다 gamelist.xml을 다시
쓰면 Adapter 계약 1이 막으려던 O(n^2)가 그대로 재현된다.
"""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from adapters.emulationstation import EmulationStationAdapter
from bridge.api import Api
from tests.fixtures import scan, temp_root, wait_idle

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game>
    <path>./FFX.iso</path>
    <name>Final Fantasy X</name>
    <genre>RPG</genre>
  </game>
  <game>
    <path>./MGS2.iso</path>
    <name>Metal Gear Solid 2</name>
  </game>
</gameList>
"""


def build_es_tree(root: Path, *, games=("FFX.iso", "MGS2.iso"), with_media=False) -> Path:
    gamelist_dir = root / "gamelists" / "ps2"
    gamelist_dir.mkdir(parents=True)
    gamelist_dir.joinpath("gamelist.xml").write_text(GAMELIST, encoding="utf-8")
    (root / "ps2").mkdir(parents=True)
    for name in games:
        (root / "ps2" / name).write_bytes(b"r" * 1000)
    if with_media:
        # **일부러 RetroPie 스타일**로 둔다(`downloaded_images/<system>/<stem>.png`).
        # 우리가 쓸 때 쓰는 배치(`media/<system>/<stem>-<tag>.png`)와 달라야, source의
        # 경로를 그대로 베껴 적었을 때 target에서 깨지는 것이 드러난다. 두 트리가 같은
        # 규칙을 쓰면 상대 경로가 우연히 맞아떨어져 테스트가 무의미해진다.
        images = root / "downloaded_images" / "ps2"
        videos = root / "downloaded_videos" / "ps2"
        images.mkdir(parents=True)
        videos.mkdir(parents=True)
        for name in games:
            stem = Path(name).stem
            (images / f"{stem}.png").write_bytes(b"c" * 50)
            (videos / f"{stem}.mp4").write_bytes(b"v" * 80)
        # 원조 ES는 gamelist가 가리키는 경로만 본다.
        tree = ET.parse(gamelist_dir / "gamelist.xml")
        for game in tree.getroot().findall("game"):
            stem = Path((game.findtext("path") or "").strip()).stem
            ET.SubElement(game, "thumbnail").text = f"../../downloaded_images/ps2/{stem}.png"
            ET.SubElement(game, "video").text = f"../../downloaded_videos/ps2/{stem}.mp4"
        tree.write(gamelist_dir / "gamelist.xml", encoding="utf-8", xml_declaration=True)
    return root


class EsMediaApplyTests(unittest.TestCase):
    """source Collection에서 target Collection으로 복사(Plan -> Apply)."""

    def setUp(self):
        self.dir = temp_root("rms_esmedia_")
        self.source_root = build_es_tree(self.dir / "source", with_media=True)
        # target은 일부러 **한 단계 더 깊은 곳**에 둔다. 두 트리 구조가 같으면 source의
        # 상대 경로를 그대로 베껴 적어도 우연히 해석되어, 테스트가 통과해 버린다.
        self.target_root = build_es_tree(self.dir / "nested" / "target", games=())

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection(
            "Source", "emulationstation", str(self.source_root))["data"]["id"]
        self.dst = self.api.create_collection(
            "Target", "emulationstation", str(self.target_root))["data"]["id"]
        for cid in (self.src, self.dst):
            scan(self.api, cid)

    def tearDown(self):
        self.api.close()

    # ------------------------------------------------------------------
    def _copy_all_to_target(self):
        rows = self.api.list_rows(self.src, limit=50)["data"]["rows"]
        self.api.copy_selection(self.src, [r["romUid"] for r in rows])
        return self.api.paste(self.dst)["data"]

    def _target_gamelist(self):
        return ET.parse(self.target_root / "gamelists" / "ps2" / "gamelist.xml").getroot()

    def _game(self, filename):
        for game in self._target_gamelist().findall("game"):
            if Path((game.findtext("path") or "").strip()).name == filename:
                return game
        return None

    def _apply(self):
        job = self.api.start_apply(self.dst)["data"]["jobId"]
        wait_idle(self.api)
        return self.api.get_job_progress(job)["data"]

    # ------------------------------------------------------------------
    def test_plan_does_not_touch_the_gamelist(self):
        """Plan 단계에서는 아무것도 바뀌지 않는다 - 기존 Plan 계약 그대로."""
        before = (self.target_root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        added = self._copy_all_to_target()
        self.assertEqual(added["added"], 2)

        after = (self.target_root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertEqual(before, after, "Plan이 파일을 건드렸다")
        self.assertFalse((self.target_root / "media").exists(), "Plan이 media를 복사했다")

    def test_apply_copies_media_and_points_the_gamelist_at_it(self):
        """Phase 7이 남긴 구멍 - 복사만 하고 gamelist를 안 고치면 화면에 안 나온다."""
        self._copy_all_to_target()
        result = self._apply()
        self.assertTrue(result["done"])
        self.assertEqual(result["result"]["applied"], 2, result["result"]["errors"])

        game = self._game("FFX.iso")
        self.assertIsNotNone(game, "gamelist에 항목이 만들어져야 한다")
        thumbnail = (game.findtext("thumbnail") or "").strip()
        self.assertTrue(thumbnail, "media 경로가 적혀야 한다")

        # 적힌 경로가 **실제로 복사된 파일**을 가리켜야 한다.
        base = self.target_root / "gamelists" / "ps2"
        resolved = (base / thumbnail).resolve()
        self.assertTrue(resolved.exists(), f"gamelist가 없는 파일을 가리킨다: {thumbnail}")
        self.assertEqual(resolved.read_bytes(), b"c" * 50)

        # **target 안**을 가리켜야 한다. source의 경로를 그대로 베껴 적으면 두 트리
        # 구조가 같을 때만 우연히 맞고, 다르면 남의 폴더를 가리킨다.
        self.assertTrue(str(resolved).startswith(str(self.target_root.resolve())),
                        f"source를 가리키고 있다: {resolved}")

    def test_new_only_system_paste_copies_metadata_rom_and_media(self):
        (self.target_root / "gamelists" / "ps2" / "gamelist.xml").write_text(
            "<gameList/>", encoding="utf-8")
        scan(self.api, self.dst)
        row = next(r for r in self.api.list_rows(self.src, limit=50)["data"]["rows"]
                   if r["file"] == "FFX.iso")
        self.api.copy_selection(self.src, [row["romUid"]])
        preview = self.api.clipboard_system_target(self.dst, "ps2")["data"]
        self.assertEqual(preview["duplicates"], [])
        pasted = self.api.paste(self.dst, "patch", {"ps2": "ps2"}, None, None, True)
        self.assertTrue(pasted["ok"], pasted.get("error"))
        self.assertEqual(pasted["data"]["added"], 1)
        self._apply()
        self.assertTrue((self.target_root / "ps2" / "FFX.iso").is_file())
        game = self._game("FFX.iso")
        self.assertIsNotNone(game)
        self.assertTrue(game.findtext("name"))
        thumbnail = game.findtext("thumbnail")
        self.assertTrue(thumbnail)
        self.assertEqual(((self.target_root / "gamelists" / "ps2") / thumbnail).resolve().read_bytes(),
                         b"c" * 50)

    def test_source_media_paths_do_not_leak_into_the_target(self):
        """`frontend_raw`는 계약 2로 보존되지만, **경로는 그 자리에서만 참이다.**

        원조 ES의 <thumbnail>/<video>는 gamelist에 적힌 경로라 frontend_raw에 담긴다.
        그것을 다른 Collection에 그대로 적으면 target이 source의 폴더를 가리킨다.
        """
        self._copy_all_to_target()
        self._apply()
        game = self._game("FFX.iso")
        base = self.target_root / "gamelists" / "ps2"
        for tag in ("thumbnail", "video"):
            value = (game.findtext(tag) or "").strip()
            self.assertNotIn("downloaded_", value,
                             f"<{tag}>가 source의 배치(RetroPie 스타일)를 그대로 들고 왔다: {value}")
            self.assertTrue((base / value).resolve().exists(),
                            f"<{tag}>가 없는 파일을 가리킨다: {value}")

    def test_metadata_only_entries_get_no_dangling_link(self):
        """복사할 media가 없으면 media 태그도 남지 않아야 한다."""
        no_media_root = build_es_tree(self.dir / "nomedia", games=("FFX.iso",))
        cid = self.api.create_collection(
            "NoMedia", "emulationstation", str(no_media_root))["data"]["id"]
        scan(self.api, cid)

        rows = self.api.list_rows(cid, limit=50)["data"]["rows"]
        self.api.copy_selection(cid, [rows[0]["romUid"]])
        self.api.paste(self.dst)
        self._apply()

        game = self._game("FFX.iso")
        self.assertFalse((game.findtext("thumbnail") or "").strip(),
                         "media가 없는데 경로가 적혔다")

    def test_video_link_is_written_too(self):
        self._copy_all_to_target()
        self._apply()
        game = self._game("FFX.iso")
        video = (game.findtext("video") or "").strip()
        base = self.target_root / "gamelists" / "ps2"
        self.assertTrue((base / video).resolve().exists())

    def test_links_are_written_once_per_system(self):
        """ROM마다 gamelist.xml을 다시 쓰면 계약 1이 막으려던 O(n^2)가 재현된다."""
        self._copy_all_to_target()
        real = EmulationStationAdapter.write_media_links
        calls = []

        def counting(self, layout, links_by_filename):
            calls.append(dict(links_by_filename))
            return real(self, layout, links_by_filename)

        with mock.patch.object(EmulationStationAdapter, "write_media_links", counting):
            self._apply()

        self.assertEqual(len(calls), 1, "System이 하나인데 두 번 이상 썼다")
        self.assertEqual(set(calls[0]), {"FFX.iso", "MGS2.iso"},
                         "한 번의 호출에 그 System의 항목이 전부 들어와야 한다")

    def test_metadata_is_preserved_alongside_the_links(self):
        """media 경로를 적으면서 기존 메타데이터를 날리면 안 된다."""
        self._copy_all_to_target()
        self._apply()
        game = self._game("FFX.iso")
        self.assertEqual(game.findtext("name"), "Final Fantasy X")
        self.assertEqual(game.findtext("genre"), "RPG")

    def test_cache_reflects_the_media_after_apply(self):
        """Apply 뒤 Cache가 갱신되지 않으면 화면은 여전히 media가 없다고 말한다."""
        self._copy_all_to_target()
        self._apply()
        rows = self.api.list_rows(self.dst, limit=50)["data"]["rows"]
        target = next(r for r in rows if r["file"] == "FFX.iso")
        self.assertTrue(target["hasMedia"], "Apply 후 Cache에 media가 반영되지 않았다")


class EsMediaFailureTests(unittest.TestCase):
    """실패 주입 - 링크 기록이 실패하면 성공으로 처리하면 안 된다."""

    def setUp(self):
        self.dir = temp_root("rms_esmedia_fail_")
        self.source_root = build_es_tree(self.dir / "source", with_media=True)
        self.target_root = build_es_tree(self.dir / "target", games=())
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection(
            "Source", "emulationstation", str(self.source_root))["data"]["id"]
        self.dst = self.api.create_collection(
            "Target", "emulationstation", str(self.target_root))["data"]["id"]
        for cid in (self.src, self.dst):
            scan(self.api, cid)
        rows = self.api.list_rows(self.src, limit=50)["data"]["rows"]
        self.api.copy_selection(self.src, [r["romUid"] for r in rows])
        self.api.paste(self.dst)

    def tearDown(self):
        self.api.close()

    def test_a_failed_link_write_downgrades_the_entries_to_partial(self):
        """파일은 복사됐지만 Frontend가 못 찾는 상태다.

        성공으로 처리해 Plan에서 지워버리면 사용자는 왜 media가 안 보이는지 알 길이
        없어진다 - Plan에 남겨 다시 볼 수 있게 한다.
        """
        def boom(self, layout, links_by_filename):
            raise OSError("gamelist.xml에 쓸 수 없습니다")

        with mock.patch.object(EmulationStationAdapter, "write_media_links", boom):
            job = self.api.start_apply(self.dst)["data"]["jobId"]
            wait_idle(self.api)
            result = self.api.get_job_progress(job)["data"]["result"]

        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["partial"], 2, "링크를 못 적었으면 완료가 아니다")
        self.assertTrue(any("media 경로 기록" in e for e in result["errors"]), result["errors"])

        # 복사된 파일 자체는 남는다 - 여기서 지우면 다음 Apply가 처음부터 다시 한다.
        self.assertTrue((self.target_root / "ps2" / "FFX.iso").exists())

        # Plan에도 남아 있어야 사용자가 다시 시도할 수 있다.
        plan = self.api.plan_state(self.dst)["data"]
        self.assertEqual(plan["total"], 2)

    def test_a_failed_media_copy_never_reaches_the_link_step(self):
        """복사가 실패했으면 gamelist에 없는 파일을 가리키게 만들면 안 된다."""
        import app.plan.applier as applier

        def failing_copy(dest_dirs, pairs, *args, **kwargs):
            return {str(dest): False for _src, dest in pairs}

        called = []
        real = EmulationStationAdapter.write_media_links

        def spy(self, layout, links_by_filename):
            called.append(links_by_filename)
            return real(self, layout, links_by_filename)

        with mock.patch.object(applier.file_ops, "copy_files", failing_copy), \
             mock.patch.object(EmulationStationAdapter, "write_media_links", spy):
            job = self.api.start_apply(self.dst)["data"]["jobId"]
            wait_idle(self.api)
            result = self.api.get_job_progress(job)["data"]["result"]

        self.assertEqual(result["failed"], 2)
        self.assertEqual(called, [], "복사가 실패했는데 링크를 적으려 했다")

    def test_media_that_was_not_copied_is_not_linked(self):
        """건너뛴 media까지 적으면 gamelist가 없는 파일을 가리킨다."""
        adapter = EmulationStationAdapter()
        collection = self.api.registry.get_collection(self.dst)
        layout = adapter.layout(collection, "ps2")

        # 복사를 하지 않은 상태에서 링크만 계산 -> 실제 파일이 없다.
        from adapters.base import MediaFile
        links = adapter.build_media_links(layout, "FFX.iso",
                                          [MediaFile(media_type="covers", path="/nope/a.png")])
        self.assertTrue(links, "계산 자체는 된다")
        self.assertFalse(Path(links[0][1]).exists(),
                         "계산만으로 파일이 생기지는 않는다 - Apply가 존재하는 것만 적어야 한다")


if __name__ == "__main__":
    unittest.main()
