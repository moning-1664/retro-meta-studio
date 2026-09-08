"""Apply를 묶어 실행할 때의 실패 격리와 되돌리기 (Phase 7.3).

`_apply_add`가 항목마다 `file_ops.copy_files()`와 `adapter.write_index()`를 부르던 것을
묶었다. 실측으로 400게임 Apply가 20.50s -> 1.20s가 됐다(항목당 50ms 중 80%가 Robocopy
프로세스 기동이었다).

**호출은 묶지만 실패의 단위는 바뀌면 안 된다.** 이 파일이 그것을 지킨다:

- 한 항목의 복사 실패가 같은 묶음의 다른 항목을 끌어내리지 않는다.
- 되돌리는 것은 **그 항목이 이번에 새로 만든 파일**뿐이다.
- 메타데이터 쓰기 실패의 정책은 예전과 같다 - 복사한 파일을 되돌린다.
"""

import unittest
from pathlib import Path
from unittest import mock

import app.plan.applier as applier
from adapters.es_de import EsDeAdapter
from app.model.plan import STATUS_APPLIED, STATUS_FAILED, STATUS_PARTIAL
from bridge.api import Api
from tests.fixtures import build_scaled_esde_tree, scan, temp_root, wait_idle


def empty_esde(root: Path) -> Path:
    (root / "gamelists" / "ps2").mkdir(parents=True)
    (root / "gamelists" / "ps2" / "gamelist.xml").write_text(
        '<?xml version="1.0"?>\n<gameList/>\n', encoding="utf-8")
    return root


class ApplyBatchingTests(unittest.TestCase):
    #: 배치 경계(COPY_BATCH=25)를 반드시 넘겨야 "묶음이 여러 개일 때"가 검증된다.
    GAMES = 60

    def setUp(self):
        self.dir = temp_root("rms_batch_")
        self.src_root = build_scaled_esde_tree(
            self.dir / "src", systems=("ps2",), per_system=self.GAMES,
            with_media=False, rom_bytes=16)
        self.dst_root = empty_esde(self.dir / "dst")

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.dst = self.api.create_collection("T", "es-de", str(self.dst_root))["data"]["id"]
        for cid in (self.src, self.dst):
            scan(self.api, cid)
        self.api.start_convert(self.src, self.dst)

    def tearDown(self):
        self.api.close()

    def _apply(self):
        job = self.api.start_apply(self.dst)["data"]["jobId"]
        wait_idle(self.api)
        return self.api.get_job_progress(job)["data"]

    def _roms(self):
        return sorted(p.name for p in (self.dst_root / "ps2").glob("*.iso"))

    # ------------------------------------------------------------------
    def test_batching_reduces_the_number_of_calls(self):
        """묶는 것이 이 작업의 목적이다 - 항목 수만큼 부르면 되돌아간 것이다."""
        copies, writes = [], []
        real_copy, real_write = applier.file_ops.copy_files, EsDeAdapter.write_index

        def count_copy(dest_dirs, pairs, *a, **k):
            copies.append(len(pairs))
            return real_copy(dest_dirs, pairs, *a, **k)

        def count_write(self, layout, entries):
            writes.append(len(entries))
            return real_write(self, layout, entries)

        with mock.patch.object(applier.file_ops, "copy_files", count_copy), \
             mock.patch.object(EsDeAdapter, "write_index", count_write):
            self._apply()

        self.assertLess(len(copies), self.GAMES, "복사를 항목마다 부르고 있다")
        self.assertEqual(len(writes), 1, "System이 하나인데 메타데이터를 여러 번 썼다")
        self.assertEqual(writes[0], self.GAMES, "한 번에 전부 써야 한다")
        self.assertEqual(sum(copies), self.GAMES, "복사 대상이 빠졌다")

    def test_progress_still_moves_during_the_copy(self):
        """전부 한 번에 묶으면 가장 긴 구간에서 진행률이 멈춰 앱이 죽은 것처럼 보인다."""
        seen = []
        real = applier.file_ops.copy_files

        def spy(dest_dirs, pairs, *a, **k):
            seen.append(1)
            return real(dest_dirs, pairs, *a, **k)

        with mock.patch.object(applier.file_ops, "copy_files", spy):
            self._apply()
        self.assertGreater(len(seen), 1, "묶음이 하나뿐이면 진행률이 한 번에 튄다")

    def test_everything_applies(self):
        result = self._apply()
        self.assertEqual(result["result"]["applied"], self.GAMES, result["result"]["errors"])
        self.assertEqual(len(self._roms()), self.GAMES)

    # --- 실패 격리 ------------------------------------------------------
    def test_one_failed_copy_does_not_drag_down_its_batch(self):
        """묶어 불렀다고 남의 항목까지 실패시키면 안 된다."""
        victim = "Game 003 (USA).iso"
        real = applier.file_ops.copy_files

        def partial_failure(dest_dirs, pairs, *a, **k):
            results = real(dest_dirs, pairs, *a, **k)
            for _src, dest in pairs:
                if Path(dest).name == victim:
                    Path(dest).unlink(missing_ok=True)
                    results[str(dest)] = False
            return results

        with mock.patch.object(applier.file_ops, "copy_files", partial_failure):
            result = self._apply()

        outcome = result["result"]
        self.assertEqual(outcome["failed"], 1)
        self.assertEqual(outcome["applied"], self.GAMES - 1,
                         "같은 묶음의 다른 항목까지 실패했다")

        # 실패한 항목만 gamelist에 없어야 한다.
        adapter = EsDeAdapter()
        collection = self.api.registry.get_collection(self.dst)
        index = adapter.read_index(_provider(), adapter.layout(collection, "ps2"))
        self.assertNotIn(victim, index)
        self.assertEqual(len(index), self.GAMES - 1)

    def test_a_failed_entry_leaves_the_others_files_alone(self):
        """되돌리는 것은 그 항목이 만든 파일뿐이다."""
        victim = "Game 003 (USA).iso"
        real = applier.file_ops.copy_files

        def partial_failure(dest_dirs, pairs, *a, **k):
            results = real(dest_dirs, pairs, *a, **k)
            for _src, dest in pairs:
                if Path(dest).name == victim:
                    Path(dest).unlink(missing_ok=True)
                    results[str(dest)] = False
            return results

        with mock.patch.object(applier.file_ops, "copy_files", partial_failure):
            self._apply()

        roms = self._roms()
        self.assertNotIn(victim, roms)
        self.assertEqual(len(roms), self.GAMES - 1, "남의 파일까지 되돌렸다")

    def test_a_failed_entry_stays_in_the_plan(self):
        victim = "Game 003 (USA).iso"
        real = applier.file_ops.copy_files

        def partial_failure(dest_dirs, pairs, *a, **k):
            results = real(dest_dirs, pairs, *a, **k)
            for _src, dest in pairs:
                if Path(dest).name == victim:
                    Path(dest).unlink(missing_ok=True)
                    results[str(dest)] = False
            return results

        with mock.patch.object(applier.file_ops, "copy_files", partial_failure):
            self._apply()

        plan = self.api.plan_state(self.dst)["data"]
        self.assertEqual(plan["total"], 1, "실패한 항목이 Plan에 남아야 다시 시도할 수 있다")

    # --- 메타데이터 실패 정책 (기존과 같아야 한다) ----------------------
    def test_metadata_failure_rolls_back_the_copied_files(self):
        """정책은 항목마다 쓰던 때와 같다 - 복사한 파일을 되돌린다.

        묶어 쓰기 때문에 대상이 그 System의 항목 전체로 늘어날 뿐이다. 어차피
        디스크/권한 문제라면 항목마다 썼어도 전부 실패해 같은 결과가 된다.
        """
        def boom(self, layout, entries):
            raise OSError("디스크 오류")

        with mock.patch.object(EsDeAdapter, "write_index", boom):
            result = self._apply()

        outcome = result["result"]
        self.assertEqual(outcome["applied"], 0)
        self.assertEqual(outcome["failed"], self.GAMES)
        self.assertEqual(self._roms(), [], "metadata 실패인데 복사된 ROM이 남아 있다")

        plan = self.api.plan_state(self.dst)["data"]
        self.assertEqual(plan["total"], self.GAMES, "전부 Plan에 남아 다시 시도할 수 있어야 한다")

    def test_metadata_failure_keeps_pre_existing_files(self):
        """되돌릴 때 이번에 만든 것만 지운다 - 원래 있던 파일은 건드리지 않는다."""
        survivor = self.dst_root / "ps2" / "Game 001 (USA).iso"
        survivor.parent.mkdir(parents=True, exist_ok=True)
        survivor.write_bytes(b"original-bytes")

        def boom(self, layout, entries):
            raise OSError("디스크 오류")

        with mock.patch.object(EsDeAdapter, "write_index", boom):
            self._apply()

        self.assertTrue(survivor.exists(), "원래 있던 파일이 롤백으로 지워졌다")
        self.assertEqual(survivor.read_bytes(), b"original-bytes")


def _provider():
    from storage.local import LocalStorageProvider
    return LocalStorageProvider()


if __name__ == "__main__":
    unittest.main()
