"""실패를 **의도적으로 일으켜** 중간 상태를 검사한다 (Phase 7.12).

"코드상 안전해 보이는 것"과 "실제 파일시스템에서 실패를 발생시켜 안전함을 입증한 것"
사이에 간극이 있다. 이 파일은 그 간극을 메운다.

각 테스트는 실패 지점을 하나씩 지정해서 터뜨리고, 그때마다 **네 가지를 전부** 본다.

    파일     - 사용자 파일이 남았는가, 원본인가 새 것인가
    잔여물   - .rms-backup 같은 것이 남았는가
    상태     - FAILED / PARTIAL / APPLIED 중 무엇인가
    다음 실행 - 다시 돌렸을 때 같은 자리에서 다시 시작할 수 있는가

`status`만 보는 테스트는 이 파일에 두지 않는다 - 그건 "실패했다고 말했다"를 확인할 뿐
"실패해도 데이터가 무사하다"를 확인하지 못한다.
"""

import unittest
from pathlib import Path

import file_ops
from app.model.plan import (RESOLVE_OVERWRITE, STATUS_APPLIED, STATUS_FAILED,
                            STATUS_PARTIAL)
from app.plan import builder
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, write_file
from tests.test_stability_hardening import PlanCase, touch
from storage.local import LocalStorageProvider

PROVIDER = LocalStorageProvider()


class OverwriteMiddleFailureTests(PlanCase):
    """덮어쓰기 도중 각 단계에서 터뜨린다.

    ROM은 덮어쓰고 media는 새로 만드는 상황을 쓴다 - 그래야 "치워둔 원본"과
    "새로 만든 파일"이 한 항목 안에 함께 있고, 롤백이 둘을 다르게 다뤄야 한다.
    """

    def setUp(self):
        super().setUp()
        self.original = b"ORIGINAL ROM" * 40
        touch(self.dest_rom, self.original)
        self.dest_cover = (self.dst_root / "downloaded_media" / "ps2" / "covers" / "FFX.png")
        self.plan_one(with_media=True)
        builder.resolve_conflict(self.plan, self.collection, PROVIDER,
                                 self.entry().key, RESOLVE_OVERWRITE)
        self.validate()

    def _break(self, name):
        """Adapter 메서드 하나를 실패시킨다. 싱글턴이므로 속성을 지워서 되돌린다."""
        def boom(*_a, **_k):
            raise OSError(f"{name} 실패")
        setattr(self.adapter, name, boom)
        self.addCleanup(lambda: self.adapter.__dict__.pop(name, None))

    def _leftovers(self):
        return sorted(p.name for p in self.dest_rom.parent.iterdir())

    # --- 성공 경로 ------------------------------------------------------
    def test_success_leaves_the_new_rom_and_no_leftovers(self):
        entry = self.entry()          # 성공하면 Plan에서 빠지므로 미리 잡아 둔다
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), b"NEW" * 100)
        self.assertEqual(self._leftovers(), ["FFX.iso"])
        self.assertEqual(entry.status, STATUS_APPLIED)

    def test_success_also_places_the_media(self):
        self.apply()
        self.assertTrue(self.dest_cover.exists(), "media가 복사되지 않았다")

    # --- gamelist 쓰기 실패 ---------------------------------------------
    def test_a_gamelist_failure_restores_the_original_rom(self):
        self._break("write_index")
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), self.original,
                         "덮어쓴 뒤 실패했는데 원본이 사라졌다")

    def test_a_gamelist_failure_removes_the_newly_created_media(self):
        """새로 만든 파일은 지운다 - 다음 Apply가 «이미 있다»를 만나면 안 된다."""
        self._break("write_index")
        self.apply()
        self.assertFalse(self.dest_cover.exists(), "실패했는데 새로 만든 media가 남았다")

    def test_a_gamelist_failure_leaves_no_backup_behind(self):
        self._break("write_index")
        self.apply()
        self.assertEqual(self._leftovers(), ["FFX.iso"], "정체불명의 파일이 남았다")

    def test_a_gamelist_failure_is_reported_as_failed(self):
        self._break("write_index")
        self.apply()
        self.assertEqual(self.entry().status, STATUS_FAILED)

    def test_the_plan_keeps_the_failed_entry_for_a_retry(self):
        """성공한 것만 Plan에서 뺀다. 실패한 것은 사용자가 다시 볼 수 있어야 한다."""
        self._break("write_index")
        self.apply()
        self.assertEqual([e.filename for e in self.plan.entries], ["FFX.iso"])

    def test_retrying_after_a_gamelist_failure_succeeds(self):
        """되돌린 상태가 «다시 시도할 수 있는 상태»여야 롤백이 끝난 것이다."""
        self._break("write_index")
        self.apply()
        self.adapter.__dict__.pop("write_index", None)

        self.validate()
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), b"NEW" * 100, "재시도가 안 됐다")
        self.assertEqual(self._leftovers(), ["FFX.iso"])

    # --- media 링크 쓰기 실패 (gamelist 이후 단계) ------------------------
    # `write_media_links` 실패가 PARTIAL이 되는지는 여기서 볼 수 없다.
    # **그 단계는 원조 EmulationStation에만 있다** - ES-DE/Pegasus/LaunchBox는 폴더
    # 규칙으로 media를 찾으므로 gamelist에 경로를 적지 않는다(`base.build_media_links`가
    # 빈 목록을 돌려준다). 아래 `MediaLinkFailureIsPartialTests`가 그 Adapter로 본다.

    # --- 복사 실패 -------------------------------------------------------
    def test_a_copy_failure_restores_the_original(self):
        self.src_rom.unlink()
        self.src_cover.unlink()
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), self.original)
        self.assertEqual(self._leftovers(), ["FFX.iso"])

    # --- 백업 자체가 실패 -------------------------------------------------
    def test_a_backup_failure_does_not_start_the_overwrite(self):
        """치워두지 못했으면 시작하지 않는다 - 시작하면 되살릴 방법이 없다."""
        real_move = file_ops.move_files
        file_ops.move_files = lambda pairs, **k: {str(d): False for _s, d in pairs}
        self.addCleanup(lambda: setattr(file_ops, "move_files", real_move))

        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), self.original,
                         "백업에 실패했는데 덮어쓰기를 진행했다")
        self.assertEqual(self.entry().status, STATUS_FAILED)


class MediaLinkFailureIsPartialTests(unittest.TestCase):
    """gamelist에 media 경로를 적는 단계가 실패하면 PARTIAL이어야 한다.

    **이 단계는 원조 EmulationStation에만 있다.** ES-DE/Pegasus/LaunchBox는 폴더
    규칙으로 media를 찾으므로 적을 것이 없다.

    여기서는 **되돌리지 않는다.** 파일은 이미 제자리에 있고 gamelist도 썼다. 되돌리면
    새로 복사한 ROM까지 지우게 되는데, 사용자가 원한 결과에 더 가까운 것은 "파일은
    갔지만 media 경로가 안 적혔다"이지 "아무 일도 없던 것처럼 되돌리기"가 아니다.
    대신 PARTIAL로 표시해서 손봐야 한다는 것을 알린다.
    """

    def setUp(self):
        file_ops.select_engine(file_ops.ENGINE_WORKER)
        self.addCleanup(file_ops.select_engine, file_ops.ENGINE_AUTO)

        self.dir = temp_root("rms_medialink_")
        self.src_root = self.dir / "source"
        build_custom_esde_tree(self.src_root, "ps2", [{"filename": "FFX.iso", "title": "FFX"}])
        self.src_cover = write_file(
            self.src_root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"c" * 30)

        self.dst_root = self.dir / "target"
        (self.dst_root / "ps2").mkdir(parents=True)
        write_file(self.dst_root / "gamelists" / "ps2" / "gamelist.xml",
                   '<?xml version="1.0"?>\n<gameList/>\n')

        from app.model.collection import (Collection, StorageLocation, SystemEntry,
                                          STORAGE_INTERNAL)
        from app.model.plan import Plan
        from app.store.cache import CacheStore
        from adapters import get_adapter

        self.collection = Collection(
            id="dst", name="dst", frontend="emulationstation", root_path=str(self.dst_root),
            storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "I",
                                      str(self.dst_root))],
            systems=[SystemEntry("ps2", STORAGE_INTERNAL)])
        self.adapter = get_adapter("emulationstation")
        self.cache = CacheStore.open_for_collection(self.dir / "cache", "dst")
        self.addCleanup(self.cache.close)
        self.plan = Plan("dst")

        src_rom = self.src_root / "ps2" / "FFX.iso"
        builder.plan_add(self.plan, self.collection, PROVIDER, [{
            "system": "ps2", "filename": "FFX.iso",
            "rom": {"path": str(src_rom), "size": src_rom.stat().st_size},
            "media": [{"type": "covers", "path": str(self.src_cover),
                       "size": self.src_cover.stat().st_size}],
            "fields": {"name": "FFX"}}])
        self.entry = self.plan.entries[0]

    def _apply(self):
        from app.plan.applier import apply_plan
        return apply_plan(self.plan, self.collection, self.cache, None, PROVIDER)

    def _break(self):
        def boom(*_a, **_k):
            raise OSError("media 경로를 쓸 수 없다")
        self.adapter.write_media_links = boom
        self.addCleanup(lambda: self.adapter.__dict__.pop("write_media_links", None))

    def test_the_baseline_actually_writes_media_links(self):
        """이 Adapter가 정말 media 경로를 적는지 먼저 확인한다 - 아니면 이 파일은 무의미하다."""
        self._apply()
        xml = (self.dst_root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        # 원조 ES는 covers를 <thumbnail> 태그에 적는다.
        self.assertIn("<thumbnail>", xml, "이 Adapter는 media 경로를 적지 않는다")
        self.assertEqual(self.entry.status, STATUS_APPLIED)

    def test_a_media_link_failure_keeps_the_copied_files(self):
        self._break()
        self._apply()
        self.assertTrue((self.dst_root / "ps2" / "FFX.iso").exists(), "복사된 ROM이 사라졌다")

    def test_a_media_link_failure_is_partial_not_applied(self):
        self._break()
        self._apply()
        self.assertEqual(self.entry.status, STATUS_PARTIAL,
                         "손봐야 하는 상태인데 완료로 보고했다")


class PartialScanAtomicityTests(unittest.TestCase):
    """스캔이 중간에 터졌을 때 기존 Cache가 무사한가.

    시나리오: 두 System을 스캔하는데 두 번째에서 예외가 난다. 첫 번째는 이미
    Cache에 반영됐고 두 번째는 손도 못 댔다. 그때 **두 번째 System의 기존 정보가
    사라지면 안 된다** - 읽지도 못한 것을 지울 근거가 없다.
    """

    def setUp(self):
        self.dir = temp_root("rms_scanfail_")
        self.root = self.dir / "esde"
        build_custom_esde_tree(self.root, "ps2", [{"filename": "FFX.iso", "title": "FFX"}])
        build_custom_esde_tree(self.root, "snes", [{"filename": "Zelda.sfc", "title": "Zelda"}])
        for system, stem in (("ps2", "FFX"), ("snes", "Zelda")):
            write_file(self.root / "downloaded_media" / system / "covers" / f"{stem}.png",
                       b"c" * 20)
            write_file(self.root / "downloaded_media" / system / "videos" / f"{stem}.mp4",
                       b"v" * 60)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("t", "es-de", str(self.root))["data"]["id"]
        scan(self.api, self.cid)
        self.before = self._snapshot()

    def _snapshot(self):
        cache = self.api.workspace.open(self.cid)
        out = {}
        for row in self.api.list_rows(self.cid, limit=50)["data"]["rows"]:
            full = cache.get_row(row["romUid"])
            out[row["file"]] = sorted(m["media_type"] for m in full["media"])
        return out

    def _scan_with_a_broken_system(self, media_types=None):
        """snes를 읽을 때만 터뜨린다."""
        from adapters.es_de import EsDeAdapter
        real = EsDeAdapter.read_media_index

        def flaky(self_adapter, provider, layout, types=None):
            if layout.system == "snes":
                raise OSError("이 System을 읽을 수 없다")
            return real(self_adapter, provider, layout, types)

        EsDeAdapter.read_media_index = flaky
        try:
            self.api.workspace.scan(self.cid, media_types=media_types, force=True)
        except Exception:
            pass                        # 스캔이 실패하는 것 자체는 이 테스트의 전제다
        finally:
            EsDeAdapter.read_media_index = real

    def test_the_baseline_has_everything(self):
        self.assertEqual(self.before,
                         {"FFX.iso": ["covers", "videos"], "Zelda.sfc": ["covers", "videos"]})

    def test_a_failure_does_not_wipe_the_system_it_never_read(self):
        self._scan_with_a_broken_system()
        self.assertEqual(self._snapshot()["Zelda.sfc"], ["covers", "videos"],
                         "읽지도 못한 System의 Cache가 사라졌다")

    def test_a_failure_during_a_partial_scan_keeps_the_unscanned_types_too(self):
        """부분 스캔 + 중간 실패. 두 위험이 겹치는 자리다."""
        self._scan_with_a_broken_system(media_types=["covers"])
        after = self._snapshot()
        self.assertEqual(after["Zelda.sfc"], ["covers", "videos"])
        self.assertEqual(after["FFX.iso"], ["covers", "videos"],
                         "부분 스캔이 스캔하지 않은 타입을 지웠다")

    def test_the_collection_is_still_usable_after_a_failed_scan(self):
        self._scan_with_a_broken_system()
        rows = self.api.list_rows(self.cid, limit=50)["data"]["rows"]
        self.assertEqual(sorted(r["file"] for r in rows), ["FFX.iso", "Zelda.sfc"])

    def test_a_later_successful_scan_repairs_everything(self):
        self._scan_with_a_broken_system()
        self.api.workspace.scan(self.cid, force=True)
        self.assertEqual(self._snapshot(), self.before)


# ======================================================================
# 여러 항목 중 하나만 실패했을 때 - 재시도가 성공한 것들을 다시 건드리지 않는가
# ======================================================================
class MixedBatchRetryTests(PlanCase):
    """**한 번에 여러 개를 Apply하다 중간 하나가 실패한 경우.**

    앞선 테스트들은 항목이 하나뿐이라 «실패하면 되돌린다»까지만 본다. 실제 사용은
    열 개를 한 번에 보내고 여섯 번째가 실패하는 식이다. 그때 사용자가 다시 Apply를
    누르면, **이미 성공한 것들을 다시 복사하면 안 된다** - 다시 복사하면 그 사이
    사용자가 손댄 대상 파일을 말없이 덮어쓰게 되고, 큰 ROM이면 시간도 두 배로 든다.
    """

    GAMES = ["A.iso", "B.iso", "C.iso", "D.iso"]
    BROKEN = "C.iso"

    def setUp(self):
        super().setUp()
        self.srcs = {name: touch(self.src_root / "ps2" / name, b"DATA-" + name.encode())
                     for name in self.GAMES}
        builder.plan_add(self.plan, self.collection, PROVIDER, [
            {"system": "ps2", "filename": name,
             "rom": {"path": str(path), "size": path.stat().st_size},
             "media": [], "fields": {"name": name.split(".")[0]}}
            for name, path in self.srcs.items()])
        self.validate()
        self.copied = []          # Apply마다 실제로 복사를 시도한 목적지
        self.breaking = False     # 켜면 BROKEN 항목만 실패한다

        # spy는 **한 번만** 끼운다 - 두 번 끼우면 두 번째가 첫 번째를 감싸 버려서
        # 꺼 둔 줄 알았던 실패 주입이 안쪽에 그대로 남는다.
        original = file_ops.copy_files

        def spy(dest_dirs, pairs):
            self.copied.extend(Path(dest).name for _src, dest in pairs)
            results = original(dest_dirs, pairs)
            if self.breaking:
                for _src, dest in pairs:
                    if Path(dest).name == self.BROKEN:
                        Path(dest).unlink(missing_ok=True)
                        results[str(dest)] = False
            return results

        file_ops.copy_files = spy
        self.addCleanup(setattr, file_ops, "copy_files", original)

    def _watch_copies(self, break_one):
        self.breaking = break_one

    def _dest(self, name):
        return self.dst_root / "ps2" / name

    def test_one_failure_does_not_stop_the_others(self):
        self._watch_copies(break_one=True)
        result = self.apply()
        self.assertEqual(result["applied"], 3)
        self.assertEqual(result["failed"], 1)
        for name in self.GAMES:
            self.assertEqual(self._dest(name).exists(), name != self.BROKEN, name)

    def test_the_plan_keeps_only_the_failed_entry(self):
        self._watch_copies(break_one=True)
        self.apply()
        self.assertEqual([e.filename for e in self.plan.entries], [self.BROKEN])

    def test_a_retry_copies_only_the_failed_entry(self):
        """사용자가 물은 그것 - 이미 성공한 것을 다시 처리하지 않는가."""
        self._watch_copies(break_one=True)
        self.apply()

        self.copied.clear()
        self._watch_copies(break_one=False)   # 이번에는 정상 동작
        self.validate()
        self.apply()

        self.assertEqual(sorted(set(self.copied)), [self.BROKEN],
                         "이미 성공한 항목을 재시도가 다시 복사했다")
        self.assertTrue(self._dest(self.BROKEN).exists(), "재시도가 실패 항목을 못 채웠다")

    def test_a_retry_leaves_the_already_applied_files_untouched(self):
        self._watch_copies(break_one=True)
        self.apply()
        before = {name: self._dest(name).stat().st_mtime_ns
                  for name in self.GAMES if name != self.BROKEN}

        self._watch_copies(break_one=False)
        self.validate()
        self.apply()

        after = {name: self._dest(name).stat().st_mtime_ns for name in before}
        self.assertEqual(after, before, "성공했던 파일을 재시도가 다시 썼다")


class ApplyCountMatchesWhatApplyDoesTests(PlanCase):
    """**Apply 버튼이 말하는 수 = Apply가 실제로 처리하는 수.**

    Plan에는 해결되지 않은 충돌도 함께 올라간다. 적용기는 그것을 건너뛰는데
    (`runnable` 필터), 화면이 Plan 전체 수를 보여주면 사용자는 누르고 나서야
    "12개라더니 9개만 됐다"를 알게 된다.
    """

    def setUp(self):
        super().setUp()
        self.clean = touch(self.src_root / "ps2" / "Clean.iso", b"CLEAN")
        # Conflict.iso는 대상에 이미 있다 - 해결하지 않으면 blocked가 된다.
        self.clash = touch(self.src_root / "ps2" / "Conflict.iso", b"NEW")
        touch(self.dst_root / "ps2" / "Conflict.iso", b"ALREADY HERE")
        builder.plan_add(self.plan, self.collection, PROVIDER, [
            {"system": "ps2", "filename": path.name,
             "rom": {"path": str(path), "size": path.stat().st_size},
             "media": [], "fields": {"name": path.stem}}
            for path in (self.clean, self.clash)])
        self.validate()

    def test_an_unresolved_conflict_is_blocked(self):
        blocked = [e.filename for e in self.plan.entries if e.blocked]
        self.assertEqual(blocked, ["Conflict.iso"])

    def test_total_counts_everything_but_runnable_counts_only_what_apply_will_do(self):
        summary = self.plan.summary()
        self.assertEqual(summary["total"], 2, "Cancel은 충돌까지 포함한 Plan 전체를 버린다")
        self.assertEqual(summary["runnable"], 1, "Apply가 처리할 수 있는 것은 하나뿐이다")

    def test_runnable_is_exactly_what_apply_reports_as_applied_plus_failed(self):
        """숫자가 맞다는 것을 실제 Apply 결과로 확인한다."""
        runnable = self.plan.summary()["runnable"]
        result = self.apply()
        self.assertEqual(result["applied"] + result["failed"] + result["partial"], runnable)
        self.assertEqual(result["skipped"], 1, "충돌은 건너뛴 것으로 보고된다")


if __name__ == "__main__":
    unittest.main()
