"""LaunchBox / EmulationStation Adapter와 **Adapter 간 Round-trip** 검증.

스펙 §50-51이 요구하는 것은 "Frontend 간 변환에서 정보가 사라지지 않는 것"이다.
Adapter 하나씩만 테스트하면 각자 자기 형식을 잘 읽고 쓰는 것까지만 확인된다 -
정작 위험한 지점은 **한 Frontend에서 읽어 다른 Frontend로 쓰고 되돌아올 때**다.
그래서 이 파일에는 개별 Adapter 테스트와 함께 왕복 테스트를 둔다.
"""

import tempfile
import unittest
from pathlib import Path

from adapters.base import GameEntry, MediaFile
from adapters.emulationstation import EmulationStationAdapter
from adapters.es_de import EsDeAdapter
from adapters.launchbox import LaunchBoxAdapter, title_to_filename
from adapters.pegasus import PegasusAdapter
from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL
from storage.local import LocalStorageProvider

PLATFORM_XML = """<?xml version="1.0"?>
<LaunchBox>
  <Game>
    <ID>{11111111-1111-1111-1111-111111111111}</ID>
    <ApplicationPath>Games\\ps2\\FFX.iso</ApplicationPath>
    <Title>Final Fantasy X</Title>
    <Notes>A role-playing game.</Notes>
    <Genre>RPG</Genre>
    <Developer>Square</Developer>
    <Publisher>Square Enix</Publisher>
    <ReleaseDate>2001-07-19T00:00:00</ReleaseDate>
    <MaxPlayers>1</MaxPlayers>
    <CommunityStarRating>4.5</CommunityStarRating>
    <PlayCount>17</PlayCount>
    <Favorite>true</Favorite>
    <Emulator>PCSX2</Emulator>
  </Game>
  <Game>
    <ApplicationPath>Games\\ps2\\MGS2.iso</ApplicationPath>
    <Title>Metal Gear Solid 2</Title>
  </Game>
</LaunchBox>
"""

ES_GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game>
    <path>./FFX.iso</path>
    <name>Final Fantasy X</name>
    <desc>A role-playing game.</desc>
    <genre>RPG</genre>
    <developer>Square</developer>
    <releasedate>20010719T000000</releasedate>
    <rating>0.9</rating>
    <image>./media/FFX-image.png</image>
    <video>./media/FFX-video.mp4</video>
    <favorite>true</favorite>
    <playcount>17</playcount>
  </game>
</gameList>
"""


def make_collection(root, frontend):
    return Collection(
        id="col-1", name="Test", frontend=frontend, root_path=str(root),
        storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "Internal", str(root))],
        systems=[SystemEntry("ps2", STORAGE_INTERNAL)],
    )


class LaunchBoxTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rms_lb_"))
        (self.root / "Data" / "Platforms").mkdir(parents=True)
        (self.root / "Data" / "Platforms" / "ps2.xml").write_text(PLATFORM_XML, encoding="utf-8")
        (self.root / "Games" / "ps2").mkdir(parents=True)
        (self.root / "Games" / "ps2" / "FFX.iso").write_bytes(b"r" * 100)
        images = self.root / "Images" / "ps2"
        (images / "Box - Front").mkdir(parents=True)
        # LaunchBox의 media 파일명은 **제목** 기준이다.
        (images / "Box - Front" / "Final Fantasy X.jpg").write_bytes(b"c" * 10)
        (images / "Screenshot - Gameplay").mkdir(parents=True)
        (images / "Screenshot - Gameplay" / "FFX.png").write_bytes(b"s" * 10)

        self.adapter = LaunchBoxAdapter()
        self.provider = LocalStorageProvider()
        self.layout = self.adapter.layout(make_collection(self.root, "launchbox"), "ps2")

    def test_detect_reads_platform_xmls(self):
        detection = self.adapter.detect(self.provider, self.root)
        self.assertTrue(detection.matched)
        self.assertEqual(detection.systems, ("ps2",))

    def test_read_index_maps_launchbox_tags(self):
        entry = self.adapter.read_index(self.provider, self.layout)["FFX.iso"]
        self.assertEqual(entry.fields["name"], "Final Fantasy X")
        self.assertEqual(entry.fields["desc"], "A role-playing game.")
        self.assertEqual(entry.fields["players"], "1")
        self.assertEqual(entry.fields["releasedate"], "2001-07-19",
                         "ISO 시각에서 날짜만 남겨야 한다")

    def test_unknown_tags_are_preserved(self):
        entry = self.adapter.read_index(self.provider, self.layout)["FFX.iso"]
        extra = {item["tag"]: item["text"] for item in entry.frontend_raw["extra"]}
        self.assertEqual(extra["PlayCount"], "17")
        self.assertEqual(extra["Emulator"], "PCSX2")

    def test_media_named_after_the_title_still_finds_its_rom(self):
        """LaunchBox만의 함정 - media 파일명이 ROM이 아니라 제목을 따른다."""
        index = self.adapter.read_media_index(self.provider, self.layout)
        types = {m.media_type for m in index["FFX"]}
        self.assertEqual(types, {"covers", "screenshots"},
                         "제목으로 저장된 커버와 ROM 이름으로 저장된 스크린샷 둘 다 붙어야 한다")

    def test_title_to_filename_replaces_illegal_characters(self):
        self.assertEqual(title_to_filename("Ratchet & Clank: Up Your Arsenal"),
                         "Ratchet & Clank_ Up Your Arsenal")

    def test_writing_preserves_unknown_tags_and_paths(self):
        entry = self.adapter.read_index(self.provider, self.layout)["FFX.iso"]
        entry.fields["genre"] = "JRPG"
        self.adapter.write_index(self.layout, [entry])

        text = Path(self.layout.metadata_file).read_text(encoding="utf-8")
        self.assertIn("<PlayCount>17</PlayCount>", text)
        self.assertIn("<Emulator>PCSX2</Emulator>", text)
        self.assertIn("<Genre>JRPG</Genre>", text)
        self.assertIn(r"Games\ps2\FFX.iso", text, "원본 ApplicationPath가 유지돼야 한다")
        self.assertIn("<Game>", text.replace("</Game>", ""))
        self.assertIn("Metal Gear Solid 2", text, "다른 게임이 사라지면 안 된다")

    def test_release_date_round_trips(self):
        before = self.adapter.read_index(self.provider, self.layout)["FFX.iso"]
        self.adapter.write_index(self.layout, [before])
        after = self.adapter.read_index(self.provider, self.layout)["FFX.iso"]
        self.assertEqual(after.fields["releasedate"], "2001-07-19")

    def test_remove_entries_drops_only_the_named_game(self):
        self.adapter.remove_entries(self.layout, ["FFX.iso"])
        index = self.adapter.read_index(self.provider, self.layout)
        self.assertEqual(list(index), ["MGS2.iso"])


class EmulationStationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rms_es_"))
        gamelist_dir = self.root / "gamelists" / "ps2"
        gamelist_dir.mkdir(parents=True)
        (gamelist_dir / "gamelist.xml").write_text(ES_GAMELIST, encoding="utf-8")
        # media는 gamelist.xml이 가리키는 상대 경로에 있다.
        (gamelist_dir / "media").mkdir()
        (gamelist_dir / "media" / "FFX-image.png").write_bytes(b"i" * 10)
        (gamelist_dir / "media" / "FFX-video.mp4").write_bytes(b"v" * 20)
        (self.root / "ps2").mkdir()
        (self.root / "ps2" / "FFX.iso").write_bytes(b"r" * 100)

        self.adapter = EmulationStationAdapter()
        self.provider = LocalStorageProvider()
        self.layout = self.adapter.layout(make_collection(self.root, "emulationstation"), "ps2")

    def test_detect_lowers_confidence_when_it_might_be_es_de(self):
        """ES-DE도 gamelists를 쓴다 - 확신하면 사용자가 잘못된 Frontend로 열게 된다."""
        plain = self.adapter.detect(self.provider, self.root)
        self.assertGreater(plain.confidence, 0.5)

        (self.root / "downloaded_media").mkdir()
        ambiguous = self.adapter.detect(self.provider, self.root)
        self.assertLess(ambiguous.confidence, plain.confidence)
        self.assertIn("ES-DE", ambiguous.message)

    def test_media_comes_from_the_paths_in_the_gamelist(self):
        """폴더 규칙으로 찾으면 배포판마다 다른 위치의 media를 통째로 놓친다."""
        index = self.adapter.read_media_index(self.provider, self.layout)
        found = {m.media_type: m.path for m in index["FFX"]}
        self.assertEqual(set(found), {"screenshots", "videos"})
        self.assertTrue(Path(found["screenshots"]).exists())

    def test_media_entries_that_point_nowhere_are_skipped(self):
        (self.layout.metadata_file and None)
        Path(self.root / "gamelists" / "ps2" / "media" / "FFX-image.png").unlink()
        index = self.adapter.read_media_index(self.provider, self.layout)
        self.assertEqual({m.media_type for m in index["FFX"]}, {"videos"})

    def test_unknown_tags_are_preserved(self):
        entry = self.adapter.read_index(self.provider, self.layout)["FFX.iso"]
        extra = {item["tag"]: item["text"] for item in entry.frontend_raw["extra"]}
        self.assertEqual(extra["playcount"], "17")
        self.assertEqual(extra["favorite"], "true")
        self.assertIn("image", extra, "media 경로 태그도 보존해야 한다")

    def test_write_media_links_updates_the_gamelist(self):
        """파일만 복사하고 gamelist를 안 고치면 ES가 그 media를 못 찾는다."""
        dest = Path(self.layout.media_dir) / "FFX-thumbnail.png"
        self.adapter.write_media_links(self.layout, "FFX.iso", [("covers", str(dest))])
        text = Path(self.layout.metadata_file).read_text(encoding="utf-8")
        self.assertIn("<thumbnail>", text)

        index = self.adapter.read_index(self.provider, self.layout)
        extra = {item["tag"]: item["text"] for item in index["FFX.iso"].frontend_raw["extra"]}
        self.assertIn("thumbnail", extra)


class RoundTripTests(unittest.TestCase):
    """**Frontend 간 왕복**에서 공통 필드가 살아남는지 (§50-51).

    frontend_raw는 그 Frontend의 원본이므로 다른 Frontend로 건너갈 때 따라가지 않는다 -
    ES-DE의 `<playcount>`를 Pegasus 블록에 적을 수는 없다. 왕복에서 반드시 지켜야 하는
    것은 **공통 필드**이고, 원본 보존은 같은 Frontend로 돌아왔을 때의 이야기다.
    """

    def setUp(self):
        self.provider = LocalStorageProvider()
        self.dir = Path(tempfile.mkdtemp(prefix="rms_roundtrip_"))

    def _layout(self, adapter, frontend, name):
        root = self.dir / name
        root.mkdir(parents=True, exist_ok=True)
        return adapter.layout(make_collection(root, frontend), "ps2")

    def source_entry(self):
        return GameEntry(filename="FFX.iso", fields={
            "name": "Final Fantasy X", "desc": "A role-playing game.", "genre": "RPG",
            "developer": "Square", "publisher": "Square Enix",
            "releasedate": "2001-07-19", "region": "", "players": "1", "rating": "4.5",
        })

    def _round_trip(self, adapter, frontend, name, *, skip=()):
        """entry -> 파일로 쓰고 -> 다시 읽어 공통 필드가 같은지."""
        layout = self._layout(adapter, frontend, name)
        source = self.source_entry()
        adapter.write_index(layout, [source])
        back = adapter.read_index(self.provider, layout)["FFX.iso"]
        for key, value in source.fields.items():
            if key in skip:
                continue
            self.assertEqual(back.fields.get(key, ""), value,
                             f"{frontend}: {key}가 왕복에서 달라졌다")
        return back

    def test_es_de_round_trip(self):
        self._round_trip(EsDeAdapter(), "es-de", "esde")

    def test_pegasus_round_trip(self):
        # Pegasus 포맷에는 region이 없다 - 그 자리는 비어 돌아온다.
        self._round_trip(PegasusAdapter(), "pegasus", "pegasus", skip=("region",))

    def test_launchbox_round_trip(self):
        self._round_trip(LaunchBoxAdapter(), "launchbox", "launchbox")

    def test_emulationstation_round_trip(self):
        self._round_trip(EmulationStationAdapter(), "emulationstation", "es")

    def test_es_de_to_pegasus_to_es_de_keeps_common_fields(self):
        """스펙 §51이 예로 든 바로 그 경로."""
        es_de, pegasus = EsDeAdapter(), PegasusAdapter()
        es_layout = self._layout(es_de, "es-de", "chain_esde")
        pg_layout = self._layout(pegasus, "pegasus", "chain_pegasus")

        source = self.source_entry()
        es_de.write_index(es_layout, [source])
        from_es = es_de.read_index(self.provider, es_layout)["FFX.iso"]

        # ES-DE -> Pegasus (공통 모델만 건너간다)
        pegasus.write_index(pg_layout, [GameEntry(filename=from_es.filename,
                                                  fields=from_es.fields)])
        from_pegasus = pegasus.read_index(self.provider, pg_layout)["FFX.iso"]

        # Pegasus -> ES-DE
        es_de.write_index(es_layout, [GameEntry(filename=from_pegasus.filename,
                                                fields=from_pegasus.fields)])
        final = es_de.read_index(self.provider, es_layout)["FFX.iso"]

        for key in ("name", "desc", "genre", "developer", "publisher",
                    "releasedate", "players", "rating"):
            self.assertEqual(final.fields[key], source.fields[key],
                             f"ES-DE -> Pegasus -> ES-DE 왕복에서 {key}가 사라졌다")

    def test_frontend_raw_survives_a_same_frontend_round_trip(self):
        """다른 Frontend를 거치는 것과 달리, 제자리 왕복에서는 원본이 그대로여야 한다."""
        adapter = EsDeAdapter()
        layout = self._layout(adapter, "es-de", "raw")
        source = self.source_entry()
        source.frontend_raw = {"extra": [{"tag": "playcount", "text": "17", "attrib": {}},
                                         {"tag": "favorite", "text": "true", "attrib": {}}]}
        adapter.write_index(layout, [source])
        back = adapter.read_index(self.provider, layout)["FFX.iso"]
        extra = {item["tag"]: item["text"] for item in back.frontend_raw["extra"]}
        self.assertEqual(extra["playcount"], "17")
        self.assertEqual(extra["favorite"], "true")

    def test_every_adapter_keeps_the_filename_it_was_given(self):
        """파일명이 바뀌면 ROM과 메타데이터의 연결이 끊긴다."""
        cases = [(EsDeAdapter(), "es-de", "fn_esde"), (PegasusAdapter(), "pegasus", "fn_pegasus"),
                 (LaunchBoxAdapter(), "launchbox", "fn_lb"),
                 (EmulationStationAdapter(), "emulationstation", "fn_es")]
        for adapter, frontend, name in cases:
            layout = self._layout(adapter, frontend, name)
            adapter.write_index(layout, [self.source_entry()])
            index = adapter.read_index(self.provider, layout)
            self.assertEqual(list(index), ["FFX.iso"], frontend)


class MediaPairTests(unittest.TestCase):
    """각 Frontend의 media 배치 규칙."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_mediapair_"))

    def _layout(self, adapter, frontend):
        root = self.dir / frontend
        root.mkdir(parents=True, exist_ok=True)
        return adapter.layout(make_collection(root, frontend), "ps2")

    def test_each_frontend_places_media_its_own_way(self):
        media = [MediaFile(media_type="covers", path="/src/a.png")]
        es_de = EsDeAdapter()
        pegasus = PegasusAdapter()
        launchbox = LaunchBoxAdapter()
        es = EmulationStationAdapter()

        esde_dest = es_de.media_pairs(self._layout(es_de, "es-de"), "FFX.iso", media)[0][1]
        self.assertEqual(Path(esde_dest).name, "FFX.png")
        self.assertEqual(Path(esde_dest).parent.name, "covers")

        pg_dest = pegasus.media_pairs(self._layout(pegasus, "pegasus"), "FFX.iso", media)[0][1]
        self.assertEqual(Path(pg_dest).name, "boxFront.png")
        self.assertEqual(Path(pg_dest).parent.name, "FFX")

        lb_dest = launchbox.media_pairs(self._layout(launchbox, "launchbox"), "FFX.iso", media)[0][1]
        self.assertEqual(Path(lb_dest).parent.name, "Box - Front")

        es_dest = es.media_pairs(self._layout(es, "emulationstation"), "FFX.iso", media)[0][1]
        self.assertEqual(Path(es_dest).name, "FFX-thumbnail.png")


if __name__ == "__main__":
    unittest.main()
