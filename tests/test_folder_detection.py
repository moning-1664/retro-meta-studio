import sqlite3

from adapters.es_de import EsDeAdapter
from app.folder_detection import inspect_folder
import storage


def test_esde_structure_suggests_esde(tmp_path):
    (tmp_path / "gamelists" / "sfc").mkdir(parents=True)
    (tmp_path / "downloaded_media").mkdir()
    result = inspect_folder(str(tmp_path))
    assert result["suggestedFrontend"] == "es-de"
    assert result["findings"][0]["systems"] == ["sfc"]


def test_esde_ignores_cleanup_and_archive_index_folder(tmp_path):
    (tmp_path / "gamelists" / "CLEANUP").mkdir(parents=True)
    (tmp_path / "gamelists" / "sfc").mkdir()
    (tmp_path / "downloaded_media").mkdir()
    (tmp_path / ".rms").mkdir()
    (tmp_path / ".rms" / "archive.db").write_bytes(b"archive")
    assert inspect_folder(str(tmp_path))["findings"][0]["systems"] == ["sfc"]
    detected = EsDeAdapter().detect(storage.for_path(str(tmp_path)), str(tmp_path))
    assert detected.systems == ("sfc",)


def test_shared_gamelists_structure_requires_selection(tmp_path):
    (tmp_path / "gamelists" / "sfc").mkdir(parents=True)
    result = inspect_folder(str(tmp_path))
    assert result["suggestedFrontend"] is None
    assert {item["frontend"] for item in result["findings"]} == {
        "es-de", "emulationstation"}


def test_pegasus_structure_suggests_pegasus(tmp_path):
    system = tmp_path / "sfc"
    system.mkdir()
    (system / "metadata.pegasus.txt").touch()
    result = inspect_folder(str(tmp_path))
    assert result["suggestedFrontend"] == "pegasus"


def test_emulationstation_rom_folder_suggests_emulationstation(tmp_path):
    system = tmp_path / "sfc"
    system.mkdir()
    (system / "gamelist.xml").touch()
    result = inspect_folder(str(tmp_path))
    assert result["suggestedFrontend"] == "emulationstation"


def test_launchbox_platforms_suggests_launchbox(tmp_path):
    platforms = tmp_path / "Data" / "Platforms"
    platforms.mkdir(parents=True)
    (platforms / "Nintendo.xml").touch()
    result = inspect_folder(str(tmp_path))
    assert result["suggestedFrontend"] == "launchbox"


def test_portable_archive_marker_is_recognized(tmp_path):
    archive_db = tmp_path / ".rms" / "archive.db"
    archive_db.parent.mkdir()
    with sqlite3.connect(archive_db) as db:
        db.execute("PRAGMA application_id=1380799297")  # RMSA
    assert inspect_folder(str(tmp_path))["archive"]


def test_empty_folder_has_no_archive_or_frontend(tmp_path):
    result = inspect_folder(str(tmp_path))
    assert not result["archive"]
    assert not result["legacyArchive"]
    assert result["suggestedFrontend"] is None
    assert result["findings"] == []
