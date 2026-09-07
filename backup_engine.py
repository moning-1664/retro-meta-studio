"""
backup_engine.py
==================
MasterDB 백업/복원 (설계서 후속 §백업/복원).

- 백업 파일은 실행 파일과 동일 디렉토리의 backup/ 폴더에 저장한다 (config.BACKUP_DIR).
- 파일명은 자동으로 날짜/시각을 postfix로 붙여 생성한다: masterdb_backup_YYYYMMDD_HHMMSS.zip
- 별도의 자동 정리(오래된 백업 삭제) 기능은 두지 않는다 - 사용자가 수동으로 관리한다.
"""

import shutil
import zipfile
from pathlib import Path
from datetime import datetime

import config as cfgmod


def create_backup(masterdb_root):
    """MasterDB 전체를 backup/ 디렉토리에 zip으로 백업. 반환: 생성된 파일 경로(str).

    [v0.5 8단계, WAL 전환 후속 수정] master.db-wal/master.db-shm(SQLite WAL 모드
    사이드카 파일)은 백업에서 제외한다. api.py의 do_backup()이 이 함수를 부르기 전에
    항상 WAL checkpoint(TRUNCATE)를 실행해 커밋된 데이터를 전부 master.db 본체로
    합쳐두므로 제외해도 데이터 유실이 없고, -shm(공유 메모리 매핑 파일)은 Windows에서
    shutil.make_archive로 zip에 포함시키려 하면 `[Errno 22] Invalid argument`로
    실패하는 게 실제로 재현됨 - 그래서 디렉토리 전체를 도는 shutil.make_archive 대신
    직접 zipfile로 원하는 파일만 골라 담는다."""
    cfgmod.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = cfgmod.BACKUP_DIR / f"masterdb_backup_{timestamp}.zip"
    root = Path(masterdb_root)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if path.is_dir() or path.name.endswith(("-wal", "-shm")):
                continue
            zf.write(path, path.relative_to(root))
    return str(archive_path)


def list_backups():
    """backup/ 디렉토리 내 백업 파일 목록을 최신순으로 반환."""
    if not cfgmod.BACKUP_DIR.exists():
        return []
    files = sorted(cfgmod.BACKUP_DIR.glob("masterdb_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def restore_backup(backup_path, masterdb_root):
    """지정된 백업 zip을 masterdb_root에 풀어 복원한다."""
    shutil.unpack_archive(str(backup_path), masterdb_root)
