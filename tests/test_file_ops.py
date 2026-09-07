"""
tests/test_file_ops.py
=======================
file_ops.py(File Operation Layer) 전용 테스트.

media_copy_worker.py 자체의 파서/원자성/회귀 테스트는
tests/test_media_copy_worker.py가 이미 자세히 다룬다. 이 파일은 두
가지를 각각 검증한다 - 성격이 다르므로 서로 다른 방법을 쓴다:

- FileOpsContractTests: file_ops의 3개 함수가 "engine에게 정확히
  위임하는가"(호출 횟수, 인자/kwargs 그대로 전달, 반환값 그대로
  전달)라는 추상화 계층 자체의 계약을 검증한다. 이건 워커 바이너리와
  무관한 순수 배선 문제이므로, 실제 워커 대신 CopyEngine을 구현한
  가짜 RecordingEngine을 file_ops._engine에 주입해서 검증한다(실제
  파일 mutation 로직을 테스트하는 게 아니라 "누가 무엇을 어떻게
  불렀는지"를 테스트하는 것이므로 모킹이 적절한 경우다 - Phase 1/2가
  지킨 "실제 mutation은 반드시 실제 워커로 검증" 원칙과 배치되지
  않는다).
- RealWorkerViaFileOpsTests / FileOpsFallbackTests: 실제로 빌드된
  native/MediaCopyWorker.exe(또는 그게 없을 때의 fallback)를 file_ops
  진입점을 통해 실행해서 실제 파일이 올바르게 만들어지는지 검증한다
  (모킹 아님 - 기존 원칙 그대로).

실행: python -m unittest tests.test_file_ops -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import file_ops
import media_copy_worker as mcw
from engines.base import CopyEngine


class RecordingEngine(CopyEngine):
    """CopyEngine 계약만 구현하는 가짜 엔진 - 실제로 아무것도 복사하지
    않고, 어떤 메서드가 어떤 인자로 몇 번 불렸는지만 기록한다."""

    def __init__(self, canned_result=None):
        self.calls = []  # [(method_name, args, kwargs), ...]
        self._canned_result = canned_result if canned_result is not None else {"canned": True}

    def copy_pairs(self, pairs, timeout_sec):
        self.calls.append(("copy_pairs", pairs, {"timeout_sec": timeout_sec}))
        return self._canned_result

    def copy_files(self, dest_dirs, pairs, timeout_sec):
        self.calls.append(("copy_files", (dest_dirs, pairs), {"timeout_sec": timeout_sec}))
        return self._canned_result

    def copy_finalize_groups(self, dest_dirs, groups, timeout_sec):
        self.calls.append(("copy_finalize_groups", (dest_dirs, groups), {"timeout_sec": timeout_sec}))
        return self._canned_result


class FileOpsContractTests(unittest.TestCase):
    """file_ops.copy_pairs/copy_files/copy_finalize_groups가 engine에게
    정확히 위임하는지(인자/기본 timeout/반환값 그대로 전달) 검증한다.
    워커 바이너리 유무와 무관하게 항상 실행된다."""

    def setUp(self):
        self._original_engine = file_ops._engine
        self.addCleanup(setattr, file_ops, "_engine", self._original_engine)

    def test_copy_pairs_delegates_args_and_default_timeout_and_returns_engine_result(self):
        fake = RecordingEngine(canned_result={"a": True})
        file_ops._engine = fake
        pairs = [(Path("s.txt"), Path("d.txt"))]

        result = file_ops.copy_pairs(pairs)

        self.assertEqual(fake.calls, [("copy_pairs", pairs, {"timeout_sec": 120.0})])
        self.assertIs(result, fake._canned_result)

    def test_copy_files_delegates_args_and_default_timeout_and_returns_engine_result(self):
        fake = RecordingEngine(canned_result={"b": True})
        file_ops._engine = fake
        dest_dirs = [Path("d1"), Path("d2")]
        pairs = [(Path("s.txt"), Path("d1/out.txt"))]

        result = file_ops.copy_files(dest_dirs, pairs)

        self.assertEqual(fake.calls, [("copy_files", (dest_dirs, pairs), {"timeout_sec": 180.0})])
        self.assertIs(result, fake._canned_result)

    def test_copy_finalize_groups_delegates_args_and_default_timeout_and_returns_engine_result(self):
        fake = RecordingEngine(canned_result={"c": True})
        file_ops._engine = fake
        dest_dirs = Path("d")
        groups = [{"copies": [], "deletes": [], "renames": []}]

        result = file_ops.copy_finalize_groups(dest_dirs, groups)

        self.assertEqual(fake.calls, [("copy_finalize_groups", (dest_dirs, groups), {"timeout_sec": 180.0})])
        self.assertIs(result, fake._canned_result)

    def test_explicit_timeout_override_is_passed_through_unchanged(self):
        fake = RecordingEngine()
        file_ops._engine = fake

        file_ops.copy_pairs([], timeout_sec=5.0)

        self.assertEqual(fake.calls[0][2], {"timeout_sec": 5.0})


class FileOpsFallbackTests(unittest.TestCase):
    """워커 바이너리가 없을 때도 file_ops 진입점을 통해 in-process
    fallback이 실제로 파일을 복사하는지 검증한다 - 워커 바이너리 빌드
    여부와 무관하게 항상 실행된다(스킵되지 않음)."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="file_ops_fallback_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_copy_pairs_falls_back_when_worker_binary_missing(self):
        src = self.tmpdir / "src.txt"
        src.write_text("fallback-payload", encoding="utf-8")
        dest = self.tmpdir / "dst.txt"

        with patch.object(mcw, "WORKER_PATH", self.tmpdir / "does_not_exist.exe"):
            results = file_ops.copy_pairs([(src, dest)])

        self.assertTrue(results[str(dest)])
        self.assertEqual(dest.read_text(encoding="utf-8"), "fallback-payload")

    def test_copy_files_falls_back_when_worker_binary_missing(self):
        src = self.tmpdir / "cover.png"
        src.write_bytes(b"COVER")
        dest_dir = self.tmpdir / "downloaded_media" / "snes" / "covers"

        with patch.object(mcw, "WORKER_PATH", self.tmpdir / "does_not_exist.exe"):
            results = file_ops.copy_files([dest_dir], [(src, dest_dir / "Mario.png")])

        self.assertTrue(results[str(dest_dir / "Mario.png")])
        self.assertEqual((dest_dir / "Mario.png").read_bytes(), b"COVER")

    def test_copy_finalize_groups_falls_back_when_worker_binary_missing(self):
        dest_dir = self.tmpdir / "snes" / "Mario"
        dest_dir.mkdir(parents=True)
        old_final = dest_dir / "covers.jpg"
        old_final.write_bytes(b"OLD-JPG")
        src = self.tmpdir / "new_cover.png"
        src.write_bytes(b"NEW-PNG")
        tmp = dest_dir / "covers.png.tmp"
        new_final = dest_dir / "covers.png"
        groups = [{"copies": [(src, tmp)], "deletes": [old_final], "renames": [(tmp, new_final)]}]

        with patch.object(mcw, "WORKER_PATH", self.tmpdir / "does_not_exist.exe"):
            results = file_ops.copy_finalize_groups(dest_dir, groups)

        self.assertTrue(results[str(tmp)])
        self.assertFalse(old_final.exists())
        self.assertTrue(new_final.exists())
        self.assertEqual(new_final.read_bytes(), b"NEW-PNG")


@unittest.skipUnless(mcw.worker_available(), "native/MediaCopyWorker.exe가 빌드돼 있지 않음 - native/build_worker.bat 먼저 실행")
class RealWorkerViaFileOpsTests(unittest.TestCase):
    """실제로 빌드된 native/MediaCopyWorker.exe를 file_ops의 3개 공개
    함수를 통해 실행해서 실제 파일이 올바르게 만들어지는지 검증한다."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="file_ops_real_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_copy_pairs_writes_real_files(self):
        pairs = []
        for i in range(3):
            src = self.tmpdir / f"src_{i}.txt"
            src.write_text(f"payload-{i}", encoding="utf-8")
            dest = self.tmpdir / f"dst_{i}.txt"
            pairs.append((src, dest))

        results = file_ops.copy_pairs(pairs)
        for src, dest in pairs:
            self.assertTrue(results[str(dest)])
            self.assertEqual(dest.read_text(encoding="utf-8"), src.read_text(encoding="utf-8"))

    def test_copy_files_creates_missing_dest_dirs_and_copies(self):
        covers_src = self.tmpdir / "cover.png"
        covers_src.write_bytes(b"COVER")
        covers_dir = self.tmpdir / "downloaded_media" / "snes" / "covers"
        marquees_dir = self.tmpdir / "downloaded_media" / "snes" / "marquees"  # 파일 없이 mkdir만

        pairs = [(covers_src, covers_dir / "Mario.png")]
        results = file_ops.copy_files([covers_dir, marquees_dir], pairs)

        self.assertTrue(results[str(covers_dir / "Mario.png")])
        self.assertEqual((covers_dir / "Mario.png").read_bytes(), b"COVER")
        self.assertTrue(marquees_dir.is_dir())

    def test_copy_finalize_groups_deletes_old_file_and_renames_tmp_to_final(self):
        dest_dir = self.tmpdir / "snes" / "Mario"
        dest_dir.mkdir(parents=True)
        old_final = dest_dir / "covers.jpg"
        old_final.write_bytes(b"OLD-JPG")

        src = self.tmpdir / "new_cover.png"
        src.write_bytes(b"NEW-PNG")
        tmp = dest_dir / "covers.png.tmp"
        new_final = dest_dir / "covers.png"

        groups = [{"copies": [(src, tmp)], "deletes": [old_final], "renames": [(tmp, new_final)]}]
        results = file_ops.copy_finalize_groups(dest_dir, groups)

        self.assertTrue(results[str(tmp)])
        self.assertFalse(old_final.exists())
        self.assertTrue(new_final.exists())
        self.assertEqual(new_final.read_bytes(), b"NEW-PNG")

    def test_copy_finalize_groups_failure_isolation_matches_direct_media_copy_worker_call(self):
        """[강화된 동등성 검증] 그룹 하나에 실패하는 copy가 섞여 있을 때,
        file_ops 경유와 media_copy_worker 직접 호출이 "같은 입력 구조에
        대해 같은 실패 격리 semantics(그룹 전체 미확정, 기존 파일 보존,
        성공했던 tmp도 rename 안 됨)"를 보이는지 두 실행을 나란히
        비교한다 - 단순히 "둘 다 True"가 아니라 그룹 원자성이라는 핵심
        계약 자체를 비교한다."""

        def make_job(root):
            dest_dir = root / "snes" / "Zelda"
            dest_dir.mkdir(parents=True)
            existing_final = dest_dir / "covers.png"
            existing_final.write_bytes(b"EXISTING")
            good_src = root / "good.png"
            good_src.write_bytes(b"GOOD")
            missing_src = root / "does_not_exist.png"
            good_tmp = dest_dir / "covers_0.png.tmp"
            bad_tmp = dest_dir / "covers_1.png.tmp"
            good_final = dest_dir / "covers_0.png"
            bad_final = dest_dir / "covers_1.png"
            groups = [{
                "copies": [(good_src, good_tmp), (missing_src, bad_tmp)],
                "deletes": [existing_final],
                "renames": [(good_tmp, good_final), (bad_tmp, bad_final)],
            }]
            return dest_dir, groups, existing_final, good_tmp, bad_tmp, good_final, bad_final

        root_a = self.tmpdir / "via_file_ops"
        root_a.mkdir()
        root_b = self.tmpdir / "via_direct"
        root_b.mkdir()

        dest_dir_a, groups_a, existing_a, good_tmp_a, bad_tmp_a, good_final_a, bad_final_a = make_job(root_a)
        dest_dir_b, groups_b, existing_b, good_tmp_b, bad_tmp_b, good_final_b, bad_final_b = make_job(root_b)

        results_a = file_ops.copy_finalize_groups(dest_dir_a, groups_a)
        results_b = mcw.copy_finalize_groups(dest_dir_b, groups_b)

        # 그룹 원자성 결과가 두 경로 모두 동일해야 한다.
        self.assertEqual(results_a[str(good_tmp_a)], results_b[str(good_tmp_b)])
        self.assertEqual(results_a[str(bad_tmp_a)], results_b[str(bad_tmp_b)])
        self.assertEqual(existing_a.exists(), existing_b.exists())
        self.assertEqual(good_final_a.exists(), good_final_b.exists())
        self.assertEqual(bad_final_a.exists(), bad_final_b.exists())
        # 구체적인 기대값도 함께 확인(단순 상호 일치만으로는 둘 다 틀려도
        # 통과할 수 있으므로).
        self.assertTrue(results_a[str(good_tmp_a)])
        self.assertFalse(results_a[str(bad_tmp_a)])
        self.assertTrue(existing_a.exists(), "그룹이 미확정이면 기존 파일이 보존돼야 함")
        self.assertFalse(good_final_a.exists(), "그룹이 미확정이면 성공한 copy도 rename되면 안 됨")


if __name__ == "__main__":
    unittest.main()
