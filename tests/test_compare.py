"""Compare 테스트 (스펙 §54-59).

이 파일이 지키는 것:
- 짝짓기는 **1:1**이다. 한쪽 항목이 상대 두 개에 동시에 붙지 않는다.
- 상대가 여럿이라 모호하면 짝짓지 않는다(§88) - 각자 "한쪽에만 있음"으로 남는다.
- Media 차이는 Conflict가 아니다. Conflict는 Metadata가 다른 경우다.
"""

import unittest

from app.compare import engine
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root


def entry(rom_uid, filename, *, system="ps2", title=None, size=1000, sha256=None,
          fields=None, media=None):
    return {"rom_uid": rom_uid, "system": system, "filename": filename,
            "title": title if title is not None else filename.rsplit(".", 1)[0],
            "size": size, "sha256": sha256, "present": 1,
            "fields": fields or {}, "media_types": media or []}


class CompareEngineTests(unittest.TestCase):
    def statuses(self, rows):
        return {r["file"]: r["status"] for r in rows}

    def test_identical_entries_are_same(self):
        left = [entry(1, "FFX.iso", fields={"name": "Final Fantasy X"})]
        right = [entry(9, "FFX.iso", fields={"name": "Final Fantasy X"})]
        rows = engine.compare(left, right)
        self.assertEqual(self.statuses(rows), {"FFX.iso": engine.STATUS_SAME})
        self.assertEqual(rows[0]["changedFields"], [])

    def test_different_metadata_is_a_conflict(self):
        left = [entry(1, "FFX.iso", fields={"name": "FFX", "genre": "RPG"})]
        right = [entry(9, "FFX.iso", fields={"name": "FFX", "genre": "JRPG"})]
        rows = engine.compare(left, right)
        self.assertEqual(rows[0]["status"], engine.STATUS_CONFLICT)
        self.assertEqual(rows[0]["changedFields"], ["genre"])

    def test_unmatched_entries_land_on_their_own_side(self):
        rows = engine.compare([entry(1, "OnlyLeft.iso")], [entry(9, "OnlyRight.iso")])
        self.assertEqual(self.statuses(rows),
                         {"OnlyLeft.iso": engine.STATUS_ONLY_A,
                          "OnlyRight.iso": engine.STATUS_ONLY_B})

    def test_same_name_different_size_still_pairs(self):
        """Compare의 짝짓기는 Match의 Exact보다 느슨하다.

        같은 이름의 다른 덤프는 "양쪽에 각각 있음"이 아니라 **짝지어서 차이를
        보여줘야** 한다 - 그 차이를 보려고 Compare를 여는 것이기 때문이다.
        """
        left = [entry(1, "FFX.iso", size=100)]
        right = [entry(9, "FFX.iso", size=200)]
        rows = engine.compare(left, right)
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["left"])
        self.assertIsNotNone(rows[0]["right"])

    def test_media_difference_is_not_a_conflict(self):
        left = [entry(1, "FFX.iso", media=["covers"])]
        right = [entry(9, "FFX.iso", media=["covers", "videos"])]
        rows = engine.compare(left, right)
        self.assertEqual(rows[0]["status"], engine.STATUS_SAME)
        self.assertTrue(rows[0]["mediaDiff"])

    def test_pairing_is_one_to_one(self):
        """왼쪽 하나가 오른쪽 둘에 동시에 붙으면 개수가 맞지 않게 된다."""
        left = [entry(1, "FFX.iso")]
        right = [entry(9, "FFX.iso"), entry(10, "FFX.iso")]
        rows = engine.compare(left, right)
        paired = [r for r in rows if r["left"] and r["right"]]
        self.assertEqual(len(paired), 1)
        self.assertEqual(len([r for r in rows if r["status"] == engine.STATUS_ONLY_B]), 1)

    def test_ambiguous_normalized_candidates_are_left_unpaired(self):
        """정규화하면 같아지는 상대가 둘이면 어느 쪽인지 알 수 없다 - 짝짓지 않는다."""
        left = [entry(1, "Game.iso", title="Game")]
        right = [entry(9, "Game (USA).iso", title="Game"),
                 entry(10, "Game (Europe).iso", title="Game")]
        rows = engine.compare(left, right)
        self.assertEqual(self.statuses(rows), {
            "Game.iso": engine.STATUS_ONLY_A,
            "Game (USA).iso": engine.STATUS_ONLY_B,
            "Game (Europe).iso": engine.STATUS_ONLY_B,
        })

    def test_a_unique_normalized_candidate_does_pair(self):
        left = [entry(1, "Game.iso", title="Game")]
        right = [entry(9, "Game (USA).iso", title="Game")]
        rows = engine.compare(left, right)
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["right"])

    def test_different_systems_never_pair(self):
        left = [entry(1, "Game.iso", system="ps2")]
        right = [entry(9, "Game.iso", system="snes")]
        rows = engine.compare(left, right)
        self.assertEqual(len(rows), 2)

    def test_summary_and_filters(self):
        left = [entry(1, "Same.iso", fields={"name": "A"}),
                entry(2, "Conflict.iso", fields={"name": "A"}),
                entry(3, "OnlyLeft.iso"),
                entry(4, "MediaOnly.iso", media=["covers"])]
        right = [entry(9, "Same.iso", fields={"name": "A"}),
                 entry(10, "Conflict.iso", fields={"name": "B"}),
                 entry(11, "OnlyRight.iso"),
                 entry(12, "MediaOnly.iso", media=[])]
        rows = engine.compare(left, right)
        counts = engine.summarize(rows)
        self.assertEqual(counts["all"], 5)
        self.assertEqual(counts[engine.STATUS_SAME], 2)      # Same, MediaOnly
        self.assertEqual(counts[engine.STATUS_CONFLICT], 1)
        self.assertEqual(counts[engine.STATUS_ONLY_A], 1)
        self.assertEqual(counts[engine.STATUS_ONLY_B], 1)
        self.assertEqual(counts["media"], 1)

        self.assertEqual(len(engine.filter_rows(rows, "conflict")), 1)
        self.assertEqual(len(engine.filter_rows(rows, "media")), 1)
        self.assertEqual(len(engine.filter_rows(rows, "all")), 5)
        self.assertEqual(len(engine.filter_rows(rows, None)), 5)


class CompareApiTests(unittest.TestCase):
    """실제 Collection 두 개를 스캔해서 API 경로로 확인한다."""

    def setUp(self):
        self.dir = temp_root("rms_compare_")
        base_root = build_custom_esde_tree(self.dir / "base", "ps2", [
            {"filename": "Same.iso", "title": "Same Game", "genre": "RPG", "size": 100},
            {"filename": "Conflict.iso", "title": "Conflict Game", "genre": "RPG", "size": 200},
            {"filename": "OnlyBase.iso", "title": "Only Base", "size": 300},
        ])
        other_root = build_custom_esde_tree(self.dir / "other", "ps2", [
            {"filename": "Same.iso", "title": "Same Game", "genre": "RPG", "size": 100},
            {"filename": "Conflict.iso", "title": "Conflict Game", "genre": "Action", "size": 200},
            {"filename": "OnlyOther.iso", "title": "Only Other", "size": 400},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.base = self.api.create_collection("Master", "es-de", str(base_root))["data"]["id"]
        self.other = self.api.create_collection("Android", "es-de", str(other_root))["data"]["id"]
        for cid in (self.base, self.other):
            scan(self.api, cid)

    def tearDown(self):
        self.api.close()

    def test_compare_is_off_until_started(self):
        self.assertIsNone(self.api.compare_state()["data"])
        self.assertFalse(self.api.compare_rows()["ok"])

    def test_starting_compare_reports_both_names_and_counts(self):
        state = self.api.start_compare(self.base, self.other)["data"]
        self.assertEqual(state["baseName"], "Master")
        self.assertEqual(state["otherName"], "Android")
        counts = state["counts"]
        self.assertEqual(counts["all"], 4)
        self.assertEqual(counts["same"], 1)
        self.assertEqual(counts["conflict"], 1)
        self.assertEqual(counts["only_a"], 1)
        self.assertEqual(counts["only_b"], 1)

    def test_comparing_a_collection_with_itself_is_refused(self):
        result = self.api.start_compare(self.base, self.base)
        self.assertFalse(result["ok"])

    def test_rows_can_be_filtered_by_status(self):
        self.api.start_compare(self.base, self.other)
        conflict = self.api.compare_rows(status="conflict")["data"]
        self.assertEqual(conflict["total"], 1)
        self.assertEqual(conflict["rows"][0]["file"], "Conflict.iso")
        self.assertEqual(conflict["rows"][0]["changedFields"], ["genre"])

        only_b = self.api.compare_rows(status="only_b")["data"]
        self.assertEqual(only_b["rows"][0]["file"], "OnlyOther.iso")

    def test_rows_can_be_searched(self):
        self.api.start_compare(self.base, self.other)
        found = self.api.compare_rows(search="onlybase")["data"]
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["rows"][0]["status"], "only_a")

    def test_detail_puts_both_sides_side_by_side(self):
        self.api.start_compare(self.base, self.other)
        detail = self.api.compare_detail("ps2|Conflict.iso")["data"]
        self.assertEqual(detail["baseName"], "Master")
        self.assertEqual(detail["left"]["fields"]["genre"], "RPG")
        self.assertEqual(detail["right"]["fields"]["genre"], "Action")
        self.assertEqual(detail["changedFields"], ["genre"])

    def test_detail_of_a_one_sided_row_has_a_null_side(self):
        self.api.start_compare(self.base, self.other)
        detail = self.api.compare_detail("ps2|OnlyBase.iso")["data"]
        self.assertIsNotNone(detail["left"])
        self.assertIsNone(detail["right"])

    def test_exiting_clears_the_mode(self):
        self.api.start_compare(self.base, self.other)
        self.assertTrue(self.api.exit_compare()["data"])
        self.assertIsNone(self.api.compare_state()["data"])


if __name__ == "__main__":
    unittest.main()
