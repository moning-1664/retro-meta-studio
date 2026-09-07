"""ES-DE Adapter와 증분 스캐너 테스트.

가장 중요한 것은 Round-trip 보존(스펙 §50-51)이다. 이전 프로젝트는 아는 태그만
뽑고 나머지를 버려서, gamelist.xml을 다시 쓰는 순간 favorite/playcount 같은 값이
사라졌다. 그 회귀를 막는 것이 이 파일의 존재 이유다.
"""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.es_de import EsDeAdapter
from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL
from app.store.cache import CacheStore
from app.scan.scanner import scan_collection
from storage.local import LocalStorageProvider

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game id="42" source="ScreenScraper">
    <path>./FFX.iso</path>
    <name>Final Fantasy X</name>
    <desc>A role-playing game.</desc>
    <genre>RPG</genre>
    <developer>Square</developer>
    <publisher>Square Enix</publisher>
    <releasedate>20010719T000000</releasedate>
    <players>1</players>
    <rating>0.9</rating>
    <favorite>true</favorite>
    <playcount>17</playcount>
    <lastplayed>20240101T120000</lastplayed>
    <sortname>Final Fantasy 10</sortname>
    <altemulator>PCSX2</altemulator>
  </game>
  <game>
    <path>./MGS2.iso</path>
    <name>Metal Gear Solid 2</name>
  </game>
  <game>
    <path>./MetadataOnly.iso</path>
    <name>ROM 없는 항목</name>
  </game>
  <folder>
    <path>./Extras</path>
    <name>Extras</name>
  </folder>
</gameList>
"""


def build_esde_tree(root: Path):
    """실제 ES-DE 레이아웃을 흉내낸 최소 트리."""
    (root / "gamelists" / "ps2").mkdir(parents=True)
    (root / "gamelists" / "ps2" / "gamelist.xml").write_text(GAMELIST, encoding="utf-8")
    for folder in ("covers", "screenshots", "videos"):
        (root / "downloaded_media" / "ps2" / folder).mkdir(parents=True)
    (root / "downloaded_media" / "ps2" / "covers" / "FFX.png").write_bytes(b"x" * 10)
    (root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").write_bytes(b"v" * 100)
    (root / "ps2").mkdir()
    (root / "ps2" / "FFX.iso").write_bytes(b"r" * 1000)
    (root / "ps2" / "MGS2.iso").write_bytes(b"r" * 2000)
    # ES-DE가 만들지만 게임 시스템이 아닌 폴더
    (root / "gamelists" / "cleanup").mkdir()
    return root


def make_collection(root):
    return Collection(
        id="col-1", name="Test", frontend="es-de", root_path=str(root),
        storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "Internal", str(root))],
        systems=[SystemEntry("ps2", STORAGE_INTERNAL)],
    )


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.root = build_esde_tree(Path(tempfile.mkdtemp(prefix="rms_esde_")))
        self.adapter = EsDeAdapter()
        self.provider = LocalStorageProvider()
        self.collection = make_collection(self.root)
        self.layout = self.adapter.layout(self.collection, "ps2")

    def test_detect_finds_systems_and_ignores_cleanup(self):
        detection = self.adapter.detect(self.provider, self.root)
        self.assertTrue(detection.matched)
        self.assertEqual(detection.systems, ("ps2",))

    def test_layout_follows_the_systems_storage(self):
        collection = make_collection(self.root)
        collection.storages.append(StorageLocation("ext-1", "external", "SD", r"F:\roms"))
        collection.systems = [SystemEntry("ps2", "ext-1")]
        layout = self.adapter.layout(collection, "ps2")
        # ROM은 Storage를 따라가고, gamelist/media는 Collection root에 남는다.
        self.assertEqual(Path(layout.rom_dir), Path(r"F:\roms\ps2"))
        self.assertEqual(Path(layout.metadata_file), self.root / "gamelists" / "ps2" / "gamelist.xml")

    def test_read_index_maps_known_fields(self):
        index = self.adapter.read_index(self.provider, self.layout)
        self.assertEqual(set(index), {"FFX.iso", "MGS2.iso", "MetadataOnly.iso"})
        ffx = index["FFX.iso"].fields
        self.assertEqual(ffx["name"], "Final Fantasy X")
        self.assertEqual(ffx["releasedate"], "2001-07-19")  # ES-DE 형식 -> 공통 형식
        self.assertEqual(ffx["rating"], "4.5")              # 0.0~1.0 -> 5점 만점

    def test_unknown_tags_and_attributes_are_preserved(self):
        index = self.adapter.read_index(self.provider, self.layout)
        raw = index["FFX.iso"].frontend_raw
        extras = {item["tag"]: item["text"] for item in raw["extra"]}
        self.assertEqual(extras["favorite"], "true")
        self.assertEqual(extras["playcount"], "17")
        self.assertEqual(extras["altemulator"], "PCSX2")
        self.assertEqual(raw["attrib"], {"id": "42", "source": "ScreenScraper"})

    def test_round_trip_keeps_everything(self):
        """읽고 그대로 다시 써도 정보가 하나도 사라지지 않아야 한다."""
        index = self.adapter.read_index(self.provider, self.layout)
        self.adapter.write_index(self.layout, list(index.values()))

        reread = self.adapter.read_index(self.provider, self.layout)
        self.assertEqual(reread["FFX.iso"].fields, index["FFX.iso"].fields)
        self.assertEqual(reread["FFX.iso"].frontend_raw, index["FFX.iso"].frontend_raw)

        root = ET.parse(self.layout.metadata_file).getroot()
        game = root.find("game")
        self.assertEqual(game.findtext("favorite"), "true")
        self.assertEqual(game.findtext("lastplayed"), "20240101T120000")
        self.assertEqual(game.get("source"), "ScreenScraper")
        # 우리가 해석하지 않는 최상위 요소도 남아 있어야 한다.
        self.assertIsNotNone(root.find("folder"), "<folder> 항목이 사라졌다")

    def test_write_is_indented_not_one_line(self):
        index = self.adapter.read_index(self.provider, self.layout)
        self.adapter.write_index(self.layout, list(index.values()))
        text = Path(self.layout.metadata_file).read_text(encoding="utf-8")
        self.assertGreater(len(text.splitlines()), 10, "한 줄로 기록되면 사람이 읽을 수 없다")
        self.assertIn("\n  <game>", text)

    def test_write_does_not_delete_entries_it_was_not_given(self):
        index = self.adapter.read_index(self.provider, self.layout)
        self.adapter.write_index(self.layout, [index["FFX.iso"]])
        self.assertIn("MGS2.iso", self.adapter.read_index(self.provider, self.layout))

    def test_media_index_can_be_narrowed_to_one_type(self):
        full = self.adapter.read_media_index(self.provider, self.layout)
        self.assertEqual({m.media_type for m in full["FFX"]}, {"covers", "videos"})

        covers_only = self.adapter.read_media_index(self.provider, self.layout, ["covers"])
        self.assertEqual({m.media_type for m in covers_only["FFX"]}, {"covers"})

    def test_broken_gamelist_does_not_raise(self):
        Path(self.layout.metadata_file).write_text("<gameList><game>", encoding="utf-8")
        self.assertEqual(self.adapter.read_index(self.provider, self.layout), {})


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.root = build_esde_tree(Path(tempfile.mkdtemp(prefix="rms_scan_")))
        self.cache_dir = Path(tempfile.mkdtemp(prefix="rms_scan_cache_"))
        self.cache = CacheStore.open_for_collection(self.cache_dir, "col-1")
        self.adapter = EsDeAdapter()
        self.provider = LocalStorageProvider()
        self.collection = make_collection(self.root)

    def tearDown(self):
        self.cache.close()

    def scan(self, **kwargs):
        return scan_collection(self.collection, self.cache, self.provider, self.adapter, **kwargs)

    def test_scan_populates_cache(self):
        result = self.scan()
        self.assertEqual(result["scanned"], 1)
        self.assertEqual(result["roms"], 2)

        rows = self.cache.query_rows()
        self.assertEqual([r["title"] for r in rows],
                         ["Final Fantasy X", "Metal Gear Solid 2", "ROM 없는 항목"])

    def test_metadata_only_entry_is_marked_absent(self):
        self.scan()
        rows = {r["filename"]: r for r in self.cache.query_rows()}
        self.assertEqual(rows["FFX.iso"]["present"], 1)
        # gamelist에는 있지만 물리 ROM이 없는 항목 - ES-DE에서 정상적인 상태다.
        self.assertEqual(rows["MetadataOnly.iso"]["present"], 0)

    def test_stats_count_missing_metadata_and_media(self):
        self.scan()
        stats = {s["system"]: s for s in self.cache.system_stats()}["ps2"]
        self.assertEqual(stats["rom_count"], 2)
        self.assertEqual(stats["rom_bytes"], 3000)
        self.assertEqual(stats["media_bytes"], 110)
        self.assertEqual(stats["missing_media"], 1)      # MGS2는 media가 없다
        self.assertEqual(stats["missing_metadata"], 0)

    def test_second_scan_skips_unchanged_system(self):
        self.scan()
        again = self.scan()
        self.assertEqual((again["scanned"], again["skipped"]), (0, 1))
        self.assertEqual(again["roms"], 2, "건너뛴 경우에도 개수는 그대로 보고해야 한다")

    def test_force_rescans_even_when_unchanged(self):
        self.scan()
        self.assertEqual(self.scan(force=True)["scanned"], 1)

    def test_new_rom_triggers_rescan(self):
        self.scan()
        (self.root / "ps2" / "NEW.iso").write_bytes(b"n" * 5)
        result = self.scan()
        self.assertEqual(result["scanned"], 1)
        self.assertIn("NEW.iso", {r["filename"] for r in self.cache.query_rows()})

    def test_partial_media_scan_does_not_satisfy_a_later_full_scan(self):
        """커버만 인덱싱한 캐시를 '이미 다 됐다'고 재사용하면 비디오를 영영 못 본다."""
        self.scan(media_types=["covers"])
        result = self.scan()
        self.assertEqual(result["scanned"], 1, "부분 스캔 캐시로 전체 스캔을 건너뛰면 안 된다")

        ffx = next(r for r in self.cache.query_rows() if r["filename"] == "FFX.iso")
        media = {m["media_type"] for m in self.cache.get_row(ffx["rom_uid"])["media"]}
        self.assertEqual(media, {"covers", "videos"})

    def test_partial_scan_keeps_previous_media_size(self):
        self.scan()
        self.scan(media_types=["covers"], force=True)
        stats = {s["system"]: s for s in self.cache.system_stats()}["ps2"]
        self.assertEqual(stats["media_bytes"], 110, "부분 스캔이 용량을 줄여버리면 안 된다")

    def test_removed_system_is_forgotten(self):
        self.scan()
        import shutil
        shutil.rmtree(self.root / "gamelists" / "ps2")
        shutil.rmtree(self.root / "downloaded_media" / "ps2")
        shutil.rmtree(self.root / "ps2")
        self.scan()
        self.assertEqual(self.cache.count_rows(), 0)

    def test_frontend_raw_survives_the_cache(self):
        self.scan()
        ffx = next(r for r in self.cache.query_rows() if r["filename"] == "FFX.iso")
        raw = self.cache.get_row(ffx["rom_uid"])["frontend_raw"]
        self.assertEqual({i["tag"] for i in raw["extra"]} & {"favorite", "playcount"},
                         {"favorite", "playcount"})


if __name__ == "__main__":
    unittest.main()
