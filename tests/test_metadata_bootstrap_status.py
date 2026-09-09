"""Collection 추가 직후의 metadata_status() 판정 (QA 재검토 P0, 2026-09-09).

사용자가 실제 GUI에서 본 증상: 정상적인 ES-DE 디렉토리를 골랐는데도 "메타데이터가
없습니다" 안내가 뜨고, Cancel을 눌러도 Collection에는 메타데이터가 이미 표시된다.

## 원인 추적

`offerMetadataBootstrap()`(gui_web/app.js)이 부르는 `metadata_status()`는
`app/metadata/service.py`의 `status()`로 이어진다. 이 함수는 System마다
`adapter.layout(collection, system)`으로 `metadata_file` 경로를 계산해
`provider.exists()`로 직접 확인한다 - Cache/스캔 결과를 참고하지 않고 항상
그 자리에서 실제 디스크를 본다. 실제 스캐너(`app/scan/scanner.py`의
`system_signature()`)도 **같은 `adapter.layout()`**을 호출해 같은
`metadata_file`을 본다 - 두 경로가 서로 다른 판정 기준을 쓰는 구조적 여지는
코드상 없다.

아래 테스트들로 직접 재현을 시도했으나(정상 ES-DE 트리를 단일 경로로 생성 /
ROM과 Metadata를 별도 경로로 분리 / 두 경로에 같은 값을 중복 전달), 모두
`missing == []`로 정확하게 나왔다 - **재현하지 못했다.**

가장 유력한 실제 원인은 이번에 없앤 **예전 3필드 입력 화면**(Metadata 폴더 /
ROM 폴더(선택) / Media 폴더(선택))이다. 세 칸을 각각 어디에 채워야 하는지
설명이 부실해, ES-DE 루트 폴더를 "ROM 폴더" 칸에만 넣고 "Metadata 폴더" 칸을
비워 두는 식의 오조합이 쉬웠다. 이번 P0로 화면을 대표 폴더 한 칸으로 줄였으므로
이 오조합 자체가 구조적으로 불가능해졌다.

이 파일은 그 회귀를 지키는 테스트다 - 단일 경로 흐름에서 metadata_status()가
정확한 값을 내는지 잠근다. 재현 안 된 것은 재현 안 된 대로 정직하게 남긴다
(POLICY/구현 버그로 확정할 근거가 없다는 뜻이지, "고쳤다"는 뜻이 아니다).
"""

import unittest

from bridge.api import Api
from tests.fixtures import build_esde_tree, temp_root, write_file


class MetadataStatusAfterSinglePathCreate(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_metastatus_")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)

    def test_well_formed_esde_tree_reports_no_missing_metadata(self):
        """새 화면이 실제로 보내는 형태 - 대표 폴더 하나, rom_path/media_path 없음."""
        root = build_esde_tree(self.dir / "esde")
        r = self.api.create_collection("Test", "es-de", str(root))
        self.assertTrue(r["ok"], r.get("error"))
        status = self.api.metadata_status(r["data"]["id"])
        self.assertTrue(status["ok"])
        self.assertEqual(status["data"]["missing"], [])
        ps2 = next(s for s in status["data"]["systems"] if s["system"] == "ps2")
        self.assertTrue(ps2["hasMetadata"])

    def test_metadata_and_rom_in_separate_roots_still_reports_no_missing(self):
        """"고급"에서 ROM 폴더를 따로 지정하는 경로 - metadata_file은 대표 폴더
        기준으로 계산되므로 ROM 위치와 무관하게 정확해야 한다."""
        meta_root = self.dir / "meta"
        rom_root = self.dir / "roms"
        write_file(meta_root / "gamelists" / "ps2" / "gamelist.xml",
                  b"<gameList><game><path>./FFX.iso</path><name>FFX</name></game></gameList>")
        write_file(meta_root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"x")
        write_file(rom_root / "ps2" / "FFX.iso", b"romdata")

        r = self.api.create_collection("Test", "es-de", str(meta_root),
                                       rom_path=str(rom_root))
        self.assertTrue(r["ok"], r.get("error"))
        status = self.api.metadata_status(r["data"]["id"])
        self.assertTrue(status["ok"])
        self.assertEqual(status["data"]["missing"], [])

    def test_root_and_rom_path_pointing_at_the_same_folder_is_harmless(self):
        """예전 3필드 화면에서 실제로 벌어졌을 법한 오조합 - 두 칸에 같은 값을
        중복으로 채워도(구 UI의 fallback 로직) 잘못 판정되지 않아야 한다."""
        root = build_esde_tree(self.dir / "esde")
        r = self.api.create_collection("Test", "es-de", str(root), rom_path=str(root))
        self.assertTrue(r["ok"], r.get("error"))
        status = self.api.metadata_status(r["data"]["id"])
        self.assertTrue(status["ok"])
        self.assertEqual(status["data"]["missing"], [])

    def test_a_system_that_genuinely_has_no_gamelist_is_reported_missing(self):
        """진짜 없는 경우까지 숨기면 안 된다 - false negative를 고치려다 반대쪽
        (false positive 은폐)으로 넘어가지 않는지 확인한다."""
        root = self.dir / "esde"
        write_file(root / "gamelists" / "ps2" / "gamelist.xml",
                  b"<gameList><game><path>./FFX.iso</path><name>FFX</name></game></gameList>")
        write_file(root / "ps2" / "FFX.iso", b"r")
        write_file(root / "snes" / "Zelda.sfc", b"r")   # gamelist 없음

        r = self.api.create_collection("Test", "es-de", str(root))
        self.assertTrue(r["ok"], r.get("error"))
        status = self.api.metadata_status(r["data"]["id"])
        self.assertTrue(status["ok"])
        self.assertEqual(status["data"]["missing"], ["snes"])


if __name__ == "__main__":
    unittest.main()
