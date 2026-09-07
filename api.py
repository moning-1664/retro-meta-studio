"""
api.py
=======
GUI(웹 프론트엔드) <-> 기존 Python 백엔드를 잇는 pywebview Api 브릿지.

이 파일은 새로운 비즈니스 로직을 만들지 않는다 - 전부 이미 테스트된 기존 모듈
(config.py, db.py, import_engine.py, export_engine.py, cleanup_engine.py,
backup_engine.py)을 그대로 호출하고, 결과를 JS가 다루기 쉬운 JSON 형태로만 변환한다.

pywebview는 JS <-> Python 통신에 JSON 직렬화를 사용하므로 한글을 포함한 모든
문자열은 UTF-8로 안전하게 왕복한다 (파일 I/O 쪽은 db.py/config.py가 이미
전부 encoding="utf-8"을 명시하고 있음 - 이 파일에서 별도 처리 불필요).

[현재 GUI 기준 스코프] 지금 완성된 웹 GUI에 실제로 노출된 기능만 연결한다.
Core 설정 / ScreenScraper 연동 / RetroArch Export / 시스템 이름 매핑 / CSV / 버전 일괄정리는
이미 존재하는 안 쓰이는 백엔드 기능이지만 현재 GUI 화면에는 없으므로 이번엔 연결하지 않는다
(추후 해당 화면을 GUI에 추가하면 그때 연결).

[미구현으로 남겨둔 것] 다이지쇼(Daijishō) Import/Export는 여전히 실제 폴더 구조를
몰라 importers/daijisho.py, exporters/daijisho.py가 NotImplementedError를 낸다.
이 API 레이어는 그 예외를 잡아 프론트엔드가 명확한 에러로 보여줄 수 있게 전달한다.
"""

import base64
import copy
import time
import json
from contextlib import contextmanager
from datetime import datetime
import shutil
import threading
import queue
import traceback
from pathlib import Path
from collections import OrderedDict

from database import SQLiteRepository
from database.shadow import ShadowConsistencyChecker

import config as cfgmod
import db as dbmod
import disk_utils
import similar_rom
from importers.scan import scan_local, detect_local_structure
from import_engine import import_local_to_masterdb
from export_engine import export_masterdb_to_local, copy_local_to_local
import compare_engine as cmp_engine
from cleanup_engine import reset_metadata, orphan_cleanup, _HANDLERS as _CLEANUP_HANDLERS
from backup_engine import create_backup, list_backups, restore_backup

# GUI에 표시되는 Frontend 라벨(표시용 대문자/고유명사) -> 백엔드 내부 키(config.SUPPORTED_FRONTENDS)
GUI_FRONTEND_TO_INTERNAL = {
    "ES-DE": "es-de",
    "EmulationStation": "emulationstation",
    "Pegasus": "pegasus",
    "LaunchBox": "launchbox",
    "Daijishō": "daijisho",
}

# GUI의 대문자 표시 라벨 <-> db.py 스키마의 소문자 media 키 매핑
# [신규] Marquees/Videos 추가 (db.py 스키마는 이미 지원하고 있었음 - API 연결만 누락)
MEDIA_TYPE_MAP = {"3DBoxes": "3dboxes", "Covers": "covers", "Miximages": "miximages", "Screenshots": "screenshots", "Wheel": "wheel", "Marquees": "marquees", "Videos": "videos"}
MEDIA_TYPE_MAP_REV = {v: k for k, v in MEDIA_TYPE_MAP.items()}

# [신규] "media가 전부 있다"고 판단할 때 기준이 되는 타입 집합 (video 제외 - 사용자 명시 요청)
NON_VIDEO_MEDIA_TYPES = {"covers", "screenshots", "miximages", "wheel", "marquees"}


def _ok(data=None):
    return {"ok": True, "data": data}


def _err(message):
    return {"ok": False, "error": str(message)}


class _JobCancelled(Exception):
    """[신규] 사용자가 진행 중인 job(예: Local 스캔) 취소를 요청했을 때 progress_cb가
    던지는 내부 신호용 예외. 워커 스레드의 try/except에서만 잡아서 처리한다."""
    pass


class Api:
    """pywebview의 js_api로 등록되는 클래스. 모든 public 메서드가 JS에서
    `window.pywebview.api.<method>(...)`로 호출 가능해진다."""

    # [버그 수정] _sha256_queue는 PriorityQueue라 heapq가 항목끼리 비교한다.
    # 예전엔 종료 신호로 그냥 None을 넣었는데, 큐 안에 실제 작업 튜플
    # (priority, seq, system, filename, path)과 None이 섞이면 heapq가 둘을
    # 비교하려다가 "'<' not supported between instances of 'NoneType' and
    # 'tuple'" TypeError를 던진다 - 이게 _sha256_worker_loop()의 while 루프
    # 밖(즉 try/except Exception으로 감싸지 않은 queue.get() 호출 자체)에서
    # 터지면 워커 스레드 전체가 조용히 죽는다(실제로 반복 테스트 중 재현/확인).
    # 종료 신호도 항상 같은 모양의 5-튜플로 만들어서 이런 이종 비교 자체가
    # 아예 일어나지 않게 한다 - system이 None인 걸로 종료 신호를 구분한다.
    _SHA256_STOP_SENTINEL = (-1, -1, None, None, None)

    def __init__(self):
        self.cfg = cfgmod.load_config()
        self.db = None
        self._sqlite = None
        self._shadow = ShadowConsistencyChecker(
            cfgmod.BASE_DIR / "logs" / "db_shadow_mismatch.log",
            (self.cfg.get("database_debug") or {}).get("mode", "off"),
        )
        self._load_db_if_configured()
        # [신규] Export/CleanUp/Prune/Refresh List 등 장시간 작업의 진행률 표시용.
        # 백그라운드 스레드에서 실행하고, JS는 get_job_progress()로 주기적으로 폴링한다.
        self._jobs = {}
        self._db_lock = threading.RLock()
        # [크래시 리포트 반영 -> Queue 구조로 교체] 예전엔 서로 다른 Local의 스캔이
        # 완전히 독립된 백그라운드 스레드로 동시에 돌 수 있었다 - 사용자가 실제로
        # "Local1 스캔 중에 Local2로 이동" -> 앱 강제종료를 재현했다(정확한 네이티브
        # 크래시 지점은 이 sandbox에서 재현 불가 - Windows pywebview/WebView2 실기
        # 확인 필요, 두 스캔이 파일시스템/이미지 처리를 겹쳐 돌리며 리소스를 과하게
        # 잡아먹는 것으로 의심). 처음엔 threading.Lock() 하나로 전역 직렬화했는데,
        # 그러면 서로 완전히 무관한 Local A Scan / Local B Export까지도 항상
        # 순서를 기다려야 했다. [범위 축소] 이제 target_ids(Local id/"masterdb")가
        # 겹치는 job끼리만 직렬화하고, 겹치지 않는 job은 동시에 돌 수 있다 - "같은
        # 대상일 때만 막는다"는 목표에 맞춘 것. job 엔트리는 큐에 들어가는 즉시
        # self._jobs에 QUEUED 상태로 남고(자기 target을 막고 있는 다른 job이 몇 개인지
        # 포함), _run_heavy_job()이 매번 큐 전체를 훑어 "지금 실행 중이거나 이번에
        # 같이 허용된 job들의 target"과 안 겹치는 job을 전부 한 번에 허용한다(FIFO
        # 순서를 최대한 존중하되, 겹치지 않으면 뒤에 있어도 먼저 허용됨) - 그래서
        # worker thread는 서로 target이 겹치지 않는 job 수만큼 동시에 존재할 수
        # 있다(_admit_ready_heavy_jobs 참고).
        self._heavy_job_queue = []  # [{"job_id","fn","mutates_db","target_ids": frozenset,"kind"}, ...]
        self._heavy_job_lock = threading.Lock()
        self._heavy_job_running_targets = {}  # job_id -> {"target_ids": frozenset,"kind"}, 현재 실행 중인 job들
        # [체감 속도 - 비디오 지연 복사] Scan/Import/Export가 비디오를 뒤로 미루는 동안
        # 그 target(Local id 또는 "masterdb")에 대한 삭제/이름변경처럼 파일을 건드리는
        # 작업이 끼어들면 방금 복사한 media/rom과 어긋날 수 있다. 그래서 진행 중인 동안
        # 해당 target을 "busy"로 표시해 삭제류만 막는다. 메타데이터 편집은 파일 이동/삭제가
        # 없으므로 막지 않는다.
        self._busy_targets = set()
        self._busy_lock = threading.Lock()
        # [P1-3] target(Local id/"masterdb")별로 지금 그걸 busy로 잡고 있는 heavy
        # job의 kind("scan"|"other")를 기록한다. Scan은 read-only라 metadata 편집과
        # 부딪힐 일이 없어(디스크가 최종 진실, pending_edits_during_scan으로 안전하게
        # 재적용) 편집을 계속 허용하지만, Import/Export는 실제로 그 Local의
        # metadata/media를 읽거나 쓰므로 동시에 사용자가 편집하면 마지막 write가
        # 서로를 덮어쓸 수 있다 - kind가 "scan"이 아니면 편집 자체를 막는다.
        self._busy_target_kind = {}
        # [P0-4] 같은 Local에 대한 Scan이 이미 진행 중(대기/1단계/2단계 어느
        # 단계든)이면 start_scan_local()이 새 job chain을 또 만들지 않고 기존
        # root job_id를 그대로 재사용한다 - JS의 ensureLocalScanned()에 있던
        # _scanInFlight 중복 방지가 handleRefresh() 경로에는 적용되지 않아서,
        # Scan 중 Refresh를 연타하면 같은 Local에 여러 Scan job chain이 큐에
        # 쌓일 수 있었다. local_id -> 아직 완전히 끝나지 않은 scan chain의
        # root job_id. 마지막 phase가 실제로 끝나야(성공/실패/취소 무관) 지운다.
        self._active_scan_jobs = {}
        # [P0-8] SHA256은 ROM의 공식 여부/동일 여부 판단을 위한 "보조" 정보일 뿐,
        # Scan/Import/Export/Copy의 critical path에 있을 필요가 없다. 예전엔
        # _copy_roms_to_masterdb()가 ROM을 복사한 직후 그 자리에서 동기로
        # file_sha256()을 계산했는데, 이 호출 전체가 mutates_db=True job의
        # _db_lock 안에서 실행되므로(_start_job_worker 참고) 큰 ROM 파일 하나를
        # 해시하는 동안 다른 모든 DB-mutating job/backup/restore가 block됐다.
        # 이제 복사 직후엔 (system, filename, file_path, priority)만 큐에 넣고
        # 즉시 다음 ROM으로 넘어간다 - 실제 해시 계산은 별도 백그라운드 스레드가
        # 큐에서 하나씩 꺼내 수행하고, SQLite 쓰기(set_rom_hash, 이건 순식간에
        # 끝남)만 짧게 _db_lock을 잡는다. PriorityQueue라 낮은 숫자가 먼저 처리된다
        # - 우선순위 규약(요청 사항 기준): 0=현재 Detail에서 보고 있는 ROM,
        # 1=Compare 화면에 보이는 ROM, 2=방금 새로 추가된 ROM(기본값, Copy 직후),
        # 3=나머지 전체. 지금은 Copy 경로가 2로 enqueue하는 것만 연결되어 있고
        # Detail/Compare가 0/1로 우선 요청을 넣는 UI 연동은 아직 없다 - request_rom_hash()
        # 를 그 용도로 호출하면 된다.
        self._sha256_queue = queue.PriorityQueue()
        self._sha256_seq = 0  # PriorityQueue가 동일 priority 항목끼리 dict를 비교하지 않도록 하는 tie-breaker
        self._sha256_stop = threading.Event()
        self._sha256_thread = threading.Thread(target=self._sha256_worker_loop, daemon=True)
        self._sha256_thread.start()
        # Web GUI에서 Local 재진입/Dashboard가 전체 파일시스템을 다시 읽지 않도록
        # Local별 raw scan 결과를 런타임에 보관한다. config.json에는 저장하지 않는다.
        self._local_scan_cache = {}  # 백그라운드 스레드와 메인 호출이 동시에 db를 건드릴 위험 방지
        # [DIAGNOSTIC BUILD] Python + Web GUI 상태를 한 파일에 기록한다.
        self._diag_lock = threading.Lock()
        self._diag_path = cfgmod.BASE_DIR / "logs" / "retro_manager_diagnostic.log"
        self._diag_thumb_count = 0
        # Small LRU for Preview thumbnails. Full-resolution media is never cached here;
        # card images are resized before crossing the Python/JS bridge.
        self._thumb_cache = OrderedDict()
        self._thumb_cache_limit = 256
        try:
            self._diag_path.parent.mkdir(parents=True, exist_ok=True)
            self._diag_path.write_text("", encoding="utf-8")
        except Exception:
            pass
        self._diag("APP_START", base_dir=str(cfgmod.BASE_DIR), masterdb_root=self.cfg.get("masterdb", {}).get("root", ""),
                   masterdb_loaded=bool(self.db), masterdb_roms=len((self.db or {}).get("roms", {})),
                   locals=[{"id": x.get("id"), "label": x.get("label"), "frontend": x.get("frontend"),
                            "rom_path": x.get("rom_path", ""), "metadata_path": x.get("metadata_path", ""),
                            "media_path": x.get("media_path", "")} for x in self.cfg.get("locals", [])])

    # ------------------------------------------------------------------
    # Diagnostic logging (0.4.0.21 diagnostic build)
    # ------------------------------------------------------------------
    def _diag(self, event, **payload):
        # Large test libraries can generate thousands of scan/render records.
        # Keep only actionable diagnostics unless explicitly enabled.
        verbose = bool(self.cfg.get("diagnostic_verbose", False))
        noisy_prefixes = ("JS:RENDER_LIST", "JS:PREVIEW_DOM_CREATED", "SCAN_LOCAL_SYSTEM", "SCAN_LOCAL_RAW", "SCAN_LOCAL_ENTRIES", "SCAN_LOCAL_DONE", "LOCAL_DETAIL_MEDIA", "LOCAL_MEDIA_IMAGE", "LIST_MASTERDB_GAMES")
        if not verbose and any(str(event).startswith(p) for p in noisy_prefixes):
            return
        try:
            record = {"ts": datetime.now().isoformat(timespec="milliseconds"), "side": "PY", "event": str(event)}
            record.update(payload)
            line = json.dumps(record, ensure_ascii=False, default=str)
            with self._diag_lock:
                with self._diag_path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    def diagnostic_log(self, event, payload=None):
        """JS에서 전달하는 진단 이벤트를 같은 로그 파일에 기록."""
        data = payload if isinstance(payload, dict) else {"value": payload}
        self._diag(f"JS:{event}", **data)
        return _ok(True)

    def get_diagnostic_log_path(self):
        return _ok(str(self._diag_path))

    def close(self):
        """Release the SQLite connection owned by this API instance."""
        # [P0-8, 버그 수정] 백그라운드 SHA256 워커가 self._sqlite에 접근하는
        # 동안(get_rom_hash/set_rom_hash) close()가 같은 connection을 닫으면,
        # SQLite는 "다른 스레드가 사용 중인 connection을 닫는 것"을 허용하지
        # 않는다 - Python 예외가 아니라 세그폴트로 이어진다(테스트처럼 Api
        # 인스턴스를 빠르게 계속 만들고 닫는 상황에서 실제로 재현/확인됨).
        # 워커의 실제 sqlite 접근은 전부 _db_lock 안에서 일어나므로, close()도
        # connection.close() 호출을 _db_lock 안에서 하면 워커가 락을 쥔 동안엔
        # close()가 자연히 그 락을 기다리게 된다(RLock이라 재진입 가능, 데드락
        # 없음) - 이게 실제 경합을 막는 핵심 수정이다. stop 신호+큐 sentinel+
        # join()은 그 위에 "정상적으로 빠르게 종료"를 보장하기 위한 보조 장치.
        try:
            self._sha256_stop.set()
            self._sha256_queue.put(self._SHA256_STOP_SENTINEL)
            self._sha256_thread.join(timeout=5)
        except Exception:
            pass
        try:
            with self._db_lock:
                if self._sqlite is not None:
                    self._sqlite.close()
                    self._sqlite = None
        except Exception:
            pass

    def get_database_debug(self):
        return _ok(self._shadow.summary())

    def set_database_debug(self, mode):
        try:
            self._shadow.set_mode(mode)
            self.cfg.setdefault("database_debug", {})["mode"] = self._shadow.mode
            cfgmod.save_config(self.cfg)
            self._diag("DB_SHADOW_MODE", mode=self._shadow.mode, log_path=str(self._shadow.log_path))
            return _ok(self._shadow.summary())
        except Exception as exc:
            return _err(str(exc))

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------
    def _load_db_if_configured(self):
        root = self.cfg.get("masterdb", {}).get("root")
        if root and Path(root).exists():
            self.db = dbmod.load_db(root)
            self._sqlite = SQLiteRepository.from_masterdb_root(root)
            self._sqlite.replace_from_dict(self.db, self.cfg.get("locals", []))
        else:
            self.db = None
            self._sqlite = None

    def _save_db(self, sync_sqlite: bool = True):
        """Persist self.db to JSON, and (unless the caller already applied a
        targeted SQLiteRepository write) resync the whole SQLite projection.

        sync_sqlite=False is for call sites that already called a targeted
        self._sqlite.xxx(...) write for the specific rom(s) they touched
        (save_version_fields, clone_version, etc). Rerunning the full
        replace_from_dict() there was pure redundant work (and, at 10k-ROM
        scale, expensive redundant work) since the projection was already
        correct. Bulk/legacy paths that mutate self.db directly without a
        matching targeted write (import/export/cleanup/csv/backup) must keep
        sync_sqlite=True so SQLite does not go stale.
        """
        root = self.cfg.get("masterdb", {}).get("root")
        if root:
            with self._db_lock:
                dbmod.save_db(root, self.db)
                first_init = self._sqlite is None
                if first_init:
                    self._sqlite = SQLiteRepository.from_masterdb_root(root)
                if first_init or sync_sqlite:
                    self._sqlite.replace_from_dict(self.db, self.cfg.get("locals", []))
                    if self._shadow.enabled:
                        self._shadow.compare_write("_save_db", self.db, self._sqlite)

    @contextmanager
    def _db_rollback_guard(self):
        """[P0 후속 수정, PR #1 리뷰] import_local_to_masterdb()는 self.db["roms"]를
        SQLite와 별도로 직접 mutate한다 (기존 rom_entry의 "media"/"versions" 같은
        중첩 dict를 in-place로 갱신). SQLite 쪽은 batch()의 `with`문 덕분에 예외 시
        정확히 rollback되지만, self.db는 평범한 Python dict라 예외가 나도 이미
        mutate된 상태 그대로 남는다 - 이후 이 작업과 무관한 다른 호출에서
        `_save_db()`가 실행되면 그 stale self.db가 SQLite/JSON에 그대로 다시
        저장되어 "SQLite는 rollback했는데 그 데이터가 self.db를 거쳐 되살아나는"
        결과로 이어질 수 있다.

        self.db["roms"]를 통째로 deepcopy해뒀다가, 이 with 블록 안에서 예외가 나면
        원래 상태로 되돌린다. rom 개수가 많을수록 deepcopy 비용이 커지지만(수만
        ROM 규모), import 자체가 이미 그 규모에서 초 단위로 걸리는 작업이라 상대적
        비용은 작고 - 무엇보다 "실패한 import가 부분 반영된 채 남는" 데이터 유실
        위험을 없애는 쪽이 우선이라고 판단했다."""
        if self.db is None:
            yield
            return
        snapshot = copy.deepcopy(self.db.get("roms", {}))
        try:
            yield
        except Exception:
            self.db["roms"] = snapshot
            raise

    # [P1-4] 완료된 job을 이 시간(초)보다 오래 들고 있지 않는다 - Scan 결과
    # (게임 수천~수만 개)처럼 큰 result가 아무도 다시 조회하지 않는 채로
    # self._jobs에 무기한 쌓이는 걸 막기 위함. 새 job이 시작될 때마다
    # 기회적으로(opportunistically) 정리한다 - 별도 타이머 스레드 없이도
    # 앱을 계속 쓰는 한(=새 job이 계속 생기는 한) 오래된 job은 알아서 빠진다.
    _JOB_TTL_SECONDS = 600

    def _prune_old_jobs(self):
        now = time.time()
        stale = [jid for jid, job in self._jobs.items()
                 if job.get("done") and (now - job.get("done_at", now)) > self._JOB_TTL_SECONDS]
        for jid in stale:
            del self._jobs[jid]

    def _run_job(self, fn, mutates_db=False):
        """
        [신규] fn(progress_cb) 형태의 함수를 백그라운드 스레드에서 실행하고, job_id를
        즉시 반환한다 (블로킹하지 않음). JS는 get_job_progress(job_id)를 짧은 주기로
        폴링해서 진행률/완료 여부를 확인한다.

        mutates_db=True: [P0 버그 수정] Import/Export/유사롬 탐색처럼 self.db/
        self._sqlite에 걸쳐 오래(수천~수만 ROM) 쓰기를 이어가는 job은, 이전엔
        `_save_db()`를 호출하는 그 순간에만 `self._db_lock`을 짧게 잡았다 - 나머지
        긴 처리 구간(특히 SQLite `batch()` 트랜잭션이 열려 있는 동안)은 잠금이 전혀
        없어서, 같은 시간에 다른 job이나 동기 호출(backup/restore/삭제 등)이 **같은
        sqlite3 connection**(`check_same_thread=False`로 공유됨)을 동시에 건드릴 수
        있었다. mutates_db=True면 `fn(progress_cb)` 실행 전체를 `self._db_lock`
        (RLock)으로 감싸서, DB에 실제로 쓰는 job들이 서로 겹치지 않고 항상 하나씩만
        실행되게 한다. `_db_lock`이 RLock이라 fn 내부에서 `_save_db()` 등이 다시
        `with self._db_lock:`을 해도(같은 스레드이므로) 안전하다.

        CleanUp/Prune/유사롬 탐색처럼 서로 겹쳐도 안전한(파일시스템을 공유
        Local/ArchiveDB 단위로 무겁게 건드리지 않는) job에 쓴다. Scan/Import/Export는
        여러 개가 동시에 스레드로 돌면 안 되므로 _run_heavy_job()을 쓴다.
        """
        self._prune_old_jobs()
        job_id = f"job_{time.time_ns()}"
        self._jobs[job_id] = {"current": 0, "total": 1, "label": "", "done": False, "result": None, "error": None,
                               "cancel_requested": False, "cancelled": False}
        self._start_job_worker(job_id, fn, mutates_db)
        return job_id

    def _start_job_worker(self, job_id, fn, mutates_db, on_finish=None):
        """self._jobs[job_id]가 이미 만들어져 있다고 가정하고, 백그라운드 스레드에서
        fn(progress_cb)를 실행한다. on_finish는(있다면) 성공/실패/취소 상관없이 job이
        끝난 직후 호출된다 - _dispatch_next_heavy_job()이 큐의 다음 job을 잇는 데 쓴다."""
        def progress_cb(current, total, label):
            job = self._jobs[job_id]
            job.update({"current": current, "total": max(1, total), "label": str(label)})
            if job["cancel_requested"]:
                raise _JobCancelled()

        def worker():
            try:
                if mutates_db:
                    with self._db_lock:
                        result = fn(progress_cb)
                else:
                    result = fn(progress_cb)
                self._jobs[job_id]["result"] = result
            except _JobCancelled:
                self._jobs[job_id]["error"] = "취소되었습니다."
                self._jobs[job_id]["cancelled"] = True
            except Exception as e:
                self._jobs[job_id]["error"] = str(e)
            finally:
                self._jobs[job_id]["done"] = True
                # [P1-4] 완료 시각을 남겨서 _prune_old_jobs()가 "언제 끝났는지" 기준으로
                # 오래된 job의 result를 정리할 수 있게 한다 - Scan 결과는 게임이
                # 수천~수만 개면 상당히 크고, get_job_progress를 다시 조회할 사람이
                # 없는데도(사용자가 이미 화면을 떠남) _jobs 딕셔너리에 무기한 남아있으면
                # 메모리가 계속 누적된다.
                self._jobs[job_id]["done_at"] = time.time()
                if on_finish:
                    on_finish()

        threading.Thread(target=worker, daemon=True).start()

    def _run_heavy_job(self, fn, mutates_db=False, target_ids=(), kind="other", on_created=None):
        """[Queue 구조, 범위 축소] Scan/Import/Export처럼 파일시스템을 무겁게 오래
        건드리는 job은 이 큐를 거쳐야만 실행된다. target_ids(Local id/"masterdb")가
        서로 겹치는 job끼리만 직렬화되고, 겹치지 않는 job(예: 완전히 다른 Local의
        Import와 Export)은 동시에 실행될 수 있다 - "같은 대상일 때만 막는다"는
        범위다.

        kind="scan"은 예외다: Local A Scan + Local B Scan처럼 target이 겹치지
        않아도, Scan끼리는 항상 전역으로 직렬화한다 - 이건 논리적 데이터 충돌이
        아니라 실제 크래시 재현 조건이었기 때문이다("Local1 스캔 중 Local2로
        이동" -> 앱 강제종료, 리소스 경합으로 의심). Import/Export는 이런 크래시
        전례가 없어서 같은 대상일 때만 막는다.

        job 엔트리는 큐에 들어가는 즉시(QUEUED 상태로) self._jobs에 만들어지고,
        막는 게 없으면 즉시 worker thread가 뜬다. 실제 직렬화는
        _admit_ready_heavy_jobs_locked()가 매번 큐 전체를 훑어서 판단한다.

        on_created(job_id): [race 수정] 큐에 들어가기도 전에(=worker thread가
        생기기 전에) 호출된다. 호출자가 "이 job_id가 지금 진행 중"이라고 외부에
        기록해야 하는 경우(예: start_scan_local()의 _active_scan_jobs) job_id를
        받은 뒤에 기록하면 늦다 - 아주 작은 fixture/빠른 job은 그 사이에 이미
        끝나버릴 수 있어서, "끝난 job을 진행 중이라고 잘못 등록"하는 race가
        생긴다. on_created를 여기(worker가 뜨기 전)에서 동기로 불러야 그 race가
        구조적으로 불가능해진다."""
        self._prune_old_jobs()
        job_id = f"job_{time.time_ns()}"
        self._jobs[job_id] = {"current": 0, "total": 1, "label": "대기 중", "done": False, "result": None,
                               "error": None, "cancel_requested": False, "cancelled": False, "queued": True}
        if on_created:
            on_created(job_id)
        entry = {"job_id": job_id, "fn": fn, "mutates_db": mutates_db,
                 "target_ids": frozenset(t for t in target_ids if t), "kind": kind}
        with self._heavy_job_lock:
            self._heavy_job_queue.append(entry)
            to_start = self._admit_ready_heavy_jobs_locked()
        self._start_admitted_heavy_jobs(to_start)
        return job_id

    def _admit_ready_heavy_jobs_locked(self):
        """self._heavy_job_lock을 잡은 상태에서만 호출한다. 큐를 순서대로 훑으면서,
        "현재 실행 중인 job들 + 이번 훑기에서 이미 허용하기로 한 job들"과 안
        부딪히는 job을 전부 허용 목록에 담아 큐에서 뺀다(FIFO를 최대한 존중하되,
        뒤에 있어도 안 부딪히면 먼저 허용됨). target이 겹치면 부딪히는 것으로
        치고, kind="scan"끼리는 target과 무관하게 항상 부딪히는 것으로 친다(Scan
        전역 직렬화). 아직 막혀 있는 job들은 label을 다시 채운 뒤 큐에 남겨둔다.
        반환값(허용된 entry 목록)은 락을 놓은 뒤 _start_admitted_heavy_jobs()로
        실제 스레드를 띄우는 데 쓴다 - 스레드 생성 자체를 락 안에서 하지 않기 위함."""
        locked_targets = set()
        scan_running = False
        for info in self._heavy_job_running_targets.values():
            locked_targets |= info["target_ids"]
            scan_running = scan_running or info["kind"] == "scan"

        remaining = []
        to_start = []
        for entry in self._heavy_job_queue:
            blocked = bool(entry["target_ids"] & locked_targets) or (entry["kind"] == "scan" and scan_running)
            if blocked:
                remaining.append(entry)
            else:
                to_start.append(entry)
                locked_targets |= entry["target_ids"]
                if entry["kind"] == "scan":
                    scan_running = True
                self._heavy_job_running_targets[entry["job_id"]] = {"target_ids": entry["target_ids"], "kind": entry["kind"]}
        self._heavy_job_queue = remaining
        for i, entry in enumerate(self._heavy_job_queue):
            job = self._jobs.get(entry["job_id"])
            if job is not None:
                job["label"] = f"대기 중 (앞에서 막고 있는 작업 {i + 1}개)" if i == 0 else f"대기 중 (앞에 {i}개)"
        return to_start

    def _start_admitted_heavy_jobs(self, entries):
        """_admit_ready_heavy_jobs_locked()가 허용한 job들을 실제로 백그라운드
        스레드로 띄운다. 락 밖에서 호출해야 한다(스레드 생성 자체는 락이 필요
        없고, worker 콜백 안에서 다시 락을 잡기 때문에 락 안에서 호출하면 위험)."""
        for entry in entries:
            job_id = entry["job_id"]
            self._jobs[job_id]["queued"] = False

            def on_finish(job_id=job_id):
                with self._heavy_job_lock:
                    self._heavy_job_running_targets.pop(job_id, None)
                    to_start = self._admit_ready_heavy_jobs_locked()
                self._start_admitted_heavy_jobs(to_start)

            self._start_job_worker(job_id, entry["fn"], entry["mutates_db"], on_finish=on_finish)

    def _split_media_for_deferred_video(self, media_types):
        """[체감 속도] performance.defer_video_media가 켜져 있으면 videos를 1차
        복사 대상에서 빼고, 2차(지연)로 돌릴 목록을 따로 반환한다. media_types를
        사용자가 이미 명시적으로 좁혀서 그 안에 videos가 없으면(예: "커버만"
        선택) 애초에 지연시킬 게 없으므로 그대로 존중한다. 반환값:
        (primary_media_types, deferred_media_types_or_None)."""
        defer = self.cfg.get("performance", {}).get("defer_video_media", True)
        if not defer:
            return media_types, None
        base = list(cfgmod.MEDIA_TYPES) if media_types is None else list(media_types)
        if "videos" not in base:
            return media_types, None
        return [m for m in base if m != "videos"], ["videos"]

    def _split_media_into_phases(self, media_types):
        """[체감 속도, Export 3단계] performance.defer_video_media가 켜져 있으면
        (1) covers, (2) videos 제외 나머지, (3) videos 순서로 3단계에 걸쳐 나눈다.
        Scan/Import와 달리 Export는 실제로 파일을 복사하므로, 커버만 먼저 끝내면
        Local 쪽에서 카드/대표이미지를 가장 먼저 볼 수 있고 비디오(대개 가장 큰
        파일)는 맨 뒤로 미뤄 나머지 media의 체감 속도를 끌어올린다. media_types가
        이미 특정 타입만으로 좁혀져 있으면(대화상자에서 "커버만" 등으로 선택) 그
        범위 안에서만 나눈다 - 없는 phase는 아예 만들지 않는다. 꺼져 있으면 예전처럼
        전체를 한 phase로 묶는다. 반환값: [(label, media_types_for_phase), ...]."""
        defer = self.cfg.get("performance", {}).get("defer_video_media", True)
        if not defer:
            return [("전체", media_types)]
        base = list(cfgmod.MEDIA_TYPES) if media_types is None else list(media_types)
        phase1 = [m for m in base if m == "covers"]
        phase3 = [m for m in base if m == "videos"]
        phase2 = [m for m in base if m not in ("covers", "videos")]
        phases = []
        if phase1:
            phases.append(("메타데이터+커버", phase1))
        if phase2:
            phases.append(("기타 미디어", phase2))
        if phase3:
            phases.append(("비디오", phase3))
        if not phases:
            # media_types가 전부 걸러졌으면(예: 빈 리스트로 "미디어 없음" 선택) 그래도
            # metadata(텍스트 필드) 자체는 한 phase로 복사되어야 한다.
            phases.append(("메타데이터", media_types if media_types is not None else []))
        return phases

    def _start_phased_media_job(self, target_ids, phases, mutates_db=True, attach_followup_job_id=False, combine_results=None, kind="other", on_phase_job_created=None):
        """[체감 속도] phases: [(label, run_fn), ...] 목록을 하나씩 순서대로 job으로
        이어서 실행한다. 앞 phase가 "성공적으로" 끝나야 다음 phase가 시작되고, 어느
        phase든 예외로 실패하면 그 자리에서 멈추고(남은 phase는 아예 안 돎) 그 예외가
        job 결과에 에러로 기록된다 - 예를 들어 SQLite 오류로 1단계 자체가 실패했는데
        나머지 media만 따로 복사하는 건 의미가 없다.

        target_ids(Local id/"masterdb")는 1단계가 시작되는 순간부터 마지막 phase가
        끝날 때까지(또는 중간에 실패할 때까지) 계속 busy로 잡아둔다 - 삭제/이름변경이
        그 사이에 끼어들면 방금 복사한 media/rom과 어긋날 수 있어서다.

        [P1-3] kind="scan"이면(읽기 전용) 메타데이터 편집을 계속 허용한다(디스크가
        항상 최종 진실이고, pending_edits_during_scan으로 안전하게 재적용된다).
        kind가 그 외(Import/Export)면 실제로 해당 Local의 metadata/media를 읽고
        쓰므로, 그 사이 편집을 허용하면 마지막 write가 서로 덮어쓸 수 있어 편집
        자체를 막는다(save_local_game_fields/save_local_media의 busy 체크 참고).

        각 phase의 progress label 앞에는 "(i/N) label: "이 자동으로 붙는다 - 사용자
        눈엔 프로그레스 바 하나가 순서대로 단계를 넘어가는 것처럼 보인다. 반환값은
        1단계 job_id(사용자가 폴링하는 진행률은 이 id 하나로 이어진다).

        attach_followup_job_id=True면(Scan 2단계 전용) 마지막이 아닌 phase의 결과
        dict에 "followUpJobId"(다음 phase의 job id)와 "partial": True를 끼워 넣는다 -
        JS가 1단계 결과로 화면을 먼저 그린 뒤, 이 id를 조용히(진행률 바 없이) 폴링해서
        2단계가 끝나면 다시 갱신할 수 있게 하기 위함. 다른 호출부(Export/Import)는 결과
        dict 형태가 고정돼 있어서 기본은 꺼둔다.

        combine_results(accumulated, phase_result) -> merged: [Parent Job lifecycle
        리뷰 반영] 지정하지 않으면(기본) 마지막 job의 result가 곧 "마지막 phase 자기
        혼자만의" 결과다 - 예를 들어 Export 3단계에서 마지막(비디오) phase의
        exported 개수만 최종 결과로 노출되고, 1/2단계에서 실제로 복사된 커버/기타
        media 개수는 통째로 사라진다(JS 토스트가 "N개 완료"를 잘못된 숫자로 보여줌).
        combine_results를 주면 매 phase가 끝날 때마다 그 결과를 이전까지의 누적값과
        합쳐서, 최종 job의 result가 전체 phase를 아우르는 진짜 합계가 되게 한다.
        accumulated는 첫 phase에서는 None이다.

        on_phase_job_created(job_id): [리뷰 반영, phase lifecycle race 수정] phase가
        바뀔 때마다(첫 phase 포함) 그 phase의 새 job_id로 매번 호출된다 - 호출자가
        "지금 이 target에 대해 실행 중인 job_id"를 외부에 추적하고 싶을 때
        (start_scan_local()의 _active_scan_jobs) 쓴다. _run_heavy_job()이 worker
        thread를 띄우기 전에(=job이 끝나기 전에 반드시) 동기 호출하므로, 등록이
        완료 시점보다 늦어서 "이미 끝난 job을 진행 중으로 잘못 등록"하는 race가
        구조적으로 생기지 않는다. 또한 root job(phase 1)뿐 아니라 phase가 바뀔
        때마다 다시 불리므로, 호출자가 그 값을 그대로 저장하면 "현재 진행 중인
        phase의 job_id"가 항상 최신으로 유지된다(예전엔 phase 1의 job_id만 저장해서,
        phase 2가 진행 중인데도 이미 done인 phase 1 job_id를 들고 있는 불일치가
        있었다)."""
        n = len(phases)

        def release():
            with self._busy_lock:
                for t in target_ids:
                    self._busy_targets.discard(t)
                    self._busy_target_kind.pop(t, None)

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
                    next_job_id = self._run_heavy_job(make_runner(index + 1, combined), mutates_db=mutates_db, target_ids=target_ids, kind=kind, on_created=on_phase_job_created)
                    if attach_followup_job_id and isinstance(result, dict):
                        result = {**result, "followUpJobId": next_job_id, "partial": True}
                    return result
                release()
                return combined

            return run

        with self._busy_lock:
            for t in target_ids:
                self._busy_targets.add(t)
                self._busy_target_kind[t] = kind
        return self._run_heavy_job(make_runner(0, None), mutates_db=mutates_db, target_ids=target_ids, kind=kind, on_created=on_phase_job_created)

    def _start_media_job(self, target_ids, run_primary, make_deferred_run, mutates_db=True):
        """[체감 속도] run_primary 뒤에 make_deferred_run()(있다면)을 2단계로 이어
        붙이는 2-phase 버전 - _start_phased_media_job의 얇은 래퍼. make_deferred_run이
        None이면(=지연할 비디오가 없음) 1 phase만 돈다."""
        phases = [("주 작업", run_primary)]
        if make_deferred_run is not None:
            phases.append(("비디오", make_deferred_run()))
        return self._start_phased_media_job(target_ids, phases, mutates_db=mutates_db)

    def _target_busy_error(self, *target_ids):
        """target_ids 중 하나라도 busy면 에러 응답을, 아니면 None을 반환한다.
        삭제/이름변경처럼 media/rom 파일을 직접 건드리는 작업 앞에서만 호출한다."""
        with self._busy_lock:
            busy = [t for t in target_ids if t and t in self._busy_targets]
        if busy:
            return _err("Scan/Import/Export가 진행 중이라 지금은 삭제/이름변경을 할 수 없습니다. 완료 후 다시 시도해주세요.")
        return None

    def _metadata_edit_busy_error(self, local_id):
        """[P1-3] Scan/Import/Export operation별로 metadata/media 편집 정책이
        다르다:
          - Scan: read-only라 편집과 부딪힐 일이 없다(디스크가 항상 최종 진실이고,
            겹치면 pending_edits_during_scan으로 안전하게 재적용된다) - 계속 허용.
          - Import/Export: 실제로 그 Local의 metadata/media 파일을 읽거나 쓴다 -
            그 사이 사용자가 같은 파일을 편집하면 마지막 write가 서로 덮어쓸 수
            있다 - 편집 자체를 막는다.
        local_id가 busy가 아니거나 busy 이유가 kind="scan"이면 None(허용)을,
        그 외(Import/Export)면 에러 응답을 반환한다."""
        with self._busy_lock:
            kind = self._busy_target_kind.get(local_id) if local_id in self._busy_targets else None
        if kind is not None and kind != "scan":
            return _err("Import/Export가 진행 중이라 지금은 Metadata/Media를 편집할 수 없습니다. 완료 후 다시 시도해주세요.")
        return None

    def get_job_progress(self, job_id):
        job = self._jobs.get(job_id)
        if not job:
            return _err("작업을 찾을 수 없습니다.")
        return _ok(job)

    def cancel_job(self, job_id):
        """[신규] 실행 중인 job(주로 Local 스캔처럼 오래 걸리는 작업)에 취소를 요청한다.
        progress_cb가 다음에 호출되는 시점에 _JobCancelled를 던져 스레드가 정리된다 -
        Python 스레드는 강제 종료할 수 없으므로 progress 콜백 지점에서 협조적으로 멈춘다.

        [Queue 구조] 아직 큐에서 대기 중(queued=True, worker thread 자체가 없음)인
        heavy job은 progress_cb가 한 번도 안 불릴 수 있으므로, 그 경우 큐에서 바로
        빼서 즉시 취소 처리한다 - 자기 차례가 올 때까지 기다렸다가 그제서야
        취소되는 낭비를 없앤다."""
        job = self._jobs.get(job_id)
        if not job:
            return _err("작업을 찾을 수 없습니다.")
        if job["done"]:
            return _ok(True)
        if job.get("queued"):
            with self._heavy_job_lock:
                cancelled_entry = next((e for e in self._heavy_job_queue if e["job_id"] == job_id), None)
                self._heavy_job_queue = [e for e in self._heavy_job_queue if e["job_id"] != job_id]
                # [주의] 여기서 뺀 job은 애초에 target을 하나도 안 잡고 있었으므로
                # (아직 실행된 적이 없음) 다른 대기 job을 새로 허용할 여지가 생기지
                # 않는다 - _admit_ready_heavy_jobs_locked() 재호출은 필요 없다.
                for i, entry in enumerate(self._heavy_job_queue):
                    j = self._jobs.get(entry["job_id"])
                    if j is not None:
                        j["label"] = f"대기 중 (앞에서 막고 있는 작업 {i + 1}개)" if i == 0 else f"대기 중 (앞에 {i}개)"
            # [P0-5] _start_phased_media_job()은 phase 0(=이 job)이 시작되기도 전에
            # busy_targets를 이미 예약해둔다(1단계가 시작되는 순간부터 잡아두는
            # 게 아니라, "잡아두고 나서" 큐에 진입시키는 구조라서). 정상적으로
            # fn이 실행됐다면 마지막 phase의 release()가 이걸 풀어주지만, queued
            # 상태에서 취소되면 fn 자체가 한 번도 안 불려서 release()도 안 불린다 -
            # 그 결과 busy_targets에 이 target들이 영원히 남아 Delete/Rename이
            # 계속 막힐 수 있었다. 여기서 대신 풀어준다.
            if cancelled_entry is not None and cancelled_entry.get("target_ids"):
                with self._busy_lock:
                    for t in cancelled_entry["target_ids"]:
                        self._busy_targets.discard(t)
                        self._busy_target_kind.pop(t, None)
            # [P0-4] 이 job이 어느 Local의 Scan chain의 한 phase였는데 큐에서
            # 대기 중(=run()이 한 번도 안 불림)일 때 취소되면, start_scan_local()의
            # is_last_phase 정리 로직 자체가 실행될 기회가 없다 - 여기서 대신
            # "Scan 진행 중" 표시를 지워서 다음 start_scan_local() 호출이 이
            # 취소된 job_id를 계속 반환하는 일이 없게 한다.
            if cancelled_entry is not None and cancelled_entry.get("kind") == "scan":
                for lid in cancelled_entry.get("target_ids", ()):
                    self._active_scan_jobs.pop(lid, None)
            job["cancelled"] = True
            job["error"] = "취소되었습니다."
            job["done"] = True
            return _ok(True)
        job["cancel_requested"] = True
        return _ok(True)


    def _native_hwnd(self):
        """Return the real Windows HWND used by pywebview's frameless window."""
        import ctypes
        user32 = ctypes.windll.user32
        # The native window keeps its title even though the visible title bar is hidden.
        hwnd = user32.FindWindowW(None, "Retro Metadata Manager")
        if hwnd:
            return hwnd
        return None

    def _ensure_native_window_style(self, hwnd):
        """Keep the Win32 sizing/move styles even though pywebview is frameless."""
        import ctypes
        user32 = ctypes.windll.user32
        GWL_STYLE = -16
        WS_THICKFRAME = 0x00040000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        WS_SYSMENU = 0x00080000
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        wanted = style | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
        if wanted != style:
            user32.SetWindowLongW(hwnd, GWL_STYLE, wanted)
            # Tell Windows that the non-client metrics changed.
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # SWP_NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED


    def window_control(self, action):
        """Native Windows window controls for the frameless pywebview window."""
        try:
            import ctypes
            hwnd = self._native_hwnd()
            if not hwnd:
                # Fallback to pywebview API if a native handle cannot be located.
                import webview
                win = getattr(self, "_window", None) or (webview.windows[0] if webview.windows else None)
                if not win:
                    return _err("창을 찾을 수 없습니다.")
                if action == "minimize": win.minimize()
                elif action == "maximize": win.maximize()
                elif action == "restore": win.restore()
                elif action == "close": win.destroy()
                else: return _err(f"알 수 없는 창 제어: {action}")
                return _ok(True)

            user32 = ctypes.windll.user32
            self._ensure_native_window_style(hwnd)
            SW_MINIMIZE, SW_RESTORE, SW_MAXIMIZE = 6, 9, 3
            if action == "minimize":
                user32.ShowWindow(hwnd, SW_MINIMIZE)
            elif action == "maximize":
                user32.ShowWindow(hwnd, SW_MAXIMIZE)
                self._window_maximized = True
            elif action == "restore":
                user32.ShowWindow(hwnd, SW_RESTORE)
                self._window_maximized = False
            elif action == "toggle_maximize":
                if user32.IsZoomed(hwnd):
                    user32.ShowWindow(hwnd, SW_RESTORE); self._window_maximized = False
                else:
                    user32.ShowWindow(hwnd, SW_MAXIMIZE); self._window_maximized = True
            elif action == "close":
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            else:
                return _err(f"알 수 없는 창 제어: {action}")
            return _ok(True)
        except Exception as e:
            return _err(str(e))

    def window_drag_start(self):
        """Hand the current mouse gesture to native Windows move handling."""
        try:
            import ctypes
            hwnd = self._native_hwnd()
            if not hwnd: return _err("창을 찾을 수 없습니다.")
            user32 = ctypes.windll.user32
            self._ensure_native_window_style(hwnd)
            user32.ReleaseCapture()
            user32.SendMessageW(hwnd, 0x00A1, 0x0002, 0)  # WM_NCLBUTTONDOWN / HTCAPTION
            return _ok(True)
        except Exception as e:
            return _err(str(e))

    def window_resize_start(self, edge="se"):
        """Start a real native Windows resize gesture for a frameless window."""
        try:
            import ctypes
            hwnd = self._native_hwnd()
            if not hwnd: return _err("창을 찾을 수 없습니다.")
            edge_map = {"w":1, "e":2, "n":3, "nw":4, "ne":5, "s":6, "sw":7, "se":8}
            code = edge_map.get(str(edge).lower())
            if not code: return _err("잘못된 resize 방향입니다.")
            user32 = ctypes.windll.user32
            self._ensure_native_window_style(hwnd)
            user32.ReleaseCapture()
            # WM_SYSCOMMAND / SC_SIZE + WMSZ_* lets Windows perform the complete
            # mouse-tracked resize itself; no JS mousemove polling is needed.
            user32.SendMessageW(hwnd, 0x0112, 0xF000 + code, 0)
            return _ok(True)
        except Exception as e:
            return _err(str(e))

    def _find_local(self, local_id):
        return cfgmod.get_local(self.cfg, local_id)

    def _rom_entry(self, rom_key):
        if not self.db:
            return None
        return self.db.get("roms", {}).get(rom_key)

    # ------------------------------------------------------------------
    # 폴더/파일 선택 (pywebview 네이티브 대화상자 - 브라우저 샌드박스 제약 없음)
    # ------------------------------------------------------------------
    def pick_folder(self, title=""):
        try:
            import webview
            win = webview.windows[0]
            # [시도] pywebview 버전에 따라 네이티브 폴더 대화상자에 안내 문구(title)를 실을 수
            # 있는지가 다르다 - 공식적으로 안정적인 파라미터인지 확신이 없어서, 여러 방식을
            # 순서대로 시도하고 전부 실패하면 파라미터 없이 기본 호출로 안전하게 폴백한다.
            result = None
            attempts = []
            if title:
                attempts.append({"directory": "", "title": title})
            attempts.append({"directory": ""})
            attempts.append({})
            for kwargs in attempts:
                try:
                    result = win.create_file_dialog(webview.FOLDER_DIALOG, **kwargs)
                    break
                except TypeError:
                    continue
            try:
                win.evaluate_js("document.body.style.opacity=document.body.style.opacity")
            except Exception:
                pass
            if result:
                return _ok(result[0])
            return _ok(None)
        except Exception as e:
            return _err(f"폴더 선택 대화상자를 열 수 없습니다: {e}")

    # ------------------------------------------------------------------
    # MasterDB
    # ------------------------------------------------------------------
    def get_masterdb_info(self):
        root = self.cfg.get("masterdb", {}).get("root", "")
        if not root:
            return _ok({"configured": False})
        rom_count = len(self.db.get("roms", {})) if self.db else 0
        metadata_count = 0
        rom_size_bytes = 0
        if self.db:
            masterdb_root = Path(root)
            for entry in self.db.get("roms", {}).values():
                fields = dbmod.get_default_fields(entry)
                if any(str(fields.get(k, "") or "").strip() for k in ("name", "desc", "genre", "developer", "publisher", "releasedate", "region", "players", "rating")):
                    metadata_count += 1
                try:
                    rp = dbmod.rom_storage_path(masterdb_root, entry["system"], entry["rom_filename"])
                    if rp.exists():
                        rom_size_bytes += rp.stat().st_size
                except (OSError, KeyError, TypeError):
                    pass
        return _ok({
            "configured": True, "root": root,
            "status": self.cfg.get("masterdb", {}).get("status", "미설정"),
            "romCount": rom_count, "metadataCount": metadata_count,
            "romSizeBytes": rom_size_bytes,
        })

    def set_masterdb_path(self, path):
        """[P0-7] Import/Export처럼 self.db/self._sqlite를 사용 중인 heavy job이
        "masterdb"를 busy로 잡고 있는 동안 경로를 바꾸면, 그 job이 마저 쓰던
        DB 객체가 도중에 교체돼버린다(self.db/self._sqlite를 여기서 바로
        갈아끼움) - worker 스레드가 이미 들고 있는 참조는 그대로지만, 그
        스레드가 self.db_lock 밖에서 self.db를 다시 읽는 지점이 있다면 새
        경로의(비어 있거나 다른) DB를 실수로 건드릴 수 있다. Delete/Rename과
        동일하게 _target_busy_error()로 막는다."""
        busy_err = self._target_busy_error("masterdb")
        if busy_err:
            return busy_err
        try:
            dbmod.ensure_masterdb_structure(path)
            self.cfg["masterdb"]["root"] = path
            self.cfg["masterdb"]["status"] = "정상"
            cfgmod.save_config(self.cfg)
            self.db = dbmod.load_db(path)
            if self._sqlite:
                self._sqlite.close()
            self._sqlite = SQLiteRepository.from_masterdb_root(path)
            self._sqlite.replace_from_dict(self.db, self.cfg.get("locals", []))
            return _ok(True)
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # Local CRUD
    # ------------------------------------------------------------------
    def list_locals(self):
        return _ok(self.cfg.get("locals", []))

    def check_local_structure(self, rom_path, metadata_path, frontend):
        try:
            internal_frontend = GUI_FRONTEND_TO_INTERNAL.get(frontend, frontend)
            status, msg = detect_local_structure(rom_path, metadata_path, metadata_path, internal_frontend)
            return _ok({"status": status, "message": msg})
        except Exception as e:
            return _err(str(e))

    def add_local(self, label, frontend, rom_path, metadata_path):
        try:
            internal_frontend = GUI_FRONTEND_TO_INTERNAL.get(frontend, frontend)
            if internal_frontend not in cfgmod.SUPPORTED_FRONTENDS:
                return _err(f"지원하지 않는 Frontend입니다: {frontend}")
            if not cfgmod.can_add_local(self.cfg):
                return _err(f"GameListSet은 최대 {cfgmod.MAX_LOCALS}개까지 등록할 수 있습니다.")
            entry = cfgmod.add_local(self.cfg, label, internal_frontend)
            entry["rom_path"] = rom_path or ""
            entry["metadata_path"] = metadata_path
            entry["media_path"] = metadata_path
            entry["rom_metadata_same_dir"] = cfgmod.FRONTEND_ROM_METADATA_SAME_DIR.get(internal_frontend, False)
            status, _msg = detect_local_structure(rom_path, metadata_path, metadata_path, internal_frontend)
            entry["status"] = {"valid": "정상", "warning": "경고", "invalid": "오류"}.get(status, "미설정")
            entry["frontendLabel"] = frontend  # GUI 표시용 원래 라벨도 함께 보관
            cfgmod.save_config(self.cfg)
            return _ok(entry)
        except Exception as e:
            return _err(str(e))

    def update_local_paths(self, local_id, rom_path, metadata_path):
        """[GameListSet 경로 변경] 기존 Local의 ROM/Metadata 경로를 재설정한다.
        add_local()과 동일한 구조 감지를 거치되, 새 항목을 만들지 않고 기존 entry를
        갱신한다. 경로가 바뀌면 이전 스캔 결과(스캔 캐시)는 더 이상 유효하지 않으므로
        같이 비운다 - 다음 조회에서 새 경로 기준으로 다시 스캔된다.

        [P0-6] 이 Local에 대한 Scan/Import/Export가 진행 중일 때 경로를 바꾸면,
        아직 끝나지 않은 phase가 이전 경로 기준으로 읽은 결과를 새 경로 기준
        entry에 이어 붙이는 등 phase마다 서로 다른 경로를 섞어 쓰는 race가
        생길 수 있다. Delete/Rename과 마찬가지로 _target_busy_error()로 막는다."""
        try:
            busy_err = self._target_busy_error(local_id)
            if busy_err:
                return busy_err
            entry = self._find_local(local_id)
            if entry is None:
                return _err("존재하지 않는 GameListSet입니다.")
            frontend = entry.get("frontend", "")
            entry["rom_path"] = rom_path or ""
            entry["metadata_path"] = metadata_path
            entry["media_path"] = metadata_path
            status, _msg = detect_local_structure(rom_path, metadata_path, metadata_path, frontend)
            entry["status"] = {"valid": "정상", "warning": "경고", "invalid": "오류"}.get(status, "미설정")
            self._local_scan_cache.pop(local_id, None)
            cfgmod.save_config(self.cfg)
            return _ok(entry)
        except Exception as e:
            return _err(str(e))

    def delete_local(self, local_id):
        busy_err = self._target_busy_error(local_id)
        if busy_err:
            return busy_err
        try:
            cfgmod.remove_local(self.cfg, local_id)
            cfgmod.save_config(self.cfg)
            return _ok(True)
        except Exception as e:
            return _err(str(e))

    def set_local_target_capacity(self, local_id, target_capacity_bytes):
        """Local의 목표 용량(바이트)을 설정. None/0 이하는 '제한 없음'으로 저장."""
        try:
            entry = next((l for l in self.cfg.get("locals", []) if l["id"] == local_id), None)
            if entry is None:
                return _err("존재하지 않는 GameListSet입니다.")
            value = None
            if target_capacity_bytes is not None:
                value = int(target_capacity_bytes)
                if value <= 0:
                    value = None
            entry["target_capacity_bytes"] = value
            cfgmod.save_config(self.cfg)
            return _ok(entry)
        except Exception as e:
            return _err(str(e))

    def scan_local(self, local_id, progress_cb=None, read_media_types=None):
        """
        Refresh List. gamelist.xml에 존재하는 항목 전체를 기준으로 목록을 만든다
        (ROM 파일이 실제로 있는지 여부와 무관하게 - Missing ROM 상태도 표시되어야 하므로).

        [BUG FIX] 예전엔 실제 발견된 ROM 파일 기준으로만 목록을 만들어서, gamelist.xml에는
        있지만 ROM 파일이 없는 항목이 리스트에서 통째로 빠졌었다.

        상태 분류 (video 제외 media 기준):
          완료(Normal): ROM 매칭 + media 전부 있음
          부분(Partial): ROM 매칭 + media 일부만 있음 (또는 전부 없음 -> missingMedia=True 별도 표시)
          누락(Missing ROM): gamelist엔 있지만 ROM 파일 없음
          duplicate: 이 Local 내에서 정규화 타이틀이 겹치는 ROM(둘 다 media 전부 있는 경우만)

        read_media_types: [체감 속도, Scan 2단계] None이면(기본, 기존 동작) 전체 media
        타입을 다 읽어서 완전히 정확한 status/duplicate 판정을 한다 - 이 결과만
        runtime_cache에 "확정" 결과로 저장된다(last_games/last_games_token). 리스트를
        (예: ["covers"]) 넘기면 그 타입만 읽어 훨씬 빠르지만, status/duplicate 판정이
        불완전할 수 있어(예: 커버만 봤으니 나머지가 없어도 "부분"으로만 뜸) 결과에
        "mediaPending": True가 붙고 cache에는 저장하지 않는다 - 뒤이어 read_media_types=None
        으로 한 번 더 돌아야 정확한 결과가 확정된다(start_scan_local()의 2단계 구조 참고).
        """
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        self._diag("SCAN_LOCAL_START", local_id=local_id, label=local.get("label"), frontend=local.get("frontend"),
                   rom_path=local.get("rom_path", ""), metadata_path=local.get("metadata_path", ""), media_path=local.get("media_path", ""),
                   masterdb_loaded=bool(self.db), masterdb_roms=len((self.db or {}).get("roms", {})))
        # [버그 수정] 스캔은 서로 독립된 두 단계로 진행되는데(1: 시스템별 gamelist 열거,
        # 2: 항목별 media 읽기 - 훨씬 느림) 예전엔 각 단계가 progress_cb에 자기 단계
        # 안에서의 0~100%를 그대로 보고했다. 그래서 1단계가 끝나고 2단계로 넘어가는
        # 순간 진행률이 뒤로(예: 28% -> 15%) 튀어서 마치 멈추거나 거꾸로 가는 것처럼
        # 보였다. 1단계는 시스템 개수가 적어 항상 빠르므로 고정 비중(5%)만 배분하고,
        # 실제 오래 걸리는 2단계에 나머지(95%)를 배분해 하나의 누적 퍼센트로 합친다.
        PHASE1_SHARE = 5

        def _phase_progress(phase, current, total, label):
            if not progress_cb:
                return
            frac = (current / total) if total else 1
            if phase == 1:
                pct = frac * PHASE1_SHARE
            else:
                pct = PHASE1_SHARE + frac * (100 - PHASE1_SHARE)
            progress_cb(round(pct), 100, label)

        try:
            from importers import get_importer
            runtime_cache = self._local_scan_cache.setdefault(local_id, {})
            result = scan_local(local, runtime_cache=runtime_cache, media_types=read_media_types)
            self._diag("SCAN_LOCAL_RAW", local_id=local_id, rom_list_count=len(result.get("rom_list", [])),
                       systems=sorted((result.get("per_system") or {}).keys()), scan_token=str(result.get("scan_token")),
                       cache_token=str(runtime_cache.get("last_games_token")), cached_games=len(runtime_cache.get("last_games") or []))
            # Raw scan token이 동일하면 metadata/media를 다시 읽어 게임 목록을 재구성할 필요가 없다.
            # 이것이 10,000 ROM Refresh에서 두 번째 이후 실행 시간을 줄이는 핵심 경로다.
            if runtime_cache.get("last_games_token") == result.get("scan_token") and runtime_cache.get("last_games") is not None:
                cached_games = runtime_cache["last_games"]
                self._diag("SCAN_LOCAL_CACHE_HIT", local_id=local_id, games=len(cached_games),
                           has_cover=sum(1 for g in cached_games if g.get("hasCover")),
                           missing_rom=sum(1 for g in cached_games if not g.get("romMatched", True)))
                return _ok({"stats": local.get("stats", {}), "status": local.get("status", "정상"),
                            "games": cached_games, "notImplemented": False})
            runtime_cache["last_result"] = result
            cfgmod.save_config(self.cfg)

            importer = get_importer(local["frontend"])
            list_gamelist_entries_fn = getattr(importer, "list_gamelist_entries", None)
            not_implemented = False

            if list_gamelist_entries_fn is None:
                # [폴백] Pegasus/LaunchBox 등 아직 gamelist 전체 열거를 지원하지 않는 Frontend는
                # 기존 방식(발견된 ROM 파일 기준)으로 동작한다. Missing ROM 표시는 안 되지만
                # 최소한 회귀는 없다.
                games = []
                for rom_idx, rom in enumerate(result["rom_list"], start=1):
                    if progress_cb:
                        progress_cb(rom_idx, len(result["rom_list"]), rom["filename"])
                    try:
                        fields = importer.read_metadata_fields(local["metadata_path"], rom["system"], rom["filename"])
                    except NotImplementedError:
                        not_implemented = True
                        fields = None
                    except Exception:
                        fields = None
                    title = fields.get("name", "") if fields else ""
                    desc = fields.get("desc", "") if fields else ""
                    genre = fields.get("genre", "") if fields else ""
                    region = fields.get("region", "") if fields else ""
                    rating = fields.get("rating", "") if fields else ""
                    has_title, has_desc = bool(title.strip()), bool(desc.strip())
                    status = "완료" if (has_title and has_desc) else ("부분" if (has_title or has_desc) else "누락")
                    games.append({
                        "romKey": f"{rom['system']}|{rom['filename']}", "system": rom["system"], "file": rom["filename"],
                        "title": title, "desc": desc, "genre": genre, "region": region, "rating": rating,
                        "status": status, "local": local_id, "romMatched": True, "missingMedia": False, "duplicate": False, "noMetadata": False,
                    })
                if read_media_types is None:
                    runtime_cache["last_games_token"] = result.get("scan_token")
                    runtime_cache["last_games"] = games
                return _ok({"stats": local["stats"], "status": local["status"], "games": games, "notImplemented": not_implemented})

            # ------------------------------------------------------------
            # [신규 경로] gamelist.xml 전체 열거 기준
            # ------------------------------------------------------------
            from utils import normalize_title
            systems = importer.list_systems(local["rom_path"], local["metadata_path"])
            self._diag("SCAN_LOCAL_SYSTEMS", local_id=local_id, system_count=len(systems), systems=list(systems))
            raw_entries = []  # (system, filename, fields, rom_matched)
            title_groups = {}  # normalize_title -> [(system, filename), ...] (media 완전한 것만)

            for sys_idx, sys_name in enumerate(systems, start=1):
                if progress_cb:
                    _phase_progress(1, sys_idx, len(systems), sys_name)
                try:
                    # [BUG FIX] importer.list_roms()는 dict가 아니라 Path 객체 리스트를 반환한다.
                    # r["filename"]으로 잘못 접근해서 매번 예외가 조용히 삼켜지고(rom_files가
                    # 항상 빈 set이 되어) romMatched가 항상 False로 나오던 버그.
                    rom_files = {r.name for r in importer.list_roms(local["rom_path"], sys_name)}
                except Exception:
                    rom_files = set()
                try:
                    entries = list_gamelist_entries_fn(local["metadata_path"], sys_name)
                    entries_error = None
                except Exception as exc:
                    entries = []
                    entries_error = repr(exc)
                self._diag("SCAN_LOCAL_SYSTEM", local_id=local_id, system=sys_name, rom_files=len(rom_files),
                           gamelist_entries=len(entries), gamelist_error=entries_error)

                gamelist_filenames = set()
                for e in entries:
                    filename, fields = e["filename"], e["fields"]
                    rom_matched = filename in rom_files
                    gamelist_filenames.add(filename)
                    raw_entries.append((sys_name, filename, fields, rom_matched, False))

                # [신규] ROM 파일은 있지만 gamelist.xml에 항목이 아예 없는 것들도 표시한다
                # (metadata 없음 - JS 쪽에서 파일명을 빨간색으로 강조 표시).
                empty_fields = {k: ("" if k != "tags" else []) for k in dbmod.META_FIELD_KEYS}
                for orphan_filename in sorted(rom_files - gamelist_filenames):
                    raw_entries.append((sys_name, orphan_filename, dict(empty_fields), True, True))

            # [버그 수정] ES-DE alias 시스템(msx/msx1, genesis/megadrive 등)이 실제로 둘 다
            # 존재하고 둘 다 같은 파일명의 gamelist 항목을 갖고 있으면(예: 스크래퍼가 두
            # 폴더 모두에 같은 메타데이터를 만들어둔 경우), Local 목록에 같은 게임이 두 줄로
            # 보였다. MasterDB Import는 이미 canonical_system()으로 이런 경우를 하나로
            # 합치므로(내용이 같으면 duplicates_skipped) Local 목록도 같은 기준(canonical
            # system + 파일명)으로 미리 합쳐서 보여준다. romKey/표시 system은 승자 쪽을
            # 그대로 쓴다 - import/export 엔진이 쓰는 importers.scan.scan_local()의 원본
            # 처리는 건드리지 않으므로 실제 Import/Export 동작에는 영향이 없다(표시 전용
            # 병합).
            # [버그 수정 v2] 승자를 "ROM 매칭 여부 -> metadata 존재 여부" 순으로만 골랐더니,
            # 두 alias 폴더 모두 metadata는 있지만 media는 한쪽에만 있는 실사용 케이스(예:
            # msx1에만 covers/screenshots 등이 있고 msx는 gamelist만 있고 media가 아예 없음)
            # 에서 media가 없는 쪽이 알파벳순으로 먼저 걸려 승자가 되어 media가 통째로
            # 사라져 보였다. "실제 media 존재 여부"를 ROM 매칭 다음, metadata 존재 여부보다
            # 먼저 보는 기준으로 승자를 고른다.
            # [버그 수정 v3] "승자 하나만 쓰는" 방식은 두 alias 폴더가 media 타입을 나눠
            # 갖고 있으면(예: msx엔 covers만, msx1엔 screenshots만) 여전히 한쪽만 반영되는
            # 문제가 있었다. 승자는 표시용 system/filename/metadata 기준으로만 고르고,
            # media는 아래 media-읽기 패스에서 그룹 내 다른 위치(alt location)들도 전부
            # 읽어서 "이미 있는 타입은 승자 값 유지, 없는 타입만 채우기"로 합집합 병합한다.
            canonical_groups = {}
            for idx, entry in enumerate(raw_entries):
                canon = cfgmod.canonical_system(local, entry[0])
                canonical_groups.setdefault((canon, entry[1]), []).append(idx)
            media_alt_locations = {}  # (winner_sys, filename) -> [alt_sys, ...] to union media from
            if any(len(indices) > 1 for indices in canonical_groups.values()):
                has_media_fn = getattr(importer, "has_media", None)

                def _entry_has_media(idx):
                    if not has_media_fn:
                        return False
                    sys_name_i, filename_i = raw_entries[idx][0], raw_entries[idx][1]
                    try:
                        return bool(has_media_fn(local["media_path"], sys_name_i, filename_i))
                    except Exception:
                        return False

                merged_entries = []
                for indices in canonical_groups.values():
                    if len(indices) == 1:
                        merged_entries.append(raw_entries[indices[0]])
                        continue
                    winner = max(indices, key=lambda i: (raw_entries[i][3], _entry_has_media(i), not raw_entries[i][4]))
                    winner_entry = raw_entries[winner]
                    merged_entries.append(winner_entry)
                    alt_systems = [raw_entries[i][0] for i in indices if i != winner]
                    if alt_systems:
                        media_alt_locations[(winner_entry[0], winner_entry[1])] = alt_systems
                raw_entries = merged_entries

            # 1차 패스: media 완전한 항목들의 정규화 타이틀을 모아서 중복 판별 준비
            # 진행률은 "시스템 수"가 아니라 실제 게임 파일 수를 기준으로 표시한다.
            # 기존 구현은 시스템명(1/4, 2/4...)만 보고하고 실제 파일 처리 중에는
            # 아무 변화가 없어 사용자가 멈춘 것으로 오해하기 쉬웠다.
            media_cache = {}
            media_paths_cache = {}
            metadata_only_count = sum(1 for e in raw_entries if not e[3])
            self._diag("SCAN_LOCAL_ENTRIES", local_id=local_id, raw_entries=len(raw_entries),
                       rom_matched=sum(1 for e in raw_entries if e[3]), metadata_only=metadata_only_count,
                       note="Media index is built for metadata-only entries too, so Missing ROM games can still show Cover/Media in Card View")
            # Media belongs to the metadata entry, not to the physical ROM.  ES-DE may
            # contain a complete gamelist/media set while the ROM directory is empty
            # (for example when metadata is being prepared before ROMs are copied).
            # Therefore every gamelist entry must participate in media indexing.
            progress_total = max(1, len(raw_entries))
            progress_current = 0
            for sys_name, filename, fields, rom_matched, no_metadata in raw_entries:
                progress_current += 1
                if progress_cb:
                    _phase_progress(2, progress_current, progress_total, filename)
                try:
                    media_dict = importer.read_media(local["media_path"], sys_name, filename, fields.get("name", ""), media_types=read_media_types)
                except NotImplementedError:
                    not_implemented = True
                    media_dict = {}
                except Exception:
                    media_dict = {}
                # alias 그룹 병합(위 참고): 다른 위치(alt system)에만 있는 media 타입으로
                # 빈 곳만 채운다 - 승자 쪽에 이미 있는 타입은 덮어쓰지 않는다.
                for alt_sys in media_alt_locations.get((sys_name, filename), []):
                    try:
                        alt_media = importer.read_media(local["media_path"], alt_sys, filename, fields.get("name", ""), media_types=read_media_types)
                    except Exception:
                        alt_media = {}
                    for mtype, val in alt_media.items():
                        if not media_dict.get(mtype):
                            media_dict[mtype] = val
                media_types = set(media_dict.keys()) - {"videos"}
                media_cache[(sys_name, filename)] = media_types
                media_paths_cache[(sys_name, filename)] = media_dict
                if NON_VIDEO_MEDIA_TYPES.issubset(media_types):
                    t = normalize_title(fields.get("name", ""))
                    if t:
                        title_groups.setdefault(t, []).append((sys_name, filename))

            duplicate_keys = set()
            for t, keys in title_groups.items():
                if len(keys) > 1:
                    duplicate_keys.update(keys)

            # Metadata-only ES-DE entries are first-class games.  Keep the summary in sync
            # with the same source used by the GameList so Dashboard/navigation can show
            # Missing ROM immediately without requiring a second scan.
            missing_rom_count = sum(1 for _sys, _fn, _fields, matched, _nometa in raw_entries if not matched)
            metadata_count = sum(1 for _sys, _fn, fields, _matched, _nometa in raw_entries if fields and any(str(fields.get(k, "") or "").strip() for k in dbmod.META_FIELD_KEYS if k != "tags"))
            local["stats"]["missing_rom"] = missing_rom_count
            local["stats"]["metadata_count"] = metadata_count
            games = []
            for sys_name, filename, fields, rom_matched, no_metadata in raw_entries:
                title, desc, genre = fields.get("name", ""), fields.get("desc", ""), fields.get("genre", "")
                region, rating = fields.get("region", ""), fields.get("rating", "")

                if not rom_matched:
                    status, missing_media = "누락", False
                else:
                    media_types = media_cache.get((sys_name, filename), set())
                    if NON_VIDEO_MEDIA_TYPES.issubset(media_types):
                        status, missing_media = "완료", False
                    elif len(media_types) == 0:
                        status, missing_media = "부분", True
                    else:
                        status, missing_media = "부분", False

                games.append({
                    "romKey": f"{sys_name}|{filename}", "system": sys_name, "file": filename,
                    "title": title, "desc": desc, "genre": genre, "region": region, "rating": rating,
                    "status": status, "local": local_id,
                    "romMatched": rom_matched, "missingMedia": missing_media,
                    "duplicate": (sys_name, filename) in duplicate_keys,
                    # [신규] ROM은 있지만 gamelist.xml에 항목 자체가 없는 경우 - JS에서 파일명을
                    # 빨간색으로 강조 표시하도록 플래그 전달.
                    "noMetadata": no_metadata,
                    # [BUG FIX] Preview(그리드) 모드에서 커버가 있어도 안 보이던 문제 -
                    # hasCover가 아예 응답에 없어서 Preview 지연로딩이 트리거 자체를 안 했음.
                    "hasCover": "covers" in media_cache.get((sys_name, filename), set()),
                    # [체감 속도, Scan 2단계] read_media_types가 제한된 패스(1단계)면
                    # status/duplicate가 아직 확정이 아니라는 표시 - 뒤이은 2단계
                    # (read_media_types=None)가 끝나면 정확한 값으로 갱신된다.
                    "mediaPending": read_media_types is not None,
                })
            if read_media_types is None:
                # [체감 속도 리뷰 반영] 이 스캔이 진행되는 동안(gamelist.xml을 읽은
                # 시점 이후) save_local_game_fields()로 저장된 metadata 수정이 있으면
                # pending_edits_during_scan에 쌓여 있다 - 방금 계산한 games는 그 저장
                # "이전" 스냅샷이라 그대로 last_games에 덮어쓰면 사용자가 막 저장한
                # 값이 캐시에서 사라진 것처럼 보인다(파일 자체는 항상 정확함). 최종
                # 커밋 직전에 그 수정들을 다시 얹어서 파일과 캐시가 어긋나지 않게 한다.
                pending_edits = runtime_cache.pop("pending_edits_during_scan", None)
                if pending_edits:
                    games_by_key = {g["romKey"]: g for g in games}
                    for rom_key, normalized in pending_edits.items():
                        g = games_by_key.get(rom_key)
                        if g is not None:
                            g.update({"title": normalized.get("name", ""), "desc": normalized.get("desc", ""),
                                      "genre": normalized.get("genre", ""), "region": normalized.get("region", ""),
                                      "rating": normalized.get("rating", ""), "noMetadata": not bool(normalized.get("name"))})
                runtime_cache["last_games_token"] = result.get("scan_token")
                runtime_cache["last_games"] = games
                runtime_cache["last_media"] = media_paths_cache
            self._diag("SCAN_LOCAL_DONE", local_id=local_id, games=len(games), read_media_types=read_media_types,
                       has_cover=sum(1 for g in games if g.get("hasCover")),
                       missing_rom=sum(1 for g in games if not g.get("romMatched", True)),
                       no_metadata=sum(1 for g in games if g.get("noMetadata")),
                       systems=sorted({g.get("system", "") for g in games}))
            return _ok({"stats": local["stats"], "status": local["status"], "games": games, "notImplemented": not_implemented})
        except _JobCancelled:
            # 취소는 job worker(_run_job)가 처리해야 하므로 여기서 _err로 감싸지 않고 그대로 다시 던진다.
            raise
        except Exception as e:
            traceback.print_exc()
            return _err(str(e))

    def reset_metadata(self, local_id):
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        try:
            removed = reset_metadata(local)
            return _ok(removed)
        except NotImplementedError as e:
            return _err(str(e))
        except Exception as e:
            return _err(str(e))

    def start_reset_metadata(self, local_id):
        """[신규] CleanUp을 진행률 표시가 가능한 백그라운드 job으로 실행."""
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        job_id = self._run_job(lambda cb: reset_metadata(local, progress_cb=cb))
        return _ok({"jobId": job_id})

    def orphan_cleanup(self, local_id):
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        try:
            removed = orphan_cleanup(local)
            return _ok({"removedCount": len(removed), "removed": removed})
        except NotImplementedError as e:
            return _err(str(e))
        except Exception as e:
            return _err(str(e))

    def start_orphan_cleanup(self, local_id):
        """[신규] Prune Data를 진행률 표시가 가능한 백그라운드 job으로 실행."""
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        busy_err = self._target_busy_error(local_id)
        if busy_err:
            return busy_err

        def run(cb):
            removed = orphan_cleanup(local, progress_cb=cb)
            return {"removedCount": len(removed), "removed": removed}

        job_id = self._run_job(run)
        return _ok({"jobId": job_id})

    def start_scan_local(self, local_id):
        """[신규] Refresh List를 진행률 표시가 가능한 백그라운드 job으로 실행.

        [체감 속도, Scan 2단계] performance.defer_video_media가 켜져 있으면 (1)
        메타데이터+커버만 먼저 읽어서 그 결과로 화면을 바로 그릴 수 있게 하고, (2)
        나머지 media(비디오 포함)를 이어서 백그라운드로 읽어 정확한 상태/중복 판정을
        완성한다. 1단계 결과에는 "followUpJobId"가 들어있어 JS가 그 job을 조용히
        폴링해서 2단계가 끝나면 화면을 다시 갱신할 수 있다(_start_phased_media_job의
        attach_followup_job_id 참고). 꺼져 있으면 예전처럼 한 번에 전부 읽는다."""
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")

        # [P0-4, 리뷰 반영으로 재수정] 이 Local에 대한 Scan chain이 이미 진행
        # 중이면(대기/1단계/2단계 어느 단계든) 새로 만들지 않고 "지금 실제로
        # 진행 중인 phase"의 job_id를 그대로 돌려준다(root=phase 1의 job_id가
        # 아니다 - on_phase_job_created 콜백이 phase가 바뀔 때마다 이 값을
        # 최신으로 갱신해준다. 예전엔 phase 1의 job_id만 저장해서, phase 2가
        # 실행 중인데도 이미 done인 phase 1 job을 들고 있는 불일치가 있었다 -
        # 그 job_id로 cancel_job()을 부르면 이미 done이라 아무 일도 안 하고
        # 조용히 성공 응답만 돌려줘서, "취소했는데 실제로는 취소 안 됨" 버그로
        # 이어질 수 있었다).
        existing_job_id = self._active_scan_jobs.get(local_id)
        if existing_job_id is not None:
            return _ok({"jobId": existing_job_id})

        def make_phase_run(phase_media_types, is_last_phase):
            def run(cb):
                # [크래시 리포트 반영 -> Queue 구조] 다른 Local의 Scan/Import/Export가
                # 이미 돌고 있으면 이 phase job 자체가 _run_heavy_job() 큐에서 자기
                # 차례를 기다린다(get_job_progress에 "대기 중 (앞에 N개)"로 그대로
                # 보임) - 그래서 여기서 별도로 lock을 잡을 필요가 없다.
                # [주의] return을 try 블록 안에서 바로 하면 안 된다 - try/except/else의
                # else는 try 블록이 return 없이 끝까지 실행돼야만 도는데, 여기선 항상
                # try 안에서 return해버려서 else가 영원히 실행되지 않는 버그가 있었다
                # (아래처럼 결과를 변수에 담아두고 try/except 밖에서 return해야 한다).
                try:
                    r = self.scan_local(local_id, progress_cb=cb, read_media_types=phase_media_types)
                    if not r["ok"]:
                        raise RuntimeError(r["error"])
                    result = r["data"]
                except Exception:
                    # [P0-4] 어느 phase든 실행 중 실패/취소되면 다음 phase는 시작되지
                    # 않으므로(_start_phased_media_job이 예외를 그대로 전파) 체인
                    # 전체가 끝난 것과 같다 - 마지막 phase가 아니어도 여기서 지운다.
                    self._active_scan_jobs.pop(local_id, None)
                    raise
                # [P0-4] 성공한 경우엔 마지막 phase일 때만 체인이 실제로 끝난다.
                # 큐에서 대기 중이던 phase job이 cancel_job()으로 (한 번도 실행되지
                # 못한 채) 제거된 경우엔 이 run()이 아예 호출되지 않으므로, 그 경로는
                # cancel_job() 쪽에서 별도로 지운다(아래 참고).
                if is_last_phase:
                    self._active_scan_jobs.pop(local_id, None)
                return result
            return run

        defer = self.cfg.get("performance", {}).get("defer_video_media", True)
        if defer:
            phases = [("메타데이터+커버", make_phase_run(["covers"], False)),
                      ("나머지 미디어", make_phase_run(None, True))]
        else:
            phases = [("전체", make_phase_run(None, True))]

        # [race 수정] _active_scan_jobs 등록을 job_id를 돌려받은 "뒤"에 하면 늦다 -
        # 아주 작은 fixture/빠른 job은 _start_phased_media_job()이 반환하기도
        # 전에 이미 phase 1이 끝나고 phase 2까지 시작될 수 있어서, 그 사이 다른
        # 스레드가 (아직 등록 안 된) local_id를 조회하면 "진행 중 아님"으로
        # 잘못 판단해 중복 job을 새로 만들 수 있었다. on_phase_job_created를
        # _run_heavy_job()이 worker thread를 띄우기 전에(=job이 끝나기 전에
        # 반드시) 동기 호출하도록 만들어서, 등록이 항상 실행보다 먼저 끝나게
        # 한다 - 게다가 phase가 바뀔 때마다 다시 불리므로 이 값은 항상 "현재
        # 진행 중인 phase"를 가리킨다.
        job_id = self._start_phased_media_job(
            (local_id,), phases, mutates_db=False, attach_followup_job_id=True, kind="scan",
            on_phase_job_created=lambda jid: self._active_scan_jobs.__setitem__(local_id, jid),
        )
        return _ok({"jobId": job_id})

    def start_import_local_to_masterdb(self, local_id, target_roms=None):
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")

        # [체감 속도] videos는 뒤로 미루고 커버+메타데이터부터 끝낸다 (performance.
        # defer_video_media, 기본 켜짐). 진행되는 동안 이 Local/masterdb는 삭제/
        # 이름변경이 막힌다 - _start_media_job 참고.
        primary_media, deferred_media = self._split_media_for_deferred_video(None)

        def run_primary(cb):
            with self._db_rollback_guard():
                t0 = time.time()
                result = import_local_to_masterdb(
                    local, self.cfg["masterdb"]["root"], self.db, progress_cb=cb,
                    target_roms=target_roms, sqlite_repo=self._sqlite,
                    selected_media_types=primary_media,
                )
                t1 = time.time()
                with self._db_lock:
                    # [v0.5 8단계] import_engine이 이미 targeted native SQLite write를 했으므로
                    # 보통은 sync_sqlite=False로 전체 재구축을 생략한다. 레거시 alias 시스템명
                    # 병합이 있었던 회차만 예외적으로 전체 재동기화(sync_sqlite=True)로 안전하게
                    # 처리한다 (그 rom들은 native mirror가 못 따라감 - import_engine.py 참고).
                    # [버그 수정, 2026-09-02] 위 문단과 반대로 `not`이 붙어있어서 정확히
                    # alias 병합이 일어난 그 순간에만 재동기화를 건너뛰고 있었다 - SQLite가
                    # JSON(self.db)과 어긋난 채로 남아 ArchiveDB 목록(SQLite 기반)에서
                    # ROM이 사라져 보이는데 전체 개수(JSON 기반)는 정상으로 뜨는 원인이었다.
                    self._save_db(sync_sqlite=bool(result.get("alias_merge_occurred", False)))
                t2 = time.time()
                # [성능 진단용] "scan+metadata읽기+media복사+native SQLite write" 구간과
                # "_save_db(JSON write / 필요시 전체 SQLite 재구축)" 구간을 나눠서 기록한다 -
                # 다음에 또 느려지면 로그만 보고 어느 구간이 범인인지 바로 알 수 있게.
                self._diag("IMPORT_TIMING", local_id=local_id, target_roms=len(target_roms) if target_roms else "all",
                           imported=result.get("imported"), duplicates_skipped=result.get("duplicates_skipped"),
                           alias_merge_occurred=result.get("alias_merge_occurred"),
                           engine_seconds=round(t1 - t0, 3), save_db_seconds=round(t2 - t1, 3), total_seconds=round(t2 - t0, 3))
                return result

        def make_deferred_run():
            def run_videos(cb):
                with self._db_rollback_guard():
                    result = import_local_to_masterdb(
                        local, self.cfg["masterdb"]["root"], self.db, progress_cb=cb,
                        target_roms=target_roms, sqlite_repo=self._sqlite,
                        selected_media_types=deferred_media,
                    )
                    with self._db_lock:
                        self._save_db(sync_sqlite=False)
                    return result
            return run_videos

        job_id = self._start_media_job(
            (local_id, "masterdb"), run_primary,
            make_deferred_run if deferred_media else None, mutates_db=True,
        )
        return _ok({"jobId": job_id})

    def import_local_to_masterdb(self, local_id):
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        try:
            with self._db_rollback_guard():
                t0 = time.time()
                result = import_local_to_masterdb(local, self.cfg["masterdb"]["root"], self.db, sqlite_repo=self._sqlite)
                t1 = time.time()
                # [버그 수정, 2026-09-02] `not`이 반대로 붙어있던 SQLite 재동기화 조건 -
                # start_import_local_to_masterdb() 위 주석/수정 참고.
                self._save_db(sync_sqlite=bool(result.get("alias_merge_occurred", False)))
                self._diag("IMPORT_TIMING", local_id=local_id, target_roms="all",
                           imported=result.get("imported"), duplicates_skipped=result.get("duplicates_skipped"),
                           alias_merge_occurred=result.get("alias_merge_occurred"),
                           engine_seconds=round(t1 - t0, 3), save_db_seconds=round(time.time() - t1, 3))
            return _ok(result)
        except Exception as e:
            traceback.print_exc()
            return _err(str(e))

    # ------------------------------------------------------------------
    # [신규] Export 3가지 모드: MetaData / Roms / MetaData+Roms
    # (MasterDB가 이제 ROM 실물 파일도 저장한다 - NAS 등에 백업/중복정리 목적)
    # ------------------------------------------------------------------
    def check_export_disk_space(self, local_id, mode, rom_keys=None):
        """ROM 복사가 필요한 모드일 때, MasterDB의 ROM 저장 드라이브에 여유 공간이
        충분한지 미리 계산한다. (이미 MasterDB에 저장된 ROM은 다시 안 세므로, 실제로
        새로 필요한 용량만 정확히 잡는다.)"""
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        if mode not in ("roms", "metadata_roms"):
            return _ok({"ok": True, "required": 0, "free": 0, "shortage": 0, "requiredFormatted": "0", "freeFormatted": "-", "shortageFormatted": "0"})
        try:
            runtime_cache = self._local_scan_cache.setdefault(local_id, {})
            scan_result = scan_local(local, runtime_cache=runtime_cache)
            masterdb_root = self.cfg["masterdb"]["root"]
            target_set = set(rom_keys or [])
            required = 0
            for rom in scan_result["rom_list"]:
                if target_set and f"{cfgmod.canonical_system(local, rom['system'])}|{rom['filename']}" not in target_set and f"{rom['system']}|{rom['filename']}" not in target_set:
                    continue
                system = cfgmod.canonical_system(local, rom["system"])
                dest = dbmod.rom_storage_path(masterdb_root, system, rom["filename"])
                if not dest.exists():
                    required += rom.get("size", 0)
            rom_dir = dbmod.db_paths(masterdb_root)["rom_dir"]
            check = disk_utils.check_space_for_copy(rom_dir, required)
            check["requiredFormatted"] = disk_utils.format_bytes(check["required"])
            check["freeFormatted"] = disk_utils.format_bytes(check["free"])
            check["shortageFormatted"] = disk_utils.format_bytes(check["shortage"])
            return _ok(check)
        except Exception as e:
            return _err(str(e))

    def _sha256_worker_loop(self):
        """[P0-8] Copy/Import/Export critical path와 완전히 분리된 백그라운드
        SHA256 계산 스레드. 큐가 비면 블로킹 get()으로 대기하다가(바쁜 대기 없음)
        항목이 들어오면 하나씩 처리한다. 파일을 읽어 해시를 계산하는 무거운
        부분은 락 밖에서 하고, SQLite에 쓰는 짧은 순간만 _db_lock을 잡는다 -
        해시 계산 자체가 다른 job을 block하는 일이 없어야 하기 때문이다."""
        while not self._sha256_stop.is_set():
            try:
                item = self._sha256_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            _priority, _seq, system, filename, file_path = item
            if system is None:  # 종료 신호(_SHA256_STOP_SENTINEL)
                self._sha256_queue.task_done()
                break
            try:
                if self._sqlite is not None:
                    key = dbmod.make_rom_key(system, filename)
                    with self._db_lock:
                        already = self._sqlite.get_rom_hash(key)
                    if already is None:
                        digest = dbmod.file_sha256(file_path)
                        if digest:
                            with self._db_lock:
                                self._sqlite.set_rom_hash(key, digest)
            except Exception:
                pass
            finally:
                self._sha256_queue.task_done()

    def request_rom_hash(self, system, filename, file_path, priority=2):
        """[P0-8] SHA256 계산을 백그라운드 큐에 요청한다(즉시 계산하지 않음).
        priority가 낮을수록 먼저 처리된다 - 0=현재 Detail, 1=Compare, 2=방금
        추가된 ROM(기본값), 3=나머지. 같은 priority 안에서는 요청한 순서대로
        처리된다(내부 seq 카운터로 tie-break - 그렇지 않으면 PriorityQueue가
        priority가 같을 때 튜플의 다음 요소(문자열)를 비교하려다가 예외를 던질
        수 있다)."""
        self._sha256_seq += 1
        self._sha256_queue.put((priority, self._sha256_seq, system, filename, str(file_path)))

    def _cache_rom_hash(self, system, filename, file_path):
        """[P0-8] ROM이 처음 복사된 직후 SHA256 계산을 백그라운드 큐에 요청한다
        (더 이상 여기서 동기로 계산하지 않는다 - Copy Job의 critical path/
        _db_lock을 오래 잡아두지 않기 위함). ArchiveDB가 설정 안 돼 있으면
        (self._sqlite is None, 예: Local->Local 직접 복사가 ArchiveDB 없이
        동작하는 경우) 캐시할 곳이 없으니 조용히 건너뛴다."""
        if self._sqlite is None:
            return
        self.request_rom_hash(system, filename, file_path, priority=2)

    def _copy_roms_to_masterdb(self, local, progress_cb=None, target_roms=None, scan_result=None):
        """ROM 실물 파일을 MasterDB 저장소로 복사. 이미 저장된 ROM은 건너뛴다.

        scan_result: [P1-1] 이미 계산된 scan_local() 결과가 있으면 재사용한다
        (없으면 새로 스캔) - 호출부가 이미 같은 Local을 스캔해뒀다면 여기서
        또 스캔하지 않는다."""
        masterdb_root = self.cfg["masterdb"]["root"]
        scan_result = scan_result or scan_local(local)
        rom_list = scan_result["rom_list"]
        if target_roms is not None:
            wanted = set(target_roms)
            rom_list = [r for r in rom_list if (r["system"], r["filename"]) in wanted or (cfgmod.canonical_system(local, r["system"]), r["filename"]) in wanted]
        copied, skipped, errors = 0, 0, []
        total = max(1, len(rom_list))
        for idx, rom in enumerate(rom_list, start=1):
            if progress_cb:
                progress_cb(idx, total, rom["filename"])
            system = cfgmod.canonical_system(local, rom["system"])
            dest = dbmod.rom_storage_path(masterdb_root, system, rom["filename"])
            if dest.exists():
                skipped += 1
                continue
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(rom["path"], dest)
                copied += 1
                self._cache_rom_hash(system, rom["filename"], dest)
            except Exception as e:
                errors.append(f"{rom['filename']}: {e}")
        return {"copied": copied, "skipped": skipped, "errors": errors}

    def start_export_local_to_masterdb(self, local_id, mode, rom_keys=None, media_types=None):
        """
        mode: "metadata" | "roms" | "metadata_roms"
        - metadata: 기존과 동일 (metadata + media만 MasterDB에 반영)
        - roms: ROM 실물 파일만 MasterDB 저장소로 복사 (이미 있는 건 건너뜀)
        - metadata_roms: 위 둘 다
        ROM 복사가 포함된 모드는 실행 전 디스크 용량을 먼저 확인하고, 부족하면
        아예 시작하지 않고 바로 실패를 반환한다 (사용자 요청: 복사 중간에 실패하지 않도록).

        media_types: [신규] None이면 발견된 media 타입을 전부 복사한다(기존 동작).
        리스트를 넘기면(GameList의 Export 대화상자가 Settings > Media와 동일한
        Metadata/Media/Rom 선택 UI를 쓰게 된 것에 대응) 그 타입만 복사한다.
        """
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        if mode not in ("metadata", "roms", "metadata_roms"):
            return _err(f"알 수 없는 Export 모드입니다: {mode}")

        if mode in ("roms", "metadata_roms"):
            space = self.check_export_disk_space(local_id, mode, rom_keys)
            if not space["ok"]:
                return _err(space["error"])
            if not space["data"]["ok"]:
                d = space["data"]
                return _err(
                    f"드라이브 용량이 부족합니다. 필요: {d['requiredFormatted']}, "
                    f"여유: {d['freeFormatted']}, 부족: {d['shortageFormatted']}"
                )

        # [체감 속도, Import from ArchiveDB 3단계] "Import from ArchiveDB" 대화상자가
        # 부르는 경로다 - start_export_to_local()과 동일하게 (1) 메타데이터+커버
        # (2) 나머지 미디어 (3) 비디오 3단계로 나눈다. mode가 "roms"만이면(metadata
        # 자체를 안 다룸) 나눌 media가 없으므로 단일 phase로 처리한다. ROM 복사는
        # media_types와 무관하니 첫 phase에서만 한다.
        phases_spec = (
            self._split_media_into_phases(media_types) if mode in ("metadata", "metadata_roms") else [("전체", media_types)]
        )

        # [P1-1] import_local_to_masterdb()/_copy_roms_to_masterdb()는 각자 이
        # Local을 다시 스캔해서 gamelist/media를 읽는다 - 3-phase Import가 같은
        # 스캔을 3번 반복하게 된다. phase가 시작되기 전에 한 번만 스캔해서 모든
        # phase가 같은 snapshot을 공유하게 한다(runtime_cache를 넘기므로 파일
        # 시그니처 기반 캐시도 그대로 활용됨).
        shared_scan_result = scan_local(local, runtime_cache=self._local_scan_cache.setdefault(local_id, {}))

        def make_phase_run(phase_media_types, do_rom_copy, is_first_phase):
            def run(cb):
                summary = {"metadataResult": None, "romsResult": None}
                target_roms = None
                if rom_keys:
                    target_roms = []
                    for rk in rom_keys:
                        system, filename = rk.split("|", 1)
                        target_roms.append((system, filename))
                if mode in ("metadata", "metadata_roms"):
                    t0 = time.time()
                    metadata_result = import_local_to_masterdb(
                        local, self.cfg["masterdb"]["root"], self.db, progress_cb=cb,
                        target_roms=target_roms, sqlite_repo=self._sqlite,
                        selected_media_types=phase_media_types, scan_result=shared_scan_result,
                    )
                    t1 = time.time()
                    summary["metadataResult"] = metadata_result
                    with self._db_lock:
                        # [버그 수정, 2026-09-02] `not`이 반대로 붙어있던 SQLite 재동기화 조건 -
                        # start_import_local_to_masterdb() 위 주석/수정 참고. alias 병합 여부에
                        # 따른 전체 재동기화는 1단계에서만 확인한다(alias 병합은 metadata
                        # 처리 시점에만 일어나고, 2/3단계는 media만 추가하므로 targeted write로 충분).
                        sync = bool(metadata_result.get("alias_merge_occurred", False)) if is_first_phase else False
                        self._save_db(sync_sqlite=sync)
                    self._diag("IMPORT_TIMING", local_id=local_id, mode=mode, target_roms=len(target_roms) if target_roms else "all",
                               imported=metadata_result.get("imported"), duplicates_skipped=metadata_result.get("duplicates_skipped"),
                               alias_merge_occurred=metadata_result.get("alias_merge_occurred"),
                               engine_seconds=round(t1 - t0, 3), save_db_seconds=round(time.time() - t1, 3))
                if do_rom_copy:
                    summary["romsResult"] = self._copy_roms_to_masterdb(local, progress_cb=cb, target_roms=target_roms, scan_result=shared_scan_result)
                return summary
            return run

        phases = [
            (label, make_phase_run(types, do_rom_copy=(mode in ("roms", "metadata_roms") and i == 0), is_first_phase=(i == 0)))
            for i, (label, types) in enumerate(phases_spec)
        ]

        def combine_import_results(acc, result):
            # [Parent Job lifecycle 리뷰 반영] combine_results 없이는 마지막(비디오)
            # phase의 summary만 최종 결과로 남아서, 1단계에서 실제로 import된 metadata
            # 개수가 토스트에서 사라진다.
            #
            # 처음엔 phase마다 imported/duplicates_skipped를 더하려 했는데 틀렸다 -
            # import_local_to_masterdb()는 selected_media_types와 무관하게 매 phase
            # 마다 대상 ROM 전체의 metadata 매칭을 다시 수행한다(selected_media_types는
            # media 필터링만 한다). 그래서 1단계에서 새로 추가된 ROM을 2/3단계가 다시
            # 보면 "이미 있음"으로 잡혀 duplicates_skipped가 실제로는 없던 중복만큼
            # 부풀려진다. metadata 집계로 의미 있는 숫자는 1단계뿐이므로 그대로 쓴다.
            # romsResult는 ROM 복사가 실제로 일어난 phase(항상 1개뿐) 것을 그대로 쓴다.
            if acc is None:
                return {"metadataResult": dict(result["metadataResult"]) if result.get("metadataResult") else None,
                        "romsResult": result.get("romsResult")}
            merged = dict(acc)
            if result.get("romsResult") is not None:
                merged["romsResult"] = result["romsResult"]
            return merged

        # [체감 속도] attach_followup_job_id=True - JS의 runJobWithProgress가 이
        # phase의 job이 끝났을 때 결과에 담긴 followUpJobId를 보고 진행률 바를 숨기지
        # 않은 채 다음 phase로 그대로 이어서 폴링한다("(1/N)->(2/N)->..."처럼 보임).
        job_id = self._start_phased_media_job(
            (local_id, "masterdb"), phases, mutates_db=True, attach_followup_job_id=True,
            combine_results=combine_import_results,
        )
        return _ok({"jobId": job_id})

    def copy_masterdb_game_data(self, source_key, target_key):
        """Copy metadata + media from one MasterDB ROM entry to another.
        Used by Ctrl+C / Ctrl+V for quick duplicate cleanup. The target gets a new
        latest metadata version and its ROM-level media is replaced by the source set."""
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        src = self.db.get("roms", {}).get(source_key)
        dst = self.db.get("roms", {}).get(target_key)
        if not src or not dst:
            return _err("복사 대상 게임을 찾을 수 없습니다.")
        fields = dbmod.get_default_fields(src)
        dbmod.add_version(dst, "manual-copy", fields=fields, set_as_default=True, source_system=dst.get("system", ""))
        import shutil
        from pathlib import Path
        root = self.cfg["masterdb"]["root"]
        src_media = src.get("media") or {}
        dest_paths = dbmod.db_paths(root)
        dest_dir = dest_paths["media_dir"] / dst["system"] / Path(dst["rom_filename"]).stem
        dest_dir.mkdir(parents=True, exist_ok=True)
        copied = {}
        for mt, vals in src_media.items():
            arr = vals if isinstance(vals, list) else [vals]
            out = []
            for i, item in enumerate(arr):
                if not item or not Path(item).exists(): continue
                ext = Path(item).suffix
                name = f"{mt}_{i}{ext}" if len(arr) > 1 else f"{mt}{ext}"
                dp = dest_dir / name
                shutil.copy2(item, dp)
                out.append(str(dp))
            if out: copied[mt] = out if mt in ("screenshots", "videos") else out[0]
        dst["media"] = copied
        # [v0.5 8단계 드라이브바이 수정] 이 경로가 dbmod.save_db()를 직접 불러 SQLite
        # 재동기화를 건너뛰던 것도 같은 부류의 버그였다 (JSON만 저장되고 SQLite 프로젝션은
        # 다음 전체 재동기화 전까지 stale 상태로 남음). self._save_db()로 바꿔 항상
        # SQLite도 같이 최신 상태로 유지한다.
        self._save_db()
        return _ok({"copied": True, "source": source_key, "target": target_key})

    # ------------------------------------------------------------------
    # MasterDB 게임 목록 / 대시보드
    # ------------------------------------------------------------------
    def list_masterdb_games(self):
        if not self.db:
            return _ok([])
        # v0.5 migration step: read the game projection natively from SQLite.
        # The legacy dict remains available to write paths until those paths are
        # migrated in a later step.
        if self._sqlite is not None:
            from utils import normalize_title
            rows = self._sqlite.list_roms()
            title_groups = {}
            for rom in rows:
                versions = rom.get("versions") or []
                default_id = rom.get("default_version_id")
                chosen = next((v for v in versions if v.get("version_id") == default_id), None) or (versions[-1] if versions else None)
                fields = (chosen or {}).get("fields") or {}
                title_groups.setdefault(normalize_title(fields.get("name", "")), []).append(rom["romKey"])
            duplicate_keys = {k for ks in title_groups.values() if len(ks) > 1 and ks[0].split("|",1)[0] for k in ks}
            games = []
            for rom in rows:
                versions = rom.get("versions") or []
                default_id = rom.get("default_version_id")
                chosen = next((v for v in versions if v.get("version_id") == default_id), None)
                if chosen is None and versions:
                    chosen = versions[-1]
                fields = (chosen or {}).get("fields") or {}
                media = rom.get("media") or {}
                games.append({
                    "romKey": rom["romKey"], "system": rom["system"], "file": rom["file"],
                    "title": fields.get("name", ""), "desc": fields.get("desc", ""),
                    "genre": fields.get("genre", ""), "region": fields.get("region", ""),
                    "rating": fields.get("rating", ""),
                    "status": "완료" if fields.get("name", "").strip() and fields.get("desc", "").strip() else ("부분" if fields.get("name", "").strip() or fields.get("desc", "").strip() else "누락"),
                    "missingMedia": not bool(media), "hasCover": bool(media.get("covers")),
                    "duplicate": rom["romKey"] in duplicate_keys,
                    "favorite": bool(rom.get("favorite")),
                })
            if self._shadow.enabled:
                self._shadow.compare_db_projection("list_masterdb_games", self.db, self._sqlite)
            self._diag("LIST_MASTERDB_GAMES_SQLITE", games=len(games))
            return _ok(games)
        return _ok([])

    def get_cover_thumbnail(self, rom_key):
        """Return a resized card thumbnail, not the full-resolution MasterDB image."""
        rom_entry = self._rom_entry(rom_key)
        if not rom_entry:
            return _ok(None)
        cover_path = rom_entry.get("media", {}).get("covers")
        if not cover_path:
            return _ok(None)
        return _ok(self._encode_thumbnail(cover_path))

    def get_local_cover_thumbnail(self, local_id, rom_key):
        """Local Preview thumbnail. Prefer the media index produced by the last scan.

        The previous implementation called importer.read_media() for every card.
        For ES-DE that meant repeatedly walking media directories, which made a
        1,000-card Preview take several seconds. The scan already knows the media
        paths, so reuse that information and only encode the selected image.
        """
        local = self._find_local(local_id)
        if not local:
            self._diag("LOCAL_THUMB_FAIL", local_id=local_id, rom_key=rom_key, reason="local_not_found")
            return _ok(None)
        try:
            system, filename = rom_key.split("|", 1)
        except ValueError:
            self._diag("LOCAL_THUMB_FAIL", local_id=local_id, rom_key=rom_key, reason="bad_rom_key")
            return _ok(None)

        media_dict = None
        runtime = self._local_scan_cache.get(local_id, {})
        cached_media = runtime.get("last_media", {})
        media_dict = cached_media.get((system, filename))

        # Backward-compatible fallback when a card is requested before a scan cache
        # has media paths (or after an old runtime cache has been restored).
        if media_dict is None:
            from importers import get_importer
            importer = get_importer(local["frontend"])
            try:
                media_dict = importer.read_media(local["media_path"], system, filename, "")
            except Exception as exc:
                self._diag("LOCAL_THUMB_FAIL", local_id=local_id, rom_key=rom_key, reason="read_media_exception", error=repr(exc))
                return _ok(None)

        cover = media_dict.get("covers") if isinstance(media_dict, dict) else None
        if not cover:
            self._diag("LOCAL_THUMB_FAIL", local_id=local_id, rom_key=rom_key, reason="no_cover_key", media_keys=sorted(media_dict.keys()) if isinstance(media_dict, dict) else [])
            return _ok(None)
        path = cover[0] if isinstance(cover, list) else cover
        encoded = self._encode_thumbnail(path)
        self._diag_thumb_count += 1
        if self._diag_thumb_count <= 30 or not encoded:
            self._diag("LOCAL_THUMB_RESULT", local_id=local_id, rom_key=rom_key, path=str(path), path_exists=Path(path).exists(),
                       encoded=bool(encoded), media_keys=sorted(media_dict.keys()) if isinstance(media_dict, dict) else [])
        return _ok(encoded)

    def get_dashboard_stats(self, scope, fast=False):
        """
        scope: 'masterdb' 또는 local_id

        [BUG FIX] 예전엔 Local 통계를 "시스템 이름이 같으면 그 Local 것"이라고 근사
        매칭해서, 시스템명이 겹치는 Local이 여러 개면 부정확했다. 이제 Local scope는
        scan_local()의 정확한 결과를 그대로 사용한다.

        [신규] 6개 지표(전체 ROM 개수/크기, 전체 metadata 개수, 전체 media 크기,
        Missing ROM, Missing Media)와 시스템별 상세(ROM/media 크기 포함)를 반환한다.
        MasterDB scope에서는 이제 ROM 실물 저장 여부도 Missing ROM 판단에 포함된다.
        """
        if scope != "masterdb":
            if fast:
                cached = self._local_scan_cache.get(scope, {})
                last = cached.get("last_result")
                local = self._find_local(scope)
                if last and local:
                    return _ok(self._dashboard_from_scan(local, last.get("rom_list", []), last.get("per_system", {}), last.get("metadata_entries", [])))
                # 최초 Dashboard 진입에서는 절대 전체 파일시스템을 스캔하지 않는다.
                # 마지막으로 저장된 Local summary가 있으면 그것만 즉시 반환한다.
                if local:
                    st = local.get("stats", {}) or {}
                    return _ok({"romCount": st.get("rom_count", 0), "romSizeBytes": st.get("rom_size_bytes", 0),
                                "metadataCount": st.get("metadata_count", max(0, st.get("rom_count", 0) - st.get("missing_metadata", 0))),
                                "mediaSizeBytes": st.get("media_size_bytes", 0), "missingRom": st.get("missing_rom", 0),
                                "missingMedia": st.get("missing_media", 0), "systems": [], "cached": True})
            return self._dashboard_stats_for_local(scope, fast=fast)
        return self._dashboard_stats_for_masterdb()

    def _dashboard_stats_for_local(self, local_id, fast=False):
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")

        if not fast and not self._local_scan_cache.get(local_id, {}).get("last_result"):
            # API 직접 호출/기존 테스트/정확한 요청에서는 최초 스캔을 허용한다.
            # Web Dashboard는 fast=True로 호출하여 UI를 절대 블로킹하지 않는다.
            runtime_cache = self._local_scan_cache.setdefault(local_id, {})
            raw = scan_local(local, runtime_cache=runtime_cache)
            runtime_cache["last_result"] = raw

        # Dashboard에서는 절대로 Web UI의 동기 전체 Local scan을 실행하지 않는다.
        # 최근 Local scan 결과가 있으면 그것을 사용하고, 없으면 config에 남은 요약 통계를 즉시 반환한다.
        cached = self._local_scan_cache.get(local_id, {}).get("last_result")
        if cached:
            roms = cached.get("rom_list", [])
            per_system_raw = cached.get("per_system", {})
            metadata_entries = cached.get("metadata_entries", [])
            return _ok(self._dashboard_from_scan(local, roms, per_system_raw, metadata_entries))

        stats = local.get("stats", {}) or {}
        return _ok({
            "romCount": int(stats.get("rom_count", 0) or 0),
            "romSizeBytes": int(stats.get("rom_size_bytes", 0) or 0),
            "metadataCount": int(stats.get("metadata_count", max(0, int(stats.get("rom_count", 0) or 0) - int(stats.get("missing_metadata", 0) or 0))) or 0),
            "mediaSizeBytes": int(stats.get("media_size_bytes", 0) or 0),
            "missingRom": int(stats.get("missing_rom", 0) or 0),
            "missingMedia": int(stats.get("missing_media", 0) or 0),
            "systems": [],
            "cached": False,
        })

    def _dashboard_from_scan(self, local, roms, per_system_raw, metadata_entries=None):
        """
        [버그 수정] 예전엔 romCount/mediaSizeBytes/metadataCount를 전부 `roms`(물리
        ROM 목록)만 순회해서 계산했다. ES-DE metadata-only Local(rom_path 미설정 -
        gamelist/media는 있지만 물리 ROM은 등록하지 않는 방식)은 roms가 항상
        비어있어서, 실제로 media/metadata가 있어도 Dashboard에는 전부 0으로 보였다.
        media 크기는 이미 per_system_raw(디렉토리 실제 크기 기준으로 scan_local()이
        계산 - ROM 존재 여부와 무관)에 정확히 들어있으므로 그것을 그대로 합산하고,
        metadata 개수는 물리 ROM 매칭 여부와 무관하게 gamelist 항목 전체를 담는
        metadata_entries의 길이를 쓴다.
        """
        metadata_entries = metadata_entries or []
        by_system = {}
        rom_size_total = media_size_total = missing_media = 0
        for system, ps in (per_system_raw or {}).items():
            rom_size = ps.get("rom_size", 0); media_size = ps.get("media_size", 0)
            rom_size_total += rom_size; media_size_total += media_size
            missing_media += ps.get("missing_media", 0)
            by_system[system] = {"system": system, "romCount": ps.get("rom_count", 0),
                                  "romSizeBytes": rom_size, "mediaSizeBytes": media_size,
                                  "missing": ps.get("missing_media", 0)}
        stats = local.get("stats", {}) or {}
        return {
            "romCount": len(roms), "romSizeBytes": rom_size_total,
            "metadataCount": len(metadata_entries), "mediaSizeBytes": media_size_total,
            "missingRom": int(stats.get("missing_rom", 0) or 0),
            "missingMedia": missing_media, "systems": list(by_system.values()), "cached": True,
        }

    def _dashboard_stats_for_masterdb(self):
        if not self.db:
            return _ok({"romCount": 0, "romSizeBytes": 0, "metadataCount": 0, "mediaSizeBytes": 0, "missingRom": 0, "missingMedia": 0, "systems": []})
        masterdb_root = self.cfg["masterdb"]["root"]
        roms = self.db.get("roms", {}).values()

        by_system = {}
        rom_size_total = 0
        media_size_total = 0
        metadata_count = 0
        missing_rom = 0
        missing_media = 0

        for r in roms:
            s = by_system.setdefault(r["system"], {"system": r["system"], "romCount": 0, "romSizeBytes": 0, "mediaSizeBytes": 0, "missing": 0})
            s["romCount"] += 1

            rom_path = dbmod.rom_storage_path(masterdb_root, r["system"], r["rom_filename"])
            if rom_path.exists():
                sz = rom_path.stat().st_size
                rom_size_total += sz
                s["romSizeBytes"] += sz
            else:
                # [신규] MasterDB가 이제 ROM 실물도 저장하므로, "실물이 없음" = Missing ROM
                missing_rom += 1
                s["missing"] += 1

            fields = dbmod.get_default_fields(r)
            versions = r.get("versions") or {}
            if versions or any(str(fields.get(k, "") or "").strip() for k in dbmod.META_FIELD_KEYS if k != "tags"):
                metadata_count += 1

            media = r.get("media") or {}
            if not media:
                missing_media += 1
                s["missing"] += 1
            else:
                for val in media.values():
                    for p in (val if isinstance(val, list) else [val]):
                        if p and Path(p).exists():
                            sz = Path(p).stat().st_size
                            media_size_total += sz
                            s["mediaSizeBytes"] += sz

        return _ok({
            "romCount": len(list(self.db.get("roms", {}))), "romSizeBytes": rom_size_total,
            "metadataCount": metadata_count, "mediaSizeBytes": media_size_total,
            "missingRom": missing_rom, "missingMedia": missing_media,
            "systems": list(by_system.values()),
        })

    def get_health_info(self):
        """[신규] Dashboard 상단 Health 요약 한 줄 (예전 Tkinter 버전 형태 복원).
        LOCAL 등록 수/4, SERVER(MasterDB) 경로. WORK 경로는 현재 아키텍처에 해당
        개념이 없어 제외 - 추후 구체화 예정."""
        n_locals = len(self.cfg.get("locals", []))
        masterdb_root = self.cfg.get("masterdb", {}).get("root") or "미설정"
        return _ok({"localCount": n_locals, "localMax": cfgmod.MAX_LOCALS, "masterdbPath": masterdb_root})

    # ------------------------------------------------------------------
    # [신규] 게임 삭제 (Local: metadata/ROM 개별 선택 가능, MasterDB: metadata만 -
    # MasterDB에서의 ROM 실물 삭제는 아직 미지원, 추후 추가 예정)
    # ------------------------------------------------------------------
    def delete_local_games(self, local_id, rom_keys, delete_metadata, delete_rom):
        """
        Local 뷰에서 선택된 게임(들)을 삭제한다.
        delete_metadata=True: 그 Local의 gamelist 항목 + media 파일 삭제 (ROM은 유지)
        delete_rom=True: 실제 ROM 파일 삭제 (metadata는 유지 - 이후 Missing ROM으로 표시됨)
        둘 다 True면 둘 다 삭제.
        """
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        if not delete_metadata and not delete_rom:
            return _err("삭제할 대상(metadata 또는 Rom)을 선택해주세요.")
        busy_err = self._target_busy_error(local_id)
        if busy_err:
            return busy_err

        frontend = local["frontend"]
        remove_entry = None
        if delete_metadata:
            if frontend not in _CLEANUP_HANDLERS:
                return _err(f"{frontend}은 아직 metadata 삭제를 지원하지 않습니다.")
            _get_referenced, remove_entry = _CLEANUP_HANDLERS[frontend]

        result = {"metadataDeleted": 0, "romDeleted": 0, "errors": []}
        for rom_key in rom_keys:
            try:
                system, filename = rom_key.split("|", 1)
            except ValueError:
                result["errors"].append(f"잘못된 romKey: {rom_key}")
                continue
            if delete_metadata:
                try:
                    remove_entry(local["metadata_path"], local["media_path"], system, filename)
                    result["metadataDeleted"] += 1
                except Exception as e:
                    result["errors"].append(f"{filename} (metadata): {e}")
            if delete_rom:
                try:
                    rom_file = Path(local["rom_path"]) / system / filename
                    if rom_file.exists():
                        rom_file.unlink()
                        result["romDeleted"] += 1
                except Exception as e:
                    result["errors"].append(f"{filename} (rom): {e}")
        return _ok(result)

    def delete_masterdb_games(self, rom_keys, delete_metadata=True, delete_rom=False):
        """MasterDB 게임 삭제. metadata는 DB 항목+연결 media, ROM은 실물 파일을 의미한다."""
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        if not delete_metadata and not delete_rom:
            return _err("삭제할 대상(metadata 또는 Rom)을 선택해주세요.")
        busy_err = self._target_busy_error("masterdb")
        if busy_err:
            return busy_err
        import shutil
        root = self.cfg.get("masterdb", {}).get("root")
        result = {"metadataDeleted": 0, "romDeleted": 0, "mediaDeleted": 0, "errors": [], "deleted": 0, "favoriteSkipped": 0}
        # [P0 버그 수정] 예전엔 아래 루프가 self.db/self._sqlite를 잠금 없이 직접
        # 건드리다가 마지막 _save_db()만 잠갔다 - 그 사이에 background job(import/export/
        # 유사롬 탐색)이 같은 sqlite3 connection에 동시에 쓸 수 있었다. 삭제 전체를
        # _db_lock으로 감싼다 (RLock이라 _save_db() 내부의 재획득도 안전).
        with self._db_lock:
            # [단위 9] favorite로 지정한 ROM은 삭제 대상에서 자동 제외한다.
            favorite_keys = self._sqlite.list_favorite_keys() if self._sqlite is not None else set()
            if favorite_keys:
                skipped = [k for k in rom_keys if k in favorite_keys]
                result["favoriteSkipped"] = len(skipped)
                rom_keys = [k for k in rom_keys if k not in favorite_keys]
            for rom_key in rom_keys:
                entry = self.db.get("roms", {}).get(rom_key)
                if not entry:
                    continue
                system, filename = entry.get("system", ""), entry.get("rom_filename", "")
                try:
                    if delete_metadata:
                        # metadata 삭제 시 DB entry와 연결 media만 삭제한다. ROM 실물은 delete_rom 옵션일 때만 삭제.
                        # [P1 버그 수정] 예전엔 media 파일을 먼저 지우고 그 다음 SQLite
                        # delete_rom()을 시도했다 - SQLite 삭제가 실패하면(continue) DB
                        # entry(JSON+SQLite)는 그대로 남아있는데 media만 이미 사라진,
                        # DB가 존재하지 않는 파일을 가리키는 상태가 될 수 있었다. 이제
                        # DB(SQLite+JSON) 삭제를 먼저 확정한 뒤에만 media를 지운다 -
                        # 최악의 경우도 "고아 media 디렉토리"(용량 낭비)일 뿐, dangling
                        # 참조는 생기지 않는다.
                        if self._sqlite is not None:
                            if not self._sqlite.delete_rom(rom_key):
                                result["errors"].append(f"{filename}: SQLite ROM 삭제 실패")
                                continue
                        del self.db["roms"][rom_key]
                        if root:
                            media_dir = dbmod.db_paths(root)["media_dir"] / system / Path(filename).stem
                            if media_dir.exists():
                                shutil.rmtree(media_dir, ignore_errors=True)
                                result["mediaDeleted"] += 1
                        result["metadataDeleted"] += 1
                        result["deleted"] += 1
                    if delete_rom and root:
                        rom_path = dbmod.rom_storage_path(root, system, filename)
                        if rom_path.exists() and rom_path.is_file():
                            rom_path.unlink(); result["romDeleted"] += 1
                        if rom_path.parent.exists() and not any(rom_path.parent.iterdir()):
                            rom_path.parent.rmdir()
                except Exception as e:
                    result["errors"].append(f"{filename}: {e}")
            self._save_db()
        return _ok(result)

    def set_rom_favorite(self, rom_key, favorite):
        """[단위 9] ArchiveDB ROM의 favorite 여부를 토글한다. self.db(JSON)에는 저장하지
        않는 SQLite-only 플래그 - _save_db()의 replace_from_dict가 rom_id를 안정적으로
        유지해주므로 JSON을 다시 불러와도 사라지지 않는다."""
        if self._sqlite is None:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        if rom_key not in self.db.get("roms", {}):
            return _err("게임을 찾을 수 없습니다.")
        ok = self._sqlite.set_favorite(rom_key, bool(favorite))
        if not ok:
            return _err("즐겨찾기 설정에 실패했습니다.")
        return _ok({"romKey": rom_key, "favorite": bool(favorite)})

    def rename_masterdb_rom(self, rom_key, new_filename):
        """
        [F2] ArchiveDB ROM 파일명을 변경한다. rom_key(system|filename) 자체가 바뀌므로
        실물 ROM 파일 + media 폴더(ROM stem 기준 하위 폴더)를 함께 옮기고, media 딕셔너리에
        저장된 경로 문자열도 새 stem으로 갱신한다. 대상 파일명이 이미 존재하면(디스크/DB
        어느 쪽이든) 충돌로 보고 아무 것도 바꾸지 않고 즉시 취소한다.
        """
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        busy_err = self._target_busy_error("masterdb")
        if busy_err:
            return busy_err
        entry = self.db.get("roms", {}).get(rom_key)
        if not entry:
            return _err("게임을 찾을 수 없습니다.")
        new_filename = (new_filename or "").strip()
        if not new_filename or "/" in new_filename or "\\" in new_filename:
            return _err("올바르지 않은 파일명입니다.")
        system = entry.get("system", "")
        old_filename = entry.get("rom_filename", "")
        if new_filename == old_filename:
            return _ok(entry)
        new_key = dbmod.make_rom_key(system, new_filename)
        if new_key in self.db.get("roms", {}):
            return _err(f"'{new_filename}' 이름의 ROM이 이미 존재합니다.")

        root = self.cfg.get("masterdb", {}).get("root")
        old_stem = Path(old_filename).stem
        new_stem = Path(new_filename).stem
        try:
            if root:
                paths = dbmod.db_paths(root)
                old_rom_path = paths["rom_dir"] / system / old_filename
                new_rom_path = paths["rom_dir"] / system / new_filename
                if new_rom_path.exists():
                    return _err(f"'{new_filename}' 파일이 이미 존재합니다.")
                if old_rom_path.exists():
                    new_rom_path.parent.mkdir(parents=True, exist_ok=True)
                    old_rom_path.rename(new_rom_path)

                old_media_dir = paths["media_dir"] / system / old_stem
                new_media_dir = paths["media_dir"] / system / new_stem
                if old_media_dir.exists() and old_media_dir.is_dir():
                    if new_media_dir.exists():
                        return _err(f"'{new_stem}' media 폴더가 이미 존재합니다.")
                    new_media_dir.parent.mkdir(parents=True, exist_ok=True)
                    old_media_dir.rename(new_media_dir)

                def _remap(value):
                    p = Path(value)
                    if p.parent.name == old_stem:
                        return str(p.parent.parent / new_stem / p.name)
                    return value
                media = entry.get("media") or {}
                for media_type, value in list(media.items()):
                    if isinstance(value, list):
                        media[media_type] = [_remap(v) for v in value]
                    elif isinstance(value, str) and value:
                        media[media_type] = _remap(value)
        except OSError as e:
            return _err(f"파일 이동 실패: {e}")

        entry["rom_filename"] = new_filename
        self.db["roms"][new_key] = entry
        del self.db["roms"][rom_key]
        self._save_db()
        return _ok({"romKey": new_key, "filename": new_filename})

    def save_local_game_fields(self, local_id, rom_key, fields):
        """Local의 실제 frontend metadata를 직접 수정한다. MasterDB Import은 필요 없다."""
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        busy_err = self._metadata_edit_busy_error(local_id)
        if busy_err:
            return busy_err
        try:
            system, filename = rom_key.split("|", 1)
        except ValueError:
            return _err("잘못된 romKey 형식입니다.")
        try:
            from exporters import get_exporter
            exporter = get_exporter(local["frontend"])
            normalized = {k: fields.get(k, "" if k != "tags" else []) for k in dbmod.META_FIELD_KEYS}
            exporter.write_metadata_fields(local["metadata_path"], system, filename, normalized)
            cache = self._local_scan_cache.get(local_id, {})
            raw = cache.get("last_result")
            if raw:
                for r in raw.get("rom_list", []):
                    if r.get("system") == system and r.get("filename") == filename:
                        r["_fields"] = normalized; r["has_metadata"] = bool(normalized.get("name")); break
            if cache.get("last_games") is not None:
                for g in cache["last_games"]:
                    if g.get("romKey") == rom_key:
                        g.update({"title": normalized.get("name", ""), "desc": normalized.get("desc", ""), "genre": normalized.get("genre", ""), "region": normalized.get("region", ""), "rating": normalized.get("rating", ""), "noMetadata": not bool(normalized.get("name"))})
                        break
            # [체감 속도 리뷰 반영] Scan phase2가 gamelist.xml을 읽는 시점과 이 저장이
            # 겹치면, phase2가 "이 저장이 반영되기 전" 스냅샷으로 계산한 games 리스트를
            # 나중에 runtime_cache["last_games"]에 통째로 덮어써서(위의 즉시 패치를
            # 무효화) 방금 저장한 값이 화면에서 사라진 것처럼 보일 수 있다. 파일에는
            # 항상 정확히 저장되지만(디스크가 최종 진실), 캐시가 그걸 반영 못 하는
            # 짧은 창이 생기는 것 - scan이 이 local에 대해 진행 중일 때만 별도로
            # 기록해뒀다가, scan이 최종 결과를 커밋하는 순간 다시 얹어서 이 문제를
            # 막는다(scan_local()의 pending_edits_during_scan 적용부 참고).
            with self._busy_lock:
                scan_in_flight = local_id in self._busy_targets
            if scan_in_flight:
                cache.setdefault("pending_edits_during_scan", {})[rom_key] = normalized
            return _ok({"fields": normalized})
        except NotImplementedError as e:
            return _err(str(e))
        except Exception as e:
            return _err(f"GameListSet metadata 저장 오류: {e}")

    def save_local_media(self, local_id, rom_key, media_type_gui, base64_data, filename):
        """Save a dropped/downloaded media asset directly into a Local frontend.

        This is intentionally separate from MasterDB ``save_media``: Local editing
        must persist to the Local's actual downloaded_media/media tree.
        """
        local = self._find_local(local_id)
        internal_key = MEDIA_TYPE_MAP.get(media_type_gui)
        if not local or not internal_key:
            return _err("GameListSet 또는 media 타입을 찾을 수 없습니다.")
        busy_err = self._metadata_edit_busy_error(local_id)
        if busy_err:
            return busy_err
        try:
            raw = base64.b64decode(base64_data)
            system, rom_filename = rom_key.split("|", 1)
            ext = Path(filename).suffix or ".png"
            frontend = str(local.get("frontend", "")).lower()
            if frontend in ("es-de", "emulationstation"):
                from exporters.base import ES_DE_MEDIA_FOLDER_MAP
                folder = ES_DE_MEDIA_FOLDER_MAP[internal_key]
                dest_dir = Path(local.get("media_path") or local["metadata_path"]) / "downloaded_media" / system / folder
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / f"{Path(rom_filename).stem}{ext}"
            else:
                # Generic fallback: write to a temporary source and let the frontend
                # exporter choose its native media layout.
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                    tf.write(raw); temp_path = Path(tf.name)
                try:
                    exporter = get_exporter(local["frontend"])
                    exporter.write_media(local.get("media_path") or local["metadata_path"], system, rom_filename, {internal_key: str(temp_path)}, copy_video=True)
                finally:
                    try: temp_path.unlink()
                    except Exception: pass
                self._diag("LOCAL_MEDIA_SAVE", local_id=local_id, rom_key=rom_key, media_type=media_type_gui, frontend=local.get("frontend"), success=True)
                return _ok(True)
            dest_path.write_bytes(raw)
            self._diag("LOCAL_MEDIA_SAVE", local_id=local_id, rom_key=rom_key, media_type=media_type_gui, path=str(dest_path), success=True)
            return _ok({"path": str(dest_path), "dataUri": self._encode_image(dest_path)})
        except Exception as exc:
            self._diag("LOCAL_MEDIA_SAVE_FAIL", local_id=local_id, rom_key=rom_key, media_type=media_type_gui, error=repr(exc))
            return _err(f"GameListSet media 저장 오류: {exc}")

    # ------------------------------------------------------------------
    # [신규] 유사롬(Comparable ROM) - 점수제, 시스템 선택 후 수동 실행, 결과 DB 저장
    # ------------------------------------------------------------------
    def get_similar_rom_settings(self):
        cfg = self.cfg.get("similar_rom", {})
        return _ok({
            "weights": {
                "title": cfg.get("weight_title", similar_rom.DEFAULT_WEIGHTS["title"]),
                "filename": cfg.get("weight_filename", similar_rom.DEFAULT_WEIGHTS["filename"]),
                "developer": cfg.get("weight_developer", similar_rom.DEFAULT_WEIGHTS["developer"]),
                "year": cfg.get("weight_year", similar_rom.DEFAULT_WEIGHTS["year"]),
                "screenshot": cfg.get("weight_screenshot", similar_rom.DEFAULT_WEIGHTS["screenshot"]),
            },
            "threshold": cfg.get("threshold", similar_rom.DEFAULT_THRESHOLD),
        })

    def save_similar_rom_settings(self, weights, threshold):
        cur = self.cfg.setdefault("similar_rom", {})
        weights = weights or {}
        cur.update({
            "weight_title": int(weights.get("title", cur.get("weight_title", 35))),
            "weight_filename": int(weights.get("filename", cur.get("weight_filename", 15))),
            "weight_developer": int(weights.get("developer", cur.get("weight_developer", 15))),
            "weight_year": int(weights.get("year", cur.get("weight_year", 15))),
            "weight_screenshot": int(weights.get("screenshot", cur.get("weight_screenshot", 20))),
            "threshold": int(threshold),
        })
        cfgmod.save_config(self.cfg)
        return _ok(True)

    def _collect_system_roms_for_similarity(self, system):
        """MasterDB에서 특정 system의 ROM들을 유사롬 비교용 형태로 수집."""
        masterdb_root = self.cfg["masterdb"]["root"]
        roms = []
        for rom_key, rom_entry in self.db.get("roms", {}).items():
            if rom_entry.get("system") != system:
                continue
            fields = dbmod.get_default_fields(rom_entry)
            screenshot = rom_entry.get("media", {}).get("screenshots")
            screenshot_path = None
            if screenshot:
                screenshot_path = screenshot[0] if isinstance(screenshot, list) else screenshot
            roms.append({
                "romKey": rom_key, "title": fields.get("name", ""),
                "filename": rom_entry.get("rom_filename", ""),
                "developer": fields.get("developer", ""), "releasedate": fields.get("releasedate", ""),
                "screenshot_path": screenshot_path,
            })
        return roms

    def _auto_pick_similar_representative(self, member_keys):
        """
        [0.4.1.x 단위 8] 유사롬 그룹의 대표를 자동으로 고른다. 우선순위(단계별로 후보를
        좁혀가며, 마지막에 하나만 남으면 그걸로 확정):
          1) favorite=True
          2) default 버전 metadata 필드가 채워진 개수가 많은 것
          3) description 길이가 긴 것
          4) media 파일 총 용량이 큰 것
        모두 동률이면 romKey 사전순으로 결정(항상 같은 결과가 나오도록).
        멤버가 DB에 없으면 후보에서 제외한다. 사용자가 이미 수동으로 대표를 지정한
        그룹은 이 함수를 호출하는 쪽(start_find_similar_roms)에서 건너뛴다.
        """
        roms = self.db.get("roms", {}) if self.db else {}
        candidates = [k for k in member_keys if k in roms]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        def filled_field_count(rom_key):
            fields = dbmod.get_default_fields(roms[rom_key])
            count = 0
            for k, v in fields.items():
                if k == "tags":
                    if v:
                        count += 1
                elif str(v or "").strip():
                    count += 1
            return count

        def desc_length(rom_key):
            return len(str(dbmod.get_default_fields(roms[rom_key]).get("desc") or ""))

        def media_total_bytes(rom_key):
            total = 0
            media = roms[rom_key].get("media") or {}
            for value in media.values():
                paths = value if isinstance(value, list) else [value]
                for p in paths:
                    try:
                        total += Path(p).stat().st_size
                    except (OSError, TypeError):
                        pass
            return total

        favorite_keys = self._sqlite.list_favorite_keys() if self._sqlite is not None else set()
        tiers = [
            lambda k: 1 if k in favorite_keys else 0,
            filled_field_count,
            desc_length,
            media_total_bytes,
        ]
        for score_fn in tiers:
            best = max(score_fn(k) for k in candidates)
            narrowed = [k for k in candidates if score_fn(k) == best]
            if len(narrowed) == 1:
                return narrowed[0]
            candidates = narrowed
        return sorted(candidates)[0]

    def start_find_similar_roms(self, system):
        """[신규] 선택된 system 내에서만 유사롬 탐색을 백그라운드로 실행 (진행률 job).
        결과는 완료 시 자동으로 SQLite에 저장된다 (v0.5 10단계 - 그룹에 고정 group_id가
        생겨서 대표 지정을 얹을 수 있음). 재탐색할 때마다 해당 system의 그룹은 전부 새로
        만들어지므로(재분석이므로) 이전 대표 지정은 초기화된다."""
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        if self._sqlite is None:
            return _err("SQLite가 초기화되지 않았습니다.")
        settings = self.get_similar_rom_settings()["data"]
        weights = {
            "title": settings["weights"]["title"], "filename": settings["weights"]["filename"],
            "developer": settings["weights"]["developer"], "year": settings["weights"]["year"],
            "screenshot": settings["weights"]["screenshot"],
        }
        threshold = settings["threshold"]
        roms = self._collect_system_roms_for_similarity(system)

        def run(cb):
            groups = similar_rom.find_similar_roms(roms, weights=weights, threshold=threshold, progress_cb=cb)
            with self._db_lock:
                self._sqlite.save_similar_groups(system, groups)
                # [0.4.1.x 단위 8] 재탐색으로 새로 만들어진 그룹은 대표가 전부 비어있으므로,
                # 저장 직후 바로 자동 대표를 지정해준다 (사용자가 이후 수동으로 바꿀 수 있음).
                for saved_group in self._sqlite.get_similar_groups(system):
                    auto_key = self._auto_pick_similar_representative(saved_group["members"])
                    if auto_key:
                        self._sqlite.set_similar_group_representative(saved_group["group_id"], auto_key)
            return {"system": system, "groups": groups}

        job_id = self._run_job(run, mutates_db=True)
        return _ok({"jobId": job_id})

    def get_similar_rom_groups(self, system):
        """이전에 저장된 유사롬 탐색 결과를 다시 계산하지 않고 조회한다."""
        if not self.db or self._sqlite is None:
            return _ok([])
        groups = self._sqlite.get_similar_groups(system)
        # 각 그룹 멤버의 표시용 정보(title/file)도 같이 붙여서 반환 (프론트에서 바로 보여줄 수 있게)
        roms = self.db.get("roms", {})
        enriched = []
        for g in groups:
            members = []
            for rom_key in g["members"]:
                rom_entry = roms.get(rom_key)
                if not rom_entry:
                    continue
                fields = dbmod.get_default_fields(rom_entry)
                members.append({"romKey": rom_key, "title": fields.get("name", ""), "file": rom_entry.get("rom_filename", "")})
            if len(members) > 1:
                enriched.append({"groupId": g["group_id"], "members": members, "representative": g["representative"]})
        return _ok(enriched)

    def set_similar_group_representative(self, group_id, rom_key):
        """유사롬 그룹의 대표 ROM을 지정(또는 rom_key=None으로 해제)한다."""
        if self._sqlite is None:
            return _err("SQLite가 초기화되지 않았습니다.")
        try:
            group_id = int(group_id)
        except (TypeError, ValueError):
            return _err("잘못된 group_id입니다.")
        ok = self._sqlite.set_similar_group_representative(group_id, rom_key)
        if not ok:
            return _err("대표로 지정할 수 없습니다 (그룹 멤버가 아니거나 그룹을 찾을 수 없음).")
        return _ok(True)

    # ------------------------------------------------------------------
    # 게임 상세 (Metadata / Version)
    # ------------------------------------------------------------------
    def get_local_game_detail(self, local_id, rom_key, lightweight=False):
        """
        [신규] Local 화면에서 게임을 클릭했을 때 쓰는 조회 경로.
        [BUG FIX] 기존엔 Local에서 게임을 골라도 get_game_detail(MasterDB 전용)을 그대로
        호출해서, 아직 Import 안 된 ROM은 무조건 "게임을 찾을 수 없습니다" 에러가 났었다.
        이 메서드는 MasterDB를 거치지 않고 Local의 metadata/media 파일을 직접 읽는다
        (예전 Tkinter 버전의 "Local 상세는 Import 없이도 조회 가능" 원칙과 동일).

        Local frontend가 지원하는 경우 실제 metadata 파일을 직접 편집할 수 있다.
        따라서 UI에서도 읽기 전용으로 잠그지 않는다.
        """
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        try:
            system, filename = rom_key.split("|", 1)
        except ValueError:
            return _err("잘못된 romKey 형식입니다.")

        from importers import get_importer
        importer = get_importer(local["frontend"])
        try:
            fields = importer.read_metadata_fields(local["metadata_path"], system, filename) or {}
        except NotImplementedError:
            fields = {}
        except Exception:
            fields = {}
        normalized_fields = {k: fields.get(k, "" if k != "tags" else []) for k in dbmod.META_FIELD_KEYS}

        media_out = {}
        try:
            media_dict = importer.read_media(local["media_path"], system, filename, fields.get("name", ""))
            self._diag("LOCAL_DETAIL_MEDIA", local_id=local_id, rom_key=rom_key, lightweight=bool(lightweight),
                       media_keys=sorted(media_dict.keys()), media_path=local.get("media_path", ""))
            for internal_key, val in media_dict.items():
                gui_key = MEDIA_TYPE_MAP_REV.get(internal_key)
                if not gui_key:
                    continue
                path = val[0] if isinstance(val, list) else val
                if internal_key == "videos":
                    media_out[gui_key] = "video://exists" if path and Path(path).exists() else None
                elif lightweight:
                    media_out[gui_key] = "media://available" if path and Path(path).exists() else None
                else:
                    media_out[gui_key] = self._encode_image(path)
        except Exception as exc:
            self._diag("LOCAL_DETAIL_MEDIA_FAIL", local_id=local_id, rom_key=rom_key, error=repr(exc))

        version = {"id": "local", "label": "v1 (Local)", "isDefault": True, "source": local["label"], "fields": normalized_fields}
        return _ok({"romKey": rom_key, "system": system, "file": filename, "versions": [version], "media": media_out, "readOnly": False})

    def get_game_detail(self, rom_key, lightweight=False):
        if self._sqlite is not None:
            rom = self._sqlite.get_rom(rom_key)
            if not rom:
                return _err("게임을 찾을 수 없습니다.")
            versions = []
            for v in rom.get("versions") or []:
                versions.append({
                    "id": v.get("version_id", ""),
                    "label": v.get("version_id", ""),
                    "isDefault": v.get("version_id") == rom.get("default_version_id"),
                    "source": v.get("source_local_id", ""),
                    "fields": v.get("fields") or {},
                })
            filled = dbmod.get_filled_fields(self._rom_entry(rom_key) or {"default_version_id": rom.get("default_version_id"), "versions": {v["id"]: {"fields": v["fields"]} for v in versions}})
            for v in versions:
                if v["isDefault"]:
                    v["fields"] = filled
            media_out = {}
            for internal_key, val in (rom.get("media") or {}).items():
                gui_key = MEDIA_TYPE_MAP_REV.get(internal_key)
                if not gui_key:
                    continue
                path = val[0] if isinstance(val, list) else val
                if internal_key == "videos":
                    media_out[gui_key] = "video://exists" if path and Path(path).exists() else None
                else:
                    media_out[gui_key] = self._encode_image(path)
            if self._shadow.enabled:
                legacy_entry = self.db.get("roms", {}).get(rom_key)
                native_entry = self._sqlite.get_rom(rom_key)
                # Compare the data semantics; image encoding is deliberately excluded.
                self._shadow.compare_rom_entry("get_game_detail", legacy_entry, native_entry)
            # [신규] ROM 실물의 SHA256 - 처음 ArchiveDB로 복사될 때 캐시된 값을 그대로
            # 읽기만 한다(여기서 새로 계산하지 않음 - 상세 패널 열 때마다 계산하면
            # 큰 ROM에서 매번 지연이 생긴다). 캐시가 없으면(구버전에서 이미 들어온
            # ROM 등) null - GUI가 "계산 안 됨"으로 표시한다.
            sha256 = self._sqlite.get_rom_hash(rom_key)
            return _ok({"romKey": rom_key, "system": rom["system"], "file": rom["file"], "versions": versions, "media": media_out, "sha256": sha256})
        rom_entry = self._rom_entry(rom_key)
        if not rom_entry:
            return _err("게임을 찾을 수 없습니다.")
        sorted_versions = dbmod.list_versions_sorted(rom_entry)
        versions = []
        for vid, vdata in sorted_versions:
            versions.append({
                "id": vid, "label": dbmod.version_label(rom_entry, vid),
                "isDefault": vid == rom_entry.get("default_version_id"),
                "source": vdata.get("source_local_id", ""), "fields": vdata["fields"],
            })
        filled = dbmod.get_filled_fields(rom_entry)
        for v in versions:
            if v["isDefault"]:
                v["fields"] = filled
        media = {}
        media_out = {}
        for internal_key, val in rom_entry.get("media", {}).items():
            gui_key = MEDIA_TYPE_MAP_REV.get(internal_key)
            if not gui_key:
                continue
            path = val[0] if isinstance(val, list) else val
            if internal_key == "videos":
                # [신규] 영상은 base64로 인코딩해서 통째로 보내지 않는다 (용량 문제).
                # GUI도 실제 재생 없이 "등록됨" 여부만 표시하므로 마커 값만 내려준다.
                media_out[gui_key] = "video://exists" if path and Path(path).exists() else None
            else:
                media_out[gui_key] = self._encode_image(path)
        return _ok({"romKey": rom_key, "system": rom_entry["system"], "file": rom_entry["rom_filename"],
                     "versions": versions, "media": media_out})

    def get_local_game_media_image(self, local_id, rom_key, media_type_gui):
        """Load one Local media image on demand, avoiding a multi-megabyte detail bridge payload."""
        local = self._find_local(local_id)
        internal_key = MEDIA_TYPE_MAP.get(media_type_gui)
        if not local or not internal_key or internal_key == "videos":
            return _ok(None)
        try:
            system, filename = rom_key.split("|", 1)
            from importers import get_importer
            importer = get_importer(local["frontend"])
            media_dict = importer.read_media(local["media_path"], system, filename, "") or {}
            val = media_dict.get(internal_key)
            path = val[0] if isinstance(val, list) and val else val
            encoded = self._encode_image(path) if path else None
            self._diag("LOCAL_MEDIA_IMAGE", local_id=local_id, rom_key=rom_key, media_type=media_type_gui,
                       media_keys=sorted(media_dict.keys()), path=str(path) if path else "", path_exists=bool(path and Path(path).exists()), encoded=bool(encoded))
            return _ok(encoded)
        except Exception as exc:
            self._diag("LOCAL_MEDIA_IMAGE_FAIL", local_id=local_id, rom_key=rom_key, media_type=media_type_gui, error=repr(exc))
            return _ok(None)

    def get_game_media_image(self, rom_key, media_type_gui):
        """Load one MasterDB media image on demand."""
        internal_key = MEDIA_TYPE_MAP.get(media_type_gui)
        rom_entry = self._rom_entry(rom_key)
        if not rom_entry or not internal_key or internal_key == "videos":
            return _ok(None)
        val = (rom_entry.get("media") or {}).get(internal_key)
        path = val[0] if isinstance(val, list) and val else val
        return _ok(self._encode_image(path) if path else None)

    def _encode_image(self, path):
        try:
            p = Path(path)
            if not p.exists():
                return None
            import mimetypes
            mime = mimetypes.guess_type(str(p))[0] or "image/png"
            if not mime.startswith(("image/", "application/")):
                mime = "image/png"
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{b64}"
        except Exception:
            return None

    def _encode_thumbnail(self, path, max_size=256):
        """Encode a small Preview thumbnail and cache it by file signature.

        Detail/Metadata views continue to use _encode_image(), so this optimization
        does not reduce the quality of the large media viewer.
        """
        try:
            p = Path(path)
            if not p.exists() or not p.is_file():
                return None
            st = p.stat()
            key = (str(p), st.st_size, st.st_mtime_ns, max_size)
            cached = self._thumb_cache.get(key)
            if cached is not None:
                self._thumb_cache.move_to_end(key)
                return cached
            from PIL import Image
            import io
            with Image.open(p) as im:
                im.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                out = io.BytesIO()
                # WebP is compact and supported by WebView2. Keep alpha when present.
                im.save(out, format="WEBP", quality=82, method=4)
            encoded = "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")
            self._thumb_cache[key] = encoded
            self._thumb_cache.move_to_end(key)
            while len(self._thumb_cache) > self._thumb_cache_limit:
                self._thumb_cache.popitem(last=False)
            return encoded
        except Exception:
            # Keep compatibility with synthetic/non-image fixtures and unusual image
            # formats. The normal path above still produces a compact WebP thumbnail.
            return self._encode_image(path)

    def save_version_fields(self, rom_key, version_id, fields):
        rom_entry = self._rom_entry(rom_key)
        if not rom_entry:
            return _err("게임을 찾을 수 없습니다.")
        if version_id not in rom_entry.get("versions", {}):
            return _err("Version을 찾을 수 없습니다.")
        normalized = {k: fields.get(k, "" if k != "tags" else []) for k in dbmod.META_FIELD_KEYS}
        if self._sqlite is not None:
            with self._db_lock:
                if not self._sqlite.update_version_fields(rom_key, version_id, normalized):
                    return _err("SQLite Version을 찾을 수 없습니다.")
                rom_entry["versions"][version_id]["fields"] = normalized
                self._save_db(sync_sqlite=False)
            return _ok(True)
        rom_entry["versions"][version_id]["fields"] = normalized
        self._save_db()
        return _ok(True)

    def clone_version(self, rom_key, version_id):
        rom_entry = self._rom_entry(rom_key)
        if not rom_entry:
            return _err("게임을 찾을 수 없습니다.")
        src = rom_entry.get("versions", {}).get(version_id)
        if not src:
            return _err("복제할 Version을 찾을 수 없습니다.")
        if self._sqlite is not None:
            new_id = dbmod.new_version_id()
            created_at = datetime.now().isoformat(timespec="milliseconds")
            fields = {k: (src.get("fields") or {}).get(k, "" if k != "tags" else []) for k in dbmod.META_FIELD_KEYS}
            with self._db_lock:
                if not self._sqlite.insert_version(rom_key, new_id, created_at, "manual", False, fields, False):
                    return _err("SQLite ROM을 찾을 수 없습니다.")
                rom_entry.setdefault("versions", {})[new_id] = {
                    "created_at": created_at, "source_local_id": "manual", "source_system": rom_entry.get("system", ""),
                    "uncertain_match": False, "fields": fields,
                }
                self._save_db(sync_sqlite=False)
            return _ok({"newVersionId": new_id})
        new_id = dbmod.clone_version(rom_entry, version_id)
        if not new_id:
            return _err("복제할 Version을 찾을 수 없습니다.")
        self._save_db()
        return _ok({"newVersionId": new_id})

    def set_default_version(self, rom_key, version_id):
        rom_entry = self._rom_entry(rom_key)
        if not rom_entry:
            return _err("게임을 찾을 수 없습니다.")
        if version_id not in rom_entry.get("versions", {}):
            return _err("Version을 찾을 수 없습니다.")
        if self._sqlite is not None:
            with self._db_lock:
                if not self._sqlite.set_default_version(rom_key, version_id):
                    return _err("SQLite Version을 찾을 수 없습니다.")
                rom_entry["default_version_id"] = version_id
                self._save_db(sync_sqlite=False)
            return _ok(True)
        if not dbmod.set_default_version(rom_entry, version_id):
            return _err("Version을 찾을 수 없습니다.")
        self._save_db()
        return _ok(True)

    def delete_version(self, rom_key, version_id):
        rom_entry = self._rom_entry(rom_key)
        if not rom_entry:
            return _err("게임을 찾을 수 없습니다.")
        busy_err = self._target_busy_error("masterdb")
        if busy_err:
            return busy_err
        if len(rom_entry.get("versions", {})) <= 1:
            return _err("최소 1개의 Version은 유지되어야 합니다.")
        if version_id not in rom_entry.get("versions", {}):
            return _err("Version을 찾을 수 없습니다.")
        replacement = None
        if rom_entry.get("default_version_id") == version_id:
            remaining = [v for v in dbmod.list_versions_sorted(rom_entry) if v[0] != version_id]
            replacement = remaining[-1][0] if remaining else None
        if self._sqlite is not None:
            with self._db_lock:
                if not self._sqlite.delete_version(rom_key, version_id, replacement):
                    return _err("SQLite Version을 삭제하지 못했습니다.")
                del rom_entry["versions"][version_id]
                if replacement is not None:
                    rom_entry["default_version_id"] = replacement
                self._save_db(sync_sqlite=False)
            return _ok({"newDefaultVersionId": rom_entry.get("default_version_id")})
        dbmod.delete_version(rom_entry, version_id)
        self._save_db()
        return _ok({"newDefaultVersionId": rom_entry.get("default_version_id")})

    def save_version_diff(self, rom_key, left_id, left_fields, right_id, right_fields):
        """Ver Diff 대화창의 저장: 양쪽 슬롯의 편집 결과를 각 Version에 반영."""
        rom_entry = self._rom_entry(rom_key)
        if not rom_entry:
            return _err("게임을 찾을 수 없습니다.")
        for vid, fields in ((left_id, left_fields), (right_id, right_fields)):
            if vid in rom_entry.get("versions", {}):
                rom_entry["versions"][vid]["fields"] = {
                    k: fields.get(k, "" if k != "tags" else []) for k in dbmod.META_FIELD_KEYS
                }
        self._save_db()
        return _ok(True)

    # ------------------------------------------------------------------
    # Media (드래그 앤 드롭 업로드)
    # ------------------------------------------------------------------
    def save_local_media_from_url(self, local_id, rom_key, media_type_gui, url):
        """Download an image URL and persist it directly into the selected Local."""
        import mimetypes
        from urllib.parse import urlparse
        try:
            import requests
            r = requests.get(str(url).strip(), timeout=15, headers={"User-Agent": "RetroMetadataManager/0.4"})
            r.raise_for_status()
            content_type = (r.headers.get("content-type") or "image/png").split(";", 1)[0].lower()
            if not content_type.startswith("image/"):
                return _err("이미지 URL이 아닙니다.")
            ext = mimetypes.guess_extension(content_type) or Path(urlparse(url).path).suffix or ".png"
            return self.save_local_media(local_id, rom_key, media_type_gui, base64.b64encode(r.content).decode("ascii"), "download" + ext)
        except Exception as e:
            self._diag("LOCAL_MEDIA_SAVE_FAIL", local_id=local_id, rom_key=rom_key, media_type=media_type_gui, error=repr(e), source="url")
            return _err(f"GameListSet 이미지 다운로드 실패: {e}")

    def save_media_from_url(self, rom_key, media_type_gui, url):
        """Download an image URL dropped from a browser and store it as MasterDB media."""
        import mimetypes
        from urllib.parse import urlparse
        try:
            import requests
            r = requests.get(str(url).strip(), timeout=15, headers={"User-Agent": "RetroMetadataManager/0.4"})
            r.raise_for_status()
            content_type = (r.headers.get("content-type") or "image/png").split(";", 1)[0].lower()
            if not content_type.startswith("image/"):
                return _err("이미지 URL이 아닙니다.")
            ext = mimetypes.guess_extension(content_type) or Path(urlparse(url).path).suffix or ".png"
            return self.save_media(rom_key, media_type_gui, base64.b64encode(r.content).decode("ascii"), "download" + ext)
        except Exception as e:
            return _err(f"이미지 다운로드 실패: {e}")

    def save_media(self, rom_key, media_type_gui, base64_data, filename):
        """
        media_type_gui: "Covers" | "Miximages" | "Screenshots" | "Wheel"
        base64_data: JS FileReader.readAsDataURL 결과에서 "data:...;base64," 접두어를 뗀 순수 base64 문자열
        """
        rom_entry = self._rom_entry(rom_key)
        if not rom_entry:
            return _err("게임을 찾을 수 없습니다.")
        internal_key = MEDIA_TYPE_MAP.get(media_type_gui)
        if not internal_key:
            return _err(f"알 수 없는 media 타입: {media_type_gui}")
        try:
            raw = base64.b64decode(base64_data)
        except Exception as e:
            return _err(f"이미지 디코딩 실패: {e}")

        ext = Path(filename).suffix or ".png"
        paths = dbmod.db_paths(self.cfg["masterdb"]["root"])
        dest_dir = paths["media_dir"] / rom_entry["system"] / Path(rom_entry["rom_filename"]).stem
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{internal_key}{ext}"
        try:
            dest_path.write_bytes(raw)
        except Exception as e:
            return _err(f"파일 저장 실패: {e}")

        media_value = [str(dest_path)] if internal_key in ("screenshots", "videos") else str(dest_path)
        if self._sqlite is not None:
            with self._db_lock:
                if not self._sqlite.set_media(rom_key, internal_key, media_value):
                    return _err("SQLite ROM을 찾을 수 없습니다.")
                dbmod.update_single_media(rom_entry, internal_key, str(dest_path))
                self._save_db(sync_sqlite=False)
        else:
            dbmod.update_single_media(rom_entry, internal_key, str(dest_path))
            self._save_db()
        if internal_key == "videos":
            return _ok({"dataUri": "video://exists"})
        return _ok({"dataUri": self._encode_image(dest_path)})

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def start_export_to_local(self, local_id, rom_keys=None, media_types=None, copy_rom=False):
        """export_to_local()의 background job 버전.

        [P0 버그 수정] GameList의 Import from ArchiveDB / Export to GameListSet
        대화상자는 항상 `api.startExportToLocal(...)`을 호출하고 그 결과를
        runJobWithProgress()(jobId를 기대)로 넘겨왔는데, 이 메서드 자체가
        gui_web/api-client.js와 api.py 어디에도 없어서 pywebview 실제 앱에서는
        두 기능 모두 호출 즉시 예외로 죽는 상태였다(Playwright는 mock 브리지라
        존재하지 않는 메서드를 호출해도 `_mockCall`까지 못 가서 잡아내지 못함).
        export_to_local()과 로직은 동일하되, _run_job으로 감싸고 progress_cb를
        연결한 것만 다르다."""
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        try:
            target_roms = None
            if rom_keys:
                target_roms = []
                for rk in rom_keys:
                    system, filename = rk.split("|", 1)
                    target_roms.append((system, filename))
            options = self.cfg.get("export_options", {})

            def resolver(existing, new, rom_info):
                return "skip"

            # [체감 속도, Export 3단계] (1) 메타데이터+커버 (2) 나머지 미디어 (3) 비디오
            # 순서로 나눈다. media_types를 대화상자에서 이미 명시적으로 좁혔으면
            # (예: "커버만") 그 범위 안에서만 나뉜다 - _split_media_into_phases 참고.
            #
            # [실사용 버그 수정] ROM 복사를 예전엔 첫 phase(메타데이터+커버)에 끼워
            # 넣었었다. export_masterdb_to_local()은 ROM을 대상 전체에 대해 순서대로
            # 처리하므로("게임1: metadata->media->ROM, 게임2: metadata->media->ROM..."),
            # 그 결과 커버 몇 장 끝나자마자 (수백MB~수GB일 수 있는) ROM 복사가 바로
            # 끼어들어 "메타데이터/미디어 옮기라 했는데 왜 ROM부터 옮기지?"처럼
            # 보였다. ROM은 media_types와 무관하므로, media_types=[](미디어 없음)로
            # 별도의 마지막 phase를 추가해서 metadata 전체 -> media 전체(커버/기타/
            # 비디오) -> ROM 전체 순서가 되게 한다.
            phases_spec = self._split_media_into_phases(media_types)

            # [P1-1] export_masterdb_to_local()은 매 phase마다 이 Local을 다시
            # 스캔해서 "이미 존재하는 ROM/media" 상태를 판단한다 - 3-phase Export가
            # 같은 gamelist/media 인덱싱을 3번 반복하는 셈이다. phase가 시작되기
            # 전에 딱 한 번만 스캔해서 모든 phase가 같은 snapshot을 공유하게 한다.
            # runtime_cache를 넘기므로(Scan/Refresh와 동일한 캐시) 완전히 새로
            # 훑는 게 아니라 기존 파일 시그니처 캐시도 그대로 활용한다.
            shared_scan_result = scan_local(local, runtime_cache=self._local_scan_cache.setdefault(local_id, {}))

            def make_phase_run(phase_media_types, do_rom_copy):
                def run(cb):
                    return export_masterdb_to_local(
                        local, self.cfg["masterdb"]["root"], self.db, options,
                        conflict_resolver=resolver, target_roms=target_roms, media_types=phase_media_types,
                        copy_rom=do_rom_copy, progress_cb=cb, sqlite_repo=self._sqlite,
                        scan_result=shared_scan_result, queue_hash_fn=self.request_rom_hash,
                    )
                return run

            phases = [
                (label, make_phase_run(types, do_rom_copy=False))
                for label, types in phases_spec
            ]
            if copy_rom:
                phases.append(("ROM", make_phase_run([], do_rom_copy=True)))

            def combine_export_results(acc, result):
                # [Parent Job lifecycle 리뷰 반영] combine_results 없이는 마지막
                # (비디오) phase의 결과만 최종 결과로 남아서, 1단계에서 실제로 export된
                # 개수가 토스트("완료 - N개")에서 사라지고 N이 비디오 phase 혼자만의
                # 개수로 표시된다.
                #
                # 처음엔 phase마다 exported/skipped_* 를 그냥 더하려 했는데, 그건
                # 틀렸다 - export_masterdb_to_local()은 media_types와 무관하게 매
                # phase마다 대상 ROM 전체에 대해 metadata 매칭/재작성을 다시
                # 수행한다(media_types는 media 단계만 거른다). 그래서 ROM 1개가
                # metadata 변경 없이 3 phase를 거치면 exported가 1이 아니라 3으로,
                # skipped_no_match/skipped_korean_dup도 phase 수만큼 부풀려진다 -
                # 진짜 값이 아니라 같은 일을 반복 집계한 것이다. metadata 집계로
                # 의미 있는 숫자는 1단계(전체를 처음 훑은 phase)뿐이므로 그걸 그대로
                # 쓰고, phase마다 실제로 다른 내용을 담는 errors/not_implemented만
                # 누적한다.
                if acc is None:
                    return dict(result)
                merged = dict(acc)
                merged["not_implemented"] = merged.get("not_implemented", False) or result.get("not_implemented", False)
                merged["errors"] = merged.get("errors", []) + result.get("errors", [])
                return merged

            # [P1 버그 수정] export_masterdb_to_local()이 sqlite_repo를 통해
            # GameListSet membership을 SQLite에 기록한다(self._sqlite에 쓰는 실제
            # DB mutation) - mutates_db=False였던 건 잘못됐고, 다른 mutation job과
            # 동시 실행되면 같은 sqlite3 connection을 겹쳐 건드릴 수 있었다.
            # [체감 속도] attach_followup_job_id=True - JS의 runJobWithProgress가
            # followUpJobId를 보고 진행률 바를 숨기지 않은 채 다음 phase로 이어서
            # 폴링한다("(1/3)->(2/3)->(3/3)"처럼 보임).
            job_id = self._start_phased_media_job(
                (local_id, "masterdb"), phases, mutates_db=True, attach_followup_job_id=True,
                combine_results=combine_export_results,
            )
            return _ok({"jobId": job_id})
        except Exception as e:
            traceback.print_exc()
            return _err(str(e))

    def export_to_local(self, local_id, rom_keys=None, media_types=None, copy_rom=False):
        """rom_keys가 None이면 해당 Local에 실제 존재하는 ROM 전체가 대상 (§3.2 기본 동작)."""
        local = self._find_local(local_id)
        if not local:
            return _err("GameListSet을 찾을 수 없습니다.")
        if not self.db:
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        try:
            target_roms = None
            if rom_keys:
                target_roms = []
                for rk in rom_keys:
                    system, filename = rk.split("|", 1)
                    target_roms.append((system, filename))

            # force_overwrite가 켜져 있으면 conflict_resolver 없이도 export_engine이 자동 처리.
            # 꺼져 있으면(=대화창으로 물어봐야 함) 이번 API 레이어에서는 "항상 스킵"으로 안전하게
            # 처리하고, 실제 대화창 UX는 JS 쪽에서 개별 항목을 골라 다시 호출하는 방식으로 뺀다.
            # (JS<->Python 동기 콜백은 pywebview 구조상 불가능하므로 이렇게 분리했다.)
            options = self.cfg.get("export_options", {})

            def resolver(existing, new, rom_info):
                return "skip"  # 대화상자는 JS 레벨에서 미리 처리하고 여기까진 안 오는 게 정상 흐름

            result = export_masterdb_to_local(
                local, self.cfg["masterdb"]["root"], self.db, options,
                conflict_resolver=resolver, target_roms=target_roms, media_types=media_types, copy_rom=bool(copy_rom),
                sqlite_repo=self._sqlite, queue_hash_fn=self.request_rom_hash,
            )
            return _ok(result)
        except Exception as e:
            traceback.print_exc()
            return _err(str(e))

    def check_export_conflicts(self, local_id, rom_keys=None):
        """실제 Export 전에, 어떤 항목이 충돌하는지 미리 조회 (JS가 대화상자를 보여줄 수 있도록)."""
        local = self._find_local(local_id)
        if not local or not self.db:
            return _ok([])
        try:
            from exporters import get_exporter
            exporter = get_exporter(local["frontend"])
            scan_result = scan_local(local)
            local_roms = scan_result["rom_list"]
            if rom_keys:
                key_set = set(rom_keys)
                local_roms = [r for r in local_roms if f"{r['system']}|{r['filename']}" in key_set]

            conflicts = []
            for rom in local_roms:
                rom_key = f"{rom['system']}|{rom['filename']}"
                rom_entry = self.db.get("roms", {}).get(rom_key)
                if not rom_entry:
                    continue
                new_fields = dbmod.get_default_fields(rom_entry)
                try:
                    existing_fields = exporter.read_existing_fields(local["metadata_path"], rom["system"], rom["filename"])
                except Exception:
                    existing_fields = None
                if existing_fields and any(
                    str(existing_fields.get(k, "")).strip() != str(new_fields.get(k, "")).strip()
                    for k in ("name", "desc", "genre", "developer", "publisher", "releasedate")
                ):
                    conflicts.append({"romKey": rom_key, "file": rom["filename"], "existing": existing_fields, "new": new_fields})
            return _ok(conflicts)
        except NotImplementedError as e:
            return _err(str(e))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # Compare (v0.5 9단계): GameListSet 대 GameListSet, 또는 MasterDB 대
    # GameListSet ROM 목록을 파일명 기준으로 나란히 비교한다.
    # ------------------------------------------------------------------
    def list_compare_sources(self):
        """Compare 화면 좌/우 드롭다운에 채울 소스 목록. MasterDB + 등록된 Local 전체."""
        sources = []
        if self.db is not None:
            sources.append({"id": "masterdb", "label": "ArchiveDB"})
        for l in self.cfg.get("locals", []):
            sources.append({"id": l["id"], "label": l.get("label", l["id"])})
        return _ok(sources)

    def _compare_collect(self, source_id):
        if source_id == "masterdb":
            if not self.db:
                return None, "ArchiveDB가 설정되어 있지 않습니다."
            favorite_keys = self._sqlite.list_favorite_keys() if self._sqlite is not None else set()
            masterdb_root = self.cfg.get("masterdb", {}).get("root")
            return cmp_engine.collect_masterdb_entries(self.db, favorite_keys=favorite_keys, masterdb_root=masterdb_root), None
        local = self._find_local(source_id)
        if not local:
            return None, f"GameListSet을 찾을 수 없습니다: {source_id}"
        try:
            return cmp_engine.collect_local_entries(local), None
        except Exception as e:
            return None, str(e)

    def compare_sources(self, source_a, source_b, system=None):
        """source_a/source_b: 'masterdb' 또는 Local id. 반환 row는 왼쪽=source_a,
        오른쪽=source_b 기준이다."""
        if not source_a or not source_b:
            return _err("비교할 두 소스를 모두 선택하세요.")
        if source_a == source_b:
            return _err("서로 다른 두 소스를 선택하세요.")
        left, err = self._compare_collect(source_a)
        if err:
            return _err(err)
        right, err = self._compare_collect(source_b)
        if err:
            return _err(err)
        rows = cmp_engine.compare_entries(left, right, system=system)

        # [SHA256 Compare 컬럼] 이미 있는 SQLite hash cache(get_rom_hash - ROM이
        # 처음 복사될 때 백그라운드로 채워짐, P0-8 참고)에서 조회만 한다 - 여기서
        # 새로 계산하지 않는다. 아직 캐시에 없으면(백그라운드 계산 중이거나 애초에
        # 그 ROM이 한 번도 복사된 적 없음) None으로 두고, JS가 "-"로 표시한다.
        def sha256_for(summary):
            if summary is None or self._sqlite is None:
                return None
            key = dbmod.make_rom_key(summary["system"], summary["filename"])
            return self._sqlite.get_rom_hash(key)

        out = []
        for r in rows:
            left_summary = cmp_engine.summarize_entry(r["left"])
            right_summary = cmp_engine.summarize_entry(r["right"])
            if left_summary is not None:
                left_summary["sha256"] = sha256_for(left_summary)
            if right_summary is not None:
                right_summary["sha256"] = sha256_for(right_summary)
            out.append({
                "system": r["system"], "file": r["file"],
                "left": left_summary, "right": right_summary,
                "matched": r["matched"], "diff": r["diff"],
            })
        return _ok(out)

    def compare_copy_row(self, source_a, source_b, direction, source_system, source_filename):
        """Compare 화면의 한 행을 반대쪽으로 복사한다 (> 또는 < 버튼, 단건)."""
        return self._compare_copy_one(source_a, source_b, direction, source_system, source_filename)

    def compare_copy_rows(self, source_a, source_b, direction, items):
        """[신규] Compare 화면에서 다중 선택한 여러 행을 한꺼번에 복사한다.

        items: [{"system": str, "filename": str}, ...] - 전부 같은 방향(direction)으로
        복사할 출발지 쪽 entry들. 한 항목이 실패해도 나머지는 계속 진행하고,
        결과를 항목별로 모아서 돌려준다(부분 실패를 조용히 감추지 않기 위함).
        반환: {"copied": int, "total": int, "failed": [{"system","filename","error"}, ...]}
        """
        if not items:
            return _err("선택된 항목이 없습니다.")
        copied = 0
        failed = []
        for item in items:
            system, filename = item.get("system"), item.get("filename")
            r = self._compare_copy_one(source_a, source_b, direction, system, filename)
            if r["ok"]:
                copied += 1
            else:
                failed.append({"system": system, "filename": filename, "error": r.get("error", "")})
        return _ok({"copied": copied, "total": len(items), "failed": failed})

    def _compare_copy_one(self, source_a, source_b, direction, source_system, source_filename):
        """Compare 화면의 한 행을 반대쪽으로 복사한다 (> 또는 < 버튼).

        direction: "toRight"(source_a -> source_b) | "toLeft"(source_b -> source_a).
        source_system/source_filename: 복사 '출발지' 쪽 entry의 실제 system/filename
        (fallback 정규화 매칭 시 좌/우 파일명이 다를 수 있어 표시용 row.file이 아니라
        GUI가 방향에 맞는 side의 값을 그대로 넘겨야 한다).

        내부적으로 기존 Import/Export 엔진을 그대로 재사용한다. 한쪽이라도 ArchiveDB면
        기존처럼 Import/Export 엔진을 그대로 쓰고(HANDOFF.md §6과 동일), 양쪽 다
        GameListSet이면 [신규] export_engine.copy_local_to_local()로 ArchiveDB를
        아예 거치지 않고 직접 복사한다 - ArchiveDB 미설정 상태에서도 동작한다.
        """
        if direction not in ("toRight", "toLeft"):
            return _err(f"알 수 없는 방향입니다: {direction}")
        src_id, dst_id = (source_a, source_b) if direction == "toRight" else (source_b, source_a)
        if src_id == dst_id:
            return _err("서로 다른 두 소스를 선택하세요.")

        if src_id != "masterdb" and dst_id != "masterdb":
            src_local = self._find_local(src_id)
            dst_local = self._find_local(dst_id)
            if not src_local:
                return _err(f"GameListSet을 찾을 수 없습니다: {src_id}")
            if not dst_local:
                return _err(f"GameListSet을 찾을 수 없습니다: {dst_id}")
            try:
                options = self.cfg.get("export_options", {})
                result = copy_local_to_local(
                    src_local, dst_local, target_roms=[(source_system, source_filename)],
                    options=options, copy_rom=True, sqlite_repo=self._sqlite,
                    queue_hash_fn=self.request_rom_hash,
                )
            except Exception as e:
                traceback.print_exc()
                return _err(str(e))
            if result.get("exported", 0) < 1:
                if result.get("errors"):
                    return _err(f"복사에 실패했습니다: {result['errors'][0]}")
                if result.get("rom_conflicts"):
                    return _err("대상 GameListSet에 이미 같은 이름의 ROM이 있어 복사하지 않았습니다.")
                return _err("원본에 metadata/media/ROM 중 옮길 내용이 없습니다.")
            # [버그 수정, 리뷰 반영] exported>=1이어도 다른 단계(media/ROM)가 실패했을
            # 수 있다 - 예전엔 errors를 여기서 그냥 버려서 부분 실패가 성공처럼
            # 보고됐다. partial 여부와 errors를 같이 넘겨 GUI가 구분할 수 있게 한다.
            return _ok({
                "exported": result["exported"],
                "partial": bool(result.get("errors")) or bool(result.get("rom_conflicts")),
                "errors": result.get("errors", []), "romConflicts": result.get("rom_conflicts", 0),
            })

        # [P0 버그 수정] import_local_to_masterdb/export_masterdb_to_local을 직접
        # 호출하므로, background job(mutates_db=True)이 열어둔 SQLite 트랜잭션과
        # 동시에 같은 connection을 건드리지 않도록 같은 _db_lock으로 감싼다.
        with self._db_lock:
            try:
                if src_id == "masterdb":
                    if not self.db:
                        return _err("ArchiveDB가 설정되어 있지 않습니다.")
                    master_system, master_filename = source_system, source_filename
                else:
                    src_local = self._find_local(src_id)
                    if not src_local:
                        return _err(f"GameListSet을 찾을 수 없습니다: {src_id}")
                    if not self.db:
                        return _err("ArchiveDB가 설정되어 있지 않습니다.")
                    with self._db_rollback_guard():
                        result = import_local_to_masterdb(
                            src_local, self.cfg["masterdb"]["root"], self.db,
                            target_roms=[(source_system, source_filename)], sqlite_repo=self._sqlite,
                        )
                        # [버그 수정, 2026-09-02] `not`이 반대로 붙어있던 SQLite 재동기화 조건 -
                        # start_import_local_to_masterdb() 위 주석/수정 참고. Compare에서
                        # alias 시스템(msx/msx1 등)의 ROM을 복사하면 정확히 이 경로를 타는데,
                        # 이 버그 때문에 그 ROM이 JSON(self.db)에는 들어갔지만 SQLite에는
                        # 반영되지 않아 - list_masterdb_games()는 SQLite만 읽으므로 - ArchiveDB
                        # 목록에서 안 보이는데 전체 개수(JSON 기반)는 그대로 큰 값으로 뜨는
                        # 증상으로 나타났다.
                        self._save_db(sync_sqlite=bool(result.get("alias_merge_occurred", False)))
                    # [신규] import_local_to_masterdb()는 metadata/media만 옮기고 ROM
                    # 실물 파일은 손대지 않는다(별도 "Export to ArchiveDB > ROM 포함"
                    # 경로에서만 복사됨). Compare에서 다른 GameListSet으로 다시 내보내는
                    # 다음 단계(copy_rom=True)가 원본을 찾을 수 있도록, ROM 파일도
                    # 여기서 ArchiveDB 저장소로 같이 복사해둔다.
                    self._copy_roms_to_masterdb(src_local, target_roms=[(source_system, source_filename)])
                    master_system = cfgmod.canonical_system(src_local, source_system)
                    rom_entry = self.db.get("roms", {}).get(dbmod.make_rom_key(master_system, source_filename))
                    if rom_entry is None:
                        return _err("가져올 metadata/media가 없어 복사할 내용이 없습니다.")
                    master_filename = rom_entry.get("rom_filename", source_filename)

                if dst_id == "masterdb":
                    return _ok(True)  # 위 Import에서 이미 MasterDB에 반영됨

                dst_local = self._find_local(dst_id)
                if not dst_local:
                    return _err(f"GameListSet을 찾을 수 없습니다: {dst_id}")
                options = self.cfg.get("export_options", {})
                export_result = export_masterdb_to_local(
                    dst_local, self.cfg["masterdb"]["root"], self.db, options,
                    conflict_resolver=lambda *a: "ok",
                    target_roms=[(master_system, master_filename)], copy_rom=True, sqlite_repo=self._sqlite,
                )
                # [P0 버그 수정] 예전엔 export_masterdb_to_local()의 반환값을 아예
                # 확인하지 않고 무조건 성공을 반환했다. Export는 대상 Local에 실제
                # ROM 파일이 있어야 매칭되는 정책이라(§HANDOFF), 대상 쪽에 ROM이 없으면
                # exported=0인 채로 "성공"이라고 잘못 표시될 수 있었다 - 실제로는
                # 아무 것도 복사되지 않았는데 UI에는 "복사되었습니다"가 뜨는 상태.
                if export_result.get("exported", 0) < 1:
                    if export_result.get("not_implemented"):
                        return _err(f"{dst_local.get('frontend', '')}은 아직 이 작업을 지원하지 않습니다.")
                    if export_result.get("errors"):
                        return _err(f"복사에 실패했습니다: {export_result['errors'][0]}")
                    if export_result.get("skipped_no_match", 0) > 0:
                        return _err("대상 GameListSet에 실제 ROM 파일이 없어 metadata/media를 복사하지 못했습니다.")
                    if export_result.get("skipped_conflict", 0) > 0:
                        return _err("설정 충돌로 인해 복사하지 못했습니다.")
                    if export_result.get("skipped_korean_dup", 0) > 0:
                        return _err("한글화 우선 정책으로 인해 복사하지 못했습니다.")
                    return _err("복사할 내용이 없어 아무 것도 반영되지 않았습니다.")
                return _ok({"exported": export_result["exported"]})
            except Exception as e:
                traceback.print_exc()
                return _err(str(e))

    # ------------------------------------------------------------------
    def get_version(self):
        from version import __version__
        return _ok(__version__)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def get_settings(self):
        ui = self.cfg.get("ui", {})
        return _ok({
            "lang": ui.get("language", "ko"),
            "theme": ui.get("theme", "dark"),
            "saveInterval": ui.get("auto_save_interval_min", 5),
            "exportOptions": self.cfg.get("export_options", {}),
            # [수정] "archivedb" 기본값 - config.py에도 동일하게 반영했지만, 이미 저장된
            # (이 필드가 없던 구버전) config.json은 config.py의 기본 dict를 안 거치고
            # 이 fallback을 그대로 타므로 여기도 같이 바꿔야 한다.
            "startupPage": ui.get("startup_page", "archivedb"),
            "confirmDestructiveActions": ui.get("confirm_destructive_actions", True),
            "loggingEnabled": ui.get("logging_enabled", False),
            "defaultListView": ui.get("default_list_view", "list"),
            "deferVideoMedia": self.cfg.get("performance", {}).get("defer_video_media", True),
        })

    def save_ui_settings(self, startup_page, confirm_destructive_actions, logging_enabled, default_list_view):
        ui = self.cfg.setdefault("ui", {})
        ui["startup_page"] = startup_page if startup_page in ("dashboard", "archivedb") else "archivedb"
        ui["confirm_destructive_actions"] = bool(confirm_destructive_actions)
        ui["logging_enabled"] = bool(logging_enabled)
        ui["default_list_view"] = default_list_view if default_list_view in ("list", "preview") else "list"
        cfgmod.save_config(self.cfg)
        return _ok(True)

    def save_performance_settings(self, defer_video_media):
        """[체감 속도] Settings > Advanced 토글 - Scan/Import/Export에서 비디오를
        뒤로 미룰지 여부."""
        self.cfg.setdefault("performance", {})["defer_video_media"] = bool(defer_video_media)
        cfgmod.save_config(self.cfg)
        return _ok(True)

    def save_settings(self, lang, theme, save_interval, export_options):
        self.cfg.setdefault("ui", {})["language"] = lang
        self.cfg["ui"]["theme"] = theme
        self.cfg["ui"]["auto_save_interval_min"] = save_interval
        self.cfg["export_options"] = {
            "korean_only_on_conflict": bool(export_options.get("koreanOnly", True)),
            "copy_media": bool(export_options.get("copyMedia", True)),
            "copy_video": bool(export_options.get("copyVideo", True)),
            "force_overwrite": bool(export_options.get("forceOverwrite", False)),
            "selected_media_types": list(export_options.get("selected_media_types", ["screenshots", "3dboxes", "covers", "marquees", "miximages", "wheel"])),
            "copy_rom": bool(export_options.get("copyRom", False)),
        }
        cfgmod.save_config(self.cfg)
        return _ok(True)

    def do_backup(self):
        if not self.cfg.get("masterdb", {}).get("root"):
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        try:
            with self._db_lock:
                if self._sqlite is not None:
                    # WAL 모드에서는 커밋된 데이터가 master.db-wal에 있을 수 있다.
                    # 백업 전에 체크포인트로 전부 master.db 본체에 합쳐야
                    # create_backup()이 -wal/-shm을 제외해도 데이터 유실이 없다.
                    self._sqlite.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                path = create_backup(self.cfg["masterdb"]["root"])
            return _ok({"path": path})
        except Exception as e:
            return _err(str(e))

    def list_backups(self):
        try:
            return _ok([p.name for p in list_backups()])
        except Exception as e:
            return _err(str(e))

    def restore_backup(self, filename):
        """[P0-7] self._db_lock만으로는 phase가 여러 개인 Import/Export를 완전히
        막지 못한다 - _db_lock은 phase 하나(fn 호출 한 번)를 실행하는 동안만
        잡혀 있고, phase와 phase 사이(다음 heavy job으로 넘어가기 전 잠깐의
        틈)에는 풀려 있다. 그 틈에 restore가 self.db/self._sqlite를 통째로
        교체해버리면, 다음 phase는 이미 사라진(또는 복원된 다른 내용의) DB를
        마저 쓰게 된다. Import/Export와 동일하게 "masterdb"가 busy인 동안은
        막는다."""
        busy_err = self._target_busy_error("masterdb")
        if busy_err:
            return busy_err
        if not self.cfg.get("masterdb", {}).get("root"):
            return _err("ArchiveDB가 설정되어 있지 않습니다.")
        try:
            with self._db_lock:
                if self._sqlite is not None:
                    self._sqlite.close()
                    self._sqlite = None
                restore_backup(cfgmod.BACKUP_DIR / filename, self.cfg["masterdb"]["root"])
                self.db = dbmod.load_db(self.cfg["masterdb"]["root"])
                # 복원된 파일 내용으로 SQLite 프로젝션도 다시 맞춰야 한다 - 예전 connection을
                # 그대로 재사용하면 unpack_archive로 통째로 바뀐 파일과 어긋난 상태(WAL 모드라면
                # 더더욱)로 계속 남는다.
                self._sqlite = SQLiteRepository.from_masterdb_root(self.cfg["masterdb"]["root"])
                self._sqlite.replace_from_dict(self.db, self.cfg.get("locals", []))
            return _ok(True)
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    def save_config_now(self):
        cfgmod.save_config(self.cfg)
        return _ok(True)
