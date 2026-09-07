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
        return media_copy_worker.copy_finalize_groups(dest_dirs, groups, timeout_sec=timeout_sec)
