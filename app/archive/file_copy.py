"""Copy once beside the destination, then publish complete bytes atomically."""

from pathlib import Path
import os
import shutil
import uuid


def _state(path):
    try:
        stat = Path(path).stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def copy_complete(source, destination, *, replace=False, move_backup=False):
    """Keep the existing destination on failure; never read a content hash.

    The Archive edit lease serializes participating writers. State checks also
    reject changes made by outside tools during the copy. This is file-level
    protection, not a transaction over the Archive DB and frontend indexes.
    """
    source, destination = Path(source), Path(destination)
    before = _state(source)
    if before is None:
        raise FileNotFoundError(source)
    old = _state(destination)
    if old is not None and os.path.samefile(source, destination):
        return False
    if old is not None and not replace:
        raise FileExistsError(destination)
    from app.archive.undo import before_copy, before_publish_file, protect_existing, current_transaction, track_temporary
    if move_backup and not current_transaction():
        raise ValueError("ROM 교체에는 복구 기록이 필요합니다.")
    before_copy(destination, moved=move_backup)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.rms-part")
    track_temporary(destination, temporary)
    try:
        shutil.copy2(source, temporary)
        if _state(source) != before or temporary.stat().st_size != before[0]:
            raise OSError(f"복사 중 원본이 바뀌었거나 크기가 다릅니다: {source}")
        if _state(destination) != old:
            raise OSError(f"복사 중 대상 파일이 바뀌었습니다: {destination}")
        before_publish_file(destination, temporary)
        if move_backup:
            protect_existing(destination)
        if replace:
            os.replace(temporary, destination)
        elif os.name == "nt":
            # Windows rename refuses an existing destination, including one
            # created between the state check and this call.
            os.rename(temporary, destination)
        else:
            os.link(temporary, destination)
            temporary.unlink()
        return True
    finally:
        if temporary.exists():
            temporary.unlink()
