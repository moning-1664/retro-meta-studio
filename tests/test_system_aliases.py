"""Hardware aliases share lookup rules; metadata families are not hardware aliases."""
import itertools
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.model.constants import (SYSTEM_ALIAS_GROUPS, canonical_system,
    metadata_compatible, normalize_system, same_system)
from app.launch import retroarch
from app.scrape.providers.screenscraper import SYSTEM_IDS, _system_id


@pytest.mark.parametrize("left,right", [pair for group in SYSTEM_ALIAS_GROUPS
    for pair in itertools.combinations(group, 2)])
def test_alias_pairs_share_matching_and_provider_ids(left, right):
    assert same_system(left, right)
    assert metadata_compatible(left, right)
    assert metadata_compatible(right, left)
    assert canonical_system(left) == canonical_system(right)
    if left in SYSTEM_IDS:
        assert _system_id(left) == _system_id(right)


@pytest.mark.parametrize("left,right", [("megadrive", "segacd"), ("sega32x", "segacd"),
    ("neogeo", "neogeocd"), ("n64", "n64dd"), ("ngp", "ngpc"),
    ("pcengine", "pcfx"), ("amiga", "amigacd32"), ("windows", "ports"),
    ("naomi", "fbneo"), ("naomi", "atomiswave"), ("nes", "fds")])
def test_distinct_hardware_is_not_an_alias(left, right):
    assert not same_system(left, right)
    assert not metadata_compatible(left, right)


@pytest.mark.parametrize("left,right", [("msx", "msx2"), ("mame", "fbneo"),
    ("pc88", "pc98"), ("pcengine", "pcenginecd")])
def test_metadata_family_does_not_share_core_settings(left, right):
    assert metadata_compatible(left, right)
    assert not same_system(left, right)
    assert retroarch.configured_core({left: "custom.dll"}, right) is None


def test_case_punctuation_unknown_names_and_override():
    assert same_system(" Mega-CD JP ", "segacd")
    assert _system_id("Mega-CD JP") == "20"
    assert not same_system("", "")
    assert not metadata_compatible("", "")
    assert not same_system("custom-a", "custom_b")
    assert normalize_system("es-de", "megacd", {"megacd": "custom"}) == "custom"
    assert normalize_system("es-de", "My Custom Folder") == "My Custom Folder"
    assert normalize_system("es-de", "snes") == "snes"
    assert normalize_system("es-de", "megacdjp") == "megacdjp"


def test_core_recommendations_and_legacy_settings_use_aliases():
    available = ["genesis_plus_gx_libretro.dll"]
    assert retroarch.default_cores_for(["megacdjp", "segacd"], available, {}) == {
        "megacdjp": available[0]}
    assert retroarch.default_cores_for(["segacd"], available, {"megacd": "custom.dll"}) == {}
    assert retroarch.configured_core({"megacd": "custom.dll"}, "megacdjp") == "custom.dll"
    assert retroarch.is_verified("gamecube") == retroarch.is_verified("gc")


@pytest.mark.parametrize("source_system,target_system", [
    ("megacd", "segacd"), ("snesna", "sfc"), ("tg-cd", "pcenginecd")])
def test_collection_paste_maps_alias_without_changing_paths(tmp_path, source_system, target_system):
    from bridge.api import Api
    from tests.fixtures import build_custom_esde_tree, scan, wait_job
    source = build_custom_esde_tree(tmp_path / "source", source_system,
        [{"filename": "Game.chd", "title": "Source title"}])
    target = build_custom_esde_tree(tmp_path / "target", target_system,
        [{"filename": "Game.chd", "title": "Old title"}])
    api = Api(registry_path=tmp_path / "registry.db", cache_dir=tmp_path / "cache")
    try:
        src = api.create_collection("Source", "es-de", str(source))["data"]["id"]
        dst = api.create_collection("Target", "es-de", str(target))["data"]["id"]
        scan(api, src)
        scan(api, dst)
        row = api.list_rows(src)["data"]["rows"][0]
        assert api.copy_selection(src, [row["romUid"]])["ok"]
        preview = api.paste(dst, "overwrite", immediate=True)
        assert preview["ok"], preview
        decisions = {item["key"]: "overwrite" for item in preview["data"].get("collisions", [])}
        started = api.paste_execute(preview["data"]["operationId"], decisions)
        assert started["ok"], started
        result = wait_job(api, started["data"]["jobId"])
        assert not result.get("error"), result
        cache = api.workspace.open(dst)
        assert cache.get_row_by_filename(target_system, "Game.chd")["fields"]["name"] == "Source title"
        assert not (target / source_system).exists()
    finally:
        api.close()


def test_collection_candidates_accept_aliases_across_frontends():
    from app.collection_import import candidates
    row = {"system": "megacd", "filename": "Game.chd", "title": "Game",
           "title_norm": "game", "filename_norm": "game", "size": 1000,
           "rom_uid": 1, "fields": {}, "media_types": []}
    source = SimpleNamespace(frontend="pegasus", systems=[SimpleNamespace(system="megacd")])
    target = SimpleNamespace(frontend="es-de")
    cache = Mock()
    cache.indexed_import_candidates.return_value = [row]
    found = candidates(target, {**row, "system": "segacd"}, source, cache)
    assert found[0]["romUid"] == 1
    assert cache.indexed_import_candidates.call_args.args[0] == ["megacd"]


def test_core_setting_changes_and_clear_apply_to_aliases_and_legacy_keys(tmp_path):
    from bridge.api import Api
    cores = tmp_path / "cores"
    cores.mkdir()
    (cores / "custom.dll").write_bytes(b"test core")
    api = Api(registry_path=tmp_path / "registry.db", cache_dir=tmp_path / "cache")
    try:
        api.set_retroarch_paths("", str(cores))
        api.save_app_settings({"emulator": {
            "systemCores": {"megacd": "old.dll", "msx": "msx.dll"},
            "gameCores": {"megacd/Game.chd": "old.dll", "msx/Game.chd": "msx.dll"}}})
        assert api._system_core(api._emulator(), "pegasus", "segacd") == "old.dll"
        assert api._game_core(api._emulator(), "megacdjp", "Game.chd") == "old.dll"
        assert api.set_system_core("segacd", "custom.dll")["ok"]
        settings = api.retroarch_settings()["data"]
        assert "megacd" not in settings["systemCores"]
        assert settings["resolvedSystemCores"]["megacdjp"] == "custom.dll"
        assert api.set_game_core("segacd", "Game.chd", "custom.dll")["ok"]
        assert api._game_core(api._emulator(), "megacd", "Game.chd") == "custom.dll"
        assert api.set_system_core("megacdjp", None)["ok"]
        assert api.set_game_core("megacdjp", "Game.chd", None)["ok"]
        assert api._system_core(api._emulator(), "es-de", "segacd") is None
        assert api._game_core(api._emulator(), "megacd", "Game.chd") is None
        assert api._emulator()["systemCores"] == {"msx": "msx.dll"}
        assert api._emulator()["gameCores"] == {"msx/Game.chd": "msx.dll"}
    finally:
        api.close()


def test_archive_paste_keeps_legacy_alias_identity(tmp_path):
    from app.archive import paste
    from unittest.mock import patch
    identity = {"rom_identity_id": "legacy", "system": "megacd", "filename": "Game.chd"}
    store = Mock()
    store.find_rom_identity.side_effect = lambda system, filename: identity if system == "megacd" else None
    state = {"signature": "same", "rid": "legacy", "row": {
        **identity, "fields": {}, "frontend_raw": {}, "media": [], "present": True}}
    with patch.object(paste, "state_of", return_value=state):
        result = paste.prepare(store, {"frontend": "es-de"}, [{"system": "segacd",
            "filename": "Game.chd", "fields": {"name": "New title"}, "media": []}], "overwrite")
    assert not result["skipped"]
    assert result["prepared"][0]["system"] == "megacd"
    assert result["snapshots"]["megacd|Game.chd"] == "same"


def test_alias_systems_do_not_merge_different_filenames():
    from app.plan.transfer import TargetIndex
    cache = Mock()
    cache.all_entries.return_value = [{"system": "segacd", "filename": "Game (Japan).chd", "rom_uid": 1}]
    index = TargetIndex(cache, {"segacd"})
    assert index.find({"system": "segacd", "filename": "Game (USA).chd"}, exact_only=True) == (None, None)
    cache.get_row.assert_not_called()
