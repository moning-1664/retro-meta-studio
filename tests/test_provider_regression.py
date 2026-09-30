"""Phase 8 Provider 도입이 기존 Adapter를 회귀시키지 않았는지 (Phase 7.11).

Phase 8.1은 Adapter의 직접 파일 접근(`ET.parse(path)`, `path.write_text()`)을
`read_document()`/`write_document()` → Provider로 옮겼다. MTP를 붙이려면 반드시
필요한 변경이지만, **모든 Adapter의 읽기/쓰기 경로를 한꺼번에 갈아끼운 변경**이라
Local filesystem에서의 기존 동작이 조용히 깨지기 쉽다.

ES-DE만 실제 자료로 검증했다고 나머지 셋이 안전하다고 볼 수 없다. 여기서는 네
Adapter 전부에 대해 같은 것을 본다.

    쓰기 -> 읽기 -> 고치기 -> 쓰기 -> 다시 읽기

그리고 **Provider가 실패할 때** Adapter가 그것을 삼키지 않는지도 본다 - MTP 기기는
작업 도중에 뽑힌다.
"""

import unittest
from pathlib import Path

import storage
import adapters.emulationstation   # noqa: F401  - Adapter 등록을 위한 import
import adapters.es_de              # noqa: F401
import adapters.launchbox          # noqa: F401
import adapters.pegasus            # noqa: F401
from adapters import available, get_adapter
from adapters.base import GameEntry
from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL
from storage.local import LocalStorageProvider
from tests.fixtures import temp_root
from tests.test_storage_provider import BlockingProvider, RecordingProvider

PROVIDER = LocalStorageProvider()

#: 모든 Frontend가 공통으로 다루는 필드만 쓴다. Frontend마다 지원 범위가 다르므로
#: (`supported_fields`) 여기서 전부를 기대하면 "지원하지 않는 것"과 "잃어버린 것"을
#: 구별할 수 없게 된다.
BASE_FIELDS = {"name": "Final Fantasy X", "genre": "RPG", "developer": "Square"}


class AdapterRoundTripCase:
    """네 Adapter에 똑같이 적용하는 검사. 이 클래스 자체는 실행되지 않는다."""

    frontend = None
    system = "ps2"
    filename = "FFX.iso"

    def setUp(self):
        self.dir = temp_root(f"rms_prov_{self.frontend}_")
        self.root = self.dir / "col"
        self.root.mkdir(parents=True)
        self.adapter = get_adapter(self.frontend)
        self.collection = Collection(
            id="c", name="c", frontend=self.frontend, root_path=str(self.root),
            storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "I", str(self.root))],
            systems=[SystemEntry(self.system, STORAGE_INTERNAL)])
        self.layout = self.adapter.layout(self.collection, self.system)
        (Path(self.layout.rom_dir)).mkdir(parents=True, exist_ok=True)
        (Path(self.layout.rom_dir) / self.filename).write_bytes(b"r" * 64)

    def _supported(self, fields):
        allowed = set(self.adapter.supported_fields)
        return {k: v for k, v in fields.items() if k in allowed}

    def _write(self, fields, raw=None):
        self.adapter.write_index(self.layout, [
            GameEntry(filename=self.filename, fields=dict(fields),
                      frontend_raw=self.adapter.tag_raw(raw) if raw else None)])

    def _read(self):
        index = self.adapter.read_index(PROVIDER, self.layout)
        self.assertIn(self.filename, index, f"{self.frontend}: 쓴 항목을 다시 못 읽는다")
        return index[self.filename]

    # --- 기본 왕복 ------------------------------------------------------
    def test_what_we_write_comes_back(self):
        self._write(BASE_FIELDS)
        got = self._read().fields
        for key, value in self._supported(BASE_FIELDS).items():
            self.assertEqual(got.get(key), value, f"{self.frontend}: {key}")

    def test_editing_one_field_leaves_the_others_alone(self):
        """사용자가 장르만 고쳤는데 개발사가 사라지면 안 된다."""
        self._write(BASE_FIELDS)
        entry = self._read()
        entry.fields["genre"] = "Action RPG"
        self.adapter.write_index(self.layout, [entry])

        got = self._read().fields
        self.assertEqual(got.get("genre"), "Action RPG")
        for key, value in self._supported(BASE_FIELDS).items():
            if key == "genre":
                continue
            self.assertEqual(got.get(key), value, f"{self.frontend}: {key}가 함께 바뀌었다")

    def test_a_second_save_is_stable(self):
        """같은 내용을 두 번 저장하면 두 번째에도 같아야 한다."""
        self._write(BASE_FIELDS)
        first = self._read()
        self.adapter.write_index(self.layout, [first])
        second = self._read()
        self.assertEqual(second.fields, first.fields, f"{self.frontend}: 저장할 때마다 달라진다")

    def test_the_file_is_written_through_the_provider(self):
        """Provider를 우회하면 MTP에서 아무것도 못 한다."""
        original = storage.for_path
        recorder = RecordingProvider()
        storage.for_path = lambda path, _p=recorder: _p
        try:
            self._write(BASE_FIELDS)
        finally:
            storage.for_path = original
        self.assertTrue(recorder.writes, f"{self.frontend}: Provider를 안 거쳤다")

    def test_a_dead_provider_writes_nothing_to_disk(self):
        """기기가 뽑힌 상태. 우회하는 코드가 있으면 여기서 파일이 생긴다."""
        original = storage.for_path
        storage.for_path = lambda path, _p=BlockingProvider(): _p
        try:
            with self.assertRaises(OSError):
                self._write(BASE_FIELDS)
        finally:
            storage.for_path = original
        self.assertFalse(Path(self.layout.metadata_file).exists(),
                         f"{self.frontend}: Provider를 우회해 디스크에 썼다")

    def test_a_dead_provider_reads_as_empty_not_as_a_crash(self):
        """gamelist 하나를 못 읽는다고 스캔 전체가 죽으면 안 된다."""
        self._write(BASE_FIELDS)
        self.assertEqual(self.adapter.read_index(BlockingProvider(), self.layout), {},
                         f"{self.frontend}: 못 읽을 때 빈 결과를 안 준다")


def _case(frontend, name):
    return type(name, (AdapterRoundTripCase, unittest.TestCase), {"frontend": frontend})


EsDeRoundTripTests = _case("es-de", "EsDeRoundTripTests")
PegasusRoundTripTests = _case("pegasus", "PegasusRoundTripTests")
LaunchBoxRoundTripTests = _case("launchbox", "LaunchBoxRoundTripTests")
EmulationStationRoundTripTests = _case("emulationstation", "EmulationStationRoundTripTests")


class EveryAdapterIsCoveredTests(unittest.TestCase):
    """Adapter를 새로 추가하고 이 파일에 넣는 것을 잊으면 여기서 걸린다."""

    def test_no_adapter_is_missing_a_round_trip_case(self):
        covered = {cls.frontend for cls in (EsDeRoundTripTests, PegasusRoundTripTests,
                                            LaunchBoxRoundTripTests,
                                            EmulationStationRoundTripTests)}
        self.assertEqual({a.id for a in available()}, covered,
                         "Provider 왕복 검사가 없는 Adapter가 있다")


class UnknownFieldsSurviveTests(unittest.TestCase):
    """Phase 7.9가 지킨 것 - 모르는 값을 버리지 않는다 - 이 그대로인지.

    Provider로 옮기면서 가장 깨지기 쉬운 부분이다. ES-DE는 실제 자료로 확인했지만
    Pegasus는 형식 자체가 달라(키:값 텍스트) 따로 봐야 한다.
    """

    def _entry_after_round_trip(self, frontend, raw):
        dirpath = temp_root(f"rms_raw_{frontend}_")
        root = dirpath / "col"
        root.mkdir(parents=True)
        adapter = get_adapter(frontend)
        collection = Collection(
            id="c", name="c", frontend=frontend, root_path=str(root),
            storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "I", str(root))],
            systems=[SystemEntry("ps2", STORAGE_INTERNAL)])
        layout = adapter.layout(collection, "ps2")
        Path(layout.rom_dir).mkdir(parents=True, exist_ok=True)
        (Path(layout.rom_dir) / "FFX.iso").write_bytes(b"r" * 8)

        adapter.write_index(layout, [GameEntry(filename="FFX.iso", fields=dict(BASE_FIELDS),
                                               frontend_raw=adapter.tag_raw(raw))])
        first = adapter.read_index(PROVIDER, layout)["FFX.iso"]
        adapter.write_index(layout, [first])          # 한 번 더 - 두 번째에 사라지는 일이 잦다
        return adapter.read_index(PROVIDER, layout)["FFX.iso"]

    def test_es_de_keeps_unknown_tags(self):
        raw = {"extra": [{"tag": "playcount", "text": "17", "attrib": {}}]}
        entry = self._entry_after_round_trip("es-de", raw)
        tags = {e["tag"]: e["text"] for e in (entry.frontend_raw or {}).get("extra", [])}
        self.assertEqual(tags.get("playcount"), "17", "모르는 태그가 사라졌다")

    def test_pegasus_keeps_unknown_keys(self):
        raw = {"extra": [{"key": "x-launch", "value": "retroarch"}]}
        entry = self._entry_after_round_trip("pegasus", raw)
        keys = {e["key"]: e["value"] for e in (entry.frontend_raw or {}).get("extra", [])}
        self.assertEqual(keys.get("x-launch"), "retroarch", "모르는 키가 사라졌다")


if __name__ == "__main__":
    unittest.main()
