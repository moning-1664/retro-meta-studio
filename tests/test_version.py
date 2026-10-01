"""Version bumps operate on isolated files, never the working application's version."""
import json
import pytest
import version


@pytest.mark.parametrize("initial,bump,expected", [
    ("0.1.0", None, "0.1.0"),
    ("0.1.9", "patch", "0.1.10"),
    ("0.1.19", "minor", "0.2.0"),
])
def test_version_source_and_ui_stay_in_sync(tmp_path, monkeypatch, initial, bump, expected):
    source = tmp_path / "version.py"
    original = f'__version__ = "{initial}"\n'
    source.write_text(original, encoding="utf-8")
    (tmp_path / "gui_web").mkdir()
    monkeypatch.setattr(version, "__file__", str(source))
    assert version.update_version(bump) == expected
    js = (tmp_path / "gui_web" / "version.js").read_text(encoding="utf-8")
    assert f"window.RMS_APP_VERSION = {json.dumps(expected)};" in js
    assert source.read_text(encoding="utf-8") == (original if bump is None else f'__version__ = "{expected}"\n')
    assert not list(tmp_path.rglob("*.tmp"))


def test_malformed_version_does_not_modify_ui(tmp_path, monkeypatch):
    source = tmp_path / "version.py"
    source.write_text('__version__ = "bad"\n', encoding="utf-8")
    monkeypatch.setattr(version, "__file__", str(source))
    with pytest.raises(ValueError):
        version.update_version("patch")
    assert not (tmp_path / "gui_web" / "version.js").exists()
