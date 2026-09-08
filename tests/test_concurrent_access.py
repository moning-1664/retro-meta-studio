"""한 연결을 여러 스레드가 쓸 때 (Phase 7.14, GUI-04).

사용자가 "Archive에 수집"을 눌렀을 때 이렇게 나왔다.

    Cannot commit. No transaction to Active
    (그런데 화면에는 완료라고 표시됨)

재현해 보니 같은 원인에서 여러 얼굴이 나온다.

    sqlite3.InterfaceError: bad parameter or other API misuse
    TypeError: the JSON object must be str ... not NoneType
    Cannot commit - no transaction is active

전부 **하나의 SQLite 연결을 두 스레드가 동시에 만지는** 증상이다. Job 워커가 스캔으로
Cache를 쓰는 동안 사용자가 Archive 수집을 누르는 것은 지극히 정상적인 사용인데,
그때 커서와 트랜잭션 상태가 뒤섞였다.

**이것은 UI 문제가 아니라 데이터 안전 문제다.** 트랜잭션 상태가 깨진 채로 쓰기가
이어지면 무엇이 저장됐는지 알 수 없다.
"""

import threading
import time
import unittest

from app.store.sqlite import Migration, connect, transaction
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, temp_root, write_file


def _finish_scan(api, job_id, timeout=60.0):
    """단계마다 job이 새로 생기므로 끝까지 따라간다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = api.get_job_progress(job_id)["data"]
        if not data.get("done"):
            time.sleep(0.02)
            continue
        follow = (data.get("result") or {}).get("followUpJobId")
        if follow:
            job_id = follow
            continue
        return data
    raise TimeoutError("스캔이 끝나지 않았다")


class SerializedConnectionTests(unittest.TestCase):
    """연결 자체가 직렬화되는가. 호출부를 고치지 않고 모든 경로를 덮기 위한 것이다."""

    def setUp(self):
        self.dir = temp_root("rms_conn_")
        self.conn = connect(self.dir / "t.db", migrations=[Migration(
            1, ("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER NOT NULL)",))])
        self.addCleanup(self.conn.close)

    def test_the_connection_exposes_a_lock(self):
        """`transaction()`이 트랜잭션 전체를 한 스레드에 묶으려면 락이 필요하다."""
        self.assertIsNotNone(getattr(self.conn, "lock", None))

    def test_rows_are_read_before_the_lock_is_released(self):
        """커서를 그대로 돌려주면 호출부가 락 밖에서 행을 당겨오게 된다."""
        with transaction(self.conn):
            self.conn.execute("INSERT INTO t (v) VALUES (1)")
            self.conn.execute("INSERT INTO t (v) VALUES (2)")
        rows = self.conn.execute("SELECT v FROM t ORDER BY v")
        self.assertEqual([r["v"] for r in rows], [1, 2])

    def test_lastrowid_still_works(self):
        with transaction(self.conn):
            cur = self.conn.execute("INSERT INTO t (v) VALUES (7)")
            self.assertGreater(cur.lastrowid, 0)

    def test_fetchone_still_works(self):
        with transaction(self.conn):
            self.conn.execute("INSERT INTO t (v) VALUES (9)")
        row = self.conn.execute("SELECT COUNT(*) AS n FROM t").fetchone()
        self.assertEqual(row["n"], 1)

    def test_concurrent_writers_do_not_corrupt_the_transaction_state(self):
        """**이것이 사용자가 본 오류다.** 락이 없으면 커밋할 트랜잭션이 사라진다."""
        errors = []

        def writer(base):
            try:
                for i in range(40):
                    with transaction(self.conn):
                        self.conn.execute("INSERT INTO t (v) VALUES (?)", (base + i,))
            except Exception as exc:                      # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=writer, args=(n * 1000,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], "동시 쓰기에서 연결이 깨졌다")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM t").fetchone()["n"], 160,
                         "쓰기가 유실됐다")

    def test_readers_and_writers_can_run_together(self):
        """읽기도 같은 연결을 만진다 - 실제로 `get_row`가 여기서 깨졌다."""
        with transaction(self.conn):
            for i in range(50):
                self.conn.execute("INSERT INTO t (v) VALUES (?)", (i,))
        errors = []

        def reader():
            try:
                for _ in range(60):
                    list(self.conn.execute("SELECT v FROM t ORDER BY v"))
            except Exception as exc:                      # noqa: BLE001
                errors.append(f"read {type(exc).__name__}: {exc}")

        def writer():
            try:
                for i in range(60):
                    with transaction(self.conn):
                        self.conn.execute("INSERT INTO t (v) VALUES (?)", (900 + i,))
            except Exception as exc:                      # noqa: BLE001
                errors.append(f"write {type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class ExportDuringScanTests(unittest.TestCase):
    """실제 사용 흐름: 스캔이 도는 중에 Archive 수집을 누른다."""

    def setUp(self):
        self.dir = temp_root("rms_expconc_")
        self.root = self.dir / "esde"
        for system in ("ps2", "snes"):
            build_custom_esde_tree(self.root, system, [
                {"filename": f"G{i}.iso", "title": f"Game {i}"} for i in range(40)])
            write_file(self.root / "downloaded_media" / system / "covers" / "G0.png", b"c" * 30)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        _finish_scan(self.api, self.api.start_scan(self.cid, True)["data"]["jobId"])

    def test_a_quiet_export_succeeds_and_reports_media(self):
        """전제 확인 - 조용한 상황에서는 잘 된다."""
        result = self.api.archive_ingest(self.cid)
        self.assertTrue(result["ok"], result.get("error"))
        rows = self.api.archive_rows(limit=500)["data"]["rows"]
        self.assertTrue(any(r["hasMedia"] for r in rows),
                        "Archive에 media를 저장했는데 목록이 없다고 말한다")

    def test_exporting_while_a_scan_runs_does_not_break(self):
        """**사용자가 실제로 한 동작이다.** 오류가 나면 안 되고, 나면 숨기지도 않는다."""
        failures = []

        def export(tag):
            result = self.api.archive_ingest(self.cid)
            if not result["ok"]:
                failures.append(f"[{tag}] {result.get('error')}")

        self.api.start_scan(self.cid, True)
        threads = [threading.Thread(target=export, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(failures, [], "스캔 중 Export가 깨졌다")

    def test_the_reported_result_matches_what_the_archive_holds(self):
        """«실패했는데 화면은 완료»가 되지 않으려면 보고와 실제가 같아야 한다."""
        data = self.api.archive_ingest(self.cid)["data"]
        total = self.api.archive_rows(limit=1)["data"]["total"]
        self.assertEqual(data["ingested"], total,
                         "수집했다고 보고한 개수와 Archive에 있는 개수가 다르다")


if __name__ == "__main__":
    unittest.main()
