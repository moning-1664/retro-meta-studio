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
import logging
from collections import OrderedDict
import traceback
import time
from pathlib import Path

from adapters import get_adapter
from app import paths
from app.model.collection import STORAGE_INTERNAL
from app.model.constants import MEDIA_TYPES, VIDEO_MEDIA_TYPE, normalize_system
from app import dashboard
from app import media_cleanup
from app import system_ops
from app.launch import retroarch
from app.model.plan import OP_STORAGE_CHANGE, RESOLVE_OVERWRITE, RESOLVE_SKIP, Plan
from app.plan import builder, clipboard
from app.plan.applier import apply_plan
from app.plan.validator import check_capacity, validate
from app.archive import service as archive_service
from app.compare import engine as compare_engine
from app.convert import service as convert_service
from app.match import service as match_service
from app.metadata import service as metadata_service
import storage
from app.store.archive import ArchiveStore
from app.store.registry import CHANGE_APPLIED, RegistryError, RegistryStore
from app.workspace import Workspace, WorkspaceError
from bridge.jobs import JobManager
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


def _sorted_systems(entries, games, *, with_storage=False):
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


def _reveal_path(path):
    """파일 탐색기로 폴더를 연다. 테스트는 이 함수를 바꿔 끼운다."""
    import os
    import subprocess
    import sys
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - 사용자가 고른 Collection 폴더다
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


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
        # 썸네일 캐시(LRU). 파일이 그대로면 인코딩 결과도 그대로다.
        self._thumb_cache: OrderedDict = OrderedDict()
        self._clipboard_dir = (Path(cache_dir).parent / "clipboard") if cache_dir else paths.CLIPBOARD_DIR
        archive_path = (Path(cache_dir).parent / "archive.db") if cache_dir else paths.ARCHIVE_DB
        self.archive = ArchiveStore(archive_path)
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

    def close(self):
        """앱 종료. 진행 중인 작업을 먼저 멈춘 뒤에 DB를 닫는다.

        워커 스레드가 쓰고 있는 sqlite 연결을 닫으면 프로세스가 죽는다. 시간 안에
        멈추지 못한 작업이 남아 있으면 연결을 닫지 않고 그대로 둔다 - 어차피 프로세스가
        끝나면서 정리되고, 크래시로 끝나는 것보다 낫다.
        """
        self._media_server.stop()
        if not self.jobs.shutdown(timeout=5.0):
            return
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
    def create_collection(self, name, frontend, root_path=None, target=None, arch=None,
                          rom_path=None, media_path=None):
        """`root_path`는 메타데이터가 있는 곳, `rom_path`는 ROM이 있는 곳이다.

        ES-DE는 이 둘을 떼어 놓는 것이 기본이라 하나만 받으면 반쪽짜리 Collection만
        만들 수 있다(§9). **둘 다 선택 사항이다** - 스크래핑을 한 번도 안 한 사용자는
        ROM만 가지고 있고, 그것도 정상적인 Collection이다. 유효하지 않은 것은 둘 다
        비어 있을 때뿐이며, 그 판단은 Workspace가 한다.
        """
        collection = self.workspace.create_collection(
            name, frontend, root_path, target=target or None, arch=arch or None,
            rom_path=rom_path or None, media_path=media_path or None)
        return ok(self._collection_summary(collection))

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
            })

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
            "systems": _sorted_systems(collection.systems, games, with_storage=True),
            "totalGames": cache.count_rows(),
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
    #: Collection → Collection 복사(붙여넣기) 정책의 기본값. Settings > Import / Export가 바꾼다.
    #: conflict가 "ask"면 지금처럼 Plan에 충돌로 남겨 사용자가 고른다.
    #: unmatchedRom*은 **원본에 ROM 파일이 없는 항목**(Archive처럼 메타데이터만 있는 항목)의
    #: 처리 방식이다(사용자 결정) - 기본은 아무것도 복사하지 않고, 켜면 Metadata/Media/Video를
    #: 독립적으로 고른다. registry에는 평평하게 저장한다 - "transfer" 섹션 patch는 한 단계
    #: 깊이까지만 병합되므로(save_app_settings), 중첩 객체로 두면 필드 하나만 바꿔도 나머지가
    #: 지워진다.
    TRANSFER_DEFAULTS = {
        "includeRom": True, "includeMedia": True, "conflict": "ask",
        "unmatchedRomMode": "skip",
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
        self.registry.set_setting(self.APP_SETTINGS_KEY, merged)
        return ok(merged)

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
        cache = self.workspace.open(collection_id)
        provider = self.workspace.provider_for(collection)
        return ok(dashboard.validate_collection(collection, get_adapter(collection.frontend), cache, provider))

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
        self.registry.move_system(collection_id, system, storage_id)
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
    def orphan_metadata_preview(self, collection_id, system):
        """이 System에서 Metadata/Media는 있는데 **ROM 파일이 없는** 항목들(System
        우클릭 > ROM 없는 항목 정리). 목록에서 파일명이 흐리게 보이는 것과 같은 기준
        (row.present)이다.
        """
        collection, cache, _provider, _adapter = self._system_context(collection_id)
        if not any(entry.system == system for entry in collection.systems):
            return err(f"System을 찾을 수 없습니다: {system}")
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
        result = media_cleanup.cleanup_media(cache, provider, self.workspace, collection_id,
                                             system, media_types)
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
                  favorites_only=False):
        """가상 스크롤이 요청한 구간만 돌려준다. 정렬/필터/검색은 전부 SQL이 처리한다."""
        cache = self.workspace.open(collection_id)
        query = {"systems": systems or None, "storage_ids": storage_ids or None,
                 "search": search or None, "favorites_only": bool(favorites_only)}
        rows = cache.query_rows(**query, order=order, descending=bool(descending),
                                limit=int(limit), offset=int(offset))
        return ok({"rows": [self._row_summary(r) for r in rows],
                   "total": cache.count_rows(**query), "offset": int(offset)})

    @guarded
    def list_uids(self, collection_id, systems=None, storage_ids=None, search=None,
                  order="title", descending=False, favorites_only=False):
        """지금 목록 전체의 rom_uid(필터·정렬 그대로). Ctrl+A가 쓴다."""
        cache = self.workspace.open(collection_id)
        return ok(cache.query_uids(systems=systems or None, storage_ids=storage_ids or None,
                                   search=search or None, order=order,
                                   descending=bool(descending), favorites_only=bool(favorites_only)))

    @guarded
    def find_row_index(self, collection_id, prefix, after=-1, systems=None, storage_ids=None,
                       search=None, order="title", descending=False, favorites_only=False):
        """영문키 점프: `after` 다음 줄부터 파일명이 `prefix`로 시작하는 줄의 위치(없으면 -1).

        가상 스크롤이라 화면에 그려진 행만 뒤지면 목록 뒤쪽으로 갈 수 없다 - 그래서
        목록 전체를 같은 정렬로 백엔드가 찾는다."""
        cache = self.workspace.open(collection_id)
        return ok(cache.index_of_prefix(prefix, int(after), systems=systems or None,
                                        storage_ids=storage_ids or None, search=search or None,
                                        order=order, descending=bool(descending),
                                        favorites_only=bool(favorites_only)))

    @staticmethod
    def _row_summary(row):
        """Gamelist 한 행. 이전 프로젝트의 컬럼을 그리는 데 필요한 것을 전부 싣는다.

            No. │ File │ Title │ Description │ Region │ Rating │ ★ │ Genre │ Status

        Description이 여기 있는 것이 중요하다 - 이전 프로젝트의 목록은 제목이 아니라
        설명 위주였고, 그래야 어떤 게임인지 목록에서 바로 판단할 수 있다.
        """
        return {
            "romUid": row["rom_uid"], "system": row["system"], "file": row["filename"],
            "title": row["title"], "size": row["size"], "storageId": row["storage_id"],
            "hasMetadata": bool(row["has_metadata"]), "hasMedia": bool(row["has_media"]),
            "present": bool(row["present"]),
            "desc": row["desc_text"] if "desc_text" in row.keys() else "",
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
            stat = Path(path).stat()
        except OSError:
            return None
        return (str(path), stat.st_size, stat.st_mtime_ns, max_size)

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
        path = Path(path)
        if not path.exists():
            return None
        suffix = path.suffix.lower()
        if suffix in (".mp4", ".avi"):
            return None
        try:
            if max_size:
                from PIL import Image
                import io
                with Image.open(path) as image:
                    image.thumbnail((max_size, max_size))
                    buffer = io.BytesIO()
                    # WebP는 같은 화질에서 JPEG보다 작다. 브릿지로 넘어가는 base64
                    # 문자열이 그만큼 짧아지므로 카드가 많을수록 차이가 커진다.
                    image.convert("RGB").save(buffer, format="WEBP", quality=82, method=4)
                    payload, mime = buffer.getvalue(), "image/webp"
            else:
                payload = path.read_bytes()
                mime = {"png": "image/png", "webp": "image/webp"}.get(suffix.lstrip("."), "image/jpeg")
        except Exception:
            # 깨진 이미지 하나가 상세 패널 전체를 막으면 안 된다.
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

        merged = {**row["fields"], **{k: v for k, v in (fields or {}).items()}}
        # frontend_raw는 보통 읽은 그대로 다시 쓴다. 즐겨찾기처럼 사용자가 직접 바꾸는
        # Frontend 고유 값일 때만 새 것이 들어온다.
        raw = row["frontend_raw"] if frontend_raw is None else frontend_raw
        adapter = get_adapter(collection.frontend)
        layout = adapter.layout(collection, row["system"])
        adapter.write_index(layout, [GameEntry(filename=row["filename"], fields=merged,
                                               frontend_raw=raw)])

        title = (merged.get("name") or "").strip() or Path(row["filename"]).stem
        cache.update_metadata(int(rom_uid), merged, title=title, title_norm=normalize_title(title),
                              frontend_raw=None if frontend_raw is None else raw)
        return ok({"title": title})

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
    def plan_state(self, collection_id):
        """Gamelist의 Status 기호와 하단 바가 필요로 하는 것."""
        plan = self._plan(collection_id)
        collection, cache, provider = self._plan_context(collection_id)
        return ok({
            **plan.summary(),
            "marks": plan.marks(),
            "capacity": check_capacity(plan, collection, cache, provider),
            "clipboard": clipboard.peek(self.registry),
            # 사용자가 결정해야 하는 것과 지난 Apply에서 실패한 것을 명확히 노출한다.
            # 이게 안 보이면 "Apply 했으니 끝났다"고 오해한다.
            "conflictEntries": [self._entry_summary(e) for e in plan.conflict_entries()],
            "failedEntries": [self._entry_summary(e) for e in plan.failed_entries()],
            # Navigator가 드래그로 옮긴 System을 Apply 전에도 목표 Storage 밑에
            # 미리 보여주려면 어디로 갈 예정인지 알아야 한다(실사용 피드백 - 예전엔
            # Apply할 때까지 원래 자리에 그대로 있어서 "드래그가 안 먹혔다"처럼 보였다).
            "pendingMoves": {e.system: e.storage_to for e in plan.entries if e.op == OP_STORAGE_CHANGE},
        })

    @staticmethod
    def _entry_summary(entry):
        return {
            "key": entry.key, "op": entry.op, "system": entry.system,
            "filename": entry.filename or entry.system,
            "status": entry.status, "error": entry.error,
            "resolution": entry.resolution,
            "conflicts": entry.conflicts,
        }

    @guarded
    def plan_resolve_conflict(self, collection_id, key, resolution):
        """충돌 항목을 어떻게 처리할지 정한다: skip(그대로 둠) 또는 overwrite(덮어씀).

        덮어쓰기를 고르면 용량 계산이 "새 파일 크기 전부"가 아니라 기존 파일과의
        차이로 다시 계산된다.
        """
        collection, _, provider = self._plan_context(collection_id)
        result = builder.resolve_conflict(self._plan(collection_id), collection, provider,
                                          key, resolution)
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
    def plan_delete(self, collection_id, rom_uids):
        collection, cache, provider = self._plan_context(collection_id)
        result = builder.plan_delete(self._plan(collection_id), collection, cache, rom_uids,
                                     provider)
        return ok(result)

    @guarded
    def plan_storage_change(self, collection_id, system, storage_to):
        collection, cache, _ = self._plan_context(collection_id)
        result = builder.plan_storage_change(self._plan(collection_id), collection, cache,
                                             system, storage_to)
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
    def paste(self, collection_id):
        """붙여넣기. **Settings의 복사 정책(transfer)을 따른다.**

        - ROM/Media를 빼기로 했으면 Plan에 올리기 전에 그 부분을 뺀다(메타데이터는 늘 간다).
        - **원본에 ROM 파일이 없는 항목**(unmatched - Archive처럼 메타데이터만 있는 항목)은
          `unmatchedRom` 정책을 따로 적용한다. 기본은 아무것도 복사하지 않고 건너뛴다.
          "복사"를 골랐으면 Metadata/Media/Video를 독립적으로 골라 그것만 담는다.
        - 충돌 기본 처리가 skip/overwrite면 **이번 붙여넣기로 생긴 충돌만** 그렇게 정한다.
          원래 Plan에 있던 충돌은 사용자가 고를 몫이라 건드리지 않는다.
        """
        collection, _, provider = self._plan_context(collection_id)
        descriptor, items = clipboard.read_items(self.registry)
        if not items:
            return err("붙여넣을 항목이 없습니다.")
        policy = self._transfer_policy()
        unmatched = policy["unmatchedRom"]

        prepared, extra_skipped = [], []
        for item in items:
            if item.get("rom"):
                prepared.append({**item,
                                 "rom": item["rom"] if policy["includeRom"] else None,
                                 "media": item.get("media") if policy["includeMedia"] else []})
                continue
            # ROM 미매칭 - 이 항목의 원본에는 애초에 ROM 파일이 없었다(unmatchedRom, 사용자 결정).
            if unmatched["mode"] != "copy":
                extra_skipped.append({"filename": item["filename"], "reason": "ROM 미매칭 - 정책에 따라 건너뜀"})
                continue
            media = []
            for m in item.get("media") or []:
                wanted = unmatched["video"] if m.get("type") == VIDEO_MEDIA_TYPE else unmatched["media"]
                if wanted:
                    media.append(m)
            fields = item.get("fields") if unmatched["metadata"] else {}
            if not unmatched["metadata"] and not media:
                extra_skipped.append({"filename": item["filename"], "reason": "ROM 미매칭 - 정책에 따라 건너뜀"})
                continue
            prepared.append({**item, "fields": fields, "media": media})

        if not prepared:
            return ok({"added": 0, "skipped": extra_skipped, "conflicts": 0,
                      "source": descriptor.get("sourceName"), "policy": policy})

        plan = self._plan(collection_id)
        result = builder.plan_add(plan, collection, provider, prepared)
        keys = result.pop("conflictKeys", [])
        if policy["conflict"] in (RESOLVE_SKIP, RESOLVE_OVERWRITE):
            for key in keys:
                builder.resolve_conflict(plan, collection, provider, key, policy["conflict"])
            result["autoResolved"] = len(keys)
            result["conflicts"] = 0
        result["skipped"] = [*extra_skipped, *result.get("skipped", [])]
        return ok({**result, "source": descriptor.get("sourceName"), "policy": policy})

    def _transfer_policy(self):
        stored = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("transfer") or {}
        merged = {**self.TRANSFER_DEFAULTS, **{k: v for k, v in stored.items() if k in self.TRANSFER_DEFAULTS}}
        conflict = merged["conflict"] if merged["conflict"] in ("ask", RESOLVE_SKIP, RESOLVE_OVERWRITE) else "ask"
        mode = merged["unmatchedRomMode"] if merged["unmatchedRomMode"] in ("skip", "copy") else "skip"
        return {
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
        report = validate(plan, collection, cache, provider)
        if report["blocked"]:
            return err("용량이 부족합니다. Plan을 줄이거나 저장 공간을 확보해주세요.")

        lock_name = f"apply:{collection_id}"
        if not self.registry.acquire_lock(lock_name, kind="apply"):
            owner = self.registry.lock_owner(lock_name) or {}
            return err(f"다른 창에서 같은 Collection을 적용하는 중입니다({owner.get('instance_id', '?')[:8]}).")

        def run(cb):
            try:
                result = apply_plan(plan, collection, cache, self.registry, provider, progress_cb=cb)
                # Apply가 건드린 System만 다시 읽어 Cache를 실제 상태에 맞춘다.
                # 이걸 안 하면 방금 지운 게임이 목록에 남고 용량도 예전 값이 보인다.
                # 전체 Full Scan은 규모가 커지면 감당이 안 되므로 범위를 좁힌다.
                if result.get("systems"):
                    self.workspace.scan(collection_id, force=True, systems=result["systems"])
                self.registry.append_change(CHANGE_APPLIED, collection_id,
                                            {"applied": result["applied"]})
                return result
            finally:
                self.registry.release_lock(lock_name)

        job_id = self.jobs.run_phased((collection_id,), [("적용", run)], kind="apply")
        return ok({"jobId": job_id})

    # ------------------------------------------------------------------
    # Archive (스펙 §37-44)
    # ------------------------------------------------------------------
    @guarded
    def archive_ingest(self, collection_id, rom_uids=None, scope=None):
        """동기 수집. 프로그램 호출과 테스트용이다.

        **화면은 이 경로를 쓰지 않는다** - GUI는 `start_archive_ingest()`로 scope를
        명시해서 부른다. 여기서 `rom_uids=None`을 전체로 보는 것은 호출부가 대상을
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
    def start_archive_ingest(self, collection_id, scope=None):
        """Collection의 항목을 Archive에 수집한다. 출처는 Collection ID로 남는다.

        **대상은 화면이 준 scope로만 정한다**(§13). 예전에는 선택이 없으면 `None`을
        보냈고 백엔드가 그것을 "Collection 전체"로 해석해서, MSX1만 보고 있던 사용자가
        Collection 전체를 Archive에 넣게 되었다.

        수집은 게임 수만큼 DB 쓰기가 일어나므로 job으로 돌린다 - 동기로 부르면 큰
        Collection에서 창이 멈춘 것처럼 보이고 취소할 방법도 없다.
        """
        collection, cache, _ = self._plan_context(collection_id)
        kind, uids = archive_service.resolve_scope(cache, scope)
        log.info("archive ingest requested: collection=%s scope=%s system=%s targets=%d",
                 collection_id, kind, (scope or {}).get("system"), len(uids))

        def run(cb):
            result = archive_service.ingest_collection(
                self.archive, collection, cache, uids, progress_cb=cb)
            log.info("archive ingest done: scope=%s requested=%d ingested=%d",
                     kind, len(uids), len(result["ingestedRomUids"]))
            return {**result, "scope": kind}

        job_id = self.jobs.run_heavy(run, mutates_state=True, target_ids=(collection_id,),
                                     kind="archive-ingest")
        return ok({"jobId": job_id, "count": len(uids), "scope": kind})

    @guarded
    def archive_rows(self, search=None, systems=None, limit=200, offset=0):
        """Archive Gamelist. Collection 목록과 같은 모양으로 돌려준다(§43).

        Description/Genre/Rating은 `rom_identities`가 아니라 Revision의
        `fields_json`에 있다 - 여기서 안 채우면 화면은 Metadata 탭에는 값이
        보이는데 목록의 Description 칸만 늘 비어 있게 된다. Detail이 보여주는
        값과 같아야 하므로 `resolve_fields()`로 같은 우선순위(Preferred →
        Archive 편집 → Latest)를 쓴다.
        """
        query = {"search": search or None, "systems": systems or None}
        rows = self.archive.list_rows(**query, limit=int(limit), offset=int(offset))
        out_rows = []
        for r in rows:
            fields, _ = self.archive.resolve_fields(r["rom_identity_id"])
            out_rows.append({
                "romUid": r["rom_identity_id"], "romIdentityId": r["rom_identity_id"],
                "system": r["system"], "file": r["filename"], "title": r["title"],
                "sources": r["source_count"], "updatedAt": r["updated_at"],
                # 예전에는 False로 박아뒀다. Archive에 media가 저장돼 있어도
                # 목록에서는 영영 없는 것으로 보였다.
                "hasMetadata": True, "hasMedia": bool(r["media_count"]),
                "present": True, "size": 0,
                "storageId": "archive",
                "desc": fields.get("desc") or "",
                "region": r["region"] or fields.get("region") or "",
                "genre": fields.get("genre") or "",
                "rating": fields.get("rating") or "",
            })
        return ok({
            "rows": out_rows,
            "total": self.archive.count_rows(**query), "offset": int(offset),
        })

    @guarded
    def archive_systems(self):
        return ok(self.archive.systems())

    @guarded
    def archive_detail(self, rom_identity_id):
        data = archive_service.detail(self.archive, rom_identity_id)
        return ok(data) if data else err("Archive 항목을 찾을 수 없습니다.")

    @guarded
    def get_archive_media_image(self, rom_identity_id, media_label, thumbnail=False):
        """Archive 항목의 media 이미지.

        Collection용 `get_media_image()`는 `collection_id` + `rom_uid`로 Cache를 뒤진다.
        Archive에는 그 둘 다 없다(식별자가 rom_identity_id다). 그래서 화면이 Archive
        탭에서도 Collection용 경로를 부르고 있었고, 조회가 조용히 실패해서 **Archive에
        media가 저장되어 있는데도 영영 보이지 않았다.**

        Archive는 파일을 복제하지 않고 원본 경로만 들고 있으므로(§37, D3), 그 경로가
        사라졌으면 그 media만 건너뛴다.
        """
        media_type = MEDIA_KEYS.get(media_label, str(media_label).lower())
        item = next((m for m in self.archive.media_refs(rom_identity_id)
                     if m["media_type"] == media_type), None)
        if item is None:
            return ok(None)
        return ok(self._encode_image(item["abs_path"], THUMBNAIL_MAX if thumbnail else None))

    @guarded
    def get_archive_media_video_url(self, rom_identity_id):
        """Archive 항목의 영상 URL. Archive는 원본 경로만 들고 있으므로 그 파일이 사라졌으면 None."""
        item = next((m for m in self.archive.media_refs(rom_identity_id)
                     if m["media_type"] == VIDEO_MEDIA_TYPE), None)
        url = self._media_server.url_for(item["abs_path"]) if item else None
        return ok({"url": url} if url else None)

    @guarded
    def archive_edit(self, rom_identity_id, fields):
        """Archive의 Metadata를 고친다. **Collection에는 반영되지 않는다**(§40)."""
        return ok(archive_service.edit(self.archive, rom_identity_id, fields))

    @guarded
    def archive_revisions(self, rom_identity_id, source_collection_id):
        """한 출처의 Revision 이력(ARCHIVE_REVISION_POLICY.md §14 Revision History)."""
        return ok(self.archive.revisions_of(rom_identity_id, source_collection_id))

    @guarded
    def archive_set_preferred(self, rom_identity_id, record_id):
        """이 Revision을 Preferred로 지정한다(정책 §8). 내용은 바뀌지 않는다."""
        return ok(archive_service.set_preferred(self.archive, rom_identity_id, int(record_id)))

    @guarded
    def archive_clear_preferred(self, rom_identity_id):
        return ok(archive_service.clear_preferred(self.archive, rom_identity_id))

    @guarded
    def archive_to_collection(self, collection_id, rom_identity_ids):
        """Archive 항목을 Collection으로 보낸다(§41).

        이미 있는 항목은 메타데이터만 즉시 반영하고(D1), 없는 항목은 파일을 옮겨야
        하므로 Plan에 올린다.
        """
        collection, cache, provider = self._plan_context(collection_id)
        result = archive_service.to_collection(self.archive, collection, cache, provider,
                                               rom_identity_ids)
        added = {"added": 0, "skipped": [], "conflicts": 0}
        if result["items"]:
            added = builder.plan_add(self._plan(collection_id), collection, provider,
                                     result["items"])
        return ok({
            "updated": result["updated"],
            "planned": added["added"], "conflicts": added.get("conflicts", 0),
            "skipped": result["skipped"] + added.get("skipped", []),
        })

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
    def start_convert(self, source_collection_id, target_collection_id):
        """변환 결과를 target의 Plan에 올린다. Auto Plan이 꺼져 있어도 여기서는
        파일을 건드리지 않는다 - 확정은 언제나 Apply의 몫이다."""
        if source_collection_id == target_collection_id:
            return err("같은 Collection으로는 변환할 수 없습니다.")
        source = self.registry.get_collection(source_collection_id)
        if source is None:
            return err("원본 Collection을 찾을 수 없습니다.")
        source_cache = self.workspace.open(source_collection_id)
        target, _cache, provider = self._plan_context(target_collection_id)
        result = convert_service.plan_convert(self._plan(target_collection_id), source,
                                              source_cache, target, provider)
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

    @staticmethod
    def _compare_row_summary(row):
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
            "leftRomUid": (row["left"] or {}).get("romUid"),
            "rightRomUid": (row["right"] or {}).get("romUid"),
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
            "mediaDiff": row["mediaDiff"],
            "baseName": state["baseName"], "otherName": state["otherName"],
            "left": row["left"], "right": row["right"],
        })

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
    def run_adapter_action(self, collection_id, action_id):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        adapter = get_adapter(collection.frontend)
        if action_id not in {a.id for a in adapter.extras()}:
            return err("이 Frontend가 지원하지 않는 기능입니다.")
        if action_id == getattr(adapter, "CUSTOM_SYSTEMS_ACTION", None):
            return ok(adapter.write_custom_systems(collection))
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

    def _launch_target(self, collection_id, rom_uid):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            raise WorkspaceError("Collection을 찾을 수 없습니다.")
        row = self.workspace.open(collection_id).get_row(int(rom_uid))
        if row is None:
            raise WorkspaceError("항목을 찾을 수 없습니다.")
        return collection, row

    @guarded
    def retroarch_game_info(self, collection_id, rom_uid):
        """Core 선택 창에 필요한 것 - 이 게임의 System 기본값/게임 지정/설치된 Core 목록."""
        collection, row = self._launch_target(collection_id, rom_uid)
        emulator = self._emulator()
        system_core = self._system_core(emulator, collection.frontend, row["system"])
        game_core = emulator["gameCores"].get(self._game_core_key(row["system"], row["filename"]))
        return ok({
            "system": row["system"], "file": row["filename"], "present": bool(row["present"]),
            "verified": retroarch.is_verified(row["system"]),
            "systemCore": system_core, "gameCore": game_core, "effectiveCore": game_core or system_core,
            "cores": retroarch.list_cores(emulator["coresDir"]), "coresDir": emulator["coresDir"],
        })

    @guarded
    def launch_game(self, collection_id, rom_uid):
        """게임을 RetroArch로 실행한다. 실패하면 화면이 다음 동작을 고를 수 있게 errorKind를 준다
        (core_unset/core_missing이면 Core 선택 창, retroarch_missing이면 Settings)."""
        collection, row = self._launch_target(collection_id, rom_uid)
        emulator = self._emulator()
        if not row["present"]:
            return {"ok": False, "error": "ROM 파일이 없는 항목입니다.", "errorKind": "rom_missing",
                    "system": row["system"]}
        layout = get_adapter(collection.frontend).layout(collection, row["system"])
        rom_path = Path(layout.rom_dir) / row["filename"]
        core = (emulator["gameCores"].get(self._game_core_key(row["system"], row["filename"]))
                or self._system_core(emulator, collection.frontend, row["system"]))
        result = retroarch.launch(emulator["retroarchPath"], emulator["coresDir"], core, rom_path, row["system"])
        log.info("RETROARCH_LAUNCH system=%s rom=%s core=%s ok=%s %s", row["system"], rom_path, core,
                 result.ok, result.error or "")
        if result.ok:
            return ok({"launched": True, "core": core})
        return {"ok": False, "error": result.error, "errorKind": result.error_kind, "system": row["system"]}

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
