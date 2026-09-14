"""ROM 폴더에 섞인 세이브·설정·로그·개발 파일은 게임으로 잡지 않는다.

모든 Adapter가 adapters/base.py의 목록 하나를 쓴다. 디스크 이미지와 압축 형식은
어떤 경우에도 ROM으로 남아야 한다(.cue/.bin/.iso/.chd/.zip/.7z).
"""

import unittest

import adapters.emulationstation
import adapters.es_de
import adapters.launchbox
import adapters.pegasus
from adapters.base import NON_ROM_EXTENSIONS
from bridge.api import Api
from tests.fixtures import build_esde_tree, temp_root, wait_job, write_file

SIDECARS = ("FFX.sav", "FFX.srm", "FFX.state3", "core.cfg", "retroarch.log", "Main.java",
            "Main.class", "meta.json", "info.nfo", "cache.sqlite", "download.part", "card.mcr")
REAL_ROMS = ("Disc1.cue", "Disc1.bin", "Game.chd", "Pack.zip", "Pack.7z")


class RomExtensionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_ext_")
        self.root = build_esde_tree(self.dir / "esde")
        for name in SIDECARS:
            write_file(self.root / "ps2" / name, b"x")
        for name in REAL_ROMS:
            write_file(self.root / "ps2" / name, b"r" * 10)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def files(self):
        return {row["file"] for row in self.api.list_rows(self.cid, limit=1000)["data"]["rows"]}

    def test_sidecar_and_development_files_are_not_listed(self):
        self.assertEqual(self.files() & set(SIDECARS), set())

    def test_disc_images_and_archives_are_always_roms(self):
        self.assertTrue(set(REAL_ROMS) <= self.files(), self.files())

    def test_no_disc_or_archive_extension_is_ever_excluded(self):
        for ext in (".cue", ".bin", ".iso", ".chd", ".zip", ".7z", ".rvz", ".cso", ".m3u", ".exe"):
            self.assertNotIn(ext, NON_ROM_EXTENSIONS, ext)

    def test_every_adapter_uses_the_same_list(self):
        for module in (adapters.es_de, adapters.emulationstation, adapters.launchbox, adapters.pegasus):
            self.assertIs(module.NON_ROM_EXTENSIONS, NON_ROM_EXTENSIONS, module.__name__)


if __name__ == "__main__":
    unittest.main()
