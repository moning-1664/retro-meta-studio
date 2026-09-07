"""
storage/local.py
=================
드라이브 문자(C:\\, E:\\ - SD카드/USB 포함)와 UNC 경로(\\\\device\\share)용 Provider.

둘을 하나의 구현으로 처리하되 `supports_watch`만 다르다. UNC에서는 File System
Watcher를 신뢰할 수 없어서(변경 알림이 유실되거나 아예 오지 않는 환경이 있다)
주기적 Validation Scan으로 대체한다.

파일 동일성(`file_id`)은 Windows에서 `os.stat()`의 `st_dev`(볼륨 일련번호)와
`st_ino`(파일 인덱스)로 얻는다 - CPython이 내부적으로 GetFileInformationByHandle을
쓰기 때문에 ctypes 없이도 정확하다. 네트워크 공유에서는 값이 0이거나 신뢰할 수
없을 수 있어서, 그 경우 None을 돌려주고 상위 계층이 정규화 경로 비교로 대체한다.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from storage.provider import DirEntry, Stat, StorageProvider, VolumeInfo


class LocalStorageProvider(StorageProvider):
    id = "local"

    def __init__(self, *, supports_watch=True):
        self.supports_watch = supports_watch

    @classmethod
    def for_path(cls, path) -> "LocalStorageProvider":
        """UNC 경로면 Watcher를 끈 Provider를 돌려준다."""
        text = str(path).replace("/", "\\")
        return cls(supports_watch=not text.startswith("\\\\"))

    def exists(self, path) -> bool:
        try:
            return Path(path).exists()
        except OSError:
            return False

    def stat(self, path) -> Stat | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        return Stat(size=st.st_size, mtime_ns=st.st_mtime_ns,
                    is_dir=os.path.isdir(path), file_id=self._file_id(st))

    def scandir(self, path) -> list[DirEntry]:
        entries = []
        try:
            with os.scandir(path) as it:
                for e in it:
                    try:
                        st = e.stat()
                        entries.append(DirEntry(name=e.name, path=e.path, is_dir=e.is_dir(),
                                                size=st.st_size, mtime_ns=st.st_mtime_ns))
                    except OSError:
                        # 개별 항목의 stat 실패가 디렉터리 전체 열거를 망치면 안 된다.
                        entries.append(DirEntry(name=e.name, path=e.path, is_dir=False))
        except OSError:
            return []
        return entries

    def volume_info(self, path) -> VolumeInfo:
        try:
            usage = shutil.disk_usage(str(path))
            capacity, free = usage.total, usage.free
        except OSError:
            # 용량을 못 읽는 저장소는 Unknown으로 둔다 - 오류가 아니다(§5).
            capacity = free = None
        return VolumeInfo(volume_key=self._volume_key(path), capacity_bytes=capacity, free_bytes=free)

    def copy_engine(self):
        from engines.native_worker_engine import NativeWorkerEngine
        return NativeWorkerEngine()

    # ------------------------------------------------------------------
    @staticmethod
    def _file_id(st) -> str | None:
        dev, ino = getattr(st, "st_dev", 0), getattr(st, "st_ino", 0)
        if not dev or not ino:
            return None
        return f"{dev}:{ino}"

    @staticmethod
    def _volume_key(path) -> str | None:
        """같은 물리 볼륨인지 판정하는 키.

        드라이브 문자는 앵커(`E:\\`)를, UNC는 `\\\\server\\share`까지를 키로 쓴다.
        디스크 일련번호를 쓰면 더 정확하지만, 드라이브 문자가 바뀌는 상황(USB 재연결)은
        어차피 사용자가 경로를 다시 지정해야 하는 상황이라 이득이 크지 않다.
        """
        try:
            resolved = Path(path).resolve()
        except OSError:
            resolved = Path(path)
        text = str(resolved).replace("/", "\\")
        if text.startswith("\\\\"):
            parts = [p for p in text.split("\\") if p]
            return "\\\\" + "\\".join(parts[:2]) if len(parts) >= 2 else text
        anchor = resolved.anchor
        return anchor or None
