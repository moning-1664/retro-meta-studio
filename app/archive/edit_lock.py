"""Shared filesystem lease covering Archive DB and frontend writes together."""

from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import json
import os
import socket
import threading
import time
import uuid

_held = threading.local()


def lock_path(root):
    return Path(root) / ".rms" / "edit.lock"


def status(root):
    path = lock_path(root)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"host": "unknown", "unreadable": True}


@contextmanager
def writing(root):
    path = lock_path(root)
    key = str(path.absolute()).casefold()
    held = getattr(_held, "paths", {})
    if key in held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.with_suffix(".takeover").exists():
        raise ValueError("Archive 편집 잠금을 인계하는 중입니다. 잠시 뒤 다시 시도하세요.")
    owner = {"token": uuid.uuid4().hex, "host": socket.gethostname(),
             "pid": os.getpid(), "startedAt": time.time()}
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        current = status(root) or {}
        raise ValueError(f"다른 Archive 편집이 진행 중입니다 ({current.get('host', '?')}). "
                         "편집이 끝난 뒤 다시 시도하세요. 중단된 잠금은 자동 해제하지 않습니다.") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(owner, stream)
            stream.flush()
            os.fsync(stream.fileno())
        if path.with_suffix(".takeover").exists():
            raise ValueError("Archive 편집 잠금을 인계하는 중입니다.")
        held[key] = owner
        _held.paths = held
        yield
    finally:
        held.pop(key, None)
        if (status(root) or {}).get("token") == owner["token"]:
            path.unlink()


def release_orphan(root, observed_token, acknowledged=False):
    """Explicit handoff only. Keep the old owner record for diagnosis."""
    if not acknowledged or not observed_token:
        raise ValueError("기존 편집 앱이 종료되었는지 먼저 확인하세요.")
    path = lock_path(root)
    marker = path.with_suffix(".takeover")
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("다른 잠금 인계가 진행 중입니다.") from None
    os.close(fd)
    try:
        current = status(root)
        if not current or current.get("token") != observed_token:
            raise ValueError("편집 잠금이 바뀌었습니다. 상태를 다시 확인하세요.")
        if current.get("host") == socket.gethostname() and os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x1000, False, int(current.get("pid") or 0))
            if handle:
                try:
                    code = ctypes.c_ulong()
                    if kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)) and code.value == 259:
                        raise ValueError("이 PC의 편집 프로세스가 아직 실행 중입니다.")
                finally:
                    kernel.CloseHandle(ctypes.c_void_p(handle))
        saved = path.with_name(f"edit.lock.{uuid.uuid4().hex}.released")
        os.replace(path, saved)
        return {"released": True, "owner": current}
    finally:
        marker.unlink(missing_ok=True)


def archive_write(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        root = self._archive_config().get("archiveDir")
        if not root:
            return method(self, *args, **kwargs)
        with writing(root):
            return method(self, *args, **kwargs)
    return wrapped
