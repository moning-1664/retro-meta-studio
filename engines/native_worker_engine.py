"""
engines/native_worker_engine.py
=================================
CopyEngine을 native/MediaCopyWorker.exe(media_copy_worker.py)로 구현한다.

로직은 전혀 새로 만들지 않는다 - media_copy_worker.py의 기존 3개 공개
함수를 그대로 위임하는 얇은 어댑터다. media_copy_worker.py 자체(job
프로토콜 인코딩, fallback, 파서 신뢰 규칙 등)는 여기서 건드리지 않는다.
"""

import media_copy_worker
from engines.base import CopyEngine


class NativeWorkerEngine(CopyEngine):
    def copy_pairs(self, pairs: list, timeout_sec: float = 120.0) -> dict:
        return media_copy_worker.copy_pairs(pairs, timeout_sec=timeout_sec)

    def copy_files(self, dest_dirs, pairs: list, timeout_sec: float = 180.0) -> dict:
        return media_copy_worker.copy_files(dest_dirs, pairs, timeout_sec=timeout_sec)

    def copy_finalize_groups(self, dest_dirs, groups: list, timeout_sec: float = 180.0) -> dict:
        try:
            return media_copy_worker.copy_finalize_groups(dest_dirs, groups, timeout_sec=timeout_sec)
        except OSError:
            # 계약상 백엔드 실패는 예외가 아니라 결과로 보고해야 한다. 목적지 폴더를
            # 만들 수 없는 경우(같은 이름의 파일이 이미 있음 등)가 여기로 온다.
            return {}

    def delete_paths(self, paths, timeout_sec: float = 180.0) -> dict:
        """copies가 빈 그룹 하나로 표현한다 - "모든 copy 성공" 조건이 자동으로 참이라
        deletes가 그대로 실행된다. 워커는 항목별 삭제 결과를 주지 않으므로 실제로
        사라졌는지로 판정한다."""
        from pathlib import Path

        paths = [Path(p) for p in paths]
        if not paths:
            return {}
        self.copy_finalize_groups([], [{"copies": [], "deletes": paths, "renames": []}],
                                  timeout_sec=timeout_sec)
        return {str(p): not p.exists() for p in paths}

    def move_pairs(self, pairs, timeout_sec: float = 300.0) -> dict:
        """쌍마다 "임시 파일로 복사 -> 원본 삭제 -> 최종 이름으로 rename" 그룹을 만든다.
        복사가 실패하면 그룹이 확정되지 않아 원본이 그대로 남는다."""
        from pathlib import Path

        pairs = [(Path(s), Path(d)) for s, d in pairs]
        if not pairs:
            return {}
        dest_dirs, groups, tmp_of = [], [], {}
        for src, dest in pairs:
            tmp = dest.with_name(dest.name + ".rmstmp")
            tmp_of[str(dest)] = str(tmp)
            dest_dirs.append(dest.parent)
            groups.append({"copies": [(src, tmp)], "deletes": [src], "renames": [(tmp, dest)]})
        results = self.copy_finalize_groups(dest_dirs, groups, timeout_sec=timeout_sec)
        return {str(dest): bool(results.get(tmp_of[str(dest)])) and dest.exists()
                for _, dest in pairs}
