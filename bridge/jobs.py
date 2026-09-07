"""
bridge/jobs.py
===============
백그라운드 Job 실행/진행률/취소 관리.

RetroGameManager의 `api.py`에서 이식했다. 원본은 Api 클래스에 섞여 있었지만
동작 자체는 실제 크래시("Local1 스캔 중 Local2로 이동" -> 앱 강제종료)와 여러
race를 겪으며 다듬어진 것이라 그대로 보존한다. 달라진 점은 두 가지뿐이다.

1. Api/DB에 대한 의존을 끊고 독립 클래스(JobManager)로 만들었다. 예전의
   `mutates_db`(MasterDB 쓰기 직렬화)는 `mutates_state`로 일반화했고, 잠금은
   JobManager가 소유한 RLock을 쓴다.
2. target_ids가 예전엔 Local id/"masterdb" 였지만 이제 Collection id다.

핵심 규칙은 그대로다:
- heavy job은 target_ids가 겹치는 것끼리만 직렬화한다(겹치지 않으면 동시 실행).
- kind="scan"끼리는 target과 무관하게 항상 전역 직렬화한다. 이건 논리적 데이터
  충돌이 아니라 실제 크래시 재현 조건이었기 때문이다.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class JobCancelled(Exception):
    """사용자가 취소를 요청했을 때 progress_cb가 던지는 내부 신호."""


class JobManager:
    JOB_TTL_SECONDS = 600

    def __init__(self):
        self._jobs = {}
        self._write_lock = threading.RLock()
        self._id_lock = threading.Lock()
        self._next_id = 0

        # heavy job 큐: [{"job_id","fn","mutates_state","target_ids": frozenset,"kind"}, ...]
        self._heavy_queue = []
        self._heavy_lock = threading.Lock()
        self._heavy_running = {}  # job_id -> {"target_ids","kind"}

        # busy target: phased job이 1단계 시작 전부터 마지막 단계가 끝날 때까지
        # 잡아둔다. 그 사이 삭제/이름변경이 끼어들면 방금 복사한 파일과 어긋난다.
        self._busy_targets = set()
        self._busy_kind = {}
        self._busy_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def get(self, job_id):
        return self._jobs.get(job_id)

    def busy_targets(self, *target_ids):
        """target_ids 중 지금 busy인 것만 돌려준다."""
        with self._busy_lock:
            return [t for t in target_ids if t and t in self._busy_targets]

    def busy_kind(self, target_id):
        with self._busy_lock:
            return self._busy_kind.get(target_id) if target_id in self._busy_targets else None

    @contextmanager
    def write_lock(self):
        with self._write_lock:
            yield

    def _new_job_id(self) -> str:
        """[버그 수정] 원본은 `f"job_{time.time_ns()}"`를 썼는데, Windows의 시스템
        시계 분해능이 약 15.6ms라 그 안에 만들어진 두 job이 **같은 id를 갖는다**.
        그러면 뒤에 만든 job이 앞 job의 `_jobs` 항목을 통째로 덮어써서, 진행률이
        엉뚱한 job을 가리키고 결과가 사라지며 취소도 다른 job에 걸린다.

        phased job은 한 phase가 끝나면서 다음 phase를 곧바로 만들기 때문에 이
        충돌이 특히 잘 난다 - 원본 저장소에서 phase label 테스트와 job 직렬화
        테스트가 간헐적으로 실패하던 것이 바로 이 증상이었다.
        """
        with self._id_lock:
            self._next_id += 1
            return f"job_{time.time_ns()}_{self._next_id}"

    def _prune(self):
        now = time.time()
        stale = [jid for jid, job in self._jobs.items()
                 if job.get("done") and (now - job.get("done_at", now)) > self.JOB_TTL_SECONDS]
        for jid in stale:
            del self._jobs[jid]

    # ------------------------------------------------------------------
    # 실행
    # ------------------------------------------------------------------
    def run(self, fn, mutates_state=False):
        """fn(progress_cb)를 백그라운드에서 실행하고 job_id를 즉시 반환한다.

        서로 겹쳐도 안전한 job(파일시스템을 Collection 단위로 무겁게 건드리지 않는
        작업)에만 쓴다. Scan/Import/Export/Apply는 run_heavy()를 써야 한다.
        """
        self._prune()
        job_id = self._new_job_id()
        self._jobs[job_id] = {"current": 0, "total": 1, "label": "", "done": False, "result": None,
                              "error": None, "cancel_requested": False, "cancelled": False}
        self._start_worker(job_id, fn, mutates_state)
        return job_id

    def run_heavy(self, fn, *, mutates_state=False, target_ids=(), kind="other", on_created=None):
        """파일시스템을 오래 건드리는 job. target_ids가 겹치는 job끼리만 직렬화된다.

        on_created(job_id): 큐에 들어가기 전(=worker thread가 생기기 전)에 동기
        호출된다. 호출자가 "이 job이 진행 중"이라고 외부에 기록해야 할 때, job_id를
        받은 뒤에 기록하면 늦다 - 아주 빠른 job은 그 사이 이미 끝나버려서 "끝난 job을
        진행 중으로 잘못 등록"하는 race가 생긴다.
        """
        self._prune()
        job_id = self._new_job_id()
        self._jobs[job_id] = {"current": 0, "total": 1, "label": "대기 중", "done": False, "result": None,
                              "error": None, "cancel_requested": False, "cancelled": False, "queued": True}
        if on_created:
            on_created(job_id)
        entry = {"job_id": job_id, "fn": fn, "mutates_state": mutates_state,
                 "target_ids": frozenset(t for t in target_ids if t), "kind": kind}
        with self._heavy_lock:
            self._heavy_queue.append(entry)
            to_start = self._admit_locked()
        self._start_admitted(to_start)
        return job_id

    def run_phased(self, target_ids, phases, *, mutates_state=True, kind="other",
                   combine_results=None, attach_followup_job_id=False, on_phase_job_created=None):
        """phases: [(label, fn), ...]를 순서대로 이어서 실행한다.

        앞 phase가 성공해야 다음이 시작되고, 어느 하나가 실패하면 거기서 멈춘다.
        target_ids는 1단계 시작 전부터 마지막 단계가 끝날 때까지 busy로 잡아둔다.
        각 phase의 progress label 앞에는 "(i/N) label: "이 자동으로 붙어서, 사용자
        눈에는 진행률 바 하나가 순서대로 단계를 넘어가는 것처럼 보인다.

        combine_results(accumulated, phase_result) -> merged: 주지 않으면 마지막
        phase의 결과만 최종 result가 된다. 여러 phase의 합계를 사용자에게 보여줘야
        하면 반드시 넘겨야 한다 - 안 그러면 앞 단계에서 처리한 개수가 통째로
        사라진 숫자가 표시된다.
        """
        n = len(phases)

        def release():
            with self._busy_lock:
                for t in target_ids:
                    self._busy_targets.discard(t)
                    self._busy_kind.pop(t, None)

        def make_runner(index, accumulated):
            label, fn = phases[index]

            def run(cb):
                def prefixed_cb(current, total, item_label):
                    cb(current, total, f"({index + 1}/{n}) {label}: {item_label}")

                try:
                    result = fn(prefixed_cb)
                except Exception:
                    release()
                    raise
                combined = combine_results(accumulated, result) if combine_results else result
                if index + 1 < n:
                    next_job_id = self.run_heavy(
                        make_runner(index + 1, combined), mutates_state=mutates_state,
                        target_ids=target_ids, kind=kind, on_created=on_phase_job_created)
                    if attach_followup_job_id and isinstance(result, dict):
                        result = {**result, "followUpJobId": next_job_id, "partial": True}
                    return result
                release()
                return combined

            return run

        with self._busy_lock:
            for t in target_ids:
                self._busy_targets.add(t)
                self._busy_kind[t] = kind
        return self.run_heavy(make_runner(0, None), mutates_state=mutates_state,
                              target_ids=target_ids, kind=kind, on_created=on_phase_job_created)

    # ------------------------------------------------------------------
    # 큐 관리
    # ------------------------------------------------------------------
    def _admit_locked(self):
        """_heavy_lock을 잡은 상태에서만 호출한다. 큐를 순서대로 훑으면서 "실행 중인
        job들 + 이번에 허용하기로 한 job들"과 안 부딪히는 job을 전부 허용한다
        (FIFO를 최대한 존중하되, 뒤에 있어도 안 겹치면 먼저 허용됨).

        스레드 생성 자체는 락 안에서 하지 않는다 - 허용된 목록만 돌려주고 실제
        실행은 락을 놓은 뒤 _start_admitted()가 한다.
        """
        locked = set()
        scan_running = False
        for info in self._heavy_running.values():
            locked |= info["target_ids"]
            scan_running = scan_running or info["kind"] == "scan"

        remaining, to_start = [], []
        for entry in self._heavy_queue:
            blocked = bool(entry["target_ids"] & locked) or (entry["kind"] == "scan" and scan_running)
            if blocked:
                remaining.append(entry)
                continue
            to_start.append(entry)
            locked |= entry["target_ids"]
            if entry["kind"] == "scan":
                scan_running = True
            self._heavy_running[entry["job_id"]] = {"target_ids": entry["target_ids"], "kind": entry["kind"]}
        self._heavy_queue = remaining
        self._relabel_queue_locked()
        return to_start

    def _relabel_queue_locked(self):
        for i, entry in enumerate(self._heavy_queue):
            job = self._jobs.get(entry["job_id"])
            if job is not None:
                job["label"] = f"대기 중 (앞에서 막고 있는 작업 {i + 1}개)" if i == 0 else f"대기 중 (앞에 {i}개)"

    def _start_admitted(self, entries):
        for entry in entries:
            job_id = entry["job_id"]
            self._jobs[job_id]["queued"] = False

            def on_finish(job_id=job_id):
                with self._heavy_lock:
                    self._heavy_running.pop(job_id, None)
                    to_start = self._admit_locked()
                self._start_admitted(to_start)

            self._start_worker(job_id, entry["fn"], entry["mutates_state"], on_finish=on_finish)

    def _start_worker(self, job_id, fn, mutates_state, on_finish=None):
        def progress_cb(current, total, label):
            job = self._jobs[job_id]
            job.update({"current": current, "total": max(1, total), "label": str(label)})
            if job["cancel_requested"]:
                raise JobCancelled()

        def worker():
            try:
                if mutates_state:
                    with self._write_lock:
                        result = fn(progress_cb)
                else:
                    result = fn(progress_cb)
                self._jobs[job_id]["result"] = result
            except JobCancelled:
                self._jobs[job_id]["error"] = "취소되었습니다."
                self._jobs[job_id]["cancelled"] = True
            except Exception as e:  # noqa: BLE001 - job 실패는 UI로 보고되어야 한다
                self._jobs[job_id]["error"] = str(e)
            finally:
                self._jobs[job_id]["done"] = True
                # 완료 시각을 남겨야 _prune()이 오래된 job의 result를 정리할 수 있다.
                # Scan 결과는 게임이 수천 개면 상당히 크고, 다시 조회할 사람이 없는데도
                # 무기한 남아 있으면 메모리가 계속 누적된다.
                self._jobs[job_id]["done_at"] = time.time()
                if on_finish:
                    on_finish()

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 종료
    # ------------------------------------------------------------------
    def active_jobs(self) -> list[str]:
        return [jid for jid, job in self._jobs.items() if not job.get("done")]

    def wait_idle(self, timeout=10.0) -> bool:
        """진행 중인 job이 하나도 없을 때까지 기다린다. 시간 안에 못 끝내면 False."""
        waiter = threading.Event()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.active_jobs():
                return True
            waiter.wait(0.02)
        return not self.active_jobs()

    def shutdown(self, timeout=5.0) -> bool:
        """진행 중인 job에 취소를 요청하고 끝날 때까지 기다린다.

        **DB 연결을 닫기 전에 반드시 호출해야 한다.** 워커 스레드가 쓰고 있는 sqlite
        연결을 닫으면 프로세스가 segfault로 죽는다(실제로 재현했다). 취소는
        progress_cb 지점에서 협조적으로 일어나므로, 시간 안에 못 멈추는 job이 있으면
        False를 돌려준다 - 그 경우 호출자는 연결을 닫지 말고 그냥 프로세스를
        끝내야 한다.
        """
        for job_id in self.active_jobs():
            self.cancel(job_id)
        return self.wait_idle(timeout)

    # ------------------------------------------------------------------
    # 취소
    # ------------------------------------------------------------------
    def cancel(self, job_id):
        """진행 중인 job에 취소를 요청한다. Python 스레드는 강제 종료할 수 없으므로
        progress_cb가 다음에 불리는 지점에서 협조적으로 멈춘다.

        아직 큐에서 대기 중인 job은 progress_cb가 한 번도 안 불릴 수 있으므로 큐에서
        바로 빼서 즉시 취소 처리한다 - 자기 차례를 기다렸다가 그제서야 취소되는
        낭비를 없앤다.
        """
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job["done"]:
            return True
        if not job.get("queued"):
            job["cancel_requested"] = True
            return True

        with self._heavy_lock:
            cancelled = next((e for e in self._heavy_queue if e["job_id"] == job_id), None)
            self._heavy_queue = [e for e in self._heavy_queue if e["job_id"] != job_id]
            # 여기서 뺀 job은 애초에 target을 하나도 안 잡고 있었으므로(실행된 적 없음)
            # 다른 대기 job을 새로 허용할 여지가 생기지 않는다 - _admit_locked() 재호출 불필요.
            self._relabel_queue_locked()

        # run_phased()는 phase 0이 시작되기도 전에 busy_targets를 예약해둔다. queued
        # 상태에서 취소되면 fn 자체가 한 번도 안 불려서 release()도 안 불리고, 그
        # target이 영원히 busy로 남아 삭제/이름변경이 계속 막힌다 - 여기서 풀어준다.
        if cancelled is not None and cancelled.get("target_ids"):
            with self._busy_lock:
                for t in cancelled["target_ids"]:
                    self._busy_targets.discard(t)
                    self._busy_kind.pop(t, None)

        job["cancelled"] = True
        job["error"] = "취소되었습니다."
        job["done"] = True
        job["done_at"] = time.time()
        return True
