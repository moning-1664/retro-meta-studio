"""
bridge/api.py
==============
pywebview 브릿지. JS에서 부를 수 있는 유일한 표면이다.

**얇게 유지한다.** 이전 프로젝트의 `api.py`는 3,400줄짜리 모놀리스로, 브릿지와
비즈니스 로직이 섞여 있어 손대기 어려웠다. 여기서는 인자 변환과 오류 포장만 하고
실제 일은 전부 `app/`으로 내려보낸다. 이 파일에 로직이 쌓이기 시작하면 그건
`app/` 어딘가로 가야 한다는 신호다.

모든 메서드는 `{"ok": True, "data": ...}` 또는 `{"ok": False, "error": "..."}`를
돌려준다. JS 쪽은 이 형태만 알면 된다.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import logging
import sqlite3
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
import traceback
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # Scraper를 쓰지 않는 설치와 테스트는 계속 동작해야 한다.
    requests = None

from adapters import get_adapter
from adapters.base import MediaFile
from app import paths
from app.model.collection import FRONTENDS, STORAGE_INTERNAL
from app.model.constants import MEDIA_TYPES, VIDEO_MEDIA_TYPE, normalize_system, metadata_compatible
from app import dashboard
from app.folder_detection import inspect_folder
from app import collection_import
from app import media_cleanup
from app import media_import
from app import system_ops
from app import storage_layout
from app import title_affix
from app.launch import retroarch
from app.model.plan import OP_ADD, OP_DELETE, OP_ARCHIVE_INGEST, OP_METADATA_EDIT, OP_STORAGE_CHANGE, OP_TITLE_EDIT, RESOLVE_OVERWRITE, RESOLVE_SKIP, Plan, PlanEntry
from app.plan import builder, clipboard, transfer
from app.plan.rom_preview import comparison as rom_comparison
from app.plan.paste_journal import PasteJournal, supports_local_undo
from app.plan.applier import apply_plan, delete_destinations
from app.plan.validator import check_capacity, validate
from app.archive.edit_lock import archive_write, writing as archive_writing, status as archive_lock_status, release_orphan as release_archive_orphan
from app.archive import conflicts as conflict_service
from app.archive import directory as archive_directory
from app.archive import legacy as archive_legacy
from app.archive import projection as archive_projection
from app.archive import shared_cache as archive_shared_cache
from app.archive import service as archive_service
from app.archive import paste as archive_paste_service
from app.archive.file_copy import copy_complete as archive_copy_complete
from app.archive.undo import ArchiveUndo, before_shared_publish, delete_file as archive_delete_file, current_transaction
from app.compare import engine as compare_engine
from app.convert import service as convert_service
from app.match import service as match_service
from app.metadata import service as metadata_service
from app.scrape import ScrapeService
from app.scrape.dat_catalog import DatCatalog
from app.scrape.providers import ScreenScraperClient, ScreenScraperConfig
from app.scrape.providers.screenscraper import SYSTEM_IDS, _system_id
from app.scrape import secrets as scrape_secrets
import storage
from app.store.archive import ARCHIVE_EDIT_SOURCE, ArchiveStore
from app.store.cache import KEY_MEDIA_TYPES
from app.store.registry import CHANGE_APPLIED, RegistryError, RegistryStore
from app.workspace import Workspace, WorkspaceError
from bridge.jobs import JobCancelled, JobManager
from bridge.media_server import MediaServer
import file_ops
from utils import normalize_title

log = logging.getLogger(__name__)

#: JS가 쓰는 표시용 라벨 <-> 저장소의 소문자 키
MEDIA_LABELS = {
    "covers": "Covers", "marquees": "Marquees", "miximages": "Miximages",
    "screenshots": "Screenshots", "videos": "Videos", "wheel": "Wheel",
    "3dboxes": "3DBoxes", "backcovers": "BackCovers", "fanart": "FanArt",
    "manuals": "Manuals", "physicalmedia": "PhysicalMedia",
    "titlescreens": "TitleScreens",
}
MEDIA_KEYS = {v: k for k, v in MEDIA_LABELS.items()}

THUMBNAIL_MAX = 256

#: 캐시해 둘 썸네일 개수. 카드 한 화면이 수십 개이므로 몇 화면 분량이면 충분하다.
THUMBNAIL_CACHE_MAX = 256

#: "캐시에 없음"과 "캐시된 값이 None(=그릴 수 없는 파일)"을 구분하는 표식.
_MISS = object()


def _path_within(path, root) -> bool:
    """Whether ``path`` resolves inside ``root`` (the boundary is inclusive)."""
    if not path or not root:
        return False
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def _sorted_systems(entries, games, *, with_storage=False, stats=None):
    """게임이 있는 System을 먼저, 없는 것을 뒤에. 같은 상태끼리는 이름순.

    빈 System을 별도의 "Empty Systems" 묶음으로 만들지 않는다 - 사용자가 보는 것은
    하나의 System 목록이고, 비어 있다는 사실은 개수(0)가 이미 말해 준다. 정렬
    우선순위만 다르게 준다.
    """
    def item(entry):
        # 목록에 뜨는 게임 수와 같은 값이어야 한다(`count_by_system`).
        row = {"system": entry.system, "count": games.get(entry.system, 0)}
        if with_storage:
            row["storageId"] = entry.storage_id
        # Metadata가 없는 항목 수. 개수 자체를 따로 주지 않고 "빠진 수"만 주는 이유는,
        # 화면이 `count - missingMetadata`로 계산하면 목록에 뜨는 수(count)와 항상
        # 아귀가 맞기 때문이다 - 두 곳에서 따로 센 숫자가 어긋나는 일이 없다.
        #
        # 용량과 Media 누락 수도 같이 준다. Scan이 이미 세어 둔 값이라 추가 비용이
        # 없고, 헤더를 펼쳤을 때 "이 System이 얼마나 차지하고 무엇이 빠졌는지"를
        # Dashboard까지 가지 않고 바로 볼 수 있다.
        if stats is not None:
            stat = stats.get(entry.system) or {}
            row["missingMetadata"] = int(stat.get("missing_metadata") or 0)
            row["missingMedia"] = int(stat.get("missing_media") or 0)
            row["romBytes"] = int(stat.get("rom_bytes") or 0)
            row["mediaBytes"] = int(stat.get("media_bytes") or 0)
        return row

    return sorted((item(e) for e in entries),
                  key=lambda r: (r["count"] == 0, r["system"].lower()))


def ok(data=None):
    return {"ok": True, "data": data}


def err(message):
    return {"ok": False, "error": str(message)}


def guarded(fn):
    """브릿지 메서드에서 새어나간 예외가 JS 쪽 Promise를 깨뜨리지 않게 한다.

    도메인 오류(Collection 없음, Storage에 System이 남아 있음 등)는 사용자에게
    그대로 보여줄 메시지이므로 조용히 돌려보낸다. 예상 못 한 예외만 traceback을
    남긴다 - 둘을 구분하지 않으면 정상 동작 중에도 로그가 traceback으로 뒤덮인다.
    """
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (WorkspaceError, RegistryError, KeyError, ValueError) as e:
            return err(e)
        except Exception as e:  # noqa: BLE001 - 사용자에게 보여줄 오류로 바꾼다
            traceback.print_exc()
            return err(e)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _reveal_path(path, select=False):
    """파일 탐색기로 연다. 테스트는 이 함수를 바꿔 끼운다.

    `select=True`면 폴더를 열지 않고 **그 파일을 고른 채로** 탐색기를 연다(개별
    게임의 ROM/Media 파일을 가리킬 때 - 폴더만 열면 수백 개 파일 중에서 다시
    찾아야 한다). Linux는 탐색기마다 파일 선택 방법이 달라 통일된 방법이 없으므로
    부모 폴더를 여는 것으로 대신한다.
    """
    import os
    import subprocess
    import sys
    if sys.platform.startswith("win"):
        if select:
            # 경로를 리스트 인자로 넘기면(`["explorer", f"/select,{path}"]`) 경로에
            # 공백이 있을 때 Windows가 그 인자 전체를 통째로 다시 따옴표로 감싸고,
            # explorer.exe는 자기만의 명령줄 파서를 쓰기 때문에 그 형태를 못 읽고
            # 조용히 기본 폴더(문서)로 폴백한다(실사용 피드백 - "문서 폴더가 열림").
            # 문자열 하나로 넘기면 Python이 그대로 명령줄로 전달해, `/select,"경로"`
            # 형태를 explorer가 기대하는 그대로 줄 수 있다.
            subprocess.Popen(f'explorer /select,"{path}"')  # noqa: S603,S607
        else:
            os.startfile(path)  # noqa: S606 - 사용자가 고른 Collection 폴더다
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if select else ["open", path])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent) if select else path])


class Api:
    def __init__(self, registry_path=None, cache_dir=None):
        """registry_path/cache_dir는 테스트에서만 넘긴다. 실행 시에는 app/paths.py의
        기본 위치(실행 파일 옆 db/)를 쓴다."""
        if registry_path is None:
            paths.ensure_dirs()
        self.registry = RegistryStore(registry_path or paths.REGISTRY_DB)
        self.workspace = Workspace(self.registry, cache_dir=cache_dir or paths.CACHE_DIR)
        self.jobs = JobManager()
        # Plan은 세션 한정이다(D2). DB에 저장하지 않고 여기서만 들고 있다가 앱이
        # 꺼지면 사라진다.
        self._plans: dict[str, Plan] = {}
        # 복사 작업은 기존 Plan과 섞지 않는다. 미리보기와 실행 사이에만 보관한다.
        self._paste_ops: dict[str, dict] = {}
        undo_root = (Path(cache_dir).parent / "paste_undo") if cache_dir else (paths.DB_DIR / "paste_undo")
        self._paste_journal = PasteJournal(undo_root)
        self._archive_journal = ArchiveUndo(undo_root.parent / "archive_undo")
        self._paste_journal.on_commit = lambda data: self._retain_backups(data["collectionId"])
        self._archive_journal.on_commit = lambda data: self._retain_backups("__archive__")
        self._backup_retention_report = {}
        self._archive_recovery_error = None
        recovered = self._paste_journal.recover_interrupted()
        if recovered:
            log.warning("Recovered %d interrupted paste operation(s): %s",
                        len(recovered), recovered)
        # 썸네일 캐시(LRU). 파일이 그대로면 인코딩 결과도 그대로다.
        self._thumb_cache: OrderedDict = OrderedDict()
        self._clipboard_dir = (Path(cache_dir).parent / "clipboard") if cache_dir else paths.CLIPBOARD_DIR
        self._scrape_cache_dir = ((Path(cache_dir).parent / "scraper_media") if cache_dir
                                  else (paths.CACHE_DIR / "scraper_media"))
        archive_path = (Path(cache_dir).parent / "archive.db") if cache_dir else paths.ARCHIVE_DB
        self._archive_path = Path(archive_path)
        self._archive_lifecycle_lock = threading.RLock()
        self._scrape_apply_lock = threading.Lock()
        self._scrape_apply_jobs = {}
        configured_archive = archive_projection.normalize_config(
            self.registry.get_setting("archive.config", {}))["archiveDir"]
        startup_cfg = archive_projection.normalize_config(self.registry.get_setting("archive.config", {}))
        try:
            has_pending_archive = bool(self._archive_journal.pending(startup_cfg))
        except (OSError, ValueError) as exc:
            has_pending_archive = True
            self._archive_recovery_error = str(exc)
            log.exception("Archive recovery record unreadable; automatic seed disabled")
        if configured_archive and not has_pending_archive:
            try:
                known = self.registry.get_setting("archive.shared_snapshot_hashes", {}) or {}
                digest = archive_shared_cache.seed_if_clean(
                    Path(archive_path), configured_archive, known.get(configured_archive))
                if digest:
                    self.registry.set_setting("archive.shared_snapshot_hashes",
                                              {**known, configured_archive: digest})
                    log.info("Seeded local Archive DB from portable snapshot")
            except (OSError, RuntimeError, sqlite3.DatabaseError) as exc:
                log.warning("Could not load portable Archive snapshot: %s", exc)
        self.archive = ArchiveStore(archive_path)
        if has_pending_archive:
            try:
                with archive_writing(configured_archive), self.archive._conn.lock:
                    related = {}
                    for record in self._archive_journal.pending(startup_cfg):
                        for cid, systems in record.get("relatedCollections", {}).items():
                            related.setdefault(cid, set()).update(systems)
                    self._archive_journal.recover(self.archive, startup_cfg)
                    self._remember_archive_digest(startup_cfg)
                    for cid, systems in related.items():
                        self.workspace.scan(cid, force=True, systems=sorted(systems))
            except Exception as exc:
                self._archive_recovery_error = str(exc)
                log.exception("Archive interrupted operation recovery blocked; backups retained")
        clipboard.prune(self._clipboard_dir)
        # 파일 복사 엔진 선택. 기본은 Robocopy다 - 서명 없는 자체 워커는 백신 행동
        # 기반 탐지에 걸린다는 실사용 보고가 있다(file_ops.py 참고).
        file_ops.select_engine(self.registry.get_setting("copy_engine", file_ops.ENGINE_AUTO))
        self._window = None
        # 창 버튼의 최대화/복원 토글 상태. pywebview가 현재 상태를 알려주지 않아
        # 우리가 들고 있는다.
        self._maximized = False
        # Compare Mode도 Plan처럼 세션 한정이다 - 껐다 켜면 비교 상태는 사라진다.
        # {"baseId":..., "otherId":..., "rows":[...]} 또는 None.
        self._compare = None
        # 영상 전용 로컬 서버(bridge/media_server.py). 처음 영상을 볼 때 켜진다.
        self._media_server = MediaServer()
        dat_path = (Path(cache_dir).parent / "user_dat.db") if cache_dir else (paths.DB_DIR / "user_dat.db")
        self.dat_catalog = DatCatalog(dat_path)
        self.scrape = ScrapeService(self._screen_scraper_client, dat_catalog=self.dat_catalog)

    def close(self):
        """앱 종료. 진행 중인 작업을 먼저 멈춘 뒤에 DB를 닫는다.

        워커 스레드가 쓰고 있는 sqlite 연결을 닫으면 프로세스가 죽는다. 시간 안에
        멈추지 못한 작업이 남아 있으면 연결을 닫지 않고 그대로 둔다 - 어차피 프로세스가
        끝나면서 정리되고, 크래시로 끝나는 것보다 낫다.
        """
        self._media_server.stop()
        if not self.jobs.shutdown(timeout=5.0):
            return
        cache_root = self._scrape_cache_dir.resolve()
        for temporary in cache_root.glob("*/*/*/*.part"):
            try:
                if temporary.resolve().is_relative_to(cache_root) and not temporary.is_symlink():
                    temporary.unlink(missing_ok=True)
            except OSError:
                log.warning("Could not remove incomplete scrape download %s", temporary)
        self.workspace.close()
        self.archive.close()
        self.registry.close()

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------
    @guarded
    def list_collections(self):
        return ok([self._collection_summary(c) for c in self.registry.list_collections()])

    @guarded
    def inspect_collection_folder(self, path):
        """Read-only frontend evidence for a folder selected in the UI."""
        return ok(inspect_folder(path))

    @guarded
    def start_inspect_collection_folder(self, path):
        """Keep slow SMB directory checks off the WebView request thread."""
        job_id = self.jobs.run(
            lambda cb: inspect_folder(path, progress_cb=cb), mutates_state=False)
        return ok({"jobId": job_id})

    @guarded
    def create_collection(self, name, frontend, root_path=None, target=None, arch=None,
                          rom_path=None, media_path=None, storage_label=None):
        """`root_path`는 메타데이터가 있는 곳, `rom_path`는 ROM이 있는 곳이다.

        ES-DE는 이 둘을 떼어 놓는 것이 기본이라 하나만 받으면 반쪽짜리 Collection만
        만들 수 있다(§9). **둘 다 선택 사항이다** - 스크래핑을 한 번도 안 한 사용자는
        ROM만 가지고 있고, 그것도 정상적인 Collection이다. 유효하지 않은 것은 둘 다
        비어 있을 때뿐이며, 그 판단은 Workspace가 한다.
        """
        extra = {}
        if storage_label:
            # 기기 Collection은 Storage 이름이 "Internal"이면 어느 기기인지 알 수 없다.
            extra["internal_label"] = str(storage_label)
        collection = self.workspace.create_collection(
            name, frontend, root_path, target=target or None, arch=arch or None,
            rom_path=rom_path or None, media_path=media_path or None, **extra)
        return ok(self._collection_summary(collection))

    # ------------------------------------------------------------------
    # MTP 기기 (storage/mtp.py) - Metadata(gamelist) 전용 연결
    # ------------------------------------------------------------------
    #: ES-DE 폴더를 찾을 때 기기를 얼마나 깊이 훑을지. MTP는 폴더 하나 여는 것도 비싸서
    #: 기기 전체를 뒤지면 몇 분씩 걸린다 - 안드로이드 ES-DE는 저장소 바로 아래
    #: (`/storage/emulated/0/ES-DE`)에 있으므로 두 단계면 충분하다.
    MTP_SEARCH_DEPTH = 2

    @guarded
    def mtp_devices(self):
        """연결된 안드로이드 기기 목록.

        **기기가 없는 것과 못 읽는 것을 구분해서 돌려준다** - 빈 목록만 주면 화면이
        "USB를 꽂으라는 건지, 뭔가 잘못된 건지"를 말해줄 수 없다.
        """
        from storage import mtp

        # **단계마다 로그를 남긴다.** 목록이 비었을 때 "USB를 안 꽂았다"와 "COM이
        # 안 떴다"와 "Windows가 기기를 0개로 본다"는 전혀 다른 문제인데, 화면에는
        # 셋 다 빈 목록으로 똑같이 보인다(실사용 피드백 - 기기가 탐색기에는
        # 보이는데 여기서는 아무것도 안 나왔다). 로그가 없으면 어느 쪽인지
        # 물어볼 방법조차 없다.
        log.info("MTP 기기 목록 요청")
        try:
            devices = mtp.provider().devices()
        except mtp.MtpError as e:
            log.warning("MTP 기기 목록 실패(MtpError): %s", e)
            return ok({"devices": [], "reason": str(e)})
        except Exception as e:  # noqa: BLE001 - 원인을 통째로 남기고 화면에는 이유만 준다
            log.exception("MTP 기기 목록 실패(예상 못 한 오류)")
            return ok({"devices": [], "reason": f"기기를 찾는 중 오류가 났습니다: {e}"})
        log.info("MTP 기기 목록 결과: %d개 %s", len(devices), [d.name for d in devices])
        return ok({"devices": [{"key": d.key, "name": d.name, "path": mtp.join_path(d.key, [])}
                               for d in devices], "reason": None})

    @guarded
    def mtp_browse(self, path):
        """기기 폴더 한 단계(폴더만). `path`가 기기 루트면 저장소 목록이 나온다."""
        from storage import mtp

        if not mtp.is_mtp_path(path):
            return err("MTP 경로가 아닙니다.")
        device_key, segments = mtp.split_path(path)
        entries = [e for e in mtp.provider().scandir(path) if e.is_dir]
        return ok({
            "path": mtp.join_path(device_key, segments),
            "parent": mtp.join_path(device_key, segments[:-1]) if segments else None,
            "entries": sorted(({"name": e.name, "path": e.path} for e in entries),
                              key=lambda e: e["name"].lower()),
        })

    @guarded
    def mtp_find_esde(self, device_key):
        """기기에서 ES-DE 폴더(`gamelists`를 품은 폴더)와 ROM 폴더 후보를 찾는다.

        얕게만 훑는다(MTP_SEARCH_DEPTH) - 못 찾으면 화면에서 직접 고르면 된다.
        """
        from storage import mtp

        provider = mtp.provider()
        found: list[dict] = []
        roms: list[str] = []

        def walk(segments, depth):
            if depth > self.MTP_SEARCH_DEPTH or len(found) >= 4:
                return
            for entry in provider.scandir(mtp.join_path(device_key, segments)):
                if not entry.is_dir:
                    continue
                here = [*segments, entry.name]
                if provider.exists(mtp.join_path(device_key, [*here, "gamelists"])):
                    found.append({"path": mtp.join_path(device_key, here), "name": entry.name})
                elif entry.name.lower() in ("roms", "rom"):
                    roms.append(mtp.join_path(device_key, here))
                walk(here, depth + 1)

        try:
            walk([], 0)
        except mtp.MtpError as e:
            return err(e)
        return ok({"esde": found, "roms": roms})

    @guarded
    def rename_collection(self, collection_id, name):
        self.registry.update_collection(collection_id, name=name)
        return ok(True)

    @guarded
    def update_collection_target(self, collection_id, target=None, arch=None, os_name=None):
        """Target/OS/Architecture는 별개 값이다(스펙 §5). Frontend는 여기서 못 바꾼다 -
        실제 형식 변환은 Convert가 담당한다."""
        self.registry.update_collection(collection_id, target=target or None,
                                        arch=arch or None, os=os_name or None)
        return ok(True)

    @guarded
    def update_collection_paths(self, collection_id, root_path=None, rom_path=None):
        """"Collection 정보"의 폴더 변경(사용자 결정) - Metadata/ROM 위치를 바꾸고
        강제로 다시 스캔한다.

        **Internal Storage와 Collection root만 옮긴다** - External Storage는 사용자가
        따로 추가한 것이라 이 화면의 몫이 아니다(건드리면 외장 SD의 ROM이 갑자기
        Internal 취급을 받는다). Adapter의 `layout()`은 매번 `collection.root_path`와
        System의 Storage를 새로 읽으므로(app/scan/scanner.py), 여기서 두 값만 바꾸고
        강제 재스캔하면 나머지는 스캔이 새 경로 기준으로 다시 맞춘다.

        **재스캔은 선택이 아니라 필수다** - 화면에서 실행 전에 반드시 경고해야 한다
        (사용자 결정). 옛 경로 기준으로 남아 있는 Cache 항목은 이 호출만으로는 지워지지
        않고, 뒤따르는 전체 재스캔이 사라진 System을 정리한다(scan_collection 참고).
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        meta = str(root_path or "").strip()
        rom = str(rom_path or "").strip()
        if not meta and not rom:
            return err("Metadata 디렉토리와 ROM 디렉토리 중 하나는 입력하세요.")
        new_root = meta or rom
        self.workspace.close_collection(collection_id)
        self.registry.update_collection(collection_id, root_path=new_root)
        self.registry.update_storage(collection_id, STORAGE_INTERNAL, root_path=new_root)
        # ROM이 Metadata와 다른 곳에 있으면 System마다 rom_path를 새 위치로 맞춘다.
        # 같은 곳이면(또는 안 줬으면) 지워서 Internal Storage 기준으로 다시 계산되게
        # 한다. External Storage에 놓인 System은 건드리지 않는다.
        rom_override = rom if (rom and rom != new_root) else None
        for entry in collection.systems:
            if entry.storage_id != STORAGE_INTERNAL:
                continue
            self.registry.upsert_system(collection_id, entry.system, entry.storage_id,
                                        rom_path=rom_override, media_path=entry.media_path,
                                        metadata_path=entry.metadata_path)
        # 실제 재스캔(수천 개짜리 Collection이면 오래 걸린다)은 여기서 동기로 하지
        # 않는다 - 화면이 다른 "다시 스캔"과 같은 방식(start_scan, 진행률 job)으로
        # 이어서 부른다.
        return ok(self._collection_summary(self.registry.get_collection(collection_id)))

    @guarded
    def delete_collection(self, collection_id):
        self._plans.pop(collection_id, None)
        self.workspace.close_collection(collection_id)
        self.registry.delete_collection(collection_id)
        return ok(True)

    @guarded
    def open_collection(self, collection_id):
        self.workspace.open(collection_id)
        return ok(self.collection_detail(collection_id)["data"])

    @guarded
    def close_collection(self, collection_id):
        self.workspace.close_collection(collection_id)
        return ok(True)

    @guarded
    def collection_detail(self, collection_id):
        """헤더와 좌측 내비게이션이 필요로 하는 모든 것."""
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        cache = self.workspace.open(collection_id)
        stats = {s["system"]: s for s in cache.system_stats()}
        games = cache.count_by_system()
        usage = cache.storage_usage()
        provider = self.workspace.provider_for(collection)

        storages = []
        for storage in collection.storages:
            volume = provider.volume_info(storage.root_path)
            storages.append({
                "id": storage.storage_id,
                "kind": storage.kind,
                "label": storage.label or storage.storage_id,
                "rootPath": storage.root_path,
                "actualBytes": usage.get(storage.storage_id, 0),
                # capacity/free가 None이면 Unknown이다 - UI는 용량 막대를 숨긴다.
                "capacityBytes": volume.capacity_bytes,
                "freeBytes": volume.free_bytes,
                "systems": _sorted_systems(collection.systems_in(storage.storage_id), games),
                "deviceId": storage.device_id or "",
                "deviceRoot": storage.device_root or "",
            })

        systems = _sorted_systems(collection.systems, games, with_storage=True, stats=stats)
        clash = self._conflicts(collection)
        for row in systems:
            sides = clash.get(row["system"].lower())
            if sides:
                row["conflict"] = sides

        return ok({
            **self._collection_summary(collection),
            "storages": storages,
            # **좌측 내비게이션이 그리는 것은 이 목록이다.**
            #
            # 예전에는 화면이 `storages[].systems`를 순회해서 Storage를 System의 부모
            # 노드로 그렸고, 그래서 사용자가 요구한 적 없는 `Internal` / `ROM` 분류가
            # 나타났다. Storage는 용량·볼륨·파일 작업을 위한 내부 개념이고, 사용자가
            # 보는 단위는 System이다. 어느 Storage에 있는지는 각 항목이 들고만 있고
            # (배지/툴팁용), 계층을 만들지 않는다.
            "systems": systems,
            "totalGames": cache.count_rows(),
            "totalMissingMetadata": sum(int(s.get("missing_metadata") or 0) for s in stats.values()),
            "totalMissingMedia": sum(int(s.get("missing_media") or 0) for s in stats.values()),
            "totalRomBytes": sum(int(s.get("rom_bytes") or 0) for s in stats.values()),
            "totalMediaBytes": sum(int(s.get("media_bytes") or 0) for s in stats.values()),
        })

    def _collection_summary(self, collection):
        return {
            "id": collection.id,
            "name": collection.name,
            "frontend": collection.frontend,
            "frontendLabel": get_adapter(collection.frontend).display_name,
            "target": collection.target,
            "os": collection.os,
            "arch": collection.arch,
            "rootPath": collection.root_path,
            "systemCount": len(collection.systems),
            # 화면이 기기 Collection을 다르게 그려야 하는 두 가지.
            # isDevice: 편집이 Plan을 거친다. metadataOnly: ROM이 없는 것이 정상이다.
            "isDevice": collection.is_device,
            "metadataOnly": collection.metadata_only,
        }

    # ------------------------------------------------------------------
    # Storage / System
    # ------------------------------------------------------------------
    @guarded
    def save_ui_state(self, collection_id, state):
        """컬럼 너비/정렬/미리보기처럼 **사용자가 맞춰 놓은 화면 상태**를 저장한다.

        Collection마다 다르게 기억한다 - System 구성이 다르면 보고 싶은 컬럼 폭도
        다르다. 저장 위치(`collections.ui_state_json`)는 처음부터 있었는데 읽고 쓰는
        길이 없어서, 앱을 닫으면 사용자가 맞춰 놓은 것이 전부 사라졌다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        merged = {**(collection.ui_state or {}), **(state or {})}
        self.registry.update_collection(collection_id, ui_state=merged)
        return ok(merged)

    @guarded
    def get_ui_state(self, collection_id):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        return ok(collection.ui_state or {})

    #: 앱 전역 설정(Settings 화면)이 registry의 app_settings에 들어가는 키.
    APP_SETTINGS_KEY = "ui.settings"
    SCRAPER_SECRET_KEY = "scraper.secrets"
    #: Collection → Collection 복사(붙여넣기) 정책의 기본값. Settings > Import / Export가 바꾼다.
    #: conflict가 "ask"면 지금처럼 Plan에 충돌로 남겨 사용자가 고른다.
    #: unmatchedRom*은 **원본에 ROM이 없고 대상에도 그 게임이 없는 항목**(Archive처럼 메타데이터만
    #: 있는 항목을 새로 붙이는 경우)의 처리 방식이다. Metadata/Media/Video를 독립적으로 고른다.
    #:
    #: **기본이 "copy"다(사용자 결정, 번복).** 예전 기본값은 "skip"이라, 원본에 ROM 파일이
    #: 없다는 이유만으로 메타데이터와 미디어까지 통째로 버렸다 - 이 앱의 핵심 관리 대상은
    #: Metadata/Media이고 ROM은 선택적 구성요소라는 원칙과 정면으로 어긋난다(실사용 리포트 -
    #: Archive 성격의 Collection에서 84개를 복사했는데 76개가 "ROM 미매칭"으로 사라졌다).
    #: 버릴지 말지는 아래 세 스위치로 고른다.
    #:
    #: registry에는 평평하게 저장한다 - "transfer" 섹션 patch는 한 단계 깊이까지만
    #: 병합되므로(save_app_settings), 중첩 객체로 두면 필드 하나만 바꿔도 나머지가 지워진다.
    TRANSFER_DEFAULTS = {
        "includeRom": True, "includeMedia": True, "conflict": "ask",
        # 붙여넣기 모드(Patch/Overwrite/Replace) - app/plan/transfer.py
        "pasteMode": transfer.DEFAULT_MODE,
        "unmatchedRomMode": "copy",
        "unmatchedRomMetadata": True, "unmatchedRomMedia": True, "unmatchedRomVideo": True,
    }

    @guarded
    def get_app_settings(self):
        """Settings 화면의 값. Collection마다가 아니라 **앱 전체에 하나**다.

        ui/stitch-v2-redesign은 이것을 브라우저 localStorage에 뒀다 - 그러면 백엔드
        (복사 정책 같은 것)가 읽을 수 없고, WebView 저장소가 지워지면 함께 사라진다.
        """
        return ok(self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {})

    @guarded
    def save_app_settings(self, patch):
        """바뀐 부분만 받아 합친다. 섹션(appearance, gamelist...) 단위로 한 단계
        깊이까지 병합한다 - 한 섹션의 값 하나를 바꾸려고 나머지를 다 보낼 필요가 없다."""
        if not isinstance(patch, dict):
            return err("설정 형식이 올바르지 않습니다.")
        merged = dict(self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {})
        for section, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(section), dict):
                merged[section] = {**merged[section], **value}
            else:
                merged[section] = value
        if "backupRetention" in patch:
            from app.plan.backup_retention import policy
            merged["backupRetention"] = policy(merged.get("backupRetention"))
        self.registry.set_setting(self.APP_SETTINGS_KEY, merged)
        return ok(merged)

    def _screen_scraper_client(self):
        public = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("scraper") or {}
        protected = self.registry.get_setting(self.SCRAPER_SECRET_KEY, {}) or {}
        return ScreenScraperClient(ScreenScraperConfig(
            dev_id=scrape_secrets.load(protected.get("devId") or ""),
            dev_password=scrape_secrets.load(protected.get("devPassword") or ""),
            soft_name=str(public.get("softName") or "RetroMetaStudio"),
            user_id=str(public.get("userId") or ""),
            user_password=scrape_secrets.load(protected.get("userPassword") or ""),
            # 작은 ROM과 단일 파일 ZIP은 해시를 우선한다. 대용량 파일과
            # 다중 파일 ZIP은 provider에서 전체 읽기를 피한다.
            use_hashes=bool(public.get("useHashes", True)),
            media_types=tuple(public["mediaTypes"]) if "mediaTypes" in public else None,
        ))

    @guarded
    def scraper_settings(self):
        public = dict((self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("scraper") or {})
        protected = self.registry.get_setting(self.SCRAPER_SECRET_KEY, {}) or {}
        public.update({"devIdSet": bool(protected.get("devId")),
                       "devPasswordSet": bool(protected.get("devPassword")),
                       "userPasswordSet": bool(protected.get("userPassword"))})
        return ok(public)

    @guarded
    def scraper_systems(self):
        return ok([{"name": name, "id": system_id}
                   for name, system_id in sorted(SYSTEM_IDS.items())
                   if name != "vita" and (system_id != 75 or name == "arcade")])

    @guarded
    def save_scraper_settings(self, patch):
        if not isinstance(patch, dict):
            return err("스크래퍼 설정 형식이 올바르지 않습니다.")
        settings = dict(self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {})
        public = dict(settings.get("scraper") or {})
        for key in ("enabled", "softName", "userId", "useHashes", "mediaTypes"):
            if key in patch:
                public[key] = patch[key]
        settings["scraper"] = public
        self.registry.set_setting(self.APP_SETTINGS_KEY, settings)
        protected = dict(self.registry.get_setting(self.SCRAPER_SECRET_KEY, {}) or {})
        for key in ("devId", "devPassword", "userPassword"):
            if key in patch and patch[key] is not None:
                value = str(patch[key])
                if value:
                    protected[key] = scrape_secrets.store(f"scraper/{key}", value)
                else:
                    scrape_secrets.delete(protected.get(key) or "")
                    protected.pop(key, None)
        self.registry.set_setting(self.SCRAPER_SECRET_KEY, protected)
        return self.scraper_settings()

    @guarded
    def start_scraper_account_status(self):
        job_id = self.jobs.run(lambda cb: self._scraper_account_job(cb), mutates_state=False)
        return ok({"jobId": job_id})

    @guarded
    def dat_sources(self):
        return ok(self.dat_catalog.sources())

    @guarded
    def start_dat_import(self, file_path, system):
        if not file_path or not Path(file_path).is_file():
            return err("DAT XML 파일을 선택하세요.")
        if not str(system or "").strip():
            return err("DAT에 대응할 System을 선택하세요.")
        job_id = self.jobs.run(
            lambda cb: self.dat_catalog.import_xml(file_path, system, cb),
            mutates_state=True)
        return ok({"jobId": job_id})

    def _scraper_account_job(self, progress):
        progress(0, 1, "ScreenScraper 계정 확인")
        status = self._screen_scraper_client().account_status()
        progress(1, 1, "연결됨")
        return status

    @guarded
    def create_scrape_session(self, target, collection_id=None, item_ids=None):
        target = str(target or "collection")
        ids = [str(value) for value in (item_ids or [])]
        if not ids:
            return err("스크랩할 게임을 선택하세요.")
        items = []
        if target == "archive":
            for identity_id in ids:
                detail = archive_service.detail(self.archive, identity_id)
                if detail is None:
                    continue
                path = next((source.get("abs_path") for source in detail.get("romSources") or []
                             if source.get("abs_path") and Path(source["abs_path"]).is_file()), None)
                items.append(self.scrape.item(
                    identity_id, detail["system"], detail["filename"], detail.get("fields"),
                    path=path, size=detail.get("size")))
        else:
            collection = self.registry.get_collection(collection_id)
            if collection is None:
                return err("Collection을 찾을 수 없습니다.")
            cache = self.workspace.open(collection_id)
            adapter = get_adapter(collection.frontend)
            for uid in ids:
                row = cache.get_row(int(uid))
                if row is None:
                    continue
                layout = adapter.layout(collection, row["system"])
                path = str(Path(layout.rom_dir) / row["filename"]) if layout.rom_dir else None
                items.append(self.scrape.item(uid, row["system"], row["filename"], row["fields"],
                                              path=path, size=row["size"]))
        if not items:
            return err("스크랩할 항목을 찾을 수 없습니다.")
        for item in items:
            match = self.registry.scrape_confirmed_match(
                target, collection_id, item["system"], item["filename"], item.get("size"))
            if match and match["provider"] == "screenscraper":
                item["confirmedGameId"] = match["remote_game_id"]
        session = self.scrape.sessions.create(target, collection_id, items)
        return ok({"id": session["id"], "target": target, "collectionId": collection_id,
                   "items": items, "quota": None})

    @guarded
    def scrape_session(self, session_id):
        return ok(self.scrape.sessions.get(session_id))

    @guarded
    def clear_scrape_confirmed_match(self, session_id, item_id):
        session = self.scrape.sessions.get(str(session_id))
        item = next((row for row in session["items"] if row["id"] == str(item_id)), None)
        if item is None:
            return err("스크랩할 항목을 찾을 수 없습니다.")
        self.registry.delete_scrape_confirmed_match(
            session["target"], session.get("collectionId"), item["system"],
            item["filename"], item.get("size"))
        system_id = _system_id(item.get("systemHint") or item["system"])
        if system_id:
            self.registry.delete_scrape_query_alias(
                "screenscraper", system_id, item.get("requestedQuery") or item["originalQuery"])
        item.pop("confirmedGameId", None)
        item.pop("aliasGameId", None)
        return ok({"cleared": True})

    @guarded
    def start_scrape_item(self, session_id, item_id, query=None, system_hint=None,
                          force_search=False):
        # Search is network and hash I/O. Keep it outside the UI thread; it does
        # not mutate Collection/Archive state until apply_scrape_session().
        session = self.scrape.sessions.get(str(session_id))
        item = next((row for row in session["items"] if row["id"] == str(item_id)), None)
        if item is None:
            return err("스크랩할 항목을 찾을 수 없습니다.")
        selected_system = item["system"] if system_hint is None else str(system_hint)
        system_id = _system_id(selected_system)
        item["aliasGameId"] = (self.registry.scrape_query_alias(
            "screenscraper", system_id, str(query or item["query"]).strip())
            if system_id else None)
        item["systemHint"] = selected_system
        job_id = self.jobs.run(
            lambda cb: self.scrape.search_item(str(session_id), str(item_id), query,
                                                system_hint, progress=cb,
                                                force_search=bool(force_search)),
            mutates_state=False)
        return ok({"jobId": job_id})

    @guarded
    def select_scrape_candidate(self, session_id, item_id, candidate_id, fields=None, media=None):
        selected = self.scrape.select(str(session_id), str(item_id), str(candidate_id),
                                      fields if fields is not None else None,
                                      media if media is not None else None)
        log.info("Scraper candidate selected item=%s candidate=%s fields=%d mediaIndexes=%s",
                 item_id, candidate_id, len(selected["selectedFields"]), selected["selectedMedia"])
        return ok(selected)

    @guarded
    def skip_scrape_item(self, session_id, item_id):
        return ok(self.scrape.skip(str(session_id), str(item_id)))

    @guarded
    def cancel_scrape_session(self, session_id):
        return ok(self.scrape.sessions.close(str(session_id)))

    @guarded
    def start_apply_scrape_session(self, session_id):
        with self._scrape_apply_lock:
            current = self._scrape_apply_jobs.get(str(session_id))
            job = self.jobs.get(current) if current else None
            if job and not job.get("done"):
                return ok({"jobId": current})
            result = self._start_apply_scrape_session(session_id)
            if result.get("ok"):
                self._scrape_apply_jobs[str(session_id)] = result["data"]["jobId"]
            return result

    def _start_apply_scrape_session(self, session_id):
        session = self.scrape.sessions.get(str(session_id))
        log.info("Scraper apply requested session=%s target=%s selected=%d total=%d",
                 session_id, session["target"],
                 sum(bool(self.scrape.proposal(item)) for item in session["items"]),
                 len(session["items"]))
        # The existing save_fields/media_paste APIs perform their own target
        # checks. A regular mutating job gives the operation the global write
        # lock without marking its own target busy and blocking those APIs.
        job_id = self.jobs.run(
            lambda cb: self._apply_scrape_session(str(session_id), cb), mutates_state=True)
        return ok({"jobId": job_id})

    def _download_scrape_media(self, url, session_id, item_id, media_type, media_format=""):
        parsed = urlparse(str(url or ""))
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (hostname == "screenscraper.fr" or hostname.endswith(".screenscraper.fr")):
            raise ValueError("허용되지 않은 미디어 주소입니다.")
        if requests is None:
            raise RuntimeError("미디어 다운로드 모듈(requests)이 설치되지 않았습니다.")
        allowed_suffixes = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".avi", ".pdf")
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in allowed_suffixes:
            suffix = "." + str(media_format or "").lower().lstrip(".")
        if suffix not in allowed_suffixes:
            suffix = ""
        name = hashlib.sha256(str(url).encode("utf-8")).hexdigest()
        folder = self._scrape_cache_dir / str(session_id) / str(item_id) / str(media_type)
        folder.mkdir(parents=True, exist_ok=True)
        for existing_suffix in allowed_suffixes:
            destination = folder / (name + existing_suffix)
            if destination.is_file():
                log.info("Scraper media cache hit item=%s type=%s bytes=%d format=%s",
                         item_id, media_type, destination.stat().st_size, existing_suffix)
                return str(destination)
        temporary = folder / (name + ".part")
        total = 0
        started = time.monotonic()
        try:
            with requests.get(url, timeout=30, stream=True) as response:
                response.raise_for_status()
                if not suffix:
                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                    suffix = {"image/png": ".png", "image/jpeg": ".jpg",
                              "image/webp": ".webp", "image/gif": ".gif",
                              "video/mp4": ".mp4", "video/x-msvideo": ".avi",
                              "application/pdf": ".pdf"}.get(content_type, "")
                if not suffix:
                    raise ValueError("스크랩 미디어 파일 형식을 확인할 수 없습니다.")
                with temporary.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 256):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > 256 * 1024 * 1024:
                            raise ValueError("미디어 파일이 허용 크기를 넘었습니다.")
                        stream.write(chunk)
            destination = folder / (name + suffix)
            temporary.replace(destination)
            log.info("Scraper media download item=%s type=%s bytes=%d format=%s seconds=%.3f",
                     item_id, media_type, total, suffix, time.monotonic() - started)
            return str(destination)
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise RuntimeError(f"미디어 다운로드 실패 ({type(exc).__name__}, HTTP {status or '응답 없음'})") from None
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def _apply_scraped_collection_media(self, collection_id, rom_uid, downloaded):
        """Apply only this scraper's media, leaving the user's existing Plan alone."""
        collection, cache, provider = self._plan_context(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            raise ValueError("스크랩 대상 게임을 찾을 수 없습니다.")
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(collection, [row["system"]])
        if blocked:
            raise ValueError(blocked.get("error") or "미디어를 쓸 수 없습니다.")
        item = {"system": row["system"], "filename": row["filename"], "rom": None,
                "media": [{"type": media_type, "path": path, "size": Path(path).stat().st_size}
                          for media_type, path in downloaded],
                "fields": row["fields"], "frontend_raw": row["frontend_raw"]}
        stage_started = time.monotonic()
        plan = Plan(collection_id)
        result = builder.plan_add(plan, collection, provider, [item])
        log.info("Scraper media plan collection=%s romUid=%s added=%s skipped=%d conflicts=%s",
                 collection_id, rom_uid, result.get("added"), len(result.get("skipped") or []),
                 result.get("conflicts"))
        if result.get("added") != 1:
            raise ValueError("스크랩 미디어를 Plan에 올리지 못했습니다.")
        for key in result.pop("conflictKeys", []):
            builder.resolve_conflict(plan, collection, provider, key, RESOLVE_OVERWRITE)
        validation = validate(plan, collection, cache, provider)
        if not validation["ok"] and not validation["blocked"]:
            log.warning("Scraper media plan invalid collection=%s romUid=%s reasons=%s",
                        collection_id, rom_uid, validation.get("entries"))
            reason = next((problem.get("error") for problem in validation.get("entries") or []
                           if problem.get("error")), "미디어 Plan 검증에 실패했습니다.")
            raise ValueError(f"스크랩 미디어를 적용하지 못했습니다: {reason}")
        if validation["blocked"]:
            log.warning("Scraper media plan blocked collection=%s romUid=%s reasons=%s",
                        collection_id, rom_uid, validation)
            raise ValueError("스크랩 미디어를 저장할 공간이 부족합니다.")
        lock_name = f"apply:{collection_id}"
        if not self.registry.acquire_lock(lock_name, kind="apply"):
            raise ValueError("다른 창에서 같은 Collection을 적용하는 중입니다.")
        try:
            outcome = apply_plan(plan, collection, cache, self.registry, provider,
                                 disc_titles=self._disc_title_option())
            log.info("Scraper collection media apply collection=%s romUid=%s types=%s outcome=%s",
                     collection_id, rom_uid, [kind for kind, _ in downloaded], outcome)
        finally:
            self.registry.release_lock(lock_name)
        if (outcome.get("applied") != 1 or outcome.get("failed")
                or outcome.get("partial") or outcome.get("skipped")):
            raise ValueError("스크랩 미디어 적용이 완료되지 않았습니다. 로그를 확인하세요.")
        log.info("Scraper collection media pipeline collection=%s romUid=%s seconds=%.3f",
                 collection_id, rom_uid, time.monotonic() - stage_started)
        return outcome.get("systems") or []

    def _rebind_plan_rows(self, collection_id, systems):
        """A rescan assigns new cache IDs; keep pending Plan entries on their game."""
        plan = self._plans.get(collection_id)
        if not plan or not len(plan):
            return
        cache = self.workspace.open(collection_id)
        rows = {(row["system"], row["filename"]): row["rom_uid"]
                for row in cache.query_rows(systems=list(systems))}
        for entry in plan.entries:
            if entry.rom_uid is not None and entry.system in systems:
                entry.rom_uid = rows.get((entry.system, entry.filename))
                if entry.rom_uid is None:
                    log.warning("Plan target missing after scan collection=%s system=%s filename=%s",
                                collection_id, entry.system, entry.filename)

    def _apply_scrape_session(self, session_id, progress):
        session = self.scrape.sessions.get(str(session_id))
        applied, partial, failed = [], [], []
        touched_systems = set()
        selected = [item for item in session["items"] if self.scrape.proposal(item)]
        for index, item in enumerate(selected, start=1):
            progress(index - 1, max(1, len(selected)), item["filename"])
            proposal = self.scrape.proposal(item)
            if not proposal:
                continue
            # A media Apply rescans the Collection and may assign fresh rom_uid
            # values to every row. The session ID stays stable for review, but
            # writes must target the current row identified by system/file.
            target_rom_uid = None
            if session["target"] == "collection":
                current = self.workspace.open(session["collectionId"]).get_row_by_filename(
                    item["system"], item["filename"])
                if current is None:
                    message = "원본 Collection에서 스크랩 대상 게임을 찾을 수 없습니다."
                    item["status"] = "selected"
                    failed.append({"itemId": item["id"], "error": message,
                                   "fieldsApplied": [], "mediaApplied": []})
                    log.warning("Scraper target missing collection=%s sessionItem=%s system=%s filename=%s",
                                session["collectionId"], item["id"], item["system"], item["filename"])
                    continue
                target_rom_uid = current["rom_uid"]
                log.info("Scraper target resolved sessionItem=%s currentRomUid=%s system=%s filename=%s",
                         item["id"], target_rom_uid, item["system"], item["filename"])
            item_started = time.monotonic()
            log.info("Scraper apply start item=%s target=%s fields=%d media=%s",
                     item["id"], session["target"], len(proposal["fields"]),
                     [media.get("media_type") for media in proposal["media"]])
            applied_fields, applied_media, errors = {}, [], []
            fields_failed = False
            failed_media_indexes = []
            if proposal["fields"]:
                try:
                    if session["target"] == "archive":
                        result = self.archive_edit(item["id"], {**(item.get("fields") or {}),
                                                                **proposal["fields"]})
                    else:
                        result = self.save_fields(session["collectionId"], target_rom_uid,
                                                  proposal["fields"])
                    if not result.get("ok"):
                        raise ValueError(result.get("error"))
                    applied_fields = proposal["fields"]
                    log.info("Scraper metadata applied item=%s fields=%d seconds=%.3f",
                             item["id"], len(applied_fields), time.monotonic() - item_started)
                except Exception as exc:
                    fields_failed = True
                    errors.append(f"메타데이터: {exc}")
                    log.warning("Scraper metadata failed item=%s error=%s: %s",
                                item["id"], type(exc).__name__, exc)
            if proposal["media"]:
                if session["target"] == "archive" and not self._archive_config().get("mediaInternal"):
                    log.warning("Scraper media blocked item=%s target=archive mediaInternal=false",
                                item["id"])
                    failed_media_indexes.extend(item.get("selectedMedia") or [])
                    errors.append("미디어: Archive 내부 미디어 보관이 꺼져 있습니다.")
                else:
                    downloaded = []
                    selected_media = list(zip(item.get("selectedMedia") or [], proposal["media"]))
                    # Card previews load in WebView; Python has not downloaded
                    # them yet. Fetch independent media concurrently, then
                    # apply serially so Archive/Collection writes stay ordered.
                    with ThreadPoolExecutor(max_workers=min(3, len(selected_media) or 1)) as pool:
                        futures = [pool.submit(self._download_scrape_media, media["url"],
                                               session_id, item["id"], media["media_type"],
                                               media.get("format"))
                                   for _media_index, media in selected_media]
                        for number, ((media_index, media), future) in enumerate(
                                zip(selected_media, futures), start=1):
                            progress(index - 1, max(1, len(selected)),
                                     f'{item["filename"]} · 미디어 {number}/{len(selected_media)}')
                            try:
                                source_path = future.result()
                                if session["target"] == "archive":
                                    result = self.archive_media_paste(
                                        item["id"], media["media_type"],
                                        {"kind": "scraper", "path": source_path})
                                    if not result.get("ok"):
                                        raise ValueError(result.get("error"))
                                    applied_media.append(media)
                                    log.info("Scraper archive media applied item=%s type=%s",
                                             item["id"], media["media_type"])
                                else:
                                    downloaded.append((media_index, media, source_path))
                            except Exception as exc:
                                failed_media_indexes.append(media_index)
                                errors.append(f'{media.get("media_type") or "미디어"}: {exc}')
                                log.warning("Scraper media failed item=%s type=%s error=%s: %s",
                                            item["id"], media.get("media_type"), type(exc).__name__, exc)
                    if downloaded:
                        try:
                            touched_systems.update(self._apply_scraped_collection_media(
                                session["collectionId"], target_rom_uid,
                                [(media["media_type"], path) for _, media, path in downloaded]) or [])
                            applied_media.extend(media for _, media, _ in downloaded)
                            log.info("Scraper collection media applied item=%s types=%s",
                                     item["id"], [media["media_type"] for _, media, _ in downloaded])
                        except Exception as exc:
                            failed_media_indexes.extend(media_index for media_index, _, _ in downloaded)
                            errors.append(f"미디어 적용: {exc}")
                            log.warning("Scraper collection media failed item=%s error=%s: %s",
                                        item["id"], type(exc).__name__, exc)
            changed = bool(applied_fields or applied_media)
            if changed:
                provenance = proposal["provenance"]
                self.registry.add_scrape_provenance(
                    target_kind=session["target"], collection_id=session.get("collectionId"),
                    item_id=(target_rom_uid if target_rom_uid is not None else item["id"]),
                    provider=provenance["provider"],
                    remote_game_id=provenance["remoteGameId"], source_url=provenance["sourceUrl"],
                    evidence=provenance["evidence"], fields=applied_fields, media=applied_media)
                if not errors and provenance.get("remoteGameId"):
                    self.registry.set_scrape_confirmed_match(
                        target_kind=session["target"], collection_id=session.get("collectionId"),
                        system=item["system"], filename=item["filename"], size=item.get("size"),
                        provider=provenance["provider"],
                        remote_game_id=provenance["remoteGameId"])
                    system_id = _system_id(item.get("systemHint") or item["system"])
                    if system_id:
                        self.registry.set_scrape_query_alias(
                            provenance["provider"], system_id,
                            item.get("requestedQuery") or item["originalQuery"],
                            provenance["remoteGameId"])
            if errors:
                log.warning("Scraper apply item=%s target=%s failed: %s",
                            item["id"], session["target"], "; ".join(errors))
                item["selectedFields"] = (item.get("selectedFields") or []) if fields_failed else []
                item["selectedMedia"] = failed_media_indexes
                item["status"] = "selected"
                record = {"itemId": item["id"], "error": "; ".join(errors),
                          "fieldsApplied": list(applied_fields),
                          "mediaApplied": [media["media_type"] for media in applied_media]}
                (partial if changed else failed).append(record)
            else:
                item.update({"selectedCandidateId": None, "selectedFields": [],
                             "selectedMedia": [], "status": "applied"})
                applied.append(item["id"])
            log.info("Scraper apply end item=%s fieldsApplied=%d mediaApplied=%s errors=%d seconds=%.3f",
                     item["id"], len(applied_fields), [m["media_type"] for m in applied_media],
                     len(errors), time.monotonic() - item_started)
            progress(index, max(1, len(selected)), item["filename"])
        if touched_systems and session["target"] == "collection":
            systems = sorted(touched_systems)
            self.workspace.scan(session["collectionId"], force=True, systems=systems)
            self._rebind_plan_rows(session["collectionId"], systems)
        if not failed and not partial and all(
                item["status"] in ("applied", "skipped") for item in session["items"]):
            self.scrape.sessions.close(str(session_id))
        return {"applied": applied, "partial": partial, "failed": failed}

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @guarded
    def dashboard_stats(self, collection_id):
        """Dashboard 화면의 숫자들. 읽기만 한다 - 스캔도 파일 변경도 하지 않는다.

        ui/stitch-v2-redesign은 이것을 main.py에서 Api 인스턴스에 런타임으로 붙였다
        (`install_dashboard`) - 오류 처리(@guarded)도 테스트도 없이 Cache 내부
        연결을 밖에서 직접 썼다. 계산은 app/dashboard.py로 옮겼다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        cache = self.workspace.open(collection_id)
        data = dashboard.collection_stats(collection, cache)
        # 용량/여유 공간은 collection_detail과 같은 곳(볼륨 정보)에서 읽는다.
        provider = self.workspace.provider_for(collection)
        for storage, bucket in zip(collection.storages, data["storages"]):
            volume = provider.volume_info(storage.root_path)
            bucket["capacityBytes"] = volume.capacity_bytes
            bucket["freeBytes"] = volume.free_bytes
        return ok({"collectionId": collection.id, "collectionName": collection.name, **data})

    @guarded
    def validate_collection(self, collection_id):
        """Metadata 파일이 실제로 읽히는지부터 ROM/Media 연결까지 본다. 고치지는 않는다.

        집계(Complete/Missing Media/Missing Description)는 Dashboard 통계와 같은
        기준(cache.metadata_health())을 쓴다 - app/dashboard.py의 docstring 참고.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")

        # **검사 전에 Cache를 맞춘다.** 이 리포트는 두 곳에서 나온다 - 깨진 XML이나
        # 없는 ROM 같은 것은 파일을 그 자리에서 읽어 알아내지만, Complete/Missing
        # Description 같은 집계는 Cache(=지난 스캔의 기억)에서 온다. 맞춰 두지 않으면
        # 한 리포트 안에서 절반은 지금 상태, 절반은 지난번 상태가 되어 사용자가
        # 어느 쪽을 믿어야 할지 알 수 없다(실제로 앱 밖에서 설명을 채운 뒤 검사하면
        # "Missing Description 2"가 그대로 남았다).
        #
        # 스캔은 지문으로 걸러지므로 바뀐 게 없으면 거의 공짜다 - 바뀐 게 있다면
        # 그 재스캔이야말로 정확한 숫자를 내는 데 꼭 필요한 일이다.
        #
        # **스캔이 실패하면 그 사실을 숨기지 않는다.** 조용히 넘어가면 옛 Cache로
        # 계산한 숫자가 지금 숫자인 척 나가고, 이 재스캔이 막으려던 바로 그 상태로
        # 되돌아간다 - 게다가 이번엔 사용자가 알아챌 방법조차 없다. 파일을 직접 읽어
        # 얻는 항목(깨진 XML·없는 ROM·중복)은 Cache와 무관하게 여전히 정확하므로
        # 검사 자체는 끝까지 하고, Cache에서 온 숫자만 «믿을 수 없음»으로 표시한다.
        stale_reason = None
        try:
            self.workspace.scan(collection_id)
        except Exception as e:  # noqa: BLE001
            stale_reason = str(e) or e.__class__.__name__

        cache = self.workspace.open(collection_id)
        provider = self.workspace.provider_for(collection)
        report = dashboard.validate_collection(collection, get_adapter(collection.frontend),
                                               cache, provider)
        # 화면이 숫자를 흐리게 보여주고 이유를 말할 수 있도록 함께 내보낸다.
        report["countsStale"] = stale_reason is not None
        report["staleReason"] = stale_reason
        return ok(report)

    @guarded
    def set_favorite(self, collection_id, rom_uid, favorite=True):
        """즐겨찾기를 켜고 끈다. **Frontend의 파일에 그대로 기록한다.**

        사용자에게는 별표 하나지만 저장 위치는 Frontend마다 다르다(ES-DE는
        gamelist.xml의 `<favorite>`). 우리가 아는 공통 필드가 아니므로
        `frontend_raw`를 통해 다룬다 - 그래야 ES-DE가 다음에 열었을 때 그 별표를
        똑같이 본다. 우리 DB에만 적어 두면 Frontend에서는 즐겨찾기가 아니다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        blocked = self._ensure_writable(collection, [row["system"]])
        if blocked:
            return blocked

        adapter = get_adapter(collection.frontend)
        tag = getattr(adapter, "FAVORITE_TAG", None)
        if not tag:
            return err(f"{adapter.display_name}는 즐겨찾기를 지원하지 않습니다.")

        # **해제는 태그를 지우는 것이 아니라 false로 적는 것이다.** Adapter는 "모르는
        # 태그를 버리지 않는다"가 원칙이라, raw에서 빼도 파일에 이미 있는 요소는
        # 그대로 남는다. ES-DE도 `<favorite>false</favorite>`를 정상으로 읽는다.
        raw = dict(row.get("frontend_raw") or {})
        extra = [dict(item) for item in (raw.get("extra") or [])
                 if (item.get("tag") or item.get("key")) != tag]
        extra.append(adapter.favorite_raw(bool(favorite)))
        raw["extra"] = extra

        saved = self.save_fields(collection_id, rom_uid, row.get("fields") or {},
                                 frontend_raw=raw)
        if not saved["ok"]:
            return saved
        cache.set_favorite(int(rom_uid), favorite)
        return ok({"romUid": int(rom_uid), "favorite": bool(favorite)})

    @guarded
    def add_external_storage(self, collection_id, label, root_path):
        # **한 Collection은 한 종류의 저장소만 쓴다.** Provider는 Collection의
        # root_path 하나로 정해지므로(workspace.provider_for), 다른 종류의 경로를
        # Storage로 붙이면 그 경로를 엉뚱한 Provider가 읽는다. 로컬 Provider에게
        # `mtp://...`를 읽히면 **오류도 없이 빈 목록**이 와서, 사용자에게는 System이
        # 그냥 비어 보인다 - 왜 비었는지 알 길이 없는 것이 가장 나쁘다.
        from storage import mtp

        collection = self.registry.get_collection(collection_id)
        if collection is not None and \
                mtp.is_mtp_path(root_path) != mtp.is_mtp_path(collection.root_path):
            return err("기기(MTP) 저장소와 일반 저장소는 한 Collection에 함께 둘 수 없습니다. "
                       "기기는 별도 Collection으로 열어주세요.")
        storage_id = self._next_storage_id(collection_id)
        self.registry.add_storage(collection_id, storage_id, kind="external",
                                  label=label or "External", root_path=root_path)
        return ok(storage_id)

    @guarded
    def remove_storage(self, collection_id, storage_id):
        self.registry.remove_storage(collection_id, storage_id)
        return ok(True)

    @guarded
    def move_system(self, collection_id, system, storage_id):
        """배치 정보만 바꾼다. 실제 파일 이동은 Plan Apply가 한다(스펙 §10)."""
        collection = self.registry.get_collection(collection_id)
        blocked = self._ensure_writable(collection, [system]) if collection else None
        if blocked:
            return blocked
        self.registry.move_system(collection_id, system, storage_id)
        return ok(True)

    @guarded
    def reassign_system_storage(self, collection_id, system, storage_id):
        """**파일은 그대로 두고** System의 배치만 다른 Storage로 합친다.

        `move_system`/Storage 이동 Plan은 실제로 ROM을 복사한다(스펙 §10) - 드래그로
        Storage를 옮기는 것은 "파일을 그쪽으로 옮겨라"라는 뜻이 맞다. 그런데 External
        Storage를 제거할 때는 얘기가 다르다. 사용자가 원하는 것은 "이 등록을
        지워라"이지 "그 드라이브에 있던 수십 GB를 다시 복사해라"가 아니다(실사용
        피드백 - "실제 롬파일은 유지되는데 표시만 Internal로 합쳐지는 걸로").

        그래서 지금 `layout()`이 계산한 절대 경로를 SystemEntry에 그대로 고정해 두고
        storage_id만 바꾼다. 이미 명시적으로 고정된 경로(entry.rom_path 등)가 있으면
        그것을 그대로 쓴다 - 여기서 다시 계산하면 사용자가 따로 지정해 둔 경로를
        지우게 된다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        entry = next((s for s in collection.systems if s.system == system), None)
        if entry is None:
            return err(f"System을 찾을 수 없습니다: {system}")
        adapter = get_adapter(collection.frontend)
        layout = adapter.layout(collection, system)
        self.registry.move_system(
            collection_id, system, storage_id,
            rom_path=entry.rom_path or layout.rom_dir,
            media_path=entry.media_path or layout.media_dir,
            metadata_path=entry.metadata_path or layout.metadata_file)
        return ok(True)

    def _system_context(self, collection_id):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            raise WorkspaceError("Collection을 찾을 수 없습니다.")
        return (collection, self.workspace.open(collection_id),
                self.workspace.provider_for(collection), get_adapter(collection.frontend))

    @guarded
    def system_removal_preview(self, collection_id, system, force=False):
        """System 삭제 전에 무엇이 지워지고 무엇이 남는지, 지울 수 없는 이유를 알려준다."""
        collection, cache, provider, adapter = self._system_context(collection_id)
        try:
            return ok(system_ops.removal_preview(collection, cache, provider, adapter, system,
                                                 force=bool(force)))
        except system_ops.SystemOpError as e:
            return err(e)

    @guarded
    def remove_system(self, collection_id, system, force=False):
        """System의 파일을 지우고 목록에서 뺀다(app/system_ops.py).

        force=False면 게임이 없는 System만 지운다. force=True는 System 우클릭의 [전체 삭제]다 -
        화면이 경고 + "확인하였습니다" 체크 + 확인으로 두 번 물은 뒤에만 부른다(사용자 결정).
        그 System을 가리키던 Plan 항목도 함께 뺀다 - 남기면 없는 파일을 대상으로 Apply한다."""
        if self.jobs.busy_targets(collection_id):
            return err("작업이 진행 중이라 지금은 System을 삭제할 수 없습니다.")
        collection, cache, provider, adapter = self._system_context(collection_id)
        try:
            result = system_ops.remove_system(self.registry, collection, cache, provider, adapter,
                                              system, force=bool(force))
        except system_ops.SystemOpError as e:
            return err(e)
        plan = self._plans.get(collection_id)
        stale = [e.key for e in plan.entries if e.system == system] if plan else []
        for key in stale:
            plan.remove(key)
        return ok({**result, "planRemoved": len(stale)})

    @guarded
    def open_system_folder(self, collection_id, system, kind):
        """System의 ROM/Metadata/Media 폴더를 파일 탐색기로 연다.

        경로는 Adapter의 layout이 정한다 - Storage 배치와 System별 경로 지정을 그대로 따른다."""
        collection, _cache, provider, adapter = self._system_context(collection_id)
        if not any(entry.system == system for entry in collection.systems):
            return err(f"System을 찾을 수 없습니다: {system}")
        try:
            path = system_ops.folder_path(adapter.layout(collection, system), kind)
        except system_ops.SystemOpError as e:
            return err(e)
        if not path or not provider.exists(path):
            return err(f"폴더가 없습니다: {path}")
        _reveal_path(path)
        return ok({"path": path})

    @guarded
    def open_storage_folder(self, collection_id, storage_id, kind):
        """Storage 그룹의 ROM/Metadata/Media **상위 폴더**를 연다(사용자 결정 - Internal/External를 우클릭하면
        특정 System이 정해지지 않았으니 System 폴더들을 품은 폴더가 열려야 한다).

        경로는 Adapter의 layout이 정한다 - 그 Storage의 System 하나를 골라 그 폴더의 부모를 계산한다."""
        collection, _cache, provider, adapter = self._system_context(collection_id)
        entries = [e for e in collection.systems if e.storage_id == storage_id]
        if not entries:
            return err("이 Storage에 붙은 System이 없습니다.")
        try:
            path = system_ops.storage_parent_folder(adapter.layout(collection, entries[0].system),
                                                    entries[0].system, kind)
        except system_ops.SystemOpError as e:
            return err(e)
        if not path or not provider.exists(path):
            return err(f"폴더가 없습니다: {path}")
        _reveal_path(path)
        return ok({"path": path})

    @guarded
    def open_row_folder(self, collection_id, rom_uid, kind):
        """게임 한 개의 ROM/Metadata/Media를 파일 탐색기에서 **그 파일을 고른 채로** 연다
        (실사용 피드백 §5 - "각 롬별로도 지원"). System 폴더 열기(open_system_folder)는
        폴더까지만 열어서, System 안에 파일이 많으면 다시 찾아야 했다.

        Metadata는 이 게임 하나만의 파일이 아니라 System이 공유하는 gamelist.xml이다 -
        그래도 "이 게임의 데이터가 있는 곳"이므로 그 파일을 고른 채로 연다. Media는
        종류가 여럿일 수 있어(cover/video/...) 있는 것 중 처음 것을 고른다.
        """
        collection, cache, provider, adapter = self._system_context(collection_id)
        blocked = self._ensure_file_ops(collection)
        if blocked:
            return blocked
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        layout = adapter.layout(collection, row["system"])
        if kind == "rom":
            if not row["present"]:
                return err("ROM 파일이 없습니다.")
            path = str(Path(layout.rom_dir) / row["filename"])
        elif kind == "metadata":
            if not layout.metadata_file:
                return err("Metadata 파일이 없습니다.")
            path = layout.metadata_file
        elif kind == "media":
            if not row["media"]:
                return err("Media 파일이 없습니다.")
            path = row["media"][0]["rel_path"]
        else:
            return err(f"알 수 없는 종류입니다: {kind}")
        if not path or not provider.exists(path):
            return err(f"파일이 없습니다: {path}")
        _reveal_path(path, select=True)
        return ok({"path": path})

    @guarded
    def orphan_metadata_preview(self, collection_id, system):
        """이 System에서 Metadata/Media는 있는데 **ROM 파일이 없는** 항목들(System
        우클릭 > ROM 없는 항목 정리). 목록에서 파일명이 흐리게 보이는 것과 같은 기준
        (row.present)이다.
        """
        collection, cache, _provider, _adapter = self._system_context(collection_id)
        if not any(entry.system == system for entry in collection.systems):
            return err(f"System을 찾을 수 없습니다: {system}")
        # Metadata 전용 Collection에서는 ROM이 없는 것이 정상이다 - 여기서 목록을
        # 내주면 멀쩡한 메타데이터 전부가 "정리 대상"으로 보인다.
        blocked = self._ensure_file_ops(collection)
        if blocked:
            return blocked
        rows = cache.query_rows(systems=[system], present=False, order="title")
        return ok({"system": system, "items": [
            {"romUid": r["rom_uid"], "filename": r["filename"], "title": r["title"]} for r in rows]})

    @guarded
    def media_cleanup_preview(self, collection_id, system):
        """System 우클릭 > "System 전체 미디어 정리" 대화상자의 체크박스 - type별
        개수·용량을 보여준다. 실제로 하나도 없는 type은 목록에서 뺀다."""
        collection, cache, _provider, _adapter = self._system_context(collection_id)
        if not any(entry.system == system for entry in collection.systems):
            return err(f"System을 찾을 수 없습니다: {system}")
        counts = media_cleanup.media_type_counts(cache, system)
        return ok({"system": system, "types": [
            {"type": key, "label": MEDIA_LABELS.get(key, key), "count": info["count"], "bytes": info["bytes"]}
            for key, info in sorted(counts.items(), key=lambda kv: -kv[1]["count"]) if info["count"]]})

    @guarded
    def media_cleanup(self, collection_id, system, media_types):
        """선택한 media type의 파일만 지운다(사용자 결정) - ROM·Metadata·다른 타입은
        그대로 둔다. 지운 뒤 그 System을 다시 스캔해 Cache를 실제 디스크 상태로
        맞춘다(app/media_cleanup.py)."""
        if not media_types:
            return err("지울 media 종류를 골라주세요.")
        if self.jobs.busy_targets(collection_id):
            return err("작업이 진행 중이라 지금은 정리할 수 없습니다.")
        collection, cache, provider, _adapter = self._system_context(collection_id)
        if not any(entry.system == system for entry in collection.systems):
            return err(f"System을 찾을 수 없습니다: {system}")
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(collection, [system])
        if blocked:
            return blocked
        result = media_cleanup.cleanup_media(cache, provider, self.workspace, collection_id,
                                             system, media_types)
        return ok(result)

    # ------------------------------------------------------------------
    # Storage 충돌 / External 연결 / 폴더 이름 바꾸기·삭제 (app/storage_layout.py)
    # ------------------------------------------------------------------
    def _conflicts(self, collection):
        return storage_layout.conflicts(collection, self.workspace.provider_for(collection),
                                        get_adapter(collection.frontend))

    def _ensure_writable(self, collection, systems):
        """같은 System 폴더가 여러 Storage에 있으면 그 System에는 쓰지 않는다(사용자 결정).
        막히면 화면에 그대로 보여줄 err를, 괜찮으면 None을 돌려준다."""
        wanted = {str(s).lower() for s in systems if s}
        if not wanted:
            return None
        clash = self._conflicts(collection)
        hit = sorted(s for s in wanted if s in clash)
        if not hit:
            return None
        return err(f"{', '.join(h.upper() for h in hit)} System 폴더가 여러 Storage에 함께 있어 쓰기가 막혀 "
                   "있습니다. System 우클릭에서 한쪽 폴더를 지우거나 이름을 바꾸면 풀립니다.")

    @staticmethod
    def _ensure_file_ops(collection):
        """파일을 옮기고 지우는 작업을 할 수 있는 Collection인가.

        MTP로 연결한 기기는 Metadata 전용이다(사용자 결정) - 대량 전송은 MTP로
        감당할 수 없어서 ADB 모드를 따로 두기로 했다. 막히면 화면에 그대로 보여줄
        err를, 괜찮으면 None을 돌려준다.
        """
        if collection is not None and collection.is_device:
            return err("기기 Collection은 Metadata만 다룹니다. 파일 복사·이동·삭제는 "
                       "ADB 모드에서 지원할 예정입니다.")
        return None

    def _drop_plan_entries(self, collection_id, system):
        plan = self._plans.get(collection_id)
        if plan:
            for key in [e.key for e in plan.entries if e.system.lower() == str(system).lower()]:
                plan.remove(key)

    @guarded
    def update_storage(self, collection_id, storage_id, label=None, root_path=None, device_id=None,
                       device_root=None):
        """Storage 설정 - 이름, PC 경로(External만), 안드로이드 Storage ID와 기기 경로."""
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        storage_entry = collection.storage(storage_id)
        if storage_entry is None:
            return err("Storage를 찾을 수 없습니다.")
        fields = {}
        if label is not None:
            fields["label"] = str(label).strip() or storage_entry.label
        if root_path is not None and storage_entry.is_external and str(root_path).strip():
            fields["root_path"] = str(root_path).strip()
        if device_id is not None:
            value = str(device_id).strip()
            if value and not re.match(r"^[A-Za-z0-9\-]+$", value):
                return err("Storage ID는 영문·숫자와 - 만 쓸 수 있습니다(예: 1234-ABCD).")
            fields["device_id"] = value or None
        if device_root is not None:
            value = str(device_root).strip().rstrip("/")
            if value and not value.startswith("/"):
                return err("기기 경로는 /로 시작해야 합니다(예: /storage/1234-ABCD/ROMs).")
            fields["device_root"] = value or None
        self.registry.update_storage(collection_id, storage_id, **fields)
        return ok(True)

    @guarded
    def attach_storage_systems(self, collection_id, storage_id):
        """External Storage root 밑의 System 폴더를 Collection에 붙인다. 파일은 건드리지 않는다."""
        collection, _cache, provider, adapter = self._system_context(collection_id)
        try:
            return ok(storage_layout.attach_storage(self.registry, collection, provider, adapter, storage_id))
        except storage_layout.StorageLayoutError as e:
            return err(e)

    #: System 이름에 쓸 수 없는 것 - 폴더 이름이 곧 System 이름이라 경로 구분자와 예약어는 안 된다.
    _SYSTEM_NAME_BAD = re.compile(r'[\\/:*?"<>|]')

    @guarded
    def create_system(self, collection_id, name, storage_id="internal"):
        """빈 System을 만든다(사용자 결정 - "system 추가를 누르고 이름을 입력하면 빈 디렉토리로 추가").

        ROM 폴더만 만든다. gamelist와 media 폴더는 게임이 생길 때 Frontend 규칙대로 만들어진다.
        ROM 폴더를 메타데이터 폴더와 따로 쓰는 Collection이면 **형제 System과 같은 ROM 폴더 밑**에 만든다.

        ES-DE는 System 이름을 폴더 이름으로 알아본다 - ES-DE 기본 목록에 없는 이름이면 만들기는 하되
        `knownToEsde=False`로 알려, 화면이 custom_systems XML이 필요하다고 말할 수 있게 한다.
        """
        if self.jobs.busy_targets(collection_id):
            return err("작업이 진행 중이라 지금은 System을 만들 수 없습니다.")
        collection, _cache, provider, adapter = self._system_context(collection_id)
        blocked = self._ensure_file_ops(collection)
        if blocked:
            return blocked
        name = str(name or "").strip()
        if not name or name in (".", "..") or name.startswith(".") or self._SYSTEM_NAME_BAD.search(name):
            return err("System 이름이 올바르지 않습니다. 폴더 이름으로 쓸 수 있는 글자만 쓰세요.")
        if any(e.system.lower() == name.lower() for e in collection.systems):
            return err(f"이미 있는 System입니다: {name}")
        if collection.storage(storage_id) is None:
            return err("Storage를 찾을 수 없습니다.")
        siblings = [e for e in collection.systems if e.storage_id == storage_id and e.rom_path]
        rom_path = str(Path(siblings[0].rom_path).parent / name) if siblings else None
        self.registry.upsert_system(collection_id, name, storage_id, rom_path=rom_path)
        collection = self.registry.get_collection(collection_id)
        layout = adapter.layout(collection, name)
        try:
            if layout.rom_dir:
                Path(layout.rom_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.registry.remove_system(collection_id, name)
            return err(f"폴더를 만들 수 없습니다: {e}")
        known = True
        template_of = getattr(adapter, "_template_systems", None)
        if template_of is not None:
            known = name.lower() in template_of(adapter.esde_platform(collection))
        return ok({"system": name, "romDir": layout.rom_dir, "knownToEsde": known})

    @guarded
    def rename_system_folder(self, collection_id, system, storage_id, new_name):
        """한 Storage 쪽 System 폴더의 이름을 바꾼다(충돌 해결). 바꾼 뒤 그 System을 다시 스캔한다."""
        if self.jobs.busy_targets(collection_id):
            return err("작업이 진행 중이라 지금은 이름을 바꿀 수 없습니다.")
        collection, cache, provider, adapter = self._system_context(collection_id)
        try:
            result = storage_layout.rename_folder(self.registry, collection, provider, adapter, cache,
                                                  system, storage_id, new_name)
        except (storage_layout.StorageLayoutError, OSError) as e:
            return err(e)
        if result["registered"]:
            self._drop_plan_entries(collection_id, system)
        self.workspace.scan(collection_id, force=True, systems=[result["to"]])
        return ok(result)

    @guarded
    def system_folder_preview(self, collection_id, system, storage_id):
        collection, _cache, provider, adapter = self._system_context(collection_id)
        try:
            return ok(storage_layout.folder_preview(collection, provider, adapter, system, storage_id))
        except storage_layout.StorageLayoutError as e:
            return err(e)

    @guarded
    def remove_system_folder(self, collection_id, system, storage_id):
        """한 Storage 쪽의 ROM 폴더만 지운다(충돌 해결). gamelist/media는 남긴다."""
        if self.jobs.busy_targets(collection_id):
            return err("작업이 진행 중이라 지금은 지울 수 없습니다.")
        collection, cache, provider, adapter = self._system_context(collection_id)
        try:
            result = storage_layout.remove_folder(self.registry, collection, provider, adapter, cache,
                                                  system, storage_id)
        except (storage_layout.StorageLayoutError, OSError) as e:
            return err(e)
        self._drop_plan_entries(collection_id, system)
        self.workspace.scan(collection_id, force=True, systems=[system])
        return ok(result)

    def _next_storage_id(self, collection_id):
        existing = {s.storage_id for s in self.registry.get_collection(collection_id).storages}
        index = 1
        while f"ext-{index}" in existing:
            index += 1
        return f"ext-{index}"

    # ------------------------------------------------------------------
    # Gamelist
    # ------------------------------------------------------------------
    @guarded
    def list_rows(self, collection_id, systems=None, storage_ids=None, search=None,
                  order="title", descending=False, limit=200, offset=0,
                  favorites_only=False, priority=None):
        """가상 스크롤이 요청한 구간만 돌려준다. 정렬/필터/검색은 전부 SQL이 처리한다."""
        cache = self.workspace.open(collection_id)
        query = {"systems": systems or None, "storage_ids": storage_ids or None,
                 "search": search or None, "favorites_only": bool(favorites_only)}
        rows = cache.query_rows(**query, order=order, descending=bool(descending),
                                limit=int(limit), offset=int(offset), priority=priority or None)
        return ok({"rows": [self._row_summary(r) for r in rows],
                   "total": cache.count_rows(**query), "offset": int(offset)})

    @guarded
    def list_uids(self, collection_id, systems=None, storage_ids=None, search=None,
                  order="title", descending=False, favorites_only=False, priority=None):
        """지금 목록 전체의 rom_uid(필터·정렬 그대로). Ctrl+A가 쓴다."""
        cache = self.workspace.open(collection_id)
        return ok(cache.query_uids(systems=systems or None, storage_ids=storage_ids or None,
                                   search=search or None, order=order,
                                   descending=bool(descending), favorites_only=bool(favorites_only),
                                   priority=priority or None))

    @guarded
    def find_row_index(self, collection_id, prefix, after=-1, systems=None, storage_ids=None,
                       search=None, order="title", descending=False, favorites_only=False,
                       priority=None):
        """영문키 점프: `after` 다음 줄부터 파일명이 `prefix`로 시작하는 줄의 위치(없으면 -1).

        가상 스크롤이라 화면에 그려진 행만 뒤지면 목록 뒤쪽으로 갈 수 없다 - 그래서
        목록 전체를 같은 정렬로 백엔드가 찾는다."""
        cache = self.workspace.open(collection_id)
        return ok(cache.index_of_prefix(prefix, int(after), systems=systems or None,
                                        storage_ids=storage_ids or None, search=search or None,
                                        order=order, descending=bool(descending),
                                        favorites_only=bool(favorites_only), priority=priority or None))

    @staticmethod
    def _meta_level(row) -> str:
        """Title과 Description이 다 있으면 ok, 하나만 있으면 partial, 둘 다 없으면 none."""
        if "name_text" not in row.keys():
            return "ok" if row["has_metadata"] else "none"
        has_title = bool((row["name_text"] or "").strip())
        has_desc = bool((row["desc_text"] or "").strip()) if "desc_text" in row.keys() else False
        if has_title and has_desc:
            return "ok"
        return "partial" if (has_title or has_desc) else "none"

    @staticmethod
    def _media_level(row) -> str:
        """주요 media(cover/screenshot/marquee/miximage) 넷이 다 있으면 ok. 다른 것만 있거나
        일부만 있으면 partial, 아무것도 없으면 none."""
        if "any_media_count" not in row.keys():
            return "ok" if row["has_media"] else "none"
        if row["key_media_count"] >= len(KEY_MEDIA_TYPES):
            return "ok"
        return "partial" if row["any_media_count"] else "none"

    @staticmethod
    def _row_summary(row):
        """Gamelist 한 행. 이전 프로젝트의 컬럼을 그리는 데 필요한 것을 전부 싣는다.

            No. │ File │ Title │ Description │ Region │ Rating │ ★ │ Genre │ Status

        Description이 여기 있는 것이 중요하다 - 이전 프로젝트의 목록은 제목이 아니라
        설명 위주였고, 그래야 어떤 게임인지 목록에서 바로 판단할 수 있다.
        """
        desc = row["desc_text"] if "desc_text" in row.keys() else ""
        return {
            "romUid": row["rom_uid"], "system": row["system"], "file": row["filename"],
            "title": row["title"], "size": row["size"], "storageId": row["storage_id"],
            "hasMetadata": bool(row["has_metadata"]), "hasMedia": bool(row["has_media"]),
            "present": bool(row["present"]),
            "desc": desc,
            # Gamelist Status 아이콘(실사용 피드백) - ROM/Media/Description/Cover
            # 네 가지를 독립적으로 표시하려면 hasMedia(무엇이든 하나) 말고 Cover
            # 하나만 따로, Description은 desc 필드 유무로 판정해야 한다.
            "hasDescription": bool(desc and desc.strip()),
            "hasCover": bool(row["has_cover"]) if "has_cover" in row.keys() else bool(row["has_media"]),
            # Status 네 칸의 상태(사용자 결정): "ok"(다 있음) / "partial"(일부만) / "none"(없음).
            # 없는 것을 빨갛게 하지 않고 회색으로, 일부만 있으면 노랗게 알린다.
            "rom": "ok" if row["present"] else "none",
            "metaLevel": Api._meta_level(row),
            "mediaLevel": Api._media_level(row),
            "videoLevel": "ok" if ("has_video" in row.keys() and row["has_video"]) else "none",
            "region": row["region"] if "region" in row.keys() else "",
            "genre": row["genre"] if "genre" in row.keys() else "",
            "rating": row["rating"] if "rating" in row.keys() else "",
            "favorite": bool(row["favorite"]) if "favorite" in row.keys() else False,
        }

    @guarded
    def get_row(self, collection_id, rom_uid):
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        media = {}
        for item in row["media"]:
            label = MEDIA_LABELS.get(item["media_type"], item["media_type"])
            # 실제 이미지는 화면에 보일 때 낱개로 가져온다. 여기서 전부 base64로
            # 실어 보내면 media가 많은 항목에서 브릿지가 과부하된다.
            media[label] = "video://exists" if item["media_type"] == "videos" else "pending"
        return ok({
            "romUid": row["rom_uid"], "system": row["system"], "file": row["filename"],
            "fields": row["fields"], "media": media, "size": row["size"],
            "present": bool(row["present"]), "sha256": row["sha256"],
            # 상세 패널의 별표도 목록과 같은 곳을 가리켜야 한다.
            "favorite": bool(row.get("favorite")),
        })

    @guarded
    def get_media_image(self, collection_id, rom_uid, media_label, thumbnail=False):
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        media_type = MEDIA_KEYS.get(media_label, str(media_label).lower())
        item = next((m for m in row["media"] if m["media_type"] == media_type), None)
        if item is None:
            return ok(None)
        return ok(self._encode_image(item["rel_path"], THUMBNAIL_MAX if thumbnail else None))

    @guarded
    def get_media_video_url(self, collection_id, rom_uid):
        """이 게임의 영상을 재생할 URL(로컬 전용 서버). 영상이 없거나 재생할 수 없는 형식이면 None.

        이미지처럼 base64로 실어 보내지 않는다 - 영상은 수~수십 MB라 브릿지가 감당하지 못한다."""
        row = self.workspace.open(collection_id).get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        item = next((m for m in row["media"] if m["media_type"] == VIDEO_MEDIA_TYPE), None)
        url = self._media_server.url_for(item["rel_path"]) if item else None
        return ok({"url": url} if url else None)

    def _encode_image(self, path, max_size=None):
        # 썸네일은 카드 하나마다 한 번씩 불린다. 목록을 오갈 때마다 같은 파일을 다시
        # 열어 축소하고 base64로 만드는 것은 순전히 낭비다 - 파일이 그대로면 결과도
        # 그대로이므로 (경로, 크기, 수정시각, 목표 크기)를 열쇠로 캐시한다.
        if max_size:
            cached = self._thumbnail_cache_get(path, max_size)
            if cached is not _MISS:
                return cached
        payload = self._encode_image_uncached(path, max_size)
        if max_size:
            self._thumbnail_cache_put(path, max_size, payload)
        return payload

    def _thumbnail_key(self, path, max_size):
        try:
            stat = storage.for_path(path).stat(path)
        except Exception:
            return None
        if stat is None:
            return None
        return (str(path), stat.size, stat.mtime_ns, max_size)

    def _thumbnail_cache_get(self, path, max_size):
        key = self._thumbnail_key(path, max_size)
        if key is None or key not in self._thumb_cache:
            return _MISS
        self._thumb_cache.move_to_end(key)
        return self._thumb_cache[key]

    def _thumbnail_cache_put(self, path, max_size, payload):
        key = self._thumbnail_key(path, max_size)
        if key is None:
            return
        self._thumb_cache[key] = payload
        self._thumb_cache.move_to_end(key)
        while len(self._thumb_cache) > THUMBNAIL_CACHE_MAX:
            self._thumb_cache.popitem(last=False)

    @staticmethod
    def _encode_image_uncached(path, max_size=None):
        """이미지 한 장을 data URL로 만든다.

        **바이트는 Provider를 통해서만 읽는다.** 로컬에서는 결과가 같지만, MTP
        기기 Collection에서는 `Path.read_bytes()`가 아예 동작하지 않는다 - 커버를
        "선택한 항목부터" 한 장씩 읽어 오는 것이 기기에서 그림이 보이는 유일한
        길이다(사용자 결정).
        """
        suffix = Path(path).suffix.lower()
        if suffix in (".mp4", ".avi"):
            return None
        try:
            data = storage.for_path(path).read_bytes(path)
            if data is None:
                return None
            if max_size:
                from PIL import Image
                import io
                with Image.open(io.BytesIO(data)) as image:
                    image.thumbnail((max_size, max_size))
                    buffer = io.BytesIO()
                    # WebP는 같은 화질에서 JPEG보다 작다. 브릿지로 넘어가는 base64
                    # 문자열이 그만큼 짧아지므로 카드가 많을수록 차이가 커진다.
                    image.convert("RGBA").save(buffer, format="WEBP", quality=82, method=4)
                    payload, mime = buffer.getvalue(), "image/webp"
            else:
                payload = data
                mime = {"png": "image/png", "webp": "image/webp"}.get(suffix.lstrip("."), "image/jpeg")
        except Exception:
            # 깨진 이미지 하나가 상세 패널 전체를 막으면 안 된다.
            log.warning("Could not decode media image path=%s thumbnail=%s", path, max_size, exc_info=True)
            return None
        return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"

    # ------------------------------------------------------------------
    # 편집 (결정 D1 - 저장 즉시 파일에 기록, Plan 미경유)
    # ------------------------------------------------------------------
    @guarded
    def save_fields(self, collection_id, rom_uid, fields, frontend_raw=None):
        """메타데이터를 그 자리에서 Collection 파일에 쓴다.

        Plan을 거치지 않는다(D1) - Plan은 저장 용량이 변하는 작업만 담는다. 대신
        Adapter에 이 항목 하나만 넘기므로 gamelist.xml의 다른 항목과 우리가
        해석하지 않는 요소는 그대로 남는다.

        기기(MTP)도 독립 작업으로 즉시 저장한다. 쓰기 실패는 성공으로 표시하지 않는다.
        """
        from adapters.base import GameEntry

        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        busy = self.jobs.busy_targets(collection_id)
        if busy and self.jobs.busy_kind(collection_id) != "scan":
            return err("작업이 진행 중이라 지금은 편집할 수 없습니다. 완료 후 다시 시도해주세요.")

        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        blocked = self._ensure_writable(collection, [row["system"]])
        if blocked:
            return blocked

        merged = {**row["fields"], **{k: v for k, v in (fields or {}).items()}}
        if collection.is_device:
            operation = Plan(collection_id)
            entry = builder.plan_metadata_edit(operation, cache, int(rom_uid),
                                               fields or {}, frontend_raw=frontend_raw)
            outcome = apply_plan(operation, collection, cache, self.registry,
                                 self.workspace.provider_for(collection))
            if outcome.get("failed") or outcome.get("partial"):
                return err("메타데이터 저장 실패: " + "; ".join(outcome.get("errors") or []))
            title = (entry.payload.get("name") or "").strip() or Path(row["filename"]).stem
            return ok({"title": title})

        # frontend_raw는 보통 읽은 그대로 다시 쓴다. 즐겨찾기처럼 사용자가 직접 바꾸는
        # Frontend 고유 값일 때만 새 것이 들어온다.
        raw = row["frontend_raw"] if frontend_raw is None else frontend_raw
        adapter = get_adapter(collection.frontend)
        layout = adapter.layout(collection, row["system"])
        undo_id = None
        if layout.metadata_file and supports_local_undo([layout.metadata_file]):
            edit_plan = Plan(collection_id)
            edit_plan.add(PlanEntry(op=OP_METADATA_EDIT, system=row["system"],
                                   filename=row["filename"], rom_uid=int(rom_uid),
                                   payload=merged))
            undo_id = uuid.uuid4().hex
            self._paste_journal.begin(undo_id, collection_id, collection, edit_plan)
        try:
            adapter.write_index(layout, [GameEntry(filename=row["filename"], fields=merged,
                                                   frontend_raw=raw)])
            if undo_id:
                self._paste_journal.commit(undo_id)
        except Exception:
            if undo_id:
                self._paste_journal.rollback_running(undo_id)
            raise

        title = (merged.get("name") or "").strip() or Path(row["filename"]).stem
        cache.update_metadata(int(rom_uid), merged, title=title, title_norm=normalize_title(title),
                              frontend_raw=None if frontend_raw is None else raw)
        return ok({"title": title, "undoOperationId": undo_id})

    # ------------------------------------------------------------------
    # Plan (세션 한정 - 결정 D2)
    # ------------------------------------------------------------------
    def _plan(self, collection_id) -> Plan:
        plan = self._plans.get(collection_id)
        if plan is None:
            plan = self._plans[collection_id] = Plan(collection_id)
        return plan

    def _plan_context(self, collection_id):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            raise WorkspaceError("Collection을 찾을 수 없습니다.")
        return collection, self.workspace.open(collection_id), self.workspace.provider_for(collection)

    @guarded
    def operation_state(self, collection_id):
        if collection_id == "__archive__":
            cfg = self._archive_config()
            pending = self._archive_journal.pending(cfg)
            return ok({"undoOperationId": pending[-1]["id"] if pending else self._archive_journal.latest(cfg),
                       "redoOperationId": self._archive_journal.latest_redo(cfg), "recoveryError": self._archive_recovery_error,
                       "retention": self._backup_retention_report.get(collection_id),
                       "clipboard": clipboard.peek(self.registry)})
        self._plan_context(collection_id)
        local_id = self._paste_journal.latest_committed(collection_id)
        local_time = self._paste_journal.details(local_id)["createdAt"] if local_id else 0
        moves = [row for row in self._archive_journal.records(self._archive_config())
                 if collection_id in row.get("relatedCollections", {}) and row["status"] == "committed"]
        archive_id = moves[-1]["id"] if moves and moves[-1]["createdAt"] > local_time else None
        redos = [row for row in self._archive_journal.records(self._archive_config())
                 if collection_id in row.get("relatedCollections", {}) and row["status"] == "undone" and row.get("redoReady")]
        local_redo = self._paste_journal.latest_redo(collection_id)
        local_redo_time = self._paste_journal.details(local_redo).get("undoneAt", 0) if local_redo else 0
        latest_archive_redo = max(redos, key=lambda row: row.get("undoneAt", 0)) if redos else None
        archive_redo = latest_archive_redo["id"] if latest_archive_redo and latest_archive_redo.get("undoneAt", 0) > local_redo_time else None
        return ok({"undoOperationId": archive_id or local_id,
                   "redoOperationId": archive_redo or local_redo,
                   "retention": self._backup_retention_report.get(collection_id),
                   "recoveryError": "파일 작업이 진행 중이거나 복구가 필요합니다. Settings > Advanced > 파일 작업 복구를 확인하세요." if self._paste_journal.pending(collection_id) else None,
                   "clipboard": clipboard.peek(self.registry)})

    @guarded
    def plan_state(self, collection_id):
        """Gamelist의 Status 기호와 하단 바가 필요로 하는 것."""
        plan = self._plan(collection_id)
        collection, cache, provider = self._plan_context(collection_id)
        return ok({
            **plan.summary(),
            "undoOperationId": self._paste_journal.latest_committed(collection_id),
            "marks": plan.marks(),
            "capacity": check_capacity(plan, collection, cache, provider),
            "clipboard": clipboard.peek(self.registry),
            # 사용자가 결정해야 하는 것과 지난 Apply에서 실패한 것을 명확히 노출한다.
            # 이게 안 보이면 "Apply 했으니 끝났다"고 오해한다.
            "conflictEntries": [self._entry_summary(e) for e in plan.conflict_entries()],
            "failedEntries": [self._entry_summary(e) for e in plan.failed_entries()],
            "entries": [self._entry_summary(e) for e in plan.entries],
            # Navigator가 드래그로 옮긴 System을 Apply 전에도 목표 Storage 밑에
            # 미리 보여주려면 어디로 갈 예정인지 알아야 한다(실사용 피드백 - 예전엔
            # Apply할 때까지 원래 자리에 그대로 있어서 "드래그가 안 먹혔다"처럼 보였다).
            "pendingMoves": {e.system: e.storage_to for e in plan.entries if e.op == OP_STORAGE_CHANGE},
        })

    @staticmethod
    def _entry_summary(entry):
        summary = {
            "key": entry.key, "op": entry.op, "system": entry.system,
            "filename": entry.filename or entry.system,
            "status": entry.status, "error": entry.error,
            "resolution": entry.resolution,
            "conflictChoices": entry.conflict_choices,
            "conflicts": entry.conflicts,
            "origin": (entry.source or {}).get("origin"),
            "sourceName": (entry.source or {}).get("sourceName"),
            "parts": ({
                "rom": bool((entry.source or {}).get("romPresent")),
                "metadata": bool((entry.source or {}).get("metadataPresent")),
                "media": int((entry.source or {}).get("mediaCount") or 0),
            } if entry.op == OP_ARCHIVE_INGEST else {
                "rom": bool((entry.source or {}).get("rom")),
                "metadata": bool((entry.source or {}).get("fields")),
                "media": len((entry.source or {}).get("media") or []),
            }) if entry.op in (OP_ADD, OP_ARCHIVE_INGEST) else None,
        }
        if entry.op == OP_TITLE_EDIT:
            summary["oldTitle"], summary["newTitle"] = entry.old_title, entry.new_title
        return summary

    @guarded
    def plan_conflict_preview(self, collection_id, key, index=0):
        """충돌 창의 미디어 미리보기 - 지금 대상에 있는 그림과 새로 들어올 그림을 나란히 보여 준다.

        경로를 인자로 받지 않는다. **Plan이 이미 들고 있는 그 충돌의 source/dest만** 읽는다 - 임의의 파일을
        읽는 통로가 되지 않게 하기 위해서다. ROM 충돌이나 영상은 그림이 없으므로 None이다.
        """
        plan = self._plan(collection_id)
        entry = plan.get(key)
        conflicts = (entry.conflicts if entry is not None else None) or []
        if entry is None or not 0 <= int(index) < len(conflicts):
            return err("충돌을 찾을 수 없습니다.")
        conflict = conflicts[int(index)]
        if conflict.get("kind") != "media":
            return ok(None)
        return ok({
            "existing": self._encode_image(conflict["dest"], THUMBNAIL_MAX),
            "incoming": self._encode_image(conflict["source"], THUMBNAIL_MAX),
        })

    @guarded
    def plan_resolve_conflict(self, collection_id, key, resolution):
        """충돌 항목을 어떻게 처리할지 정한다: skip(그대로 둠) 또는 overwrite(덮어씀).

        덮어쓰기를 고르면 용량 계산이 "새 파일 크기 전부"가 아니라 기존 파일과의
        차이로 다시 계산된다.
        """
        collection, _, provider = self._plan_context(collection_id)
        plan = self._plan(collection_id)
        result = builder.resolve_conflict(plan, collection, provider, key, resolution)
        entry = plan.get(key)
        log.info("Plan conflict choices collection=%s item=%s files=%s", collection_id, key,
                 [{"type": c.get("mediaType") or c.get("kind"), "source": c.get("source"),
                   "dest": c.get("dest"),
                   "choice": entry.conflict_choices.get(str(c.get("dest")))
                   if entry.resolution == "custom" else entry.resolution}
                  for c in (entry.conflicts or [])])
        return ok(result)

    @guarded
    def plan_resolve_all_conflicts(self, collection_id, resolution):
        """충돌 전체를 같은 방식으로 처리한다.

        수백 개를 하나씩 누르게 하면 도구로 쓸 수 없다. 다만 기본값을 자동으로
        적용하지는 않는다 - 사용자가 명시적으로 고른 경우에만 여기로 온다.
        """
        collection, _, provider = self._plan_context(collection_id)
        plan = self._plan(collection_id)
        keys = [e.key for e in plan.conflict_entries()]
        for key in keys:
            builder.resolve_conflict(plan, collection, provider, key, resolution)
        return ok({"resolved": len(keys), "resolution": resolution})

    @guarded
    def delete_immediate(self, collection_id, rom_uids, parts=None, permanent=False):
        """Move local assets to recoverable sidecar files, then update the index."""
        collection, cache, provider = self._plan_context(collection_id)
        rows = [cache.get_row(int(uid)) for uid in (rom_uids or [])]
        rows = [row for row in rows if row is not None]
        if not rows:
            return err("삭제할 게임을 찾을 수 없습니다.")
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(
            collection, sorted({row["system"] for row in rows}))
        if blocked:
            return blocked
        adapter = get_adapter(collection.frontend)
        layouts = [adapter.layout(collection, system) for system in {row["system"] for row in rows}]
        undoable = supports_local_undo(
                path for layout in layouts
                for path in (layout.rom_dir, layout.metadata_file, layout.media_dir))
        if not permanent and not undoable:
            return ok({"requiresConfirmation": True, "undoable": False})
        plan = Plan(collection_id)
        builder.plan_delete(plan, collection, cache,
                            [row["rom_uid"] for row in rows], provider, parts=parts)
        report = validate(plan, collection, cache, provider)
        if report["blocked"] or report["entries"]:
            return err("대상 파일이 바뀌었습니다. 다시 선택한 뒤 삭제하세요.")
        paths = [path for entry in plan.entries
                 for path in delete_destinations(entry, collection, cache, adapter)]
        operation_id = uuid.uuid4().hex
        lock_name = f"apply:{collection_id}"
        if not self.registry.acquire_lock(lock_name, kind="delete"):
            return err("다른 창에서 같은 Collection을 수정하는 중입니다.")

        def run(progress):
            journal_started = False
            try:
                suffix = None
                if not permanent:
                    suffix = self._paste_journal.begin(
                        operation_id, collection_id, collection, plan, extra_paths=paths)
                    journal_started = True
                result = apply_plan(plan, collection, cache, self.registry, provider,
                                    progress_cb=progress, trash_suffix=suffix)
                if journal_started and (result.get("failed") or result.get("partial")
                                        or result.get("invalid")):
                    self._paste_journal.rollback_running(operation_id)
                    result["rolledBack"], result["applied"] = True, 0
                elif journal_started:
                    self._paste_journal.commit(operation_id)
                    result["undoOperationId"] = operation_id
                if result.get("systems"):
                    self.workspace.scan(collection_id, force=True, systems=result["systems"])
                return result
            except Exception:
                if journal_started:
                    self._paste_journal.rollback_running(operation_id)
                raise
            finally:
                self.registry.release_lock(lock_name)

        try:
            job_id = self.jobs.run_heavy(run, mutates_state=True,
                                         target_ids=(collection_id,), kind="apply")
        except Exception:
            self.registry.release_lock(lock_name)
            raise
        return ok({"jobId": job_id})

    @guarded
    def rename_game(self, collection_id, rom_uid, new_name):
        """Rename local ROM and its own media with one recoverable transaction."""
        if collection_id == "__archive__":
            def rename_archive(progress):
                result = self.archive_rename(str(rom_uid), new_name)
                if not result["ok"]:
                    raise ValueError(result["error"])
                return result["data"]
            return ok({"jobId": self.jobs.run_heavy(rename_archive, mutates_state=True,
                        target_ids=("archive",), kind="archive-rename")})
        from adapters.base import GameEntry
        collection, cache, provider = self._plan_context(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("게임을 찾을 수 없습니다.")
        name = str(new_name or "").strip()
        if (not name or name in (".", "..") or name[-1:] in (".", " ")
                or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)
                or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1,10)], *[f"LPT{i}" for i in range(1,10)]}):
            return err("Windows에서 사용할 수 없는 파일명입니다.")
        if Path(name).suffix.lower() != Path(row["filename"]).suffix.lower():
            return err("ROM 확장자는 유지해주세요.")
        if name.lower() == row["filename"].lower():
            return err("기존 이름과 같은 파일명입니다.")
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(collection, [row["system"]])
        if blocked:
            return blocked
        adapter = get_adapter(collection.frontend)
        layout = adapter.layout(collection, row["system"])
        if not supports_local_undo([layout.rom_dir, layout.media_dir, layout.metadata_file]):
            return err("이름 변경은 현재 로컬 Collection에서 지원합니다.")
        if cache.get_row_by_filename(row["system"], name):
            return err("같은 파일명의 게임이 이미 있습니다.")
        pairs = []
        old_rom = Path(layout.rom_dir) / row["filename"]
        if row["present"]:
            pairs.append((old_rom, old_rom.with_name(name)))
        old_stem, new_stem = Path(row["filename"]).stem, Path(name).stem
        links = []
        for media in row.get("media") or []:
            source = Path(media["rel_path"])
            # Linked/shared media keep their paths. Only this game's named files move.
            if (source.stem == old_stem and source.is_file()
                    and layout.media_dir and _path_within(source, layout.media_dir)
                    and not cache.db.execute("SELECT 1 FROM media WHERE rel_path=? AND rom_uid<>? LIMIT 1",
                                             (str(source), int(rom_uid))).fetchone()):
                destination = source.with_name(new_stem + source.suffix)
                pairs.append((source, destination))
                links.append((media["media_type"], str(destination)))
            else:
                links.append((media["media_type"], str(source)))
        pairs = list(dict.fromkeys(pairs))
        if any(destination.exists() for _, destination in pairs):
            return err("변경할 이름의 파일이 이미 있습니다.")
        operation_id = uuid.uuid4().hex
        lock_name = f"apply:{collection_id}"
        if not self.registry.acquire_lock(lock_name, kind="rename"):
            return err("다른 창에서 같은 Collection을 수정하는 중입니다.")
        plan = Plan(collection_id)
        builder.plan_metadata_edit(plan, cache, int(rom_uid), {})
        def run(progress):
            begun = False
            try:
                self._paste_journal.begin(operation_id, collection_id, collection, plan,
                    extra_paths=[path for pair in pairs for path in pair])
                begun = True
                self._paste_journal.record_renames(operation_id, pairs)
                for source, destination in pairs:
                    if destination.exists():
                        raise ValueError("대상 파일이 새로 생겼습니다.")
                    os.rename(source, destination)
                adapter.remove_entries(layout, [row["filename"]])
                raw = adapter.strip_location_raw(row["frontend_raw"])
                adapter.write_index(layout, [GameEntry(filename=name, fields=row["fields"], frontend_raw=raw)])
                if links:
                    adapter.write_media_links(layout, {name: links})
                self._paste_journal.commit(operation_id)
                self.workspace.scan(collection_id, force=True, systems=[row["system"]])
                progress(1, 1, "이름 변경 완료")
                return {"applied": 1, "filename": name, "undoOperationId": operation_id}
            except Exception:
                if begun:
                    self._paste_journal.rollback_running(operation_id)
                    self.workspace.scan(collection_id, force=True, systems=[row["system"]])
                raise
            finally:
                self.registry.release_lock(lock_name)
        try:
            job_id = self.jobs.run_heavy(run, mutates_state=True, target_ids=(collection_id,), kind="apply")
        except Exception:
            self.registry.release_lock(lock_name)
            raise
        return ok({"jobId": job_id})

    @guarded
    def plan_delete(self, collection_id, rom_uids, parts=None):
        """삭제 예정으로 올린다. `parts`(rom/metadata/media/video의 목록)로 무엇을 지울지 고른다.
        정하지 않으면 전부다."""
        if parts is not None and not isinstance(parts, (list, tuple)):
            return err("삭제 대상 형식이 올바르지 않습니다.")
        collection, cache, provider = self._plan_context(collection_id)
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(
            collection, [(cache.get_row(int(uid)) or {}).get("system")
                         for uid in rom_uids or []])
        if blocked:
            return blocked
        try:
            result = builder.plan_delete(self._plan(collection_id), collection, cache, rom_uids,
                                         provider, parts)
        except builder.PlanBuildError as e:
            return err(str(e))
        return ok(result)

    #: System 이름이 고정 목록인 Frontend - 폴더를 옮기면 Frontend가 그 System을 못 읽는다.
    #: 사용자 결정: "System 간 파일 이동은 non-esde only".
    _FIXED_SYSTEM_FRONTENDS = {"es-de", "emulationstation"}

    @guarded
    def plan_move_to_system(self, collection_id, rom_uids, target_system, _operation=None):
        """고른 게임을 **다른 System으로 옮긴다**(ROM+메타데이터+미디어).

        사용자 결정 - "FBNEO ACT는 FBNEO 중 action 장르를 모은 디렉토리인데, FBNEO로 모으고 싶을 때
        옮기는 기능이 필요하다". Pegasus처럼 metadata가 ROM 폴더에 딸린 Frontend가 대상이고,
        ES-DE 계열은 System 이름이 정해진 목록이라 받지 않는다.

        "옮기기"는 **대상에 추가 + 원본 삭제**로 Plan에 올린다 - 둘 다 이미 검증·충돌·적용 경로를
        갖고 있어서 옮기기만을 위한 길을 새로 낼 이유가 없다. Apply가 추가를 먼저 하고 삭제를
        나중에 하므로(app/plan/applier.py) 순서도 맞다.
        """
        collection, cache, provider = self._plan_context(collection_id)
        if collection.frontend in self._FIXED_SYSTEM_FRONTENDS:
            return err(f"{collection.frontend}는 System 이름이 정해져 있어 게임을 다른 System으로 "
                       "옮길 수 없습니다. 폴더를 옮기면 Frontend가 그 System을 읽지 못합니다.")
        target = str(target_system or "").strip()
        if not target:
            return err("옮길 System을 고르세요.")
        if not any(e.system == target for e in collection.systems):
            return err(f"System을 찾을 수 없습니다: {target}")
        rows = [cache.get_row(int(uid)) for uid in (rom_uids or [])]
        rows = [r for r in rows if r is not None and r["system"] != target]
        if not rows:
            return err("옮길 항목이 없습니다.")
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(
            collection, sorted({target, *(r["system"] for r in rows)}))
        if blocked:
            return blocked

        uids = [r["rom_uid"] for r in rows]
        items, _bytes = clipboard.build_items(collection, cache, uids)
        items = [{**item, "system": target} for item in items]
        plan = _operation if _operation is not None else self._plan(collection_id)
        added = builder.plan_add(plan, collection, provider, items)
        # 대상에 이미 같은 파일이 있으면 사용자가 정해야 한다 - 옮기기가 조용히 덮어쓰지 않는다.
        conflicts = added.pop("conflictKeys", [])
        builder.plan_delete(plan, collection, cache, uids, provider)
        if _operation is not None:
            for entry in plan.entries:
                if entry.op == OP_DELETE:
                    entry.source = {**(entry.source or {}),
                                    "requiresCopy": f"add|{target}|{entry.filename}"}
        return ok({"moved": added["added"], "target": target, "conflicts": len(conflicts),
                   "skipped": added.get("skipped", [])})

    @guarded
    def plan_storage_change(self, collection_id, system, storage_to, _operation=None):
        collection, cache, _ = self._plan_context(collection_id)
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(collection, [system])
        if blocked:
            return blocked
        result = builder.plan_storage_change(_operation if _operation is not None else self._plan(collection_id), collection, cache,
                                             system, storage_to)
        return ok(result)

    # ------------------------------------------------------------------
    # Title Prefix/Postfix (app/title_affix.py) - Plan을 거치는 예외(D1, app/model/plan.py)
    # ------------------------------------------------------------------
    def _title_affix_config(self):
        stored = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("titleAffix") or {}
        return title_affix.normalize_config(stored)

    def _title_affix_rows(self, cache, rom_uids=None, system=None):
        """대상 행. `rom_uids`가 있으면 Gamelist에서 고른 항목들, 없으면 System 전체다.
        `system`은 하나이거나 **여러 개**다(Storage 그룹 우클릭 - 그 그룹의 System 전부)."""
        if rom_uids:
            rows = (cache.get_row(int(uid)) for uid in rom_uids)
            return [row for row in rows if row is not None]
        if system:
            systems = list(system) if isinstance(system, (list, tuple)) else [system]
            return cache.query_rows(systems=systems, order="title")
        return []

    @guarded
    def title_affix_preview(self, collection_id, rom_uids=None, system=None):
        """이 게임들에 실제로 적용될 새 제목 미리보기(Gamelist 우클릭 - 선택 항목,
        System 우클릭 - 그 System 전체 중 하나를 넘긴다). 아직 아무것도 바꾸지 않는다."""
        collection, cache, _provider = self._plan_context(collection_id)
        rows = self._title_affix_rows(cache, rom_uids, system)
        if not rows:
            return err("대상을 찾을 수 없습니다.")
        changes = title_affix.preview_titles(rows, self._title_affix_config())
        return ok({"items": changes, "changed": sum(1 for c in changes if c["changed"])})

    @guarded
    def disc_retag_preview(self, collection_id, system, fmt=None):
        """"멀티 디스크 태그 적용"(System 우클릭) 미리보기 - 기존 꼬리표를 지우고 설정에
        고른(또는 넘겨받은) 형식으로 다시 붙인다. 디스크가 아닌 항목은 바뀌지 않는다."""
        collection, cache, _provider = self._plan_context(collection_id)
        rows = self._title_affix_rows(cache, system=system)
        if not rows:
            return err("대상을 찾을 수 없습니다.")
        fmt = fmt or self._disc_title_option()["format"]
        changes = title_affix.preview_disc_retag(rows, fmt)
        return ok({"items": changes, "changed": sum(1 for c in changes if c["changed"])})

    @guarded
    def plan_disc_retag(self, collection_id, system, fmt=None, _operation=None):
        """미리보기에서 확인한 대로 Plan에 올린다(Title Prefix/Postfix와 같은 D1 예외 -
        Plan을 거치는 텍스트 편집)."""
        collection, cache, _provider = self._plan_context(collection_id)
        rows = self._title_affix_rows(cache, system=system)
        if not rows:
            return err("대상을 찾을 수 없습니다.")
        blocked = self._ensure_writable(collection, sorted({row["system"] for row in rows}))
        if blocked:
            return blocked
        fmt = fmt or self._disc_title_option()["format"]
        changes = title_affix.preview_disc_retag(rows, fmt)
        result = builder.plan_title_edit(_operation if _operation is not None else self._plan(collection_id), cache, changes)
        return ok(result)

    @guarded
    def plan_title_edit(self, collection_id, rom_uids=None, system=None, _operation=None):
        """미리보기에서 확인한 대로 Plan에 올린다. 실제 파일은 Apply를 눌러야 바뀐다(사용자 결정).

        미리보기와 똑같은 대상 선택을 다시 받아 서버에서 새로 계산한다 - 클라이언트가
        준 결과를 그대로 믿지 않는다(다른 Plan 만들기 메서드들과 같은 태도).
        """
        collection, cache, _provider = self._plan_context(collection_id)
        rows = self._title_affix_rows(cache, rom_uids, system)
        if not rows:
            return err("대상을 찾을 수 없습니다.")
        blocked = self._ensure_writable(collection, sorted({row["system"] for row in rows}))
        if blocked:
            return blocked
        changes = title_affix.preview_titles(rows, self._title_affix_config())
        result = builder.plan_title_edit(_operation if _operation is not None else self._plan(collection_id), cache, changes)
        return ok(result)

    @guarded
    def plan_remove_entry(self, collection_id, key):
        return ok(self._plan(collection_id).remove(key))

    @guarded
    def plan_clear(self, collection_id):
        self._plan(collection_id).clear()
        return ok(True)

    @guarded
    def copy_selection(self, collection_id, rom_uids):
        """다른 인스턴스에서도 붙여넣을 수 있게 내보낸다(결정 D5)."""
        collection, cache, _ = self._plan_context(collection_id)
        return ok(clipboard.copy_selection(self.registry, collection, cache, rom_uids,
                                           self._clipboard_dir))

    @guarded
    def cut_selection(self, collection_id, rom_uids):
        if collection_id == "__archive__":
            preview = self.archive_delete_owned_preview(rom_uids)
            if not preview["ok"] or preview["data"]["blocked"]:
                return err("외부 원본 연결이 있는 게임은 이동할 수 없습니다. 복사를 사용하세요.")
            result = self.archive_copy_selection(rom_uids)
            if result["ok"]:
                descriptor = clipboard.peek(self.registry)
                descriptor["cut"] = True
                descriptor["archiveIds"] = [str(rid) for rid in rom_uids]
                descriptor["archiveConfig"] = self._archive_config()
                descriptor["archiveStates"] = {str(rid): archive_paste_service.state_of(
                    self.archive, self.archive.get_identity(str(rid)))["signature"] for rid in rom_uids}
                self.registry.set_setting(clipboard.CLIPBOARD_KEY, descriptor)
            return result
        result = self.copy_selection(collection_id, rom_uids)
        if not result["ok"]:
            return result
        descriptor = clipboard.peek(self.registry)
        descriptor["cut"] = True
        self.registry.set_setting(clipboard.CLIPBOARD_KEY, descriptor)
        return ok({**result["data"], "cut": True})

    @guarded
    def clipboard_items(self):
        """지금 복사해 둔 항목들의 (System, 파일명) 요약. Gamelist에서 "이 항목에
        붙여넣기"를 보여줄지 판단하는 데 쓴다 - 파일명이 다른 항목에는 자동 매칭
        Ctrl+V가 닿지 않으므로(§5 - "System + ROM Filename은 대상 지목을 위한
        힌트일 뿐, Game Identity 자체가 아니다"), 정확히 무엇이 복사되어 있는지
        보여주고 사용자가 직접 대상을 골라야 한다.
        """
        _descriptor, items = clipboard.read_items(self.registry)
        if not items:
            return err("붙여넣을 항목이 없습니다.")
        return ok({"count": len(items),
                   "items": [{"system": i["system"], "filename": i["filename"],
                              "title": (i.get("fields") or {}).get("name") or i["filename"]}
                             for i in items]})

    @guarded
    def clipboard_systems(self, collection_id):
        """복사해 둔 항목의 System과, 그것이 이 Collection에 있는지.

        Frontend마다 System 이름 규칙이 다르다(사용자 피드백 - Pegasus의 `FBNEO ACT`는 ES-DE가
        허용하지 않는 이름이다). 화면은 이 목록을 보고 **어느 System으로 붙일지 고르는 창**을 띄운다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        _descriptor, items = clipboard.read_items(self.registry)
        if not items:
            return err("붙여넣을 항목이 없습니다.")
        mine = {e.system for e in collection.systems}
        counts: dict[str, int] = {}
        for item in items:
            counts[item["system"]] = counts.get(item["system"], 0) + 1
        return ok({
            "systems": [{"system": name, "count": counts[name], "exists": name in mine}
                        for name in sorted(counts)],
            "targetSystems": sorted(mine),
        })

    @guarded
    def clipboard_system_target(self, collection_id, system):
        """Preview a new-only paste into one Collection system."""
        collection, cache, _ = self._plan_context(collection_id)
        if system not in {entry.system for entry in collection.systems}:
            return err(f"대상 System을 찾을 수 없습니다: {system}")
        descriptor, items = clipboard.read_items(self.registry)
        if not items:
            return ok({"count": 0, "items": [], "duplicates": []})
        if (descriptor.get("sourceCollectionId") == collection_id
                and collection.frontend in self._FIXED_SYSTEM_FRONTENDS
                and any(item["system"] != system for item in items)):
            return err("이 Collection에서는 다른 System으로 붙여넣을 수 없습니다.")
        index = transfer.TargetIndex(cache, {system})
        duplicates = []
        summaries = []
        for item in items:
            mapped = {**item, "system": system}
            match, _ = index.find(mapped, exact_only=True)
            if match is not None:
                duplicates.append({"filename": item["filename"],
                                   "targetFilename": match["filename"]})
            summaries.append({"system": item["system"], "filename": item["filename"],
                              "title": (item.get("fields") or {}).get("name") or item["filename"]})
        return ok({"count": len(items), "items": summaries, "duplicates": duplicates})

    @guarded
    def paste(self, collection_id, mode=None, system_map=None, target_map=None,
              fallback_target=None, new_only=False, immediate=False):
        """붙여넣기. **Settings의 복사 정책(transfer)을 따른다.**

        `mode`(patch/overwrite/replace)가 이미 있는 항목을 어떻게 다룰지 정한다
        (app/plan/transfer.py). 주지 않으면 저장된 모드를 쓴다.

        `system_map`({원본 System: 이 Collection의 System})으로 **System 이름이 달라도 붙여넣는다**
        (사용자 결정 - "페가수스의 FBNEO ACT를 ES-DE로 가져올 때 system을 선택해서 붙여넣기").
        빈 값으로 두면 원본 이름을 그대로 쓴다(없으면 그 이름으로 새로 생긴다).

        - ROM/Media를 빼기로 했으면 Plan에 올리기 전에 그 부분을 뺀다(메타데이터는 늘 간다).
        - **`unmatchedRom` 정책은 대상 Game이 아예 없을 때만 적용된다.** 원본에 ROM이 없다는
          것(Archive처럼 메타데이터만 있는 항목)과 대상 Game이 존재하지 않는다는 것은 다른
          이야기다 - ROM이 없다고 Game이 없는 것은 아니다. 대상에 이미 그 Game이 있으면
          (ROM이 있든 메타데이터만 있든) 이 정책과 무관하게 평소 모드(Patch/Overwrite/Replace)
          그대로 메타데이터/미디어가 간다. 대상이 정말 없어서 **ROM 없는 새 항목**이
          생기는 경우에만 `unmatchedRom` 정책이 끼어든다 - 기본은 아무것도 복사하지 않고
          건너뛴다. "복사"를 골랐으면 Metadata/Media/Video를 독립적으로 골라 그것만 담는다.
        - 충돌 기본 처리가 skip/overwrite면 **이번 붙여넣기로 생긴 충돌만** 그렇게 정한다.
          원래 Plan에 있던 충돌은 사용자가 고를 몫이라 건드리지 않는다.
        """
        collection, _, provider = self._plan_context(collection_id)
        descriptor, items = clipboard.read_items(self.registry)
        if not items:
            return err("붙여넣을 항목이 없습니다.")
        cut = bool(descriptor.get("cut"))
        if cut and descriptor.get("sourceCollectionId") == "__archive__":
            if not immediate or target_map or fallback_target or (mode and transfer.normalize_mode(mode) != transfer.MODE_OVERWRITE):
                return err("잘라낸 게임은 대상 System에 붙여넣으세요.")
            from app.archive import move as archive_move
            return ok(archive_move.prepare(self, collection_id, descriptor, items, system_map))
        if cut:
            if not immediate or target_map or fallback_target:
                return err("잘라낸 게임은 대상 System의 빈 공간에 붙여넣으세요.")
            if mode and transfer.normalize_mode(mode) != transfer.MODE_OVERWRITE:
                return err("잘라낸 게임은 붙여넣기로 이동하세요.")
            items = [{**item, "cutSourceSystem": item["system"],
                      "cutSourceFilename": item["filename"]} for item in items]
        # System 이름 바꾸기는 **정책을 따지기 전에** 한다 - 이 뒤의 검사(쓰기 가능한 System인가)는
        # 실제로 파일이 놓일 System을 봐야 한다.
        remap = {str(k): str(v).strip() for k, v in (system_map or {}).items() if str(v or "").strip()}
        if (descriptor.get("sourceCollectionId") == collection_id
                and collection.frontend in self._FIXED_SYSTEM_FRONTENDS):
            for item in items:
                source_system = item["system"]
                mapped_system = remap.get(source_system, source_system)
                source_key = transfer.item_key(item)
                explicit_target = (target_map or {}).get(source_key)
                target_system = str(explicit_target).partition("|")[0] if explicit_target else ""
                fallback_system = (str(fallback_target).partition("|")[0]
                                   if fallback_target and len(items) == 1 else "")
                destinations = [value for value in (mapped_system, target_system, fallback_system) if value and value != source_system]
                if destinations and (cut or any(not metadata_compatible(source_system, value) for value in destinations)):
                    return err("이 Collection에서는 다른 System으로 붙여넣을 수 없습니다. "
                               "다른 System으로 이동도 지원하지 않습니다.")
        if remap:
            items = [{**item, "pasteSourceSystem": item["system"],
                      "system": remap.get(item["system"], item["system"])} for item in items]
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(
            collection, [item.get("system") for item in items])
        if blocked:
            return blocked
        policy = self._transfer_policy()
        if cut:
            policy = {**policy, "includeRom": True, "includeMedia": True}
        mode = transfer.normalize_mode(mode or policy["pasteMode"])
        downgraded_from = None
        policy = {**policy, "pasteMode": mode}

        # **사용자가 지목한 대상**({"system|원본파일명": "system|대상파일명"}). 자동 판단(파일명 일치)이
        # 못 붙인 짝을 사람이 직접 잇는 길이다(제안서 §5 - Replace는 Match 결과에 제한되지 않는다).
        # 지목한 대상이 없으면 **조용히 새 항목을 만들지 않고 거절한다** - 사용자는 그 자리에 쓰라고
        # 말한 것이지 새로 만들라고 한 것이 아니다.
        targets, target_cache = {}, self.workspace.open(collection_id)
        if new_only:
            destination_systems = {item["system"] for item in items}
            if (len(destination_systems) != 1 or target_map or fallback_target
                    or not remap):
                return err("System 신규 복사는 대상 System 하나만 지정해야 합니다.")
            system = next(iter(destination_systems))
            if system not in {entry.system for entry in collection.systems}:
                return err(f"대상 System을 찾을 수 없습니다: {system}")
            new_index = transfer.TargetIndex(target_cache, {system})
            duplicates = [item["filename"] for item in items
                          if new_index.find(item, exact_only=True)[0] is not None]
            if duplicates:
                return err(f"대상 System에 같은 게임이 이미 있습니다: {', '.join(duplicates[:3])}")
        for source_key, dest_key in (target_map or {}).items():
            dest_system, _, dest_filename = str(dest_key).partition("|")
            row = target_cache.get_row_by_filename(dest_system, dest_filename)
            if row is None:
                return err(f"지목한 대상을 찾을 수 없습니다: {dest_key}")
            targets[str(source_key)] = row

        # **화면에서 고른 행**(`fallback_target`). 단일 붙여넣기에서는 명시적 대상이 우선한다.
        #
        # 사용자 모델은 "행을 고르고 붙여넣으면 그 행에 붙는다"인데, 예전의 Ctrl+V는 고른 행을
        # 아예 보지 않고 이름으로만 대상을 찾았다. 그래서 이름이 전혀 다른 두 게임
        # (`Final Fantasy 7.zip` <-> `ff7.rom`)은 화면에서 대상을 골라 놓고 붙여넣어도 닿지
        # 않았다(실사용 리포트). 이름으로 확실한 대상을 찾았으면 그쪽이 이긴다 - 고른 행을
        # 무조건 이기게 하면, 다른 볼일로 남아 있던 선택이 조용히 덮어쓰기 대상이 된다.
        # 확인 창은 띄우지 않는다. **Plan이 확인 역할을 한다** - Apply 전에는 아무것도 바뀌지 않는다.
        fallback_row = None
        if fallback_target and len(items) == 1:      # 여러 개를 한 행에 붙일 수는 없다
            system, _, filename = str(fallback_target).partition("|")
            fallback_row = target_cache.get_row_by_filename(system, filename)
        # 같은 Collection 안에서 복사했다면, 이름으로 찾은 "확실한 대상"이 **원본 자기 자신**일
        # 수 있다. 자기 자신에게 붙여넣는 것은 아무 일도 아니므로, 그것 때문에 사용자가 고른
        # 행을 무시하면 안 된다(실사용 리포트 - 같은 nes 안에서 `Dragon Ball 2 (K).zip`을 복사해
        # `Dragon Ball Z1 (K).zip`에 붙이려 했는데, 원본 자신이 대상으로 잡혀 아무 일도 없었다).
        unmatched = policy["unmatchedRom"]
        # **대상 찾기는 한 곳에서만 한다.** 예전에는 여기서 `get_row_by_filename()`으로 정확한
        # 파일명만 보고 "대상이 없다 = ROM 미매칭"으로 걸러 낸 뒤, 그 뒤의 transfer.prepare()가
        # 다시 제 기준으로 대상을 찾았다. 두 기준이 달라서, 이름만 조금 다른 같은 게임
        # (`Aleste [J].zip` vs `Aleste (Japan) ... .zip`)은 여기서 먼저 버려져 prepare()에
        # 닿지도 못했다(실사용 버그 - "Compare에선 다르다고 나오는데 붙여넣으면 아무 일도 없다").
        index = transfer.TargetIndex(target_cache, {item["system"] for item in items})

        prepared, extra_skipped = [], []
        for item in items:
            key = transfer.item_key(item)
            existing = targets.get(key)
            how = "manual" if existing is not None else None
            if existing is None and fallback_row is not None:
                existing, how = fallback_row, "selected"
                targets[key] = fallback_row
            if existing is None:
                existing, how = index.find(item, exact_only=True)
            source_system = item.get("pasteSourceSystem", item["system"])
            destination_system = existing["system"] if existing is not None else item["system"]
            if source_system != destination_system:
                if cut or not metadata_compatible(source_system, destination_system):
                    extra_skipped.append({"filename": item["filename"], "reason": "메타데이터 계열이 다른 System입니다."})
                    continue
                if existing is None:
                    extra_skipped.append({"filename": item["filename"], "reason": "대상 System에 같은 파일명의 게임이 없습니다."})
                    continue
                item = {**item, "rom": None}
            if item.get("rom") or existing is not None:
                # ROM이 있거나, 대상 Game이 이미 있거나, 비슷한 후보가 있다. 대상이 있으면 이건
                # 그냥 평범한 Metadata/Media 갱신이다 - ROM 유무와 무관하게 모드(Patch/Overwrite/
                # Replace)를 그대로 따른다. 비슷한 후보만 있는 경우도 여기로 흘려보낸다 -
                # prepare()가 "직접 지목하세요"라고 정확한 이유를 붙여 준다(여기서 "ROM 미매칭"
                # 이라고 엉뚱한 이유를 달면 사용자가 진짜 원인을 못 찾는다).
                # unmatchedRom 정책은 "후보조차 없어 ROM 없는 새 항목이 생기는" 경우만 본다.
                prepared.append({**item,
                                 "rom": item["rom"] if policy["includeRom"] else None,
                                 "media": item.get("media") if policy["includeMedia"] else []})
                continue
            # 진짜 미매칭 - 원본에 ROM이 없고 대상 Game도 없어서, 붙이면 ROM 없는 새
            # 항목이 생긴다(unmatchedRom, 사용자 결정).
            if unmatched["mode"] != "copy":
                extra_skipped.append({"filename": item["filename"],
                                      "reason": "원본에 ROM이 없고 대상에도 같은 게임이 없습니다"
                                                " - Settings의 정책에 따라 건너뜀"})
                continue
            media = []
            for m in item.get("media") or []:
                wanted = unmatched["video"] if m.get("type") == VIDEO_MEDIA_TYPE else unmatched["media"]
                if wanted:
                    media.append(m)
            fields = item.get("fields") if unmatched["metadata"] else {}
            if not unmatched["metadata"] and not media:
                extra_skipped.append({"filename": item["filename"],
                                      "reason": "원본에 ROM이 없고 대상에도 같은 게임이 없습니다"
                                                " - Metadata/Media를 모두 끄면 남는 것이 없습니다"})
                continue
            prepared.append({**item, "fields": fields, "media": media})

        # 모드는 **원본에 ROM이 없던 항목의 정책(위)을 거친 뒤에** 적용한다 - 모드가 대상에 이미 있는 ROM을
        # 걷어 낸 항목은 "원본에 ROM이 없는" 항목이 아니다. 걷어 내고 나면 바뀔 것이 없는 항목은 Plan에
        # 올리지 않고 이유를 알린다.
        destination_systems = {item["system"] for item in prepared}
        destination_systems.update(row["system"] for row in targets.values())
        if fallback_row is not None:
            destination_systems.add(fallback_row["system"])
        adapter = get_adapter(collection.frontend)
        layouts = [adapter.layout(collection, system) for system in destination_systems]
        undoable = supports_local_undo(
            path for layout in layouts
            for path in (layout.rom_dir, layout.metadata_file, layout.media_dir))
        prepared, mode_skipped = transfer.prepare(prepared, target_cache, mode,
                                                  targets=targets, index=index,
                                                  exact_only=True,
                                                  allow_rom_replace=immediate and undoable,
                                                  force_media=immediate and mode == transfer.MODE_REPLACE)
        extra_skipped.extend(mode_skipped)

        if not prepared:
            return ok({"added": 0, "skipped": extra_skipped, "conflicts": 0,
                      "source": descriptor.get("sourceName"), "policy": policy,
                      "downgradedFrom": downgraded_from})

        plan = Plan(collection_id) if immediate else self._plan(collection_id)
        if immediate and undoable:
            prepared = [{**item, "retainBackups": True} for item in prepared]
        result = builder.plan_add(plan, collection, provider, prepared)
        keys = result.pop("conflictKeys", [])
        if immediate:
            # 충돌 기준은 파일명까지 같은 대상이 이미 있는가이다. 명시적으로 행을
            # 지목한 경우만 다른 파일명의 대상에 기록한다. Plan의 파일 충돌 목록은
            # 실행 직전에 다시 검증하며, 기존 Plan 항목을 이 작업에 섞지 않는다.
            collisions = []
            file_conflicts = {f"{entry.system}|{entry.filename}" for entry in plan.entries
                              if entry.conflicts}
            for item in prepared:
                existing = target_cache.get_row_by_filename(item["system"], item["filename"])
                key = transfer.item_key(item)
                if key not in file_conflicts and not transfer.fields_conflict(
                        (existing or {}).get("fields"), item.get("fields"), mode):
                    continue
                collisions.append({
                    "key": key, "system": item["system"],
                    "filename": item["filename"],
                    "existingRomUid": existing["rom_uid"] if existing else None,
                    "romComparison": rom_comparison(item.get("rom"), str(Path(get_adapter(collection.frontend).layout(collection, item["system"]).rom_dir) / item["filename"]), provider),
                    "existingFields": existing.get("fields") or {} if existing else {},
                    "incomingFields": item.get("fields") or {},
                    "existingTitle": ((existing.get("fields") or {}).get("name")
                                      if existing else None) or item["filename"],
                    "incomingTitle": (item.get("fields") or {}).get("name") or item["filename"],
                    "existingDescription": ((existing.get("fields") or {}).get("desc")
                                            if existing else None) or "",
                    "incomingDescription": (item.get("fields") or {}).get("desc") or "",
                })
            op_id = uuid.uuid4().hex
            if len(self._paste_ops) >= 20:
                self._paste_ops.pop(next(iter(self._paste_ops)))
            cut_source_id = descriptor.get("sourceCollectionId") if cut else None
            if cut:
                source_collection, source_cache, _ = self._plan_context(cut_source_id)
                source_layouts = [get_adapter(source_collection.frontend).layout(source_collection, item["cutSourceSystem"])
                                  for item in prepared]
                if not undoable or not supports_local_undo(path for layout in source_layouts
                    for path in (layout.rom_dir, layout.media_dir, layout.metadata_file)):
                    return err("잘라내기는 현재 로컬 경로 사이에서만 지원합니다.")
                if cut_source_id == collection_id and any(item["system"] == item["cutSourceSystem"] for item in prepared):
                    return err("같은 System으로 이동할 수 없습니다.")
            self._paste_ops[op_id] = {"collectionId": collection_id, "plan": plan,
                                      "collisions": collisions, "prepared": prepared,
                                      "undoable": undoable, "cutSourceId": cut_source_id}
            return ok({"operationId": op_id, "source": descriptor.get("sourceName"),
                       "action": "move" if cut else "paste", "count": len(prepared), "collisions": collisions,
                       "undoable": undoable,
                       "skipped": extra_skipped + result.get("skipped", [])})
        if mode in (transfer.MODE_OVERWRITE, transfer.MODE_REPLACE):
            # 덮어쓰기 모드: **미디어만** 충돌한 항목은 덮어쓴다(원하는 그림으로 바꾸려는 것이므로).
            # ROM이 충돌한 항목은 설정의 충돌 정책을 따른다 - 다른 ROM 파일을 덮어쓰는 것은
            # 미디어 한 장을 바꾸는 것과 무게가 다르다.
            auto = [k for k in keys
                    if all(c.get("kind") != "rom" for c in (plan.get(k).conflicts or []))]
            for key in auto:
                builder.resolve_conflict(plan, collection, provider, key, RESOLVE_OVERWRITE)
            keys = [k for k in keys if k not in auto]
            result["autoResolved"] = len(auto)
            result["conflicts"] = len(keys)
        if policy["conflict"] in (RESOLVE_SKIP, RESOLVE_OVERWRITE):
            for key in keys:
                builder.resolve_conflict(plan, collection, provider, key, policy["conflict"])
            result["autoResolved"] = result.get("autoResolved", 0) + len(keys)
            result["conflicts"] = 0
        result["skipped"] = [*extra_skipped, *result.get("skipped", [])]
        return ok({**result, "source": descriptor.get("sourceName"), "policy": policy,
                   "downgradedFrom": downgraded_from})

    @guarded
    def operation_preview(self, collection_id, action, options=None):
        """Build an isolated operation. There is no user-managed pending queue."""
        options = options or {}
        collection, cache, provider = self._plan_context(collection_id)
        operation = Plan(collection_id)
        if action == "title":
            result = self.plan_title_edit(collection_id, options.get("romUids"),
                                          options.get("system"), _operation=operation)
        elif action == "disc":
            result = self.plan_disc_retag(collection_id, options.get("system"),
                                          options.get("format"), _operation=operation)
        elif action == "move":
            result = self.plan_move_to_system(collection_id, options.get("romUids"),
                                              options.get("system"), _operation=operation)
        elif action == "storage":
            result = self.plan_storage_change(collection_id, options.get("system"),
                                              options.get("storageId"), _operation=operation)
        elif action == "archive-import":
            result = self.archive_to_collection(collection_id, options.get("ids") or [],
                options.get("mode"), options.get("targetRomUid"), _operation=operation)
        elif action == "import":
            result = self.collection_import_plan(collection_id, options.get("sourceId"),
                options.get("romUids"), options.get("targetRomUid"), options.get("system"),
                options.get("mode"), _operation=operation)
        else:
            return err("지원하지 않는 작업입니다.")
        if not result["ok"]:
            return result
        return self._register_operation(collection_id, action, operation, result)

    @guarded
    def start_archive_import_preview(self, collection_id, options=None):
        options = options or {}
        def run(progress):
            operation = Plan(collection_id)
            result = self.archive_to_collection(collection_id, options.get("ids") or [],
                options.get("mode"), options.get("targetRomUid"), _operation=operation, _progress=progress)
            if not result["ok"]:
                raise ValueError(result["error"])
            progress(1, 1, "Archive 가져오기 준비 완료")
            registered = self._register_operation(collection_id, "archive-import", operation, result)
            if not registered["ok"]:
                raise ValueError(registered["error"])
            return registered["data"]
        return ok({"jobId": self.jobs.run_heavy(run, mutates_state=True,
            target_ids=(collection_id, "archive"), kind="archive-import-preview")})

    def _register_operation(self, collection_id, action, operation, result):
        collection, cache, provider = self._plan_context(collection_id)
        adapter = get_adapter(collection.frontend)
        paths = []
        for entry in operation.entries:
            layout = adapter.layout(collection, entry.system)
            paths.extend([layout.rom_dir, layout.metadata_file, layout.media_dir])
        undoable = action != "storage" and supports_local_undo(paths)
        prepared, collisions = [], []
        for entry in operation.entries:
            if entry.op != OP_ADD:
                continue
            entry.source = {**(entry.source or {}), "retainBackups": undoable}
            item = {**entry.source, "system": entry.system, "filename": entry.filename}
            prepared.append(item)
            existing = cache.get_row_by_filename(entry.system, entry.filename)
            if entry.conflicts or transfer.fields_conflict(
                    (existing or {}).get("fields"), item.get("fields"), "overwrite"):
                fields = (existing or {}).get("fields") or {}
                incoming = item.get("fields") or {}
                collisions.append({"key": transfer.item_key(item), "system": entry.system,
                    "filename": entry.filename, "existingRomUid": (existing or {}).get("rom_uid"),
                    "romComparison": rom_comparison(item.get("rom"), str(Path(adapter.layout(collection, entry.system).rom_dir) / entry.filename), provider),
                    "existingFields": fields, "incomingFields": incoming,
                    "existingTitle": fields.get("name") or entry.filename,
                    "incomingTitle": incoming.get("name") or entry.filename,
                    "existingDescription": fields.get("desc") or "",
                    "incomingDescription": incoming.get("desc") or ""})
        operation_id = uuid.uuid4().hex
        self._paste_ops[operation_id] = {"collectionId": collection_id, "plan": operation,
            "prepared": prepared, "collisions": collisions, "undoable": undoable}
        return ok({"operationId": operation_id, "action": action, "targetCollectionId": collection_id, "count": len({(e.system, e.filename) for e in operation.entries}),
                   "collisions": collisions, "undoable": undoable,
                   "skipped": result["data"].get("skipped", [])})

    @guarded
    def paste_execute(self, operation_id, decisions=None, acknowledge_non_undoable=False):
        """미리 본 복사만 실행한다. 결정하지 않은 충돌은 안전하게 보류한다."""
        op = self._paste_ops.get(str(operation_id))
        if op is None:
            return err("복사 미리보기가 만료되었습니다. 다시 붙여넣으세요.")
        if op.get("target") == "archive-move":
            from app.archive import move as archive_move
            result = archive_move.execute(self, str(operation_id), op, decisions or {})
            self._paste_ops.pop(str(operation_id), None)
            return ok(result)
        if op.get("target") == "archive":
            return self._execute_archive_paste_operation(
                str(operation_id), op, decisions or {}, acknowledge_non_undoable)
        collection_id, plan = op["collectionId"], op["plan"]
        if not op["undoable"] and not acknowledge_non_undoable:
            return err("네트워크 또는 기기 경로의 작업은 자동 되돌리기를 보장할 수 없습니다. 실행 전 확인이 필요합니다.")
        decisions = decisions or {}
        expected = {c["key"] for c in op["collisions"]}
        if any(decisions.get(key) not in ("overwrite", "skip") for key in expected):
            return err("충돌한 게임마다 덮어쓰기 또는 건너뛰기를 선택하세요.")
        collection, cache, provider = self._plan_context(collection_id)
        for entry in list(plan.entries):
            choice = decisions.get(f"{entry.system}|{entry.filename}")
            if choice == "skip":
                plan.remove(entry.key)
                for dependent in list(plan.entries):
                    if (dependent.source or {}).get("requiresCopy") == entry.key:
                        plan.remove(dependent.key)
            elif entry.conflicts:
                builder.resolve_conflict(plan, collection, provider, entry.key,
                                         RESOLVE_OVERWRITE)
        if not len(plan):
            self._paste_ops.pop(str(operation_id), None)
            return ok({"jobId": None, "skipped": len(expected)})
        report = validate(plan, collection, cache, provider)
        if report["blocked"] or report["entries"]:
            return err("대상 파일이 바뀌었거나 저장 공간이 부족합니다. 다시 붙여넣으세요.")
        source_id = op.get("cutSourceId")
        source_plan = None
        if source_id:
            source_collection, source_cache, source_provider = self._plan_context(source_id)
            source_plan = Plan(source_id)
            source_uids = []
            for entry in plan.entries:
                original = entry.source or {}
                row = source_cache.get_row_by_filename(original["cutSourceSystem"], original["cutSourceFilename"])
                if not row:
                    return err("잘라낸 원본 게임이 바뀌었습니다. 다시 잘라내세요.")
                source_uids.append(row["rom_uid"])
            builder.plan_delete(source_plan, source_collection, source_cache, source_uids, source_provider)
            target_adapter = get_adapter(collection.frontend)
            source_adapter = get_adapter(source_collection.frontend)
            from app.plan.builder import add_destinations
            destination_paths = [Path(path) for entry in plan.entries
                for _, path, _, _ in add_destinations(entry, target_adapter.layout(collection, entry.system), target_adapter)]
            destination_paths += [Path(target_adapter.layout(collection, entry.system).metadata_file) for entry in plan.entries]
            source_paths = [Path(path) for entry in source_plan.entries
                for path in delete_destinations(entry, source_collection, source_cache, source_adapter)]
            source_paths += [Path(source_adapter.layout(source_collection, entry.system).metadata_file) for entry in source_plan.entries]
            def path_keys(paths):
                names, identities = set(), set()
                for path in set(paths):
                    names.add(os.path.normcase(os.path.abspath(path)))
                    try:
                        stat = path.stat()
                        if stat.st_ino:
                            identities.add((stat.st_dev, stat.st_ino))
                    except FileNotFoundError:
                        pass
                return names, identities
            source_names, source_ids = path_keys(source_paths)
            destination_names, destination_ids = path_keys(destination_paths)
            if source_names & destination_names or source_ids & destination_ids:
                return err("원본과 대상이 같은 파일을 참조해 이동할 수 없습니다. 복사를 사용하세요.")
            source_report = validate(source_plan, source_collection, source_cache, source_provider)
            if source_report["entries"] or source_report["blocked"]:
                return err("잘라낸 원본 파일이 바뀌었습니다. 다시 잘라내세요.")
        lock_name = f"apply:{collection_id}"
        if not self.registry.acquire_lock(lock_name, kind="apply"):
            return err("다른 창에서 같은 Collection을 적용하는 중입니다.")
        source_lock = f"apply:{source_id}" if source_id and source_id != collection_id else None
        if source_lock and not self.registry.acquire_lock(source_lock, kind="move"):
            self.registry.release_lock(lock_name)
            return err("원본 Collection에서 다른 작업이 진행 중입니다.")
        self._paste_ops.pop(str(operation_id), None)

        def run(progress):
            journal_started = False
            try:
                if op["undoable"]:
                    suffix = self._paste_journal.begin(operation_id, collection_id,
                                                       collection, plan, extra_paths=[
                        path for entry in plan.entries if entry.op == OP_DELETE
                        for path in delete_destinations(entry, collection, cache,
                                                       get_adapter(collection.frontend))])
                    journal_started = True
                    if source_plan:
                        source_paths = [path for entry in source_plan.entries for path in delete_destinations(
                            entry, source_collection, source_cache, get_adapter(source_collection.frontend))]
                        self._paste_journal.include_source(operation_id, source_collection, source_plan, source_paths)
                else:
                    suffix = None
                result = apply_plan(plan, collection, cache, self.registry, provider,
                                    progress_cb=progress, disc_titles=self._disc_title_option(),
                                    backup_suffix=suffix, retain_backups=op["undoable"],
                                    rom_staging=op["undoable"], trash_suffix=suffix)
                if source_plan and not (result.get("failed") or result.get("partial") or result.get("invalid")):
                    moved = apply_plan(source_plan, source_collection, source_cache, self.registry,
                                       source_provider, trash_suffix=suffix)
                    for key in ("failed", "partial", "invalid"):
                        result[key] = result.get(key, 0) + moved.get(key, 0)
                    result["errors"] = result.get("errors", []) + moved.get("errors", [])
                    self.workspace.scan(source_id, force=True, systems=[e.system for e in source_plan.entries] or
                        sorted({item["cutSourceSystem"] for item in op["prepared"]}))
                    if not (result.get("failed") or result.get("partial") or result.get("invalid")):
                        current = clipboard.peek(self.registry) or {}
                        if current.get("cut") and current.get("sourceCollectionId") == source_id:
                            clipboard.clear(self.registry)
                if journal_started:
                    if result.get("failed") or result.get("partial") or result.get("invalid"):
                        self._paste_journal.rollback_running(operation_id)
                        result["rolledBack"] = True
                        result["applied"] = 0
                        if source_id:
                            self.workspace.scan(source_id, force=True, systems=sorted({item["cutSourceSystem"] for item in op["prepared"]}))
                    else:
                        self._paste_journal.commit(operation_id)
                        result["undoOperationId"] = operation_id
                if result.get("systems"):
                    self.workspace.scan(collection_id, force=True, systems=result["systems"])
                self.registry.append_change(CHANGE_APPLIED, collection_id,
                                            {"applied": result["applied"]})
                return result
            except Exception:
                if journal_started:
                    self._paste_journal.rollback_running(operation_id)
                    if source_id:
                        self.workspace.scan(source_id, force=True, systems=sorted({item["cutSourceSystem"] for item in op["prepared"]}))
                raise
            finally:
                self.registry.release_lock(lock_name)
                if source_lock:
                    self.registry.release_lock(source_lock)

        try:
            job_id = self.jobs.run_heavy(run, mutates_state=True,
                                         target_ids=tuple({collection_id, source_id} - {None}), kind="apply")
        except Exception:
            self.registry.release_lock(lock_name)
            if source_lock:
                self.registry.release_lock(source_lock)
            raise
        return ok({"jobId": job_id})

    @guarded
    def paste_preview_media(self, operation_id, key, media_type):
        """현재 복사 미리보기의 작은 원본 이미지 하나만 필요할 때 읽는다."""
        op = self._paste_ops.get(str(operation_id))
        if op is None or str(media_type) not in ("covers", "screenshots"):
            return ok(None)
        item = next((i for i in op["prepared"] if transfer.item_key(i) == key), None)
        if item is None:
            return ok(None)
        media = next((m for m in item.get("media") or []
                      if (m.get("type") or m.get("media_type")) == media_type), None)
        return ok(self._encode_image(media.get("path"), THUMBNAIL_MAX) if media else None)

    @guarded
    def paste_undo(self, collection_id, archive_operation_id=None):
        """마지막 로컬 작업을 되돌린다. 이후 파일 변경이 있으면 거절한다."""
        if collection_id != "__archive__" and not archive_operation_id:
            state_result = self.operation_state(collection_id)
            candidate = state_result.get("data", {}).get("undoOperationId")
            if candidate and (self._archive_journal.root / candidate / "operation.json").exists():
                return self.paste_undo("__archive__", candidate)
        if collection_id == "__archive__":
            cfg = self._archive_config()
            pending = self._archive_journal.pending(cfg)
            operation_id = archive_operation_id or (pending[-1]["id"] if pending else self._archive_journal.latest(cfg))
            if not operation_id:
                return err("되돌릴 수 있는 Archive 작업이 없습니다.")
            def undo_archive(progress):
                with archive_writing(cfg["archiveDir"]), self._archive_lifecycle_lock, self.archive._conn.lock:
                    if cfg != self._archive_config():
                        raise ValueError("Archive 설정이 바뀌었습니다.")
                    progress(0, 1, "Archive 복구 상태 확인 중")
                    tx = self._archive_journal.load(operation_id)
                    if tx.data["config"] != cfg:
                        raise ValueError("이 작업은 현재 Archive의 기록이 아닙니다.")
                    related = tx.data.get("relatedCollections", {})
                    held = []
                    try:
                        for cid in sorted(related):
                            if not self.registry.acquire_lock(f"apply:{cid}", kind="undo"):
                                raise ValueError("Collection에 다른 작업이 진행 중입니다.")
                            held.append(cid)
                        tx.restore(self.archive)
                    except Exception as exc:
                        if tx.data["status"] == "restoring":
                            self._archive_recovery_error = str(exc)
                            log.exception("Archive Undo interrupted; further edits blocked")
                        raise
                    finally:
                        for cid in held:
                            self.registry.release_lock(f"apply:{cid}")
                    for cid, systems in related.items():
                        self.workspace.scan(cid, force=True, systems=systems)
                    self._remember_archive_digest(cfg)
                    self._archive_recovery_error = None
                    self._thumb_cache.clear()
                    try:
                        progress(1, 1, "Archive 실행 취소 완료")
                    except JobCancelled:
                        log.info("Archive Undo completed before cancellation operation=%s", operation_id)
                    return {"operationId": operation_id}
            return ok({"jobId": self.jobs.run_heavy(undo_archive, mutates_state=True,
                       target_ids=("archive",), kind="archive-undo")})
        operation_id = self._paste_journal.latest_committed(collection_id)
        if not operation_id:
            return err("되돌릴 수 있는 로컬 작업이 없습니다.")
        lock_name = f"apply:{collection_id}"
        if not self.registry.acquire_lock(lock_name, kind="undo"):
            return err("다른 창에서 같은 Collection을 수정하는 중입니다.")

        related_ids = self._paste_journal.details(operation_id).get("relatedCollections", {})
        acquired_related = []
        for related_id in sorted(related_ids):
            if related_id == collection_id:
                continue
            related_lock = f"apply:{related_id}"
            if not self.registry.acquire_lock(related_lock, kind="undo"):
                for held in acquired_related:
                    self.registry.release_lock(held)
                self.registry.release_lock(lock_name)
                return err("원본 Collection에서 다른 작업이 진행 중입니다.")
            acquired_related.append(related_lock)

        def run(progress):
            try:
                progress(0, 1, "파일 상태 확인 중")
                restored = self._paste_journal.undo(operation_id)
                if restored["systems"]:
                    self.workspace.scan(collection_id, force=True, systems=restored["systems"])
                for related_id, systems in restored.get("relatedCollections", {}).items():
                    if related_id != collection_id:
                        self.workspace.scan(related_id, force=True, systems=systems)
                progress(1, 1, "되돌리기 완료")
                return {"operationId": operation_id, "systems": restored["systems"]}
            finally:
                self.registry.release_lock(lock_name)
                for held in acquired_related:
                    self.registry.release_lock(held)

        try:
            job_id = self.jobs.run_heavy(run, mutates_state=True,
                                         target_ids=tuple({collection_id, *related_ids}), kind="apply")
        except Exception:
            self.registry.release_lock(lock_name)
            for held in acquired_related:
                self.registry.release_lock(held)
            raise
        return ok({"jobId": job_id})

    @guarded
    def paste_redo(self, collection_id, archive_operation_id=None):
        cfg = self._archive_config()
        if collection_id != "__archive__":
            archive_rows = [row for row in self._archive_journal.records(cfg) if collection_id in row.get("relatedCollections", {}) and row.get("redoReady") and row["status"] == "undone"]
            local_id = self._paste_journal.latest_redo(collection_id)
            local_time = self._paste_journal.details(local_id).get("undoneAt", 0) if local_id else 0
            if archive_rows:
                chosen = max(archive_rows, key=lambda row: row.get("undoneAt", 0))
                if chosen.get("undoneAt", 0) > local_time:
                    return self.paste_redo("__archive__", chosen["id"])
            if not local_id:
                return err("다시 실행할 작업이 없습니다.")
            def redo_collection(progress):
                details = self._paste_journal.details(local_id)
                held = []
                try:
                    for cid in sorted({collection_id, *details.get("relatedCollections", {})}):
                        if not self.registry.acquire_lock(f"apply:{cid}", kind="redo"):
                            raise ValueError("다른 Collection 작업이 진행 중입니다.")
                        held.append(cid)
                    restored = self._paste_journal.redo(local_id)
                    self.workspace.scan(collection_id, force=True, systems=restored["systems"])
                    for cid, systems in restored.get("relatedCollections", {}).items():
                        self.workspace.scan(cid, force=True, systems=systems)
                    return {"operationId": local_id}
                finally:
                    for cid in held:
                        self.registry.release_lock(f"apply:{cid}")
            return ok({"jobId": self.jobs.run_heavy(redo_collection, mutates_state=True,
                        target_ids=(collection_id,), kind="redo")})
        operation_id = archive_operation_id or self._archive_journal.latest_redo(cfg)
        if not operation_id:
            return err("다시 실행할 작업이 없습니다.")
        def run(progress):
            with archive_writing(cfg["archiveDir"]), self._archive_lifecycle_lock, self.archive._conn.lock:
                tx = self._archive_journal.load(operation_id)
                if tx.data.get("config") != cfg or not tx.data.get("redoReady"):
                    raise ValueError("다시 실행할 Archive 작업이 현재 설정과 일치하지 않습니다.")
                held = []
                try:
                    for cid in sorted(tx.data.get("relatedCollections", {})):
                        if not self.registry.acquire_lock(f"apply:{cid}", kind="redo"):
                            raise ValueError("다른 Collection 작업이 진행 중입니다.")
                        held.append(cid)
                    tx.redo(self.archive)
                    self._remember_archive_digest(cfg)
                    for cid, systems in tx.data.get("relatedCollections", {}).items():
                        self.workspace.scan(cid, force=True, systems=systems)
                    self._thumb_cache.clear()
                    return {"operationId": operation_id}
                except Exception as exc:
                    if tx.data["status"] == "redoing":
                        self._archive_recovery_error = str(exc)
                    raise
                finally:
                    for cid in held:
                        self.registry.release_lock(f"apply:{cid}")
        return ok({"jobId": self.jobs.run_heavy(run, mutates_state=True, target_ids=("archive",), kind="archive-redo")})

    @guarded
    def operation_history(self, collection_id):
        from app.plan.history import listing
        return ok({"items": listing(self, collection_id), "recoveryError": self._archive_recovery_error,
            "retention": self._backup_retention_report.get(collection_id)})

    def _retain_backups(self, scope):
        from app.plan.backup_retention import prune
        try:
            settings = self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}
            report = prune(self, scope, settings.get("backupRetention"))
            report["eventId"] = uuid.uuid4().hex
            self._backup_retention_report[scope] = report
            if report.get("discarded") or report.get("limitExceeded") or report.get("sizeWarning") or report.get("errors"):
                log.info("Backup retention scope=%s report=%s", scope, report)
        except Exception as exc:
            log.exception("Backup retention failed; completed operation retained scope=%s", scope)
            self._backup_retention_report[scope] = {"eventId":uuid.uuid4().hex, "discarded":0, "errors":[str(exc)]}

    @guarded
    def recovery_action(self, collection_id, operation_id, action):
        if self.jobs.busy_targets(collection_id if collection_id != "__archive__" else "archive"):
            return err("진행 중인 작업이 끝난 뒤 복구하세요.")
        from app.plan.history import recovery_action
        with self._archive_lifecycle_lock:
            lock = f"apply:{collection_id}"
            if not self.registry.acquire_lock(lock, kind="recovery"):
                return err("다른 작업이 진행 중입니다.")
            try:
                return ok(recovery_action(self, collection_id, operation_id, action))
            finally:
                self.registry.release_lock(lock)

    @guarded
    def discard_operation_history(self, collection_id, operation_ids, acknowledged=False):
        if not acknowledged:
            return err("백업을 삭제하면 실행 취소·다시 실행이 불가능합니다. 확인이 필요합니다.")
        if self.jobs.busy_targets(collection_id if collection_id != "__archive__" else "archive"):
            return err("진행 중인 작업이 끝난 뒤 백업을 정리하세요.")
        from app.plan.history import discard
        with self._archive_lifecycle_lock:
            lock = f"apply:{collection_id}"
            if collection_id != "__archive__" and not self.registry.acquire_lock(lock, kind="history"):
                return err("다른 Collection 작업이 진행 중입니다.")
            try:
                return ok(discard(self, collection_id, operation_ids or []))
            finally:
                if collection_id != "__archive__":
                    self.registry.release_lock(lock)

    def _disc_title_option(self) -> dict:
        """여러 장짜리 게임의 제목 뒤에 장 번호를 붙일지(사용자 결정 - 기본은 끔).

        ES-DE는 목록에 파일명을 보여주지 않아, 여러 장짜리 게임은 제목이 전부 똑같이
        보인다. 켜면 Apply할 때 제목 뒤에만 붙인다 - 파일명은 건드리지 않는다.
        """
        stored = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("metadata") or {}
        fmt = stored.get("discTitleFormat")
        return {
            "enabled": bool(stored.get("discTitles")),
            "format": fmt if fmt in title_affix.DISC_FORMATS else title_affix.DEFAULT_DISC_FORMAT,
        }

    @guarded
    def disc_title_formats(self):
        """설정 화면이 고를 수 있는 표기 목록. 예시는 실제 함수가 만든 것을 보여준다 -
        설명과 동작이 어긋나지 않게."""
        return ok([{"id": key,
                    "sample": title_affix.disc_suffix("Game (Disc 1 of 3).bin", "psx", key).strip(),
                    "sampleDisk": title_affix.disc_suffix("Game (Disk 1 of 3).dsk", "msx2", key).strip()}
                   for key in title_affix.DISC_FORMATS])

    def _transfer_policy(self):
        stored = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("transfer") or {}
        merged = {**self.TRANSFER_DEFAULTS, **{k: v for k, v in stored.items() if k in self.TRANSFER_DEFAULTS}}
        conflict = merged["conflict"] if merged["conflict"] in ("ask", RESOLVE_SKIP, RESOLVE_OVERWRITE) else "ask"
        mode = merged["unmatchedRomMode"] if merged["unmatchedRomMode"] in ("skip", "copy") else "copy"
        return {
            "pasteMode": transfer.normalize_mode(merged.get("pasteMode")),
            "includeRom": bool(merged["includeRom"]),
            "includeMedia": bool(merged["includeMedia"]),
            "conflict": conflict,
            # 화면과 테스트가 다루기 쉽도록 중첩된 모양으로 돌려준다. 저장은 평평하게 한다(위 참고).
            "unmatchedRom": {
                "mode": mode,
                "metadata": bool(merged["unmatchedRomMetadata"]),
                "media": bool(merged["unmatchedRomMedia"]),
                "video": bool(merged["unmatchedRomVideo"]),
            },
        }

    @guarded
    def validate_plan(self, collection_id):
        plan = self._plan(collection_id)
        collection, cache, provider = self._plan_context(collection_id)
        return ok(validate(plan, collection, cache, provider))

    @guarded
    def start_apply(self, collection_id):
        """Plan을 실제 파일 변경으로 실행한다(스펙 §31).

        같은 Collection을 다른 인스턴스가 동시에 Apply하지 못하도록 프로세스 간
        락을 잡는다(§9.4). 끝나면 반드시 놓는다.
        """
        plan = self._plan(collection_id)
        if not len(plan):
            return err("적용할 Plan이 없습니다.")

        collection, cache, provider = self._plan_context(collection_id)
        archive_entries = [entry for entry in plan.entries if entry.op == OP_ARCHIVE_INGEST]
        file_entries = [entry for entry in plan.entries if entry.op != OP_ARCHIVE_INGEST]
        blocked = self._ensure_writable(collection, [entry.system for entry in file_entries])
        if blocked:
            return blocked
        if archive_entries:
            cfg = self._archive_config()
            if not archive_projection.is_configured(cfg):
                return err("Archive 디렉토리가 설정되지 않았습니다. 수집 계획을 다시 확인하세요.")
            if any((entry.source or {}).get("archiveDir") != str(cfg["archiveDir"])
                   for entry in archive_entries):
                return err("Archive 디렉토리가 바뀌었습니다. 기존 수집 계획을 지우고 다시 추가하세요.")
        report = validate(plan, collection, cache, provider)
        if report["entries"]:
            log.warning("Plan validation invalid collection=%s entries=%s", collection_id,
                        report["entries"])
        if report["blocked"]:
            return err("용량이 부족합니다. Plan을 줄이거나 저장 공간을 확보해주세요.")
        if not any(not entry.blocked and entry.status != "invalid" for entry in plan.entries):
            reason = (report["entries"][0]["error"] if report["entries"] else
                      "적용할 수 있는 Plan 항목이 없습니다.")
            return err(f"Plan을 적용할 수 없습니다: {reason}")
        archive_ready = [entry for entry in archive_entries if entry.status != "invalid"]
        archive_invalid = len(archive_entries) - len(archive_ready)

        lock_name = f"apply:{collection_id}"
        if not self.registry.acquire_lock(lock_name, kind="apply"):
            owner = self.registry.lock_owner(lock_name) or {}
            return err(f"다른 창에서 같은 Collection을 적용하는 중입니다({owner.get('instance_id', '?')[:8]}).")

        def run_archive(cb):
            try:
                current = []
                for entry in archive_ready:
                    row = cache.get_row_by_filename(entry.system, entry.filename)
                    if row is None or archive_service.ingest_fingerprint(row) != entry.source["fingerprint"]:
                        entry.status, entry.error = "invalid", "원본 항목이 바뀌었습니다. 수집 계획을 다시 만드세요."
                        raise ValueError(f"{entry.filename}: 원본 항목이 변경되어 Archive 수집을 멈췄습니다.")
                    current.append(row["rom_uid"])
                ingested = archive_service.ingest_collection(
                    self.archive, collection, cache, current,
                    progress_cb=lambda done, total, label: cb(
                        int(done * 650 / max(1, total)), 1000, label))
                self._project_archive(ingested, ingested["romIdentityIds"],
                    progress_cb=lambda done, total, label: cb(
                        650 + int(done * 350 / max(1, total)), 1000, label))
                for entry in archive_ready:
                    plan.remove(entry.key)
                cb(1000, 1000, "Archive 수집 완료")
                return {"applied": len(archive_ready), "archiveIngested": ingested["ingested"],
                        "archiveRevised": ingested["revised"], "failed": 0, "partial": 0,
                        "skipped": 0, "invalid": archive_invalid if not file_entries else 0,
                        "errors": [], "systems": []}
            except Exception:
                if file_entries:
                    self.registry.release_lock(lock_name)
                raise
            finally:
                if not file_entries:
                    self.registry.release_lock(lock_name)

        def run_files(cb):
            try:
                result = apply_plan(plan, collection, cache, self.registry, provider,
                                    progress_cb=cb, disc_titles=self._disc_title_option())
                log.info("Plan apply collection=%s applied=%s invalid=%s failed=%s partial=%s skipped=%s",
                         collection_id, result.get("applied"), result.get("invalid"),
                         result.get("failed"), result.get("partial"), result.get("skipped"))
                if result.get("systems"):
                    self.workspace.scan(collection_id, force=True, systems=result["systems"])
                    self._rebind_plan_rows(collection_id, result["systems"])
                self.registry.append_change(CHANGE_APPLIED, collection_id,
                                            {"applied": result["applied"]})
                return result
            finally:
                self.registry.release_lock(lock_name)

        phases = []
        if archive_ready:
            phases.append(("Archive 수집", run_archive))
        if file_entries:
            phases.append(("Collection 적용", run_files))
        def combine(previous, current):
            if previous is None:
                return current
            return {**current,
                    **{key: int(previous.get(key) or 0) + int(current.get(key) or 0)
                       for key in ("applied", "failed", "partial", "skipped", "invalid")},
                    "archiveIngested": previous.get("archiveIngested", 0),
                    "archiveRevised": previous.get("archiveRevised", 0),
                    "errors": previous.get("errors", []) + current.get("errors", []),
                    "systems": sorted(set(previous.get("systems", [])) | set(current.get("systems", [])))}
        job_id = self.jobs.run_phased((collection_id,), phases, kind="apply",
                                     combine_results=combine, attach_followup_job_id=True)
        return ok({"jobId": job_id})

    # ------------------------------------------------------------------
    # Archive (스펙 §37-44)
    # ------------------------------------------------------------------
    @guarded
    @archive_write
    def archive_ingest(self, collection_id, rom_uids=None, scope=None):
        """동기 수집. 프로그램 호출과 테스트용이다.

        **화면은 이 경로를 쓰지 않는다** - GUI는 `plan_archive_ingest()`로 scope를
        명시해서 Plan에 담는다. 여기서 `rom_uids=None`을 전체로 보는 것은 호출부가 대상을
        직접 나열하는 프로그램 경로에서만 통하는 편의다.
        """
        collection, cache, _ = self._plan_context(collection_id)
        if scope is not None:
            _kind, rom_uids = archive_service.resolve_scope(cache, scope)
        return ok(archive_service.ingest_collection(self.archive, collection, cache, rom_uids))

    @guarded
    def archive_ingest_preview(self, collection_id, scope=None):
        """이 scope로 수집하면 몇 개가 들어가는지. 버튼 라벨과 확인용이다."""
        _collection, cache, _ = self._plan_context(collection_id)
        kind, uids = archive_service.resolve_scope(cache, scope)
        return ok({"kind": kind, "count": len(uids),
                   "system": (scope or {}).get("system")})

    @guarded
    def plan_archive_ingest(self, collection_id, scope):
        """Archive 수집 대상을 Collection Plan에 올린다. 실제 Revision은 Apply에서 기록한다."""
        cfg = self._archive_config()
        if not archive_projection.is_configured(cfg):
            return err("Archive 디렉토리를 먼저 정하세요. Settings > Archive에서 저장할 폴더와 형식을 고릅니다.")
        if not isinstance(scope, dict) or scope.get("kind") not in ("all", "system", "selected"):
            return err("Archive 수집 범위를 선택하세요.")
        collection, cache, _ = self._plan_context(collection_id)
        kind, uids = archive_service.resolve_scope(cache, scope)
        plan = self._plan(collection_id)
        keys, skipped = [], []
        rows = cache.get_rows(uids)
        for uid in dict.fromkeys(uids):
            row = rows.get(int(uid))
            if row is None:
                skipped.append({"filename": str(uid), "reason": "원본 항목을 찾을 수 없습니다."})
                continue
            entry = PlanEntry(
                op=OP_ARCHIVE_INGEST, system=row["system"], filename=row["filename"],
                rom_uid=row["rom_uid"],
                source={"fingerprint": archive_service.ingest_fingerprint(row),
                        "archiveDir": str(cfg["archiveDir"]), "origin": "archive-ingest",
                        "sourceName": collection.name, "title": row["title"],
                        "metadataPresent": bool(row["fields"]),
                        "mediaCount": len(row["media"]),
                        "romPresent": bool(row["present"])},
            )
            plan.add(entry)
            keys.append(entry.key)
        return ok({"planned": len(keys), "keys": keys, "skipped": skipped, "scope": kind})

    @guarded
    def start_archive_ingest(self, collection_id, scope=None):
        """Collection의 항목을 Archive에 수집한다. 출처는 Collection ID로 남는다.

        **대상은 화면이 준 scope로만 정한다**(§13). 예전에는 선택이 없으면 `None`을
        보냈고 백엔드가 그것을 "Collection 전체"로 해석해서, MSX1만 보고 있던 사용자가
        Collection 전체를 Archive에 넣게 되었다.

        수집은 게임 수만큼 DB 쓰기가 일어나므로 job으로 돌린다 - 동기로 부르면 큰
        Collection에서 창이 멈춘 것처럼 보이고 취소할 방법도 없다.
        """
        # **Archive 디렉토리를 정하기 전에는 수집하지 않는다**(사용자 피드백 - 디렉토리를 고르지도
        # 않았는데 수집이 돌았다). 정해 두지 않으면 모은 것이 DB에만 남아, 사용자가 꺼내 쓸 수 있는
        # Frontend 트리가 어디에도 만들어지지 않는다(docs/ARCHIVE_DIRECTORY_DESIGN.md).
        if not archive_projection.is_configured(self._archive_config()):
            return err("Archive 디렉토리를 먼저 정하세요. Settings > Archive에서 저장할 폴더와 형식을 고릅니다.")
        collection, cache, _ = self._plan_context(collection_id)
        kind, uids = archive_service.resolve_scope(cache, scope)
        log.info("archive ingest requested: collection=%s scope=%s system=%s targets=%d",
                 collection_id, kind, (scope or {}).get("system"), len(uids))

        def run(cb):
            with archive_writing(self._archive_config()["archiveDir"]):
                result = self._archive_ingest_job(collection, cache, uids, cb)["data"]
                log.info("archive ingest done: scope=%s requested=%d ingested=%d",
                         kind, len(uids), len(result["ingestedRomUids"]))
                # **cb를 여기도 넘긴다.** 안 넘기면 DB 수집이 끝나 진행률이 100%를 찍은 뒤에도
                # gamelist.xml/media 쓰기가 조용히 이어져서(전송량이 큰 Archive는 이 단계가
                # 더 오래 걸린다), 막대는 100%에서 멈춘 것처럼 보이고 취소도 다음 progress_cb
                # 호출까지 반영되지 않아 안 먹는 것처럼 보였다(실사용 버그 리포트).
                return {**result, "scope": kind}

        job_id = self.jobs.run_heavy(run, mutates_state=True, target_ids=(collection_id,),
                                     kind="archive-ingest")
        return ok({"jobId": job_id, "count": len(uids), "scope": kind})

    @archive_write
    def _archive_ingest_job(self, collection, cache, uids, progress):
        result = archive_service.ingest_collection(self.archive, collection, cache, uids, progress_cb=progress)
        projected = self._project_archive(result, result["romIdentityIds"], progress_cb=progress)
        return ok({**result, "projection": projected})

    @guarded
    def archive_rows(self, search=None, systems=None, limit=200, offset=0, conflicts_only=False,
                     favorites_only=False, rom_identity_ids=None, priority=None,
                     order="title", descending=False):
        """Archive Gamelist. Collection 목록과 같은 모양으로 돌려준다(§43).

        Description/Genre/Rating은 `rom_identities`가 아니라 Revision의
        `fields_json`에 있다 - 여기서 안 채우면 화면은 Metadata 탭에는 값이
        보이는데 목록의 Description 칸만 늘 비어 있게 된다. Detail이 보여주는
        값과 같아야 하므로 `resolve_fields()`로 같은 우선순위(Preferred →
        Archive 편집 → Latest)를 쓴다.
        """
        started_at = time.perf_counter()
        query = {"search": search or None, "systems": systems or None}
        # 특정 항목만 다시 읽는다 - Archive에서 뭔가 바꾼 뒤 그 줄만 갱신할 때 쓴다.
        # 행을 만드는 코드가 여기 한 곳뿐이어야 목록과 갱신이 어긋나지 않는다.
        if rom_identity_ids is not None:
            query["only_ids"] = [str(i) for i in rom_identity_ids]
        if conflicts_only:
            # 사용자 결정 - "유사롬만 골라서 볼 수 있는 filter". 내용이 실제로 다른 것(=`[n]`이 붙는 것)만
            # 남긴다 - 고를 것이 있는 항목만 보여야 정리할 때 뜻이 있다.
            query["only_ids"] = list(conflict_service.conflict_counts(
                self.archive, systems=systems or None))
        # **즐겨찾기는 Metadata 안에 있다**(frontend_raw의 `<favorite>`) - 별도 컬럼으로
        # 복제하지 않는다(사용자 결정 - "DB는 gamelist가 못 담는 것만"). 그래서 SQL로는
        # 못 거르고 resolve 뒤에 거른다. 사용자 DB(identity 2,992개)에서 전체 resolve가
        # 0.28초라 페이지를 나누기 전에 걸러도 목록이 느려지지 않는다(실측).
        favorites_only = bool(favorites_only)
        page = (None, 0) if favorites_only else (int(limit), int(offset))
        rows = self.archive.list_rows(**query, limit=page[0], offset=page[1], priority=priority,
                                      order=order, descending=bool(descending))
        listing_seconds = time.perf_counter() - started_at
        archive_cfg = self._archive_config()
        adapter = get_adapter(archive_cfg["frontend"])
        row_ids = [str(row["rom_identity_id"]) for row in rows]
        metadata_by_id = self.archive.resolve_fields_many(row_ids)
        rom_sources_by_id = self.archive.rom_sources_many(row_ids)
        resolve_seconds = time.perf_counter() - started_at - listing_seconds
        out_rows = []
        for r in rows:
            rid = str(r["rom_identity_id"])
            media_types = set(filter(None, (r["media_types"] or "").split(",")))
            fields, raw = metadata_by_id.get(rid, ({}, {}))
            starred = adapter.is_favorite(raw)
            if favorites_only and not starred:
                continue
            rom_ownership = self._rom_ownership_from_sources(
                rom_sources_by_id.get(rid, []), archive_cfg, check_exists=False)
            out_rows.append({
                "romUid": r["rom_identity_id"], "romIdentityId": r["rom_identity_id"],
                "system": r["system"], "file": r["filename"],
                "title": (Path(r["filename"] or "").stem if r["metadata_cleared"]
                          else fields.get("name") or r["title"]),
                "sources": r["source_count"], "updatedAt": r["updated_at"],
                # 예전에는 False로 박아뒀다. Archive에 media가 저장돼 있어도
                # 목록에서는 영영 없는 것으로 보였다.
                "hasMetadata": any(v is not None and str(v).strip() for v in fields.values()),
                "hasMedia": bool(media_types),
                "rom": "ok" if r["rom_count"] else "none",
                "metaLevel": ("ok" if fields.get("name") and fields.get("desc")
                              else "partial" if fields.get("name") or fields.get("desc") else "none"),
                "mediaLevel": ("ok" if set(KEY_MEDIA_TYPES).issubset(media_types)
                               else "partial" if media_types else "none"),
                "videoLevel": "ok" if "videos" in media_types else "none",
                # Metadata(frontend_raw)에 있는 별표를 그대로 읽는다.
                "favorite": starred,
                # ROM 위치가 기록돼 있으면 있는 것으로 본다. 없으면 메타데이터만 있는
                # 항목이다(ROM only/Metadata only 표시는 화면이 이 값으로 가른다).
                "present": bool(r["rom_count"]), "size": 0,
                "storageId": "archive",
                "desc": fields.get("desc") or "",
                "region": r["region"] or fields.get("region") or "",
                "genre": fields.get("genre") or "",
                "rating": fields.get("rating") or "",
                # 목록 메뉴가 외부 연결 ROM을 물리적으로 지우지 않도록, ROM 경로
                # 소유권만 가볍게 함께 준다. Media 전체 판정은 상세에서 계산한다.
                "ownership": {"rom": {key: value for key, value in rom_ownership.items()
                                        if key != "items"}},
            })
        if favorites_only:
            # 전부 걸러낸 뒤 여기서 페이지를 나눈다 - 필터가 SQL 밖에 있으므로
            # LIMIT/OFFSET도 여기서 맞춰야 개수와 페이지가 어긋나지 않는다.
            total = len(out_rows)
            out_rows = out_rows[int(offset):int(offset) + int(limit)]
        else:
            total = self.archive.count_rows(**query)
        log.info("Archive rows: offset=%s limit=%s rows=%s total=%s list=%.3fs resolve=%.3fs rest=%.3fs",
                 offset, limit, len(out_rows), total, listing_seconds, resolve_seconds,
                 time.perf_counter() - started_at - listing_seconds - resolve_seconds)
        return ok({"rows": out_rows, "total": total, "offset": int(offset)})

    @guarded
    def archive_uids(self, systems=None):
        """지금 필터(System)에 맞는 Archive 항목 전체의 romIdentityId.

        HERO의 "메타데이터 가져오기"가 쓴다(§4) - Archive에서 이 Collection으로
        당겨올 대상을 정할 때, 화면에 보이는 첫 페이지(archive_rows의 limit=200)만
        가져오면 Archive가 그보다 크면 뒷부분이 조용히 빠진다. list_rows(limit=None)은
        LIMIT 절 자체를 안 붙이므로 전부 온다.
        """
        if isinstance(systems, dict):
            query = systems
            result = self.archive_rows(
                search=query.get("search"), systems=query.get("systems"),
                favorites_only=query.get("favoritesOnly", False),
                conflicts_only=query.get("conflictsOnly", False), limit=10_000_000,
                order=query.get("order") or "title", descending=query.get("descending", False),
                priority=query.get("priority"))
            return result if not result.get("ok") else ok(
                [row["romIdentityId"] for row in result["data"]["rows"]])
        rows = self.archive.list_rows(systems=systems or None, limit=None)
        return ok([r["rom_identity_id"] for r in rows])

    @guarded
    def archive_find_row_index(self, query, prefix, after=-1):
        """Find the next filename initial across the full filtered Archive list."""
        query = query or {}
        needle = str(prefix or "").lower()
        if not needle:
            return ok(-1)
        if query.get("favoritesOnly"):
            # Favorite lives in frontend_raw; this filter needs resolved rows.
            result = self.archive_rows(
                search=query.get("search"), systems=query.get("systems"),
                favorites_only=True, conflicts_only=query.get("conflictsOnly", False),
                limit=10_000_000, order=query.get("order") or "title",
                descending=query.get("descending", False), priority=query.get("priority"))
            if not result.get("ok"):
                return result
            filenames = [row["file"] for row in result["data"]["rows"]]
        else:
            only_ids = (list(conflict_service.conflict_counts(
                self.archive, systems=query.get("systems") or None))
                        if query.get("conflictsOnly") else None)
            rows = self.archive.list_rows(
                search=query.get("search"), systems=query.get("systems"),
                only_ids=only_ids, limit=None, order=query.get("order") or "title",
                descending=bool(query.get("descending")), priority=query.get("priority"))
            filenames = [row["filename"] for row in rows]
        if not filenames:
            return ok(-1)
        start = int(after)
        for step in range(1, len(filenames) + 1):
            index = (start + step) % len(filenames)
            if str(filenames[index] or "").lower().startswith(needle):
                return ok(index)
        return ok(-1)

    @guarded
    def archive_copy_selection(self, rom_identity_ids):
        """Copy Archive items to the same handoff clipboard Collections use.

        Reading a linked asset is allowed.  Archive-owned paths are preferred
        when both an owned copy and an external source exist.
        """
        cfg = self._archive_config()
        items = []
        for rid in [str(value) for value in (rom_identity_ids or [])]:
            identity = self.archive.get_identity(rid)
            if identity is None:
                continue
            fields, raw = self.archive.resolve_fields(rid)
            ownership = self._archive_rom_ownership(rid, cfg)
            rom_item = next((item for item in ownership["items"]
                             if item["mode"] == "internal" and item["present"]), None)
            if rom_item is None:
                rom_item = next((item for item in ownership["items"] if item["present"]), None)
            rom = None
            if rom_item:
                path = Path(rom_item["path"])
                try:
                    rom = {"path": str(path), "size": int(path.stat().st_size)}
                except OSError:
                    rom = None

            media = []
            for media_type, ref in archive_projection.effective_media(self.archive, rid).items():
                path = self._archive_media_display_path(rid, media_type, ref, cfg=cfg)
                if path and Path(path).is_file():
                    try:
                        size = int(Path(path).stat().st_size)
                    except OSError:
                        continue
                    media.append({"type": media_type, "path": str(path), "size": size})
            items.append({
                "system": identity["system"],
                "filename": identity["filename"] or identity["filename_norm"],
                "rom": rom, "media": media, "fields": fields, "frontend_raw": raw,
            })
        if not items:
            return err("복사할 Archive 항목을 찾을 수 없습니다.")
        return ok(clipboard.write_items(
            self.registry, items, self._clipboard_dir,
            source_collection_id="__archive__", source_name="Archive"))

    @guarded
    def archive_clipboard_system_target(self, system):
        """Preview a new-only paste into an Archive System."""
        cfg = self._archive_config()
        target = normalize_system(cfg["frontend"], str(system or "").strip())
        if not target or Path(target).name != target:
            return err("안전하지 않은 System 이름입니다.")
        _descriptor, source_items = clipboard.read_items(self.registry)
        items, duplicates = [], []
        for item in source_items:
            filename = str(item.get("filename") or "")
            if not filename or Path(filename).name != filename:
                continue
            entry = {"system": target, "filename": filename,
                     "title": (item.get("fields") or {}).get("name") or filename}
            (duplicates if self.archive.find_rom_identity(target, filename) else items).append(entry)
        return ok({"system": target, "items": items, "duplicates": duplicates})

    @guarded
    @archive_write
    def archive_paste(self, mode=None, target_rom_identity_id=None, target_system=None,
                      new_only=False, immediate=False):
        """Paste handoff items into Archive using the shared transfer policy.

        ROM bytes are internalized under Archive's configured ROM root and are
        never overwritten.  Media follows ``mediaInternal`` through the normal
        projection path; with it disabled the source remains a read-only link.
        """
        cfg = self._archive_config()
        if not archive_projection.is_configured(cfg):
            return err("Archive 디렉토리를 먼저 설정하세요.")
        descriptor, source_items = clipboard.read_items(self.registry)
        if not source_items:
            return err("붙여넣을 항목이 없습니다.")
        if descriptor.get("cut"):
            if not immediate or target_rom_identity_id or (mode and transfer.normalize_mode(mode) != transfer.MODE_OVERWRITE):
                return err("잘라낸 게임은 대상 System에 붙여넣으세요.")
            from app.archive import move as archive_move
            mapping = {item["system"]: target_system for item in source_items} if target_system else None
            return ok(archive_move.prepare(self, "__archive__", descriptor, source_items, mapping))
        if immediate:
            preview = archive_paste_service.prepare(
                self.archive, cfg, source_items, mode,
                target_id=target_rom_identity_id, target_system=target_system,
                new_only=bool(new_only))
            if not preview["prepared"]:
                return ok({"count": 0, "skipped": preview["skipped"]})
            operation_id = uuid.uuid4().hex
            if len(self._paste_ops) >= 20:
                self._paste_ops.pop(next(iter(self._paste_ops)))
            self._paste_ops[operation_id] = {
                **preview, "target": "archive", "config": dict(cfg),
                "collectionId": "__archive__", "undoable": True}
            return ok({"operationId": operation_id, "target": "archive",
                       "source": descriptor.get("sourceName"),
                       "count": len(preview["prepared"]), "undoable": self._paste_ops[operation_id]["undoable"],
                       "collisions": preview["collisions"], "skipped": preview["skipped"]})
        return self._archive_paste_items(
            cfg, source_items, mode, target_rom_identity_id, target_system, new_only)

    def _archive_paste_items(self, cfg, source_items, mode=None,
                             target_rom_identity_id=None, target_system=None,
                             new_only=False, progress_cb=None):
        log.info("Archive paste requested mode=%s items=%d targetSystem=%s targetRow=%s newOnly=%s",
                 mode, len(source_items), target_system, target_rom_identity_id, new_only)
        if target_rom_identity_id and len(source_items) != 1:
            return err("항목을 하나만 복사했을 때만 이 항목으로 붙여넣을 수 있습니다.")
        if target_rom_identity_id and target_system:
            return err("게임과 System을 동시에 붙여넣기 대상으로 지정할 수 없습니다.")
        mapped_system = (normalize_system(cfg["frontend"], str(target_system).strip())
                         if target_system else None)
        if mapped_system and (Path(mapped_system).name != mapped_system
                              or not _path_within(Path(cfg["romDir"] or cfg["archiveDir"])
                                                  / mapped_system,
                                                  Path(cfg["romDir"] or cfg["archiveDir"]))):
            return err("안전하지 않은 System 이름입니다.")

        target_identity = (self.archive.get_identity(str(target_rom_identity_id))
                           if target_rom_identity_id else None)
        if target_rom_identity_id and target_identity is None:
            return err("붙여넣을 Archive 항목을 찾을 수 없습니다.")

        rom_root = Path(cfg["romDir"] or cfg["archiveDir"])
        normalized_mode = transfer.normalize_mode(mode)
        downgraded_from = None
        pasted = copied_roms = 0
        skipped, conflicts, changed_ids, record_ids = [], [], [], []
        overwrite_media = {}

        for source_item in source_items:
            item = dict(source_item)
            if target_identity:
                target_filename = target_identity["filename"] or target_identity["filename_norm"]
                if str(item.get("filename") or "") != str(target_filename):
                    # A ROM must not be renamed to another extension/region merely
                    # because the user targets a different metadata row.
                    item["rom"] = None
                item["system"] = target_identity["system"]
                item["filename"] = target_filename
                identity = target_identity
            else:
                item["system"] = mapped_system or normalize_system(
                    cfg["frontend"], item.get("system") or "")
                identity = self.archive.find_rom_identity(item["system"], item.get("filename") or "")

            filename = str(item.get("filename") or "")
            system = str(item.get("system") or "")
            if not filename or Path(filename).name != filename or not system:
                skipped.append({"filename": filename, "reason": "안전하지 않은 System 또는 파일명입니다."})
                continue
            if not _path_within(rom_root / system, rom_root):
                skipped.append({"filename": filename, "reason": "Archive 경로 밖의 System은 사용할 수 없습니다."})
                continue
            if new_only and identity is not None:
                skipped.append({"filename": filename, "reason": "대상 System에 같은 게임이 이미 있습니다."})
                continue

            existing = None
            if identity:
                existing_fields, existing_raw = self.archive.resolve_fields(identity["rom_identity_id"])
                existing_media = [
                    {**media, "rel_path": media.get("abs_path")}
                    for media in archive_projection.effective_media(
                        self.archive, identity["rom_identity_id"]).values()]
                existing = {
                    "system": identity["system"],
                    "filename": identity["filename"] or identity["filename_norm"],
                    "present": any(Path(source["abs_path"]).is_file()
                                   for source in self.archive.rom_sources(identity["rom_identity_id"])
                                   if source.get("abs_path")),
                    "fields": existing_fields, "frontend_raw": existing_raw,
                    "media": existing_media,
                }
            prepared, reason = transfer.decide(
                item, existing, normalized_mode,
                allow_rom_replace=bool(current_transaction()) and normalized_mode == transfer.MODE_REPLACE,
                force_media=normalized_mode == transfer.MODE_REPLACE)
            if prepared is None:
                skipped.append({"filename": filename, "reason": reason})
                continue

            fields = prepared.get("fields") or {}
            raw = prepared.get("frontend_raw") or {}
            if identity is None:
                title = (fields.get("name") or "").strip() or Path(filename).stem
                game_id = self.archive.ensure_game(title, normalize_title(title))
                rid = self.archive.ensure_rom_identity(
                    game_id, system, normalize_title(Path(filename).stem), filename=filename,
                    size=int((prepared.get("rom") or {}).get("size") or 0) or None,
                    region=fields.get("region"), title=(fields.get("name") or None))
            else:
                rid = identity["rom_identity_id"]

            rom = prepared.get("rom")
            if rom and rom.get("path") and Path(rom["path"]).is_file():
                destination = rom_root / system / filename
                if not _path_within(destination, rom_root):
                    skipped.append({"filename": filename, "reason": "Archive ROM 경로 밖으로 복사할 수 없습니다."})
                    continue
                if destination.exists() and Path(rom["path"]).resolve() != destination.resolve():
                    if normalized_mode == transfer.MODE_REPLACE and current_transaction():
                        archive_copy_complete(rom["path"], destination, replace=True, move_backup=True)
                        copied_roms += 1
                        self.archive.put_rom_source(rid, archive_directory.DIRECTORY_SOURCE, destination, destination.stat().st_size)
                    else:
                        conflicts.append({"filename": filename, "path": str(destination),
                                          "reason": "Archive ROM 파일이 이미 있어 덮어쓰지 않았습니다."})
                else:
                    if not destination.exists():
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        archive_copy_complete(rom["path"], destination)
                        copied_roms += 1
                    self.archive.put_rom_source(
                        rid, archive_directory.DIRECTORY_SOURCE, destination,
                        int(destination.stat().st_size))

            media_state = self._archive_edit_media_state(rid)
            changed_types = set()
            for media in prepared.get("media") or []:
                media_type = media.get("type") or media.get("media_type")
                source = media.get("path") or media.get("abs_path")
                if not media_type or not source or not Path(source).is_file():
                    continue
                stat = Path(source).stat()
                self.archive.put_media_ref(rid, media_type, ARCHIVE_EDIT_SOURCE,
                                           source, stat.st_size)
                media_state[media_type] = {
                    "media_type": media_type, "abs_path": str(source),
                    "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "state": "present",
                }
                changed_types.add(media_type)

            self.archive.put_record(rid, ARCHIVE_EDIT_SOURCE, fields, raw,
                                    media=list(media_state.values()))
            if fields or raw:
                self.archive.set_metadata_cleared(rid, False)
            latest = self.archive.latest_record(rid, ARCHIVE_EDIT_SOURCE)
            if latest:
                record_ids.append(latest["record_id"])
            if changed_types:
                overwrite_media[rid] = changed_types
            changed_ids.append(rid)
            pasted += 1

        projection = self._project_archive(
            {"revisionRecordIds": record_ids}, changed_ids,
            overwrite_media=overwrite_media, progress_cb=progress_cb) if changed_ids else None
        log.info("Archive paste completed pasted=%d romsCopied=%d skipped=%d conflicts=%d",
                 pasted, copied_roms, len(skipped), len(conflicts))
        return ok({"pasted": pasted, "copiedRoms": copied_roms,
                   "policy": {"pasteMode": normalized_mode},
                   "downgradedFrom": downgraded_from,
                   "skipped": skipped, "conflicts": conflicts, "projection": projection})

    def _execute_archive_paste_operation(self, operation_id, op, decisions, acknowledged):
        if not op["undoable"] and not acknowledged:
            return err("마스터 붙여넣기의 파일 복원은 아직 보장하지 못합니다. 실행 전 확인이 필요합니다.")
        if op["config"] != self._archive_config():
            return err("마스터 디렉토리 설정이 바뀌었습니다. 다시 붙여넣으세요.")
        if not archive_paste_service.unchanged(self.archive, op):
            return err("마스터의 대상 게임이 바뀌었습니다. 다시 붙여넣으세요.")
        expected = {item["key"] for item in op["collisions"]}
        if any(decisions.get(key) not in {"overwrite", "skip"} for key in expected):
            return err("충돌한 게임마다 덮어쓰기 또는 건너뛰기를 선택하세요.")
        selected = [item for item in op["prepared"]
                    if decisions.get(transfer.item_key(item)) != "skip"]
        if not selected:
            self._paste_ops.pop(operation_id, None)
            return ok({"jobId": None, "skipped": len(expected)})
        def run(progress):
            with archive_writing(self._archive_config()["archiveDir"]):
                with self._archive_lifecycle_lock, self.archive._conn.lock:
                    if self._archive_recovery_error:
                        raise ValueError(self._archive_recovery_error)
                    if op["config"] != self._archive_config():
                        raise ValueError("Archive 설정이 바뀌었습니다. 다시 붙여넣으세요.")
                    cfg = op["config"]
                    shared = archive_shared_cache.snapshot_path(cfg["archiveDir"])
                    known = self.registry.get_setting("archive.shared_snapshot_hashes", {}) or {}
                    current = archive_shared_cache.fingerprint(shared) if shared.is_file() else None
                    if current != known.get(cfg["archiveDir"]):
                        raise ValueError("다른 PC에서 Archive가 바뀌었습니다. 새로고침 후 다시 붙여넣으세요.")
                    if not archive_paste_service.unchanged(self.archive, op):
                        raise ValueError("마스터의 대상 게임이 바뀌었습니다. 다시 붙여넣으세요.")
                    tx = self._archive_journal.begin(operation_id, self.archive, op["config"],
                        [item["system"] for item in selected], allow_network=True) if op["undoable"] else None
                    from contextlib import nullcontext
                    try:
                        with tx.tracking() if tx else nullcontext():
                            result = self._archive_paste_items(
                                op["config"], selected, op["mode"], progress_cb=progress)
                        if not result["ok"]:
                            raise ValueError(result["error"])
                        data = result["data"]
                        projected = data.get("projection") or {}
                        incomplete = (projected.get("error") or projected.get("mediaMissing") or
                                      (projected.get("sharedSnapshot") or {}).get("status")
                                      in {"error", "conflict"})
                        if tx and incomplete:
                            raise ValueError("Archive 파일 또는 공유 DB를 모두 반영하지 못했습니다.")
                        if tx:
                            tx.commit(self.archive)
                        return {"applied": data["pasted"], "failed": 0,
                                "partial": data["pasted"] if incomplete else 0,
                                "undoOperationId": operation_id if tx else None, "archive": data}
                    except BaseException:
                        if tx:
                            try:
                                tx.failed(self.archive)
                                tx.restore(self.archive)
                                self._remember_archive_digest(op["config"])
                            except Exception as exc:
                                self._archive_recovery_error = str(exc)
                                log.exception("Archive paste rollback blocked operation=%s; backups retained", operation_id)
                        raise
        self._paste_ops.pop(operation_id, None)
        job_id = self.jobs.run_heavy(run, mutates_state=True,
                                     target_ids=("archive",), kind="archive-paste")
        return ok({"jobId": job_id})

    @guarded
    def archive_systems(self):
        return ok(self.archive.systems())

    def _archive_rom_ownership(self, rom_identity_id, cfg=None, *, check_exists=True) -> dict:
        """Classify recorded ROM paths by the configured Archive ROM root."""
        cfg = cfg or self._archive_config()
        return self._rom_ownership_from_sources(
            self.archive.rom_sources(rom_identity_id), cfg, check_exists=check_exists)

    @staticmethod
    def _rom_ownership_from_sources(sources, cfg, *, check_exists=True) -> dict:
        root = (cfg.get("romDir") or cfg.get("archiveDir")) if cfg else None
        # Gamelist status is informational. Resolving every ROM and the root
        # on a network drive made each 200-row scroll page wait for filesystem
        # round trips. File operations still use _path_within() with resolve().
        display_root = os.path.normcase(os.path.abspath(root)) if root and not check_exists else None
        items = []
        for source in sources:
            path = source.get("abs_path")
            if display_root and path:
                display_path = os.path.normcase(os.path.abspath(path))
                try:
                    internal = os.path.commonpath((display_root, display_path)) == display_root
                except ValueError:
                    internal = False
            else:
                internal = _path_within(path, root) if check_exists else False
            items.append({
                "sourceCollectionId": source.get("source_collection_id"),
                "path": path,
                "mode": "internal" if internal else "linked",
                "present": bool(path and (Path(path).is_file() if check_exists else True)),
            })
        internal_count = sum(item["mode"] == "internal" for item in items)
        linked_count = sum(item["mode"] == "linked" for item in items)
        mode = ("mixed" if internal_count and linked_count else
                "internal" if internal_count else "linked" if linked_count else "none")
        return {"mode": mode, "internalCount": internal_count,
                "linkedCount": linked_count, "items": items}

    def _archive_media_ownership(self, rom_identity_id, cfg=None, *, check_exists=True) -> dict:
        """Classify each effective media type by the file Archive displays."""
        cfg = cfg or self._archive_config()
        root = cfg.get("archiveDir") if cfg else None
        types = {}
        for media_type, item in archive_projection.effective_media(
                self.archive, rom_identity_id).items():
            display_path = self._archive_media_display_path(
                rom_identity_id, media_type, item, require_exists=False, cfg=cfg)
            internal = _path_within(display_path, root)
            types[media_type] = {
                "mode": "internal" if internal else "linked",
                "path": display_path,
                "bytes": int(item.get("size") or 0),
                "present": bool(display_path and (Path(display_path).is_file()
                                                    if check_exists else True)),
            }
        internal_count = sum(item["mode"] == "internal" for item in types.values())
        linked_count = sum(item["mode"] == "linked" for item in types.values())
        mode = ("mixed" if internal_count and linked_count else
                "internal" if internal_count else "linked" if linked_count else "none")
        return {"mode": mode, "internalCount": internal_count,
                "linkedCount": linked_count, "types": types}

    def _archive_ownership(self, rom_identity_id, cfg=None, *, check_exists=True) -> dict:
        cfg = cfg or self._archive_config()
        rom = self._archive_rom_ownership(rom_identity_id, cfg, check_exists=check_exists)
        media = self._archive_media_ownership(rom_identity_id, cfg, check_exists=check_exists)
        modes = {part["mode"] for part in (rom, media) if part["mode"] != "none"}
        mode = ("mixed" if len(modes) > 1 or "mixed" in modes else
                next(iter(modes)) if modes else "none")
        return {"mode": mode, "rom": rom, "media": media,
                # Metadata revisions and direct edits always live in Archive.
                "metadata": {"mode": "internal"}}

    @guarded
    def archive_ownership_summary(self):
        counts = {"internal": 0, "linked": 0, "mixed": 0, "none": 0}
        cfg = self._archive_config()
        for row in self.archive.list_rows(limit=None):
            mode = self._archive_ownership(
                row["rom_identity_id"], cfg, check_exists=False)["mode"]
            counts[mode] = counts.get(mode, 0) + 1
        return ok({**counts, "total": sum(counts.values())})

    @guarded
    def archive_detail(self, rom_identity_id):
        data = archive_service.detail(self.archive, rom_identity_id)
        if not data:
            return err("Archive 항목을 찾을 수 없습니다.")
        # 별표는 Metadata(frontend_raw) 안에 있다 - DB에 따로 두지 않으므로 읽을 때
        # 꺼낸다. Frontend마다 태그가 다르므로 Archive 설정의 Adapter에게 묻는다.
        adapter = get_adapter(self._archive_config()["frontend"])
        data["favorite"] = adapter.is_favorite(data.get("frontendRaw"))
        # 보관 파일과 외부 연결을 가리지 않고 실제 ROM이 하나라도 있는지 알려준다.
        # 이 값은 Play/Core 제어의 공통 차단 조건에도 쓰인다.
        data["present"] = any(Path(source["abs_path"]).is_file()
                               for source in data.get("romSources", [])
                               if source.get("abs_path"))
        data["ownership"] = self._archive_ownership(rom_identity_id)
        return ok(data)

    @guarded
    def archive_system_folder(self, system, kind):
        """설정된 Archive 투영 트리 또는 원본 미디어의 System 폴더를 연다."""
        cfg = self._archive_config()
        if not archive_projection.is_configured(cfg):
            return err("Archive 디렉터리를 먼저 설정하세요.")
        system = str(system or "")
        known_systems = {row["system"] for row in self.archive.systems()}
        if system not in known_systems:
            return err(f"Archive에 없는 System입니다: {system}")
        adapter = get_adapter(cfg["frontend"])
        layout = adapter.layout(archive_projection.collection_for(cfg), system)
        if kind == "rom":
            path = Path(cfg["romDir"] or cfg["archiveDir"]) / system
        elif kind == "metadata":
            path = Path(layout.metadata_file).parent
        elif kind == "media":
            if cfg["mediaInternal"]:
                path = Path(layout.media_dir)
            else:
                path = None
                for row in self.archive.list_rows(systems=[system], limit=None):
                    for item in archive_projection.effective_media(
                            self.archive, row["rom_identity_id"]).values():
                        resolved = self._archive_media_display_path(
                            row["rom_identity_id"], item["media_type"], item)
                        if resolved and Path(resolved).is_file():
                            path = Path(resolved).parent
                            break
                    if path is not None:
                        break
                if path is None:
                    return err(f"{system}에 열 수 있는 Media 파일이 없습니다.")
        else:
            return err(f"알 수 없는 Archive 폴더 종류입니다: {kind}")
        if not path.is_dir():
            return err(f"폴더가 없습니다: {path}")
        _reveal_path(str(path))
        return ok({"path": str(path)})

    @guarded
    def get_archive_media_image(self, rom_identity_id, media_label, thumbnail=False):
        """Archive 항목의 media 이미지.

        Collection용 `get_media_image()`는 `collection_id` + `rom_uid`로 Cache를 뒤진다.
        Archive에는 그 둘 다 없다(식별자가 rom_identity_id다). 그래서 화면이 Archive
        탭에서도 Collection용 경로를 부르고 있었고, 조회가 조용히 실패해서 **Archive에
        media가 저장되어 있는데도 영영 보이지 않았다.**

        mediaInternal 설정에 따라 Archive 복사본 또는 외부 원본을 표시한다. 선택된
        경로가 사라졌으면 그 media만 건너뛴다.
        """
        media_type = MEDIA_KEYS.get(media_label, str(media_label).lower())
        item = archive_projection.effective_media(self.archive, rom_identity_id).get(media_type)
        if item is None:
            return ok(None)
        path = self._archive_media_display_path(rom_identity_id, media_type, item)
        return ok(self._encode_image(path, THUMBNAIL_MAX if thumbnail else None) if path else None)

    def _archive_media_display_path(self, rom_identity_id, media_type, item, *,
                                    require_exists=True, cfg=None):
        """Resolve the Archive's own frontend media copy when configured.

        With mediaInternal disabled, Archive displays the source Collection file.
        With it enabled, the configured Archive frontend tree is the source of
        truth for display and export.
        """
        cfg = cfg or self._archive_config()
        if not archive_projection.is_configured(cfg):
            return item.get("abs_path")
        if not cfg["mediaInternal"]:
            # Revision snapshots may live under .rms even after the user turns
            # internal media off.  In reference mode, resolve back to the
            # compatibility index that still records the Collection source.
            source_id = item.get("source_collection_id")
            original = next((ref for ref in self.archive.media_refs(rom_identity_id)
                             if ref.get("media_type") == media_type
                             and ref.get("source_collection_id") == source_id), None)
            return (original or item).get("abs_path")
        identity = self.archive.get_identity(rom_identity_id)
        if not identity:
            return None
        adapter = get_adapter(cfg["frontend"])
        layout = adapter.layout(archive_projection.collection_for(cfg), identity["system"])
        fields, _raw = self.archive.resolve_fields(rom_identity_id)
        filename = identity["filename"] or identity["filename_norm"]
        media = MediaFile(media_type=media_type, path=item["abs_path"],
                          size=int(item.get("size") or 0))
        for _src, dest in adapter.media_pairs(layout, filename, [media],
                                             title=(fields.get("name") or None)):
            if not require_exists or Path(dest).is_file():
                return dest
        return None

    @guarded
    def get_archive_version_media_image(self, rom_identity_id, source_collection_id, media_label,
                                        thumbnail=False, record_id=None):
        """`get_archive_media_image()`와 같지만 **정해진(preferred) 것이 아니라 특정
        출처의 것**을 돌려준다. 서로 다른 버전(§16)을 고르는 화면에서 "그 출처가 가진
        그림"을 실제로 보여줘야 문장(크기/일치율)만으로 못 하는 판단(둘이 진짜 같은
        그림인지)을 사람이 눈으로 할 수 있다(실사용 피드백 - "conflict 내용을 보니
        크기도 같다"는데도 문장만으로는 확인할 방법이 없었다)."""
        media_type = MEDIA_KEYS.get(media_label, str(media_label).lower())
        item = None
        if record_id is not None:
            record = self.archive.record_by_id(int(record_id))
            if record and record["rom_identity_id"] == str(rom_identity_id):
                item = next((m for m in self.archive.media_of_revision(record_id)
                             if m["media_type"] == media_type), None)
        if item is None:
            item = next((m for m in self.archive.media_refs(rom_identity_id)
                         if m["media_type"] == media_type
                         and m["source_collection_id"] == source_collection_id), None)
        if item is None:
            return ok(None)
        # Revision tiles must show that Revision's immutable snapshot. Resolving
        # through the current frontend projection would make every historical
        # version display the latest image instead.
        path = (item.get("abs_path") if record_id is not None
                else self._archive_media_display_path(rom_identity_id, media_type, item))
        return ok(self._encode_image(path, THUMBNAIL_MAX if thumbnail else None) if path else None)

    @guarded
    def get_archive_media_video_url(self, rom_identity_id):
        """Archive 항목의 영상 URL - 설정에 따라 자체 copy 또는 source를 쓴다."""
        item = next((m for m in self.archive.media_refs(rom_identity_id)
                     if m["media_type"] == VIDEO_MEDIA_TYPE), None)
        path = self._archive_media_display_path(rom_identity_id, VIDEO_MEDIA_TYPE, item) if item else None
        url = self._media_server.url_for(path) if path else None
        return ok({"url": url} if url else None)

    ARCHIVE_CONFIG_KEY = "archive.config"

    def _remember_archive_digest(self, cfg):
        directory = cfg["archiveDir"]
        shared = archive_shared_cache.snapshot_path(directory)
        known = self.registry.get_setting("archive.shared_snapshot_hashes", {}) or {}
        if shared.is_file():
            known[directory] = archive_shared_cache.fingerprint(shared)
        else:
            known.pop(directory, None)
        self.registry.set_setting("archive.shared_snapshot_hashes", known)

    def _publish_archive_snapshot(self, cfg, *, legacy_digest=None):
        before_shared_publish(self.archive)
        directory = cfg["archiveDir"]
        known = self.registry.get_setting("archive.shared_snapshot_hashes", {}) or {}
        try:
            result = archive_shared_cache.publish(
                self.archive, directory, known.get(directory), legacy_digest=legacy_digest)
        except (OSError, sqlite3.DatabaseError) as exc:
            log.warning("Could not publish portable Archive snapshot: %s", exc)
            return {"status": "error", "error": str(exc)}
        if result["status"] == "published":
            self.registry.set_setting("archive.shared_snapshot_hashes", {**known, directory: result["digest"]})
        elif result["status"] == "conflict":
            log.warning("Portable Archive snapshot changed on another computer; local DB kept")
        return {"status": result["status"]}

    def _pull_archive_snapshot(self, cfg):
        """Accept a newer shared Archive DB without discarding local edits."""
        directory = cfg["archiveDir"]
        known = self.registry.get_setting("archive.shared_snapshot_hashes", {}) or {}
        result = archive_shared_cache.pull_if_clean(
            self.archive, directory, known.get(directory))
        if result["status"] == "loaded":
            self.registry.set_setting("archive.shared_snapshot_hashes",
                                      {**known, directory: result["digest"]})
            log.info("Loaded newer portable Archive snapshot from %s", directory)
        elif result["status"] == "conflict":
            log.warning("Portable Archive snapshot changed while local Archive has edits")
        return {"status": result["status"]}

    def _archive_config(self) -> dict:
        return archive_projection.normalize_config(
            self.registry.get_setting(self.ARCHIVE_CONFIG_KEY, {}))

    @guarded
    def archive_config(self):
        """Archive 설정(Frontend 형식 / 디렉토리 / ROM 디렉토리 / media 보관)."""
        cfg = self._archive_config()
        return ok({**cfg, "configured": archive_projection.is_configured(cfg),
                   "editLock": archive_lock_status(cfg["archiveDir"]) if cfg.get("archiveDir") else None})

    @guarded
    def archive_release_edit_lock(self, observed_token, acknowledged=False):
        cfg = self._archive_config()
        if not cfg.get("archiveDir"):
            return err("Archive 디렉토리가 설정되지 않았습니다.")
        return ok(release_archive_orphan(cfg["archiveDir"], observed_token, acknowledged))

    @guarded
    def save_archive_config(self, patch):
        """설정을 저장한다. **저장만 한다** - 디렉토리에 다시 쓰는 일은 오래 걸릴 수 있어
        `start_archive_apply()`(진행률이 있는 job)로 따로 한다."""
        if not isinstance(patch, dict):
            return err("설정 형식이 올바르지 않습니다.")
        old = self._archive_config()
        new = archive_projection.normalize_config({**old, **patch})
        if new["frontend"] not in FRONTENDS:
            return err(f"알 수 없는 Frontend입니다: {new['frontend']}")
        for key in ("archiveDir", "romDir"):
            if new[key]:
                try:
                    Path(new[key]).mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    return err(f"폴더를 만들 수 없습니다: {e}")
        with self._archive_lifecycle_lock:
            if (new["archiveDir"] and new["archiveDir"] != old["archiveDir"]
                    and not self.archive.count_rows() and not self.jobs.active_jobs()):
                # Scheduling an Archive job uses the same lock. Never close a
                # connection after a refresh has been admitted.
                self.archive.close()
                try:
                    digest = archive_shared_cache.seed_if_empty(self._archive_path, new["archiveDir"])
                    if digest:
                        known = self.registry.get_setting("archive.shared_snapshot_hashes", {}) or {}
                        self.registry.set_setting("archive.shared_snapshot_hashes",
                                                  {**known, new["archiveDir"]: digest})
                except (OSError, RuntimeError, sqlite3.DatabaseError) as exc:
                    log.warning("Could not load selected Archive snapshot: %s", exc)
                finally:
                    self.archive = ArchiveStore(self._archive_path)
            self.registry.set_setting(self.ARCHIVE_CONFIG_KEY, new)
        moved = (new["frontend"], new["archiveDir"]) != (old["frontend"], old["archiveDir"])
        return ok({**new, "configured": archive_projection.is_configured(new),
                   # 화면이 "지금 적용할까요?"를 물을 근거
                   "needsApply": bool(moved and archive_projection.is_configured(new)),
                   "hasLegacy": archive_legacy.has_legacy(new["archiveDir"])})

    @archive_write
    def _apply_archive_config(self, progress_cb=None) -> dict:
        """이전 버전 Archive가 있으면 가져오고, Archive 전체를 설정한 디렉토리/형식으로 쓴다."""
        cfg = self._archive_config()
        if not archive_projection.is_configured(cfg):
            raise ValueError("Archive 디렉토리가 설정되지 않았습니다.")
        started_at = time.perf_counter()
        imported = None
        legacy_digest = None
        if archive_legacy.has_legacy(cfg["archiveDir"]):
            legacy_digest = archive_shared_cache.fingerprint(
                archive_legacy.legacy_db_path(cfg["archiveDir"]))
            imported = archive_legacy.import_legacy(self.archive, cfg["archiveDir"])
            log.info("legacy archive imported: %s", imported)
        legacy_seconds = time.perf_counter() - started_at
        def phase(start, end, name):
            if progress_cb is None:
                return None
            def report(current, total, label):
                ratio = max(0.0, min(1.0, float(current) / max(1, float(total))))
                progress_cb(round(start + ((end - start) * ratio)), 1000,
                            f"{name}: {label}")
            return report
        # 디렉토리에 있는 것(직접 넣은 ROM, 고친 gamelist)도 함께 읽는다.
        synced = archive_directory.sync_from_directory(
            self.archive, cfg, storage.for_path(cfg["archiveDir"]), progress_cb=phase(0, 450, "읽기"))
        scan_seconds = time.perf_counter() - started_at - legacy_seconds
        archive_projection.snapshot_revision_media(
            self.archive, cfg, self.archive.record_ids_with_media(),
            progress_cb=phase(450, 650, "Revision 미디어"))
        snapshot_seconds = time.perf_counter() - started_at - legacy_seconds - scan_seconds
        projection = archive_projection.project(
            self.archive, cfg, progress_cb=phase(650, 950, "Frontend 쓰기"))
        projection_seconds = (time.perf_counter() - started_at - legacy_seconds
                              - scan_seconds - snapshot_seconds)
        if progress_cb:
            progress_cb(950, 1000, "공유 DB 저장")
        shared = self._publish_archive_snapshot(cfg, legacy_digest=legacy_digest)
        if progress_cb:
            progress_cb(1000, 1000, "완료")
        timings = {"legacySeconds": round(legacy_seconds, 3),
                   "scanSeconds": round(scan_seconds, 3),
                   "snapshotSeconds": round(snapshot_seconds, 3),
                   "projectionSeconds": round(projection_seconds, 3),
                   "sharedSeconds": round(time.perf_counter() - started_at
                                          - legacy_seconds - scan_seconds
                                          - snapshot_seconds - projection_seconds, 3)}
        log.info("Archive apply timings: %s; scan stages: %s; projection stages: %s",
                 timings, synced.get("timings"), projection.get("timings"))
        return {"imported": imported, "synced": synced, "projection": projection,
                "timings": timings, "sharedSnapshot": shared}

    @guarded
    def start_archive_apply(self):
        """설정을 적용한다(job). media 수만 개를 복사할 수 있어 화면이 멈추지 않게 job으로 돈다."""
        if not archive_projection.is_configured(self._archive_config()):
            return err("Archive 디렉토리가 설정되지 않았습니다.")
        queued_at = time.perf_counter()
        def run(cb):
            log.info("Archive apply started after %.3fs wait", time.perf_counter() - queued_at)
            try:
                return self._apply_archive_config(cb)
            except JobCancelled:
                log.info("Archive apply cancelled after %.3fs", time.perf_counter() - queued_at)
                raise
            except Exception:
                log.exception("Archive apply failed after %.3fs", time.perf_counter() - queued_at)
                raise
        log.info("Archive apply requested")
        with self._archive_lifecycle_lock:
            job_id = self.jobs.run_heavy(run, mutates_state=True,
                                         target_ids=("archive",), kind="archive-apply")
        return ok({"jobId": job_id})

    @archive_write
    def _project_archive(self, result, rom_identity_ids=None, progress_cb=None,
                         overwrite_media=None):
        """Archive가 바뀐 뒤 설정된 디렉토리에 반영한다. 설정이 없으면 아무것도 안 한다."""
        cfg = self._archive_config()
        if not archive_projection.is_configured(cfg):
            return None
        try:
            record_ids = list((result or {}).get("revisionRecordIds") or []) if isinstance(result, dict) else []
            if not record_ids:
                for rid in rom_identity_ids or []:
                    edited = self.archive.latest_record(rid, archive_service.ARCHIVE_EDIT_SOURCE)
                    if edited:
                        record_ids.append(edited["record_id"])
            archive_projection.snapshot_revision_media(self.archive, cfg, record_ids)
            projected = archive_projection.project(self.archive, cfg, rom_identity_ids,
                                                    overwrite_media=overwrite_media,
                                                    progress_cb=progress_cb)
            projected["sharedSnapshot"] = self._publish_archive_snapshot(cfg)
            if current_transaction() and (projected.get("mediaMissing") or
                    projected["sharedSnapshot"]["status"] != "published"):
                raise ValueError("Archive 파일과 공유 DB를 모두 반영하지 못했습니다.")
            return projected
        except JobCancelled:
            # job의 progress_cb가 던진다(bridge/jobs.py) - 그대로 올려보내야
            # worker()가 "취소되었습니다"로 끝낸다. 여기서 삼키면 media 복사 중
            # 취소를 눌러도 job이 그냥 성공한 것처럼 끝나 보였다(실사용 버그 리포트).
            raise
        except Exception:  # noqa: BLE001 - 수집 자체는 성공했으므로 실패는 알리기만 한다
            log.exception("Archive 디렉토리에 쓰지 못했습니다")
            if current_transaction():
                raise
            return {"error": "Archive 디렉토리에 쓰지 못했습니다. 로그를 확인하세요."}

    @guarded
    def archive_conflicts(self, systems=None, rom_identity_ids=None):
        """`[n]` 뱃지용. **버전이 둘 이상이고 아직 고르지 않은 Identity만** 돌려준다."""
        started_at = time.perf_counter()
        counts = conflict_service.conflict_counts(
            self.archive, systems=systems or None,
            rom_identity_ids=rom_identity_ids if rom_identity_ids is not None else None)
        log.info("Archive conflicts: scope=%s requested=%s found=%s elapsed=%.3fs",
                 "system" if systems else "all",
                 len(rom_identity_ids) if rom_identity_ids is not None else "all",
                 len(counts), time.perf_counter() - started_at)
        return ok(counts)

    @guarded
    def archive_versions(self, rom_identity_id):
        """`[n]`을 눌렀을 때 보여줄 버전 목록(Title/Description/Media 크기/출처)."""
        versions = conflict_service.versions_of(self.archive, rom_identity_id)
        names = {c.id: c.name for c in self.registry.list_collections()}
        for v in versions:
            v["sourceNames"] = [names.get(s, s) for s in v["sources"]]
        preferred = self.archive.get_preferred(rom_identity_id)
        return ok({"romIdentityId": rom_identity_id, "versions": versions,
                   "preferredRecordId": preferred["record_id"] if preferred else None})

    @guarded
    @archive_write
    def archive_choose_version(self, rom_identity_id, record_id):
        """버전 하나를 고른다 - 이후 그 버전이 쓰이고 `[n]`은 사라진다."""
        result = archive_service.set_preferred(self.archive, rom_identity_id, int(record_id))
        self._project_archive(result, [rom_identity_id])
        return ok(result)

    def _media_source_path(self, source) -> str | None:
        """복사할 media 파일의 위치. source: {"kind": "archive"|"collection", "id", "uid", "key"}"""
        if source.get("kind") == "scraper":
            path = source.get("path")
            return str(path) if path and _path_within(path, self._scrape_cache_dir) else None
        media_type = MEDIA_KEYS.get(source.get("key"), str(source.get("key") or "").lower())
        if source.get("kind") == "archive":
            item = archive_projection.effective_media(self.archive, str(source.get("uid"))).get(media_type)
            return (self._archive_media_display_path(str(source.get("uid")), media_type, item)
                    if item else None)
        row = self.workspace.open(source.get("id")).get_row(int(source.get("uid")))
        item = next((m for m in (row["media"] if row else []) if m["media_type"] == media_type), None)
        return item["rel_path"] if item else None

    @guarded
    def media_paste(self, collection_id, rom_uid, media_key, source, immediate=False):
        """**Collection의 게임 한 개에 그림 한 장만 갈아 끼운다**(사용자 결정 - "특정 media를 복사하고
        타겟 media에서 붙여넣기").

        바이트가 움직이므로 Plan을 거친다(D1). 다른 media와 메타데이터는 건드리지 않는다 -
        이 항목이 들고 가는 것은 고른 그 한 종류뿐이다. 이미 있는 그림은 **덮어쓴다** - 바꾸려고
        누른 것이므로 충돌 창을 다시 띄우지 않는다.
        """
        collection, cache, provider = self._plan_context(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(collection, [row["system"]])
        if blocked:
            return blocked
        media_type = MEDIA_KEYS.get(media_key, str(media_key or "").lower())
        src = self._media_source_path(source or {})
        if not src or not Path(src).is_file():
            return err("복사할 media를 찾을 수 없습니다.")

        item = {
            "system": row["system"], "filename": row["filename"], "rom": None,
            "media": [{"type": media_type, "path": str(src), "size": Path(src).stat().st_size}],
            # 메타데이터는 지금 값을 그대로 둔다 - 그림 한 장만 바꾸는 것이다.
            "fields": row["fields"], "frontend_raw": row["frontend_raw"],
        }
        plan = Plan(collection_id) if immediate else self._plan(collection_id)
        result = builder.plan_add(plan, collection, provider, item and [item])
        for key in result.pop("conflictKeys", []):
            builder.resolve_conflict(plan, collection, provider, key, RESOLVE_OVERWRITE)
        result["conflicts"] = 0
        if immediate:
            return self._register_operation(collection_id, "media", plan, ok(result))
        return ok({**result, "mediaType": media_type, "romUid": int(rom_uid)})

    @guarded
    @archive_write
    def archive_media_paste(self, rom_identity_id, media_key, source):
        """다른 항목(Collection 또는 Archive)의 media 하나를 이 Archive 항목에 붙인다.

        cover 등 일부만 상대 것이 더 마음에 들 때 쓴다. 이 항목의 **다른 media와 메타데이터는
        그대로**다. 붙인 것은 "Archive에서 직접 고른 값"이라서 버전 충돌(`[n]`)도 해소된다.
        """
        identity = self.archive.get_identity(rom_identity_id)
        if identity is None:
            return err("Archive 항목을 찾을 수 없습니다.")
        media_type = MEDIA_KEYS.get(media_key, str(media_key or "").lower())
        src = self._media_source_path(source or {})
        if not src or not Path(src).is_file():
            return err("복사할 media를 찾을 수 없습니다.")
        # Archive 디렉토리가 있으면 거기에 두고 그것을 참조한다 - 원본 Collection이 사라져도
        # 남는다. 없으면 원본 위치를 그대로 가리킨다(Archive는 기본적으로 참조다).
        source_stat = Path(src).stat()
        self.archive.put_media_ref(rom_identity_id, media_type, ARCHIVE_EDIT_SOURCE, src,
                                   source_stat.st_size)
        fields, raw = self.archive.resolve_fields(rom_identity_id)
        media = self._archive_edit_media_state(rom_identity_id)
        media[media_type] = {"media_type": media_type, "abs_path": src,
                             "size": source_stat.st_size,
                             "mtime_ns": source_stat.st_mtime_ns, "state": "present"}
        revision, created = self.archive.put_record(
            rom_identity_id, ARCHIVE_EDIT_SOURCE, fields, raw,
            media=list(media.values()))
        edited = self.archive.latest_record(rom_identity_id, ARCHIVE_EDIT_SOURCE)
        log.info("Archive media paste staged item=%s type=%s source=%s bytes=%d "
                 "revision=%s record=%s created=%s",
                 rom_identity_id, media_type, src, source_stat.st_size,
                 revision, edited["record_id"], created)
        projection = self._project_archive(
            {"revisionRecordIds": [edited["record_id"]]}, [rom_identity_id],
            overwrite_media={rom_identity_id: {media_type}})
        resolved = archive_projection.effective_media(self.archive, rom_identity_id).get(media_type)
        log.info("Archive media paste projected item=%s type=%s effectiveSource=%s "
                 "effectivePath=%s effectiveBytes=%s projection=%s",
                 rom_identity_id, media_type,
                 resolved.get("source_collection_id") if resolved else None,
                 resolved.get("abs_path") if resolved else None,
                 resolved.get("size") if resolved else None, projection)
        if isinstance(projection, dict) and projection.get("error"):
            log.error("Archive media projection failed item=%s type=%s source=%s: %s",
                      rom_identity_id, media_type, src, projection["error"])
            return err(f"미디어를 Archive 디렉토리에 반영하지 못했습니다: {projection['error']}")
        cfg = self._archive_config()
        if archive_projection.is_configured(cfg) and cfg["mediaInternal"]:
            display_path = self._archive_media_display_path(
                rom_identity_id, media_type, {"abs_path": src, "size": source_stat.st_size},
                require_exists=False, cfg=cfg)
            if not display_path:
                return err("Archive 미디어 저장 경로를 확인할 수 없습니다.")
            destination = Path(display_path)
            try:
                projected_size = destination.stat().st_size
            except OSError:
                projected_size = None
            if projected_size != source_stat.st_size:
                log.warning("Archive media projection mismatch item=%s type=%s source=%s "
                            "sourceBytes=%d destination=%s destinationBytes=%s projection=%s",
                            rom_identity_id, media_type, src, source_stat.st_size,
                            display_path, projected_size, projection)
                try:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(display_path)):
                        shutil.copy2(src, destination)
                    projected_size = destination.stat().st_size
                except OSError as exc:
                    log.exception("Archive media direct copy failed item=%s type=%s",
                                  rom_identity_id, media_type)
                    return err(f"미디어를 Archive 디렉토리에 복사하지 못했습니다: {exc}")
                if projected_size != source_stat.st_size:
                    return err("Archive 미디어 복사본의 크기가 원본과 다릅니다.")
            log.info("Archive media verified item=%s type=%s bytes=%d destination=%s",
                     rom_identity_id, media_type, projected_size, display_path)
        return ok({"romIdentityId": rom_identity_id, "mediaType": media_type, "projection": projection})

    @guarded
    def import_media_image(self, target, collection_id, item_id, media_key, encoded, immediate=False):
        """Stage a validated local image, then reuse the normal media paste path."""
        if str(target) not in ("archive", "collection"):
            return err("미디어 대상이 올바르지 않습니다.")
        if MEDIA_KEYS.get(media_key, str(media_key or "").lower()) == VIDEO_MEDIA_TYPE:
            return err("영상 슬롯에는 이미지를 붙여넣을 수 없습니다.")
        path = media_import.stage_image(str(encoded or ""), self._scrape_cache_dir / "manual")
        source = {"kind": "scraper", "path": str(path)}
        if str(target) == "archive":
            return self.archive_media_paste(str(item_id), media_key, source)
        return self.media_paste(str(collection_id), item_id, media_key, source, immediate=immediate)

    def _archive_edit_media_state(self, rom_identity_id):
        """Latest Archive edit media as a complete, per-type mutable snapshot."""
        latest = self.archive.latest_record(rom_identity_id, ARCHIVE_EDIT_SOURCE)
        items = self.archive.media_of_revision(latest["record_id"]) if latest else []
        return {item["media_type"]: dict(item) for item in items}

    @guarded
    @archive_write
    def archive_media_delete(self, rom_identity_id, media_key):
        """Remove the currently effective source link for one media type.

        The source file is never deleted. A tombstone keeps this media type
        removed even when another Collection source still has a reference.
        When Archive owns media, only its projected destination is unlinked.
        """
        rid = str(rom_identity_id)
        identity = self.archive.get_identity(rid)
        if identity is None:
            return err("Archive 항목을 찾을 수 없습니다.")
        media_type = MEDIA_KEYS.get(media_key, str(media_key or "").lower())
        current = archive_projection.effective_media(self.archive, rid).get(media_type)
        if current is None:
            return err("Archive에 연결된 미디어가 없습니다.")

        cfg = self._archive_config()
        if archive_projection.is_configured(cfg) and cfg["mediaInternal"]:
            adapter = get_adapter(cfg["frontend"])
            collection = archive_projection.collection_for(cfg)
            layout = adapter.layout(collection, identity["system"])
            fields, _raw = self.archive.resolve_fields(rid)
            filename = identity["filename"] or identity["filename_norm"]
            media = MediaFile(media_type=media_type, path=current["abs_path"],
                              size=int(current.get("size") or 0))
            archive_root = Path(cfg["archiveDir"]).resolve()
            for _src, dest in adapter.media_pairs(
                    layout, filename, [media], title=(fields.get("name") or None)):
                dest_path = Path(dest).resolve()
                try:
                    dest_path.relative_to(archive_root)
                except ValueError:
                    continue
                # A configuration may point Archive at the source tree itself.
                # Never unlink the source asset in that case.
                if dest_path == Path(current["abs_path"]).resolve():
                    continue
                if dest_path.is_file():
                    archive_delete_file(dest_path)

        fields, raw = self.archive.resolve_fields(rid)
        media = self._archive_edit_media_state(rid)
        media[media_type] = {"media_type": media_type, "abs_path": "", "size": 0,
                             "state": "cleared"}
        self.archive.put_record(rid, archive_service.ARCHIVE_EDIT_SOURCE, fields, raw,
                                media=list(media.values()))
        edited = self.archive.latest_record(rid, archive_service.ARCHIVE_EDIT_SOURCE)
        projection = self._project_archive(
            {"revisionRecordIds": [edited["record_id"]]}, [rid],
            overwrite_media={rid: {media_type}})
        return ok({"romIdentityId": rid, "mediaType": media_type,
                   "sourceCollectionId": current["source_collection_id"],
                   "projection": projection})

    @guarded
    @archive_write
    def archive_refresh(self):
        """Archive 디렉토리를 다시 읽어 DB에 없는 항목(직접 넣은 ROM, 고친 gamelist)을 채운다."""
        cfg = self._archive_config()
        if not archive_projection.is_configured(cfg):
            return err("Archive 디렉토리가 설정되지 않았습니다.")
        provider = storage.for_path(cfg["archiveDir"])
        with self._archive_lifecycle_lock:
            pulled = self._pull_archive_snapshot(cfg)
            if pulled["status"] == "conflict":
                return err("다른 PC의 Archive DB와 이 PC의 수정 내용이 달라 자동으로 합칠 수 없습니다.")
            result = archive_directory.sync_from_directory(self.archive, cfg, provider)
            return ok({**result, "sharedPull": pulled})

    @guarded
    def start_archive_refresh(self):
        """Archive 디렉토리 재색인을 취소 가능한 background job으로 실행한다."""
        cfg = self._archive_config()
        if not archive_projection.is_configured(cfg):
            return err("Archive 디렉토리가 설정되지 않았습니다.")
        provider = storage.for_path(cfg["archiveDir"])
        queued_at = time.perf_counter()
        def refresh(cb):
            with archive_writing(self._archive_config()["archiveDir"]):
                log.info("Archive refresh started after %.3fs wait", time.perf_counter() - queued_at)
                started_at = time.perf_counter()
                try:
                    cb(0, 1000, "다른 PC의 Archive 변경 확인")
                    pulled = self._pull_archive_snapshot(cfg)
                    if pulled["status"] == "conflict":
                        raise ValueError("다른 PC의 Archive DB와 이 PC의 수정 내용이 달라 자동으로 합칠 수 없습니다.")
                    result = archive_directory.sync_from_directory(
                        self.archive, cfg, provider, progress_cb=cb)
                    result["sharedPull"] = pulled
                    result["scanSeconds"] = round(time.perf_counter() - started_at, 3)
                    result["sharedSnapshot"] = self._publish_archive_snapshot(cfg)
                    log.info("Archive refresh scan: %.3fs, systems=%s, stages=%s",
                             result["scanSeconds"], result["systems"], result.get("timings"))
                    return result
                except JobCancelled:
                    log.info("Archive refresh cancelled after %.3fs", time.perf_counter() - started_at)
                    raise
                except Exception:
                    log.exception("Archive refresh failed after %.3fs", time.perf_counter() - started_at)
                    raise
        log.info("Archive refresh requested")
        with self._archive_lifecycle_lock:
            job_id = self.jobs.run_heavy(
                refresh,
                mutates_state=True, target_ids=("archive",), kind="archive-refresh")
        return ok({"jobId": job_id})

    @guarded
    def archive_shared_conflict_status(self):
        cfg = self._archive_config()
        source = archive_shared_cache.snapshot_path(cfg["archiveDir"])
        if not source.is_file():
            return err("공유 Archive DB를 찾을 수 없습니다.")
        return ok({"digest": archive_shared_cache.fingerprint(source)})

    @guarded
    @archive_write
    def archive_resolve_shared_conflict(self, choice, observed_digest):
        if choice not in ("local", "shared"):
            return err("Archive 충돌 해결 방법을 선택하세요.")
        if not observed_digest:
            return err("공유 Archive DB를 다시 확인하세요.")
        with self._archive_lifecycle_lock:
            if self.jobs.active_jobs():
                return err("진행 중인 작업이 끝난 뒤 Archive 충돌을 해결하세요.")
            cfg = self._archive_config()
            result = archive_shared_cache.resolve_conflict(
                self.archive, cfg["archiveDir"], str(observed_digest), choice,
                self._archive_path.parent / "archive_conflict_backups")
            if result["status"] in ("loaded", "published"):
                known = self.registry.get_setting("archive.shared_snapshot_hashes", {}) or {}
                self.registry.set_setting("archive.shared_snapshot_hashes",
                                          {**known, cfg["archiveDir"]: result["digest"]})
            return ok(result)

    @guarded
    @archive_write
    def archive_project(self):
        """Archive 전체를 설정된 디렉토리에 다시 쓴다(복구/재배치용)."""
        cfg = self._archive_config()
        if not archive_projection.is_configured(cfg):
            return err("Archive 디렉토리가 설정되지 않았습니다.")
        archive_projection.snapshot_revision_media(
            self.archive, cfg, self.archive.record_ids_with_media())
        return ok(archive_projection.project(self.archive, cfg))

    @guarded
    @archive_write
    def archive_edit(self, rom_identity_id, fields):
        """Archive의 Metadata를 고친다. **Collection에는 반영되지 않는다**(§40)."""
        result = archive_service.edit(self.archive, rom_identity_id, fields)
        self._project_archive(result, [rom_identity_id])
        return ok(result)

    @guarded
    @archive_write
    def archive_rename(self, rom_identity_id, new_name):
        identity = self.archive.get_identity(str(rom_identity_id))
        if not identity:
            return err("게임을 찾을 수 없습니다.")
        name = str(new_name or "").strip()
        if (not name or name in (".", "..") or name[-1:] in (".", " ")
                or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)
                or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1,10)], *[f"LPT{i}" for i in range(1,10)]}):
            return err("Windows에서 사용할 수 없는 파일명입니다.")
        old = identity["filename"]
        if Path(name).suffix.lower() != Path(old).suffix.lower():
            return err("ROM 확장자는 유지해주세요.")
        if name.casefold() == old.casefold() or self.archive.find_rom_identity(identity["system"], name):
            return err("같은 파일명의 게임이 이미 있습니다.")
        ownership = self._archive_rom_ownership(str(rom_identity_id))
        if ownership["linkedCount"]:
            return err("외부 원본 ROM은 이름을 변경할 수 없습니다.")
        tx = current_transaction()
        for item in ownership["items"]:
            source = Path(item["path"])
            if source.is_file():
                destination = source.with_name(name)
                tx.rename(source, destination)
                self.archive._conn.execute("UPDATE archive_rom_sources SET abs_path=? WHERE rom_identity_id=? AND abs_path=?",
                    (str(destination), str(rom_identity_id), str(source)))
        from app.store.archive import rom_key_of
        self.archive._conn.execute("UPDATE rom_identities SET filename=?,filename_norm=?,rom_key=? WHERE rom_identity_id=?",
            (name, normalize_title(Path(name).stem), rom_key_of(name), str(rom_identity_id)))
        cfg = self._archive_config()
        adapter = get_adapter(cfg["frontend"])
        layout = adapter.layout(archive_projection.collection_for(cfg), identity["system"])
        adapter.remove_entries(layout, [old])
        projected = self._project_archive({}, [str(rom_identity_id)])
        if (projected or {}).get("error"):
            raise ValueError(projected["error"])
        return ok({"filename": name, "romIdentityId": str(rom_identity_id)})

    @guarded
    @archive_write
    def archive_metadata_delete(self, rom_identity_ids):
        """Hide effective metadata while retaining ROM, media, and source history."""
        ids = [str(value) for value in (rom_identity_ids or [])]
        if not ids:
            return err("지울 항목을 선택하세요.")
        cfg = self._archive_config()
        configured = archive_projection.is_configured(cfg)
        adapter = get_adapter(cfg["frontend"]) if configured else None
        collection = archive_projection.collection_for(cfg) if configured else None
        cleared, failures = 0, []
        for rid in ids:
            identity = self.archive.get_identity(rid)
            if identity is None:
                failures.append({"romIdentityId": rid, "reason": "Archive 항목을 찾을 수 없습니다."})
                continue
            try:
                if configured:
                    remove = getattr(adapter, "remove_entries", None)
                    if remove is None:
                        raise ValueError("이 Frontend는 메타데이터 항목 삭제를 지원하지 않습니다.")
                    layout = adapter.layout(collection, identity["system"])
                    remove(layout, [identity["filename"] or identity["filename_norm"]])
                self.archive.set_metadata_cleared(rid, True)
                cleared += 1
            except Exception as exc:  # continue with other selected identities
                failures.append({"romIdentityId": rid, "reason": str(exc)})
        return ok({"cleared": cleared, "failures": failures})

    @guarded
    @archive_write
    def archive_set_favorite(self, rom_identity_id, favorite=True):
        """즐겨찾기를 켜고 끈다. **Collection과 같은 방식이다**(사용자 결정).

        별표는 gamelist가 표현할 수 있는 값이므로 Archive에서도 **Metadata에 쓴다** -
        Archive는 정해진 Frontend 형식으로 저장되는 Collection의 일종이고(디렉토리
        projection), DB는 그 형식이 담지 못하는 것(Revision/Preferred/출처)을 덧붙이는
        층이라는 것이 이 앱의 구조다. 그래서 Collection의 set_favorite()과 똑같이
        `frontend_raw`에 적는다(= Archive 디렉토리의 gamelist.xml로 나간다).
        **DB에 따로 컬럼을 두지 않는다** - gamelist가 담을 수 있는 값을 DB가 또
        들고 있으면 같은 사실이 두 곳에 남아 어긋난다. 목록은 읽을 때 raw에서
        꺼내 쓴다(archive_rows).

        출처 Collection의 gamelist는 건드리지 않는다(§40) - 여기서 쓰는 것은 Archive
        자신의 Metadata다.
        """
        identity = self.archive.get_identity(rom_identity_id)
        if identity is None:
            return err("Archive 항목을 찾을 수 없습니다.")
        adapter = get_adapter(self._archive_config()["frontend"])
        tag = getattr(adapter, "FAVORITE_TAG", None)
        if not tag:
            return err(f"{adapter.display_name}는 즐겨찾기를 지원하지 않습니다.")

        # **해제는 태그를 지우는 것이 아니라 false로 적는 것이다** - Adapter는 모르는
        # 태그를 버리지 않으므로, raw에서 빼도 이미 파일에 있는 요소는 남는다
        # (Collection쪽 set_favorite()과 같은 이유).
        fields, raw = self.archive.resolve_fields(rom_identity_id)
        raw = dict(raw or {})
        extra = [dict(item) for item in (raw.get("extra") or [])
                 if (item.get("tag") or item.get("key")) != tag]
        extra.append(adapter.favorite_raw(bool(favorite)))
        raw["extra"] = extra

        result = archive_service.edit(self.archive, rom_identity_id, fields, raw)
        self._project_archive(result, [rom_identity_id])
        return ok({"romIdentityId": rom_identity_id, "favorite": bool(favorite)})

    @guarded
    @archive_write
    def archive_delete(self, rom_identity_ids):
        """Archive에서 이 항목들의 기록을 지운다.

        이 명령은 소유권과 관계없이 Revision/출처/Preferred 지정만 제거한다. 물리
        파일 삭제는 `archive_rom_delete`와 `archive_media_delete`처럼 자산 종류와
        Archive 관리 경계를 명시하는 명령에서만 수행한다.

        Archive 우클릭 메뉴의 "삭제"가 예전엔 Collection용 `plan_delete()`를 그대로
        불러 `Collection_id`가 "__archive__" 같은 값이라 매번 "Collection을 찾을 수
        없습니다"로 죽고 있었다(실사용 버그 리포트 - "복붙이나 삭제가 구조적으로
        안 되냐"). Archive는 Plan을 거치지 않는다(D1 - 바이트가 안 움직인다) - Metadata
        편집(archive_edit)과 같은 자리에서 즉시 지운다.

        Archive 디렉토리가 설정돼 있으면 그 gamelist에서도 항목을 지운다 - 안 그러면
        "디렉토리가 진실"이라는 원칙(app/archive/directory.py) 때문에 다음 새로고침 때
        지운 항목이 디렉토리에서 다시 읽혀 되살아난다. 그 디렉토리에 이미 복사해 둔
        media 파일까지 지우지는 않는다(고아 파일로 남는다) - ROM/Media를 실제로 지우는
        일은 이 메서드의 몫이 아니다.
        """
        ids = [str(i) for i in (rom_identity_ids or [])]
        if not ids:
            return err("지울 항목이 없습니다.")
        cfg = self._archive_config()
        removable = archive_projection.is_configured(cfg)
        adapter = get_adapter(cfg["frontend"]) if removable else None
        collection = archive_projection.collection_for(cfg) if removable else None
        deleted = 0
        for rid in ids:
            identity = self.archive.get_identity(rid)
            if identity is None:
                continue
            if removable and identity["filename"]:
                try:
                    layout = adapter.layout(collection, identity["system"])
                    remove = getattr(adapter, "remove_entries", None)
                    if remove is not None:
                        remove(layout, [identity["filename"]])
                except Exception:  # noqa: BLE001 - DB 삭제는 그래도 진행한다
                    log.exception("Archive 디렉토리에서 항목 제거 실패: %s", rid)
            if self.archive.delete_identity(rid):
                deleted += 1
        return ok({"deleted": deleted})

    @guarded
    def archive_delete_owned_preview(self, rom_identity_ids):
        cfg = self._archive_config()
        eligible, blocked = [], []
        for rid in [str(value) for value in (rom_identity_ids or [])]:
            if self.archive.get_identity(rid) is None:
                blocked.append({"romIdentityId": rid, "reason": "항목 없음"})
                continue
            ownership = self._archive_ownership(rid, cfg, check_exists=False)
            if ownership["rom"]["linkedCount"] or ownership["media"]["linkedCount"]:
                blocked.append({"romIdentityId": rid, "reason": "외부 원본 연결"})
            else:
                eligible.append(rid)
        return ok({"eligible": eligible, "blocked": blocked})

    @guarded
    @archive_write
    def archive_delete_owned(self, rom_identity_ids):
        """Delete a fully Archive-owned game including its Archive files.

        Mixed or externally linked identities are rejected. A partial file
        failure leaves the identity available so the user can retry.
        """
        ids = [str(value) for value in (rom_identity_ids or [])]
        if not ids:
            return err("지울 항목을 선택하세요.")
        cfg = self._archive_config()
        if not archive_projection.is_configured(cfg):
            return err("Archive 디렉토리를 먼저 설정하세요.")
        archive_root = Path(cfg["archiveDir"]).resolve()
        # Validate the complete selection before touching any file. A direct
        # bridge call must obey the same ownership rule as the disabled UI menu.
        preview = self.archive_delete_owned_preview(ids)
        if not preview.get("ok"):
            return preview
        if preview["data"]["blocked"]:
            return err("선택 항목에 외부 원본 연결이나 없는 게임이 있어 전체 삭제할 수 없습니다.")
        deleted, failures = 0, []
        for rid in ids:
            if self.archive.get_identity(rid) is None:
                failures.append({"romIdentityId": rid, "reason": "Archive 항목을 찾을 수 없습니다."})
                continue
            ownership = self._archive_ownership(rid, cfg)
            if ownership["rom"]["linkedCount"] or ownership["media"]["linkedCount"]:
                failures.append({"romIdentityId": rid,
                                 "reason": "외부 원본에 연결되어 있어 전체 삭제할 수 없습니다."})
                continue
            media_paths = [Path(item["path"]) for item in ownership["media"]["types"].values()
                           if item.get("path") and item["mode"] == "internal"]
            record_ids = self.archive.record_ids_of_identity(rid)
            rom_result = self.archive_rom_delete([rid])
            if not rom_result.get("ok") or rom_result["data"].get("failures"):
                failures.append({"romIdentityId": rid,
                                 "reason": rom_result.get("error") or "ROM 파일 삭제에 실패했습니다."})
                continue
            media_results = [self.archive_media_delete_selected([rid], part)
                             for part in ("media", "video")]
            if any(not result.get("ok") or result["data"].get("failures")
                   for result in media_results):
                failures.append({"romIdentityId": rid, "reason": "미디어 파일 삭제에 실패했습니다."})
                continue
            result = self.archive_delete([rid])
            if not result.get("ok") or not result["data"].get("deleted"):
                failures.append({"romIdentityId": rid,
                                 "reason": result.get("error") or "Archive 기록 삭제에 실패했습니다."})
                continue
            deleted += 1
            # Media projected at its original Archive path may have been kept
            # by archive_media_delete's source-protection rule. This operation
            # has already rejected every external path, so clean those copies.
            for path in media_paths:
                if _path_within(path, archive_root) and path.is_file():
                    try:
                        archive_delete_file(path)
                    except OSError as exc:
                        failures.append({"romIdentityId": rid, "reason": str(exc)})
            for record_id in record_ids:
                folder = archive_root / ".rms" / "revision-media" / str(record_id)
                if not _path_within(folder, archive_root) or not folder.is_dir():
                    continue
                try:
                    for child in list(folder.iterdir()):
                        if child.is_file() and not child.name.endswith((".rms-backup", ".rms-redo", ".rms-part")):
                            archive_delete_file(child)
                    # Recovery sidecars remain here until history is discarded.
                    if not any(folder.iterdir()):
                        folder.rmdir()
                except OSError as exc:
                    failures.append({"romIdentityId": rid, "reason": str(exc)})
        return ok({"deleted": deleted, "failures": failures})

    # ------------------------------------------------------------------
    # System 우클릭 - 언어 태그/멀티 디스크 태그 적용, 시스템 전체 삭제 (Archive판)
    # ------------------------------------------------------------------
    # 실사용 리포트 - "System 우클릭 옵션들도 다 안 되던데(prefix 붙이기, 디렉토리
    # 이동 등)". 확인해보니 Archive의 System 목록에는 우클릭 메뉴 자체가 안 걸려
    # 있었다(app.js). 메뉴가 있어야 뜻이 있는 항목만 옮긴다 - "Storage 옮기기"/
    # "System 이름 바꾸기"/"미디어 정리"는 Collection의 실제 파일·Storage 개념이
    # 있어야 하는 동작이라 Archive에는 그대로 옮길 수 없다(Archive는 여러 출처를
    # 모은 색인이지 자신의 파일을 갖지 않는다, §37). 반대로 언어 태그/디스크 태그
    # 적용(순수 텍스트 계산, app/title_affix.py)과 삭제(archive_delete)는 Archive
    # 데이터만으로 완전히 계산되므로 그대로 옮길 수 있다.
    def _archive_title_affix_rows(self, system=None, rom_identity_ids=None):
        """대상 행을 title_affix가 아는 모양으로 바꾼다.

        `rom_identity_ids`를 주면 그것만(Gamelist에서 고른 항목), 아니면 그 System
        전체다(System 우클릭) - Collection 쪽 `_title_affix_rows()`와 같은 갈래다.
        """
        ids = [str(i) for i in (rom_identity_ids or [])]
        rows = (self.archive.list_rows(only_ids=ids, limit=None) if ids
                else self.archive.list_rows(systems=[system] if system else None, limit=None))
        return [{"rom_uid": r["rom_identity_id"], "system": r["system"],
                 "filename": r["filename"], "title": r["title"]} for r in rows]

    @guarded
    def archive_title_affix_preview(self, system, rom_identity_ids=None):
        rows = self._archive_title_affix_rows(system, rom_identity_ids)
        if not rows:
            return err("대상을 찾을 수 없습니다.")
        changes = title_affix.preview_titles(rows, self._title_affix_config())
        return ok({"items": changes, "changed": sum(1 for c in changes if c["changed"])})

    @guarded
    @archive_write
    def archive_apply_title_affix(self, system, rom_identity_ids=None):
        """미리보기에서 확인한 대로 **바로** 적용한다. Archive는 Plan을 거치지
        않는다(D1 - 텍스트만 바뀌고 바이트는 안 움직인다) - archive_edit()과 같은
        자리에서 즉시 쓴다."""
        rows = self._archive_title_affix_rows(system, rom_identity_ids)
        changes = title_affix.preview_titles(rows, self._title_affix_config())
        return ok({"applied": self._archive_rename(changes)})

    @guarded
    def archive_disc_retag_preview(self, system, fmt=None):
        rows = self._archive_title_affix_rows(system)
        if not rows:
            return err("대상을 찾을 수 없습니다.")
        fmt = fmt or self._disc_title_option()["format"]
        changes = title_affix.preview_disc_retag(rows, fmt)
        return ok({"items": changes, "changed": sum(1 for c in changes if c["changed"])})

    @guarded
    @archive_write
    def archive_apply_disc_retag(self, system, fmt=None):
        rows = self._archive_title_affix_rows(system)
        fmt = fmt or self._disc_title_option()["format"]
        changes = title_affix.preview_disc_retag(rows, fmt)
        return ok({"applied": self._archive_rename(changes)})

    def _archive_rename(self, changes):
        """제목만 바꾼 편집 기록을 남긴다 - **지금 보이는 값 전체에 제목만 얹어서** 쓴다.

        화면의 저장(handleSaveDetail)과 같은 방식이다. 예전에는 `{"name": ...}` 하나만
        보냈는데, 편집 기록은 덮어쓰기가 아니라 통째로 새로 쓰이므로(put_record) 그 전에
        사용자가 Archive에서 직접 고쳐 둔 다른 값들이 이 한 번으로 사라졌다.
        """
        applied = 0
        for change in changes:
            if not change["changed"]:
                continue
            rid = change["romUid"]
            fields, _raw = self.archive.resolve_fields(rid)
            result = archive_service.edit(self.archive, rid, {**fields, "name": change["newTitle"]})
            self._project_archive(result, [rid])
            applied += 1
        return applied

    @guarded
    def archive_orphan_preview(self, system):
        """ROM이 한 번도 기록되지 않은 Archive 항목들(= 메타데이터만 남은 것).

        Collection의 "ROM 없는 항목 정리"와 뜻은 같지만 지우는 대상이 다르다 -
        Collection은 실제 gamelist 항목을 지우고, 여기서는 Archive의 기록만 지운다
        (실제 ROM/Media 파일은 애초에 Archive의 것이 아니다, §37).
        """
        rows = [r for r in self.archive.list_rows(systems=[system], limit=None)
                if not r["rom_count"]]
        return ok({"system": system, "items": [
            {"romIdentityId": r["rom_identity_id"], "filename": r["filename"],
             "title": r["title"]} for r in rows]})

    @guarded
    @archive_write
    def archive_cleanup_orphans(self, system):
        rows = [r for r in self.archive.list_rows(systems=[system], limit=None)
                if not r["rom_count"]]
        return self.archive_delete([r["rom_identity_id"] for r in rows]) if rows else ok({"deleted": 0})

    @guarded
    def archive_rom_folder(self, rom_identity_id):
        """Archive 보관 또는 외부 연결 ROM이 실제로 기록된 폴더를 연다."""
        ownership = self._archive_rom_ownership(rom_identity_id)
        candidates = ownership["items"]
        chosen = next((item for item in candidates
                       if item["mode"] == "internal" and item["present"]), None)
        chosen = chosen or next((item for item in candidates if item["present"]), None)
        chosen = chosen or next((item for item in candidates if item.get("path")), None)
        path = chosen.get("path") if chosen else None
        if not path:
            return err("이 항목에는 기록된 ROM 위치가 없습니다.")
        parent = str(Path(path).parent)
        if not Path(parent).exists():
            return err(f"폴더가 없습니다: {parent}")
        _reveal_path(parent)
        return ok({"path": parent})

    @guarded
    @archive_write
    def archive_rom_delete(self, rom_identity_ids):
        """Delete only ROM files that are inside Archive's configured ROM root.

        External Collection paths stay linked and untouched.  An Archive-owned
        source whose file is already missing is removed from the index as stale.
        """
        ids = [str(value) for value in (rom_identity_ids or [])]
        if not ids:
            return err("지울 ROM을 선택하세요.")
        cfg = self._archive_config()
        root = cfg.get("romDir") or cfg.get("archiveDir")
        if not root:
            return err("Archive ROM 디렉토리가 설정되지 않았습니다.")

        deleted_files = removed_sources = linked_sources = 0
        failures = []
        for rid in ids:
            ownership = self._archive_rom_ownership(rid, cfg)
            linked_sources += ownership["linkedCount"]
            for item in ownership["items"]:
                if item["mode"] != "internal":
                    continue
                path = item.get("path")
                # Recheck immediately before mutation; ownership may have been
                # calculated before the configuration or source row changed.
                if not _path_within(path, root):
                    linked_sources += 1
                    continue
                try:
                    target = Path(path)
                    if target.is_file():
                        archive_delete_file(target)
                        deleted_files += 1
                    elif target.exists():
                        failures.append({"romIdentityId": rid, "path": path,
                                         "reason": "ROM 경로가 파일이 아닙니다."})
                        continue
                    if self.archive.delete_rom_source(
                            rid, item.get("sourceCollectionId"), path):
                        removed_sources += 1
                except OSError as exc:
                    failures.append({"romIdentityId": rid, "path": path,
                                     "reason": str(exc)})
        if not deleted_files and not removed_sources and linked_sources and not failures:
            return err("선택한 ROM은 원본 Collection에 연결되어 있어 Archive에서 파일을 삭제할 수 없습니다.")
        return ok({"deletedFiles": deleted_files, "removedSources": removed_sources,
                   "linkedSourcesKept": linked_sources, "failures": failures})

    @guarded
    def archive_media_cleanup_preview(self, system):
        """Count Archive-owned media by type without touching linked originals."""
        counts = {}
        cfg = self._archive_config()
        for row in self.archive.list_rows(systems=[str(system or "")], limit=None):
            ownership = self._archive_media_ownership(
                row["rom_identity_id"], cfg, check_exists=False)
            for media_type, item in ownership["types"].items():
                if item["mode"] != "internal":
                    continue
                entry = counts.setdefault(media_type, {"type": media_type,
                    "label": MEDIA_LABELS.get(media_type, media_type), "count": 0, "bytes": 0})
                entry["count"] += 1
                entry["bytes"] += item.get("bytes", 0)
        return ok({"system": system, "types": sorted(
            counts.values(), key=lambda item: (-item["count"], item["type"]))})

    @guarded
    @archive_write
    def archive_media_delete_selected(self, rom_identity_ids, part):
        """Delete only Archive-owned media/video for selected identities."""
        if part not in ("media", "video"):
            return err("미디어 또는 영상을 선택하세요.")
        ids = [str(value) for value in (rom_identity_ids or [])]
        if not ids:
            return err("지울 항목을 선택하세요.")
        removed = linked_kept = 0
        failures = []
        cfg = self._archive_config()
        for rid in ids:
            if self.archive.get_identity(rid) is None:
                failures.append({"romIdentityId": rid, "reason": "Archive 항목을 찾을 수 없습니다."})
                continue
            ownership = self._archive_media_ownership(rid, cfg)
            for media_type, item in ownership["types"].items():
                if (media_type == "videos") != (part == "video"):
                    continue
                if item["mode"] != "internal":
                    linked_kept += 1
                    continue
                result = self.archive_media_delete(rid, media_type)
                if result.get("ok"):
                    removed += 1
                else:
                    failures.append({"romIdentityId": rid, "mediaType": media_type,
                                     "reason": result.get("error")})
        return ok({"removed": removed, "linkedKept": linked_kept, "failures": failures})

    @guarded
    @archive_write
    def archive_media_delete_system(self, system, media_types=None):
        """Remove selected Archive-owned media types from one System."""
        selected = (set(str(media_type) for media_type in media_types)
                    if media_types is not None else None)
        if selected is not None and (not selected or not selected.issubset(set(MEDIA_LABELS))):
            return err("지울 미디어 종류를 골라주세요.")
        removed = linked_kept = 0
        failures = []
        cfg = self._archive_config()
        for row in self.archive.list_rows(systems=[str(system or "")], limit=None):
            rid = row["rom_identity_id"]
            ownership = self._archive_media_ownership(rid, cfg)
            for media_type, item in ownership["types"].items():
                if selected is not None and media_type not in selected:
                    continue
                if item["mode"] != "internal":
                    linked_kept += 1
                    continue
                result = self.archive_media_delete(rid, media_type)
                if result.get("ok"):
                    removed += 1
                else:
                    failures.append({"romIdentityId": rid, "mediaType": media_type,
                                     "reason": result.get("error")})
        if not removed and linked_kept and not failures:
            return err("이 System의 Media는 모두 외부 원본 연결이라 Archive에서 파일을 삭제할 수 없습니다.")
        return ok({"removed": removed, "linkedKept": linked_kept, "failures": failures})

    @guarded
    @archive_write
    def archive_delete_system(self, system):
        """"시스템 전체 삭제"의 Archive판 - 그 System의 Identity를 전부 지운다.
        archive_delete()와 같은 이유로 실제 ROM/Media 파일은 그대로다."""
        ids = [r["rom_identity_id"] for r in self.archive.list_rows(systems=[system], limit=None)]
        return self.archive_delete(ids)

    @guarded
    def archive_revisions(self, rom_identity_id, source_collection_id):
        """한 출처의 Revision 이력(ARCHIVE_REVISION_POLICY.md §14 Revision History)."""
        return ok(self.archive.revisions_of(rom_identity_id, source_collection_id))

    @guarded
    @archive_write
    def archive_set_preferred(self, rom_identity_id, record_id):
        """이 Revision을 Preferred로 지정한다(정책 §8). 내용은 바뀌지 않는다."""
        return ok(archive_service.set_preferred(self.archive, rom_identity_id, int(record_id)))

    @guarded
    @archive_write
    def archive_clear_preferred(self, rom_identity_id):
        return ok(archive_service.clear_preferred(self.archive, rom_identity_id))

    @guarded
    def archive_to_collection(self, collection_id, rom_identity_ids, mode=None,
                              target_rom_uid=None, _operation=None, _progress=None):
        """Archive 항목의 메타데이터와 파일을 함께 Plan에 담는다."""
        collection, cache, provider = self._plan_context(collection_id)
        blocked = self._ensure_file_ops(collection)
        if blocked:
            return blocked
        blocked = self._ensure_writable(collection, [s.system for s in collection.systems])
        if blocked:
            return blocked
        target_row = cache.get_row(int(target_rom_uid)) if target_rom_uid is not None else None
        if target_rom_uid is not None and target_row is None:
            return err("대상 게임을 찾을 수 없습니다.")
        if target_row is not None and len(rom_identity_ids) != 1:
            return err("대상 게임에 가져올 Archive 후보를 한 개 선택하세요.")
        cfg = self._archive_config()
        result = archive_service.to_collection(self.archive, collection, cache, provider,
                                               rom_identity_ids,
                                               media_resolver=(
                                                   lambda rid, media_type, item:
                                                   self._archive_media_display_path(rid, media_type, item)
                                               ) if cfg["mediaInternal"] else None,
                                               explicit_target=target_row, progress=_progress)
        policy = self._transfer_policy()
        target_adapter = get_adapter(collection.frontend)
        items = [{**item,
                  "rom": item.get("rom") if policy["includeRom"] else None,
                  "media": item.get("media") if policy["includeMedia"] else [],
                  "frontend_raw": item.get("frontend_raw") or {}
                  if target_adapter.raw_is_mine(item.get("frontend_raw") or {}) else {}}
                 for item in result["items"]]
        prepared, skipped = transfer.prepare(items, cache, mode or policy["pasteMode"],
                                             exact_only=target_row is None)
        added = {"added": 0, "skipped": [], "conflicts": 0}
        plan = _operation if _operation is not None else self._plan(collection_id)
        if prepared:
            added = builder.plan_add(plan, collection, provider, prepared)
        keys = list(dict.fromkeys(added.get("keys", [])))
        return ok({
            "planned": len(keys), "keys": keys,
            "conflicts": sum(bool(plan.get(key).conflicts) for key in keys),
            "skipped": result["skipped"] + skipped + added.get("skipped", []),
        })

    @guarded
    def collection_import_candidates(self, target_id, target_rom_uid, source_id):
        if source_id == target_id:
            return err("다른 Collection을 출처로 선택하세요.")
        target, target_cache, _ = self._plan_context(target_id)
        source, source_cache, _ = self._plan_context(source_id)
        row = target_cache.get_row(int(target_rom_uid))
        if row is None:
            return err("대상 게임을 찾을 수 없습니다.")
        return ok({"source": {"system": row["system"], "filename": row["filename"],
                               "title": row["title"], "size": row["size"]},
                   "candidates": collection_import.candidates(
                       target, row, source, source_cache)})

    @guarded
    def collection_import_plan(self, target_id, source_id, rom_uids=None,
                               target_rom_uid=None, target_system=None, mode=None, _operation=None):
        if source_id == target_id:
            return err("다른 Collection을 출처로 선택하세요.")
        target, target_cache, provider = self._plan_context(target_id)
        source, source_cache, _ = self._plan_context(source_id)
        blocked = self._ensure_file_ops(target)
        if blocked:
            return blocked
        target_row = target_cache.get_row(int(target_rom_uid)) if target_rom_uid is not None else None
        if target_rom_uid is not None and target_row is None:
            return err("대상 게임을 찾을 수 없습니다.")
        if target_system is not None and target_system not in {s.system for s in target.systems}:
            return err("대상 System을 찾을 수 없습니다.")
        blocked = self._ensure_writable(target,
            [target_row["system"]] if target_row else
            [target_system] if target_system else [s.system for s in target.systems])
        if blocked:
            return blocked
        ids = list(rom_uids or [])
        if not ids:
            wanted = normalize_system(target.frontend, target_system) if target_system else None
            ids = [row["rom_uid"] for row in source_cache.all_entries()
                   if wanted is None or normalize_system(source.frontend, row["system"]) == wanted]
        result = collection_import.plan_import(
            _operation if _operation is not None else self._plan(target_id), source, source_cache, target, target_cache, provider,
            ids, mode=mode or self._transfer_policy()["pasteMode"],
            policy=self._transfer_policy(), target_row=target_row,
            target_system=target_system)
        return ok(result)

    # ------------------------------------------------------------------
    # Match (스펙 §45-49)
    # ------------------------------------------------------------------
    @guarded
    def match_candidates(self, collection_id, rom_uid):
        """이 ROM과 같은 것일 수 있는 Archive 항목들. **자동으로 붙이지 않는다**(§49).

        사용자가 Match 버튼을 눌렀을 때만 불리는 경로이므로 Heuristic까지 본다.
        """
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        return ok(match_service.candidates_for(self.archive, collection_id, row, deep=True))

    @guarded
    def match_counts(self, collection_id, rom_uids):
        """Gamelist 뱃지용 후보 개수. 화면에 보이는 행만 넘길 것.

        가벼운 티어(Exact/Normalized)만 세므로, 여기서 0이어도 Match 다이얼로그를
        열면 Heuristic 후보가 나올 수 있다.
        """
        cache = self.workspace.open(collection_id)
        rows = [cache.get_row(int(uid)) for uid in (rom_uids or [])]
        rows = [r for r in rows if r is not None]
        counts = match_service.counts_for_rows(self.archive, collection_id, rows)
        return ok({str(uid): n for uid, n in counts.items()})

    @guarded
    def apply_match(self, collection_id, rom_uid, rom_identity_id, manual=False):
        """사용자가 고른 후보를 확정한다. 파일도 Metadata도 아직 건드리지 않는다.

        후보 목록에 없는 Identity는 거절한다 - `manual=True`를 명시해야 강제로 잇고,
        그때는 티어가 `manual`로 남아 엔진 판정과 구분된다. 지금 UI에는 강제 연결
        경로가 없고, Compare(Phase 6)처럼 사용자가 좌우를 직접 지목하는 화면이
        생길 때 쓰라고 열어 둔 것이다.
        """
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        return ok(match_service.apply_match(self.archive, collection_id, row,
                                            rom_identity_id, manual=bool(manual)))

    @guarded
    def clear_match(self, collection_id, rom_uid):
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        return ok({"cleared": match_service.clear_match(self.archive, collection_id, row)})

    # ------------------------------------------------------------------
    # Metadata 없는 Collection 시작하기
    # ------------------------------------------------------------------
    @guarded
    def metadata_status(self, collection_id):
        """gamelist가 없는 System이 있는지. Collection을 연 직후 물어보기 위한 것이다."""
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        provider = storage.for_path(collection.root_path)
        return ok(metadata_service.status(collection, provider))

    @guarded
    def generate_metadata(self, collection_id, systems=None):
        """ROM 목록만 담은 gamelist를 만든다. 이미 있는 파일은 건드리지 않는다."""
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        provider = storage.for_path(collection.root_path)
        clash = self._conflicts(collection)
        if systems:
            blocked = self._ensure_writable(collection, systems)
            if blocked:
                return blocked
        elif clash:
            # 전체 대상이면 충돌한 System만 빼고 만든다 - 하나 때문에 전부 막을 이유는 없다.
            systems = [e.system for e in collection.systems if e.system.lower() not in clash]
        return ok(metadata_service.generate(collection, provider, systems))

    # ------------------------------------------------------------------
    # Convert (스펙 §53)
    # ------------------------------------------------------------------
    @guarded
    def convert_preview(self, source_collection_id, target_collection_id):
        """이 변환에서 무엇이 넘어가고 무엇이 사라지는지. **아무것도 바꾸지 않는다.**

        Frontend 간 변환은 반드시 무언가를 잃으므로(§50-51), 실행 전에 그것을 보여줘야
        사용자가 판단할 수 있다.
        """
        if source_collection_id == target_collection_id:
            return err("같은 Collection으로는 변환할 수 없습니다.")
        source = self.registry.get_collection(source_collection_id)
        target = self.registry.get_collection(target_collection_id)
        if source is None or target is None:
            return err("Collection을 찾을 수 없습니다.")
        cache = self.workspace.open(source_collection_id)
        return ok(convert_service.preview(source, cache, target))

    @guarded
    def start_convert(self, source_collection_id, target_collection_id, immediate=False):
        """변환 결과를 target의 Plan에 올린다. Auto Plan이 꺼져 있어도 여기서는
        파일을 건드리지 않는다 - 확정은 언제나 Apply의 몫이다."""
        if source_collection_id == target_collection_id:
            return err("같은 Collection으로는 변환할 수 없습니다.")
        source = self.registry.get_collection(source_collection_id)
        if source is None:
            return err("원본 Collection을 찾을 수 없습니다.")
        source_cache = self.workspace.open(source_collection_id)
        target, _cache, provider = self._plan_context(target_collection_id)
        operation = Plan(target_collection_id) if immediate else self._plan(target_collection_id)
        result = convert_service.plan_convert(operation, source,
                                              source_cache, target, provider)
        if immediate:
            return self._register_operation(target_collection_id, "convert", operation, ok(result))
        return ok(result)

    # ------------------------------------------------------------------
    # Compare (스펙 §54-59)
    # ------------------------------------------------------------------
    @guarded
    def start_compare(self, base_collection_id, other_collection_id):
        """두 Collection을 맞대어 비교를 시작한다.

        비교 결과는 **여기서 한 번 계산해 들고 있는다**. 필터를 누를 때마다 두
        Collection을 다시 훑으면 만 단위 목록에서 버튼이 먹통이 되고, 무엇보다 그
        사이에 스캔이 끼면 필터마다 다른 스냅샷을 보게 된다. 최신 상태로 다시 보려면
        사용자가 명시적으로 다시 시작하면 된다.
        """
        if base_collection_id == other_collection_id:
            return err("같은 Collection끼리는 비교할 수 없습니다.")
        base = self.registry.get_collection(base_collection_id)
        other = self.registry.get_collection(other_collection_id)
        if base is None or other is None:
            return err("Collection을 찾을 수 없습니다.")

        left = self.workspace.open(base_collection_id).all_entries()
        right = self.workspace.open(other_collection_id).all_entries()
        rows = compare_engine.compare(left, right)
        self._compare = {"baseId": base_collection_id, "otherId": other_collection_id,
                         "rows": rows, "takenAt": time.time()}
        return ok(self._compare_state())

    @guarded
    def compare_state(self):
        """지금 Compare Mode인지와 요약. 아니면 data=None."""
        return ok(self._compare_state() if self._compare else None)

    def _compare_state(self):
        base = self.registry.get_collection(self._compare["baseId"])
        other = self.registry.get_collection(self._compare["otherId"])
        rows = self._compare["rows"]
        return {
            "baseId": self._compare["baseId"], "otherId": self._compare["otherId"],
            "baseName": base.name if base else "?",
            "otherName": other.name if other else "?",
            "counts": compare_engine.summarize(rows),
            "systems": sorted({r["system"] for r in rows}),
            # 이 결과는 시작 시점의 스냅샷이다. 그 사이 Collection이 바뀌었을 수
            # 있으므로 언제 찍은 것인지 화면이 말해줄 수 있어야 한다.
            "takenAt": self._compare.get("takenAt"),
        }

    @guarded
    def compare_rows(self, status=None, systems=None, search=None, limit=200, offset=0):
        """Compare Gamelist. 일반 Gamelist와 같은 모양으로 돌려준다."""
        if not self._compare:
            return err("Compare Mode가 아닙니다.")
        rows = compare_engine.filter_rows(self._compare["rows"], status)
        if systems:
            rows = [r for r in rows if r["system"] in systems]
        if search:
            needle = str(search).strip().lower()
            rows = [r for r in rows
                    if needle in r["file"].lower()
                    or needle in ((r["left"] or r["right"] or {}).get("title") or "").lower()]
        total = len(rows)
        page = rows[int(offset):int(offset) + int(limit)]
        return ok({"rows": [self._compare_row_summary(r) for r in page],
                   "total": total, "offset": int(offset)})

    @guarded
    def compare_all_keys(self, status=None, systems=None, search=None):
        """지금 필터에 맞는 **전체** 행의 열쇠(system|file). Ctrl+A(전체 선택)용.

        `compare_rows()`는 화면에 보여줄 몫만 페이지로 잘라 준다(기본 200개). 가상
        스크롤이 그 조각만 `S.rowCache`에 채워 두므로, "화면에 이미 다 있다"고
        믿고 그 캐시만으로 전체 선택을 만들면 200개가 넘는 결과에서는 뒤쪽이
        조용히 빠진다(실사용 버그 - "대부분 다르다고 나오는데 실제로는 몇 개만
        붙여넣기 된다"). Compare 결과 자체는 이미 메모리에 있으니 새로 비교할
        필요는 없지만, 페이지가 아니라 **전체**를 돌려줘야 한다.
        """
        if not self._compare:
            return err("Compare Mode가 아닙니다.")
        rows = compare_engine.filter_rows(self._compare["rows"], status)
        if systems:
            rows = [r for r in rows if r["system"] in systems]
        if search:
            needle = str(search).strip().lower()
            rows = [r for r in rows
                    if needle in r["file"].lower()
                    or needle in ((r["left"] or r["right"] or {}).get("title") or "").lower()]
        return ok([f"{r['system']}|{r['file']}" for r in rows])

    @staticmethod
    def _compare_row_summary(row):
        left, right = row["left"] or {}, row["right"] or {}
        side = row["left"] or row["right"] or {}
        return {
            # 좌우 어느 쪽에만 있을 수 있으므로 romUid는 목록의 키로 쓰지 않는다 -
            # (system, file)이 Compare 행의 안정적인 식별자다.
            "key": f"{row['system']}|{row['file']}",
            "system": row["system"], "file": row["file"],
            "title": side.get("title") or "",
            "size": side.get("size") or 0,
            "status": row["status"], "mediaDiff": row["mediaDiff"],
            "changedFields": row["changedFields"],
            "leftRomUid": left.get("romUid"), "rightRomUid": right.get("romUid"),
            # 가운데 목록이 좌/우를 **각자의** 파일명/제목으로 그린다. 짝이 이름 정규화로 맺어진
            # 경우 양쪽 파일명이 다를 수 있는데, 한 쌍만 주면 양쪽에 같은 값이 찍혔다.
            "leftFile": left.get("filename"), "rightFile": right.get("filename"),
            "leftTitle": left.get("title") or "", "rightTitle": right.get("title") or "",
            "leftPresent": bool(left.get("present")), "rightPresent": bool(right.get("present")),
        }

    @guarded
    def compare_detail(self, key):
        """한 행의 좌우 Metadata를 나란히. 다른 필드는 changedFields로 알린다."""
        if not self._compare:
            return err("Compare Mode가 아닙니다.")
        row = next((r for r in self._compare["rows"]
                    if f"{r['system']}|{r['file']}" == key), None)
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        state = self._compare_state()
        return ok({
            "key": key, "system": row["system"], "file": row["file"],
            "status": row["status"], "changedFields": row["changedFields"],
            "mediaDiff": row["mediaDiff"], "mediaChanged": row.get("mediaChanged", []),
            "baseName": state["baseName"], "otherName": state["otherName"],
            "left": self._compare_side_detail(row["left"], state["baseId"], row["system"]),
            "right": self._compare_side_detail(row["right"], state["otherId"], row["system"]),
        })

    def _compare_side_detail(self, side, collection_id, system):
        """한쪽의 Detail에 필요한 것. 그림을 읽을 수 있게 collectionId/romUid를 함께 준다."""
        if side is None:
            return None
        collection = self.registry.get_collection(collection_id)
        rom_path = None
        if collection is not None:
            layout = get_adapter(collection.frontend).layout(collection, system)
            rom_path = str(Path(layout.rom_dir) / side["filename"]) if layout.rom_dir else None
        return {**side, "collectionId": collection_id, "romPath": rom_path}

    @guarded
    def compare_operation_preview(self, options=None):
        options = options or {}
        if not self._compare:
            return err("Compare Mode가 아닙니다.")
        direction = options.get("direction")
        operation = Plan("")
        if options.get("sourceKey"):
            result = self.compare_manual_copy(options["sourceKey"], options.get("targetKey"),
                options.get("mode"), _operation=operation)
        else:
            result = self.compare_copy_rows(options.get("keys"), direction,
                metadata_only=options.get("metadataOnly", True), overwrite=False,
                media_types=options.get("mediaTypes"), _operation=operation)
        if not result["ok"]:
            return result
        target_id = result["data"]["targetId"]
        operation.collection_id = target_id
        return self._register_operation(target_id, "compare", operation, result)

    @guarded
    def compare_copy_rows(self, keys, direction, metadata_only=True, overwrite=True, mode=None,
                          media_types=None, _operation=None):
        """**고른 여러 행**을 한 번에 반대쪽 Plan에 올린다(사용자 결정 - Compare 상단의 `<` `>`는
        "선택된 항목들의 메타데이터+미디어를 좌/우측으로 overwrite").

        기본이 `metadata_only=True`인 이유: 이 버튼은 ROM을 옮기는 것이 아니라 **내용을 맞추는**
        것이다. ROM까지 옮기는 것은 행마다 있는 `>` `<`(한쪽에만 ROM이 있을 때)가 맡는다.

        `overwrite=True`면 이번에 생긴 충돌을 덮어쓰기로 정해 둔다 - 덮어쓰라고 누른 버튼이
        충돌 창을 다시 띄우면 같은 결정을 두 번 하는 셈이다. 실제 파일은 Apply를 눌러야 바뀐다.
        """
        if not self._compare:
            return err("Compare Mode가 아닙니다.")
        keys = list(keys or [])
        if not keys:
            return err("보낼 항목을 먼저 고르세요.")
        planned, skipped, target_name, target_id = 0, [], None, None
        for key in keys:
            result = self.compare_copy_row(key, direction, metadata_only=metadata_only,
                                           overwrite=overwrite, mode=mode,
                                           media_types=media_types, _operation=_operation)
            if not result["ok"]:
                skipped.append({"key": key, "reason": result["error"]})
                continue
            data = result["data"]
            planned += data.get("added", 0)
            skipped.extend(data.get("skipped", []))
            target_name, target_id = data["targetName"], data["targetId"]
        if target_id is None:
            return err(skipped[0]["reason"] if skipped else "보낼 수 있는 항목이 없습니다.")
        return ok({"added": planned, "skipped": skipped, "requested": len(keys),
                   "targetId": target_id, "targetName": target_name, "direction": direction,
                   "metadataOnly": bool(metadata_only)})

    @guarded
    def compare_manual_copy(self, source_key, target_key, mode=None, _operation=None):
        """**사용자가 직접 이은 두 항목** 사이의 전송(제안서 §5, §15.3-15.4).

        자동 짝짓기는 파일명/제목이 비슷할 때만 잇는다. `Final Fantasy 7.zip`과 `ff7.rom`처럼
        아무 공통점이 없으면 둘은 각각 "한쪽에만 있음"으로 남는데, 사람은 그것이 같은 게임임을 안다.
        그럴 때 두 행을 고르고 이 경로로 보낸다.

        **Match 결과는 바꾸지 않는다.** 이것은 "이번에 이 대상에 써라"라는 실행 승인이지
        "이 둘은 같은 게임이다"라는 선언이 아니다(§15.8) - 선언은 `apply_match()`가 한다.

        방향은 유추한다: 원본이 있는 쪽에서 대상이 있는 쪽으로 간다. 양쪽에 다 있거나 한쪽이
        비어 있으면 무엇을 하려는지 알 수 없으므로 거절한다.
        """
        if not self._compare:
            return err("Compare Mode가 아닙니다.")
        if source_key == target_key:
            return err("원본과 대상이 같은 항목입니다.")
        rows = {f"{r['system']}|{r['file']}": r for r in self._compare["rows"]}
        source_row, target_row = rows.get(source_key), rows.get(target_key)
        if source_row is None or target_row is None:
            return err("고른 항목을 찾을 수 없습니다.")

        # 원본이 왼쪽에 있으면 대상은 오른쪽에 있어야 한다(그 반대도 마찬가지).
        if source_row["left"] and target_row["right"] and not source_row["right"]:
            side, other, to_right = source_row["left"], target_row["right"], True
        elif source_row["right"] and target_row["left"] and not source_row["left"]:
            side, other, to_right = source_row["right"], target_row["left"], False
        else:
            return err("한쪽에만 있는 항목 두 개를 서로 다른 쪽에서 골라야 잇을 수 있습니다.")

        source_id = self._compare["baseId"] if to_right else self._compare["otherId"]
        target_id = self._compare["otherId"] if to_right else self._compare["baseId"]
        source = self.registry.get_collection(source_id)
        target, target_cache, provider = self._plan_context(target_id)
        if source is None or target is None:
            return err("Collection을 찾을 수 없습니다.")
        blocked = self._ensure_file_ops(target) or self._ensure_writable(target, [target_row["system"]])
        if blocked:
            return blocked

        items, _bytes = clipboard.build_items(source, self.workspace.open(source_id), [side["romUid"]])
        if not items:
            return err("원본 항목을 읽지 못했습니다.")
        existing = target_cache.get_row(int(other["romUid"]))
        prepared, skipped = transfer.prepare(
            items, target_cache, transfer.normalize_mode(mode or transfer.MODE_REPLACE),
            targets={transfer.item_key(items[0]): existing})
        if not prepared:
            return ok({"added": 0, "skipped": skipped, "conflicts": 0, "targetId": target_id,
                       "targetName": target.name, "targetFile": other["filename"]})

        plan = _operation if _operation is not None else self._plan(target_id)
        result = builder.plan_add(plan, target, provider, prepared)
        for conflict_key in result.pop("conflictKeys", []):
            # 직접 지목해서 보낸 것이다 - 이번에 생긴 media 충돌은 다시 묻지 않는다.
            if all(c.get("kind") != "rom" for c in (plan.get(conflict_key).conflicts or [])):
                builder.resolve_conflict(plan, target, provider, conflict_key, RESOLVE_OVERWRITE)
                result["conflicts"] = max(0, result.get("conflicts", 0) - 1)
        result["skipped"] = [*skipped, *result.get("skipped", [])]
        return ok({**result, "targetId": target_id, "targetName": target.name,
                   "targetFile": other["filename"], "sourceFile": side["filename"]})

    @guarded
    def compare_copy_row(self, key, direction, metadata_only=False, overwrite=False, mode=None,
                         media_types=None, _operation=None):
        """Compare 한 행을 반대쪽 Collection의 **Plan에 올린다**(사용자 결정 - "모든 변경은
        PLAN 기준 / 실제 Apply를 눌러야 적용").

        `direction`: "toRight"(기준 -> 상대) 또는 "toLeft"(상대 -> 기준).
        `metadata_only`: `≠`(양쪽에 ROM이 있는데 내용이 다름)에서 쓴다 - ROM은 이미 있으므로
        옮기지 않고 메타데이터/media만 보낸다.

        Compare 결과는 시작 시점의 스냅샷이라 여기서 Plan에 올려도 그 스냅샷은 그대로 둔다 -
        다시 비교(Refresh)하는 것이 "지금 상태"를 보는 정직한 방법이다.
        """
        if not self._compare:
            return err("Compare Mode가 아닙니다.")
        if direction not in ("toLeft", "toRight"):
            return err(f"알 수 없는 방향입니다: {direction}")
        row = next((r for r in self._compare["rows"]
                    if f"{r['system']}|{r['file']}" == key), None)
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        to_right = direction == "toRight"
        side = row["left"] if to_right else row["right"]
        if side is None:
            return err("보낼 쪽에 그 항목이 없습니다.")
        source_id = self._compare["baseId"] if to_right else self._compare["otherId"]
        target_id = self._compare["otherId"] if to_right else self._compare["baseId"]

        source = self.registry.get_collection(source_id)
        target, _cache, provider = self._plan_context(target_id)
        if source is None or target is None:
            return err("Collection을 찾을 수 없습니다.")
        blocked = self._ensure_file_ops(target) or self._ensure_writable(target, [row["system"]])
        if blocked:
            return blocked

        items, _bytes = clipboard.build_items(source, self.workspace.open(source_id), [side["romUid"]])
        if not items:
            return err("원본 항목을 읽지 못했습니다.")
        # Compare는 **이미 같은 게임임을 안다**(짝이 이름 정규화로 맺어져 파일명이 달라도). 그러니 붙여넣기처럼
        # 파일명으로 다시 찾지 않고 짝이 알려 준 상대 행을 그대로 게임 단위 전송 계층에 넘긴다.
        # 의도(Metadata/Media/ROM)는 여기서 정하고, 파일 안전 검사는 그 뒤 plan_add()가 바뀔 것에만 한다.
        other = row["right"] if to_right else row["left"]
        wanted = {str(t).lower() for t in (media_types or []) if str(t).strip()}
        if wanted:
            # 고른 미디어 종류만 보낸다(사용자 결정 - Compare 미디어 다중 선택). 메타데이터/ROM은 건드리지 않는다.
            if other is None:
                return err("상대에 그 항목이 없어 미디어만 보낼 수 없습니다.")
            items = [{**item, "rom": None, "fields": {},
                      "media": [m for m in item.get("media") or []
                                if (m.get("type") or m.get("media_type")) in wanted]} for item in items]
        elif metadata_only or not side.get("present"):
            # 내용을 맞추는 버튼이거나 ROM이 없는 쪽이다 - ROM은 옮기지 않는다.
            items = [{**item, "rom": None} for item in items]
        if other is not None:
            target_cache = self.workspace.open(target_id)
            existing = target_cache.get_row(int(other["romUid"]))
            items = [{**item, "filename": other["filename"]} for item in items]
            out, reason = transfer.decide(items[0], existing,
                                          transfer.normalize_mode(mode or "overwrite"))
            if out is None:
                return ok({"added": 0, "skipped": [{"filename": other["filename"], "reason": reason}],
                           "conflicts": 0, "targetId": target_id, "targetName": target.name,
                           "direction": direction, "metadataOnly": bool(metadata_only)})
            items = [out]
        plan = _operation if _operation is not None else self._plan(target_id)
        result = builder.plan_add(plan, target, provider, items)
        keys = result.pop("conflictKeys", [])
        if overwrite and keys:
            # 덮어쓰라고 누른 버튼이다 - 이번에 생긴 충돌을 다시 묻지 않는다(사용자 결정).
            # ROM 충돌은 예외다 - ROM 교체는 명시적으로 고른 것이고, 다른 파일을 덮는 일은 사용자가 정한다.
            auto = [k for k in keys
                    if all(c.get("kind") != "rom" for c in (plan.get(k).conflicts or []))]
            for conflict_key in auto:
                builder.resolve_conflict(plan, target, provider, conflict_key, RESOLVE_OVERWRITE)
            result["conflicts"] = len(keys) - len(auto)
        return ok({**result, "targetId": target_id, "targetName": target.name,
                   "direction": direction, "metadataOnly": bool(metadata_only)})

    @guarded
    def exit_compare(self):
        """Compare Mode 종료(§58의 [Exit Compare])."""
        self._compare = None
        return ok(True)

    # ------------------------------------------------------------------
    # Job
    # ------------------------------------------------------------------
    @guarded
    def start_scan(self, collection_id, force=False):
        """커버를 먼저 끝내고 나머지 media를 뒤로 미룬다 - 카드 이미지가 먼저 보인다."""
        phases = [
            ("메타데이터+커버", lambda cb: self.workspace.scan(
                collection_id, media_types=["covers"], force=force, progress_cb=cb)),
            ("나머지 미디어", lambda cb: self.workspace.scan(
                collection_id, force=force, progress_cb=cb)),
        ]
        # **후속 job id를 결과에 실어 보낸다.** 단계마다 job이 새로 생기므로, 1단계
        # job만 지켜보면 그것이 끝나는 순간 화면은 "스캔 완료"로 알고 목록을 그린다.
        # 그런데 2단계가 여전히 Cache를 쓰고 있어서, 그 직후 보이는 개수가 실행할
        # 때마다 다르다(실제 백업에서 1,539 / 1,533 / 1,519로 흔들렸다).
        job_id = self.jobs.run_phased((collection_id,), phases, kind="scan",
                                      attach_followup_job_id=True)
        return ok({"jobId": job_id})

    @guarded
    def get_job_progress(self, job_id):
        job = self.jobs.get(job_id)
        return ok(job) if job else err("작업을 찾을 수 없습니다.")

    @guarded
    def cancel_job(self, job_id):
        return ok(self.jobs.cancel(job_id))

    # ------------------------------------------------------------------
    # 환경
    # ------------------------------------------------------------------
    @guarded
    def media_types(self):
        return ok([{"key": k, "label": MEDIA_LABELS.get(k, k)} for k in MEDIA_TYPES])

    @guarded
    def frontends(self):
        from adapters import available
        return ok([{"id": a.id, "label": a.display_name,
                    "mediaTypes": list(a.media_types)} for a in available()])

    @guarded
    def adapter_actions(self, collection_id):
        """이 Collection의 Frontend가 제공하는 고유 기능 목록(§22).

        Storage 같은 일반 기능으로 올리지 않는다 - ES-DE의 custom systems XML은
        ES-DE의 사정이고, 다른 Frontend는 같은 문제를 다른 방식으로 푼다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        adapter = get_adapter(collection.frontend)
        return ok([{"id": a.id, "label": a.label} for a in adapter.extras()])

    @guarded
    def run_adapter_action(self, collection_id, action_id, storage_id=None):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        adapter = get_adapter(collection.frontend)
        if action_id not in {a.id for a in adapter.extras()}:
            return err("이 Frontend가 지원하지 않는 기능입니다.")
        if action_id == getattr(adapter, "CUSTOM_SYSTEMS_ACTION", None):
            # storage_id를 주면 그 Storage만 대상으로 한다(실사용 피드백 - External이
            # 여러 개일 때 어느 그룹에서 눌러도 전체를 다시 쓰는 것은 의도와 다르다).
            result = adapter.write_custom_systems(collection, storage_id=storage_id)
            if result.get("error"):
                return err(result["error"])
            return ok(result)
        return err("아직 구현되지 않은 기능입니다.")

    # ------------------------------------------------------------------
    # RetroArch 실행 (app/launch/retroarch.py)
    # ------------------------------------------------------------------
    #: 설정은 앱 전역 Settings의 `emulator` 섹션에 둔다.
    #:   retroarchPath, coresDir - Settings 화면이 바로 고친다.
    #:   systemCores {system: core파일명}, gameCores {"system/파일명": core파일명} - 아래 메서드로만
    #:   고친다. save_app_settings는 한 단계 깊이까지만 병합하므로, 화면이 dict 일부만 보내면
    #:   나머지가 지워진다 - 그래서 여기서 읽고 고쳐서 통째로 쓴다.
    def _emulator(self):
        stored = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("emulator") or {}
        return {
            "retroarchPath": str(stored.get("retroarchPath") or ""),
            "coresDir": str(stored.get("coresDir") or ""),
            "systemCores": dict(stored.get("systemCores") or {}),
            "gameCores": dict(stored.get("gameCores") or {}),
        }

    @staticmethod
    def _game_core_key(system, filename):
        #: 게임 단위 Core는 System+파일명으로 기억한다. rom_uid는 다시 스캔하면 바뀌고, 같은 ROM을
        #: 다른 Collection에서 열어도 같은 Core로 실행되는 편이 자연스럽다.
        return f"{str(system or '').lower()}/{filename}"

    def _system_core(self, emulator, frontend, system):
        cores = emulator["systemCores"]
        key = str(system or "").lower()
        return cores.get(key) or cores.get(str(normalize_system(frontend, key)).lower())

    @guarded
    def retroarch_settings(self):
        emulator = self._emulator()
        return ok({**emulator, "cores": retroarch.list_cores(emulator["coresDir"]),
                   "unverified": sorted(retroarch.UNVERIFIED_SYSTEMS)})

    @guarded
    def set_retroarch_paths(self, retroarch_path, cores_dir):
        self.save_app_settings({"emulator": {"retroarchPath": str(retroarch_path or "").strip(),
                                             "coresDir": str(cores_dir or "").strip()}})
        return self.retroarch_settings()

    @guarded
    def set_system_core(self, system, core):
        """System 기본 Core. core가 비면 지정을 지운다. cores 폴더에 없는 파일은 거절한다."""
        key = str(system or "").strip().lower()
        if not key:
            return err("System이 필요합니다.")
        emulator = self._emulator()
        if core:
            if core not in retroarch.list_cores(emulator["coresDir"]):
                return err(f"Core 폴더에 없는 파일입니다: {core}")
            emulator["systemCores"][key] = core
        else:
            emulator["systemCores"].pop(key, None)
        self.save_app_settings({"emulator": {"systemCores": emulator["systemCores"]}})
        return ok(emulator["systemCores"])

    @guarded
    def set_game_core(self, system, filename, core):
        """이 게임에만 쓸 Core(System 기본값보다 우선). core가 비면 지정을 지운다."""
        if not system or not filename:
            return err("System과 파일명이 필요합니다.")
        emulator = self._emulator()
        key = self._game_core_key(system, filename)
        if core:
            if core not in retroarch.list_cores(emulator["coresDir"]):
                return err(f"Core 폴더에 없는 파일입니다: {core}")
            emulator["gameCores"][key] = core
        else:
            emulator["gameCores"].pop(key, None)
        self.save_app_settings({"emulator": {"gameCores": emulator["gameCores"]}})
        return ok(emulator["gameCores"])

    @guarded
    def apply_default_cores(self, systems):
        """아직 Core가 없는 System에 알려진 기본 Core를 채운다. 이미 정한 것은 덮어쓰지 않는다."""
        emulator = self._emulator()
        available = retroarch.list_cores(emulator["coresDir"])
        if not available:
            return err("Core 폴더가 없거나 비어 있습니다. Settings > Emulator에서 Core 폴더를 지정하세요.")
        applied = retroarch.default_cores_for(systems or [], available, emulator["systemCores"])
        if applied:
            self.save_app_settings({"emulator": {"systemCores": {**emulator["systemCores"], **applied}}})
        return ok({"applied": applied, "count": len(applied)})

    #: Archive 항목을 실행할 때 collection_id 자리에 쓰는 값.
    ARCHIVE_TARGET = "archive"

    def _launch_target(self, collection_id, rom_uid):
        """실행 대상 하나를 (frontend, system, filename, rom_path, present)로 푼다.

        **Archive 항목도 ROM 위치가 기록돼 있으면 실행할 수 있다** - 예전에는 화면이
        Archive라는 이유만으로 막았다. 실행에 필요한 것은 ROM 파일이 실제로 있느냐뿐이고
        그것은 항목이 어디 속하든 같다.
        """
        if collection_id == self.ARCHIVE_TARGET:
            identity = self.archive.get_identity(str(rom_uid))
            if identity is None:
                raise WorkspaceError("항목을 찾을 수 없습니다.")
            filename = identity["filename"] or identity["filename_norm"]
            rom_path = next((Path(src["abs_path"]) for src in self.archive.rom_sources(identity["rom_identity_id"])
                             if Path(src["abs_path"]).is_file()), None)
            return {"frontend": self._archive_config()["frontend"], "system": identity["system"],
                    "filename": filename, "rom_path": rom_path, "present": rom_path is not None}
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            raise WorkspaceError("Collection을 찾을 수 없습니다.")
        row = self.workspace.open(collection_id).get_row(int(rom_uid))
        if row is None:
            raise WorkspaceError("항목을 찾을 수 없습니다.")
        layout = get_adapter(collection.frontend).layout(collection, row["system"])
        return {"frontend": collection.frontend, "system": row["system"],
                "filename": row["filename"], "rom_path": Path(layout.rom_dir) / row["filename"],
                "present": bool(row["present"])}

    @guarded
    def retroarch_game_info(self, collection_id, rom_uid):
        """Core 선택 창에 필요한 것 - 이 게임의 System 기본값/게임 지정/설치된 Core 목록."""
        target = self._launch_target(collection_id, rom_uid)
        emulator = self._emulator()
        system_core = self._system_core(emulator, target["frontend"], target["system"])
        game_core = emulator["gameCores"].get(self._game_core_key(target["system"], target["filename"]))
        return ok({
            "system": target["system"], "file": target["filename"], "present": target["present"],
            "verified": retroarch.is_verified(target["system"]),
            "systemCore": system_core, "gameCore": game_core, "effectiveCore": game_core or system_core,
            "cores": retroarch.list_cores(emulator["coresDir"]), "coresDir": emulator["coresDir"],
        })

    @guarded
    def launch_game(self, collection_id, rom_uid):
        """게임을 RetroArch로 실행한다. 실패하면 화면이 다음 동작을 고를 수 있게 errorKind를 준다
        (core_unset/core_missing이면 Core 선택 창, retroarch_missing이면 Settings)."""
        target = self._launch_target(collection_id, rom_uid)
        emulator = self._emulator()
        system, filename, rom_path = target["system"], target["filename"], target["rom_path"]
        if not target["present"]:
            return {"ok": False, "error": "ROM 파일이 없는 항목입니다.", "errorKind": "rom_missing",
                    "system": system}
        core = (emulator["gameCores"].get(self._game_core_key(system, filename))
                or self._system_core(emulator, target["frontend"], system))
        result = retroarch.launch(emulator["retroarchPath"], emulator["coresDir"], core, rom_path, system)
        log.info("RETROARCH_LAUNCH system=%s rom=%s core=%s ok=%s %s", system, rom_path, core,
                 result.ok, result.error or "")
        if result.ok:
            return ok({"launched": True, "core": core})
        return {"ok": False, "error": result.error, "errorKind": result.error_kind, "system": system}

    @guarded
    def pick_file(self, title="", file_types=None, directory=""):
        """파일 하나를 고르는 대화상자(RetroArch 실행 파일 등). pywebview 버전별 인자 차이를 흡수한다."""
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        base = {"file_types": tuple(file_types)} if file_types else {}
        result = None
        for kwargs in ({**base, "directory": directory or ""}, base, {}):
            try:
                result = window.create_file_dialog(webview.OPEN_DIALOG, **kwargs)
                break
            except TypeError:
                continue
        if not result:
            return ok(None)
        return ok(result[0] if isinstance(result, (list, tuple)) else result)

    @guarded
    def pick_folder(self, title=""):
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        result = window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return ok(None)
        return ok(result[0] if isinstance(result, (list, tuple)) else result)

    @guarded
    def window_control(self, action):
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        if action == "minimize":
            window.minimize()
        elif action == "maximize":
            # 전체화면(toggle_fullscreen)이 아니라 **최대화/복원**이다. frameless 창에서는
            # 이 버튼이 네이티브 제목 표시줄의 최대화를 대신하므로, 전체화면으로 들어가
            # 작업 표시줄까지 덮으면 사용자가 빠져나올 방법을 잃는다.
            if self._maximized:
                window.restore()
            else:
                window.maximize()
            self._maximized = not self._maximized
        elif action == "close":
            window._rms_close_confirmed = True
            window.destroy()
        return ok(True)

    @guarded
    def window_resize(self, width, height):
        """창 크기를 바꾼다. frameless 창의 크기 조절 손잡이가 쓴다.

        frameless 창은 네이티브 크기 조절 테두리를 잃는다. 그 스타일을 Win32로
        되붙이는 방법은 창 생성 자체를 불안정하게 만들어 쓰지 않기로 했고, 대신
        UI의 손잡이가 이 메서드를 부른다.
        """
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        window.resize(max(1, int(width)), max(1, int(height)))
        self._maximized = False
        return ok(True)

    @guarded
    def window_set_bounds(self, x, y, width, height):
        """창 위치와 크기를 함께 바꾼다. 위/왼쪽 테두리를 끌 때 쓴다.

        오른쪽/아래는 크기만 바꾸면 되지만, 왼쪽이나 위를 끌면 반대편 모서리가 제자리에
        있어야 하므로 위치도 같이 옮겨야 한다."""
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        window.move(int(x), int(y))
        window.resize(max(1, int(width)), max(1, int(height)))
        self._maximized = False
        return ok(True)

    @guarded
    def default_storage_id(self):
        return ok(STORAGE_INTERNAL)

    @guarded
    def get_copy_engine(self):
        """지금 어떤 엔진으로 파일을 옮기는지. 백신 문제로 바꿔야 할 때 쓴다."""
        from engines.robocopy_engine import robocopy_available
        return ok({
            "setting": self.registry.get_setting("copy_engine", file_ops.ENGINE_AUTO),
            "active": file_ops.active_engine_name(),
            "robocopyAvailable": robocopy_available(),
        })

    @guarded
    def set_copy_engine(self, name):
        if name not in (file_ops.ENGINE_AUTO, file_ops.ENGINE_ROBOCOPY, file_ops.ENGINE_WORKER):
            return err(f"알 수 없는 엔진입니다: {name}")
        self.registry.set_setting("copy_engine", name)
        file_ops.select_engine(name)
        return ok({"active": file_ops.active_engine_name()})
