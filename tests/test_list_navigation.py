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


if __name__ == "__main__":
    unittest.main()
