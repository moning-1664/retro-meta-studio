"""Scraper provider, review session, secrets, provenance and apply boundaries."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from app.scrape import ScrapeCandidate, ScrapeIdentity, ScrapeMedia, ScrapeService
from app.scrape import secrets as scrape_secrets
from app.scrape.providers.screenscraper import (
    ScreenScraperClient,
    ScreenScraperConfig,
    ScreenScraperError,
    hashes_of_file,
)
from app.store.registry import RegistryStore
from bridge.api import Api


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
        self.assertEqual(found[0].evidence, ("원본 별칭 해시 일치",))
        self.assertEqual(hashes_of_file(path)["crc32"], f"{zlib.crc32(b'patched') & 0xffffffff:08X}")

    def test_account_counters_tolerate_formatted_and_invalid_values(self):
        http = FakeHttp([FakeResponse({"response": {"ssuser": {
            "id": "u", "requeststoday": "1 234", "maxrequestsperday": "bad",
            "requestspermin": "7", "maxrequestspermin": None, "maxthreads": "2",
        }}})])
        status = ScreenScraperClient(config(), http).account_status()
        self.assertEqual(status["requestsToday"], 1234)
        self.assertEqual(status["requestsLimit"], 0)
        self.assertEqual(status["maxThreads"], 2)

    def test_search_only_sends_numeric_system_ids(self):
        payload = {"response": {"jeux": []}}
        http = FakeHttp([FakeResponse(payload), FakeResponse(payload)])
        provider = ScreenScraperClient(config(), http)
        provider.search("Game", "ps2")
        provider.search("Game", "58")
        self.assertNotIn("systemeid", http.calls[0][1]["params"])
        self.assertEqual(http.calls[1][1]["params"]["systemeid"], "58")

    def test_quota_http_error_is_classified(self):
        provider = ScreenScraperClient(config(), FakeHttp([FakeResponse({}, status=429)]))
        with self.assertRaises(ScreenScraperError) as raised:
            provider.account_status()
        self.assertEqual(raised.exception.kind, "quota")


class SessionTests(unittest.TestCase):
    def test_hash_miss_falls_back_to_name_and_quota_is_reused(self):
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
        self.assertEqual(Provider.statuses, 1)
        self.assertEqual(Provider.searches, [("게임", "ps2"), ("수동 검색", "58")])
        self.assertEqual(one["item"]["status"], "review")
        self.assertTrue(two["quota"]["estimated"])
        self.assertEqual(two["quota"]["requestsToday"], 12)

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
        def add_scrape_provenance(self, **value):
            self.rows.append(value)

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
        api.media_paste = lambda *args: {"ok": False, "error": "disk full"}
        first = api._apply_scrape_session(session["id"], lambda *args: None)
        self.assertEqual(len(first["partial"]), 1)
        self.assertEqual(item["selectedFields"], [])
        self.assertEqual(item["selectedMedia"], [0])
        self.assertEqual(api.registry.rows[0]["fields"], {"name": "게임"})

        api.media_paste = lambda *args: {"ok": True, "data": {}}
        second = api._apply_scrape_session(session["id"], lambda *args: None)
        self.assertEqual(second, {"applied": ["1"], "partial": [], "failed": []})
        with self.assertRaises(KeyError):
            api.scrape.sessions.get(session["id"])

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


if __name__ == "__main__":
    unittest.main()
