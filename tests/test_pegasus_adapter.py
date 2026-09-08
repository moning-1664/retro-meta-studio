"""Pegasus Adapter 테스트.

이 파일의 존재 이유는 ES-DE 테스트와 같다 - **Round-trip 보존**(스펙 §50-51)이다.
이전 프로젝트의 Pegasus writer는 game 블록을 아는 필드만으로 다시 만들어서, 사용자가
직접 넣어 둔 키(`sort-by`, `x-rating`, `assets.boxFront` 등)가 Export 한 번에 사라졌다.
그 회귀를 막는 것이 여기 있는 테스트들이다.
"""

import tempfile
import unittest
from pathlib import Path

from adapters.pegasus import PegasusAdapter, parse_metadata
from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL
from storage.local import LocalStorageProvider

METADATA = """collection: Sony PlayStation 2
shortname: ps2
launch: pcsx2 {file.path}

game: Final Fantasy X
file: FFX.iso
description: A role-playing game.
  Second line of the description.
genre: RPG
developer: Square
publisher: Square Enix
release: 2001-07-19
players: 1
rating: 90%
sort-by: Final Fantasy 10
x-favorite: true

game: Metal Gear Solid 2
file: MGS2.iso
genre: Action
"""


def build_tree(root: Path) -> Path:
    system = root / "ps2"
    (system / "media" / "FFX").mkdir(parents=True)
    (system / METADATA_NAME).write_text(METADATA, encoding="utf-8")
    (system / "FFX.iso").write_bytes(b"r" * 1000)
    (system / "MGS2.iso").write_bytes(b"r" * 2000)
    (system / "media" / "FFX" / "boxFront.png").write_bytes(b"c" * 10)
    (system / "media" / "FFX" / "video.mp4").write_bytes(b"v" * 100)
    return root


METADATA_NAME = "metadata.pegasus.txt"


def make_collection(root):
    return Collection(
        id="col-1", name="Test", frontend="pegasus", root_path=str(root),
        storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "Internal", str(root))],
        systems=[SystemEntry("ps2", STORAGE_INTERNAL)],
    )


class ParseTests(unittest.TestCase):
    def test_header_is_kept_apart_from_games(self):
        header, blocks = parse_metadata(METADATA)
        self.assertEqual(header[0], "collection: Sony PlayStation 2")
        self.assertEqual(len(blocks), 2)

    def test_indented_lines_continue_the_previous_value(self):
        """여러 줄 description을 줄마다 새 키로 읽으면 설명이 통째로 깨진다."""
        _header, blocks = parse_metadata(METADATA)
        desc = dict(blocks[0])["description"]
        self.assertEqual(desc, "A role-playing game.\nSecond line of the description.")

    def test_block_order_is_preserved(self):
        _header, blocks = parse_metadata(METADATA)
        self.assertEqual([k for k, _ in blocks[0]][:3], ["game", "file", "description"])


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.root = build_tree(Path(tempfile.mkdtemp(prefix="rms_pegasus_")))
        self.adapter = PegasusAdapter()
        self.provider = LocalStorageProvider()
        self.collection = make_collection(self.root)
        self.layout = self.adapter.layout(self.collection, "ps2")

    def test_detect_finds_systems(self):
        detection = self.adapter.detect(self.provider, self.root)
        self.assertTrue(detection.matched)
        self.assertEqual(detection.systems, ("ps2",))

    def test_detect_rejects_a_tree_without_metadata(self):
        empty = Path(tempfile.mkdtemp(prefix="rms_pegasus_empty_"))
        (empty / "ps2").mkdir()
        self.assertFalse(self.adapter.detect(self.provider, empty).matched)

    def test_layout_keeps_rom_metadata_and_media_together(self):
        """Pegasus는 ES-DE와 달리 셋이 같은 System 폴더에 있다."""
        self.assertEqual(Path(self.layout.rom_dir), self.root / "ps2")
        self.assertEqual(Path(self.layout.metadata_file), self.root / "ps2" / METADATA_NAME)
        self.assertEqual(Path(self.layout.media_dir), self.root / "ps2" / "media")

    def test_list_roms_ignores_the_metadata_file(self):
        self.assertEqual(self.adapter.list_roms(self.provider, self.layout),
                         ["FFX.iso", "MGS2.iso"])

    def test_read_index_maps_known_fields(self):
        index = self.adapter.read_index(self.provider, self.layout)
        entry = index["FFX.iso"]
        self.assertEqual(entry.fields["name"], "Final Fantasy X")
        self.assertEqual(entry.fields["genre"], "RPG")
        self.assertEqual(entry.fields["developer"], "Square")
        self.assertEqual(entry.fields["releasedate"], "2001-07-19")

    def test_unknown_keys_go_to_frontend_raw(self):
        entry = self.adapter.read_index(self.provider, self.layout)["FFX.iso"]
        extra = {item["key"]: item["value"] for item in entry.frontend_raw["extra"]}
        self.assertEqual(extra["sort-by"], "Final Fantasy 10")
        self.assertEqual(extra["x-favorite"], "true")

    def test_media_index_maps_asset_names_to_types(self):
        index = self.adapter.read_media_index(self.provider, self.layout)
        types = {m.media_type for m in index["FFX"]}
        self.assertEqual(types, {"covers", "videos"})

    def test_media_index_can_be_narrowed(self):
        index = self.adapter.read_media_index(self.provider, self.layout, media_types=["covers"])
        self.assertEqual([m.media_type for m in index["FFX"]], ["covers"])

    # ------------------------------------------------------------------
    # 쓰기 / Round-trip
    # ------------------------------------------------------------------
    def test_writing_preserves_unknown_keys(self):
        """§50-51의 핵심 - 이전 프로젝트가 여기서 값을 잃었다."""
        index = self.adapter.read_index(self.provider, self.layout)
        entry = index["FFX.iso"]
        entry.fields["genre"] = "JRPG"
        self.adapter.write_index(self.layout, [entry])

        text = Path(self.layout.metadata_file).read_text(encoding="utf-8")
        self.assertIn("sort-by: Final Fantasy 10", text)
        self.assertIn("x-favorite: true", text)
        self.assertIn("genre: JRPG", text)

    def test_writing_preserves_the_header_and_other_games(self):
        index = self.adapter.read_index(self.provider, self.layout)
        self.adapter.write_index(self.layout, [index["FFX.iso"]])
        text = Path(self.layout.metadata_file).read_text(encoding="utf-8")
        self.assertIn("collection: Sony PlayStation 2", text)
        self.assertIn("launch: pcsx2 {file.path}", text)
        self.assertIn("game: Metal Gear Solid 2", text)

    def test_round_trip_is_stable(self):
        """읽고 그대로 쓰면 다시 읽었을 때 같아야 한다."""
        before = self.adapter.read_index(self.provider, self.layout)
        self.adapter.write_index(self.layout, list(before.values()))
        after = self.adapter.read_index(self.provider, self.layout)

        self.assertEqual(set(before), set(after))
        for filename, entry in before.items():
            self.assertEqual(entry.fields, after[filename].fields, filename)
            self.assertEqual(entry.frontend_raw, after[filename].frontend_raw, filename)

    def test_multiline_description_survives_the_round_trip(self):
        before = self.adapter.read_index(self.provider, self.layout)["FFX.iso"]
        self.adapter.write_index(self.layout, [before])
        after = self.adapter.read_index(self.provider, self.layout)["FFX.iso"]
        self.assertEqual(after.fields["desc"], before.fields["desc"])
        self.assertIn("\n", after.fields["desc"])

    def test_writing_a_new_game_appends_a_block(self):
        from adapters.base import GameEntry
        self.adapter.write_index(self.layout, [
            GameEntry(filename="New.iso", fields={"name": "New Game", "genre": "Puzzle"})])
        index = self.adapter.read_index(self.provider, self.layout)
        self.assertEqual(index["New.iso"].fields["name"], "New Game")
        self.assertEqual(len(index), 3, "기존 항목이 사라지면 안 된다")

    def test_remove_entries_only_drops_the_named_games(self):
        self.adapter.remove_entries(self.layout, ["FFX.iso"])
        index = self.adapter.read_index(self.provider, self.layout)
        self.assertEqual(list(index), ["MGS2.iso"])
        text = Path(self.layout.metadata_file).read_text(encoding="utf-8")
        self.assertIn("collection: Sony PlayStation 2", text)

    def test_media_pairs_use_pegasus_asset_names(self):
        from adapters.base import MediaFile
        pairs = self.adapter.media_pairs(self.layout, "FFX.iso", [
            MediaFile(media_type="covers", path="/src/a.png"),
            MediaFile(media_type="videos", path="/src/b.mp4"),
        ])
        dests = [Path(dest).name for _src, dest in pairs]
        self.assertEqual(dests, ["boxFront.png", "video.mp4"])
        self.assertEqual(Path(pairs[0][1]).parent, Path(self.layout.media_dir) / "FFX")

    def test_media_pairs_keep_only_the_first_of_each_type(self):
        """Pegasus는 타입당 파일 하나를 기대한다 - 두 번째가 첫 번째를 덮어쓰면 안 된다."""
        from adapters.base import MediaFile
        pairs = self.adapter.media_pairs(self.layout, "FFX.iso", [
            MediaFile(media_type="covers", path="/src/a.png"),
            MediaFile(media_type="covers", path="/src/b.png"),
        ])
        self.assertEqual(len(pairs), 1)


if __name__ == "__main__":
    unittest.main()
