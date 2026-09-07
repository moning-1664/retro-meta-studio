"""
engines/robocopy_engine.py
===========================
Windows 내장 Robocopy로 CopyEngine을 구현한다.

**왜 필요한가.** 네이티브 워커(MediaCopyWorker.exe)는 서명되지 않은 실행 파일이
대량 파일 작업을 반복하는 형태라, 백신(AhnLab)의 행동 기반 탐지에 걸린다는 실사용
보고가 있다. `GOLDEN_VALIDATION.md`에 기록된 무탐지 실측은 특정 시점의 한 번일 뿐
보장이 아니다 - 탐지 규칙은 언제든 바뀐다.

Robocopy는 Windows에 기본 포함된 **마이크로소프트 서명 바이너리**라 그 문제에서
자유롭다. 부모 프로세스가 직접 파일 API를 두드리지 않는다는 성질(워커를 쓰는 원래
이유)도 그대로다.

**설계상 제약과 대응**
- Robocopy는 복사하면서 이름을 바꾸지 못한다. 그래서 이름이 같은 쌍은 디렉터리
  단위로 묶어 한 번에 처리하고, 이름이 다른 쌍만 따로 `move` 명령으로 마무리한다.
  실무에서 이름이 달라지는 경우는 드물다(ROM도 media도 대개 이름을 유지한다).
- 이동은 `/MOV`로 네이티브 지원된다. 임시 파일을 만들고 rename하는 우회가 필요 없다.
- 삭제는 Robocopy가 못 하므로 `cmd /c del`에 여러 파일을 한 번에 넘긴다. 이것도
  부모 프로세스가 아니라 시스템 바이너리가 수행한다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from engines.base import CopyEngine

#: Robocopy는 8 미만이면 성공이다(0=복사할 것 없음, 1=복사됨, 2=추가 파일 있음 ...).
ROBOCOPY_SUCCESS_MAX = 8

#: cmd 명령줄 길이 한계(8191)에 여유를 둔 값.
COMMAND_LENGTH_BUDGET = 6000

_CREATE_NO_WINDOW = 0x08000000

#: 이름을 바꾸며 복사할 때 거쳐가는 임시 하위 폴더. 목적지의 기존 파일을 건드리지
#: 않기 위해 필요하다.
STAGE_DIR_NAME = ".rms-stage"


def robocopy_available() -> bool:
    return bool(_robocopy_path())


def _robocopy_path():
    found = shutil.which("robocopy")
    if found:
        return found
    fallback = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "Robocopy.exe"
    return str(fallback) if fallback.exists() else None


def _ensure_dir(path) -> bool:
    """디렉터리를 만든다. 실패해도 예외를 던지지 않는다.

    CopyEngine 계약상 백엔드 실패는 그 항목만 실패로 표시해야 한다 - 같은 이름의
    파일이 이미 있어서 폴더를 못 만드는 경우에도 호출자는 완전한 결과 dict를 받아야 한다.
    """
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def _run(args, timeout_sec):
    """콘솔 창이 깜박이지 않게 CREATE_NO_WINDOW로 실행한다."""
    try:
        completed = subprocess.run(
            args, capture_output=True, timeout=timeout_sec,
            creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return completed.returncode
    except (subprocess.TimeoutExpired, OSError):
        return 9999


class RobocopyEngine(CopyEngine):
    id = "robocopy"

    def __init__(self, executable=None):
        self.executable = executable or _robocopy_path()

    # ------------------------------------------------------------------
    def copy_pairs(self, pairs: list, timeout_sec: float = 120.0) -> dict:
        return self._copy(pairs, timeout_sec, make_dirs=False)

    def copy_files(self, dest_dirs, pairs: list, timeout_sec: float = 180.0) -> dict:
        dest_dirs = [dest_dirs] if isinstance(dest_dirs, (str, Path)) else list(dest_dirs or [])
        return self._copy(pairs, timeout_sec, make_dirs=True, extra_dirs=dest_dirs)

    def copy_finalize_groups(self, dest_dirs, groups: list, timeout_sec: float = 180.0) -> dict:
        """그룹 원자성 계약을 지킨다: 그룹의 모든 copy가 성공해야 delete/rename을 한다.

        Robocopy로 복사한 뒤 delete/rename은 시스템 명령으로 처리한다.
        """
        dest_dirs = [dest_dirs] if isinstance(dest_dirs, (str, Path)) else list(dest_dirs or [])
        results = {}
        for group in groups:
            copies = [(Path(s), Path(t)) for s, t in group.get("copies", [])]
            copied = self._copy(copies, timeout_sec, make_dirs=True, extra_dirs=dest_dirs) if copies else {}
            results.update(copied)
            if copies and not all(copied.get(str(t)) for _, t in copies):
                # 확정하지 않는다. 이번에 만든 임시 파일만 정리하고 기존 파일은 남긴다.
                self.delete_paths([t for _, t in copies if t.exists()], timeout_sec)
                continue
            deletes = [Path(p) for p in group.get("deletes", [])]
            if deletes:
                self.delete_paths(deletes, timeout_sec)
            for src, dest in group.get("renames", []):
                self._move_one(Path(src), Path(dest), timeout_sec)
        return results

    # ------------------------------------------------------------------
    def delete_paths(self, paths, timeout_sec: float = 180.0) -> dict:
        """`cmd /c del`에 여러 파일을 한 번에 넘긴다. 명령줄 길이에 맞춰 나눠 보낸다."""
        paths = [Path(p) for p in paths]
        if not paths:
            return {}
        batch, length = [], 0
        for path in paths:
            # 따옴표는 subprocess가 필요할 때만 붙인다. 여기서 직접 붙이면 그 문자가
            # 파일명의 일부로 넘어가서 명령이 조용히 실패한다.
            if batch and length + len(str(path)) > COMMAND_LENGTH_BUDGET:
                _run(["cmd", "/c", "del", "/f", "/q", *[str(p) for p in batch]], timeout_sec)
                batch, length = [], 0
            batch.append(path)
            length += len(str(path)) + 3
        if batch:
            _run(["cmd", "/c", "del", "/f", "/q", *[str(p) for p in batch]], timeout_sec)
        # del은 항목별 성공 여부를 주지 않으므로 실제로 사라졌는지로 판정한다.
        return {str(p): not p.exists() for p in paths}

    def move_pairs(self, pairs, timeout_sec: float = 300.0) -> dict:
        """Robocopy `/MOV`로 이동한다. 임시 파일 + rename 우회가 필요 없다."""
        pairs = [(Path(s), Path(d)) for s, d in pairs]
        same_name, renamed = [], []
        for src, dest in pairs:
            (same_name if src.name == dest.name else renamed).append((src, dest))

        results = {}
        for (src_dir, dest_dir), items in _group_by_dirs(same_name).items():
            if not _ensure_dir(dest_dir):
                for _, dest in items:
                    results[str(dest)] = False
                continue
            for chunk in _chunk_names([s.name for s, _ in items]):
                _run([self.executable, str(src_dir), str(dest_dir), *chunk,
                      "/MOV", "/NJH", "/NJS", "/NP", "/NDL", "/NC", "/NS", "/R:1", "/W:1"], timeout_sec)
            for _, dest in items:
                results[str(dest)] = dest.exists()

        for src, dest in renamed:
            results[str(dest)] = self._move_one(src, dest, timeout_sec)
        return results

    # ------------------------------------------------------------------
    def _copy(self, pairs, timeout_sec, make_dirs, extra_dirs=()):
        pairs = [(Path(s), Path(d)) for s, d in pairs]
        for directory in extra_dirs:
            _ensure_dir(directory)
        if not pairs:
            return {}

        results = {}
        same_name = [(s, d) for s, d in pairs if s.name == d.name]
        renamed = [(s, d) for s, d in pairs if s.name != d.name]

        for (src_dir, dest_dir), items in _group_by_dirs(same_name).items():
            if make_dirs and not _ensure_dir(dest_dir):
                for _, dest in items:
                    results[str(dest)] = False
                continue
            for chunk in _chunk_names([s.name for s, _ in items]):
                _run([self.executable, str(src_dir), str(dest_dir), *chunk,
                      "/NJH", "/NJS", "/NP", "/NDL", "/NC", "/NS", "/R:1", "/W:1"], timeout_sec)
            for _, dest in items:
                results[str(dest)] = dest.exists()

        # 이름이 바뀌는 쌍: Robocopy는 복사하면서 이름을 못 바꾼다. 임시 하위 폴더에
        # 원본 이름으로 받은 뒤 최종 이름으로 옮긴다. 목적지에 원본 이름으로 바로
        # 놓으면 같은 이름의 기존 파일을 덮어쓸 수 있어서 반드시 거쳐야 한다.
        for src, dest in renamed:
            if not _ensure_dir(dest.parent):
                results[str(dest)] = False
                continue
            stage_dir = dest.parent / STAGE_DIR_NAME
            staged = stage_dir / src.name
            code = _run([self.executable, str(src.parent), str(stage_dir), src.name,
                         "/NJH", "/NJS", "/NP", "/NDL", "/NC", "/NS", "/R:1", "/W:1"], timeout_sec)
            moved = (code < ROBOCOPY_SUCCESS_MAX and staged.exists()
                     and self._move_one(staged, dest, timeout_sec))
            results[str(dest)] = moved
            if staged.exists():
                self.delete_paths([staged], timeout_sec)
            try:
                stage_dir.rmdir()
            except OSError:
                pass
        return results

    def _move_one(self, src, dest, timeout_sec) -> bool:
        src, dest = Path(src), Path(dest)
        if not src.exists() or not _ensure_dir(dest.parent):
            return False
        _run(["cmd", "/c", "move", "/y", str(src), str(dest)], timeout_sec)
        return dest.exists()


def _group_by_dirs(pairs):
    grouped = defaultdict(list)
    for src, dest in pairs:
        grouped[(str(src.parent), str(dest.parent))].append((src, dest))
    return grouped


def _chunk_names(names):
    """Robocopy 한 번에 넘길 파일 이름 묶음. 명령줄 길이 한계를 넘지 않게 나눈다."""
    chunk, length = [], 0
    for name in names:
        quoted = f'"{name}"'
        if chunk and length + len(quoted) > COMMAND_LENGTH_BUDGET:
            yield chunk
            chunk, length = [], 0
        chunk.append(name)
        length += len(quoted) + 1
    if chunk:
        yield chunk
