"""CopyEngine 구현들이 같은 계약을 지키는지 확인한다.

두 엔진(Robocopy / Native Worker)은 서로 갈아끼울 수 있어야 한다. 백신 탐지 때문에
엔진을 바꾸는 상황이 실제로 생기므로, 호출부에서 보이는 동작이 같아야 한다.
"""

import tempfile
import unittest
from pathlib import Path

import file_ops
from engines.native_worker_engine import NativeWorkerEngine
from engines.robocopy_engine import RobocopyEngine, robocopy_available


class EngineContractMixin:
    """두 엔진에 같은 시나리오를 돌린다."""

    def make_engine(self):
        raise NotImplementedError

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_engine_"))
        self.src = self.dir / "src"
        self.dst = self.dir / "dst"
        self.src.mkdir()
        self.engine = self.make_engine()

    def write(self, name, content=b"data", directory=None):
        path = (directory or self.src) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    # ------------------------------------------------------------------
    def test_copy_files_creates_destination_dirs(self):
        a = self.write("a.bin", b"a" * 16)
        b = self.write("b.bin", b"b" * 32)
        pairs = [(a, self.dst / "a.bin"), (b, self.dst / "b.bin")]

        results = self.engine.copy_files([self.dst], pairs, timeout_sec=30)
        self.assertTrue(all(results.get(str(d)) for _, d in pairs), results)
        self.assertEqual((self.dst / "a.bin").read_bytes(), b"a" * 16)
        self.assertEqual((self.dst / "b.bin").read_bytes(), b"b" * 32)

    def test_copy_can_rename_on_the_way(self):
        source = self.write("original.bin", b"x" * 8)
        dest = self.dst / "renamed.bin"
        results = self.engine.copy_files([self.dst], [(source, dest)], timeout_sec=30)
        self.assertTrue(results.get(str(dest)), results)
        self.assertEqual(dest.read_bytes(), b"x" * 8)
        self.assertTrue(source.exists(), "복사는 원본을 남겨야 한다")

    def test_missing_source_is_reported_not_raised(self):
        dest = self.dst / "nope.bin"
        results = self.engine.copy_files([self.dst], [(self.src / "nope.bin", dest)], timeout_sec=30)
        self.assertFalse(results.get(str(dest)))

    def test_delete_paths(self):
        a, b = self.write("a.bin"), self.write("b.bin")
        results = self.engine.delete_paths([a, b], timeout_sec=30)
        self.assertTrue(all(results.values()), results)
        self.assertFalse(a.exists())
        self.assertFalse(b.exists())

    def test_move_pairs_removes_the_source(self):
        source = self.write("game.bin", b"rom" * 10)
        dest = self.dst / "game.bin"
        results = self.engine.move_pairs([(source, dest)], timeout_sec=30)
        self.assertTrue(results.get(str(dest)), results)
        self.assertEqual(dest.read_bytes(), b"rom" * 10)
        self.assertFalse(source.exists(), "이동 후 원본이 남아 있다")

    def test_failed_move_keeps_the_source(self):
        """이동 도중 실패로 파일이 사라지면 안 된다."""
        source = self.write("keep.bin", b"important")
        # 대상 경로를 만들 수 없게 해서 실패를 유도한다.
        blocked = self.dir / "blocked"
        blocked.write_bytes(b"not a directory")
        results = self.engine.move_pairs([(source, blocked / "keep.bin")], timeout_sec=30)
        self.assertFalse(list(results.values())[0])
        self.assertTrue(source.exists(), "실패했는데 원본이 사라졌다")

    def test_existing_destination_is_not_mistaken_for_success(self):
        """[회귀] 목적지에 원래 파일이 있고 이번 복사가 실패하면 실패로 보고해야 한다.

        dest.exists()만으로 판정하면 실패를 성공으로 보고한다. 그 결과를 믿고 Plan이
        원본을 지우거나 Registry를 갱신하면 데이터가 어긋난다.
        """
        stale = self.write("target.bin", b"stale content", directory=self.dst)
        missing_source = self.src / "does-not-exist.bin"

        results = self.engine.copy_files([self.dst], [(missing_source, stale)], timeout_sec=30)
        self.assertFalse(results.get(str(stale)), "원본이 없는데 복사가 성공으로 보고됐다")
        self.assertEqual(stale.read_bytes(), b"stale content", "실패했는데 기존 파일이 바뀌었다")

    def test_existing_destination_is_not_mistaken_for_a_completed_move(self):
        """[회귀] 이동에서는 더 위험하다. 성공으로 오인하면 파일이 두 곳에 남는다."""
        source = self.write("dup.bin", b"source content")
        stale = self.write("dup.bin", b"stale content", directory=self.dst)

        # 목적지를 읽기 전용 폴더로 만들 수 없는 환경도 있으므로, 원본을 잠가서
        # 이동이 실패하도록 만든다.
        with open(source, "rb"):
            results = self.engine.move_pairs([(source, stale)], timeout_sec=30)
            if results.get(str(stale)):
                # 이 플랫폼에서는 열려 있어도 이동이 되므로 검증할 수 없다.
                self.skipTest("이 환경에서는 열린 파일도 이동된다")
        self.assertTrue(source.exists(), "이동 실패인데 원본이 사라졌다")

    def test_group_is_atomic(self):
        """그룹 안의 copy가 하나라도 실패하면 delete/rename을 실행하지 않는다."""
        good = self.write("good.bin", b"g")
        existing = self.write("existing.bin", b"old", directory=self.dst)
        groups = [{
            "copies": [(good, self.dst / "good.tmp"),
                       (self.src / "missing.bin", self.dst / "missing.tmp")],
            "deletes": [existing],
            "renames": [(self.dst / "good.tmp", self.dst / "good.bin")],
        }]
        self.engine.copy_finalize_groups([self.dst], groups, timeout_sec=30)
        self.assertTrue(existing.exists(), "확정되지 않은 그룹이 기존 파일을 지웠다")
        self.assertFalse((self.dst / "good.bin").exists(), "확정되지 않았는데 rename이 실행됐다")


@unittest.skipUnless(robocopy_available(), "Robocopy를 찾을 수 없음")
class RobocopyEngineTests(EngineContractMixin, unittest.TestCase):
    def make_engine(self):
        return RobocopyEngine()


class NativeWorkerEngineTests(EngineContractMixin, unittest.TestCase):
    def make_engine(self):
        # 워커 바이너리가 없으면 media_copy_worker가 in-process fallback을 쓴다.
        return NativeWorkerEngine()


class EngineSelectionTests(unittest.TestCase):
    def tearDown(self):
        file_ops.select_engine(file_ops.ENGINE_AUTO)

    def test_default_prefers_robocopy(self):
        """네이티브 워커는 서명이 없어 백신에 걸린 사례가 있다. 기본은 Robocopy다."""
        file_ops.select_engine(file_ops.ENGINE_AUTO)
        expected = "robocopy" if robocopy_available() else "worker"
        self.assertEqual(file_ops.active_engine_name(), expected)

    def test_can_force_the_native_worker(self):
        file_ops.select_engine(file_ops.ENGINE_WORKER)
        self.assertIsInstance(file_ops.engine(), NativeWorkerEngine)

    @unittest.skipUnless(robocopy_available(), "Robocopy를 찾을 수 없음")
    def test_can_force_robocopy(self):
        file_ops.select_engine(file_ops.ENGINE_ROBOCOPY)
        self.assertIsInstance(file_ops.engine(), RobocopyEngine)


if __name__ == "__main__":
    unittest.main()
