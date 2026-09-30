import json
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.archive.edit_lock import lock_path, status, writing


def test_lock_blocks_another_writer_and_allows_nested_projection():
    with TemporaryDirectory() as root:
        failures = []
        with writing(root):
            owner = status(root)
            with writing(root):
                assert status(root) == owner
            def contender():
                try:
                    with writing(root):
                        failures.append("unexpected success")
                except ValueError as error:
                    failures.append(str(error))
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(timeout=3)
            assert not thread.is_alive()
            assert len(failures) == 1
            assert "Archive" in failures[0]
        assert status(root) is None


def test_exception_releases_lock_but_orphan_is_never_silently_stolen():
    with TemporaryDirectory() as root:
        with pytest.raises(RuntimeError):
            with writing(root):
                raise RuntimeError("injected failure")
        assert status(root) is None
        path = lock_path(root)
        owner = {"token": "old-owner", "host": "PC-A", "pid": 123, "startedAt": 0}
        path.write_text(json.dumps(owner), encoding="utf-8")
        with pytest.raises(ValueError, match="PC-A"):
            with writing(root):
                pass
        assert status(root) == owner


def test_explicit_orphan_release_checks_observed_owner_and_preserves_record():
    from app.archive.edit_lock import release_orphan
    with TemporaryDirectory() as root:
        path = lock_path(root)
        path.parent.mkdir(parents=True)
        owner = {"token": "stopped", "host": "remote-PC", "pid": 123}
        path.write_text(json.dumps(owner), encoding="utf-8")
        with pytest.raises(ValueError):
            release_orphan(root, "stopped", False)
        with pytest.raises(ValueError):
            release_orphan(root, "different", True)
        assert status(root) == owner
        assert release_orphan(root, "stopped", True)["released"]
        assert status(root) is None
        assert len(list(path.parent.glob("*.released"))) == 1
        with writing(root):
            assert status(root)["token"] != "stopped"
