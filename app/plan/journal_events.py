"""Durable small Archive events between atomic operation.json checkpoints."""
import json
import os
from pathlib import Path


def load(directory):
    directory = Path(directory)
    data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
    checkpoint = data.get("journalSequence", 0)
    path = directory / "events.jsonl"
    if not path.exists():
        return data
    with path.open("rb") as stream:
        for line in stream:
            # A crash may tear the final append. No mutation follows an append
            # unless its complete line has been fsynced successfully.
            if not line.endswith(b"\n"):
                break
            event = json.loads(line)
            sequence = event["sequence"]
            if sequence <= checkpoint:
                continue
            if sequence != data.get("journalSequence", 0) + 1:
                raise ValueError("Archive 복구 기록의 순서가 손상되었습니다. 백업을 보존했습니다.")
            if event["section"] == "renames":
                renames = data.setdefault("renames", [])
                if event["key"] != len(renames):
                    raise ValueError("Archive 이름 변경 기록의 순서가 손상되었습니다.")
                renames.append(event["value"])
            else:
                data.setdefault(event["section"], {})[event["key"]] = event["value"]
            data["journalSequence"] = sequence
    return data


def append(directory, data, section, key, value):
    sequence = data.get("journalSequence", 0) + 1
    event = {"sequence": sequence, "section": section, "key": key, "value": value}
    with (Path(directory) / "events.jsonl").open("ab") as stream:
        stream.write((json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    data["journalSequence"] = sequence
