"""RetroArch 실행 모듈(app/launch/retroarch.py) - 실제 프로세스는 띄우지 않는다(popen 주입)."""

import unittest
from pathlib import Path

from app.launch import retroarch
from tests.fixtures import temp_root, write_file


class FakeProc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_ra_")
        self.exe = write_file(self.dir / "RetroArch" / "retroarch.exe", b"x")
        self.cores = self.dir / "RetroArch" / "cores"
        write_file(self.cores / "snes9x_libretro.dll", b"c")
        write_file(self.cores / "bsnes_libretro.dll", b"c")
        write_file(self.cores / "readme.txt", b"t")
        self.rom = write_file(self.dir / "ROMs" / "snes" / "Super Mario World (USA).sfc", b"r")
        self.calls = []

    def popen(self, code=None):
        def run(command, **kwargs):
            self.calls.append((command, kwargs))
            return FakeProc(code)
        return run

    def go(self, **over):
        popen = over.pop("popen", None) or self.popen()
        args = dict(exe_path=str(self.exe), cores_dir=str(self.cores), core_filename="snes9x_libretro.dll",
                    rom_path=str(self.rom), system="snes")
        args.update(over)
        return retroarch.launch(**args, popen=popen, startup_check_sec=0)

    def test_launch_passes_arguments_as_a_list_with_core_rom_and_windowed_override(self):
        result = self.go()
        self.assertTrue(result.ok, result.error)
        command, kwargs = self.calls[0]
        self.assertEqual(command[0], str(self.exe))
        self.assertEqual(command[1:3], ["-L", str(self.cores / "snes9x_libretro.dll")])
        self.assertTrue(command[3].startswith("--appendconfig="))
        self.assertEqual(command[-1], str(self.rom))          # 공백·괄호가 있어도 한 인자
        self.assertEqual(kwargs["cwd"], str(self.exe.parent))  # 포터블 설치 대응

    def test_unverified_system_can_launch_with_an_explicit_core(self):
        result = self.go(system="ps2")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(self.calls), 1)

    def test_missing_retroarch_or_folder_instead_of_file(self):
        self.assertEqual(self.go(exe_path="").error_kind, "retroarch_missing")
        self.assertEqual(self.go(exe_path=str(self.exe.parent)).error_kind, "retroarch_missing")

    def test_missing_rom(self):
        self.assertEqual(self.go(rom_path=str(self.dir / "nope.sfc")).error_kind, "rom_missing")

    def test_core_unset_and_core_file_missing(self):
        self.assertEqual(self.go(core_filename="").error_kind, "core_unset")
        self.assertEqual(self.go(core_filename="gone_libretro.dll").error_kind, "core_missing")
        self.assertEqual(self.go(cores_dir="").error_kind, "core_missing")
        self.assertEqual(self.calls, [])

    def test_process_dying_immediately_is_a_failure(self):
        result = self.go(popen=self.popen(code=1))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "launch_failed")

    def test_still_running_after_the_check_is_success(self):
        self.assertTrue(self.go(popen=self.popen(code=None)).ok)


class CoreHelpersTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_racore_")
        for name in ("snes9x_libretro.dll", "mgba_libretro.dll", "fbneo_libretro.dll", "notes.txt"):
            write_file(self.dir / name, b"c")

    def test_list_cores_only_core_files_sorted(self):
        self.assertEqual(retroarch.list_cores(self.dir),
                         ["fbneo_libretro.dll", "mgba_libretro.dll", "snes9x_libretro.dll"])
        self.assertEqual(retroarch.list_cores(self.dir / "nope"), [])
        self.assertEqual(retroarch.list_cores(""), [])

    def test_core_label(self):
        self.assertEqual(retroarch.core_label("snes9x_libretro.dll"), "snes9x")

    def test_defaults_fill_only_missing_systems_with_installed_candidates(self):
        available = retroarch.list_cores(self.dir)
        applied = retroarch.default_cores_for(["snes", "gba", "cps2", "n64", "SFC"], available,
                                              existing={"gba": "gpsp_libretro.dll"})
        self.assertEqual(applied, {"snes": "snes9x_libretro.dll", "cps2": "fbneo_libretro.dll",
                                   "sfc": "snes9x_libretro.dll"})

    def test_verified(self):
        self.assertFalse(retroarch.is_verified("PS2"))
        self.assertTrue(retroarch.is_verified("snes"))


if __name__ == "__main__":
    unittest.main()
