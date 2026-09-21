"""External Storage 정체성(사용자 결정, 2026-09).

- 같은 System 폴더가 두 Storage에 ROM을 갖고 있으면 충돌: 표시하고 쓰기를 막는다.
- External을 추가하면 그 밑의 System 폴더를 붙인다(새로 등록 / ROM 없는 쪽에서 옮김 / 충돌은 보고만).
- 충돌은 한쪽 폴더 이름 바꾸기나 삭제로 푼다.
- ES-DE custom_systems XML은 ES-DE 기본 정의를 복사하고 <path>만 바꾼다. 안드로이드는 Storage ID로 기기 경로.
"""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bridge.api import Api
from tests.fixtures import build_esde_tree, temp_root, wait_job, write_file


class StorageConflictTests(unittest.TestCase):
    """Internal(Collection root)에 ps2 ROM, SD에도 ps2 ROM(충돌)과 snes ROM(새 System)."""

    def setUp(self):
        self.dir = temp_root("rms_storage_layout_")
        self.root = build_esde_tree(self.dir / "esde")
        self.sd = self.dir / "sd"
        write_file(self.sd / "ps2" / "Other.iso", b"s" * 50)
        write_file(self.sd / "snes" / "SMW.sfc", b"s" * 20)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        self.scan()
        self.ext = self.api.add_external_storage(self.cid, "SD", str(self.sd))["data"]

    def scan(self):
        wait_job(self.api, self.api.start_scan(self.cid, True)["data"]["jobId"])

    def systems(self):
        return {s["system"]: s for s in self.api.collection_detail(self.cid)["data"]["systems"]}

    def uid(self, filename):
        return next(r["romUid"] for r in self.api.list_rows(self.cid, limit=50)["data"]["rows"] if r["file"] == filename)

    def attach(self):
        r = self.api.attach_storage_systems(self.cid, self.ext)
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]

    def test_attach_adds_new_systems_and_reports_conflicts(self):
        result = self.attach()
        self.assertEqual(result, {"added": ["snes"], "moved": [], "conflicts": ["ps2"]})
        self.assertEqual(self.systems()["snes"]["storageId"], self.ext)
        self.assertEqual(self.systems()["ps2"]["storageId"], "internal")   # 충돌은 옮기지 않는다

    def test_detail_marks_both_sides_of_a_conflict(self):
        sides = self.systems()["ps2"]["conflict"]
        self.assertEqual({s["storageId"] for s in sides}, {"internal", self.ext})
        self.assertIn(str(self.sd / "ps2"), [s["path"] for s in sides])
        self.assertNotIn("conflict", self.systems().get("gba", {"x": 1}) or {})

    def test_writes_to_a_conflicted_system_are_blocked(self):
        uid = self.uid("FFX.iso")
        for result in (
            self.api.save_fields(self.cid, uid, {"name": "X"}),
            self.api.set_favorite(self.cid, uid, True),
            self.api.plan_delete(self.cid, [uid]),
            self.api.plan_storage_change(self.cid, "ps2", self.ext),
            self.api.move_system(self.cid, "ps2", self.ext),
            self.api.media_cleanup(self.cid, "ps2", ["covers"]),
        ):
            self.assertFalse(result["ok"])
            self.assertIn("쓰기가 막혀", result["error"])
        gamelist = (self.root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("Final Fantasy X", gamelist)

    def test_renaming_the_other_side_resolves_the_conflict(self):
        r = self.api.rename_system_folder(self.cid, "ps2", self.ext, "ps2sd")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue((self.sd / "ps2sd" / "Other.iso").exists())
        systems = self.systems()
        self.assertNotIn("conflict", systems["ps2"])
        self.assertEqual(systems["ps2sd"]["storageId"], self.ext)
        self.assertTrue(self.api.save_fields(self.cid, self.uid("FFX.iso"), {"name": "Again"})["ok"])

    def test_renaming_the_registered_side_moves_gamelist_and_media_too(self):
        r = self.api.rename_system_folder(self.cid, "ps2", "internal", "ps2int")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue((self.root / "ps2int" / "FFX.iso").exists())
        self.assertTrue((self.root / "gamelists" / "ps2int" / "gamelist.xml").exists())
        self.assertTrue((self.root / "downloaded_media" / "ps2int" / "covers" / "FFX.png").exists())
        systems = self.systems()
        self.assertEqual(systems["ps2int"]["count"], 3)
        self.assertNotIn("conflict", systems["ps2int"])

    def test_rename_rejects_bad_or_taken_names(self):
        self.attach()
        self.assertFalse(self.api.rename_system_folder(self.cid, "ps2", self.ext, "../evil")["ok"])
        self.assertFalse(self.api.rename_system_folder(self.cid, "ps2", self.ext, "snes")["ok"])
        self.assertTrue((self.sd / "ps2").exists())

    def test_removing_the_other_side_folder_resolves_the_conflict(self):
        preview = self.api.system_folder_preview(self.cid, "ps2", self.ext)["data"]
        self.assertEqual((preview["fileCount"], preview["registered"]), (1, False))
        r = self.api.remove_system_folder(self.cid, "ps2", self.ext)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertFalse((self.sd / "ps2").exists())
        self.assertTrue((self.root / "ps2" / "FFX.iso").exists())
        self.assertNotIn("conflict", self.systems()["ps2"])

    def test_removing_the_registered_side_moves_the_system_to_the_remaining_storage(self):
        r = self.api.remove_system_folder(self.cid, "ps2", "internal")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["movedTo"], self.ext)
        self.assertFalse((self.root / "ps2").exists())
        self.assertTrue((self.root / "gamelists" / "ps2" / "gamelist.xml").exists())   # 메타데이터는 남긴다
        systems = self.systems()
        self.assertEqual(systems["ps2"]["storageId"], self.ext)
        self.assertNotIn("conflict", systems["ps2"])


class AttachMoveTests(unittest.TestCase):
    def test_system_without_internal_roms_moves_to_external(self):
        dir_ = temp_root("rms_attach_move_")
        root = build_esde_tree(dir_ / "esde")
        write_file(root / "gamelists" / "gba" / "gamelist.xml",
                   '<?xml version="1.0"?>\n<gameList><game><path>./Zelda.gba</path><name>Zelda</name></game></gameList>')
        sd = dir_ / "sd"
        write_file(sd / "gba" / "Zelda.gba", b"z" * 10)
        api = Api(registry_path=dir_ / "registry.db", cache_dir=dir_ / "cache")
        self.addCleanup(api.close)
        cid = api.create_collection("C", "es-de", str(root))["data"]["id"]
        wait_job(api, api.start_scan(cid)["data"]["jobId"])
        ext = api.add_external_storage(cid, "SD", str(sd))["data"]
        result = api.attach_storage_systems(cid, ext)["data"]
        self.assertEqual(result["moved"], ["gba"])
        wait_job(api, api.start_scan(cid, True)["data"]["jobId"])
        rows = api.list_rows(cid, systems=["gba"], limit=10)["data"]["rows"]
        self.assertTrue(rows[0]["present"])


class StorageSettingsAndXmlTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_esde_xml_")
        self.root = build_esde_tree(self.dir / "esde")
        self.sd = self.dir / "sd"
        write_file(self.sd / "ROMs" / "snes" / "SMW.sfc", b"s" * 20)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)

    def make(self, target):
        cid = self.api.create_collection("C", "es-de", str(self.root), target)["data"]["id"]
        wait_job(self.api, self.api.start_scan(cid)["data"]["jobId"])
        ext = self.api.add_external_storage(cid, "SD", str(self.sd / "ROMs"))["data"]
        self.api.attach_storage_systems(cid, ext)
        return cid, ext

    def xml_systems(self):
        root = ET.parse(self.root / "custom_systems" / "es_systems.xml").getroot()
        return {n.findtext("name"): n for n in root.findall("system")}

    def test_device_fields_are_saved_and_validated(self):
        cid, ext = self.make("android")
        self.assertTrue(self.api.update_storage(cid, ext, "SD카드", None, "1234-ABCD", "/storage/1234-ABCD/ROMs")["ok"])
        storage = next(s for s in self.api.collection_detail(cid)["data"]["storages"] if s["id"] == ext)
        self.assertEqual((storage["label"], storage["deviceId"], storage["deviceRoot"]),
                         ("SD카드", "1234-ABCD", "/storage/1234-ABCD/ROMs"))
        self.assertFalse(self.api.update_storage(cid, ext, None, None, "12 34", None)["ok"])
        self.assertFalse(self.api.update_storage(cid, ext, None, None, None, "storage/x")["ok"])

    def test_android_xml_copies_esde_definition_and_uses_the_device_path(self):
        cid, ext = self.make("android")
        missing = self.api.run_adapter_action(cid, "esde-custom-systems")["data"]
        self.assertEqual((missing["written"], missing["needsDeviceId"]), (False, ["snes"]))

        self.api.update_storage(cid, ext, None, None, "1234-ABCD", "")
        result = self.api.run_adapter_action(cid, "esde-custom-systems")["data"]
        self.assertTrue(result["written"])
        self.assertEqual(result["platform"], "android")
        snes = self.xml_systems()["snes"]
        self.assertEqual(snes.findtext("path"), "/storage/1234-ABCD/snes")
        self.assertIn(".sfc", snes.findtext("extension"))              # ES-DE 기본 정의를 그대로 복사
        self.assertIn("snes9x", ET.tostring(snes, encoding="unicode"))   # 실행 명령도 살아 있다
        self.assertNotIn("ps2", self.xml_systems())                      # Android Internal은 적지 않는다

    def test_android_xml_needs_only_the_device_path_not_a_storage_id(self):
        """기기 경로(전체 경로)만 있으면 만들어진다 - ID를 따로 받지 않는다(사용자 결정)."""
        cid, ext = self.make("android")
        self.api.update_storage(cid, ext, None, None, "", "/storage/1234-ABCD/Roms")
        result = self.api.run_adapter_action(cid, "esde-custom-systems")["data"]
        self.assertTrue(result["written"], result)
        self.assertEqual(self.xml_systems()["snes"].findtext("path"), "/storage/1234-ABCD/Roms/snes")

    def test_target_left_unset_still_uses_the_device_path_if_one_is_set(self):
        """실사용 버그 리포트 - Target을 "Unknown"으로 둔 채 만든 Collection이 기기 경로를
        입력해 뒀는데도 PC 경로(윈도우 템플릿)로 나왔다. 기기 경로가 있으면 Target을
        안 정했어도 Android로 본다."""
        cid, ext = self.make(None)
        self.api.update_storage(cid, ext, None, None, "", "/storage/1234-ABCD/Roms")
        result = self.api.run_adapter_action(cid, "esde-custom-systems")["data"]
        self.assertTrue(result["written"], result)
        self.assertEqual(result["platform"], "android")
        snes = self.xml_systems()["snes"]
        self.assertEqual(snes.findtext("path"), "/storage/1234-ABCD/Roms/snes")
        self.assertIn("snes9x", ET.tostring(snes, encoding="unicode"))   # 안드로이드 템플릿(명령)을 썼다

    def test_empty_result_says_why(self):
        cid, _ext = self.make("windows")
        # 아직 System을 안 붙인 새 Storage에는 쓸 것이 없고, 그 이유가 "붙은 System이 없다"다.
        empty = self.api.add_external_storage(cid, "Empty", str(self.dir / "empty"))["data"]
        result = self.api.run_adapter_action(cid, "esde-custom-systems", storage_id=empty)["data"]
        self.assertFalse(result["written"])
        self.assertEqual(result["reason"], "no-systems")

    def test_a_storage_id_scopes_generation_to_just_that_storage(self):
        """External이 둘일 때, 한쪽 그룹의 버튼이 다른 쪽까지 다시 쓰면 안 된다
        (실사용 피드백 - "external만 골라서 생성하는게 맞다"). Collection당 파일은
        하나지만, 이번에 쓴 것은 storage_id로 고른 Storage의 System뿐이어야 한다."""
        cid, ext1 = self.make("windows")
        write_file(self.sd / "ROMs" / "gba" / "Zelda.gba", b"g" * 20)
        sd2 = self.dir / "sd2"
        write_file(sd2 / "n64" / "Mario64.z64", b"n" * 20)
        wait_job(self.api, self.api.start_scan(cid, force=True)["data"]["jobId"])
        ext2 = self.api.add_external_storage(cid, "SD2", str(sd2))["data"]
        self.api.attach_storage_systems(cid, ext2)

        result = self.api.run_adapter_action(cid, "esde-custom-systems", storage_id=ext1)["data"]
        self.assertEqual(sorted(result["systems"]), ["gba", "snes"])
        self.assertNotIn("n64", result["systems"])
        systems = self.xml_systems()
        self.assertIn("snes", systems)
        self.assertIn("gba", systems)
        self.assertNotIn("n64", systems, "다른 External의 System까지 함께 썼다")

        # 이번엔 ext2만 골라 쓴다 - ext1(snes/gba)의 기존 항목은 그대로 남아야 한다.
        result2 = self.api.run_adapter_action(cid, "esde-custom-systems", storage_id=ext2)["data"]
        self.assertEqual(result2["systems"], ["n64"])
        self.assertEqual(sorted(result2["kept"]), ["gba", "snes"])
        systems2 = self.xml_systems()
        self.assertEqual(set(systems2), {"snes", "gba", "n64"})

    def test_windows_xml_uses_the_pc_path_and_keeps_other_entries(self):
        write_file(self.root / "custom_systems" / "es_systems.xml",
                   '<?xml version="1.0"?>\n<systemList><system><name>mine</name><path>C:\\mine</path></system>'
                   '<system><name>snes</name><path>OLD</path></system></systemList>')
        cid, ext = self.make("windows")
        result = self.api.run_adapter_action(cid, "esde-custom-systems")["data"]
        self.assertEqual(result["kept"], ["mine"])
        systems = self.xml_systems()
        self.assertEqual(Path(systems["snes"].findtext("path")), self.sd / "ROMs" / "snes")
        self.assertIn("mine", systems)
        self.assertEqual(len([n for n in systems if n == "snes"]), 1)


class MixedStorageKindsTests(unittest.TestCase):
    """**한 Collection은 한 종류의 저장소만 쓴다** (검증 리스트 #10).

    Provider는 Collection의 root_path 하나로 정해진다(workspace.provider_for).
    그래서 종류가 다른 경로를 Storage로 붙이면 엉뚱한 Provider가 그 경로를 읽는다.
    로컬 Provider에게 `mtp://...`를 읽히면 예외조차 없이 **빈 목록**이 와서,
    사용자에게는 그 System이 그냥 비어 보인다 - 원인을 알 방법이 없다.
    """

    def setUp(self):
        self.dir = temp_root("rms_mixed_")
        self.root = build_esde_tree(self.dir / "lib")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]

    def test_a_device_path_cannot_be_added_to_a_local_collection(self):
        result = self.api.add_external_storage(self.cid, "Phone", "mtp://R58N30ABCDE")
        self.assertFalse(result["ok"])
        self.assertIn("함께 둘 수 없습니다", result["error"])

    def test_the_rejected_storage_is_not_registered(self):
        self.api.add_external_storage(self.cid, "Phone", "mtp://R58N30ABCDE")
        storages = self.api.collection_detail(self.cid)["data"]["storages"]
        self.assertEqual([s for s in storages if "mtp" in str(s.get("rootPath", "")).lower()], [])

    def test_a_normal_external_storage_still_works(self):
        """가드가 평범한 경우까지 막으면 안 된다."""
        sd = self.dir / "sd"
        sd.mkdir(parents=True, exist_ok=True)
        self.assertTrue(self.api.add_external_storage(self.cid, "SD", str(sd))["ok"])

    def test_the_silent_emptiness_this_guard_prevents_is_real(self):
        """가드가 왜 필요한지를 못 박아 둔다 - 로컬 Provider는 기기 경로에 대해
        오류가 아니라 «아무것도 없음»을 돌려준다."""
        import storage

        provider = storage.for_path(str(self.root))
        self.assertEqual(provider.scandir("mtp://DEV/Internal shared storage/ps2"), [])
        self.assertFalse(provider.exists("mtp://DEV/Internal shared storage/ps2"))


if __name__ == "__main__":
    unittest.main()


class CustomSystemsWriteFailureTests(unittest.TestCase):
    """쓰기가 실패하면 성공이라고 답하지 않는다."""

    def test_failed_write_is_reported_not_swallowed(self):
        from unittest import mock
        from adapters import es_de
        dir_ = temp_root("rms_xml_fail_")
        root = build_esde_tree(dir_ / "esde")
        sd = dir_ / "sd"
        write_file(sd / "snes" / "SMW.sfc", b"s")
        api = Api(registry_path=dir_ / "registry.db", cache_dir=dir_ / "cache")
        self.addCleanup(api.close)
        cid = api.create_collection("C", "es-de", str(root), "windows")["data"]["id"]
        wait_job(api, api.start_scan(cid)["data"]["jobId"])
        ext = api.add_external_storage(cid, "SD", str(sd))["data"]
        api.attach_storage_systems(cid, ext)
        with mock.patch.object(es_de, "write_xml", return_value=False):
            result = api.run_adapter_action(cid, "esde-custom-systems")
        self.assertFalse(result["ok"])
        self.assertIn("쓰지 못했습니다", result["error"])


class StorageFolderTests(unittest.TestCase):
    """Storage 그룹 우클릭의 "폴더 열기"는 System 폴더들을 품은 **상위 폴더**를 가리킨다(사용자 결정)."""

    def setUp(self):
        self.dir = temp_root("rms_storage_folder_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def _folder(self, kind):
        from unittest import mock
        from bridge import api as bridge_api
        opened = []
        with mock.patch.object(bridge_api, "_reveal_path", lambda path, select=False: opened.append(path)):
            result = self.api.open_storage_folder(self.cid, "internal", kind)
        return result, opened

    def test_rom_folder_is_the_parent_of_the_system_folders(self):
        result, opened = self._folder("rom")
        self.assertTrue(result["ok"], result)
        self.assertEqual(Path(opened[0]), self.root)

    def test_metadata_folder_is_gamelists(self):
        result, opened = self._folder("metadata")
        self.assertTrue(result["ok"], result)
        self.assertEqual(Path(opened[0]), self.root / "gamelists")

    def test_media_folder_is_downloaded_media(self):
        result, opened = self._folder("media")
        self.assertTrue(result["ok"], result)
        self.assertEqual(Path(opened[0]), self.root / "downloaded_media")

    def test_unknown_kind_and_empty_storage_are_refused(self):
        self.assertFalse(self._folder("nope")[0]["ok"])
        self.assertFalse(self.api.open_storage_folder(self.cid, "no-such-storage", "rom")["ok"])


class TitleAffixSeveralSystemsTests(unittest.TestCase):
    """Storage 그룹 우클릭 - 그 그룹의 System 여러 개를 한 번에 대상으로 삼는다."""

    def test_preview_accepts_a_list_of_systems(self):
        dir_ = temp_root("rms_affix_multi_")
        root = build_esde_tree(dir_ / "esde")
        write_file(root / "gamelists" / "snes" / "gamelist.xml",
                   '<?xml version="1.0"?>\n<gameList><game><path>./Zelda (Japan).sfc</path><name>Zelda</name></game></gameList>')
        write_file(root / "snes" / "Zelda (Japan).sfc", b"z")
        api = Api(registry_path=dir_ / "registry.db", cache_dir=dir_ / "cache")
        self.addCleanup(api.close)
        cid = api.create_collection("C", "es-de", str(root))["data"]["id"]
        wait_job(api, api.start_scan(cid)["data"]["jobId"])
        api.save_app_settings({"titleAffix": {"jp": {"enabled": True, "mode": "postfix", "text": " [JP]"}}})
        one = api.title_affix_preview(cid, None, "snes")["data"]["items"]
        both = api.title_affix_preview(cid, None, ["snes", "ps2"])["data"]["items"]
        self.assertEqual(len(one), 1)
        self.assertGreater(len(both), len(one), "여러 System을 주었는데 하나만 대상이 됐다")


class CreateSystemAndMissingSystemPasteTests(unittest.TestCase):
    """System 만들기(빈 폴더)와, 없는 System을 붙여넣을 때 ROM이 놓이는 곳."""

    def setUp(self):
        self.dir = temp_root("rms_newsys_")
        self.src = build_esde_tree(self.dir / "src")
        self.meta = build_esde_tree(self.dir / "meta")
        self.roms = self.dir / "roms"
        write_file(self.roms / "ps2" / "MGS2.iso", b"m")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)

    def _collection(self, with_separate_roms=False):
        cid = self.api.create_collection("C", "es-de", str(self.meta),
                                         rom_path=str(self.roms) if with_separate_roms else None)["data"]["id"]
        wait_job(self.api, self.api.start_scan(cid)["data"]["jobId"])
        return cid

    def test_creating_a_system_makes_an_empty_rom_folder(self):
        cid = self._collection()
        result = self.api.create_system(cid, "fbneo")
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.meta / "fbneo").is_dir())
        self.assertEqual(list((self.meta / "fbneo").iterdir()), [])
        systems = [s["system"] for s in self.api.collection_detail(cid)["data"]["systems"]]
        self.assertIn("fbneo", systems)

    def test_the_new_system_goes_next_to_the_existing_rom_folders(self):
        cid = self._collection(with_separate_roms=True)
        result = self.api.create_system(cid, "snes")
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.roms / "snes").is_dir(), "ROM 폴더를 따로 쓰는 Collection인데 다른 곳에 만들었다")
        self.assertFalse((self.meta / "snes").exists())

    def test_bad_or_duplicate_names_are_refused(self):
        cid = self._collection()
        for bad in ("", "  ", "..", ".hidden", "a/b", "a\b", "x:y"):
            self.assertFalse(self.api.create_system(cid, bad)["ok"], repr(bad))
        self.assertFalse(self.api.create_system(cid, "PS2")["ok"], "대소문자만 다른 이름은 이미 있는 System이다")

    def test_a_name_es_de_does_not_know_is_created_but_flagged(self):
        cid = self._collection()
        self.assertTrue(self.api.create_system(cid, "snes")["data"]["knownToEsde"])
        self.assertFalse(self.api.create_system(cid, "fbneo-action")["data"]["knownToEsde"])

    def test_pasting_a_system_the_target_lacks_puts_the_rom_in_the_rom_folder(self):
        """예전에는 ROM이 메타데이터 폴더로 들어갔다(사용자 피드백)."""
        cid = self._collection(with_separate_roms=True)
        scid = self.api.create_collection("S", "es-de", str(self.src))["data"]["id"]
        wait_job(self.api, self.api.start_scan(scid)["data"]["jobId"])
        # 대상에는 ps2 System이 있으니 없는 System(snes)로 시험한다: 원본에 snes를 만든다.
        write_file(self.src / "snes" / "Mario.sfc", b"s" * 20)
        write_file(self.src / "gamelists" / "snes" / "gamelist.xml",
                   '<?xml version="1.0"?>\n<gameList><game><path>./Mario.sfc</path><name>Mario</name></game></gameList>')
        wait_job(self.api, self.api.start_scan(scid, True)["data"]["jobId"])
        uid = next(r["romUid"] for r in self.api.list_rows(scid)["data"]["rows"] if r["file"] == "Mario.sfc")
        self.api.copy_selection(scid, [uid])
        self.api.paste(cid)
        from tests.fixtures import wait_idle
        self.api.start_apply(cid)
        wait_idle(self.api)
        self.assertTrue((self.roms / "snes" / "Mario.sfc").exists(), "ROM이 ROM 폴더로 가지 않았다")
        self.assertFalse((self.meta / "snes" / "Mario.sfc").exists(), "ROM이 메타데이터 폴더로 들어갔다")
