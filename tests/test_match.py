"""Match 엔진 테스트 (스펙 §45-49).

이 파일이 지켜야 하는 규칙은 둘이다.
- **자동으로 붙는 것은 Exact뿐이다(§49).** 정규화 이름만 같거나 유사도만 높은 후보는
  절대 자동 반영되지 않는다.
- **파일명만으로 Exact를 확정하지 않는다(§47).** 크기나 해시라는 확증이 있어야 한다.

fixture는 규모를 지정할 수 있는 build_scaled_esde_tree()를 쓴다. 게임이 3개뿐이면
"후보가 여럿이라 자동으로 못 고르는" 상황 자체를 만들 수 없기 때문이다.
"""

import unittest

from app.match import engine
from bridge.api import Api
from tests.fixtures import (build_custom_esde_tree, build_scaled_esde_tree,
                            scan, temp_root)


class ClassifyTests(unittest.TestCase):
    """엔진의 티어 판정만 따로 본다 - DB 없이 규칙 자체를 고정한다."""

    def source(self, **over):
        base = {"system": "ps2", "filename": "Game 001 (USA).iso", "size": 1000,
                "sha256": None, "title": "Game 001", "title_norm": "game 001",
                "filename_norm": "game 001", "developer": "", "releasedate": ""}
        base.update(over)
        return base

    def identity(self, **over):
        base = {"rom_identity_id": "i1", "game_id": "g1", "system": "ps2",
                "filename": "Game 001 (Europe).iso", "filename_norm": "game 001",
                "title": "Game 001", "title_norm": "game 001", "size": 1000,
                "sha256": None, "region": None}
        base.update(over)
        return base

    def test_same_hash_is_exact(self):
        tier, score, evidence = engine.classify(self.source(sha256="a" * 64),
                                                self.identity(sha256="a" * 64, size=999))
        self.assertEqual(tier, engine.TIER_EXACT)
        self.assertEqual(score, 100.0)
        self.assertEqual(evidence, ["SHA256 일치"], "왜 Exact인지 근거가 남아야 한다")

    def test_different_hash_is_never_a_candidate(self):
        """해시가 어긋나면 이름이 같아도 같은 ROM일 수 없다."""
        tier, _, _ = engine.classify(self.source(sha256="a" * 64), self.identity(sha256="b" * 64))
        self.assertIsNone(tier)

    def test_filename_alone_is_not_exact(self):
        """§47: 단순 Filename만으로 Exact Match를 확정해서는 안 된다."""
        tier, _, _ = engine.classify(self.source(size=None), self.identity(size=None))
        self.assertEqual(tier, engine.TIER_NORMALIZED)

    def test_filename_plus_size_is_exact(self):
        tier, _, _ = engine.classify(self.source(size=1000), self.identity(size=1000))
        self.assertEqual(tier, engine.TIER_EXACT)

    def test_same_name_different_size_stays_a_candidate(self):
        """지역판/리비전 차이로 보이는 상황 - 확증이 없으니 자동으로 붙이지 않는다."""
        tier, _, _ = engine.classify(self.source(size=1000), self.identity(size=2000))
        self.assertEqual(tier, engine.TIER_NORMALIZED)
        self.assertNotIn(engine.TIER_NORMALIZED, engine.AUTO_TIERS)

    def test_different_system_never_matches(self):
        tier, _, _ = engine.classify(self.source(), self.identity(system="snes"))
        self.assertIsNone(tier)

    def test_auto_match_needs_exactly_one_exact(self):
        exact_a = {"romIdentityId": "a", "tier": engine.TIER_EXACT, "score": 99.0}
        exact_b = {"romIdentityId": "b", "tier": engine.TIER_EXACT, "score": 99.0}
        loose = {"romIdentityId": "c", "tier": engine.TIER_NORMALIZED, "score": 85.0}
        self.assertEqual(engine.auto_match([exact_a, loose])["romIdentityId"], "a")
        self.assertIsNone(engine.auto_match([exact_a, exact_b]), "Exact가 둘이면 사람이 골라야 한다")
        self.assertIsNone(engine.auto_match([loose]), "Normalized는 절대 자동이 아니다")


class MatchApiTests(unittest.TestCase):
    """실제 Collection 두 개(USA판 / Europe판)를 만들어 놓고 API 경로로 확인한다."""

    def setUp(self):
        self.dir = temp_root("rms_match_")
        usa = build_scaled_esde_tree(self.dir / "usa", systems=("ps2",), per_system=10)
        eur = build_scaled_esde_tree(self.dir / "eur", systems=("ps2",), per_system=10,
                                     variant="region")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.usa = self.api.create_collection("USA", "es-de", str(usa))["data"]["id"]
        self.eur = self.api.create_collection("EUR", "es-de", str(eur))["data"]["id"]
        for cid in (self.usa, self.eur):
            scan(self.api, cid)
        # Archive에는 USA판만 넣어 둔다 - EUR Collection이 그걸 찾아가는 상황.
        self.api.archive_ingest(self.usa)

    def tearDown(self):
        self.api.close()

    def _row(self, collection_id, filename):
        rows = self.api.list_rows(collection_id, limit=500)["data"]["rows"]
        return next(r for r in rows if r["file"] == filename)

    # ------------------------------------------------------------------
    def test_region_variants_are_separate_identities(self):
        """§46: 같은 Game이라도 지역판은 서로 다른 ROM Identity다."""
        self.api.archive_ingest(self.eur)
        rows = self.api.archive_rows(limit=500)["data"]["rows"]
        files = {r["file"] for r in rows}
        self.assertIn("Game 001 (USA).iso", files)
        self.assertIn("Game 001 (Europe).iso", files)
        self.assertEqual(len(rows), 20, "USA 10개 + Europe 10개가 각자 남아야 한다")

    def test_candidates_are_offered_but_nothing_is_applied(self):
        row = self._row(self.eur, "Game 001 (Europe).iso")
        result = self.api.match_candidates(self.eur, row["romUid"])["data"]

        self.assertTrue(result["candidates"], "USA판이 후보로 나와야 한다")
        top = result["candidates"][0]
        self.assertEqual(top["filename"], "Game 001 (USA).iso")
        self.assertEqual(top["tier"], engine.TIER_NORMALIZED, "크기가 달라 Exact가 될 수 없다")
        self.assertIsNone(result["autoMatch"], "자동으로 붙일 수 있는 후보가 아니다")
        self.assertIsNone(result["linkedRomIdentityId"], "고르기 전에는 아무것도 붙어 있지 않다")

    def test_candidates_exclude_the_collections_own_entries(self):
        """자기가 올린 Identity가 자기 후보로 뜨면 안 된다."""
        row = self._row(self.usa, "Game 001 (USA).iso")
        result = self.api.match_candidates(self.usa, row["romUid"])["data"]
        self.assertEqual(result["candidates"], [])

    def test_apply_match_records_the_choice(self):
        row = self._row(self.eur, "Game 001 (Europe).iso")
        candidates = self.api.match_candidates(self.eur, row["romUid"])["data"]["candidates"]
        chosen = candidates[0]["romIdentityId"]

        applied = self.api.apply_match(self.eur, row["romUid"], chosen)["data"]
        self.assertEqual(applied["romIdentityId"], chosen)
        self.assertEqual(applied["tier"], engine.TIER_NORMALIZED)

        again = self.api.match_candidates(self.eur, row["romUid"])["data"]
        self.assertEqual(again["linkedRomIdentityId"], chosen)
        self.assertTrue(next(c for c in again["candidates"] if c["romIdentityId"] == chosen)["linked"])

    def test_matched_row_ingests_into_the_linked_identity(self):
        """Match를 확정했으면 다시 Ingest해도 새 Identity를 만들지 않는다."""
        row = self._row(self.eur, "Game 001 (Europe).iso")
        chosen = self.api.match_candidates(self.eur, row["romUid"])["data"]["candidates"][0]["romIdentityId"]
        self.api.apply_match(self.eur, row["romUid"], chosen)

        before = self.api.archive_rows(limit=500)["data"]["total"]
        self.api.archive_ingest(self.eur)
        after = self.api.archive_rows(limit=500)["data"]["total"]
        self.assertEqual(after - before, 9, "Match한 1개는 기존 Identity에 붙어 새로 늘지 않는다")

        detail = self.api.archive_detail(chosen)["data"]
        self.assertEqual({s["collectionId"] for s in detail["sources"]}, {self.usa, self.eur},
                         "두 Collection이 같은 Identity의 출처로 나란히 보여야 한다(§44)")

    def test_clear_match_removes_the_link(self):
        row = self._row(self.eur, "Game 001 (Europe).iso")
        chosen = self.api.match_candidates(self.eur, row["romUid"])["data"]["candidates"][0]["romIdentityId"]
        self.api.apply_match(self.eur, row["romUid"], chosen)
        self.assertTrue(self.api.clear_match(self.eur, row["romUid"])["data"]["cleared"])
        self.assertIsNone(self.api.match_candidates(self.eur, row["romUid"])["data"]["linkedRomIdentityId"])

    def test_match_counts_skips_rows_that_are_already_linked(self):
        rows = self.api.list_rows(self.eur, limit=500)["data"]["rows"]
        uids = [r["romUid"] for r in rows]
        counts = self.api.match_counts(self.eur, uids)["data"]
        self.assertTrue(counts, "이름이 같은 USA판이 있으므로 뱃지가 떠야 한다")

        target = self._row(self.eur, "Game 001 (Europe).iso")
        chosen = self.api.match_candidates(self.eur, target["romUid"])["data"]["candidates"][0]["romIdentityId"]
        self.api.apply_match(self.eur, target["romUid"], chosen)

        after = self.api.match_counts(self.eur, uids)["data"]
        self.assertNotIn(str(target["romUid"]), after, "이미 확정한 행에는 뱃지를 띄우지 않는다")

    def test_match_across_systems_is_refused(self):
        snes_root = build_scaled_esde_tree(self.dir / "snes", systems=("snes",), per_system=2)
        snes = self.api.create_collection("SNES", "es-de", str(snes_root))["data"]["id"]
        scan(self.api, snes)
        row = self._row(snes, "Game 001 (USA).iso")
        ps2_identity = self.api.archive_rows(limit=500)["data"]["rows"][0]["romIdentityId"]
        result = self.api.apply_match(snes, row["romUid"], ps2_identity)
        self.assertFalse(result["ok"])
        self.assertIn("System", result["error"])


class GoldenMatchCases(unittest.TestCase):
    """티어 판정을 케이스별로 고정한다.

    Match에서 무서운 것은 "테스트가 실패하는 것"이 아니라 **잘못된 매칭이 조용히
    통과하는 것**이다. 그래서 판정 규칙 하나하나에 이름을 붙여 박아 둔다 - 누군가
    임계값이나 티어 순서를 건드리면 어느 케이스가 무너졌는지 바로 보이도록.
    """

    def pair(self, src=None, ident=None):
        source = {"system": "ps2", "filename": "Game (USA).iso", "size": 1000,
                  "sha256": None, "title": "Game", "title_norm": "game",
                  "filename_norm": "game", "developer": "", "publisher": "",
                  "releasedate": ""}
        identity = {"rom_identity_id": "i1", "game_id": "g1", "system": "ps2",
                    "filename": "Game (Europe).iso", "filename_norm": "game",
                    "title": "Game", "title_norm": "game", "size": 1000,
                    "sha256": None, "region": None}
        source.update(src or {})
        identity.update(ident or {})
        return source, identity

    # --- Exact ---------------------------------------------------------
    def test_golden_same_hash(self):
        source, identity = self.pair({"sha256": "a" * 64}, {"sha256": "a" * 64, "size": 999})
        self.assertEqual(engine.classify(source, identity)[0], engine.TIER_EXACT)

    def test_golden_same_filename_and_size(self):
        source, identity = self.pair({"size": 1000}, {"size": 1000})
        self.assertEqual(engine.classify(source, identity)[0], engine.TIER_EXACT)

    def test_golden_same_filename_different_hash_is_excluded(self):
        """해시가 어긋나면 이름과 크기가 같아도 같은 ROM이 아니다."""
        source, identity = self.pair({"sha256": "a" * 64}, {"sha256": "b" * 64})
        self.assertIsNone(engine.classify(source, identity)[0])

    # --- Normalized ----------------------------------------------------
    def test_golden_region_variants_are_normalized_not_exact(self):
        source, identity = self.pair({"size": 1000}, {"size": 2000})
        self.assertEqual(engine.classify(source, identity)[0], engine.TIER_NORMALIZED)

    def test_golden_metadata_only_entry_cannot_be_exact(self):
        """크기를 모르는 항목(ROM 없는 metadata-only)은 확증이 없다(§47)."""
        source, identity = self.pair({"size": None}, {"size": None})
        self.assertEqual(engine.classify(source, identity)[0], engine.TIER_NORMALIZED)

    # --- Metadata / Heuristic ------------------------------------------
    def test_golden_developer_and_release_make_a_metadata_candidate(self):
        source, _ = self.pair({"developer": "Konami", "releasedate": "20010719T000000"})
        tier, score, evidence = engine._metadata_match(
            source, self.pair(ident={"developer": "Konami",
                                        "releasedate": "20010719T000000"})[1])
        self.assertEqual(tier, engine.TIER_METADATA)
        self.assertGreaterEqual(score, engine.METADATA_THRESHOLD)
        self.assertIn("개발사 일치", evidence)

    def test_golden_developer_alone_is_not_enough(self):
        """같은 회사가 낸 다른 게임까지 후보로 올라오면 목록이 쓸모없어진다."""
        source, _ = self.pair({"developer": "Konami", "releasedate": "20010719T000000"})
        self.assertIsNone(engine._metadata_match(source, self.pair(ident={"developer": "Konami"})[1])[0])

    def test_golden_empty_fields_never_match_each_other(self):
        source, _ = self.pair()
        self.assertIsNone(engine._metadata_match(source, self.pair()[1])[0])

    def test_golden_similar_names_land_in_heuristic(self):
        source, identity = self.pair(
            {"title": "Metal Gear Solid 2", "filename": "Metal Gear Solid 2.iso",
             "title_norm": "metal gear solid 2", "filename_norm": "metal gear solid 2"},
            {"title": "Metal Gear Solid 2 Substance",
             "filename": "Metal Gear Solid 2 Substance.iso",
             "title_norm": "metal gear solid 2 substance",
             "filename_norm": "metal gear solid 2 substance"})
        self.assertIsNone(engine.classify(source, identity)[0], "이름이 달라 앞 티어로는 안 걸린다")
        tier, score, evidence = engine._heuristic_match(source, identity)
        self.assertEqual(tier, engine.TIER_HEURISTIC)
        self.assertGreaterEqual(score, engine.HEURISTIC_THRESHOLD)
        self.assertTrue(evidence, "점수를 만든 근거를 사용자에게 보여줄 수 있어야 한다")

    def test_golden_unrelated_titles_are_not_candidates(self):
        source, identity = self.pair(
            {"title": "Final Fantasy X", "filename": "FFX.iso",
             "title_norm": "final fantasy x", "filename_norm": "ffx"},
            {"title": "Gran Turismo 3", "filename": "GT3.iso",
             "title_norm": "gran turismo 3", "filename_norm": "gt3"})
        self.assertIsNone(engine.classify(source, identity)[0])
        self.assertIsNone(engine._heuristic_match(source, identity)[0])

    # --- 자동 매칭 -----------------------------------------------------
    def test_golden_two_exact_candidates_block_auto_match(self):
        """모호하면 자동으로 결정하지 않는다(§88)."""
        exact = [{"romIdentityId": "a", "tier": engine.TIER_EXACT, "score": 99.0},
                 {"romIdentityId": "b", "tier": engine.TIER_EXACT, "score": 99.0}]
        self.assertIsNone(engine.auto_match(exact))

    def test_golden_manual_tier_is_never_automatic(self):
        self.assertNotIn(engine.TIER_MANUAL, engine.AUTO_TIERS)
        self.assertIsNone(engine.auto_match(
            [{"romIdentityId": "a", "tier": engine.TIER_MANUAL, "score": 0.0}]))


class ApplyMatchPolicyTests(unittest.TestCase):
    """Apply Match가 "근거 있는 선택"만 받아들이는지.

    Match Link는 메모가 아니라 Ingest / Archive -> Collection / Compare가 "같은 ROM"이라고
    믿고 쓰는 관계 데이터다. 근거 없는 연결이 티어까지 위장한 채 같은 테이블에 섞이면
    나중에 그 링크가 어디서 왔는지 설명할 수 없게 된다.
    """

    def setUp(self):
        self.dir = temp_root("rms_apply_")
        source_root = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "Metal Gear Solid 2.iso", "title": "Metal Gear Solid 2",
             "developer": "Konami", "releasedate": "20011113T000000", "size": 1000},
            {"filename": "Gran Turismo 3.iso", "title": "Gran Turismo 3",
             "developer": "Polyphony", "releasedate": "20010428T000000", "size": 2000},
        ])
        target_root = build_custom_esde_tree(self.dir / "dst", "ps2", [
            # 같은 게임인데 이름이 다르다 - 앞쪽 두 티어로는 안 걸린다.
            {"filename": "MGS2 Sons of Liberty.iso", "title": "Metal Gear Solid 2 Sons of Liberty",
             "developer": "Konami", "releasedate": "20011113T000000", "size": 1500},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("Source", "es-de", str(source_root))["data"]["id"]
        self.dst = self.api.create_collection("Target", "es-de", str(target_root))["data"]["id"]
        for cid in (self.src, self.dst):
            scan(self.api, cid)
        self.api.archive_ingest(self.src)
        self.row = self.api.list_rows(self.dst, limit=50)["data"]["rows"][0]

    def tearDown(self):
        self.api.close()

    def _archive_id(self, filename):
        rows = self.api.archive_rows(limit=50)["data"]["rows"]
        return next(r["romIdentityId"] for r in rows if r["file"] == filename)

    def test_choosing_a_real_candidate_records_its_own_tier_and_score(self):
        """후보 목록에 보인 티어/점수가 그대로 남아야 한다.

        예전에는 확정할 때 classify()를 다시 불렀는데, classify()는 Exact/Normalized만
        판정하므로 Metadata/Heuristic 후보가 전부 "heuristic / 0.0점"으로 뭉개졌다 -
        사용자가 보고 고른 근거와 실제로 기록된 근거가 달라지는 셈이었다.
        """
        result = self.api.match_candidates(self.dst, self.row["romUid"])["data"]
        candidate = next(c for c in result["candidates"]
                         if c["filename"] == "Metal Gear Solid 2.iso")
        self.assertIn(candidate["tier"], (engine.TIER_METADATA, engine.TIER_HEURISTIC))
        self.assertGreater(candidate["score"], 0.0)

        applied = self.api.apply_match(self.dst, self.row["romUid"],
                                       candidate["romIdentityId"])["data"]
        self.assertEqual(applied["tier"], candidate["tier"])
        self.assertEqual(applied["score"], candidate["score"])
        self.assertFalse(applied["manual"])

    def test_an_identity_that_is_not_a_candidate_is_refused(self):
        unrelated = self._archive_id("Gran Turismo 3.iso")
        result = self.api.apply_match(self.dst, self.row["romUid"], unrelated)
        self.assertFalse(result["ok"])
        self.assertIn("후보 목록에 없는", result["error"])

    def test_forcing_it_is_possible_but_recorded_as_manual(self):
        unrelated = self._archive_id("Gran Turismo 3.iso")
        applied = self.api.apply_match(self.dst, self.row["romUid"], unrelated,
                                       manual=True)["data"]
        self.assertEqual(applied["tier"], engine.TIER_MANUAL)
        self.assertTrue(applied["manual"])
        self.assertEqual(applied["score"], 0.0,
                         "엔진이 근거를 못 댄 연결에 점수를 붙이면 안 된다")


if __name__ == "__main__":
    unittest.main()
