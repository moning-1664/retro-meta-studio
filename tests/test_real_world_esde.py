"""실제 ES-DE 백업에서 발견한 결함들 (Phase 7.7).

**합성 fixture로는 절대 나오지 않던 것들이다.** 사용자의 실제 ES-DE 3.1 백업
(27개 시스템, gamelist 26개, media 14,705개 / 13.87GB)을 스캔해 보고 찾았다.

실제 경로를 테스트가 직접 보게 하지는 않는다 - 182GB이고 그 PC에만 있으며, 쓰기
경로가 실수로 실제 자료를 건드리면 되돌릴 수 없다. 대신 **거기서 확인한 모양만**
작은 fixture로 옮겨 왔다.

| 결함 | 실제 영향 |
|---|---|
| `<alternativeEmulator>`가 `<gameList>` 앞에 형제로 온다 | 9개 시스템 488게임(32%) 유실 |
| 같은 media type 파일이 둘 (`.jpg` + `.png`) | UNIQUE 위반으로 **스캔이 죽어** 8개 시스템 미스캔 |
| 이스케이프 안 된 `&` | famicom 199게임 유실 |
| ES-DE 자체 폴더가 System으로 잡힘 | `controllers`/`screensavers`/`temp`가 빈 시스템으로 표시 |

고친 뒤 같은 자료에서 930개 → 1,546개가 됐다.
"""

import unittest
from pathlib import Path

from adapters.es_de import EsDeAdapter
from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL
from bridge.api import Api
from storage.local import LocalStorageProvider
from tests.fixtures import scan, temp_root, wait_idle

PROVIDER = LocalStorageProvider()

#: ES-DE 3.x가 실제로 만들어 내는 모양. 최상위 요소가 **둘**이라 엄밀히는 잘못된
#: XML이고 `ET.parse`가 "junk after document element"로 거절한다.
ALTERNATIVE_EMULATOR_GAMELIST = """<?xml version="1.0"?>
<alternativeEmulator>
\t<label>Snes9x 2010</label>
</alternativeEmulator>
<gameList>
\t<game>
\t\t<path>./Zelda.sfc</path>
\t\t<name>The Legend of Zelda</name>
\t\t<genre>Action</genre>
\t</game>
\t<game>
\t\t<path>./Mario.sfc</path>
\t\t<name>Super Mario World</name>
\t</game>
</gameList>
"""

#: 이스케이프하지 않은 `&`가 값 안에 그대로 있는 파일. 실제 famicom gamelist가 이랬다.
BARE_AMPERSAND_GAMELIST = """<?xml version="1.0"?>
<gameList>
\t<game>
\t\t<path>./Captain America.zip</path>
\t\t<name>캡틴 아메리카 & 어벤저스</name>
\t\t<desc>만다린은 아이언맨과 비전을 쓰러뜨렸습니다.</desc>
\t</game>
</gameList>
"""

#: 둘 다 있는 경우 - 실제로 이 조합이 한 파일에 함께 오기도 한다.
BOTH_PROBLEMS_GAMELIST = """<?xml version="1.0"?>
<alternativeEmulator>
\t<label>Nestopia</label>
</alternativeEmulator>
<gameList>
\t<game>
\t\t<path>./Rock & Roll.nes</path>
\t\t<name>Rock & Roll Racing</name>
\t</game>
</gameList>
"""


def es_de_tree(root: Path, system="sfc", gamelist=ALTERNATIVE_EMULATOR_GAMELIST,
               roms=("Zelda.sfc", "Mario.sfc")) -> Path:
    (root / "gamelists" / system).mkdir(parents=True)
    (root / "gamelists" / system / "gamelist.xml").write_text(gamelist, encoding="utf-8")
    (root / system).mkdir(parents=True, exist_ok=True)
    for name in roms:
        (root / system / name).write_bytes(b"r" * 128)
    (root / "downloaded_media" / system / "covers").mkdir(parents=True)
    return root


def make_collection(root, system="sfc"):
    return Collection(
        id="col-1", name="Test", frontend="es-de", root_path=str(root),
        storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "Internal", str(root))],
        systems=[SystemEntry(system, STORAGE_INTERNAL)],
    )


class MalformedGamelistTests(unittest.TestCase):
    """실제 ES-DE가 만들어 내는 "잘못된" XML을 읽어낸다."""

    def setUp(self):
        self.adapter = EsDeAdapter()
        self.dir = temp_root("rms_realxml_")
        self._case = 0

    def _index(self, gamelist, system="sfc", roms=("Zelda.sfc", "Mario.sfc")):
        self._case += 1
        root = es_de_tree(self.dir / f"case{self._case}",
                          system=system, gamelist=gamelist, roms=roms)
        layout = self.adapter.layout(make_collection(root, system), system)
        return self.adapter.read_index(PROVIDER, layout)

    def test_alternative_emulator_before_gamelist_is_read(self):
        """ES-DE 3.x의 실제 출력. 이걸 못 읽으면 그 System의 메타데이터가 통째로 사라진다."""
        index = self._index(ALTERNATIVE_EMULATOR_GAMELIST)
        self.assertEqual(sorted(index), ["Mario.sfc", "Zelda.sfc"])
        self.assertEqual(index["Zelda.sfc"].fields["name"], "The Legend of Zelda")
        self.assertEqual(index["Zelda.sfc"].fields["genre"], "Action")

    def test_bare_ampersand_is_repaired(self):
        """`<name>캡틴 아메리카 & 어벤저스</name>` - 진짜로 깨진 XML이다.

        한 글자 때문에 그 System의 199개 항목을 통째로 버리는 것이 더 나쁘다.
        """
        index = self._index(BARE_AMPERSAND_GAMELIST, system="famicom",
                            roms=("Captain America.zip",))
        self.assertEqual(list(index), ["Captain America.zip"])
        self.assertEqual(index["Captain America.zip"].fields["name"], "캡틴 아메리카 & 어벤저스")

    def test_both_problems_at_once(self):
        index = self._index(BOTH_PROBLEMS_GAMELIST, system="nes", roms=("Rock & Roll.nes",))
        self.assertEqual(index["Rock & Roll.nes"].fields["name"], "Rock & Roll Racing")

    def test_a_truly_unreadable_file_still_returns_empty(self):
        """복구는 최선을 다하는 것이지 아무거나 통과시키는 것이 아니다.

        읽을 수 없으면 그 System만 메타데이터 없는 상태로 두고 스캔은 계속돼야 한다.
        """
        index = self._index("<<<이건 XML이 아니다>>>", system="junk", roms=())
        self.assertEqual(index, {})

    def test_normal_gamelists_are_unaffected(self):
        normal = ('<?xml version="1.0"?>\n<gameList>\n'
                  '  <game><path>./Zelda.sfc</path><name>Zelda</name></game>\n</gameList>\n')
        index = self._index(normal, roms=("Zelda.sfc",))
        self.assertEqual(index["Zelda.sfc"].fields["name"], "Zelda")


class DuplicateMediaTests(unittest.TestCase):
    """같은 media type 파일이 둘일 때 **스캔이 죽지 않아야 한다.**

    실제 자료에서 `covers/Shanghai 1.jpg`와 `covers/Shanghai 1.png`가 함께 있었고,
    그 두 파일 때문에 27개 시스템 중 8개가 아예 스캔되지 않았다.
    """

    def setUp(self):
        self.dir = temp_root("rms_dupmedia_")
        self.root = es_de_tree(self.dir / "esde", roms=("Zelda.sfc", "Mario.sfc"),
                               gamelist='<?xml version="1.0"?>\n<gameList/>\n')
        covers = self.root / "downloaded_media" / "sfc" / "covers"
        # 같은 stem에 확장자만 다른 두 커버 - 실제로 있는 상황이다.
        (covers / "Zelda.jpg").write_bytes(b"j" * 40)
        (covers / "Zelda.png").write_bytes(b"p" * 60)
        (covers / "Mario.png").write_bytes(b"m" * 50)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.cid = self.api.create_collection("real", "es-de", str(self.root))["data"]["id"]

    def tearDown(self):
        self.api.close()

    def test_scan_completes_without_error(self):
        job = self.api.start_scan(self.cid, True)["data"]["jobId"]
        wait_idle(self.api)
        progress = self.api.get_job_progress(job)["data"]
        self.assertIsNone(progress.get("error"), "중복 media 때문에 스캔이 죽었다")
        self.assertEqual(self.api.list_rows(self.cid, limit=50)["data"]["total"], 2)

    def test_the_duplicate_type_is_reduced_to_one(self):
        scan(self.api, self.cid)
        rows = self.api.list_rows(self.cid, limit=50)["data"]["rows"]
        target = next(r for r in rows if r["file"] == "Zelda.sfc")
        row = self.api.workspace.open(self.cid).get_row(target["romUid"])
        covers = [m for m in row["media"] if m["media_type"] == "covers"]
        self.assertEqual(len(covers), 1, "같은 타입이 둘 남으면 Cache 제약을 다시 위반한다")

    def test_the_choice_is_stable_across_scans(self):
        """스캔할 때마다 다른 파일이 뽑히면 Compare가 매번 다르다고 말한다."""
        picks = []
        for _ in range(2):
            self.api.start_scan(self.cid, True)
            wait_idle(self.api)
            rows = self.api.list_rows(self.cid, limit=50)["data"]["rows"]
            target = next(r for r in rows if r["file"] == "Zelda.sfc")
            row = self.api.workspace.open(self.cid).get_row(target["romUid"])
            picks.append(next(m["rel_path"] for m in row["media"] if m["media_type"] == "covers"))
        self.assertEqual(picks[0], picks[1])

    def test_other_media_types_are_untouched(self):
        scan(self.api, self.cid)
        rows = self.api.list_rows(self.cid, limit=50)["data"]["rows"]
        mario = next(r for r in rows if r["file"] == "Mario.sfc")
        row = self.api.workspace.open(self.cid).get_row(mario["romUid"])
        self.assertEqual([m["media_type"] for m in row["media"]], ["covers"])


class EsDeReservedFolderTests(unittest.TestCase):
    """ES-DE 자체 폴더가 게임 System으로 잡히면 빈 항목이 목록에 뜬다."""

    def test_es_de_own_folders_are_not_systems(self):
        root = temp_root("rms_reserved_") / "esde"
        es_de_tree(root)
        for name in ("controllers", "screensavers", "temp", "themes", "collections"):
            (root / name).mkdir(parents=True, exist_ok=True)

        adapter = EsDeAdapter()
        systems = adapter.list_systems(PROVIDER, make_collection(root))
        for name in ("controllers", "screensavers", "temp", "themes", "collections"):
            self.assertNotIn(name, systems, f"{name}이 System으로 잡혔다")
        self.assertIn("sfc", systems)


class WriteBackPreservesTheFileTests(unittest.TestCase):
    """**읽을 수 있게 된 것만으로는 부족하다 - 다시 써도 잃지 않아야 한다.**

    Phase 7.7에서 `<alternativeEmulator>`가 앞에 오는 gamelist를 읽게 만들었지만,
    읽을 때 `<gameList>`만 꺼내고 그대로 다시 쓰는 바람에 **저장 한 번에
    `<alternativeEmulator>`가 사라졌다.** 사용자가 그 System에 대해 고른 에뮬레이터
    설정이 통째로 날아간다.

    실제 백업 26개 중 9개가 이 형태였다. 파일 단위로 태그를 세어 보고서야 드러났다 -
    round-trip 테스트는 **우리가 읽는 것**만 비교하므로 우리가 아예 안 읽는 부분이
    사라지는 것은 잡지 못한다.
    """

    def setUp(self):
        self.adapter = EsDeAdapter()
        self.dir = temp_root("rms_writeback_")
        self._case = 0

    def _layout(self, gamelist, system="sfc", roms=("Zelda.sfc", "Mario.sfc")):
        self._case += 1
        root = es_de_tree(self.dir / f"case{self._case}",
                          system=system, gamelist=gamelist, roms=roms)
        return self.adapter.layout(make_collection(root, system), system)

    def _rewrite(self, layout):
        """읽어서 그대로 다시 쓴다 - Apply/Export가 하는 일과 같다."""
        index = self.adapter.read_index(PROVIDER, layout)
        self.adapter.write_index(layout, list(index.values()))
        return Path(layout.metadata_file).read_text(encoding="utf-8")

    def test_alternative_emulator_survives_a_rewrite(self):
        after = self._rewrite(self._layout(ALTERNATIVE_EMULATOR_GAMELIST))
        self.assertIn("<alternativeEmulator>", after,
                      "저장했더니 사용자가 고른 에뮬레이터 설정이 사라졌다")
        self.assertIn("Snes9x 2010", after)

    def test_the_games_are_still_there_too(self):
        layout = self._layout(ALTERNATIVE_EMULATOR_GAMELIST)
        self._rewrite(layout)
        index = self.adapter.read_index(PROVIDER, layout)
        self.assertEqual(sorted(index), ["Mario.sfc", "Zelda.sfc"])
        self.assertEqual(index["Zelda.sfc"].fields["name"], "The Legend of Zelda")

    def test_it_survives_a_second_rewrite(self):
        """한 번은 살아남고 두 번째에 사라지면 더 찾기 어렵다."""
        layout = self._layout(ALTERNATIVE_EMULATOR_GAMELIST)
        self._rewrite(layout)
        self.assertIn("Snes9x 2010", self._rewrite(layout))

    def test_removing_a_game_does_not_remove_it_either(self):
        layout = self._layout(ALTERNATIVE_EMULATOR_GAMELIST)
        self.adapter.remove_entries(layout, ["Mario.sfc"])
        after = Path(layout.metadata_file).read_text(encoding="utf-8")
        self.assertIn("Snes9x 2010", after)
        self.assertNotIn("Mario.sfc", after)
        self.assertIn("Zelda.sfc", after)

    def test_the_result_is_still_readable_by_us(self):
        """되돌려 놓은 원문이 파일을 깨뜨리면 안 된다."""
        layout = self._layout(BOTH_PROBLEMS_GAMELIST, system="nes", roms=("Rock & Roll.nes",))
        self._rewrite(layout)
        index = self.adapter.read_index(PROVIDER, layout)
        self.assertEqual(index["Rock & Roll.nes"].fields["name"], "Rock & Roll Racing")

    def test_a_normal_gamelist_gains_no_prologue(self):
        """`<alternativeEmulator>`가 없던 파일에 없던 것을 만들어 넣지 않는다."""
        normal = ('<?xml version="1.0"?>\n<gameList>\n'
                  '  <game><path>./Zelda.sfc</path><name>Zelda</name></game>\n</gameList>\n')
        after = self._rewrite(self._layout(normal, roms=("Zelda.sfc",)))
        self.assertNotIn("alternativeEmulator", after)

    def test_empty_tags_are_not_invented(self):
        """원래 없던 `<region>`을 게임마다 빈 값으로 만들어 넣지 않는다.

        ES-DE가 읽는 값은 달라지지 않지만, 1,539개 항목에 전부 붙으면 사용자가 파일을
        열어 봤을 때도 버전 관리에 넣어 뒀을 때도 잡음이 된다.
        """
        after = self._rewrite(self._layout(ALTERNATIVE_EMULATOR_GAMELIST))
        for tag in ("region", "players", "publisher", "developer"):
            self.assertNotIn(f"<{tag}", after, f"없던 <{tag}>가 생겼다")

    def test_rating_keeps_the_shape_es_de_wrote(self):
        """값은 같은데 `0.9`가 `0.90`이 되면 저장할 때마다 파일이 달라진다.

        실제 백업의 rating은 전부 `0.8`/`0.9`/`1` 꼴이었고, 우리가 `:.2f`로 쓰는
        바람에 1,119줄이 뜻 없이 바뀌고 있었다.
        """
        rated = ('<?xml version="1.0"?>\n<gameList>\n'
                 '  <game><path>./Zelda.sfc</path><name>Zelda</name>'
                 '<rating>0.9</rating></game>\n'
                 '  <game><path>./Mario.sfc</path><name>Mario</name>'
                 '<rating>1</rating></game>\n</gameList>\n')
        after = self._rewrite(self._layout(rated))
        self.assertIn("<rating>0.9</rating>", after)
        self.assertIn("<rating>1</rating>", after)

    def test_a_field_the_user_cleared_is_still_cleared(self):
        """반대로 **있던 값을 지운 것**은 지워져야 한다 - 안 쓰는 것과 다르다."""
        layout = self._layout(ALTERNATIVE_EMULATOR_GAMELIST)
        index = self.adapter.read_index(PROVIDER, layout)
        entry = index["Zelda.sfc"]
        entry.fields["genre"] = ""
        self.adapter.write_index(layout, [entry])
        self.assertEqual(
            self.adapter.read_index(PROVIDER, layout)["Zelda.sfc"].fields["genre"], "")

if __name__ == "__main__":
    unittest.main()
