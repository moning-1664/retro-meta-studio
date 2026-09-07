"""bridge/jobs.py 이식 검증.

원본(api.py)이 실제 크래시/race를 겪으며 얻은 동작들 - target 단위 직렬화,
scan 전역 직렬화, 대기 중 취소 시 busy target 해제 - 이 그대로 유지되는지 본다.
sleep으로 타이밍을 맞추지 않고 Event로 동기화한다.
"""

import threading
import unittest

from bridge.jobs import JobManager


def wait_done(manager, job_id, timeout=5.0):
    deadline = threading.Event()
    job = manager.get(job_id)
    for _ in range(int(timeout / 0.01)):
        if job.get("done"):
            return job
        deadline.wait(0.01)
    raise AssertionError(f"job이 시간 내에 끝나지 않았습니다: {job}")


class BasicJobTests(unittest.TestCase):
    def setUp(self):
        self.jm = JobManager()

    def test_result_and_progress_are_recorded(self):
        def fn(cb):
            cb(3, 10, "작업 중")
            return "done"

        job_id = self.jm.run(fn)
        job = wait_done(self.jm, job_id)
        self.assertEqual(job["result"], "done")
        self.assertEqual((job["current"], job["total"], job["label"]), (3, 10, "작업 중"))
        self.assertIsNone(job["error"])

    def test_exception_is_reported_not_raised(self):
        job_id = self.jm.run(lambda cb: (_ for _ in ()).throw(RuntimeError("boom")))
        job = wait_done(self.jm, job_id)
        self.assertEqual(job["error"], "boom")

    def test_cancel_stops_at_next_progress_call(self):
        started, may_finish = threading.Event(), threading.Event()

        def fn(cb):
            started.set()
            may_finish.wait(2.0)
            cb(1, 2, "여기서 취소 신호를 확인한다")
            return "should not reach"

        job_id = self.jm.run(fn)
        started.wait(2.0)
        self.jm.cancel(job_id)
        may_finish.set()

        job = wait_done(self.jm, job_id)
        self.assertTrue(job["cancelled"])
        self.assertIsNone(job["result"])


class JobIdTests(unittest.TestCase):
    """[회귀] job id는 반드시 유일해야 한다.

    원본은 `time.time_ns()`만으로 id를 만들었는데 Windows 시계 분해능(약 15.6ms)
    안에 만들어진 job들이 같은 id를 갖고 서로의 `_jobs` 항목을 덮어썼다. phased
    job은 한 phase가 끝나며 다음 phase를 즉시 만들기 때문에 특히 잘 부딪혔고,
    그 결과 진행률/결과/취소가 엉뚱한 job에 걸렸다.
    """

    def test_ids_are_unique_even_when_created_in_a_tight_loop(self):
        jm = JobManager()
        ids = {jm.run(lambda cb: None) for _ in range(200)}
        self.assertEqual(len(ids), 200)

    def test_phase_jobs_do_not_share_an_id(self):
        jm = JobManager()
        created = []
        job_id = jm.run_phased(
            ("col-1",), [("P1", lambda cb: "a"), ("P2", lambda cb: "b")],
            on_phase_job_created=created.append)
        wait_done(jm, job_id)
        for _ in range(200):
            if len(created) >= 2 and jm.get(created[1]).get("done"):
                break
            threading.Event().wait(0.01)
        self.assertEqual(len(set(created)), 2, f"phase job id가 충돌했습니다: {created}")
        self.assertEqual(jm.get(created[0])["result"], "a")
        self.assertEqual(jm.get(created[1])["result"], "b")


class HeavyJobSerializationTests(unittest.TestCase):
    def setUp(self):
        self.jm = JobManager()

    def _blocking(self, started, release, marker, order):
        def fn(cb):
            started.set()
            release.wait(3.0)
            order.append(marker)
            return marker

        return fn

    def test_same_target_jobs_are_serialized(self):
        order = []
        started1, release1 = threading.Event(), threading.Event()
        first = self.jm.run_heavy(self._blocking(started1, release1, "first", order), target_ids=("col-1",))
        started1.wait(2.0)

        second = self.jm.run_heavy(lambda cb: order.append("second") or "second", target_ids=("col-1",))
        # 첫 job이 아직 안 끝났으므로 두 번째는 큐에서 대기해야 한다.
        self.assertTrue(self.jm.get(second)["queued"])
        self.assertIn("대기 중", self.jm.get(second)["label"])

        release1.set()
        wait_done(self.jm, first)
        wait_done(self.jm, second)
        self.assertEqual(order, ["first", "second"])

    def test_different_targets_run_concurrently(self):
        started_a, started_b = threading.Event(), threading.Event()
        release = threading.Event()

        def make(started):
            def fn(cb):
                started.set()
                release.wait(3.0)
                return "ok"
            return fn

        job_a = self.jm.run_heavy(make(started_a), target_ids=("col-1",))
        job_b = self.jm.run_heavy(make(started_b), target_ids=("col-2",))

        self.assertTrue(started_a.wait(2.0))
        self.assertTrue(started_b.wait(2.0), "target이 겹치지 않으면 동시에 실행되어야 한다")
        release.set()
        wait_done(self.jm, job_a)
        wait_done(self.jm, job_b)

    def test_scan_jobs_serialize_even_across_targets(self):
        started, release = threading.Event(), threading.Event()

        def first(cb):
            started.set()
            release.wait(3.0)
            return "first"

        job1 = self.jm.run_heavy(first, target_ids=("col-1",), kind="scan")
        started.wait(2.0)
        job2 = self.jm.run_heavy(lambda cb: "second", target_ids=("col-2",), kind="scan")
        self.assertTrue(self.jm.get(job2)["queued"], "scan끼리는 target이 달라도 직렬화된다")

        release.set()
        wait_done(self.jm, job1)
        wait_done(self.jm, job2)


class PhasedJobTests(unittest.TestCase):
    def setUp(self):
        self.jm = JobManager()

    def test_phases_run_in_order_with_prefixed_labels(self):
        labels = []

        def phase(name):
            def fn(cb):
                cb(1, 1, name)
                return {name: 1}
            return fn

        def combine(acc, result):
            merged = dict(acc or {})
            merged.update(result)
            return merged

        job_id = self.jm.run_phased(
            ("col-1",), [("메타데이터", phase("a")), ("비디오", phase("b"))],
            combine_results=combine)

        job = wait_done(self.jm, job_id)
        # 마지막 phase는 새 job이므로 첫 job의 result는 1단계 것이다.
        self.assertEqual(job["result"], {"a": 1})
        labels.append(job["label"])
        self.assertTrue(labels[0].startswith("(1/2) 메타데이터:"), labels[0])

    def test_busy_target_released_after_last_phase(self):
        job_id = self.jm.run_phased(("col-1",), [("단일", lambda cb: "ok")])
        wait_done(self.jm, job_id)
        self.assertEqual(self.jm.busy_targets("col-1"), [])

    def test_busy_target_released_when_phase_fails(self):
        def boom(cb):
            raise RuntimeError("실패")

        job_id = self.jm.run_phased(("col-1",), [("실패단계", boom), ("안돎", lambda cb: "x")])
        wait_done(self.jm, job_id)
        self.assertEqual(self.jm.busy_targets("col-1"), [],
                         "phase 실패 시에도 busy target이 남으면 삭제/이름변경이 영원히 막힌다")

    def test_cancelling_queued_phase_job_releases_busy_target(self):
        started, release = threading.Event(), threading.Event()

        def blocker(cb):
            started.set()
            release.wait(3.0)
            return "blocked"

        blocking_job = self.jm.run_heavy(blocker, target_ids=("col-1",))
        started.wait(2.0)

        queued = self.jm.run_phased(("col-1",), [("대기", lambda cb: "never")])
        self.assertTrue(self.jm.get(queued)["queued"])
        self.assertEqual(self.jm.busy_targets("col-1"), ["col-1"])

        # 한 번도 실행되지 않은 채 취소되면 release()가 안 불리므로, cancel이 대신
        # 풀어줘야 한다.
        self.jm.cancel(queued)
        self.assertEqual(self.jm.busy_targets("col-1"), [])
        self.assertTrue(self.jm.get(queued)["cancelled"])

        release.set()
        wait_done(self.jm, blocking_job)


if __name__ == "__main__":
    unittest.main()
