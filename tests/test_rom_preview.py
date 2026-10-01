import os

from app.plan.rom_preview import comparison


def test_rom_replacement_facts(tmp_path):
    source, target = tmp_path / "source.zip", tmp_path / "target.zip"
    source.write_bytes(b"new")
    target.write_bytes(b"old content")
    os.utime(source, ns=(1_700_000_000_000_000_000,) * 2)
    result = comparison({"path": str(source)}, target)
    assert result["existing"]["size"] == 11
    assert result["incoming"] == {"size": 3, "modifiedAt": 1_700_000_000_000}


def test_no_rom_or_no_existing_file_has_no_comparison(tmp_path):
    assert comparison(None, tmp_path / "missing") is None
    assert comparison({"path": str(tmp_path / "source")}, tmp_path / "missing") is None


def test_same_file_has_no_replacement(tmp_path):
    source = tmp_path / "game.zip"
    source.write_bytes(b"rom")
    assert comparison({"path": str(source)}, source) is None


def test_unreadable_source_keeps_known_size(tmp_path):
    target = tmp_path / "game.zip"
    target.write_bytes(b"old")
    result = comparison({"path": str(tmp_path / "missing"), "size": 42}, target)
    assert result["incoming"] == {"size": 42, "modifiedAt": None}
