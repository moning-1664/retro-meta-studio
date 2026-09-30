"""User DAT import must only provide a bounded, system-scoped search hint."""

from __future__ import annotations

import zlib
import zipfile
from pathlib import Path

from app.scrape.dat_catalog import DatCatalog
from app.scrape.models import ScrapeCandidate
from app.scrape.service import ScrapeService


def catalog(tmp_path):
    return DatCatalog(tmp_path / "dat.db")


def test_logiqx_import_and_single_member_zip_header_lookup(tmp_path):
    source = tmp_path / "games.dat"
    crc = f"{zlib.crc32(b'test'):08x}"
    source.write_text(f"""<datafile><header><name>Sample DAT</name><version>2026</version></header>
      <game name="Some Game"><description>Official Title</description>
        <rom name="original.bin" size="4" crc="{crc}"/></game></datafile>""")
    indexed = catalog(tmp_path)
    result = indexed.import_xml(source, "msx")
    assert (result["games"], result["name"], result["version"]) == (1, "Sample DAT", "2026")
    archive = tmp_path / "Korean Patched.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("patched.bin", b"test")
    hit = indexed.lookup("msx", archive.name, archive)
    assert hit and hit["title"] == "Official Title"
    assert hit["method"] == "zip-entry-size-crc"
    assert indexed.lookup("ps2", archive.name, archive) is None


def test_crc_shared_by_three_games_is_not_treated_as_an_exact_match(tmp_path):
    source = tmp_path / "ambiguous.dat"
    crc = f"{zlib.crc32(b'test'):08x}"
    indexed = catalog(tmp_path)
    for name in ("Alpha", "Beta", "Beta"):
        source.write_text(f'<datafile><game name="{name}"><description>{name}</description>'
                          f'<rom name="{name}.bin" size="4" crc="{crc}"/></game></datafile>')
        indexed.import_xml(source, "msx")
    archive = tmp_path / "Unknown.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("unknown.bin", b"test")
    assert indexed.lookup("msx", archive.name, archive) is None


def test_mame_shortname_lookup_keeps_system_and_parent(tmp_path):
    source = tmp_path / "mame.xml"
    source.write_text("""<mame><machine name="ws90" cloneof="ws89">
      <description>World Soccer 1990</description>
      <rom name="chip.bin" size="3" crc="12345678"/></machine></mame>""")
    indexed = catalog(tmp_path)
    indexed.import_xml(source, "arcade")
    hit = indexed.lookup("arcade", "ws90.zip")
    assert hit and (hit["title"], hit["parent"], hit["method"]) == (
        "World Soccer 1990", "ws89", "shortname")
    assert indexed.lookup("fbneo", "ws90.zip")["title"] == "World Soccer 1990"
    assert indexed.lookup("msx", "ws90.zip") is None


def test_mame_element_dtd_is_supported_but_entities_are_rejected(tmp_path):
    source = tmp_path / "mame.xml"
    source.write_text("""<?xml version="1.0"?>
    <!DOCTYPE mame [<!ELEMENT mame (machine*)><!ELEMENT machine (description)>
      <!ATTLIST machine name CDATA #REQUIRED><!ELEMENT description (#PCDATA)>]>
    <mame><machine name="sf2"><description>Street Fighter II</description></machine></mame>""")
    indexed = catalog(tmp_path)
    indexed.import_xml(source, "mame2003")
    assert indexed.lookup("fbneo", "sf2.zip")["title"] == "Street Fighter II"
    source.write_text("""<!DOCTYPE mame [<!ENTITY title "Injected">]>
      <mame><machine name="sf2"><description>&title;</description></machine></mame>""")
    try:
        indexed.import_xml(source, "arcade")
    except ValueError as error:
        assert "Entity" in str(error)
    else:
        raise AssertionError("entity declarations must be rejected")
    assert len(indexed.sources()) == 1


def test_dat_hint_queries_title_but_does_not_auto_confirm(tmp_path):
    source = tmp_path / "mame.xml"
    source.write_text("""<mame><machine name="ws90">
      <description>World Soccer 1990</description></machine></mame>""")
    indexed = catalog(tmp_path)
    indexed.import_xml(source, "arcade")

    class Provider:
        def __init__(self):
            self.queries = []

        def identify(self, identity):
            return []

        def search(self, query, system_hint=""):
            self.queries.append((query, system_hint))
            return [ScrapeCandidate("ss:1", "screenscraper", "1",
                                    "World Soccer 1990", "arcade", {"name": "World Soccer 1990"},
                                    confidence=95)]

    provider = Provider()
    service = ScrapeService(lambda: provider, dat_catalog=indexed)
    item = service.item("1", "arcade", "ws90.zip", {})
    session = service.sessions.create("collection", "c1", [item])
    result = service.search_item(session["id"], "1", None, None)
    assert provider.queries == [("World Soccer 1990", "arcade")]
    assert result["item"]["datHint"]["method"] == "shortname"
    assert result["item"]["selectedCandidateId"] is None


def test_invalid_xml_rolls_back_source(tmp_path):
    source = tmp_path / "bad.xml"
    source.write_text("<not-a-dat/>")
    indexed = catalog(tmp_path)
    try:
        indexed.import_xml(source, "msx")
    except ValueError:
        pass
    else:
        raise AssertionError("must reject unknown XML")
    assert indexed.sources() == []


def test_failed_query_cache_is_bypassed_by_manual_retry():
    class Provider:
        def __init__(self):
            self.queries = []

        def identify(self, identity):
            return []

        def search(self, query, system_hint=""):
            self.queries.append((query, system_hint))
            return []

    provider = Provider()
    service = ScrapeService(lambda: provider)
    item = service.item("1", "msx", "Unlisted.zip", {})
    session = service.sessions.create("collection", "c1", [item])
    service.search_item(session["id"], "1", None, None)
    service.search_item(session["id"], "1", "Unlisted", None)
    assert provider.queries == [("Unlisted", "msx")]
    service.search_item(session["id"], "1", "Unlisted", None, force_search=True)
    assert provider.queries == [("Unlisted", "msx"), ("Unlisted", "msx")]
