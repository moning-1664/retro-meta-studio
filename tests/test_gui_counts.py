"""좌측 네비게이션과 목록이 같은 것을 세는가 (Phase 7.13, GUI-02).

사용자가 실제 ES-DE 백업(메타데이터만 있고 ROM은 없는 상태)을 열었을 때 이렇게 나왔다.

    All        1,539
    각 System      0   ← 28개 System 전부

두 가지가 겹친 결과였다.

1. **세는 대상이 달랐다.** 네비게이션은 `system_stats.rom_count`(물리 ROM 파일 수)를,
   목록은 `count_rows()`(게임 수)를 썼다. ES-DE는 gamelist와 media만 있고 ROM이 없는
   항목을 정상적으로 가질 수 있으므로, 그런 Collection에서는 앞의 값이 전부 0이 된다.
2. **스캔이 끝나지 않았는데 끝난 것으로 보였다.** 스캔은 "커버 먼저, 나머지 나중"의
   2단계인데 단계마다 job이 새로 생긴다. 1단계 job이 끝나는 순간 화면은 완료로 알고
   목록을 그렸고, 2단계가 여전히 Cache를 쓰고 있어서 개수가 실행할 때마다 달랐다
   (실제 백업에서 1,539 / 1,533 / 1,519).
"""

import unittest

from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, temp_root, wait_idle, write_file


def metadata_only_tree(root):
    """gamelist와 media는 있는데 ROM 파일이 없는 트리 - ES-DE에서 정상인 상태."""
    build_custom_esde_tree(root, "ps2", [
        {"filename": "FFX.iso", "title": "Final Fantasy X", "rom": False},
        {"filename": "MGS2.iso", "title": "Metal Gear Solid 2", "rom": False},
    ])
    build_custom_esde_tree(root, "snes", [
        {"filename": "Zelda.sfc", "title": "Zelda", "rom": False},
    ])
    for system, stem in (("ps2", "FFX"), ("snes", "Zelda")):
        write_file(root / "downloaded_media" / system / "covers" / f"{stem}.png", b"c" * 20)
        write_file(root / "downloaded_media" / system / "videos" / f"{stem}.mp4", b"v" * 60)
    return root


class NavigationCountsMatchTheListTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_counts_")
        self.root = metadata_only_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("meta", "es-de", str(self.root))["data"]["id"]
        self._scan()

    def _scan(self):
        self.api.start_scan(self.cid, True)
        wait_idle(self.api)

    def _nav_counts(self):
        detail = self.api.collection_detail(self.cid)["data"]
        return {s["system"]: s["count"]
                for storage in detail["storages"] for s in storage["systems"]}

    def test_the_rows_are_there_at_all(self):
        """전제 확인 - ROM이 없어도 gamelist의 항목은 목록에 떠야 한다."""
        self.assertEqual(self.api.list_rows(self.cid, limit=50)["data"]["total"], 3)

    def test_each_system_shows_its_games_not_zero(self):
        """**이것이 사용자가 본 문제다.** 목록에는 1,539개인데 System은 전부 0이었다."""
        self.assertEqual(self._nav_counts(), {"ps2": 2, "snes": 1})

    def test_the_counts_add_up_to_the_total(self):
        total = self.api.list_rows(self.cid, limit=50)["data"]["total"]
        self.assertEqual(sum(self._nav_counts().values()), total)

    def test_a_system_filter_returns_what_the_navigation_promised(self):
        """네비게이션이 2개라고 했으면 눌렀을 때 2개가 나와야 한다."""
        for system, promised in self._nav_counts().items():
            rows = self.api.list_rows(self.cid, systems=[system], limit=50)["data"]
            self.assertEqual(rows["total"], promised, system)

    def test_roms_still_count_when_they_do_exist(self):
        """ROM이 있는 Collection에서도 같은 값이어야 한다 - 한쪽만 고치면 안 된다."""
        root = build_custom_esde_tree(self.dir / "withroms", "gba",
                                      [{"filename": "Metroid.gba", "title": "Metroid"}])
        cid = self.api.create_collection("roms", "es-de", str(root))["data"]["id"]
        self.api.start_scan(cid, True)
        wait_idle(self.api)
        detail = self.api.collection_detail(cid)["data"]
        counts = {s["system"]: s["count"]
                  for st in detail["storages"] for s in st["systems"]}
        self.assertEqual(counts, {"gba": 1})


class ScanReportsDoneOnlyWhenItIsDoneTests(unittest.TestCase):
    """스캔은 "커버 먼저, 나머지 나중"의 2단계다. **단계마다 job이 새로 생긴다.**

    1단계 job이 끝난 것을 스캔 완료로 읽으면, 2단계가 Cache를 쓰는 중에 목록을 그리게
    되어 개수가 실행할 때마다 달라진다. 그래서 결과에 후속 job id를 실어 보낸다.
    """

    def setUp(self):
        self.dir = temp_root("rms_phases_")
        self.root = metadata_only_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("meta", "es-de", str(self.root))["data"]["id"]

    def _follow(self, job_id):
        """화면이 하는 것과 같은 방식으로 끝까지 따라간다."""
        import time
        deadline = time.time() + 30
        while time.time() < deadline:
            data = self.api.get_job_progress(job_id)["data"]
            if not data.get("done"):
                time.sleep(0.02)
                continue
            follow = (data.get("result") or {}).get("followUpJobId")
            if follow:
                job_id = follow
                continue
            return data
        raise TimeoutError("스캔이 끝나지 않았다")

    def test_the_first_phase_announces_its_successor(self):
        """후속 job을 알려주지 않으면 화면은 따라갈 방법이 없다."""
        job = self.api.start_scan(self.cid, True)["data"]["jobId"]
        import time
        deadline = time.time() + 30
        while time.time() < deadline:
            data = self.api.get_job_progress(job)["data"]
            if data.get("done"):
                break
            time.sleep(0.02)
        self.assertTrue((data.get("result") or {}).get("followUpJobId"),
                        "1단계가 끝났는데 후속 job을 알려주지 않는다")

    def test_counts_are_stable_once_the_chain_finishes(self):
        """끝까지 따라간 뒤에는 몇 번을 다시 세도 같아야 한다."""
        counts = []
        for _ in range(3):
            job = self.api.start_scan(self.cid, True)["data"]["jobId"]
            self._follow(job)
            detail = self.api.collection_detail(self.cid)["data"]
            counts.append((self.api.list_rows(self.cid, limit=50)["data"]["total"],
                           detail["totalGames"],
                           tuple(sorted((s["system"], s["count"])
                                        for st in detail["storages"] for s in st["systems"]))))
        self.assertEqual(len(set(counts)), 1, f"스캔할 때마다 개수가 다르다: {counts}")

    def test_the_list_total_and_the_detail_total_agree(self):
        """같은 것을 세는 두 값이 다르면 둘 중 하나는 아직 쓰이는 중이다."""
        self._follow(self.api.start_scan(self.cid, True)["data"]["jobId"])
        detail = self.api.collection_detail(self.cid)["data"]
        self.assertEqual(detail["totalGames"],
                         self.api.list_rows(self.cid, limit=50)["data"]["total"])


if __name__ == "__main__":
    unittest.main()
