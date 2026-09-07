"""
tests/test_media_copy_worker.py
================================
media_copy_worker.py 전용 테스트.

두 그룹으로 나눈다:
- ParserRobustnessTests: subprocess.run을 mock해서 "워커가 이상한 출력을
  냈을 때 copy_pairs()가 어떻게 반응하는가"만 빠르게 검증한다(Python
  wiring 테스트).
- RealWorkerIntegrationTests: native/MediaCopyWorker.exe가 실제로 빌드돼
  있으면, 그 바이너리를 진짜로 실행해서 CopyFileW까지 왕복하는 걸
  검증한다(native/build_worker.bat로 미리 빌드해야 함 - 없으면 스킵).
  이 기능의 핵심(패키징된 프로세스 대신 별도 프로세스가 실제로 파일을
  쓰는가)은 mock만으로는 증명되지 않으므로, 이 그룹이 반드시 있어야
  한다는 리뷰 지적을 반영.

실행: python -m unittest tests.test_media_copy_worker -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import media_copy_worker as mcw


class _FakeCompletedProcess:
    def __init__(self, stdout, returncode):
        self.stdout = stdout
        self.returncode = returncode


class ParserRobustnessTests(unittest.TestCase):
    """subprocess.run을 mock해서 워커 출력 파싱 로직만 검증한다."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="mcw_parser_"))
        self.pairs = [
            (self.tmpdir / "a_src.txt", self.tmpdir / "a_dst.txt"),
            (self.tmpdir / "b_src.txt", self.tmpdir / "b_dst.txt"),
            (self.tmpdir / "c_src.txt", self.tmpdir / "c_dst.txt"),
        ]
        for src, _ in self.pairs:
            src.write_text("x", encoding="utf-8")
        # copy_pairs()가 워커를 쓰게 하려면 worker_available()이 True여야
        # 한다 - 실제 바이너리 존재 여부와 무관하게 파서 로직만 보고
        # 싶으므로 patch한다.
        self._avail_patch = patch.object(mcw, "worker_available", return_value=True)
        self._avail_patch.start()
        self.addCleanup(self._avail_patch.stop)
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def _run_with_fake_worker(self, stdout, returncode):
        with patch("subprocess.run", return_value=_FakeCompletedProcess(stdout, returncode)):
            return mcw.copy_pairs(self.pairs)

    def test_malformed_status_is_not_trusted_as_failure(self):
        """[P0] "BROKEN 0"처럼 OK/ERR가 아닌 status는 "실제 복사 실패"로
        오인되면 안 된다 - fallback을 거쳐 최종적으로 실제 파일 상태
        (성공)를 반영해야 한다."""
        stdout = "BROKEN 0\nOK 1\nOK 2\n"
        results = self._run_with_fake_worker(stdout, returncode=1)
        # index 0은 malformed라 missing -> fallback(shutil.copy2)으로
        # 실제 복사가 일어나 True가 되어야 한다(소스 파일이 존재하므로).
        self.assertTrue(results[str(self.pairs[0][1])])
        self.assertTrue(self.pairs[0][1].exists())
        self.assertTrue(results[str(self.pairs[1][1])])
        self.assertTrue(results[str(self.pairs[2][1])])

    def test_duplicate_index_is_not_trusted(self):
        """같은 index가 두 번 보고되면(OK 0 그리고 ERR 0 2) 어느 쪽도
        믿지 않고 missing -> fallback으로 넘겨서 실제 파일 상태로
        결정해야 한다."""
        stdout = "OK 0\nERR 0 2\nOK 1\nOK 2\n"
        results = self._run_with_fake_worker(stdout, returncode=1)
        self.assertTrue(results[str(self.pairs[0][1])])
        self.assertTrue(self.pairs[0][1].exists())

    def test_returncode_ge_2_treats_whole_batch_as_worker_failure(self):
        """returncode>=2는 "워커가 어떤 pair도 제대로 처리 못했다"는
        프로세스 레벨 신호다 - stdout에 뭐가 있든 무시하고 전체를
        fallback해야 한다."""
        stdout = "OK 0\n"  # 있어도 무시돼야 함
        results = self._run_with_fake_worker(stdout, returncode=2)
        for src, dest in self.pairs:
            self.assertTrue(results[str(dest)], f"{dest} should have been copied via fallback")
            self.assertTrue(dest.exists())

    def test_returncode_zero_but_reports_failure_is_inconsistent_and_falls_back(self):
        """워커 계약상 returncode==0이면 ERR가 하나도 없어야 한다. 그런데도
        "ERR"가 파싱되면 워커 출력 자체를 신뢰할 수 없으므로 전체를
        fallback해야 한다."""
        stdout = "OK 0\nERR 1 2\nOK 2\n"
        results = self._run_with_fake_worker(stdout, returncode=0)
        for src, dest in self.pairs:
            self.assertTrue(results[str(dest)])
            self.assertTrue(dest.exists())

    def test_normal_ok_err_output_is_trusted_without_fallback(self):
        """정상적인 OK/ERR 출력(개별 파일 실패 포함)은 재시도 없이 그대로
        반영돼야 한다 - index 1(ERR)의 dest 파일이 fallback으로 생기면
        안 된다."""
        stdout = "OK 0\nERR 1 2\nOK 2\n"
        results = self._run_with_fake_worker(stdout, returncode=1)
        self.assertTrue(results[str(self.pairs[0][1])])
        self.assertFalse(results[str(self.pairs[1][1])])
        self.assertFalse(self.pairs[1][1].exists(), "ERR로 보고된 pair는 fallback 재시도가 없어야 한다")
        self.assertTrue(results[str(self.pairs[2][1])])

    def test_worker_missing_binary_falls_back_entirely(self):
        self._avail_patch.stop()
        try:
            with patch.object(mcw, "WORKER_PATH", self.tmpdir / "does_not_exist.exe"):
                results = mcw.copy_pairs(self.pairs)
        finally:
            self._avail_patch.start()
        for src, dest in self.pairs:
            self.assertTrue(results[str(dest)])
            self.assertTrue(dest.exists())


@unittest.skipUnless(mcw.worker_available(), "native/MediaCopyWorker.exe가 빌드돼 있지 않음 - native/build_worker.bat 먼저 실행")
class RealWorkerIntegrationTests(unittest.TestCase):
    """실제로 빌드된 native/MediaCopyWorker.exe를 subprocess로 실행해서
    CopyFileW 왕복까지 검증한다 - 이게 없으면 위 ParserRobustnessTests는
    Python wiring만 증명할 뿐, "별도 프로세스가 실제로 파일을 쓴다"는
    이 기능의 핵심을 증명하지 못한다."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="mcw_real_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_ascii_path_multiple_pairs(self):
        pairs = []
        for i in range(5):
            src = self.tmpdir / f"src_{i}.txt"
            src.write_text(f"payload-{i}", encoding="utf-8")
            dest = self.tmpdir / f"dst_{i}.txt"
            pairs.append((src, dest))

        results = mcw.copy_pairs(pairs)
        for src, dest in pairs:
            self.assertTrue(results[str(dest)])
            self.assertEqual(dest.read_text(encoding="utf-8"), src.read_text(encoding="utf-8"))

    def test_korean_source_and_destination_paths(self):
        src_dir = self.tmpdir / "한글소스폴더"
        dest_dir = self.tmpdir / "한글목적지폴더"
        src_dir.mkdir()
        dest_dir.mkdir()
        src = src_dir / "커버이미지.txt"
        src.write_text("한글 콘텐츠 테스트", encoding="utf-8")
        dest = dest_dir / "결과파일.txt"

        results = mcw.copy_pairs([(src, dest)])
        self.assertTrue(results[str(dest)])
        self.assertEqual(dest.read_text(encoding="utf-8"), "한글 콘텐츠 테스트")

    def test_missing_source_reports_failure_without_creating_destination(self):
        src = self.tmpdir / "does_not_exist.txt"
        dest = self.tmpdir / "out.txt"

        results = mcw.copy_pairs([(src, dest)])
        self.assertFalse(results[str(dest)])
        self.assertFalse(dest.exists())

    def test_destination_already_exists_is_overwritten(self):
        src = self.tmpdir / "src.txt"
        src.write_text("new-content", encoding="utf-8")
        dest = self.tmpdir / "dst.txt"
        dest.write_text("old-content", encoding="utf-8")

        results = mcw.copy_pairs([(src, dest)])
        self.assertTrue(results[str(dest)])
        self.assertEqual(dest.read_text(encoding="utf-8"), "new-content")

    def test_oversized_job_line_does_not_desync_later_pairs(self):
        """[P0 회귀 방지] 64KB보다 긴 job line이 뒤에 오는 정상 pair들의
        index 매핑을 깨뜨리면 안 된다."""
        before_src = self.tmpdir / "before.txt"
        before_src.write_text("before", encoding="utf-8")
        before_dest = self.tmpdir / "before_out.txt"

        # 실존하지 않아도 된다 - job 파일 한 줄을 64KB 넘게 만드는 게
        # 목적이므로, 실제 파일시스템에 만들 필요 없는 아주 긴 가짜 경로만
        # 있으면 된다.
        long_src = Path(str(self.tmpdir) + "\\" + ("x" * 70000) + ".txt")
        long_dest = self.tmpdir / "toolong_out.txt"

        after_src = self.tmpdir / "after.txt"
        after_src.write_text("after", encoding="utf-8")
        after_dest = self.tmpdir / "after_out.txt"

        pairs = [(before_src, before_dest), (long_src, long_dest), (after_src, after_dest)]
        results = mcw.copy_pairs(pairs)

        self.assertTrue(results[str(before_dest)])
        self.assertEqual(before_dest.read_text(encoding="utf-8"), "before")
        self.assertFalse(results[str(long_dest)])
        self.assertFalse(long_dest.exists())
        self.assertTrue(results[str(after_dest)])
        self.assertEqual(after_dest.read_text(encoding="utf-8"), "after")


@unittest.skipUnless(mcw.worker_available(), "native/MediaCopyWorker.exe가 빌드돼 있지 않음 - native/build_worker.bat 먼저 실행")
class RealWorkerFinalizeGroupsIntegrationTests(unittest.TestCase):
    """[v2] copy_finalize_groups()의 핵심 - mkdir/기존 파일 삭제/rename까지
    전부 워커가 하는지를 실제 컴파일된 워커로 검증한다. 이게 바로 실제
    RetroMetadataManager(headless_export.exe)에서 M1875가 재현됐던 지점
    (부모가 mkdir/삭제/rename을 직접 하던 구버전)을 고친 부분이므로,
    mock이 아니라 진짜 파일시스템 상태로 검증해야 의미가 있다."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="mcw_finalize_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_mkdir_happens_inside_worker_for_nonexistent_dest_dir(self):
        dest_dir = self.tmpdir / "does" / "not" / "exist" / "yet"
        self.assertFalse(dest_dir.exists())

        src = self.tmpdir / "cover.png"
        src.write_bytes(b"COVER-BYTES")
        tmp = dest_dir / "covers.png.tmp"
        final = dest_dir / "covers.png"

        groups = [{"copies": [(src, tmp)], "deletes": [], "renames": [(tmp, final)]}]
        results = mcw.copy_finalize_groups(dest_dir, groups)

        self.assertTrue(results[str(tmp)])
        self.assertTrue(final.exists())
        self.assertEqual(final.read_bytes(), b"COVER-BYTES")
        self.assertFalse(tmp.exists(), "확정된 그룹은 tmp가 최종 이름으로 rename되어 남아있지 않아야 함")

    def test_successful_group_deletes_old_file_and_renames_tmp_to_final(self):
        dest_dir = self.tmpdir / "snes" / "Mario"
        dest_dir.mkdir(parents=True)
        old_final = dest_dir / "covers.jpg"  # 예전 확장자
        old_final.write_bytes(b"OLD-JPG")

        src = self.tmpdir / "new_cover.png"
        src.write_bytes(b"NEW-PNG")
        tmp = dest_dir / "covers.png.tmp"
        new_final = dest_dir / "covers.png"

        groups = [{"copies": [(src, tmp)], "deletes": [old_final], "renames": [(tmp, new_final)]}]
        results = mcw.copy_finalize_groups(dest_dir, groups)

        self.assertTrue(results[str(tmp)])
        self.assertFalse(old_final.exists(), "확정된 그룹은 기존(다른 확장자) 파일을 지워야 함")
        self.assertTrue(new_final.exists())
        self.assertEqual(new_final.read_bytes(), b"NEW-PNG")

    def test_failed_copy_in_group_leaves_existing_file_and_cleans_up_tmp(self):
        dest_dir = self.tmpdir / "snes" / "Zelda"
        dest_dir.mkdir(parents=True)
        existing_final = dest_dir / "covers.png"
        existing_final.write_bytes(b"EXISTING-COVER")

        good_src = self.tmpdir / "wheel.png"
        good_src.write_bytes(b"WHEEL-BYTES")
        missing_src = self.tmpdir / "does_not_exist.png"

        good_tmp = dest_dir / "covers_0.png.tmp"
        bad_tmp = dest_dir / "covers_1.png.tmp"
        good_final = dest_dir / "covers_0.png"
        bad_final = dest_dir / "covers_1.png"

        # 한 그룹(=media type "covers") 안에 파일 2개, 하나는 존재하지 않는
        # 소스 - _copy_media_to_masterdb가 실제로 이렇게 부르진 않지만(소스
        # 존재 확인은 Python이 먼저 함), copy_finalize_groups() 자체가
        # "그룹 안 하나라도 실패하면 전부 롤백"을 지키는지는 이 레벨에서
        # 직접 검증해야 한다.
        groups = [{
            "copies": [(good_src, good_tmp), (missing_src, bad_tmp)],
            "deletes": [existing_final],
            "renames": [(good_tmp, good_final), (bad_tmp, bad_final)],
        }]
        results = mcw.copy_finalize_groups(dest_dir, groups)

        self.assertTrue(results[str(good_tmp)])
        self.assertFalse(results[str(bad_tmp)])
        # 그룹 전체가 미확정이어야 한다: 기존 파일이 그대로 남아있고,
        # 성공했던 쪽의 tmp/final도 만들어지면 안 된다.
        self.assertTrue(existing_final.exists(), "그룹 일부만 실패해도 기존 파일은 삭제되면 안 됨")
        self.assertEqual(existing_final.read_bytes(), b"EXISTING-COVER")
        self.assertFalse(good_final.exists(), "그룹이 확정되지 않았으면 성공한 파일도 rename되면 안 됨")
        self.assertFalse(good_tmp.exists(), "확정 안 된 그룹의 tmp는 정리되어야 함")
        self.assertFalse(bad_tmp.exists())

    def test_independent_groups_do_not_affect_each_other(self):
        dest_dir = self.tmpdir / "nes" / "Contra"
        dest_dir.mkdir(parents=True)

        good_src = self.tmpdir / "good.png"
        good_src.write_bytes(b"GOOD")
        missing_src = self.tmpdir / "missing.png"

        covers_tmp = dest_dir / "covers.png.tmp"
        covers_final = dest_dir / "covers.png"
        wheel_tmp = dest_dir / "wheel.png.tmp"
        wheel_final = dest_dir / "wheel.png"

        groups = [
            {"copies": [(good_src, covers_tmp)], "deletes": [], "renames": [(covers_tmp, covers_final)]},
            {"copies": [(missing_src, wheel_tmp)], "deletes": [], "renames": [(wheel_tmp, wheel_final)]},
        ]
        results = mcw.copy_finalize_groups(dest_dir, groups)

        self.assertTrue(results[str(covers_tmp)])
        self.assertTrue(covers_final.exists())
        self.assertFalse(results[str(wheel_tmp)])
        self.assertFalse(wheel_final.exists())


class FinalizeGroupsParserRobustnessTests(unittest.TestCase):
    """copy_finalize_groups()도 copy_pairs()와 동일한 stdout 신뢰 규칙을
    쓰는지(공유 _parse_worker_output 경유) mock으로 빠르게 확인한다."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="mcw_finalize_parser_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self._avail_patch = patch.object(mcw, "worker_available", return_value=True)
        self._avail_patch.start()
        self.addCleanup(self._avail_patch.stop)

        self.src = self.tmpdir / "src.png"
        self.src.write_bytes(b"X")
        self.dest_dir = self.tmpdir / "dest"
        self.tmp = self.dest_dir / "covers.png.tmp"
        self.final = self.dest_dir / "covers.png"
        self.groups = [{"copies": [(self.src, self.tmp)], "deletes": [], "renames": [(self.tmp, self.final)]}]

    def test_returncode_ge_2_falls_back_and_still_finalizes(self):
        with patch("subprocess.run", return_value=_FakeCompletedProcess("", returncode=2)):
            results = mcw.copy_finalize_groups(self.dest_dir, self.groups)
        self.assertTrue(results[str(self.tmp)])
        self.assertTrue(self.final.exists())

    def test_malformed_status_falls_back_to_reprocessing_whole_group(self):
        with patch("subprocess.run", return_value=_FakeCompletedProcess("GARBLED 0\n", returncode=1)):
            results = mcw.copy_finalize_groups(self.dest_dir, self.groups)
        self.assertTrue(results[str(self.tmp)])
        self.assertTrue(self.final.exists())


@unittest.skipUnless(mcw.worker_available(), "native/MediaCopyWorker.exe가 빌드돼 있지 않음 - native/build_worker.bat 먼저 실행")
class WorkerJobFileRobustnessTests(unittest.TestCase):
    """[리뷰 반영, P0] native/MediaCopyWorker.exe 자신의 job 파서가 손상된
    입력(형식이 깨진 C/R 줄, MAX_GROUP_ENTRIES 초과)을 만났을 때 "일부만
    등록된 채로 그룹을 성공 확정"해버리지 않는지 직접 검증한다.
    media_copy_worker.py는 항상 올바른 job을 만들어 보내므로 이 시나리오를
    재현하려면 job 파일을 손으로 만들어서 워커를 직접 호출해야 한다 -
    Python wrapper API로는 이 경로를 자연스럽게 못 만든다."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="mcw_jobfile_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def _run_worker(self, job_lines):
        import subprocess

        job_path = self.tmpdir / "manual.job"
        job_path.write_text("\n".join(job_lines) + "\n", encoding="utf-8")
        return subprocess.run(
            [str(mcw.WORKER_PATH), str(job_path)],
            capture_output=True, text=True, timeout=30,
        )

    def test_malformed_c_line_prevents_group_from_finalizing(self):
        """그룹 안에 정상 C가 하나, 형식이 깨진(탭 부족) C가 하나 있으면
        - 정상 C는 개별적으로 성공해도(OK가 찍혀도) - 그룹 전체는 확정되면
        안 된다(기존 파일 삭제/최종 rename이 일어나면 안 됨)."""
        dest_dir = self.tmpdir / "dest"
        old_final = dest_dir / "covers.png"
        good_src = self.tmpdir / "good.png"
        good_src.write_bytes(b"GOOD")
        good_tmp = dest_dir / "covers.png.tmp"
        good_final = dest_dir / "covers.png"

        dest_dir.mkdir(parents=True)
        old_final.write_bytes(b"EXISTING")

        job_lines = [
            f"M\t{dest_dir}",
            "G\t_",
            f"C\t0\t{good_src}\t{good_tmp}",
            "C\tBROKEN_NO_TABS_HERE",  # 형식이 깨진 C - 탭이 없음
            f"X\t{old_final}",
            f"R\t{good_tmp}\t{good_final}",
        ]
        result = self._run_worker(job_lines)

        self.assertEqual(result.returncode, 1, "손상된 job은 exit code 1이어야 함")
        self.assertIn("OK 0", result.stdout, "정상 C는 개별적으로는 여전히 실행/보고돼야 함")
        # 그룹이 확정 안 됐으므로(group_corrupted): X(삭제)/R(rename)은 전혀
        # 실행되지 않고, 이번에 성공했던 tmp 복사분은 정리(삭제)된다 -
        # 원래 실패 그룹 처리와 동일.
        self.assertFalse(good_tmp.exists(), "확정 안 된 그룹은 성공했던 tmp도 정리(삭제)돼야 함")
        self.assertTrue(old_final.exists(), "그룹이 확정 안 됐으면 기존 파일이 삭제되면 안 됨")
        self.assertEqual(old_final.read_bytes(), b"EXISTING")

    def test_max_group_entries_overflow_prevents_finalization(self):
        """[리뷰 반영] MAX_GROUP_ENTRIES(1024)를 넘는 C를 같은 그룹에 보내면,
        앞의 1024개가 전부 성공하더라도 그룹이 확정되면 안 된다 - 등록 못한
        나머지가 계획에서 조용히 빠진 채로 rename/delete가 실행되는 걸
        막아야 한다."""
        dest_dir = self.tmpdir / "dest_overflow"
        dest_dir.mkdir(parents=True)
        old_final = dest_dir / "screenshots_0.png"
        old_final.write_bytes(b"EXISTING-SCREENSHOT")

        src_dir = self.tmpdir / "src"
        src_dir.mkdir()
        shared_src = src_dir / "shared.png"
        shared_src.write_bytes(b"S")

        job_lines = [f"M\t{dest_dir}", "G\t_"]
        # MAX_GROUP_ENTRIES=1024이므로 1030개를 보내 확실히 넘긴다. 전부
        # 같은 소스를 가리켜서 파일시스템 부담 없이 빠르게 실행되게 한다.
        n = 1030
        for i in range(n):
            tmp = dest_dir / f"screenshots_{i}.png.tmp"
            job_lines.append(f"C\t{i}\t{shared_src}\t{tmp}")
        job_lines.append(f"X\t{old_final}")
        for i in range(n):
            tmp = dest_dir / f"screenshots_{i}.png.tmp"
            final = dest_dir / f"screenshots_{i}.png"
            job_lines.append(f"R\t{tmp}\t{final}")

        result = self._run_worker(job_lines)

        self.assertEqual(result.returncode, 1, "overflow가 있었으므로 exit code 1이어야 함")
        # 그룹이 확정되지 않았으므로: 기존 파일(X 대상)의 내용이 그대로여야
        # 하고("screenshots_0.png"는 old_final과 이름이 같음 - rename됐다면
        # 내용이 b"S"로 바뀌었을 것), rename 자체가 하나도 실행되지 않아야
        # 하므로 다른 index의 최종 이름도 생기면 안 된다.
        self.assertEqual(old_final.read_bytes(), b"EXISTING-SCREENSHOT",
                          "그룹이 확정 안 됐으면 기존 파일 내용이 rename으로 덮이면 안 됨")
        self.assertFalse((dest_dir / "screenshots_1.png").exists(),
                          "확정 안 된 그룹은 등록됐던 다른 index도 rename되면 안 됨")


@unittest.skipUnless(mcw.worker_available(), "native/MediaCopyWorker.exe가 빌드돼 있지 않음 - native/build_worker.bat 먼저 실행")
class RealWorkerCopyFilesAndMultiDirIntegrationTests(unittest.TestCase):
    """[Phase 2] copy_files()와 copy_finalize_groups()의 다중 dest_dirs
    지원을 실제 컴파일된 워커로 검증한다. MasterDB -> Local 방향
    (export_engine.py/exporters/*)이 쓰는 게 이 경로다 - media type마다
    목적지 폴더가 다른 es-de 스타일 구조를 한 번의 워커 호출로 처리할 수
    있어야 한다."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="mcw_copyfiles_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_copy_files_creates_multiple_missing_dest_dirs_in_one_call(self):
        """es-de 스타일: covers/screenshots/marquees가 전부 다른(아직 없는)
        폴더 - 한 번의 copy_files() 호출로 셋 다 생겨야 한다."""
        covers_src = self.tmpdir / "cover.png"
        covers_src.write_bytes(b"COVER")
        shots_src = self.tmpdir / "shot.png"
        shots_src.write_bytes(b"SHOT")

        covers_dir = self.tmpdir / "downloaded_media" / "snes" / "covers"
        shots_dir = self.tmpdir / "downloaded_media" / "snes" / "screenshots"
        marquees_dir = self.tmpdir / "downloaded_media" / "snes" / "marquees"  # 이 폴더로는 아무것도 안 감

        pairs = [
            (covers_src, covers_dir / "Mario.png"),
            (shots_src, shots_dir / "Mario.png"),
        ]
        results = mcw.copy_files([covers_dir, shots_dir, marquees_dir], pairs)

        self.assertTrue(results[str(covers_dir / "Mario.png")])
        self.assertTrue(results[str(shots_dir / "Mario.png")])
        self.assertEqual((covers_dir / "Mario.png").read_bytes(), b"COVER")
        self.assertEqual((shots_dir / "Mario.png").read_bytes(), b"SHOT")
        # 파일이 없더라도 요청한 디렉터리는 전부 생겨야 한다(M 명령은
        # copies와 무관하게 독립적으로 처리됨).
        self.assertTrue(marquees_dir.is_dir(), "파일이 없는 디렉터리도 M 명령으로 생성돼야 함")

    def test_copy_files_one_failure_does_not_affect_other_independent_pairs(self):
        """copy_files()는 그룹 원자성이 없다(삭제/rename 자체가 없으므로) -
        하나가 실패해도 다른 pair는 정상적으로 복사돼야 한다."""
        good_src = self.tmpdir / "good.png"
        good_src.write_bytes(b"GOOD")
        missing_src = self.tmpdir / "missing.png"
        dest_dir = self.tmpdir / "dest"

        pairs = [(good_src, dest_dir / "good_out.png"), (missing_src, dest_dir / "missing_out.png")]
        results = mcw.copy_files([dest_dir], pairs)

        self.assertTrue(results[str(dest_dir / "good_out.png")])
        self.assertEqual((dest_dir / "good_out.png").read_bytes(), b"GOOD")
        self.assertFalse(results[str(dest_dir / "missing_out.png")])
        self.assertFalse((dest_dir / "missing_out.png").exists())

    def test_copy_files_single_path_still_works(self):
        """dest_dirs로 리스트가 아니라 Path 하나만 줘도(예전 API와 호환)
        정상 동작해야 한다."""
        src = self.tmpdir / "src.png"
        src.write_bytes(b"X")
        dest_dir = self.tmpdir / "single_dir"

        results = mcw.copy_files(dest_dir, [(src, dest_dir / "out.png")])
        self.assertTrue(results[str(dest_dir / "out.png")])


if __name__ == "__main__":
    unittest.main()
