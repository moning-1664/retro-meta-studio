"""Conservative process ownership checks for recovery journals."""
import ctypes
import os
import time


def process_stamp(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return str(pid)
        except ProcessLookupError:
            return None
        except PermissionError:
            return "unknown"
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None if ctypes.get_last_error() == 87 else "unknown"
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)):
            return "unknown"
        return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def owner():
    return {"pid": os.getpid(), "processStamp": process_stamp(os.getpid()), "heartbeat": time.time()}


def status(data):
    saved = data.get("owner")
    if not saved:
        return "dead"
    current = process_stamp(int(saved["pid"]))
    if current == "unknown":
        return "unknown"
    return "alive" if current is not None and current == saved.get("processStamp") else "dead"


def alive(data):
    return status(data) != "dead"
