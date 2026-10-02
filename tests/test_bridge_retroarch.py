"""RetroArch 실행 - bridge 계층(설정 저장, Core 우선순위, ROM 경로 계산)."""

import unittest
from pathlib import Path
from unittest import mock

from app.launch import retroarch
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, temp_root, wait_job, write_file


class FakeProc:
    def poll(self):
        return None


class BridgeRetroarchTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_bra_")
        self.root = build_custom_esde_tree(self.dir / "esde", "snes", [
            {"filename": "Super Mario World (USA).sfc", "title": "Super Mario World"},
            {"filename": "Ghost.sfc", "title": "Ghost", "rom": False},
        ])
        self.exe = write_file(self.dir / "RetroArch" / "retroarch.exe", b"x")
        self.cores = self.dir / "RetroArch" / "cores"
        for name in ("snes9x_libretro.dll", "bsnes_libretro.dll"):
            write_file(self.cores / name, b"c")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])
        self.calls = []

    def uid(self, filename):
        return next(r["romUid"] for r in self.api.list_rows(self.cid, limit=10)["data"]["rows"] if r["file"] == filename)

    def configure(self):
        return self.api.set_retroarch_paths(str(self.exe), str(self.cores))

    def launch(self, filename="Super Mario World (USA).sfc"):
        def popen(command, **kwargs):
            self.calls.append(command)
            return FakeProc()
        with mock.patch.object(retroarch.subprocess, "Popen", popen), mock.patch.object(retroarch.time, "sleep"):
            return self.api.launch_game(self.cid, self.uid(filename))

    def test_settings_start_empty_and_list_installed_cores_after_paths(self):
        s = self.api.retroarch_settings()["data"]
        self.assertEqual((s["retroarchPath"], s["cores"]), ("", []))
        self.assertIn("ps2", s["unverified"])
        s = self.configure()["data"]
        self.assertEqual(s["cores"], ["bsnes_libretro.dll", "snes9x_libretro.dll"])

    def test_launch_without_core_asks_for_one(self):
        self.configure()
        r = self.launch()
        self.assertFalse(r["ok"])
        self.assertEqual(r["errorKind"], "core_unset")
        self.assertEqual(self.calls, [])

    def test_launch_uses_rom_path_from_layout_and_system_core(self):
        self.configure()
        self.assertTrue(self.api.set_system_core("snes", "snes9x_libretro.dll")["ok"])
        r = self.launch()
        self.assertTrue(r["ok"], r)
        command = self.calls[0]
        self.assertEqual(command[2], str(self.cores / "snes9x_libretro.dll"))
        self.assertEqual(Path(command[-1]), self.root / "snes" / "Super Mario World (USA).sfc")

    def test_game_core_overrides_system_core_and_can_be_cleared(self):
        self.configure()
        self.api.set_system_core("snes", "snes9x_libretro.dll")
        self.api.set_game_core("snes", "Super Mario World (USA).sfc", "bsnes_libretro.dll")
        info = self.api.retroarch_game_info(self.cid, self.uid("Super Mario World (USA).sfc"))["data"]
        self.assertEqual(info["effectiveCore"], "bsnes_libretro.dll")
        self.launch()
        self.assertEqual(self.calls[-1][2], str(self.cores / "bsnes_libretro.dll"))
        self.api.set_game_core("snes", "Super Mario World (USA).sfc", None)
        self.launch()
        self.assertEqual(self.calls[-1][2], str(self.cores / "snes9x_libretro.dll"))

    def test_core_not_in_cores_folder_is_rejected(self):
        self.configure()
        self.assertFalse(self.api.set_system_core("snes", "nope_libretro.dll")["ok"])
        self.assertFalse(self.api.set_game_core("snes", "x.sfc", "nope_libretro.dll")["ok"])

    def test_system_and_game_cores_survive_each_other(self):
        """save_app_settings는 한 단계 깊이만 병합한다 - 한쪽 저장이 다른 쪽을 지우면 안 된다."""
        self.configure()
        self.api.set_system_core("snes", "snes9x_libretro.dll")
        self.api.set_game_core("snes", "A.sfc", "bsnes_libretro.dll")
        self.api.set_retroarch_paths(str(self.exe), str(self.cores))
        s = self.api.retroarch_settings()["data"]
        self.assertEqual(s["systemCores"], {"sfc": "snes9x_libretro.dll"})
        self.assertEqual(s["resolvedSystemCores"]["snes"], "snes9x_libretro.dll")
        self.assertEqual(s["gameCores"], {"sfc/A.sfc": "bsnes_libretro.dll"})

    def test_apply_default_cores_fills_only_missing(self):
        self.assertFalse(self.api.apply_default_cores(["snes"])["ok"])   # Core 폴더 없음
        self.configure()
        r = self.api.apply_default_cores(["snes", "gba"])["data"]
        self.assertEqual(r["applied"], {"snes": "snes9x_libretro.dll"})
        self.api.set_system_core("snes", "bsnes_libretro.dll")
        self.assertEqual(self.api.apply_default_cores(["snes"])["data"]["count"], 0)

    def test_metadata_only_row_cannot_launch(self):
        self.configure()
        self.api.set_system_core("snes", "snes9x_libretro.dll")
        r = self.launch("Ghost.sfc")
        self.assertEqual(r["errorKind"], "rom_missing")

    def test_missing_retroarch_path(self):
        self.api.set_retroarch_paths("", str(self.cores))
        self.api.set_system_core("snes", "snes9x_libretro.dll")
        self.assertEqual(self.launch()["errorKind"], "retroarch_missing")


if __name__ == "__main__":
    unittest.main()


class ArchiveLaunchTests(BridgeRetroarchTests):
    """Archive 항목도 ROM 위치가 기록돼 있으면 실행된다 - 화면이 막을 이유가 없었다."""

    def _ingest(self):
        # Archive는 저장할 디렉토리를 정한 뒤에만 수집한다(사용자 결정).
        self.api.save_archive_config({"archiveDir": str(self.dir / "Archives")})
        self.api.start_archive_ingest(self.cid, {"kind": "all"})
        from tests.fixtures import wait_idle
        wait_idle(self.api)
        return next(r["romIdentityId"] for r in self.api.archive_rows()["data"]["rows"]
                    if r["file"] == "Super Mario World (USA).sfc")

    def _launch_archive(self, rid):
        def popen(command, **kwargs):
            self.calls.append(command)
            return FakeProc()
        with mock.patch.object(retroarch.subprocess, "Popen", popen), mock.patch.object(retroarch.time, "sleep"):
            return self.api.launch_game("archive", rid)

    def test_archive_row_reports_whether_a_rom_is_recorded(self):
        self._ingest()
        rows = {r["file"]: r for r in self.api.archive_rows()["data"]["rows"]}
        self.assertTrue(rows["Super Mario World (USA).sfc"]["present"])
        self.assertFalse(rows["Ghost.sfc"]["present"])

    def test_archive_item_launches_from_recorded_rom_path(self):
        rid = self._ingest()
        self.configure()
        self.api.set_system_core("snes", "snes9x_libretro.dll")
        r = self._launch_archive(rid)
        self.assertTrue(r["ok"], r)
        self.assertEqual(Path(self.calls[0][-1]), self.root / "snes" / "Super Mario World (USA).sfc")

    def test_archive_item_without_rom_says_so(self):
        self._ingest()
        rid = next(r["romIdentityId"] for r in self.api.archive_rows()["data"]["rows"]
                   if r["file"] == "Ghost.sfc")
        self.configure()
        r = self._launch_archive(rid)
        self.assertFalse(r["ok"])
        self.assertEqual(r["errorKind"], "rom_missing")
