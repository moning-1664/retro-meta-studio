"""ES-DE 외 Frontend와의 실제 호환성.

`test_adapters.py`는 "우리 모델이 정보를 잃지 않는가"를 본다. 그건 **우리끼리의
왕복**이라 통과해도 실제 Frontend가 그 결과를 읽어준다는 보장이 없다. 대표적인 예가
LaunchBox media 파일명이다 - 쓰기는 ROM stem으로 하는데 읽기는 제목을 stem으로
되돌리는 fallback이 있어서, 우리끼리 import->export->import를 돌리면 완벽히 맞아
떨어지고 **LaunchBox 안에서만 커버가 안 보인다.**

그래서 이 파일은 "우리 왕복이 맞는가"가 아니라 **"각 Frontend의 공식 포맷 규칙에
맞는가"**를 직접 본다. 기준은 각 Frontend의 포맷 문서다.

## 아직 못 고친 것은 expectedFailure로 남긴다

현재 코드가 지원하지 않는다는 것을 알면서 적은 것이 있다. 주석으로만 남기면 아무도
다시 읽지 않으므로 `@unittest.expectedFailure`로 박아 둔다. 고치는 순간
"unexpected success"가 되어 suite가 실패하고, 그때 데코레이터를 떼면 된다 - 고쳤는지
아닌지를 사람의 기억이 아니라 테스트가 판정한다.

실제로 그렇게 동작했다: Pegasus `assets.*`, `metadata.txt`, 원조 ES의 ROM 폴더
gamelist, LaunchBox media 파일명은 모두 여기 expectedFailure로 먼저 박혔다가
고쳐지면서 데코레이터를 뗀 것들이다. 지금 남은 것은 Pegasus multi-file game 하나다.
"""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.base import GameEntry, MediaFile
from adapters.emulationstation import EmulationStationAdapter
from adapters.es_de import EsDeAdapter   # noqa: F401 - import 시점에 register()된다
from adapters.launchbox import LaunchBoxAdapter
from adapters.pegasus import PegasusAdapter
from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL
from storage.local import LocalStorageProvider


def make_collection(root, frontend, system):
    return Collection(
        id="c1", name="c", frontend=frontend, root_path=str(root),
        storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "Internal", str(root))],
        systems=[SystemEntry(system=system, storage_id=STORAGE_INTERNAL)])


class FrontendCase(unittest.TestCase):
    frontend = ""
    system = ""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.provider = LocalStorageProvider()
        self.addCleanup(self._tmp.cleanup)

    def layout(self):
        return self.adapter.layout(make_collection(self.root, self.frontend, self.system),
                                   self.system)


# ----------------------------------------------------------------------
# LaunchBox
# ----------------------------------------------------------------------
class LaunchBoxCompatTest(FrontendCase):
    """LaunchBox의 media 파일명은 **제목** 기준이다(adapters/launchbox.py 참고).

    그래서 `Chrono Trigger (USA).sfc`의 커버는 `Chrono Trigger.jpg`로 저장돼야 한다.
    ROM 파일명과 제목이 다른 것이 LaunchBox에서는 예외가 아니라 기본이다 - 스크래퍼가
    지역/리비전 표기를 떼고 제목을 붙이기 때문이다.
    """

    frontend = "launchbox"
    system = "ps2"

    def setUp(self):
        super().setUp()
        self.adapter = LaunchBoxAdapter()
        platforms = self.root / "Data" / "Platforms"
        platforms.mkdir(parents=True)
        (platforms / "ps2.xml").write_text(
            '<?xml version="1.0"?>\n<LaunchBox>\n'
            '  <Game>\n'
            '    <ApplicationPath>Games\\ps2\\Final Fantasy X (USA).iso</ApplicationPath>\n'
            '    <Title>Final Fantasy X</Title>\n'
            '  </Game>\n'
            '</LaunchBox>\n', encoding="utf-8")
        self.rom = "Final Fantasy X (USA).iso"

    def test_제목과_다른_ROM명을_제대로_읽는다(self):
        entry = self.adapter.read_index(self.provider, self.layout())[self.rom]
        self.assertEqual(entry.fields["name"], "Final Fantasy X")

    def test_media는_ROM명이_아니라_제목으로_저장된다(self):
        """우리 read 쪽은 제목표에 없는 파일을 파일명 그대로 인덱싱하는 fallback이
        있어서, 쓰기가 ROM stem이어도 **왕복 테스트는 통과한다.** 깨지는 건
        LaunchBox 안에서뿐이다 - 그래서 왕복이 아니라 규칙을 직접 본다.
        """
        pairs = self.adapter.media_pairs(
            self.layout(), self.rom, [MediaFile(media_type="covers", path="/src/cover.jpg")],
            title="Final Fantasy X")
        self.assertEqual(Path(pairs[0][1]).name, "Final Fantasy X.jpg")

    def test_제목에_파일명_불가_문자가_있으면_LaunchBox처럼_치환한다(self):
        pairs = self.adapter.media_pairs(
            self.layout(), "rc3.iso", [MediaFile(media_type="covers", path="/src/c.png")],
            title="Ratchet & Clank: Up Your Arsenal")
        self.assertEqual(Path(pairs[0][1]).name, "Ratchet & Clank_ Up Your Arsenal.png")

    def test_제목을_모르면_ROM_stem으로_떨어진다(self):
        """제목이 비어 있을 때 빈 파일명을 만들면 안 된다."""
        for title in (None, "", "   "):
            pairs = self.adapter.media_pairs(
                self.layout(), self.rom, [MediaFile(media_type="covers", path="/src/c.jpg")],
                title=title)
            self.assertEqual(Path(pairs[0][1]).name, "Final Fantasy X (USA).jpg")

    def test_쓴_파일명을_우리가_다시_읽어낸다(self):
        """쓰기 규칙과 읽기 규칙이 같은 이름을 가리키는지. 여기가 어긋난 것이
        원래 버그였다."""
        title = "Final Fantasy X"
        pairs = self.adapter.media_pairs(
            self.layout(), self.rom, [MediaFile(media_type="covers", path="/src/c.png")],
            title=title)
        dest = Path(pairs[0][1])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"PNG")
        index = self.adapter.read_media_index(self.provider, self.layout())
        self.assertIn("covers", [m.media_type for m in index[Path(self.rom).stem]])

    def test_다른_Collection으로_옮기면_ApplicationPath를_새로_계산한다(self):
        """원본의 `<ApplicationPath>`는 **그 라이브러리 안에서만 참인 경로**다.

        그대로 따라가면 target의 LaunchBox가 source의 드라이브를 가리켜, 사용자가
        게임을 눌렀을 때 실행이 실패한다. 원조 ES의 media 경로와 같은 성격이라
        같은 훅(`strip_location_raw`)으로 처리한다.
        """
        source_raw = {"applicationPath": "D:\\LaunchBox\\Games\\PS2\\FFX.iso",
                      "_frontend": "launchbox"}
        preserved = self.adapter.strip_location_raw(source_raw)
        self.assertNotIn("applicationPath", preserved)

        game = ET.Element("Game")
        layout = self.layout()
        self.adapter.from_common(
            game, GameEntry(filename="FFX.iso", fields={"name": "FFX"},
                            frontend_raw=preserved), layout)
        written = game.findtext("ApplicationPath")
        self.assertNotIn("D:\\LaunchBox", written)
        self.assertEqual(Path(written.replace("\\", "/")).name, "FFX.iso")

    def test_같은_Collection_안에서는_원본_경로를_그대로_지킨다(self):
        """`strip_location_raw()`는 **옮길 때만** 부른다(applier).

        같은 자리에 다시 쓸 때는 사용자가 설정해 둔 상대/절대 경로 표기가 그대로
        남아야 한다 - 우리가 계산한 경로로 덮어쓰면 사용자의 라이브러리 설정이 바뀐다.
        """
        entry = self.adapter.read_index(self.provider, self.layout())[self.rom]
        game = ET.Element("Game")
        self.adapter.from_common(game, entry, self.layout())
        self.assertEqual(game.findtext("ApplicationPath"),
                         "Games\\ps2\\Final Fantasy X (USA).iso")


# ----------------------------------------------------------------------
# Pegasus
# ----------------------------------------------------------------------
class PegasusCompatTest(FrontendCase):
    frontend = "pegasus"
    system = "nes"

    def setUp(self):
        super().setUp()
        self.adapter = PegasusAdapter()
        self.system_dir = self.root / self.system
        self.system_dir.mkdir(parents=True)

    def write_metadata(self, text, filename="metadata.pegasus.txt"):
        (self.system_dir / filename).write_text(text, encoding="utf-8")

    def test_rating은_Pegasus의_퍼센트_표기로_쓴다(self):
        """공통 모델의 rating은 5점 만점이고(ES-DE의 0~1을 ×5한 값),
        Pegasus 공식 포맷의 rating은 **퍼센트**다.

        변환 없이 그대로 적으면 ES-DE의 별 4.5개가 Pegasus에서 `4.5`가 되어,
        평점이 조용히 다른 값이 된다 - Convert에서 값이 틀리는데 오류는 안 나는
        종류라 눈으로는 오래 못 잡는다.
        """
        self.write_metadata("collection: NES\n")
        self.adapter.write_index(self.layout(), [
            GameEntry(filename="a.nes", fields={"name": "A", "rating": "4.5"})])
        text = (self.system_dir / "metadata.pegasus.txt").read_text(encoding="utf-8")
        self.assertIn("rating: 90%", text)

    def test_퍼센트로_적힌_rating을_5점_만점으로_읽는다(self):
        self.write_metadata("collection: NES\n\ngame: A\nfile: a.nes\nrating: 90%\n")
        entry = self.adapter.read_index(self.provider, self.layout())["a.nes"]
        self.assertEqual(entry.fields["rating"], "4.5")

    def test_rating_왕복은_5점_만점의_해상도까지만_정확하다(self):
        """퍼센트(101단계)가 5점 만점 소수 한 자리(51단계)보다 촘촘해서, 홀수 퍼센트는
        왕복에서 1% 밀린다(75% -> 3.8 -> 76%).

        공통 모델의 rating 해상도는 ES-DE의 `normalize_esde_rating()`이 정한 것이고,
        Pegasus만 더 정밀하게 담으면 같은 별점이 Frontend마다 다르게 보인다. 그래서
        해상도를 맞추는 쪽을 택했다 - 대신 **그 오차가 누적되지는 않는다**는 것을
        여기서 못박는다. 한 번 밀린 뒤로는 몇 번을 왕복해도 같은 값이어야 한다.
        """
        self.write_metadata("collection: NES\n\ngame: A\nfile: a.nes\nrating: 75%\n")
        entry = self.adapter.read_index(self.provider, self.layout())["a.nes"]
        self.assertEqual(entry.fields["rating"], "3.8")

        self.adapter.write_index(self.layout(), [entry])
        text = (self.system_dir / "metadata.pegasus.txt").read_text(encoding="utf-8")
        self.assertIn("rating: 76%", text)

        for _ in range(3):
            entry = self.adapter.read_index(self.provider, self.layout())["a.nes"]
            self.assertEqual(entry.fields["rating"], "3.8")
            self.adapter.write_index(self.layout(), [entry])
        text = (self.system_dir / "metadata.pegasus.txt").read_text(encoding="utf-8")
        self.assertIn("rating: 76%", text)

    def test_정확히_표현되는_값은_왕복에서_그대로다(self):
        self.write_metadata("collection: NES\n\ngame: A\nfile: a.nes\nrating: 90%\n")
        entry = self.adapter.read_index(self.provider, self.layout())["a.nes"]
        self.assertEqual(entry.fields["rating"], "4.5")
        self.adapter.write_index(self.layout(), [entry])
        self.assertIn("rating: 90%",
                      (self.system_dir / "metadata.pegasus.txt").read_text(encoding="utf-8"))

    def test_metadata_txt라는_이름도_인식한다(self):
        """Pegasus 공식 포맷은 `metadata.pegasus.txt`와 `metadata.txt`를
        모두 허용한다. 후자만 있는 라이브러리를 못 읽으면 Collection 추가 자체가 막힌다."""
        (self.system_dir / "a.nes").write_bytes(b"ROM")
        self.write_metadata("collection: NES\n\ngame: A\nfile: a.nes\n", "metadata.txt")
        self.assertGreater(self.adapter.detect(self.provider, self.root).confidence, 0)
        self.assertIn("a.nes", self.adapter.read_index(self.provider, self.layout()))

    def test_assets_키가_가리키는_media를_찾는다(self):
        """Pegasus는 `media/<game>/boxFront.png` 폴더 규칙 외에
        메타데이터 안의 `assets.box_front:` 키로 경로를 직접 지정할 수 있다.
        폴더 규칙만 훑으면 이렇게 지정된 media를 통째로 놓친다.
        """
        (self.system_dir / "assets").mkdir()
        (self.system_dir / "assets" / "Mario.png").write_bytes(b"PNG")
        self.write_metadata("collection: NES\n\ngame: Mario\nfile: a.nes\n"
                            "assets.box_front: assets/Mario.png\n")
        index = self.adapter.read_media_index(self.provider, self.layout())
        self.assertEqual([m.media_type for m in index["a"]], ["covers"])

    @unittest.expectedFailure
    def test_multi_file_game을_읽는다(self):
        """**현재 미지원.** Pegasus는 `files:`로 한 게임에 여러 ROM을 묶을 수 있다.
        공통 모델의 GameEntry는 `filename` 하나를 중심으로 돌기 때문에 이 블록은
        read에서 통째로 누락된다(아래 보존 테스트 참고 - 사라지지는 않는다)."""
        self.write_metadata("collection: PS1\n\ngame: Final Fantasy VII\n"
                            "files:\n  disc1.iso\n  disc2.iso\ndeveloper: Square\n")
        index = self.adapter.read_index(self.provider, self.layout())
        self.assertEqual(len(index), 1)

    def test_읽지_못하는_multi_file_블록도_Export에서_파괴하지_않는다(self):
        """읽지 못하는 것과 지우는 것은 전혀 다른 문제다.

        `write_index()`가 기존 파일을 다시 읽어 해당 블록만 갈아끼우는 덕분에,
        우리가 해석하지 못한 `files:` 블록은 그대로 남는다. 이게 보장되지 않으면
        "multi-file 미지원"은 P2가 아니라 데이터 파괴 버그가 된다.
        """
        self.write_metadata(
            "collection: PS1\n\ngame: Final Fantasy VII\n"
            "files:\n  disc1.iso\n  disc2.iso\ndeveloper: Square\n\n"
            "game: Normal\nfile: normal.iso\n")
        self.adapter.write_index(self.layout(), [
            GameEntry(filename="normal.iso", fields={"name": "Normal EDITED"})])
        text = (self.system_dir / "metadata.pegasus.txt").read_text(encoding="utf-8")
        self.assertIn("disc1.iso", text)
        self.assertIn("disc2.iso", text)
        self.assertIn("Normal EDITED", text)


# ----------------------------------------------------------------------
# EmulationStation
# ----------------------------------------------------------------------
class EmulationStationCompatTest(FrontendCase):
    """원조 ES는 gamelist.xml을 **두 자리**에서 찾는다.

    1. `<system ROM 폴더>/gamelist.xml`   (Batocera 등이 쓰는 배치)
    2. `<root>/gamelists/<system>/gamelist.xml`

    지금 어댑터는 2번만 안다.
    """

    frontend = "emulationstation"
    system = "ps2"

    def setUp(self):
        super().setUp()
        self.adapter = EmulationStationAdapter()

    def _rom_folder_layout(self):
        system_dir = self.root / self.system
        system_dir.mkdir(parents=True)
        (system_dir / "FFX.iso").write_bytes(b"ROM")
        (system_dir / "gamelist.xml").write_text(
            '<?xml version="1.0"?><gameList><game><path>./FFX.iso</path>'
            '<name>Final Fantasy X</name></game></gameList>', encoding="utf-8")

    def _central_layout(self):
        gamelists = self.root / "gamelists" / self.system
        gamelists.mkdir(parents=True)
        (self.root / self.system).mkdir(parents=True)
        (self.root / self.system / "FFX.iso").write_bytes(b"ROM")
        (gamelists / "gamelist.xml").write_text(
            '<?xml version="1.0"?><gameList><game><path>./FFX.iso</path>'
            '<name>Final Fantasy X</name></game></gameList>', encoding="utf-8")

    def test_중앙_gamelists_배치를_인식한다(self):
        self._central_layout()
        self.assertGreater(self.adapter.detect(self.provider, self.root).confidence, 0)
        index = self.adapter.read_index(self.provider, self.layout())
        self.assertEqual(index["FFX.iso"].fields["name"], "Final Fantasy X")

    def test_ROM_폴더_안의_gamelist를_인식한다(self):
        """Batocera 계열이 쓰는 배치라 드문 구성이 아니다. `gamelists/` 하나만 보면
        이런 라이브러리는 Collection 추가 자체가 막힌다.

        어느 배치인지는 **파일이 실제로 있는 자리**가 정한다 - `layout()`이 후보를
        훑어서 `metadata_file`을 확정하므로, 스캐너의 변경 감지도 같은 파일을 본다.
        """
        self._rom_folder_layout()
        detection = self.adapter.detect(self.provider, self.root)
        self.assertGreater(detection.confidence, 0)
        self.assertIn(self.system, detection.systems)

        layout = self.layout()
        self.assertEqual(Path(layout.metadata_file),
                         self.root / self.system / "gamelist.xml")
        index = self.adapter.read_index(self.provider, layout)
        self.assertEqual(index["FFX.iso"].fields["name"], "Final Fantasy X")

    def test_중앙_배치가_있으면_그쪽을_쓴다(self):
        """둘 다 있을 때 어느 쪽을 보는지 못박는다 - 조용히 바뀌면 사용자가 편집한
        내용이 안 보이는 파일에 적히게 된다."""
        self._central_layout()
        (self.root / self.system / "gamelist.xml").write_text(
            '<?xml version="1.0"?><gameList></gameList>', encoding="utf-8")
        self.assertEqual(Path(self.layout().metadata_file),
                         self.root / "gamelists" / self.system / "gamelist.xml")

    def test_아무것도_없으면_중앙_배치에_새로_만든다(self):
        (self.root / self.system).mkdir(parents=True)
        self.assertEqual(Path(self.layout().metadata_file),
                         self.root / "gamelists" / self.system / "gamelist.xml")

    def test_metadata_path를_직접_주면_ROM_폴더_gamelist도_읽는다(self):
        """자동 탐색은 없지만 경로를 알려주면 읽기 자체는 된다.

        고칠 자리가 `layout()`이 아니라 **detect/scan**임을 보여주는 테스트다 -
        `layout(collection, system)`은 provider를 받지 않아서 그 안에서 파일이
        있는지 찾아볼 수 없다. 탐색은 provider를 가진 쪽이 하고, 결과를
        `SystemEntry.metadata_path`에 적어 두는 것이 맞다.
        """
        self._rom_folder_layout()
        collection = make_collection(self.root, self.frontend, self.system)
        collection.systems[0].metadata_path = str(self.root / self.system / "gamelist.xml")
        layout = self.adapter.layout(collection, self.system)
        index = self.adapter.read_index(self.provider, layout)
        self.assertEqual(index["FFX.iso"].fields["name"], "Final Fantasy X")


# ----------------------------------------------------------------------
# Test Pack
# ----------------------------------------------------------------------
class TestPackTest(unittest.TestCase):
    """`tools/make_test_pack.py`가 만든 팩이 실제로 유효한지.

    실기 검증(Frontend를 직접 물려 보는 것)은 자동화할 수 없지만, **팩 자체가
    망가진 상태로 실기에 나가는 것**은 막을 수 있다. 팩이 틀리면 사람이 없는 버그를
    쫓게 되고, 그게 실기 검증에서 제일 비싼 실패다.

    어댑터 기본 경로가 바뀌면 팩의 폴더 배치도 같이 바뀌어야 하는데, 이 테스트가
    없으면 그 어긋남이 다음 실기 검증 때까지 드러나지 않는다.
    """

    @classmethod
    def setUpClass(cls):
        from tools.make_test_pack import BUILDERS
        cls.builders = BUILDERS
        cls._tmp = tempfile.TemporaryDirectory()
        cls.pack = Path(cls._tmp.name)
        for name, build in BUILDERS.items():
            target = cls.pack / name
            target.mkdir(parents=True)
            build(target)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _read(self, pack_name, frontend, system):
        from adapters.base import get_adapter
        root = self.pack / pack_name
        adapter = get_adapter(frontend)
        collection = make_collection(root, frontend, system)
        layout = adapter.layout(collection, system)
        provider = LocalStorageProvider()
        return adapter, layout, provider, adapter.read_index(provider, layout)

    def test_es_de_팩이_읽힌다(self):
        adapter, layout, provider, index = self._read("es-de", "es-de", "snes")
        self.assertGreater(adapter.detect(provider, self.pack / "es-de").confidence, 0)
        # ROM이 어댑터의 기본 rom_dir에 놓여야 한다 - 여기가 어긋나면 팩은 멀쩡해
        # 보이는데 앱에서는 "메타데이터만 있는 항목"이 잔뜩 뜬다.
        self.assertGreater(len(adapter.list_roms(provider, layout)), 0)
        self.assertEqual(index["Chrono Trigger (USA) (Rev 1).sfc"].fields["name"],
                         "Chrono Trigger")

    def test_launchbox_팩은_media를_제목으로_저장한다(self):
        """팩은 **LaunchBox의 규칙대로** 만들어져 있어야 한다(우리 쓰기 버그와 무관하게).

        그래야 "우리가 읽을 수 있는가"와 "우리가 쓴 것이 맞는가"를 분리해서 볼 수 있다.
        """
        adapter, layout, provider, index = self._read(
            "launchbox", "launchbox", "Super Nintendo Entertainment System")
        cover = (self.pack / "launchbox" / "Images"
                 / "Super Nintendo Entertainment System" / "Box - Front"
                 / "Chrono Trigger.png")
        self.assertTrue(cover.exists(), "LaunchBox media는 제목 기준 파일명이어야 한다")
        media = adapter.read_media_index(provider, layout)
        self.assertIn("covers",
                      [m.media_type for m in media["Chrono Trigger (USA) (Rev 1)"]])

    def test_pegasus_팩이_읽힌다(self):
        adapter, layout, provider, index = self._read("pegasus", "pegasus", "snes")
        self.assertEqual(index["슈퍼 마리오 월드 (K).sfc"].fields["name"], "슈퍼 마리오 월드")
        # rating은 퍼센트로 적혀 있고 5점 만점으로 읽혀야 한다.
        self.assertEqual(index["Chrono Trigger (USA) (Rev 1).sfc"].fields["rating"], "5.0")

    def test_ROM_폴더_배치_팩도_읽힌다(self):
        """`emulationstation-romfolder/`는 gamelist.xml이 ROM 폴더 안에 있다.

        예전엔 이 팩이 "재현용 한계"였다 - Collection 추가 자체가 막혔다. 지금은
        읽혀야 하고, 그게 어긋나면 팩이든 어댑터든 한쪽이 퇴행한 것이다.
        """
        adapter, layout, provider, index = self._read(
            "emulationstation-romfolder", "emulationstation", "snes")
        self.assertGreater(
            adapter.detect(provider, self.pack / "emulationstation-romfolder").confidence, 0)
        self.assertEqual(Path(layout.metadata_file).parent.name, "snes")
        self.assertEqual(index["Chrono Trigger (USA) (Rev 1).sfc"].fields["name"],
                         "Chrono Trigger")

    def test_emulationstation_팩은_gamelist가_media_경로를_가진다(self):
        adapter, layout, provider, index = self._read(
            "emulationstation", "emulationstation", "snes")
        media = adapter.read_media_index(provider, layout)
        self.assertIn("covers", [m.media_type for m in media["Chrono Trigger (USA) (Rev 1)"]])

    def test_팩이_알려진_한계를_실제로_재현한다(self):
        """팩의 존재 이유의 절반은 **아직 못 고친 것을 재현하는 것**이다.

        어느 날 이 assert가 깨지면 둘 중 하나다 - 버그가 고쳐졌거나(좋다, 위쪽
        expectedFailure도 같이 깨졌을 것이다), 팩이 그 케이스를 잃어버렸거나(나쁘다).
        """
        # Pegasus multi-file 블록은 읽히지 않는다.
        _a, _l, _p, index = self._read("pegasus", "pegasus", "snes")
        self.assertNotIn("Multi Disc Disc 1.sfc", index)

    def test_체크리스트가_모든_케이스를_담는다(self):
        from tools.make_test_pack import CASES, write_checklist
        write_checklist(self.pack)
        text = (self.pack / "CHECKLIST.md").read_text(encoding="utf-8")
        for case in CASES:
            self.assertIn(case.key, text)


if __name__ == "__main__":
    unittest.main()
