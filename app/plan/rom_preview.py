"""Lightweight file facts for ROM replacement previews; never read file contents."""

import os

from storage.local import LocalStorageProvider


def comparison(rom, destination, provider=None):
    if not rom or not rom.get("path") or not destination:
        return None
    if os.path.normcase(os.path.abspath(rom["path"])) == os.path.normcase(os.path.abspath(destination)):
        return None
    provider = provider or LocalStorageProvider()

    def facts(path):
        try:
            stat = provider.stat(path)
            if stat is None or stat.is_dir:
                return None
            return {"size": stat.size,
                    "modifiedAt": stat.mtime_ns / 1_000_000 if stat.mtime_ns else None}
        except (OSError, ValueError, NotImplementedError):
            return None

    existing = facts(destination)
    if existing is None:
        return None
    incoming = facts(rom["path"])
    if incoming is None:
        incoming = {"size": rom.get("size"), "modifiedAt": None}
    return {"existing": existing, "incoming": incoming}
