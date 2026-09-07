"""
disk_utils.py
==============
Export 등 대량 파일 복사 작업 전에 대상 드라이브의 여유 공간을 미리 확인하기 위한 유틸.
외부 의존성 없이 표준 라이브러리 shutil.disk_usage만 사용한다.
"""

import shutil
from pathlib import Path


def get_free_bytes(path):
    """path가 위치한 드라이브/파일시스템의 여유 공간(바이트). path가 아직 없는 폴더여도
    가장 가까운 존재하는 상위 폴더를 찾아 그 드라이브 기준으로 계산한다."""
    p = Path(path)
    while not p.exists():
        parent = p.parent
        if parent == p:  # 루트까지 올라갔는데도 없으면 포기
            break
        p = parent
    return shutil.disk_usage(p).free


def check_space_for_copy(dest_path, required_bytes, margin_bytes=100 * 1024 * 1024):
    """
    dest_path가 위치한 드라이브에 required_bytes를 복사할 여유 공간이 있는지 확인.
    margin_bytes(기본 100MB)만큼 여유를 더 두어, 딱 맞는 상황에서 실패하는 걸 방지한다.

    반환: {"ok": bool, "free": int, "required": int, "shortage": int}
    shortage는 부족한 양(바이트). ok=True면 0.
    """
    free = get_free_bytes(dest_path)
    needed = required_bytes + margin_bytes
    shortage = max(0, needed - free)
    return {"ok": shortage == 0, "free": free, "required": required_bytes, "shortage": shortage}


def format_bytes(n):
    """사람이 읽기 좋은 형태로 바이트 수 포맷 (예: 1.21 GB)."""
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
