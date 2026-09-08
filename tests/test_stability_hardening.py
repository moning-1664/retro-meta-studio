"""Apply 안정성 회귀 테스트 (Phase 7.10 Stability Hardening).

여기 있는 테스트는 전부 **사용자의 ROM/media가 사라지거나 엉뚱하게 덮어써지는**
시나리오다. 기능이 없는 것보다 조용히 데이터를 잃는 쪽이 훨씬 나쁘다.

공통 원칙 하나: **사용자가 승인한 것은 "그 시점의 그 파일"이다.** Plan을 만들 때
본 파일과 Apply 직전의 파일이 다르면, 조용히 진행하지 말고 멈춰야 한다. 크기만
비교하면 부족하다 - 같은 크기의 다른 ROM으로 바뀌는 것은 ROM 관리에서 아주 흔하다.
"""

import unittest
from pathlib import Path

import file_ops
from adapters import get_adapter
from app.model.collection import (Collection, StorageLocation, SystemEntry,
                                  STORAGE_INTERNAL)
from app.model.plan import (OP_ADD, Plan, RESOLVE_OVERWRITE, STATUS_APPLIED,
                            STATUS_FAILED, STATUS_INVALID, STATUS_PARTIAL)
from app.plan import builder, validator
from app.plan.applier import apply_plan
from app.store.cache import CacheStore
from bridge.api import Api
from storage.local import LocalStorageProvider
from tests.fixtures import build_custom_esde_tree, scan, temp_root

PROVIDER = LocalStorageProvider()


def touch(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ======================================================================
# P0-1. 부분 스캔이 스캔하지 않은 media를 지운다
# ======================================================================
class PartialScanKeepsUnscannedMediaTests(unittest.TestCase):
    """커버만 다시 읽었는데 비디오 정보가 캐시에서 사라지면 안 된다.

    스캐너는 속도를 위해 "커버 먼저, 비디오 나중"으로 두 번에 나눠 읽는다. 그런데
    `replace_system()`이 그 System의 행을 통째로 지우고 다시 넣기 때문에, **이번에
    읽지 않은 media type의 행까지 함께 사라졌다.**

    사용자에게는 "비디오가 갑자기 없어졌다"로 보이고, 그 상태에서 Plan을 만들면
    비디오가 복사 대상에서 빠진다.
    """

    def setUp(self):
        self.dir = temp_root("rms_partial_")
        self.root = self.dir / "esde"
        build_custom_esde_tree(self.root, "ps2", [{"filename": "FFX.iso", "title": "FFX"}])
        media = self.root / "downloaded_media" / "ps2"
        touch(media / "covers" / "FFX.png", b"c" * 10)
        touch(media / "videos" / "FFX.mp4", b"v" * 100)
        touch(media / "wheel" / "FFX.png", b"w" * 20)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("t", "es-de", str(self.root))["data"]["id"]

    def _media_types(self):
        rows = self.api.list_rows(self.cid, limit=10)["data"]["rows"]
        row = self.api.workspace.open(self.cid).get_row(rows[0]["romUid"])
        return sorted(m["media_type"] for m in row["media"])

    def _scan(self, media_types=None):
        self.api.workspace.scan(self.cid, media_types=media_types, force=True)

    def test_a_full_scan_sees_every_media_type(self):
        self._scan()
        self.assertEqual(self._media_types(), ["covers", "videos", "wheel"])

    def test_scanning_covers_only_keeps_the_other_types(self):
        """이것이 이 파일의 P0다 - 읽지 않은 것을 지우면 안 된다."""
        self._scan()
        self._scan(media_types=["covers"])
        self.assertEqual(self._media_types(), ["covers", "videos", "wheel"],
                         "부분 스캔이 스캔하지 않은 media를 지웠다")

    def test_the_scanned_type_is_actually_refreshed(self):
        """지우지 않는 것만으로는 부족하다 - 스캔한 타입은 갱신돼야 한다."""
        self._scan()
        touch(self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"c" * 999)
        self._scan(media_types=["covers"])

        rows = self.api.list_rows(self.cid, limit=10)["data"]["rows"]
        row = self.api.workspace.open(self.cid).get_row(rows[0]["romUid"])
        covers = next(m for m in row["media"] if m["media_type"] == "covers")
        self.assertEqual(int(covers["size"]), 999)

    def test_a_removed_file_of_a_scanned_type_does_disappear(self):
        """스캔한 타입 안에서 사라진 파일은 사라져야 한다 - 아무것도 안 지우는 게 답이 아니다."""
        self._scan()
        (self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png").unlink()
        self._scan(media_types=["covers"])
        self.assertEqual(self._media_types(), ["videos", "wheel"])

    def test_full_scan_after_partial_scan_matches_a_plain_full_scan(self):
        """full -> partial -> full 이 처음부터 full 한 번과 같아야 한다."""
        self._scan()
        self._scan(media_types=["covers"])
        self._scan()
        self.assertEqual(self._media_types(), ["covers", "videos", "wheel"])

    def test_a_partial_scan_of_a_type_with_no_files_keeps_the_rest(self):
        """그 타입에 파일이 하나도 없어도 다른 타입을 지우면 안 된다."""
        self._scan()
        (self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png").unlink()
        self._scan(media_types=["covers"])
        self.assertEqual(self._media_types(), ["videos", "wheel"])


# ======================================================================
# 공통 - Plan/Apply 테스트를 위한 최소 Collection
# ======================================================================
class PlanCase(unittest.TestCase):
    """source Collection에서 target Collection으로 ADD하는 최소 구성."""

    def setUp(self):
        file_ops.select_engine(file_ops.ENGINE_WORKER)
        self.addCleanup(file_ops.select_engine, file_ops.ENGINE_AUTO)

        self.dir = temp_root("rms_plan_")
        self.src_root = self.dir / "source"
        self.dst_root = self.dir / "target"
        build_custom_esde_tree(self.src_root, "ps2", [{"filename": "FFX.iso", "title": "FFX"}])
        build_custom_esde_tree(self.dst_root, "ps2", [])

        self.src_rom = self.src_root / "ps2" / "FFX.iso"
        self.src_rom.write_bytes(b"NEW" * 100)
        self.src_cover = touch(self.src_root / "downloaded_media" / "ps2" / "covers" / "FFX.png",
                               b"n" * 50)

        self.collection = Collection(
            id="dst", name="dst", frontend="es-de", root_path=str(self.dst_root),
            storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "Internal",
                                      str(self.dst_root))],
            systems=[SystemEntry("ps2", STORAGE_INTERNAL)])
        self.adapter = get_adapter("es-de")
        self.cache = CacheStore.open_for_collection(self.dir / "cache", "dst")
        self.addCleanup(self.cache.close)
        self.plan = Plan("dst")

    @property
    def dest_rom(self) -> Path:
        return self.dst_root / "ps2" / "FFX.iso"

    def item(self, with_media=True):
        media = ([{"type": "covers", "path": str(self.src_cover),
                   "size": self.src_cover.stat().st_size}] if with_media else [])
        return {"system": "ps2", "filename": "FFX.iso",
                "rom": {"path": str(self.src_rom), "size": self.src_rom.stat().st_size},
                "media": media, "fields": {"name": "FFX"}}

    def plan_one(self, with_media=True):
        return builder.plan_add(self.plan, self.collection, PROVIDER,
                                [self.item(with_media=with_media)])

    def entry(self):
        return self.plan.entries[0]

    def validate(self):
        return validator.validate(self.plan, self.collection, self.cache, PROVIDER)

    def apply(self):
        return apply_plan(self.plan, self.collection, self.cache, None, PROVIDER)


# ======================================================================
# P0-2. 승인한 대상과 실제로 덮어쓸 대상이 같은지
# ======================================================================
class OverwriteTargetIsRecheckedTests(PlanCase):
    """사용자가 승인한 것은 «그 시점의 그 파일을 덮어쓴다»이다.

    «Apply 시점에 그 경로에 있는 아무 파일이나 덮어쓴다»가 아니다. Plan 승인과 Apply
    사이에 다른 프로그램이 대상 파일을 바꿔치기했다면 그 승인은 더 이상 유효하지 않다.
    """

    def setUp(self):
        super().setUp()
        touch(self.dest_rom, b"OLD" * 100)          # 크기는 같고 내용만 다르다
        self.plan_one(with_media=False)
        self.assertTrue(self.entry().conflicts, "충돌로 잡히지 않았다")
        builder.resolve_conflict(self.plan, self.collection, PROVIDER,
                                 self.entry().key, RESOLVE_OVERWRITE)

    def test_an_untouched_target_applies_normally(self):
        self.assertTrue(self.validate()["ok"], "아무도 안 건드렸는데 막혔다")
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), b"NEW" * 100)

    def test_a_replaced_target_stops_the_apply(self):
        """대상이 다른 파일로 바뀌었다 - 승인은 그 파일에 대한 것이 아니었다."""
        touch(self.dest_rom, b"OTHER" * 60)
        result = self.validate()
        self.assertFalse(result["ok"], "바뀐 대상을 그대로 덮어쓰려 한다")
        self.assertEqual(self.entry().status, STATUS_INVALID)

    def test_a_same_size_replacement_is_detected(self):
        """크기만 비교하면 이걸 못 잡는다 - 같은 이름 다른 CRC는 ROM에서 흔하다.

        외부 도구가 파일을 "교체"하는 방식(지우고 새로 만들기)을 그대로 흉내낸다.
        그래야 파일 식별자가 실제로 바뀐다.
        """
        original = self.dest_rom.stat()
        self.dest_rom.unlink()
        touch(self.dest_rom, b"XYZ" * 100)
        self.assertEqual(self.dest_rom.stat().st_size, original.st_size)
        self.assertFalse(self.validate()["ok"], "같은 크기의 다른 파일을 못 알아봤다")

    def test_the_known_limit_is_written_down(self):
        """**크기/시각/식별자가 셋 다 같으면 구분할 수 없다.**

        같은 시계 tick 안에서 같은 파일을 제자리 덮어쓰면 수정 시각도 파일 식별자도
        바뀌지 않는다. 그것까지 잡으려면 내용을 해싱해야 하는데, 4GB짜리 ISO 수천 개를
        Plan 만들 때마다 해싱하는 것은 도구를 못 쓰게 만든다.

        이 테스트는 그 한계를 **숨기지 않고 기록해 두기 위한 것**이다. 나중에 깊은
        검증(hash) 옵션을 붙일 때 여기가 출발점이 된다.
        """
        before = self.dest_rom.stat()
        self.dest_rom.write_bytes(b"XYZ" * 100)     # 제자리 덮어쓰기
        after = self.dest_rom.stat()
        if (before.st_mtime_ns, before.st_ino) != (after.st_mtime_ns, after.st_ino):
            self.skipTest("이 파일 시스템에서는 제자리 덮어쓰기도 흔적을 남긴다")
        self.assertTrue(self.validate()["ok"],
                        "구분할 수 없는 경우인데 구분한 척한다")

    def test_a_deleted_target_is_also_stale(self):
        """지워졌다면 «덮어쓰기» 승인은 의미가 없다. 새로 만드는 것은 다른 결정이다."""
        self.dest_rom.unlink()
        self.assertFalse(self.validate()["ok"])

    def test_the_stale_target_is_not_overwritten_even_if_apply_runs(self):
        """검증을 건너뛰고 Apply가 돌아도 바뀐 대상을 덮어쓰지 않아야 한다."""
        touch(self.dest_rom, b"OTHER" * 60)
        self.validate()
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), b"OTHER" * 60,
                         "승인받지 않은 파일을 덮어썼다")


# ======================================================================
# P0-3. 덮어쓰기가 도중에 실패하면 원본을 되돌린다
# ======================================================================
class OverwriteRollbackRestoresOriginalTests(PlanCase):
    """**copy 성공 != transaction 성공.**

    기존 파일을 덮어쓴 뒤 gamelist 기록이 실패하면, 지금까지는 새 파일이 그대로
    남았다. 사용자 입장에서는 «실패했다»는 메시지를 보면서 원본 ROM은 이미 없어진
    상태다. 새로 만든 파일만 되돌리는 롤백으로는 이 경우를 못 살린다.
    """

    def setUp(self):
        super().setUp()
        self.original = b"OLD" * 100
        touch(self.dest_rom, self.original)
        self.plan_one(with_media=False)
        builder.resolve_conflict(self.plan, self.collection, PROVIDER,
                                 self.entry().key, RESOLVE_OVERWRITE)
        self.validate()

    def _break_metadata(self):
        def boom(*_a, **_k):
            raise OSError("gamelist를 쓸 수 없다")
        self.adapter.write_index, self._saved = boom, self.adapter.write_index
        self.addCleanup(lambda: setattr(type(self.adapter), "write_index", self._saved)
                        if False else setattr(self.adapter, "write_index", self._saved))

    def test_a_successful_overwrite_leaves_the_new_file_and_no_backup(self):
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), b"NEW" * 100)
        leftovers = [p.name for p in self.dest_rom.parent.iterdir()
                     if p.name != self.dest_rom.name]
        self.assertEqual(leftovers, [], f"쓸데없는 파일이 남았다: {leftovers}")

    def test_a_failure_after_the_copy_restores_the_original(self):
        """이 파일 전체에서 가장 중요한 테스트다."""
        self._break_metadata()
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), self.original,
                         "덮어쓴 뒤 실패했는데 원본이 사라졌다")

    def test_the_entry_is_reported_as_failed_not_applied(self):
        self._break_metadata()
        self.apply()
        self.assertIn(self.entry().status, (STATUS_FAILED, STATUS_PARTIAL))
        self.assertNotEqual(self.entry().status, STATUS_APPLIED)

    def test_no_backup_file_is_left_behind_after_a_failure(self):
        """되돌린 뒤에도 정체불명의 .backup이 남으면 다음 스캔에 유령 항목이 뜬다."""
        self._break_metadata()
        self.apply()
        names = sorted(p.name for p in self.dest_rom.parent.iterdir())
        self.assertEqual(names, ["FFX.iso"], f"남은 파일: {names}")

    def test_a_copy_failure_leaves_the_original_intact(self):
        """복사 자체가 실패한 경우에도 원본은 그대로여야 한다."""
        self.src_rom.unlink()
        self.apply()
        self.assertTrue(self.dest_rom.exists(), "원본이 사라졌다")
        self.assertEqual(self.dest_rom.read_bytes(), self.original)


# ======================================================================
# P1-4. 원본이 같은 크기의 다른 파일로 바뀐 경우
# ======================================================================
class SourceChangeDetectionTests(PlanCase):
    def setUp(self):
        super().setUp()
        self.plan_one(with_media=False)
        self.validate()   # snapshot이 잡히는 시점

    def test_an_untouched_source_is_fine(self):
        self.assertTrue(self.validate()["ok"])

    def test_a_resized_source_is_rejected(self):
        self.src_rom.write_bytes(b"N" * 5)
        self.assertFalse(self.validate()["ok"])

    def test_a_same_size_source_replacement_is_rejected(self):
        """크기만 보면 통과한다 - 그래서 mtime/file_id까지 봐야 한다.

        외부 도구의 교체(지우고 새로 만들기)를 그대로 흉내낸다. 제자리 덮어쓰기는
        같은 tick 안에서는 흔적이 남지 않아 원리적으로 구분할 수 없다 -
        `OverwriteTargetIsRecheckedTests.test_the_known_limit_is_written_down` 참고.
        """
        self.src_rom.unlink()
        self.src_rom.write_bytes(b"OTH" * 100)
        self.assertEqual(self.src_rom.stat().st_size, len(b"NEW" * 100))
        self.assertFalse(self.validate()["ok"], "같은 크기의 다른 원본을 못 알아봤다")


# ======================================================================
# P1-5. Delete 대상 media가 바뀐 경우
# ======================================================================
class DeleteChecksMediaTests(unittest.TestCase):
    """Plan을 만든 뒤 커버가 다른 그림으로 바뀌었다면 그것은 승인 대상이 아니다."""

    def setUp(self):
        self.dir = temp_root("rms_del_")
        self.root = self.dir / "esde"
        build_custom_esde_tree(self.root, "ps2", [{"filename": "FFX.iso", "title": "FFX"}])
        self.cover = touch(self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png",
                           b"c" * 40)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("t", "es-de", str(self.root))["data"]["id"]
        scan(self.api, self.cid)
        self.rom_uid = self.api.list_rows(self.cid, limit=10)["data"]["rows"][0]["romUid"]
        self.api.plan_delete(self.cid, [self.rom_uid])

    def _validate(self):
        return self.api.validate_plan(self.cid)["data"]

    def test_an_untouched_delete_is_valid(self):
        self.assertTrue(self._validate()["ok"])

    def test_a_changed_cover_stops_the_delete(self):
        touch(self.cover, b"DIFFERENT" * 9)
        self.assertFalse(self._validate()["ok"], "바뀐 media를 그대로 지우려 한다")

    def test_a_same_size_cover_replacement_is_detected(self):
        touch(self.cover, b"d" * 40)
        self.assertFalse(self._validate()["ok"], "같은 크기의 다른 media를 못 알아봤다")

    def test_a_cover_that_vanished_does_not_block_the_delete(self):
        """지우려던 것이 이미 없는 것은 문제가 아니다 - 목적이 이미 달성됐다."""
        self.cover.unlink()
        self.assertTrue(self._validate()["ok"])


# ======================================================================
# P1-6. 용량 판정은 실제 여유 공간을 본다
# ======================================================================
class CapacityUsesActualFreeSpaceTests(PlanCase):
    """Cache는 «빠른 예상값»이지 파일 시스템의 진실이 아니다.

    Cache가 마지막으로 본 사용량과 실제 사용량은 언제든 어긋난다 - 다른 프로그램이
    같은 디스크에 파일을 쓰기 때문이다. 최종 판정은 실제 여유 공간으로 해야 한다.
    """

    def test_a_plan_larger_than_the_free_space_is_blocked(self):
        self.plan_one(with_media=False)
        entry = self.entry()
        free = PROVIDER.volume_info(str(self.dst_root)).free_bytes
        if free is None:
            self.skipTest("여유 공간을 읽을 수 없는 볼륨")
        # 실제 여유 공간보다 확실히 큰 계획으로 바꾼다.
        entry.physical_delta = {STORAGE_INTERNAL: free + 10 * 1024 ** 3}
        self.plan._delta = dict(entry.physical_delta)

        result = self.validate()
        self.assertTrue(result["blocked"], "여유 공간보다 큰 계획이 통과했다")

    def test_a_small_plan_is_not_blocked_by_a_stale_cache(self):
        """Cache가 실제와 달라도 실제로 여유가 있으면 막지 않는다."""
        self.plan_one(with_media=False)
        self.cache.set_system_stats("ps2", STORAGE_INTERNAL, STORAGE_INTERNAL,
                                    rom_count=1, rom_bytes=10 ** 15)   # 말도 안 되는 값
        self.assertFalse(self.validate()["blocked"], "Cache의 엉뚱한 값 때문에 막혔다")


# ======================================================================
# P1-7. 새로 발견된 System의 Storage
# ======================================================================
class NewSystemStorageTests(unittest.TestCase):
    """External에 있는 System을 Internal로 등록하면 용량 표시가 통째로 틀어진다."""

    def setUp(self):
        self.dir = temp_root("rms_newsys_")
        self.root = self.dir / "esde"
        self.ext = self.dir / "sdcard"
        build_custom_esde_tree(self.root, "ps2", [{"filename": "FFX.iso", "title": "FFX"}])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("t", "es-de", str(self.root))["data"]["id"]
        self.ext_id = self.api.add_external_storage(self.cid, "SD", str(self.ext))["data"]

    def _storage_of(self, system):
        collection = self.api.workspace.registry.get_collection(self.cid)
        entry = next((s for s in collection.systems if s.system == system), None)
        return entry.storage_id if entry else None

    def test_a_new_system_inside_the_collection_root_is_internal(self):
        (self.root / "snes").mkdir()
        (self.root / "snes" / "Zelda.sfc").write_bytes(b"r" * 10)
        scan(self.api, self.cid)
        self.assertEqual(self._storage_of("snes"), STORAGE_INTERNAL)

    def test_a_new_system_on_the_external_storage_is_external(self):
        """이것이 P1이다 - 실제 위치를 보지 않고 Internal로 박아 넣었다."""
        (self.ext / "gba").mkdir(parents=True)
        (self.ext / "gba" / "Metroid.gba").write_bytes(b"r" * 10)
        scan(self.api, self.cid)
        self.assertEqual(self._storage_of("gba"), self.ext_id,
                         "External에 있는 System을 Internal로 등록했다")

    def test_an_existing_mapping_is_not_overwritten_by_detection(self):
        """사용자가 정해 둔 배치를 스캔이 마음대로 되돌리면 안 된다."""
        (self.root / "snes").mkdir()
        (self.root / "snes" / "Zelda.sfc").write_bytes(b"r" * 10)
        scan(self.api, self.cid)
        self.api.workspace.registry.upsert_system(self.cid, "snes", self.ext_id)
        scan(self.api, self.cid)
        self.assertEqual(self._storage_of("snes"), self.ext_id)


# ======================================================================
# P1-8. Storage 경로 경계
# ======================================================================
class StoragePathBoundaryTests(unittest.TestCase):
    """`D:\\ROM`과 `D:\\ROM_BACKUP`은 다른 폴더다.

    단순 문자열 prefix 비교는 이 둘을 같은 것으로 본다. 그 결과 백업 폴더의 용량이
    ROM Storage에 더해지고, 화면의 내장/외장 표시가 실제와 어긋난다.
    """

    def collection(self, *roots):
        storages = [StorageLocation(f"s{i}", "internal" if i == 0 else "external",
                                    f"S{i}", root)
                    for i, root in enumerate(roots)]
        return Collection(id="c", name="c", frontend="es-de", root_path=roots[0],
                          storages=storages)

    def test_a_descendant_matches(self):
        c = self.collection(r"D:\ROM")
        self.assertEqual(c.storage_for_path(r"D:\ROM\PS2\game.iso"), "s0")

    def test_the_root_itself_matches(self):
        c = self.collection(r"D:\ROM")
        self.assertEqual(c.storage_for_path(r"D:\ROM"), "s0")
        self.assertEqual(c.storage_for_path("D:\\ROM\\"), "s0")

    def test_a_sibling_with_the_same_prefix_does_not_match(self):
        """이것이 P1이다."""
        c = self.collection(r"D:\ROM")
        self.assertEqual(c.storage_for_path(r"D:\ROM_BACKUP\game.iso"), STORAGE_INTERNAL)
        self.assertNotEqual(c.storage_for_path(r"D:\ROM_BACKUP\game.iso"), "s0")

    def test_the_longest_matching_root_still_wins(self):
        """기존 longest-match 동작은 유지해야 한다 - 중첩 Storage가 실제로 있다."""
        c = self.collection(r"D:\ROM", r"D:\ROM\PS2")
        self.assertEqual(c.storage_for_path(r"D:\ROM\PS2\game.iso"), "s1")
        self.assertEqual(c.storage_for_path(r"D:\ROM\SNES\game.sfc"), "s0")

    def test_forward_slashes_and_case_do_not_matter(self):
        c = self.collection(r"D:\ROM")
        self.assertEqual(c.storage_for_path("d:/rom/ps2/game.iso"), "s0")
        self.assertEqual(c.storage_for_path("d:/rom_backup/game.iso"), STORAGE_INTERNAL)


# ======================================================================
# P1-9. media가 사라지면 예상 용량도 다시 계산한다
# ======================================================================
class DeltaIsRecalculatedTests(PlanCase):
    """«복사할 것에서 뺐다»면 «용량 계산에서도 빼야» 한다.

    validation이 사라진 media를 source에서 빼면서 예상 바이트는 그대로 두면, 화면의
    Plan 용량과 실제로 일어날 일이 어긋난다. 그 차이만큼 Capacity Check도 틀린다.
    """

    def setUp(self):
        super().setUp()
        self.big = touch(self.src_root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4",
                         b"v" * 5000)

    def item(self, with_media=True):
        data = super().item(with_media=with_media)
        data["media"].append({"type": "videos", "path": str(self.big), "size": 5000})
        return data

    def test_the_estimate_matches_what_will_actually_be_copied(self):
        self.plan_one()
        before = self.entry().estimated_bytes
        self.big.unlink()
        self.validate()

        entry = self.entry()
        self.assertLess(entry.estimated_bytes, before, "사라진 media가 예상치에 남아 있다")
        self.assertEqual(entry.estimated_bytes,
                         sum(int(m["size"]) for m in entry.source["media"])
                         + int(entry.source["rom"]["size"]))

    def test_the_physical_delta_drops_too(self):
        self.plan_one()
        before = dict(self.entry().physical_delta)
        self.big.unlink()
        self.validate()
        self.assertLess(self.entry().physical_delta.get(STORAGE_INTERNAL, 0),
                        before.get(STORAGE_INTERNAL, 0),
                        "사라진 media가 물리 증감에 남아 있다")

    def test_the_plan_total_follows(self):
        """Plan 전체 합계도 따라가야 화면 표시가 맞는다."""
        self.plan_one()
        self.big.unlink()
        self.validate()
        self.assertEqual(self.plan.delta().get(STORAGE_INTERNAL, 0),
                         self.entry().physical_delta.get(STORAGE_INTERNAL, 0))


if __name__ == "__main__":
    unittest.main()
