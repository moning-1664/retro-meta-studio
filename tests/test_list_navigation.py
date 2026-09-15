"""목록 전체를 대상으로 하는 키보드 동작의 백엔드 - Ctrl+A(list_uids)와 영문키
점프(find_row_index).

목록은 가상 스크롤이라 화면에 그려진 행은 수십 개뿐이다. ui/stitch-v2-redesign은
그 행들만 뒤져서, 큰 목록에서는 뒤쪽으로 점프하거나 전체를 고를 수 없었다. 여기서는
두 기능이 **목록과 같은 정렬**로 전체를 본다는 것을 확인한다.
"""

import unittest

from bridge.api import Api
from tests.fixtures import build_esde_tree, temp_root, wait_job, write_file


class ListNavigationTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_nav_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def files(self, **query):
        rows = self.api.list_rows(self.cid, limit=1000, **query)["data"]["rows"]
        return [row["file"] for row in rows]

    def expected_index(self, prefix, after, files):
        for k in range(1, len(files) + 1):
            i = (after + k) % len(files)
            if files[i].lower().startswith(prefix):
                return i
        return -1

    # ---------------------------------------------------------------- Ctrl+A
    def test_list_uids_covers_the_whole_list_in_the_same_order(self):
        rows = self.api.list_rows(self.cid, limit=1000)["data"]["rows"]
        self.assertEqual(self.api.list_uids(self.cid)["data"], [r["romUid"] for r in rows])

    def test_list_uids_follows_the_filter(self):
        uids = self.api.list_uids(self.cid, search="metal")["data"]
        self.assertEqual(len(uids), 1)

    # ---------------------------------------------------------------- 영문키 점프
    def test_jump_finds_the_next_matching_row_in_list_order(self):
        files = self.files()
        for after in (-1, 0, 1, 2):
            self.assertEqual(self.api.find_row_index(self.cid, "m", after)["data"],
                             self.expected_index("m", after, files), after)

    def test_jump_wraps_around_to_the_top(self):
        files = self.files()
        last_m = max(i for i, f in enumerate(files) if f.lower().startswith("m"))
        first_m = min(i for i, f in enumerate(files) if f.lower().startswith("m"))
        self.assertEqual(self.api.find_row_index(self.cid, "m", last_m)["data"], first_m)

    def test_jump_uses_the_current_sort(self):
        files = self.files(order="filename", descending=True)
        self.assertEqual(
            self.api.find_row_index(self.cid, "f", -1, order="filename", descending=True)["data"],
            self.expected_index("f", -1, files))

    def test_no_match_is_minus_one(self):
        self.assertEqual(self.api.find_row_index(self.cid, "z", -1)["data"], -1)

    def test_like_wildcards_in_the_prefix_are_literal(self):
        """`_`는 파일명에 흔하다 - LIKE 와일드카드로 해석되면 아무 파일에나 걸린다."""
        self.assertEqual(self.api.find_row_index(self.cid, "_", -1)["data"], -1)
        write_file(self.root / "ps2" / "_Bonus.iso", b"b" * 10)
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])
        files = self.files()
        self.assertEqual(self.api.find_row_index(self.cid, "_", -1)["data"], files.index("_Bonus.iso"))


# ==========================================================================
# 우선 정렬 (실사용 피드백) - "모든상태/메타데이터 없음/미디어없음/ROM없음" 필터가
# currentQuery()에서 끝내 안 읽혀 실제로는 아무 것도 안 걸렀다. 그 자리를 필터가
# 아니라 **1차 정렬 기준**으로 바꾼다 - 있는 항목이 없는 항목보다 먼저 오고, 그
# 안에서는 기존 정렬이 그대로 2차 기준이다. list_rows/list_uids/find_row_index가
# 반드시 같은 순서를 내야 한다(가상 스크롤·Ctrl+A·영문키 점프가 어긋나면 안 된다).
class PrioritySortTests(unittest.TestCase):
    """build_esde_tree: FFX(ROM+media 있음) / MGS2(ROM 있음, media 없음) /
    MetadataOnly(ROM 없음, media 없음)."""

    def setUp(self):
        self.dir = temp_root("rms_priority_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def files(self, **query):
        rows = self.api.list_rows(self.cid, limit=1000, **query)["data"]["rows"]
        return [row["file"] for row in rows]

    def test_no_priority_behaves_exactly_like_before(self):
        self.assertEqual(self.files(), self.files(priority=None))

    def test_rom_priority_puts_the_missing_rom_last(self):
        files = self.files(priority="rom")
        self.assertEqual(files[-1], "MetadataOnly.iso")
        # 그 안에서는 기존 정렬(title)이 그대로다 - FFX/MGS2 둘 다 ROM이 있다.
        self.assertEqual(files[:2], ["FFX.iso", "MGS2.iso"])   # title_norm 기준

    def test_media_priority_puts_the_one_without_media_first_among_the_no_media_group(self):
        # media 있음: FFX. media 없음: MGS2, MetadataOnly. "있음"이 먼저 온다.
        files = self.files(priority="media")
        self.assertEqual(files[0], "FFX.iso")
        self.assertEqual(set(files[1:]), {"MGS2.iso", "MetadataOnly.iso"})

    def test_priority_does_not_hide_anything(self):
        """예전 상태 필터와의 결정적 차이 - 항목 수는 그대로다."""
        for priority in (None, "rom", "metadata", "media"):
            self.assertEqual(len(self.files(priority=priority)), 3, priority)

    def test_list_uids_matches_list_rows_order_under_priority(self):
        rows = self.api.list_rows(self.cid, limit=1000, priority="media")["data"]["rows"]
        self.assertEqual(self.api.list_uids(self.cid, priority="media")["data"],
                         [r["romUid"] for r in rows])

    def test_jump_uses_the_priority_order(self):
        files = self.files(priority="rom")
        after = self.api.find_row_index(self.cid, "m", -1, priority="rom")["data"]
        # "m"으로 시작하는 파일은 MGS2.iso와 MetadataOnly.iso 둘이다 - priority=rom
        # 정렬에서 먼저 나오는 쪽(ROM이 있는 MGS2)이 걸려야 한다.
        self.assertEqual(files[after], "MGS2.iso")


if __name__ == "__main__":
    unittest.main()
