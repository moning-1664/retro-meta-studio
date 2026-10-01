"""Opt-in retention. Recovery and the newest Undo/Redo remain protected."""
import logging
import json
from pathlib import Path
from app.plan import history

log = logging.getLogger(__name__)


def policy(raw):
    raw = raw if isinstance(raw, dict) else {}
    result = {"enabled": raw.get("enabled") is True}
    for key, default, upper in (("maxCount", 20, 10000), ("maxSizeGB", 10, 100000)):
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= upper:
            raise ValueError("백업 한도는 0 이상의 정수여야 합니다. 0은 제한 없음입니다.")
        result[key] = value
    if result["enabled"] and not (result["maxCount"] or result["maxSizeGB"]):
        raise ValueError("백업 자동 정리를 켜려면 개수 또는 용량 한도를 지정하세요.")
    return result


def safe_sidecars(data):
    for destination, item in data.get("files", {}).items():
        for key in ("backup", "redo"):
            raw = item.get(key)
            if not raw:
                continue
            path = Path(raw)
            if not path.exists():
                continue
            if path.is_symlink() or path.resolve() != path.absolute():
                return False
            expected = (item.get("before") if key == "backup" else item.get("committedState"))
            if expected is None:
                expected = data.get("preFiles" if key == "backup" else "postFiles", {}).get(destination)
            if expected is None:
                return False
            if expected is not None:
                size, mtime = (expected[0], expected[1]) if isinstance(expected, list) else (expected["size"], expected["mtimeNs"])
                stat = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (size, mtime):
                    return False
    return True


def prune(api, scope, raw):
    limits = policy(raw)
    if not limits["enabled"]:
        return {"discarded": 0, "enabled": False}
    rows = history.listing(api, scope)
    if any(row["status"] in {"running", "restoring", "redoing", "recovery_failed"} for row in rows):
        return {"discarded": 0, "blocked": True}
    newest = set()
    for kind in ("collection", "archive"):
        latest = next((row["id"] for row in rows if row["kind"] == kind and row["status"] == "committed"), None)
        if latest:
            newest.add(latest)
    total, count, candidates = sum(row["bytes"] for row in rows), len(rows), []
    for row in rows:
        if (row["id"] not in newest and row["canDiscard"] and not row.get("redoReady")
                and not row.get("relatedCollections")):
            candidates.append(row)
    removed, errors = 0, []
    permitted = {row["id"]: row for row in rows}
    maximum = limits["maxSizeGB"] * 1024 ** 3
    for row in reversed(candidates):
        if not ((limits["maxCount"] and count > limits["maxCount"]) or (maximum and total > maximum)):
            break
        try:
            root = api._archive_journal.root if row["kind"] == "archive" else api._paste_journal.root
            directory = root / row["id"]
            data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
            if (data.get("status") not in {"committed", "undone", "recovered"}
                    or data.get("redoReady") or data.get("relatedCollections") or not safe_sidecars(data)):
                continue
            history.discard(api, scope, [row["id"]], _permitted=permitted)
            removed += 1
            count -= 1
            total -= row["bytes"]
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
            log.warning("Backup retention kept operation=%s: %s", row["id"], exc)
    exceeded = bool((limits["maxCount"] and count > limits["maxCount"]) or (maximum and total > maximum))
    return {"discarded": removed, "bytesRemaining": total, "limitExceeded": exceeded, "errors": errors}
