"""StorageProvider 계약과, Adapter가 그것을 정말로 지나는지 (Phase 8.1).

**이 계층의 존재 이유는 MTP다.** 그런데 Adapter가 `ET.parse(path)`로 파일을 직접
열고 있으면 그 이음매는 있으나 마나다 - 경로가 없는 저장소에서는 Provider를 아무리
갈아 끼워도 Adapter가 먼저 실패한다.

그래서 여기서 두 가지를 본다.

1. **Provider가 계약대로 동작하는가** - 없는 파일에 예외를 던지지 않고, 반쯤 쓰다 만
   파일을 남기지 않는다.
2. **Adapter의 메타데이터 읽기/쓰기가 정말 Provider를 지나는가** - Provider를 가짜로
   바꿔치기했을 때 디스크에 아무 일도 일어나지 않아야 한다. 지나지 않는 코드가
   하나라도 남아 있으면 여기서 걸린다.
"""

import unittest
from pathlib import Path

import storage
from adapters.es_de import EsDeAdapter
from adapters.pegasus import PegasusAdapter
from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL
from storage.local import LocalStorageProvider
from storage.provider import StorageProvider
from tests.fixtures import temp_root


class LocalProviderContractTests(unittest.TestCase):
    def setUp(self):
        self.provider = LocalStorageProvider()
        self.dir = temp_root("rms_provider_")

    def test_reading_a_missing_file_is_none_not_an_exception(self):
        """파일 하나가 없다고 스캔 전체가 죽으면 안 된다."""
        self.assertIsNone(self.provider.read_bytes(self.dir / "없는파일.xml"))

    def test_reading_a_directory_is_none_too(self):
        self.assertIsNone(self.provider.read_bytes(self.dir))

    def test_write_creates_parent_directories(self):
        target = self.dir / "gamelists" / "snes" / "gamelist.xml"
        self.assertTrue(self.provider.write_bytes(target, b"<gameList/>"))
        self.assertEqual(target.read_bytes(), b"<gameList/>")

    def test_write_leaves_no_temporary_file_behind(self):
        """임시 파일이 남으면 다음 스캔에서 정체불명의 항목이 목록에 뜬다."""
        target = self.dir / "roms" / "gamelist.xml"
        self.provider.write_bytes(target, b"x")
        self.assertEqual([p.name for p in target.parent.iterdir()], ["gamelist.xml"])

    def test_a_failed_write_does_not_destroy_the_previous_file(self):
        """반쯤 쓰인 gamelist를 남기면 그 System의 메타데이터를 통째로 잃는다."""
        target = self.dir / "gamelist.xml"
        self.provider.write_bytes(target, b"<gameList>old</gameList>")

        # 디렉터리를 같은 이름으로 만들어 두면 바꿔치기가 실패한다.
        broken = self.dir / "sub"
        broken.mkdir()
        self.assertFalse(self.provider.write_bytes(broken, "새 내용".encode("utf-8")))
        self.assertEqual(target.read_bytes(), b"<gameList>old</gameList>")

    def test_the_write_is_read_back_by_the_same_provider(self):
        target = self.dir / "a.txt"
        self.provider.write_bytes(target, "한글".encode("utf-8"))
        self.assertEqual(self.provider.read_bytes(target).decode("utf-8"), "한글")

    def test_for_path_picks_a_provider_for_every_shape_of_path(self):
        for path in (r"C:\Games\ROMs", r"\\nas\share\roms", str(self.dir)):
            self.assertIsInstance(storage.for_path(path), StorageProvider, path)

    def test_unc_paths_do_not_trust_the_watcher(self):
        """SMB에서는 변경 알림이 유실된다 - 주기적 Validation Scan으로 대체해야 한다."""
        self.assertFalse(storage.for_path(r"\\nas\share\roms").supports_watch)
        self.assertTrue(storage.for_path(r"C:\roms").supports_watch)


class RecordingProvider(LocalStorageProvider):
    """실제로 동작하되 무엇이 자기를 지나갔는지 기록한다."""

    def __init__(self):
        super().__init__()
        self.reads, self.writes = [], []

    def read_bytes(self, path):
        self.reads.append(str(path))
        return super().read_bytes(path)

    def write_bytes(self, path, data):
        self.writes.append(str(path))
        return super().write_bytes(path, data)


class BlockingProvider(RecordingProvider):
    """아무것도 읽지 못하고 아무것도 쓰지 못하는 저장소.

    MTP 기기가 도중에 뽑힌 상태와 같다. Adapter가 Provider를 우회하고 있으면
    **디스크에는 파일이 생기고** 여기서 걸린다.
    """

    def read_bytes(self, path):
        self.reads.append(str(path))
        return None

    def write_bytes(self, path, data):
        self.writes.append(str(path))
        return False


class AdaptersGoThroughTheProviderTests(unittest.TestCase):
    """Adapter의 메타데이터 I/O가 Provider를 지나는지."""

    def setUp(self):
        self.dir = temp_root("rms_seam_")
        self._original = storage.for_path
        self.addCleanup(lambda: setattr(storage, "for_path", self._original))

    def _use(self, provider):
        storage.for_path = lambda path, _p=provider: _p
        return provider

    def _collection(self, root, frontend, system="snes"):
        return Collection(
            id="c", name="c", frontend=frontend, root_path=str(root),
            storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "I", str(root))],
            systems=[SystemEntry(system, STORAGE_INTERNAL)])

    def _es_de_layout(self, root):
        return EsDeAdapter().layout(self._collection(root, "es-de"), "snes")

    def test_writing_a_gamelist_goes_through_the_provider(self):
        root = self.dir / "esde"
        provider = self._use(RecordingProvider())
        layout = self._es_de_layout(root)

        from adapters.base import GameEntry
        EsDeAdapter().write_index(layout, [GameEntry(filename="Zelda.sfc",
                                                     fields={"name": "Zelda"})])
        self.assertEqual(provider.writes, [str(Path(layout.metadata_file))])

    def test_nothing_reaches_the_disk_when_the_provider_refuses(self):
        """기기가 뽑힌 상태. 우회하는 코드가 있으면 파일이 생겨 버린다."""
        root = self.dir / "gone"
        provider = self._use(BlockingProvider())
        layout = self._es_de_layout(root)

        from adapters.base import GameEntry
        with self.assertRaises(OSError):
            EsDeAdapter().write_index(layout, [GameEntry(filename="Zelda.sfc", fields={"name": "Z"})])

        self.assertTrue(provider.writes, "Provider를 아예 안 불렀다")
        self.assertFalse(Path(layout.metadata_file).exists(), "Provider를 우회해 디스크에 썼다")
        self.assertFalse(root.exists(), "Provider를 우회해 폴더까지 만들었다")

    def test_removing_entries_goes_through_the_provider_too(self):
        root = self.dir / "esde2"
        real = LocalStorageProvider()
        layout = self._es_de_layout(root)
        real.write_bytes(layout.metadata_file,
                         b'<?xml version="1.0"?>\n<gameList>\n'
                         b'  <game><path>./Zelda.sfc</path></game>\n</gameList>\n')

        provider = self._use(RecordingProvider())
        EsDeAdapter().remove_entries(layout, ["Zelda.sfc"])
        self.assertIn(str(Path(layout.metadata_file)), provider.writes)

    def test_pegasus_metadata_goes_through_the_provider(self):
        """XML이 아닌 Adapter도 같은 길을 지나야 한다."""
        root = self.dir / "pegasus"
        provider = self._use(BlockingProvider())
        layout = PegasusAdapter().layout(self._collection(root, "pegasus"), "snes")

        from adapters.base import GameEntry
        with self.assertRaises(OSError):
            PegasusAdapter().write_index(layout, [GameEntry(filename="Zelda.sfc",
                                                            fields={"name": "Zelda"})])
        self.assertTrue(provider.writes, "Provider를 아예 안 불렀다")
        self.assertFalse(Path(layout.metadata_file).exists(), "Provider를 우회해 디스크에 썼다")

    def test_reading_a_gamelist_goes_through_the_provider(self):
        root = self.dir / "esde3"
        layout = self._es_de_layout(root)
        LocalStorageProvider().write_bytes(
            layout.metadata_file,
            b'<?xml version="1.0"?>\n<gameList>\n'
            b'  <game><path>./Zelda.sfc</path><name>Zelda</name></game>\n</gameList>\n')

        provider = RecordingProvider()
        index = EsDeAdapter().read_index(provider, layout)
        self.assertEqual(index["Zelda.sfc"].fields["name"], "Zelda")
        self.assertIn(str(layout.metadata_file), provider.reads)


class NoDirectFileAccessInAdaptersTests(unittest.TestCase):
    """Adapter 소스에 직접 파일 접근이 다시 기어들어오지 않게 못을 박는다.

    위의 동적 테스트는 지금 있는 경로만 본다. 새 Adapter나 새 메서드가
    `ET.parse(path)`로 시작하면 그건 아무도 안 부르는 동안에는 통과한다.
    """

    #: 이 이름들이 Adapter 안에 있으면 Provider를 우회하는 것이다. `.write(`까지 막는
    #: 이유는 `ElementTree.write(path)`가 가장 흔한 우회 경로이기 때문이다. `.mkdir(`도
    #: 막는다 - 폴더를 직접 만드는 것 역시 경로 있는 저장소를 전제한다.
    FORBIDDEN = ("ET.parse(", ".write(", ".write_text(", ".read_text(",
                 ".write_bytes(", ".read_bytes(", ".mkdir(", "open(")

    def test_no_adapter_touches_the_filesystem_directly(self):
        offenders = []
        for path in sorted(Path("adapters").glob("*.py")):
            if path.name == "base.py":
                continue    # 문서 I/O를 모아 둔 곳이다 - 여기만 Provider를 부른다.
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#")[0]
                if any(bad in code for bad in self.FORBIDDEN):
                    offenders.append(f"{path.name}:{number} {line.strip()}")
        self.assertEqual(offenders, [], "Adapter가 Provider를 우회한다:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
