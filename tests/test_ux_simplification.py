from app.plan.transfer import fields_conflict
from app.folder_detection import inspect_folder
from app.match import engine
from bridge.api import Api
from unittest.mock import Mock
import threading
import pytest


@pytest.mark.parametrize("left,right", [("msx", "msx2"), ("msx1", "MSX Turbo R"),
    ("msx2+", "msx2plus"), ("PC-8801", "pc98"), ("mame2003+", "fbneo"),
    ("fba", "cps3"), ("pce", "pcenginecd"), ("supergrafx", "pcecd")])
def test_metadata_families(left, right):
    from app.model.constants import metadata_compatible
    assert metadata_compatible(left, right)
    assert metadata_compatible(right, left)


@pytest.mark.parametrize("left,right", [("pcengine", "pcfx"), ("naomi", "fbneo"),
    ("msx", "pc98"), ("nes", "snes")])
def test_unrelated_systems_remain_separate(left, right):
    from app.model.constants import metadata_compatible
    assert not metadata_compatible(left, right)


def test_archive_family_paste_never_copies_rom():
    from app.archive import paste
    from unittest.mock import patch
    identity = {"system": "msx2", "filename": "126 games.rom", "filename_norm": "126 games"}
    store = Mock()
    store.get_identity.return_value = identity
    source = {"system": "msx", "filename": "126 games.rom", "fields": {"name": "126 Games"},
              "rom": {"path": "original.rom"}, "media": []}
    state = {"signature": "unchanged", "rid": "target", "row": {**identity,
             "fields": {}, "frontend_raw": {}, "media": [], "present": True}}
    with patch.object(paste, "state_of", return_value=state):
        result = paste.prepare(store, {"frontend": "es-de"}, [source], "overwrite", target_id="target")
    assert result["prepared"][0].get("rom") is None
    assert result["prepared"][0]["system"] == "msx2"
    assert result["prepared"][0]["filename"] == "126 games.rom"


def test_archive_family_bulk_requires_existing_filename():
    from app.archive import paste
    store = Mock()
    store.find_rom_identity.return_value = None
    result = paste.prepare(store, {"frontend": "es-de"}, [{"system": "msx", "filename": "missing.rom",
        "fields": {}, "rom": {"path": "source.rom"}}], "overwrite", target_system="msx2")
    assert not result["prepared"]
    assert len(result["skipped"]) == 1


def test_collection_family_paste_preserves_target_rom(tmp_path):
    from tests.fixtures import build_custom_esde_tree, scan, wait_job
    source = build_custom_esde_tree(tmp_path / "source", "msx", [{"filename": "126 games.rom", "title": "New metadata"}])
    target = build_custom_esde_tree(tmp_path / "target", "msx2", [{"filename": "126 games.rom", "title": "Old metadata"}])
    api = Api(registry_path=tmp_path / "registry.db", cache_dir=tmp_path / "cache")
    try:
        src = api.create_collection("source", "es-de", str(source))["data"]["id"]
        dst = api.create_collection("target", "es-de", str(target))["data"]["id"]
        scan(api, src)
        scan(api, dst)
        row = api.list_rows(src)["data"]["rows"][0]
        rom = target / "msx2" / "126 games.rom"
        rom.write_bytes(b"target ROM must survive")
        assert api.copy_selection(src, [row["romUid"]])["ok"]
        preview = api.paste(dst, "overwrite", {"msx": "msx2"}, immediate=True)
        assert preview["ok"], preview
        decisions = {item["key"]: "overwrite" for item in preview["data"].get("collisions", [])}
        started = api.paste_execute(preview["data"]["operationId"], decisions)
        assert started["ok"], started
        result = wait_job(api, started["data"]["jobId"])
        assert not result.get("error"), result
        assert rom.read_bytes() == b"target ROM must survive"
        assert api.workspace.open(dst).get_row_by_filename("msx2", "126 games.rom")["fields"]["name"] == "New metadata"
    finally:
        api.close()


def test_empty_metadata_is_not_a_conflict():
    assert not fields_conflict({"name": "", "desc": None}, {"name": "Game", "desc": "Text"})
    assert not fields_conflict({"name": "Game"}, {"name": "Game", "desc": "Text"})
    assert fields_conflict({"name": "Old"}, {"name": "New"})
    assert not fields_conflict({"name": "Old"}, {"name": "New"}, "patch")
    assert fields_conflict({"desc": "Existing"}, {}, "replace")


def test_nested_detection_and_existing_rom_setting(tmp_path):
    root = tmp_path / "Frontend" / "ES-DE"
    (root / "gamelists").mkdir(parents=True)
    (root / "downloaded_media").mkdir()
    roms = root / "ROMs"
    roms.mkdir()
    (root / "settings").mkdir()
    (root / "settings" / "es_settings.xml").write_text(
        '<config><string name="ROMDirectory" value="ROMs" /></config>')
    result = inspect_folder(str(tmp_path))
    assert result["path"] == str(root)
    assert result["suggestedRomDir"] == str(roms.resolve())


def test_ambiguous_nested_detection_does_not_choose(tmp_path):
    for name in ("A", "B"):
        (tmp_path / name / "gamelists").mkdir(parents=True)
        (tmp_path / name / "downloaded_media").mkdir()
    result = inspect_folder(str(tmp_path))
    assert result["suggestedFrontend"] is None
    assert len(result["nestedCandidates"]) == 2


def test_shared_developer_and_date_do_not_match_unrelated_games():
    left = {"title": "1942", "title_norm": "1942", "filename": "1942.zip", "filename_norm": "1942",
            "developer": "Capcom", "releasedate": "1984", "system": "arcade"}
    right = {**left, "title": "SonSon", "title_norm": "sonson", "filename": "sonson.zip", "filename_norm": "sonson"}
    assert engine.classify_pair(left, right)[0] is None


def test_duplicate_scrape_apply_reuses_running_job():
    api = Api.__new__(Api)
    api._scrape_apply_lock = threading.Lock()
    api._scrape_apply_jobs = {}
    api.jobs = Mock()
    api.jobs.get.return_value = {"done": False}
    api._start_apply_scrape_session = Mock(return_value={"ok": True, "data": {"jobId": "job"}})
    assert api.start_apply_scrape_session("session")["data"]["jobId"] == "job"
    assert api.start_apply_scrape_session("session")["data"]["jobId"] == "job"
    api._start_apply_scrape_session.assert_called_once()


def test_thumbnail_preserves_transparent_cover(tmp_path):
    from PIL import Image
    import io
    import base64
    path = tmp_path / "cover.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 0)).save(path)
    encoded = Api._encode_image_uncached(str(path), 10)
    image = Image.open(io.BytesIO(base64.b64decode(encoded.split(",", 1)[1])))
    assert image.convert("RGBA").getpixel((0, 0))[3] == 0


def test_native_close_does_not_block_ui_on_javascript():
    from types import SimpleNamespace
    from webview.event import Event
    from bridge.windows import WindowManager
    from unittest.mock import patch
    manager = WindowManager.__new__(WindowManager)
    manager._lock = threading.Lock()
    manager._bridges = {}
    window = SimpleNamespace()
    window.events = SimpleNamespace(closed=Event(window), closing=Event(window, should_lock=True))
    window.evaluate_js = Mock(return_value=False)
    window.destroy = Mock()
    bridge = SimpleNamespace(_window_id="main")
    manager._attach(bridge, window)
    with patch("bridge.windows.threading.Thread") as worker:
        assert window.events.closing.set() is True
        window.evaluate_js.assert_not_called()
        worker.assert_called_once()
    window._rms_close_confirmed = True
    assert window.events.closing.set() is False
