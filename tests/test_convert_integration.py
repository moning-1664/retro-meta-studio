"""Convert의 마지막 10% — 실제 파일시스템 왕복 검증 (Phase 7.2 Hardening).

Phase 7.2의 테스트는 미리보기 숫자와 Plan 동작을 봤지만, **실제로 파일이 오가고 다시
읽히는 경로**는 얇게만 봤다. 그 틈에서 실제 버그가 하나 나왔다:

    ES-DE의 frontend_raw({"tag","text"})가 Pegasus로 넘어가
    from_common이 item["key"]를 찾다가 KeyError -> Apply 전체 실패

`build_custom_esde_tree()`가 미지 태그를 만들지 않아서 기존 테스트가 이걸 통과시켰다.
여기서는 **미지 태그와 media를 실제로 심고** 왕복시킨다.
"""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.base import COMMON_FIELDS, RAW_FRONTEND_KEY
from adapters.emulationstation import EmulationStationAdapter
from adapters.es_de import EsDeAdapter
from adapters.launchbox import LaunchBoxAdapter
from adapters.pegasus import PegasusAdapter
from bridge.api import Api
from storage.local import LocalStorageProvider
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle

PROVIDER = LocalStorageProvider()


def esde_source(root: Path) -> Path:
    """미지 태그와 media를 실제로 가진 ES-DE 트리."""
    build_custom_esde_tree(root, "ps2", [
        {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG",
         "developer": "Square", "publisher": "Square Enix",
         "releasedate": "20010719T000000", "size": 100},
    ])
    gamelist = root / "gamelists" / "ps2" / "gamelist.xml"
    tree = ET.parse(gamelist)
    for game in tree.getroot().findall("game"):
        ET.SubElement(game, "playcount").text = "17"
        ET.SubElement(game, "favorite").text = "true"
        ET.SubElement(game, "region").text = "USA"
    tree.write(gamelist, encoding="utf-8", xml_declaration=True)

    covers = root / "downloaded_media" / "ps2" / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    (covers / "FFX.png").write_bytes(b"cover-bytes")
    return root


def empty_esde(root: Path) -> Path:
    (root / "gamelists" / "ps2").mkdir(parents=True)
    (root / "gamelists" / "ps2" / "gamelist.xml").write_text(
        '<?xml version="1.0"?>\n<gameList/>\n', encoding="utf-8")
    (root / "downloaded_media" / "ps2").mkdir(parents=True)
    return root


def empty_pegasus(root: Path) -> Path:
    (root / "ps2").mkdir(parents=True)
    (root / "ps2" / "metadata.pegasus.txt").write_text(
        "collection: PlayStation 2\nshortname: ps2\n\n", encoding="utf-8")
    return root


def empty_es(root: Path) -> Path:
    (root / "gamelists" / "ps2").mkdir(parents=True)
    (root / "gamelists" / "ps2" / "gamelist.xml").write_text(
        '<?xml version="1.0"?>\n<gameList/>\n', encoding="utf-8")
    return root


def empty_launchbox(root: Path) -> Path:
    (root / "Data" / "Platforms").mkdir(parents=True)
    (root / "Data" / "Platforms" / "ps2.xml").write_text(
        '<?xml version="1.0"?>\n<LaunchBox/>\n', encoding="utf-8")
    (root / "Games" / "ps2").mkdir(parents=True)
    return root


class ConvertIntegrationTests(unittest.TestCase):
    """실제 파일시스템을 오가는 변환. Plan -> Apply -> 재스캔까지 통과시킨다."""

    def setUp(self):
        self.dir = temp_root("rms_convert_int_")
        self.src_root = esde_source(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("ES-DE", "es-de", str(self.src_root))["data"]["id"]
        scan(self.api, self.src)

    def tearDown(self):
        self.api.close()

    # ------------------------------------------------------------------
    def _target(self, name, frontend, builder):
        root = builder(self.dir / name)
        cid = self.api.create_collection(name, frontend, str(root))["data"]["id"]
        scan(self.api, cid)
        return cid, root

    def _convert_and_apply(self, source_id, target_id):
        result = self.api.start_convert(source_id, target_id)
        self.assertTrue(result["ok"], result.get("error"))
        job = self.api.start_apply(target_id)["data"]["jobId"]
        wait_idle(self.api)
        outcome = self.api.get_job_progress(job)["data"]["result"]
        self.assertEqual(outcome["failed"], 0, outcome["errors"])
        self.assertEqual(outcome["partial"], 0, outcome["errors"])
        return outcome

    # --- ① frontend_raw는 다른 Frontend로 건너가지 않는다 ----------------
    def test_foreign_frontend_raw_never_reaches_the_target(self):
        """이게 실제 버그였다 - 넘어가서 KeyError로 Apply가 통째로 실패했다."""
        target, root = self._target("pegasus", "pegasus", empty_pegasus)
        self._convert_and_apply(self.src, target)

        text = (root / "ps2" / "metadata.pegasus.txt").read_text(encoding="utf-8")
        self.assertIn("game: Final Fantasy X", text)
        self.assertNotIn("playcount", text, "ES-DE 고유 태그가 Pegasus 블록에 새어 들어갔다")
        self.assertNotIn("favorite", text)

    def test_same_frontend_keeps_frontend_raw(self):
        """반대로 같은 Frontend끼리는 보존돼야 한다 - 일괄 폐기가 아니다."""
        target, root = self._target("esde2", "es-de", empty_esde)
        self._convert_and_apply(self.src, target)

        root_el = ET.parse(root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = root_el.find("game")
        self.assertEqual(game.findtext("playcount"), "17")
        self.assertEqual(game.findtext("favorite"), "true")

    def test_raw_declares_its_origin(self):
        row = self.api.workspace.open(self.src).get_row(
            self.api.list_rows(self.src)["data"]["rows"][0]["romUid"])
        self.assertEqual(row["frontend_raw"].get(RAW_FRONTEND_KEY), "es-de")

    # --- ② source media 경로가 실제로 해석되는가 -------------------------
    def test_source_media_path_resolves_to_a_real_file(self):
        """`rel_path`라는 이름과 달리 절대 경로가 들어 있다 - 그대로 열려야 한다."""
        row = self.api.workspace.open(self.src).get_row(
            self.api.list_rows(self.src)["data"]["rows"][0]["romUid"])
        paths = [Path(m["rel_path"]) for m in row["media"]]
        self.assertTrue(paths, "media가 스캔되지 않았다")
        for path in paths:
            self.assertTrue(path.is_absolute(), f"상대 경로다: {path}")
            self.assertTrue(path.exists(), f"열 수 없다: {path}")

    def test_media_actually_lands_in_the_target(self):
        target, root = self._target("pegasus", "pegasus", empty_pegasus)
        self._convert_and_apply(self.src, target)
        cover = root / "ps2" / "media" / "FFX" / "boxFront.png"
        self.assertTrue(cover.exists(), "media가 복사되지 않았다")
        self.assertEqual(cover.read_bytes(), b"cover-bytes", "다른 파일이 복사됐다")

    # --- ③④ 실제 파일시스템 왕복 --------------------------------------
    def _round_trip(self, mid_frontend, mid_builder, mid_name):
        """ES-DE -> X -> ES-DE. 공통 필드가 살아 돌아와야 한다(§50-51)."""
        mid, _mid_root = self._target(mid_name, mid_frontend, mid_builder)
        self._convert_and_apply(self.src, mid)
        self.api.start_scan(mid, True)
        wait_idle(self.api)

        back, back_root = self._target(f"{mid_name}_back", "es-de", empty_esde)
        self._convert_and_apply(mid, back)

        adapter = EsDeAdapter()
        collection = self.api.registry.get_collection(back)
        final = adapter.read_index(PROVIDER, adapter.layout(collection, "ps2"))["FFX.iso"]
        return final, back_root

    def test_es_de_to_emulationstation_and_back(self):
        final, _ = self._round_trip("emulationstation", empty_es, "es")
        for key in ("name", "genre", "developer", "publisher", "releasedate", "region"):
            self.assertTrue(final.fields[key], f"{key}가 왕복에서 사라졌다")
        self.assertEqual(final.fields["name"], "Final Fantasy X")
        self.assertEqual(final.fields["releasedate"], "2001-07-19")

    def test_es_de_to_pegasus_and_back(self):
        final, _ = self._round_trip("pegasus", empty_pegasus, "pegasus")
        for key in ("name", "genre", "developer", "publisher", "releasedate"):
            self.assertTrue(final.fields[key], f"{key}가 왕복에서 사라졌다")
        self.assertEqual(final.fields["name"], "Final Fantasy X")
        # region은 Pegasus를 거치며 사라진다 - 미리보기가 그렇게 예고했으므로 정상이다.
        self.assertEqual(final.fields["region"], "",
                         "Pegasus 경유인데 region이 남았다면 미리보기가 거짓말한 것이다")

    def test_media_survives_a_full_round_trip(self):
        _final, back_root = self._round_trip("pegasus", empty_pegasus, "pegasus")
        cover = back_root / "downloaded_media" / "ps2" / "covers" / "FFX.png"
        self.assertTrue(cover.exists(), "media가 왕복에서 사라졌다")
        self.assertEqual(cover.read_bytes(), b"cover-bytes")


    def test_repeated_round_trips_do_not_keep_losing_fields(self):
        """**손실은 한 번 일어나고 멈춰야 한다 - 왕복마다 조금씩 깎이면 안 된다.**

        Frontend 사이 변환은 반드시 무언가를 잃는다(§50-51). 그건 정상이다. 문제는
        그 손실이 **누적되는** 경우다. 사용자가 ES-DE와 Pegasus를 오가며 작업하는
        것은 흔한데, 왕복할 때마다 필드가 하나씩 사라지면 몇 번 만에 제목만 남는다.

        그래서 1회 왕복 뒤 살아남은 것이 3회 왕복 뒤에도 그대로인지 본다.
        """
        current, hop = self.src, 0
        after_first = None
        for _ in range(3):
            hop += 1
            mid, _ = self._target(f"pg{hop}", "pegasus", empty_pegasus)
            self._convert_and_apply(current, mid)
            self.api.start_scan(mid, True)
            wait_idle(self.api)

            hop += 1
            back, back_root = self._target(f"esde{hop}", "es-de", empty_esde)
            self._convert_and_apply(mid, back)
            self.api.start_scan(back, True)
            wait_idle(self.api)

            adapter = EsDeAdapter()
            collection = self.api.registry.get_collection(back)
            fields = adapter.read_index(
                PROVIDER, adapter.layout(collection, "ps2"))["FFX.iso"].fields
            if after_first is None:
                after_first = dict(fields)
            current = back

        self.assertEqual(fields, after_first,
                         "왕복을 반복할수록 값이 계속 깎인다")
        self.assertEqual(fields["name"], "Final Fantasy X")

    def test_media_also_survives_repeated_round_trips(self):
        """파일도 마찬가지다 - 왕복마다 하나씩 사라지면 안 된다."""
        current, hop = self.src, 0
        for _ in range(3):
            hop += 1
            mid, _ = self._target(f"m_pg{hop}", "pegasus", empty_pegasus)
            self._convert_and_apply(current, mid)
            self.api.start_scan(mid, True)
            wait_idle(self.api)

            hop += 1
            back, back_root = self._target(f"m_esde{hop}", "es-de", empty_esde)
            self._convert_and_apply(mid, back)
            self.api.start_scan(back, True)
            wait_idle(self.api)
            current = back

        cover = back_root / "downloaded_media" / "ps2" / "covers" / "FFX.png"
        self.assertTrue(cover.exists(), "왕복 3회 만에 media가 사라졌다")
        self.assertEqual(cover.read_bytes(), b"cover-bytes", "다른 파일로 바뀌었다")

    # --- ⑤ LaunchBox: 제목 기준 media 파일명 ---------------------------
    def test_launchbox_apply_places_media_and_reads_it_back(self):
        target, root = self._target("launchbox", "launchbox", empty_launchbox)
        self._convert_and_apply(self.src, target)

        xml = (root / "Data" / "Platforms" / "ps2.xml").read_text(encoding="utf-8")
        self.assertIn("<Title>Final Fantasy X</Title>", xml)

        adapter = LaunchBoxAdapter()
        collection = self.api.registry.get_collection(target)
        layout = adapter.layout(collection, "ps2")
        index = adapter.read_media_index(PROVIDER, layout)
        self.assertIn("FFX", index, "복사한 media를 다시 못 찾는다")
        self.assertEqual({m.media_type for m in index["FFX"]}, {"covers"})

    # --- ⑥ 미리보기 숫자와 실제 결과 -----------------------------------
    def test_preview_matches_what_actually_happens(self):
        target, root = self._target("pegasus", "pegasus", empty_pegasus)
        preview = self.api.convert_preview(self.src, target)["data"]
        self.assertEqual(preview["games"], 1)
        self.assertEqual(preview["media"], 1)
        self.assertEqual(preview["unsupportedFieldNames"], ["region"])

        self._convert_and_apply(self.src, target)
        text = (root / "ps2" / "metadata.pegasus.txt").read_text(encoding="utf-8")
        self.assertNotIn("region", text, "미리보기는 잃는다고 했는데 실제로는 남았다")
        self.assertTrue((root / "ps2" / "media" / "FFX" / "boxFront.png").exists())

    def test_reconverting_plans_the_same_items_but_moves_no_bytes(self):
        """미리보기 숫자와 Plan의 "실제 변화"는 다른 것을 잰다.

        미리보기는 **source에 무엇이 있는가**를 세고, Plan은 **목적지에 무엇을 해야
        하는가**를 계산한다. 이미 같은 파일이 있으면 항목은 그대로 Plan에 올라가지만
        용량 변화는 0이다 - 파일은 안 옮겨도 Metadata는 다를 수 있으므로 항목 자체를
        빼면 안 된다.

        두 숫자가 어긋나 보이는 정상적인 경우라, 나중에 "미리보기가 틀렸다"고 오해하지
        않도록 여기에 적어 둔다.
        """
        target, _root = self._target("pegasus", "pegasus", empty_pegasus)
        self._convert_and_apply(self.src, target)
        self.api.start_scan(target, True)
        wait_idle(self.api)

        preview = self.api.convert_preview(self.src, target)["data"]
        self.assertEqual(preview["games"], 1, "미리보기는 여전히 source의 1개를 센다")

        again = self.api.start_convert(self.src, target)["data"]
        self.assertEqual(again["added"], 1, "항목은 다시 올라간다")
        self.assertEqual(again["conflicts"], 0, "같은 파일이므로 충돌이 아니다")

        # Plan에는 서로 다른 두 숫자가 있다.
        #   addedBytes    = 항목들의 예상 전송량(같은 파일이어도 항목 크기는 잡힌다)
        #   capacity delta = **실제로 늘어나는 디스크 사용량**
        # 이미 같은 파일이 있으면 전자는 0이 아니지만 후자는 0이다. 용량 경고를
        # 띄울지 판단할 때는 반드시 후자를 봐야 한다.
        plan = self.api.plan_state(target)["data"]
        for capacity in plan["capacity"]:
            self.assertEqual(capacity["deltaBytes"], 0,
                             f"{capacity['label']}: 같은 파일인데 디스크가 늘어난다고 계산했다")

    # --- 원본 보존 ------------------------------------------------------
    def test_the_source_is_never_modified(self):
        before_xml = (self.src_root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        before_cover = (self.src_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").read_bytes()

        for name, frontend, builder in [("pegasus", "pegasus", empty_pegasus),
                                        ("es", "emulationstation", empty_es),
                                        ("launchbox", "launchbox", empty_launchbox)]:
            target, _ = self._target(name, frontend, builder)
            self._convert_and_apply(self.src, target)

        self.assertEqual(
            (self.src_root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8"),
            before_xml)
        self.assertEqual(
            (self.src_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").read_bytes(),
            before_cover)


class AdapterContractTests(unittest.TestCase):
    """모든 Adapter가 지켜야 하는 선언들을 한자리에서 고정한다.

    Adapter가 늘어날 때마다 각자 테스트를 쓰기를 기대하면 언젠가 빠진다. 여기서
    등록된 전부를 훑으면 새 Adapter도 자동으로 이 검사를 받는다.
    """

    def adapters(self):
        import app.workspace  # noqa: F401  - 등록을 위한 import
        from adapters import available
        return available()

    def test_every_adapter_declares_sane_supported_fields(self):
        for adapter in self.adapters():
            with self.subTest(adapter=adapter.id):
                self.assertTrue(adapter.supported_fields, "빈 목록은 있을 수 없다")
                unknown = set(adapter.supported_fields) - set(COMMON_FIELDS)
                self.assertEqual(unknown, set(), f"공통 모델에 없는 필드를 선언했다: {unknown}")
                self.assertIn("name", adapter.supported_fields, "제목을 못 담는 Frontend는 없다")

    def test_every_adapter_declares_media_types(self):
        for adapter in self.adapters():
            with self.subTest(adapter=adapter.id):
                self.assertTrue(adapter.media_types)
                self.assertEqual(len(set(adapter.media_types)), len(adapter.media_types),
                                 "media type이 중복 선언됐다")

    def test_every_adapter_tags_its_raw(self):
        """출처 표시가 없으면 다른 Frontend의 raw를 걸러낼 수 없다."""
        for adapter in self.adapters():
            with self.subTest(adapter=adapter.id):
                tagged = adapter.tag_raw({"extra": [{"tag": "x", "text": "1"}]})
                self.assertEqual(tagged[RAW_FRONTEND_KEY], adapter.id)
                self.assertTrue(adapter.raw_is_mine(tagged))
                self.assertFalse(adapter.raw_is_mine({RAW_FRONTEND_KEY: "somebody-else"}))

    def test_empty_raw_is_not_tagged(self):
        """빈 값에 출처만 붙여 두면 "보존할 것이 있다"고 오해하게 된다."""
        for adapter in self.adapters():
            with self.subTest(adapter=adapter.id):
                self.assertEqual(adapter.tag_raw({}), {})

    def test_untagged_raw_is_treated_as_ours(self):
        """예전에 저장된 값에는 표시가 없다 - 표시가 없다고 버리면 계약 2를 어긴다."""
        for adapter in self.adapters():
            with self.subTest(adapter=adapter.id):
                self.assertTrue(adapter.raw_is_mine({"extra": []}))

    def test_pegasus_is_the_only_one_missing_region(self):
        """선언이 실제 포맷과 어긋나면 미리보기가 거짓말을 한다."""
        by_id = {a.id: a for a in self.adapters()}
        self.assertNotIn("region", by_id["pegasus"].supported_fields)
        for other in ("es-de", "launchbox", "emulationstation"):
            self.assertIn("region", by_id[other].supported_fields, other)


if __name__ == "__main__":
    unittest.main()
