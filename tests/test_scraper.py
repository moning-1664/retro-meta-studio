"""Scraper provider, review session, secrets, provenance and apply boundaries."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
import unittest
import zlib
import zipfile
from pathlib import Path
from unittest import mock

from app.scrape import ScrapeCandidate, ScrapeIdentity, ScrapeMedia, ScrapeService
from app.scrape.service import _query_fallbacks
from app.scrape import secrets as scrape_secrets
from app.scrape.providers.screenscraper import (
    ScreenScraperClient,
    ScreenScraperConfig,
    ScreenScraperError,
    hashes_of_file,
    lookup_hashes,
    _title_similarity,
)
from app.store.registry import RegistryStore
from app.plan import builder
from bridge.api import Api
from tests.fixtures import build_esde_tree, wait_idle


class FakeResponse:
    def __init__(self, payload=None, status=200, text=""):
        self.payload = payload
        self.status_code = status
        self.text = text

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def config():
    return ScreenScraperConfig("developer", "secret", "RetroMetaStudio", "user", "password")


def candidate(media=()):
    return ScrapeCandidate(
        candidate_id="screenscraper:42", provider="screenscraper", remote_game_id="42",
        title="게임", system="PlayStation 2", fields={"name": "게임", "genre": "RPG"},
        media=tuple(media), evidence=("ROM 해시 일치",), confidence=100,
        confidence_reason="ROM 해시 일치", source_url="https://www.screenscraper.fr/gameinfos.php?gameid=42")


class HashAndProviderTests(unittest.TestCase):
    def test_confirmed_game_lookup_rejects_mismatched_game_or_system(self):
        valid = {"response": {"jeu": {"id": "42", "nom": "Game", "systeme": {"id": "58"}}}}
        http = FakeHttp([FakeResponse(valid)])
        found = ScreenScraperClient(config(), http).confirmed_game("42", "ps2")
        self.assertEqual(found[0].remote_game_id, "42")
        self.assertEqual(http.calls[0][1]["params"]["gameid"], "42")
        self.assertEqual(http.calls[0][1]["params"]["systemeid"], "58")
        wrong = FakeHttp([FakeResponse({"response": {"jeu": {
            "id": "43", "nom": "Wrong", "systeme": {"id": "58"}}}})])
        self.assertEqual(ScreenScraperClient(config(), wrong).confirmed_game("42", "ps2"), [])
        wrong_system = FakeHttp([FakeResponse({"response": {"jeu": {
            "id": "42", "nom": "Wrong", "systeme": {"id": "2"}}}})])
        self.assertEqual(ScreenScraperClient(config(), wrong_system).confirmed_game("42", "ps2"), [])

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_scraper_provider_"))

    def test_hashes_are_calculated_in_one_public_result(self):
        data = b"korean-patched-rom\x00\x01"
        path = self.dir / "game.rom"
        path.write_bytes(data)
        result = hashes_of_file(path, chunk_size=3)
        self.assertEqual(result["size"], len(data))
        self.assertEqual(result["crc32"], f"{zlib.crc32(data) & 0xffffffff:08X}")
        self.assertEqual(result["md5"], hashlib.md5(data).hexdigest())  # noqa: S324
        self.assertEqual(result["sha1"], hashlib.sha1(data).hexdigest())  # noqa: S324

    def test_identify_sends_all_observed_hashes_without_overwriting_them(self):
        item = ScrapeService.item("1", "msx", "Boogie Woogie Jungle [J].zip",
                                  {"name": "부기 우기 정글"})
        self.assertEqual(item["query"], "Boogie Woogie Jungle")

        path = self.dir / "게임 (K).rom"
        path.write_bytes(b"patched")
        http = FakeHttp([FakeResponse({"response": {"jeu": {
            "id": "42", "nom": "Original Game", "systeme_nom": "PS2",
            "synopsis": [{"langue": "en", "text": "Description"}],
            "medias": [{"type": "box-2d", "url": "https://media.screenscraper.fr/cover.png"}],
        }}})])
        result = ScreenScraperClient(config(), http).identify(
            ScrapeIdentity("ps2", path.name, str(path)))
        self.assertEqual(len(result), 1)
        sent = http.calls[0][1]["params"]
        expected = hashes_of_file(path)
        self.assertEqual((sent["crc"], sent["md5"], sent["sha1"]),
                         (expected["crc32"], expected["md5"], expected["sha1"]))
        self.assertEqual(result[0].media[0].media_type, "covers")

    def test_arcade_romset_short_name_uses_filename_lookup_without_hashing_zip(self):
        http = FakeHttp([FakeResponse({"response": {"jeu": {
            "id": "90", "nom": "World Soccer '90", "systeme": {"id": "75"},
        }}})])
        config_without_hash = ScreenScraperConfig(
            "developer", "secret", "RetroMetaStudio", "user", "password", use_hashes=False)
        found = ScreenScraperClient(config_without_hash, http).identify(
            ScrapeIdentity("fbneo", "ws90.zip", None))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].evidence, ("Arcade ROM-set 파일명으로 조회",))
        self.assertEqual(found[0].confidence, 40)
        self.assertIn("직접 확인", found[0].confidence_reason)
        params = http.calls[0][1]["params"]
        self.assertEqual((params["romnom"], params["systemeid"]), ("ws90.zip", "75"))
        self.assertNotIn("sha1", params)

    def test_arcade_romset_retries_stem_after_filename_not_found(self):
        http = FakeHttp([FakeResponse(status=404), FakeResponse({"response": {"jeu": {
            "id": "90", "nom": "World Soccer '90", "systeme": {"id": "75"},
        }}})])
        found = ScreenScraperClient(config(), http).identify(
            ScrapeIdentity("fbern", "ws90.zip", None))
        self.assertEqual(len(found), 1)
        self.assertEqual([call[1]["params"]["romnom"] for call in http.calls],
                         ["ws90.zip", "ws90"])
        self.assertTrue(all(call[1]["params"]["systemeid"] == "75" for call in http.calls))

    def test_missing_platform_ids_have_documented_mapping(self):
        from app.scrape.providers.screenscraper import _system_id
        self.assertEqual([_system_id(name) for name in
                         ("psvita", "vita", "wii", "wiiu", "switch", "fbern",
                          "ngpc", "pc98", "mastersystem", "windows")],
                         ["62", "62", "16", "18", "225", "75", "82", "208", "2", "138"])

    def test_vita_alias_is_searchable_but_not_duplicated_in_system_choices(self):
        directory = Path(tempfile.mkdtemp(prefix="rms_scraper_systems_"))
        api = Api(registry_path=directory / "registry.db", cache_dir=directory / "cache")
        try:
            result = api.scraper_systems()
            self.assertTrue(result["ok"], result.get("error"))
            names = [row["name"] for row in result["data"]]
            self.assertIn("psvita", names)
            self.assertNotIn("vita", names)
            self.assertEqual([row for row in result["data"] if row["id"] == 75],
                             [{"name": "arcade", "id": 75}])
        finally:
            api.close()

    def test_identify_accepts_lookup_alias_but_keeps_observed_identity_separate(self):
        path = self.dir / "patched.rom"
        path.write_bytes(b"patched")
        http = FakeHttp([FakeResponse({"response": {"jeu": {"id": 7, "nom": "원작"}}})])
        identity = ScrapeIdentity("ps2", path.name, str(path), lookup_alias={
            "crc32": "DEADBEEF", "md5": "alias-md5", "sha1": "alias-sha1", "size": 999,
            "systemId": "58",
        })
        found = ScreenScraperClient(config(), http).identify(identity)
        sent = http.calls[0][1]["params"]
        self.assertEqual((sent["crc"], sent["md5"], sent["sha1"], sent["romtaille"], sent["systemeid"]),
                         ("DEADBEEF", "alias-md5", "alias-sha1", 999, "58"))
        self.assertEqual(found[0].evidence, ("원본 별칭으로 조회",))
        self.assertEqual(found[0].confidence, 65)
        self.assertIn("일치 확인 필요", found[0].confidence_reason)
        self.assertEqual(hashes_of_file(path)["crc32"], f"{zlib.crc32(b'patched') & 0xffffffff:08X}")

    def test_single_member_zip_uses_inner_crc_without_reading_payload(self):
        path = self.dir / "Game (USA).zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Game.rom", b"rom-data")
        with mock.patch("app.scrape.providers.screenscraper.hashes_of_file",
                        side_effect=AssertionError("ZIP bytes must not be hashed")):
            found = lookup_hashes(str(path))
        self.assertEqual(found, {"size": path.stat().st_size,
                                 "crc32": f"{zlib.crc32(b'rom-data') & 0xffffffff:08X}"})
        http = FakeHttp([FakeResponse({"response": {"jeu": {"id": 1, "nom": "Game"}}})])
        ScreenScraperClient(config(), http).identify(ScrapeIdentity("msx", path.name, str(path)))
        params = http.calls[0][1]["params"]
        self.assertEqual((params["crc"], params["romtaille"]),
                         (found["crc32"], path.stat().st_size))
        self.assertNotIn("md5", params)

    def test_multi_member_arcade_zip_uses_romset_name_only(self):
        path = self.dir / "ws90.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("one.bin", b"one")
            archive.writestr("two.bin", b"two")
        http = FakeHttp([FakeResponse({"response": {"jeu": {"id": 90, "nom": "World Soccer"}}})])
        ScreenScraperClient(config(), http).identify(ScrapeIdentity("fbneo", path.name, str(path)))
        params = http.calls[0][1]["params"]
        self.assertEqual(params["romnom"], "ws90.zip")
        self.assertNotIn("crc", params)
        self.assertNotIn("md5", params)

    def test_large_uncompressed_rom_is_not_read_for_hash_lookup(self):
        path = self.dir / "large.iso"
        with path.open("wb") as stream:
            stream.truncate(65 * 1024 * 1024)
        with mock.patch("app.scrape.providers.screenscraper.hashes_of_file",
                        side_effect=AssertionError("large ROM must not be hashed")):
            self.assertEqual(lookup_hashes(str(path)), {})

    def test_query_removes_dump_tags_but_keeps_meaningful_parentheses(self):
        self.assertEqual(ScrapeIdentity("sfc", "Legend_of_Zelda,_The (USA) (Rev 1) [!].zip")
                         .default_query, "The Legend of Zelda")
        self.assertEqual(ScrapeIdentity("sfc", "Game (Special Edition) (En,Fr,De).zip")
                         .default_query, "Game (Special Edition)")

    def test_patch_markers_skip_hash_lookup_and_leave_clean_search_title(self):
        for filename, expected in (("Game [T-Kor].zip", "Game"),
                                   ("Game (한글패치).zip", "Game"),
                                   ("Queens Blade - Spiral Chaos T-En [U].chd",
                                    "Queens Blade - Spiral Chaos"),
                                   ("Game (Hack).zip", "Game"),
                                   ("Game 번역판.zip", "Game")):
            with self.subTest(filename=filename):
                identity = ScrapeIdentity("sfc", filename, str(self.dir / filename))
                self.assertTrue(identity.is_modified_rom)
                self.assertEqual(identity.default_query, expected)
                provider = ScreenScraperClient(config(), FakeHttp([]))
                self.assertEqual(provider.identify(identity), [])
                self.assertEqual(provider.http.calls, [])
        original = ScrapeIdentity("sfc", "Game (Special Edition).zip")
        self.assertFalse(original.is_modified_rom)
        self.assertEqual(original.default_query, "Game (Special Edition)")

    def test_account_counters_tolerate_formatted_and_invalid_values(self):
        http = FakeHttp([FakeResponse({"response": {"ssuser": {
            "id": "u", "requeststoday": "1 234", "maxrequestsperday": "bad",
            "requestspermin": "7", "maxrequestspermin": None, "maxthreads": "2",
        }}})])
        status = ScreenScraperClient(config(), http).account_status()
        self.assertEqual(status["requestsToday"], 1234)
        self.assertEqual(status["requestsLimit"], 0)
        self.assertEqual(status["maxThreads"], 2)

    def test_account_limit_parses_thousands_separators(self):
        for value in ("20 000", "20.000", "20,000", "20\u202f000"):
            with self.subTest(value=value):
                http = FakeHttp([FakeResponse({"response": {"ssuser": {
                    "requeststoday": "6", "maxrequestsperday": value,
                }}})])
                status = ScreenScraperClient(config(), http).account_status()
                self.assertEqual(status["requestsLimit"], 20000)

    def test_search_maps_system_name_to_numeric_id(self):
        payload = {"response": {"jeux": []}}
        http = FakeHttp([FakeResponse(payload), FakeResponse(payload)])
        provider = ScreenScraperClient(config(), http)
        provider.search("Game", "msx")
        provider.search("Game", "58")
        self.assertEqual(http.calls[0][1]["params"]["systemeid"], "113")
        self.assertEqual(http.calls[1][1]["params"]["systemeid"], "58")

    def test_sega_cd_folder_has_a_known_system_id(self):
        http = FakeHttp([FakeResponse({"response": {"jeux": []}})])
        ScreenScraperClient(config(), http).search("Sonic CD", "segacd")
        self.assertEqual(http.calls[0][1]["params"]["systemeid"], "20")

    def test_all_systems_skips_jeu_infos_and_searches_without_system_id(self):
        http = FakeHttp([FakeResponse({"response": {"jeux": [
            {"id": "1", "nom": "Sonic", "systeme": {"id": "1"}},
        ]}})])
        provider = ScreenScraperClient(config(), http)
        self.assertEqual(provider.identify(ScrapeIdentity("", "Sonic.zip")), [])
        self.assertEqual(http.calls, [])
        self.assertEqual(len(provider.search("Sonic", "")), 1)
        self.assertTrue(http.calls[0][0].endswith("jeuRecherche.php"))
        self.assertNotIn("systemeid", http.calls[0][1]["params"])

    def test_arcade_board_child_of_75_is_accepted_but_other_parent_is_not(self):
        http = FakeHttp([FakeResponse({"response": {"jeu": {
            "id": "39874", "nom": "1942", "systeme": {"id": "151", "parentid": "75"},
        }}}), FakeResponse({"response": {"jeux": [
            {"id": "39874", "nom": "1942", "systeme": {"id": "151", "parentid": "75"}},
            {"id": "123448", "nom": "1942 PlayChoice", "systeme": {"id": "184", "parentid": "3"}},
        ]}})])
        provider = ScreenScraperClient(config(), http)
        self.assertEqual([row.remote_game_id for row in provider.identify(
            ScrapeIdentity("mame2003", "1942.zip"))], ["39874"])
        self.assertEqual([row.remote_game_id for row in provider.search("1942", "fbneo")],
                         ["39874"])

    def test_search_ignores_wrapper_without_game_id(self):
        http = FakeHttp([FakeResponse({"response": {"jeux": [{"error": "no match"}]}})])
        self.assertEqual(ScreenScraperClient(config(), http).search("abcop", "fbneo"), [])

    def test_search_rejects_other_system_results_and_unknown_names(self):
        http = FakeHttp([FakeResponse({"response": {"jeux": [
            {"id": "1", "nom": "Godzilla", "systeme": {"id": "113", "nom": "MSX"}},
            {"id": "2", "nom": "Godzilla", "systeme": {"id": "58", "nom": "PS2"}},
            {"id": "3", "nom": "Godzilla"},
        ]}})])
        provider = ScreenScraperClient(config(), http)
        self.assertEqual([item.remote_game_id for item in provider.search("Godzilla", "msx")],
                         ["1", "3"])
        with self.assertRaises(ScreenScraperError):
            provider.search("Godzilla", "unknown-system")
        self.assertEqual(len(http.calls), 1)

    def test_unrelated_single_search_result_is_not_forced_as_a_candidate(self):
        http = FakeHttp([FakeResponse({"response": {"jeux": [{
            "id": "9", "nom": "Completely Different Racing Game",
        }]}})])
        self.assertEqual(ScreenScraperClient(config(), http).search("SD Snatcher", ""), [])

    def test_arcade_short_name_keeps_explicit_same_system_as_review_candidate(self):
        http = FakeHttp([FakeResponse({"response": {"jeux": [
            {"id": "1", "nom": "Street Fighter II - The World Warrior",
             "systeme": {"id": "75", "nom": "MAME"}},
            {"id": "2", "nom": "Street Fighter II - Console Edition",
             "systeme": {"id": "58", "nom": "PS2"}},
            {"id": "3", "nom": "Unverified Arcade Title"},
        ]}})])
        with self.assertLogs("app.scrape.providers.screenscraper", level="INFO") as logs:
            found = ScreenScraperClient(config(), http).search("sf2", "fbneo")
        self.assertEqual([item.remote_game_id for item in found], ["1"])
        self.assertLess(found[0].confidence, 45)
        self.assertIn("직접 확인 필요", found[0].confidence_reason)
        self.assertIn("systemeid", http.calls[0][1]["params"])
        self.assertEqual(http.calls[0][1]["params"]["systemeid"], "75")
        self.assertTrue(any("decision=arcadeReview" in line and "similarity=" in line
                            and "title=Street Fighter II" in line for line in logs.output))
        self.assertTrue(any("decision=otherSystem" in line for line in logs.output))
        self.assertTrue(any("decision=lowSimilarity" in line for line in logs.output))

    def test_common_arcade_set_names_are_reviewable_without_claiming_title_match(self):
        samples = (("sf2", "Street Fighter II - The World Warrior"),
                   ("mslug", "Metal Slug - Super Vehicle-001"),
                   ("kof98", "The King of Fighters '98"))
        for query, title in samples:
            with self.subTest(query=query):
                http = FakeHttp([FakeResponse({"response": {"jeux": [{
                    "id": "1", "nom": title, "systeme": {"id": "75", "nom": "MAME"},
                }]}})])
                found = ScreenScraperClient(config(), http).search(query, "mame")
                self.assertEqual([item.title for item in found], [title])
                self.assertLess(found[0].confidence, 45)

    def test_arcade_short_name_does_not_rescue_all_systems_or_unknown_platform(self):
        game = {"id": "1", "nom": "Street Fighter II - The World Warrior",
                "systeme": {"id": "75", "nom": "MAME"}}
        missing_system = {"id": "2", "nom": "Street Fighter II - The World Warrior"}
        for hint, rows in (("", [game]), ("fbneo", [missing_system])):
            with self.subTest(hint=hint):
                http = FakeHttp([FakeResponse({"response": {"jeux": rows}})])
                self.assertEqual(ScreenScraperClient(config(), http).search("sf2", hint), [])

    def test_arcade_full_title_still_rejects_unrelated_result(self):
        http = FakeHttp([FakeResponse({"response": {"jeux": [{
            "id": "9", "nom": "Completely Different Racing Game",
            "systeme": {"id": "75", "nom": "MAME"},
        }]}})])
        self.assertEqual(ScreenScraperClient(config(), http).search("Street Fighter II", "mame"), [])

    def test_search_accepts_documented_json_localized_fields(self):
        http = FakeHttp([FakeResponse({"response": {"jeux": [{
            "id": "42", "nom": "Godzilla", "systeme": {"id": "113", "nom": "MSX"},
            "noms": {"nom_us": "Godzilla: Monster of Monsters", "nom_jp": "ゴジラ"},
            "synopsis": {"synopsis_en": "English description"},
            "dates": {"date_us": "1988-01-01"},
        }]}})])
        found = ScreenScraperClient(config(), http).search("Godzilla", "msx")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].fields["desc"], "English description")
        self.assertEqual(found[0].fields["releasedate"], "1988-01-01")
        self.assertIn("Godzilla: Monster of Monsters", found[0].alternate_titles)

    def test_japanese_title_can_match_its_localized_name(self):
        http = FakeHttp([FakeResponse({"response": {"jeux": [{
            "id": "42", "nom": "Evangelion 2", "systeme": {"id": "58"},
            "noms": {"nom_jp": "新世紀エヴァンゲリオン2"},
        }]}})])
        found = ScreenScraperClient(config(), http).search("新世紀エヴァンゲリオン2", "ps2")
        self.assertEqual([row.remote_game_id for row in found], ["42"])
        self.assertGreaterEqual(found[0].confidence, 80)

    def test_404_means_no_match_but_401_and_429_remain_visible(self):
        self.assertEqual(ScreenScraperClient(config(), FakeHttp([FakeResponse({}, status=404)]))
                         .search("missing", "msx"), [])
        for status, kind in ((401, "busy"), (403, "auth"), (429, "rate"),
                             (430, "quota"), (431, "quota")):
            with self.subTest(status=status):
                provider = ScreenScraperClient(config(), FakeHttp([FakeResponse({}, status=status)]))
                with self.assertRaises(ScreenScraperError) as raised:
                    provider.search("Godzilla", "msx")
                self.assertEqual(raised.exception.kind, kind)

    def test_only_one_media_per_requested_type_is_returned(self):
        cfg = ScreenScraperConfig("developer", "secret", "RetroMetaStudio",
                                  media_types=("covers", "videos"))
        http = FakeHttp([FakeResponse({"response": {"jeux": [{
            "id": "42", "nom": "Game", "medias": [
                {"type": "box-2d", "url": "https://media.screenscraper.fr/a.png"},
                {"type": "box-2d", "url": "https://media.screenscraper.fr/b.png"},
                {"type": "ss", "url": "https://media.screenscraper.fr/shot.png"},
                {"type": "video", "url": "https://media.screenscraper.fr/video.mp4"},
            ],
        }]}})])
        found = ScreenScraperClient(cfg, http).search("Game", "")
        self.assertEqual([item.media_type for item in found[0].media], ["covers", "videos"])

    def test_empty_media_selection_returns_metadata_without_media(self):
        cfg = ScreenScraperConfig("developer", "secret", "RetroMetaStudio", media_types=())
        http = FakeHttp([FakeResponse({"response": {"jeux": [{
            "id": "42", "nom": "Game", "medias": [
                {"type": "box-2d", "url": "https://media.screenscraper.fr/a.png"},
            ],
        }]}})])
        found = ScreenScraperClient(cfg, http).search("Game", "")
        self.assertEqual(found[0].media, ())

    def test_hash_identification_can_be_disabled_without_reading_the_rom(self):
        cfg = ScreenScraperConfig("developer", "secret", "RetroMetaStudio", use_hashes=False)
        http = FakeHttp([])
        missing = self.dir / "large-rom-that-must-not-be-opened.iso"
        self.assertEqual(ScreenScraperClient(cfg, http).identify(
            ScrapeIdentity("ps2", missing.name, str(missing))), [])
        self.assertEqual(http.calls, [])

    def test_quota_http_error_is_classified(self):
        provider = ScreenScraperClient(config(), FakeHttp([FakeResponse({}, status=429)]))
        with self.assertRaises(ScreenScraperError) as raised:
            provider.account_status()
        self.assertEqual(raised.exception.kind, "rate")


class SessionTests(unittest.TestCase):
    def test_title_similarity_handles_accents_and_numbered_sequels(self):
        self.assertEqual(_title_similarity("Pokemon 2", "Pokémon II"), 1.0)
        self.assertEqual(_title_similarity("Final Fantasy III", "Final Fantasy 3"), 1.0)
        self.assertLess(_title_similarity("Pokemon 2", "Final Fantasy 3"), 0.45)

    def test_fullwidth_colon_gets_bounded_search_variants(self):
        self.assertEqual(_query_fallbacks("Game： Subtitle"),
                         ["Game:Subtitle", "Game"])

    def test_weak_first_candidate_does_not_prevent_subtitle_fallback(self):
        weak = candidate()
        strong = ScrapeCandidate(**{**weak.__dict__, "candidate_id": "screenscraper:43",
                                    "remote_game_id": "43", "confidence": 95})
        weak = ScrapeCandidate(**{**weak.__dict__, "confidence": 50})
        class Provider:
            searches = []
            def identify(self, identity):
                return []
            def search(self, query, system_hint=""):
                self.__class__.searches.append(query)
                return [strong] if query == "Game" else [weak]

        service = ScrapeService(Provider)
        item = service.item("1", "ps2", "Game: Subtitle.iso", {})
        session = service.sessions.create("collection", "c1", [item])
        result = service.search_item(session["id"], "1", None, None)
        self.assertEqual(Provider.searches, ["Game: Subtitle", "Game:Subtitle", "Game"])
        self.assertEqual(result["item"]["candidates"][0]["remote_game_id"], "43")
        self.assertEqual(result["quota"]["requestsToday"], 3)

    def test_confirmed_match_uses_game_id_only_for_unchanged_query_and_system(self):
        class Provider:
            calls = []
            def confirmed_game(self, game_id, system):
                self.__class__.calls.append(("confirmed", game_id, system))
                return [candidate()]
            def identify(self, identity):
                self.__class__.calls.append(("identify", identity.system))
                return []
            def search(self, query, system_hint=""):
                self.__class__.calls.append(("search", query))
                return []

        service = ScrapeService(Provider)
        item = service.item("1", "ps2", "game.rom", {})
        item["confirmedGameId"] = "42"
        session = service.sessions.create("collection", "c1", [item])
        result = service.search_item(session["id"], "1", None, None)
        self.assertEqual(Provider.calls, [("confirmed", "42", "ps2")])
        self.assertEqual(result["quota"]["requestsToday"], 1)
        Provider.calls.clear()
        service.search_item(session["id"], "1", "another game", None)
        self.assertEqual(Provider.calls, [("identify", "ps2"), ("search", "another game")])

    def test_subtitle_variants_run_only_after_miss_and_stop_at_first_match(self):
        class Provider:
            searches = []
            def identify(self, identity):
                return []
            def search(self, query, system_hint=""):
                self.__class__.searches.append(query)
                return [candidate()] if query == "Game:Subtitle" else []

        service = ScrapeService(Provider)
        item = service.item("1", "ps2", "Game Subtitle.iso", {})
        session = service.sessions.create("collection", "c1", [item])
        result = service.search_item(session["id"], "1", "Game: Subtitle", None)
        self.assertEqual(Provider.searches, ["Game: Subtitle", "Game:Subtitle"])
        self.assertEqual(result["item"]["query"], "Game:Subtitle")
        self.assertEqual(result["quota"]["requestsToday"], 2)

    def test_subtitle_fallback_is_bounded_and_does_not_search_subtitle_alone(self):
        class Provider:
            searches = []
            def identify(self, identity):
                return []
            def search(self, query, system_hint=""):
                self.__class__.searches.append(query)
                return []

        service = ScrapeService(Provider)
        item = service.item("1", "ps2", "Game - Subtitle.iso", {})
        session = service.sessions.create("collection", "c1", [item])
        result = service.search_item(session["id"], "1", None, None)
        self.assertEqual(Provider.searches, ["Game - Subtitle", "Game: Subtitle", "Game"])
        self.assertEqual(result["item"]["status"], "not_found")
        self.assertEqual(result["quota"]["requestsToday"], 3)

    def test_arcade_short_name_retries_existing_human_title(self):
        class Provider:
            searches = []
            def identify(self, identity):
                return []
            def search(self, query, system_hint=""):
                self.__class__.searches.append((query, system_hint))
                return [candidate()] if query == "World Soccer 90" else []

        service = ScrapeService(Provider)
        item = service.item("1", "fbneo", "ws90.zip", {"name": "World Soccer 90"})
        session = service.sessions.create("collection", "c1", [item])
        result = service.search_item(session["id"], "1", None, None)
        self.assertEqual(Provider.searches, [("ws90", "fbneo"), ("World Soccer 90", "fbneo")])
        self.assertEqual(result["item"]["query"], "World Soccer 90")
        self.assertEqual(result["item"]["status"], "review")

    def test_weak_arcade_romname_result_also_checks_existing_english_title(self):
        weak = ScrapeCandidate(**{**candidate().__dict__, "confidence": 40,
                                  "remote_game_id": "42", "candidate_id": "screenscraper:42"})
        strong = ScrapeCandidate(**{**candidate().__dict__, "confidence": 95,
                                    "remote_game_id": "43", "candidate_id": "screenscraper:43"})
        class Provider:
            searches = []
            def identify(self, identity):
                return [weak]
            def search(self, query, system_hint=""):
                self.__class__.searches.append(query)
                return [strong]

        service = ScrapeService(Provider)
        item = service.item("1", "fbneo", "ws90.zip", {"name": "World Stadium 90"})
        session = service.sessions.create("archive", None, [item])
        result = service.search_item(session["id"], "1", None, None)
        self.assertEqual(Provider.searches, ["World Stadium 90"])
        self.assertEqual(result["item"]["candidates"][0]["remote_game_id"], "43")


    def test_hash_miss_falls_back_to_name_without_waiting_for_quota(self):
        class Provider:
            statuses = 0
            searches = []
            def account_status(self):
                self.__class__.statuses += 1
                return {"requestsToday": 10, "requestsLimit": 100}
            def identify(self, identity):
                return []
            def search(self, query, system_hint=""):
                self.__class__.searches.append((query, system_hint))
                return [candidate()]

        service = ScrapeService(Provider)
        first = service.item("1", "ps2", "게임 (K).zip", {})
        second = service.item("2", "ps2", "다른 게임.zip", {})
        session = service.sessions.create("collection", "c1", [first, second])
        one = service.search_item(session["id"], "1", None, None)
        two = service.search_item(session["id"], "2", "수동 검색", "58")
        self.assertEqual(Provider.statuses, 0)
        self.assertEqual(Provider.searches, [("게임", "ps2"), ("수동 검색", "58")])
        self.assertEqual(one["item"]["status"], "review")
        self.assertTrue(two["quota"]["estimated"])
        self.assertEqual(two["quota"]["requestsToday"], 2)

    def test_selection_rejects_unknown_fields_and_media_indexes(self):
        service = ScrapeService(lambda: None)
        item = service.item("1", "ps2", "game.rom", {})
        item["candidates"] = [candidate((ScrapeMedia("covers", "https://x"),)).to_dict()]
        session = service.sessions.create("collection", "c1", [item])
        selected = service.select(session["id"], "1", "screenscraper:42",
                                  ["name", "unknown"], [0, 5, -1])
        self.assertEqual(selected["selectedFields"], ["name"])
        self.assertEqual(selected["selectedMedia"], [0])
        proposal = service.proposal(selected)
        self.assertEqual(proposal["fields"], {"name": "게임"})
        self.assertEqual(len(proposal["media"]), 1)

    def test_skip_clears_a_previous_selection(self):
        service = ScrapeService(lambda: None)
        item = service.item("1", "ps2", "game.rom", {})
        item["candidates"] = [candidate().to_dict()]
        session = service.sessions.create("collection", "c1", [item])
        service.select(session["id"], "1", "screenscraper:42")
        skipped = service.skip(session["id"], "1")
        self.assertEqual(skipped["status"], "skipped")
        self.assertIsNone(service.proposal(skipped))


class SecretAndProvenanceTests(unittest.TestCase):
    def test_confirmed_match_is_scoped_by_target_collection_system_and_size(self):
        directory = Path(tempfile.mkdtemp(prefix="rms_scraper_matches_"))
        store = RegistryStore(directory / "registry.db")
        try:
            store.set_scrape_confirmed_match(
                target_kind="collection", collection_id="c1", system="ps2",
                filename="Game.iso", size=123, provider="screenscraper", remote_game_id="42")
            self.assertEqual(store.scrape_confirmed_match(
                "collection", "c1", "ps2", "game.iso", 123)["remote_game_id"], "42")
            self.assertIsNone(store.scrape_confirmed_match("archive", None, "ps2", "game.iso", 123))
            self.assertIsNone(store.scrape_confirmed_match("collection", "c2", "ps2", "game.iso", 123))
            self.assertIsNone(store.scrape_confirmed_match("collection", "c1", "ps2", "game.iso", 124))
        finally:
            store.close()

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows secure storage test")
    def test_windows_secure_storage_round_trip(self):
        reference = scrape_secrets.store("tests/scraper-secret", "개발자-비밀번호")
        try:
            self.assertNotIn("비밀번호", reference)
            self.assertEqual(scrape_secrets.load(reference), "개발자-비밀번호")
        finally:
            scrape_secrets.delete(reference)

    def test_bridge_never_returns_or_plaintext_stores_secrets(self):
        directory = Path(tempfile.mkdtemp(prefix="rms_scraper_secrets_"))
        api = Api(registry_path=directory / "registry.db", cache_dir=directory / "cache")
        try:
            with mock.patch.object(scrape_secrets, "store",
                                   side_effect=lambda name, value: f"cred:test/{name}/{value}"):
                saved = api.save_scraper_settings({"devId": "dev", "devPassword": "pw",
                                                   "userId": "user", "userPassword": "user-pw"})
            self.assertTrue(saved["ok"], saved.get("error"))
            self.assertNotIn("devId", saved["data"])
            self.assertNotIn("devPassword", saved["data"])
            raw = api.registry.get_setting(api.SCRAPER_SECRET_KEY)
            self.assertEqual(raw, {"devId": "cred:test/scraper/devId/dev",
                                   "devPassword": "cred:test/scraper/devPassword/pw",
                                   "userPassword": "cred:test/scraper/userPassword/user-pw"})
        finally:
            api.close()

    def test_provenance_round_trip_includes_media(self):
        directory = Path(tempfile.mkdtemp(prefix="rms_scraper_provenance_"))
        store = RegistryStore(directory / "registry.db")
        try:
            store.add_scrape_provenance(target_kind="collection", collection_id="c1", item_id="7",
                                        provider="screenscraper", remote_game_id="42",
                                        evidence=["ROM 해시 일치"], fields={"name": "게임"},
                                        media=[{"media_type": "covers", "url": "https://example"}])
            row = store.scrape_provenance("collection", "c1", "7")[0]
            self.assertEqual(row["fields"], {"name": "게임"})
            self.assertEqual(row["media"][0]["media_type"], "covers")
        finally:
            store.close()


class ApplyBoundaryTests(unittest.TestCase):
    class Registry:
        def __init__(self):
            self.rows = []
            self.matches = []
        def add_scrape_provenance(self, **value):
            self.rows.append(value)
        def set_scrape_confirmed_match(self, **value):
            self.matches.append(value)

    def make_api(self):
        api = Api.__new__(Api)
        api.scrape = ScrapeService(lambda: None)
        api.registry = self.Registry()
        return api

    def selected_session(self, api, *, target="collection"):
        media = ScrapeMedia("covers", "https://media.screenscraper.fr/cover.png")
        item = api.scrape.item("1", "ps2", "game.rom", {"name": "Old"})
        item["candidates"] = [candidate((media,)).to_dict()]
        session = api.scrape.sessions.create(target, "c1" if target == "collection" else None, [item])
        api.scrape.select(session["id"], "1", "screenscraper:42", ["name"], [0])
        return session, item

    def test_partial_apply_keeps_only_failed_media_for_retry(self):
        api = self.make_api()
        session, item = self.selected_session(api)
        api.save_fields = lambda *args: {"ok": True, "data": {}}
        api._download_scrape_media = lambda *args: __file__
        api._apply_scraped_collection_media = lambda *args: (_ for _ in ()).throw(ValueError("disk full"))
        first = api._apply_scrape_session(session["id"], lambda *args: None)
        self.assertEqual(len(first["partial"]), 1)
        self.assertEqual(item["selectedFields"], [])
        self.assertEqual(item["selectedMedia"], [0])
        self.assertEqual(api.registry.rows[0]["fields"], {"name": "게임"})
        self.assertEqual(api.registry.matches, [])

        api._apply_scraped_collection_media = lambda *args: None
        second = api._apply_scrape_session(session["id"], lambda *args: None)
        self.assertEqual(second, {"applied": ["1"], "partial": [], "failed": []})
        self.assertEqual(api.registry.matches[0]["remote_game_id"], "42")
        with self.assertRaises(KeyError):
            api.scrape.sessions.get(session["id"])

    def test_apply_selected_item_keeps_unsearched_items_in_session(self):
        api = self.make_api()
        session, selected = self.selected_session(api)
        pending = api.scrape.item("2", "ps2", "next.rom", {})
        session["items"].append(pending)
        api.save_fields = lambda *args: {"ok": True, "data": {}}
        api._download_scrape_media = lambda *args: __file__
        api._apply_scraped_collection_media = lambda *args: []
        result = api._apply_scrape_session(session["id"], lambda *_args: None)
        self.assertEqual(result["applied"], ["1"])
        self.assertEqual(selected["status"], "applied")
        self.assertEqual(api.scrape.sessions.get(session["id"])["items"][1]["status"], "pending")

    def test_selected_media_downloads_can_progress_concurrently(self):
        api = self.make_api()
        media = tuple(ScrapeMedia(kind, f"https://media.screenscraper.fr/{kind}.png")
                      for kind in ("covers", "screenshots", "wheel"))
        item = api.scrape.item("1", "ps2", "game.rom", {})
        item["candidates"] = [candidate(media).to_dict()]
        session = api.scrape.sessions.create("collection", "c1", [item])
        api.scrape.select(session["id"], "1", "screenscraper:42", [], [0, 1, 2])
        barrier = threading.Barrier(3)
        def download(*_args):
            barrier.wait(timeout=2)
            return __file__
        api._download_scrape_media = download
        api._apply_scraped_collection_media = lambda *_args: []
        result = api._apply_scrape_session(session["id"], lambda *_args: None)
        self.assertEqual(result["applied"], ["1"])
        self.assertEqual(result["failed"], [])

    def test_archive_without_internal_media_does_not_treat_remote_as_owned(self):
        api = self.make_api()
        session, item = self.selected_session(api, target="archive")
        api.archive_edit = lambda *args: {"ok": True, "data": {}}
        api._archive_config = lambda: {"mediaInternal": False}
        result = api._apply_scrape_session(session["id"], lambda *args: None)
        self.assertEqual(len(result["partial"]), 1)
        self.assertEqual(item["selectedMedia"], [0])
        self.assertIn("내부 미디어", result["partial"][0]["error"])

    def test_media_download_rejects_non_screenscraper_hosts_before_network_access(self):
        api = self.make_api()
        with self.assertRaisesRegex(ValueError, "허용되지 않은"):
            api._download_scrape_media("https://evil.example/cover.png", "s", "i", "covers")

    def test_extensionless_provider_media_uses_response_content_type(self):
        class Download:
            headers = {"Content-Type": "image/png; charset=binary"}
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return None
            def raise_for_status(self):
                return None
            def iter_content(self, _size):
                yield b"png-data"

        with tempfile.TemporaryDirectory() as temporary:
            api = self.make_api()
            api._scrape_cache_dir = Path(temporary)
            with mock.patch("bridge.api.requests.get", return_value=Download()):
                path = api._download_scrape_media(
                    "https://www.screenscraper.fr/image.php?gameid=42", "s", "i", "covers")
            self.assertEqual(Path(path).suffix, ".png")
            self.assertEqual(Path(path).read_bytes(), b"png-data")

    def test_collection_scrape_applies_media_without_using_the_users_plan(self):
        class Download:
            headers = {"Content-Type": "image/png"}
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return None
            def raise_for_status(self):
                return None
            def iter_content(self, _size):
                yield b"new scraper cover"

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collection_root = build_esde_tree(root / "collection")
            api = Api(registry_path=root / "registry.db", cache_dir=root / "cache")
            try:
                cid = api.create_collection("Games", "es-de", str(collection_root))["data"]["id"]
                api.start_scan(cid)
                wait_idle(api)
                row = next(r for r in api.list_rows(cid)["data"]["rows"] if r["file"] == "FFX.iso")
                item = api.scrape.item(str(row["romUid"]), "ps2", "FFX.iso", row.get("fields") or {})
                item["candidates"] = [candidate((ScrapeMedia(
                    "covers", "https://www.screenscraper.fr/image.php?gameid=42"),)).to_dict()]
                session = api.scrape.sessions.create("collection", cid, [item])
                api.scrape.select(session["id"], item["id"], "screenscraper:42", [], [0])
                with mock.patch("bridge.api.requests.get", return_value=Download()):
                    result = api._apply_scrape_session(session["id"], lambda *args: None)
                self.assertEqual(result["failed"], [])
                self.assertEqual(result["partial"], [])
                cover = collection_root / "downloaded_media" / "ps2" / "covers" / "FFX.png"
                self.assertEqual(cover.read_bytes(), b"new scraper cover")
                self.assertEqual(api.plan_state(cid)["data"]["total"], 0)
            finally:
                api.close()

    def test_invalid_scraper_media_plan_is_reported_instead_of_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collection_root = build_esde_tree(root / "collection")
            api = Api(registry_path=root / "registry.db", cache_dir=root / "cache")
            try:
                cid = api.create_collection("Games", "es-de", str(collection_root))["data"]["id"]
                api.start_scan(cid)
                wait_idle(api)
                row = next(r for r in api.list_rows(cid)["data"]["rows"] if r["file"] == "FFX.iso")
                downloaded = root / "new-cover.png"
                downloaded.write_bytes(b"new scraper cover")
                old_cover = collection_root / "downloaded_media" / "ps2" / "covers" / "FFX.png"
                original = old_cover.read_bytes()
                with mock.patch("bridge.api.validate", return_value={"ok": False, "blocked": False,
                         "entries": [{"error": "대상 파일이 바뀌었습니다"}]}):
                    with self.assertRaisesRegex(ValueError, "대상 파일이 바뀌었습니다"):
                        api._apply_scraped_collection_media(cid, row["romUid"],
                                                            [("covers", str(downloaded))])
                self.assertEqual(old_cover.read_bytes(), original)
            finally:
                api.close()

    def test_multiple_scrapes_keep_later_rows_and_pending_plan_targets_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collection_root = build_esde_tree(root / "collection")
            api = Api(registry_path=root / "registry.db", cache_dir=root / "cache")
            try:
                cid = api.create_collection("Games", "es-de", str(collection_root))["data"]["id"]
                api.start_scan(cid)
                wait_idle(api)
                rows = [row for row in api.list_rows(cid)["data"]["rows"]
                        if row["file"] in ("FFX.iso", "MGS2.iso")]
                self.assertEqual(len(rows), 2)
                cache = api.workspace.open(cid)
                pending = builder.plan_metadata_edit(api._plan(cid), cache,
                                                     rows[1]["romUid"], {"genre": "Updated"})
                items = []
                for row in rows:
                    item = api.scrape.item(str(row["romUid"]), "ps2", row["file"], row.get("fields") or {})
                    item["candidates"] = [candidate((ScrapeMedia(
                        "covers", f"https://www.screenscraper.fr/image.php?gameid={row['romUid']}",
                        format="png"),)).to_dict()]
                    items.append(item)
                session = api.scrape.sessions.create("collection", cid, items)
                for item in items:
                    api.scrape.select(session["id"], item["id"], "screenscraper:42", [], [0])
                source = root / "cover.png"
                source.write_bytes(b"scraped cover")
                api._download_scrape_media = lambda *args: str(source)
                result = api._apply_scrape_session(session["id"], lambda *args: None)
                self.assertEqual(result["applied"], [item["id"] for item in items])
                self.assertEqual(result["failed"], [])
                current = next(row for row in api.workspace.open(cid).query_rows(systems=["ps2"])
                               if row["filename"] == pending.filename)
                self.assertEqual(pending.rom_uid, current["rom_uid"])
                self.assertEqual(api.validate_plan(cid)["data"]["blocked"], False)
            finally:
                api.close()


if __name__ == "__main__":
    unittest.main()
